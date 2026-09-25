"""One collection run against Epic's public API. Committed data is append-only; the working
state (live checks, sparklines, island metadata) lives in .state/ and is rebuilt if lost."""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from epic import EpicAPI, OutOfTime
from store import append_rows, atomic_write, load_state, parse_time, read_table, save_state, utc_text

ISLAND_FIELDS = ["first_seen", "code", "title", "creator", "created_in", "category", "tags", "source"]
RANKING_FIELDS = ["hour", "genre", "rank", "code"]
LAUNCH_FIELDS = ["stage", "code", "first_seen", "measured_to", "points", "peak_ccu", "peak_at", "pickup_at",
                 "hours_to_pickup", "plays", "minutes_played", "favorites", "recommendations",
                 "unique_players", "avg_minutes", "d1", "d7", "best_rank", "best_rank_genre"]
CURVE_FIELDS = ["code", "hour", "ccu", "plays"]
PICKUP_FIELDS = ["at", "code", "kind", "age_hours", "ccu_before", "ccu_after"]
DAILY_FIELDS = ["date", "code", "peak_ccu", "plays", "unique_players", "minutes_played", "avg_minutes",
                "favorites", "recommendations", "d1", "d7"]
KEYWORD_FIELDS = ["date", "kind", "term", "islands", "new_7d", "ranked", "unique_players", "plays"]
RUN_FIELDS = ["started", "finished", "requests", "retries", "new_islands", "catalog", "rank_hours",
              "launch_checks", "finals", "established", "notes"]
MINUTE_METRICS = ["peakCCU", "plays", "minutesPlayed", "favorites", "recommendations"]
WINDOW = timedelta(days=7) - timedelta(minutes=10)  # Epic keeps 7 days; stay just inside it.
TERM = re.compile(r"[^\W_]+")
STOPWORDS = {"the", "and", "a", "an", "of", "to", "in", "on", "for", "with", "by", "is", "it", "my", "your",
             "de", "la", "el", "le", "les", "des", "du", "et", "y", "en", "do", "da", "e", "o", "vs", "v"}


# ---------- catalog and new releases ----------

def seed_path(data_dir=None):
    return Path(data_dir or config.DATA_DIR) / "seed_codes.txt"


def known_codes(data_dir=None):
    codes = set()
    path = seed_path(data_dir)
    if path.exists():
        codes.update(line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#"))
    codes.update(row["code"] for row in read_table("islands", data_dir=data_dir))
    return codes


def island_row(item, now, source):
    return dict(first_seen=utc_text(now), code=item["code"], title=(item.get("title") or "").strip(),
                creator=item.get("creatorCode") or "", created_in=item.get("createdIn") or "",
                category=item.get("category") or "", tags="|".join(item.get("tags") or []), source=source)


def crawl_catalog(api):
    items = []
    for page in api.pages("/islands", size=config.LIST_PAGE_SIZE):
        items.extend(item for item in page if item.get("code"))
    return items


def write_seed(items, now, data_dir=None):
    codes = sorted({item["code"] for item in items})
    atomic_write(seed_path(data_dir), f"# Public islands before tracking began at {utc_text(now)}\n"
                 + "\n".join(codes) + "\n")
    return set(codes)


def scan_new(api, known, now):
    """The list is newest release first, so stop at the first page with nothing new."""
    rows = []
    for page in api.pages("/islands", max_pages=config.HEAD_MAX_PAGES, size=config.LIST_PAGE_SIZE):
        fresh = [item for item in page if item.get("code") and item["code"] not in known]
        for item in fresh:
            known.add(item["code"])
            rows.append(island_row(item, now, "head"))
        if not fresh:
            break
    return rows


def title_terms(title, frequent=None):
    """Words and word pairs in a title; 'brain rot' also counts as 'brainrot' when that is a real term."""
    words = [w for w in TERM.findall(title.lower()) if len(w) > 1 and not w.isdigit() and w not in STOPWORDS]
    terms = set(words)
    for first, second in zip(words, words[1:]):
        terms.add(f"{first} {second}")
        if frequent is not None and first + second in frequent:
            terms.add(first + second)
    return terms


def keyword_rows(items, islands, state, now):
    """Supply (islands using a term) against demand (players on ranked islands using it)."""
    new_cutoff = utc_text(now - timedelta(days=7))
    recent = {row["code"] for row in islands if row["first_seen"] >= new_cutoff}
    ranked = set(state.get("ranked", {}).get("codes", {}))
    days = {code: info.get("day") or {} for code, info in state.get("est", {}).items()}
    word_counts = Counter()
    for item in items:
        word_counts.update(t for t in title_terms(item.get("title") or "") if " " not in t)
    frequent = {term for term, count in word_counts.items() if count >= config.KEYWORD_MIN_ISLANDS}
    totals = {}
    for item in items:
        code = item["code"]
        terms = [("word", t) for t in title_terms(item.get("title") or "", frequent)]
        terms += [("tag", t) for t in item.get("tags") or []]
        day = days.get(code, {})
        for key in terms:
            entry = totals.setdefault(key, [0, 0, 0, 0, 0])
            entry[0] += 1
            entry[1] += code in recent
            if code in ranked:
                entry[2] += 1
                entry[3] += day.get("unique_players") or 0
                entry[4] += day.get("plays") or 0
    date = utc_text(now)[:10]
    return [dict(date=date, kind=kind, term=term, islands=v[0], new_7d=v[1], ranked=v[2],
                 unique_players=v[3], plays=v[4])
            for (kind, term), v in sorted(totals.items())
            if kind == "tag" or (v[0] >= config.KEYWORD_MIN_ISLANDS and (v[2] >= 2 or v[1] >= config.KEYWORD_MIN_ISLANDS))]


def remember_meta(state, items, codes):
    meta = state.setdefault("meta", {})
    for item in items:
        if item["code"] in codes:
            meta[item["code"]] = [item.get("title") or "", item.get("creatorCode") or "",
                                  item.get("tags") or [], item.get("createdIn") or "", item.get("category") or ""]


# ---------- genre rankings ----------

def genres(api, state, now):
    cached = state.get("genres")
    if cached and parse_time(cached["at"]) > now - timedelta(hours=24):
        return cached["list"]
    payload = api.get("/genres") or {}
    listing = [[g["slug"], g["displayName"]] for g in payload.get("data") or []]
    if not listing:
        raise RuntimeError("Epic returned no genres")
    state["genres"] = dict(at=utc_text(now), list=listing)
    return listing


def ranking_hours(now, stored, dead):
    latest = now.replace(minute=0, second=0, microsecond=0)
    hours = (latest - timedelta(hours=back) for back in range(1, 7 * 24 - 1))
    return [h for h in hours if utc_text(h) not in stored and utc_text(h) not in dead]


def collect_rankings(api, state, now, data_dir=None):
    listing = genres(api, state, now)
    since = utc_text(now - timedelta(days=8))
    stored = {row["hour"] for row in read_table("rankings", since[:7], data_dir) if row["hour"] >= since}
    dead = set(state.get("dead_rank_hours", []))
    done = 0
    for hour in ranking_hours(now, stored, dead):
        if done >= config.RANKING_HOURS_PER_RUN or not api.has_time(60):
            break
        at = utc_text(hour)
        board = {}
        for index, (slug, _) in enumerate(listing):
            payload = api.get(f"/genres/{slug}/rankings", at=at, size=config.RANKING_TRACK_DEPTH) or {}
            if index == 0 and not (payload.get("meta") or {}).get("total"):
                break  # Snapshot not published yet (Epic lags a few hours).
            board[slug] = [(int(r["rank"]), r["islandCode"]) for r in payload.get("data") or []]
        if not board:
            if hour < now - timedelta(hours=config.RANKING_GIVE_UP_HOURS):
                dead.add(at)
            continue
        append_rows("rankings", RANKING_FIELDS, (dict(hour=at, genre=slug, rank=rank, code=code)
                    for slug, rows in board.items() for rank, code in rows if rank <= config.RANKING_STORE_DEPTH),
                    now, data_dir)
        done += 1
        if at > state.get("ranked", {}).get("hour", ""):
            codes = {}
            for slug, rows in board.items():
                for rank, code in rows:
                    if code not in codes or rank < codes[code][1]:
                        codes[code] = [slug, rank]
            state["ranked"] = dict(hour=at, codes=codes)
    cutoff = utc_text(now - timedelta(days=8))
    state["dead_rank_hours"] = sorted(h for h in dead if h >= cutoff)
    return done


# ---------- metric series helpers ----------

def series_from(payload):
    """{metric: [{value, timestamp}]} -> sorted [(time, {metric: value})]."""
    points = {}
    for metric, values in (payload or {}).items():
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, dict) and "timestamp" in entry:
                slot = points.setdefault(parse_time(entry["timestamp"]), {})
                if metric == "retention":
                    slot["d1"], slot["d7"] = entry.get("d1"), entry.get("d7")
                else:
                    slot[metric] = entry.get("value")
    return sorted(points.items())


def detect_pickup(points, lookback=6):
    """First sudden jump: >= PICKUP_MIN_CCU and >= PICKUP_FACTOR x the prior lookback peak."""
    history = []
    for when, value in points:
        before = max((v or 0 for v in history[-lookback:]), default=0)
        if value is not None and value >= config.PICKUP_MIN_CCU and value >= config.PICKUP_FACTOR * max(before, 1):
            return when, before, value
        history.append(value)
    return None


def total(points, metric):
    values = [m.get(metric) for _, m in points if m.get(metric) is not None]
    return round(sum(values), 2) if values else ""


def launch_summary(series, first_seen, hours):
    end = first_seen + timedelta(hours=hours)
    points = [(t, m) for t, m in series if first_seen - timedelta(minutes=10) < t < end]
    ccu = [(t, m.get("peakCCU")) for t, m in points]
    values = [v for _, v in ccu if v is not None]
    peak = max(values) if values else None
    pickup = detect_pickup(ccu)
    return dict(points=len(values), peak_ccu=peak if peak is not None else "",
                peak_at=next((utc_text(t) for t, v in ccu if v == peak), "") if peak is not None else "",
                pickup_at=utc_text(pickup[0]) if pickup else "",
                hours_to_pickup=round(max(0.0, (pickup[0] - first_seen).total_seconds() / 3600), 2) if pickup else "",
                plays=total(points, "plays"), minutes_played=total(points, "minutesPlayed"),
                favorites=total(points, "favorites"), recommendations=total(points, "recommendations"))


def hourly(series, start, hours):
    """Hourly (max CCU, summed plays) buckets relative to start."""
    buckets = [[None, None] for _ in range(hours)]
    for when, metrics in series:
        index = int((when - start).total_seconds() // 3600)
        if 0 <= index < hours:
            ccu, plays = metrics.get("peakCCU"), metrics.get("plays")
            if ccu is not None:
                buckets[index][0] = max(buckets[index][0] or 0, ccu)
            if plays is not None:
                buckets[index][1] = (buckets[index][1] or 0) + plays
    return buckets


def mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else ""


# ---------- launch tracking ----------

def launch_task(api, row, now, stages_done):
    """Fetch one new island's 10-minute series since release and compute what is due."""
    code, first_seen = row["code"], parse_time(row["first_seen"])
    age = (now - first_seen).total_seconds() / 3600
    start = max(first_seen - timedelta(hours=1), now - WINDOW)
    end = min(now, first_seen + timedelta(hours=config.LAUNCH_WINDOW_HOURS))
    series = series_from(api.get(f"/islands/{code}/metrics/minute", **{"from": utc_text(start), "to": utc_text(end)},
                                 metrics=MINUTE_METRICS))
    result = dict(code=code, first_seen=row["first_seen"], age=age, series=series, rows=[], curve=[])
    base = dict(code=code, first_seen=row["first_seen"])
    if age >= config.EARLY_STAGE_HOURS and "24" not in stages_done:
        summary = launch_summary(series, first_seen, config.EARLY_STAGE_HOURS)
        result["rows"].append(dict(base, stage="24", measured_to=utc_text(first_seen + timedelta(hours=24)), **summary))
    if age >= config.FINAL_AFTER_HOURS and "144" not in stages_done:
        summary = launch_summary(series, first_seen, config.LAUNCH_WINDOW_HOURS)
        extra = dict(unique_players="", avg_minutes="", d1="", d7="", best_rank="", best_rank_genre="")
        if summary["points"]:
            days = series_from(api.get(f"/islands/{code}/metrics/day", **{"from": utc_text(start), "to": utc_text(end)}))
            days = [(t, m) for t, m in days if t < end]
            extra.update(unique_players=total(days, "uniquePlayers"),
                         avg_minutes=mean(m.get("averageMinutesPerPlayer") for _, m in days),
                         d1=mean(m.get("d1") for _, m in days), d7=mean(m.get("d7") for _, m in days))
            ranks = (api.get(f"/islands/{code}/rankings", **{"from": utc_text(start), "to": utc_text(end)}) or {}).get("data") or []
            best = min(((g["rank"], g["genreSlug"]) for snap in ranks for g in snap.get("genres") or []), default=None)
            if best:
                extra.update(best_rank=best[0], best_rank_genre=best[1])
        result["rows"].append(dict(base, stage="144", measured_to=utc_text(end), **summary, **extra))
        if summary["peak_ccu"] != "" and summary["peak_ccu"] >= config.CURVE_MIN_PEAK:
            result["curve"] = [dict(code=code, hour=h, ccu=c if c is not None else "", plays=p if p is not None else "")
                               for h, (c, p) in enumerate(hourly(series, first_seen, config.LAUNCH_WINDOW_HOURS))]
    return result


def due_launches(islands, stages, state, now):
    """(committed rows due: finals first, since they expire with Epic's 7-day window; live checks due)."""
    finals, early, live = [], [], []
    checks = state.get("launch", {})
    for row in islands:
        first_seen = parse_time(row["first_seen"])
        age = (now - first_seen).total_seconds() / 3600
        if age >= 168 or age < 0:
            continue
        done = stages.get(row["code"], set())
        if age >= config.FINAL_AFTER_HOURS and "144" not in done:
            finals.append((-age, row))
        elif age >= config.EARLY_STAGE_HOURS and "24" not in done:
            early.append((-age, row))
        else:
            passed = [h for h in config.LAUNCH_CHECK_HOURS if age >= h]
            if passed and passed[-1] not in checks.get(row["code"], {}).get("checks", []):
                live.append((-age, row))
    ordered = lambda group: [row for _, row in sorted(group, key=lambda x: x[0])]
    return ordered(finals) + ordered(early), ordered(live)


def apply_launch(state, result, now, logged):
    code, series = result["code"], result["series"]
    first_seen = parse_time(result["first_seen"])
    ccu = [(t, m.get("peakCCU")) for t, m in series if t > first_seen - timedelta(minutes=10)]
    values = [v for _, v in ccu if v is not None]
    pickup = detect_pickup(ccu)
    entry = state.setdefault("launch", {}).setdefault(code, {})
    entry.update(at=utc_text(now), peak=max(values) if values else 0,
                 ccu=next((v for _, v in reversed(ccu) if v is not None), 0),
                 pickup=utc_text(pickup[0]) if pickup else None,
                 checks=sorted(set(entry.get("checks", [])) | {h for h in config.LAUNCH_CHECK_HOURS if result["age"] >= h}))
    if values:
        entry["spark"] = [c or 0 for c, _ in hourly(series, first_seen, min(config.LAUNCH_WINDOW_HOURS, int(result["age"]) + 1))]
    if pickup and code not in logged:
        logged.add(code)
        return dict(at=utc_text(pickup[0]), code=code, kind="launch",
                    age_hours=round((pickup[0] - first_seen).total_seconds() / 3600, 2),
                    ccu_before=pickup[1], ccu_after=pickup[2])
    return None


# ---------- established islands ----------

def established_task(api, code, now, need_meta):
    day = series_from(api.get(f"/islands/{code}/metrics/day", **{"from": utc_text(now - WINDOW), "to": utc_text(now)}))
    hours = series_from(api.get(f"/islands/{code}/metrics/hour", **{"from": utc_text(now - timedelta(hours=48)),
                                                                     "to": utc_text(now)}, metrics=["peakCCU"]))
    meta = api.get(f"/islands/{code}") if need_meta else None
    return dict(code=code, day=day, hours=hours, meta=meta)


def apply_established(state, result, now, stored_days, logged_events):
    code = result["code"]
    today = utc_text(now)[:10]
    daily = []
    for when, m in result["day"]:
        date = utc_text(when)[:10]
        if date < today and (date, code) not in stored_days and m.get("peakCCU") is not None:
            stored_days.add((date, code))
            daily.append(dict(date=date, code=code, peak_ccu=m.get("peakCCU"), plays=m.get("plays") or "",
                              unique_players=m.get("uniquePlayers") or "", minutes_played=m.get("minutesPlayed") or "",
                              avg_minutes=m.get("averageMinutesPerPlayer") or "", favorites=m.get("favorites") or "",
                              recommendations=m.get("recommendations") or "",
                              d1=m.get("d1") if m.get("d1") is not None else "",
                              d7=m.get("d7") if m.get("d7") is not None else ""))
    entry = state.setdefault("est", {}).setdefault(code, {})
    last = [(t, m) for t, m in result["day"] if utc_text(t)[:10] < today and m.get("peakCCU") is not None]
    if last:
        m = last[-1][1]
        entry["day"] = dict(date=utc_text(last[-1][0])[:10], peak_ccu=m.get("peakCCU"), plays=m.get("plays"),
                            unique_players=m.get("uniquePlayers"), avg_minutes=m.get("averageMinutesPerPlayer"),
                            d1=m.get("d1"), d7=m.get("d7"), favorites=m.get("favorites"),
                            recommendations=m.get("recommendations"))
    ccu = [(t, m.get("peakCCU")) for t, m in result["hours"]]
    entry.update(at=utc_text(now), spark=[v or 0 for _, v in ccu][-48:])
    events = []
    if len(ccu) > 3:
        # Scan every hour after the first three so each jump is found once, then de-duplicated.
        for i in range(3, len(ccu)):
            found = detect_pickup(ccu[max(0, i - 3):i + 1], lookback=3)
            if found and found[0] == ccu[i][0] and (code, utc_text(found[0])) not in logged_events:
                logged_events.add((code, utc_text(found[0])))
                events.append(dict(at=utc_text(found[0]), code=code, kind="established", age_hours="",
                                   ccu_before=found[1], ccu_after=found[2]))
    if result["meta"]:
        remember_meta(state, [result["meta"]], {code})
    return daily, events


# ---------- run ----------

def run_parallel(api, tasks, errors):
    """Run (callable, args) tasks on a small pool. Tasks cut off by the time budget return None;
    one island failing is counted in errors instead of losing the whole run."""
    def guarded(task):
        function, args = task
        try:
            return function(api, *args)
        except OutOfTime:
            return None
        except (RuntimeError, KeyError, TypeError, ValueError) as error:
            errors.append(f"{args[0] if isinstance(args[0], str) else args[0].get('code')}: {error}")
            return None
    with ThreadPoolExecutor(max_workers=config.WORKERS) as pool:
        return [r for r in pool.map(guarded, tasks) if r is not None]


def run(api, state, now, data_dir=None):
    stats = dict(new_islands=0, catalog="", rank_hours=0, launch_checks=0, finals=0, established=0)
    notes, errors = [], []
    known = known_codes(data_dir)

    if not seed_path(data_dir).exists():
        items = crawl_catalog(api)  # A partial seed would mislabel old islands as new, so this must finish.
        known = write_seed(items, now, data_dir) | known
        # First keyword pass a couple of hours later, once rankings and daily stats exist.
        state["catalog_at"] = utc_text(now - timedelta(hours=config.CATALOG_EVERY_HOURS - 2))
        stats["catalog"] = "seed"

    new_rows = scan_new(api, known, now)
    stats["new_islands"] += append_rows("islands", ISLAND_FIELDS, new_rows, now, data_dir)

    try:
        stats["rank_hours"] = collect_rankings(api, state, now, data_dir)
    except OutOfTime:
        notes.append("rankings cut short")

    week_ago = utc_text(now - timedelta(days=7, hours=1))
    islands = [row for row in read_table("islands", week_ago[:7], data_dir) if row["first_seen"] >= week_ago]
    stages = {}
    for row in read_table("launches", week_ago[:7], data_dir):
        stages.setdefault(row["code"], set()).add(row["stage"])
    logged = {row["code"] for row in read_table("pickups", week_ago[:7], data_dir) if row["kind"] == "launch"}
    logged_events = {(row["code"], row["at"]) for row in read_table("pickups", week_ago[:7], data_dir)}

    def launches(rows):
        results = run_parallel(api, [(launch_task, (row, now, stages.get(row["code"], set()))) for row in rows], errors)
        pickups = [apply_launch(state, result, now, logged) for result in results]
        launch_rows = [r for result in results for r in result["rows"]]
        append_rows("launches", LAUNCH_FIELDS, launch_rows, now, data_dir)
        append_rows("curves", CURVE_FIELDS, (r for result in results for r in result["curve"]), now, data_dir)
        append_rows("pickups", PICKUP_FIELDS, (p for p in pickups if p), now, data_dir)
        for r in launch_rows:
            stages.setdefault(r["code"], set()).add(r["stage"])
        stats["launch_checks"] += len(results)
        stats["finals"] += sum(r["stage"] == "144" for r in launch_rows)

    launches(due_launches(islands, stages, state, now)[0])

    if (not state.get("catalog_at") or parse_time(state["catalog_at"]) <= now - timedelta(hours=config.CATALOG_EVERY_HOURS)) \
            and api.has_time(150):
        try:
            items = crawl_catalog(api)
            late = [island_row(item, now, "catalog") for item in items if item["code"] not in known]
            known.update(row["code"] for row in late)
            stats["new_islands"] += append_rows("islands", ISLAND_FIELDS, late, now, data_dir)
            islands.extend(late)
            remember_meta(state, items, set(state.get("ranked", {}).get("codes", {})))
            append_rows("keywords", KEYWORD_FIELDS, keyword_rows(items, islands, state, now), now, data_dir)
            state["catalog_at"] = utc_text(now)
            stats["catalog"] = f"{len(items)} islands"
        except OutOfTime:
            notes.append("catalog cut short")

    launches(due_launches(islands, stages, state, now)[1])

    launch_codes = {row["code"] for row in islands}
    ranked = state.get("ranked", {}).get("codes", {})
    est = state.get("est", {})
    stale = utc_text(now - timedelta(hours=config.ESTABLISHED_REFRESH_HOURS))
    queue = sorted((code for code in ranked if code not in launch_codes and est.get(code, {}).get("at", "") < stale),
                   key=lambda code: (est.get(code, {}).get("at", ""), ranked[code][1]))  # Stalest, then best ranked.
    meta = state.setdefault("meta", {})
    results = run_parallel(api, [(established_task, (code, now, code not in meta)) for code in queue], errors)
    since = utc_text(now - timedelta(days=8))[:10]
    stored_days = {(row["date"], row["code"]) for row in read_table("daily", since[:7], data_dir) if row["date"] >= since}
    daily_rows, events = [], []
    for result in results:
        rows, found = apply_established(state, result, now, stored_days, logged_events)
        daily_rows += rows
        events += found
    append_rows("daily", DAILY_FIELDS, daily_rows, now, data_dir)
    append_rows("pickups", PICKUP_FIELDS, events, now, data_dir)
    stats["established"] = len(results)
    if len(results) < len(queue):
        notes.append(f"{len(queue) - len(results)} established islands waiting")
    if errors:
        notes.append(f"{len(errors)} island errors, first: {errors[0][:160]}")

    # Forget working state that no longer matters.
    state["launch"] = {c: v for c, v in state.get("launch", {}).items() if c in launch_codes}
    state["est"] = {c: v for c, v in est.items() if c in ranked or v.get("at", "") >= since}
    keep = set(ranked) | set(state["est"])
    state["meta"] = {c: v for c, v in meta.items() if c in keep}
    return stats, notes


def main():
    started = datetime.now(timezone.utc)
    api = EpicAPI()
    state = load_state()
    stats, notes = run(api, state, started)
    save_state(state)
    finished = datetime.now(timezone.utc)
    append_rows("runs", RUN_FIELDS, [dict(started=utc_text(started), finished=utc_text(finished), requests=api.calls,
                                          retries=api.retries, notes="; ".join(notes), **stats)], started)
    print(f"{utc_text(finished)} requests={api.calls} retries={api.retries} " +
          " ".join(f"{k}={v}" for k, v in stats.items()) + (f" notes={'; '.join(notes)}" if notes else ""))


if __name__ == "__main__":
    main()
