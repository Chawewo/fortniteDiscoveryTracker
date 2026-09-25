"""Build dashboard/data.json from committed data plus the working state. Launch timing only uses
islands caught by the newest-first scan ('head'), whose first-seen time is accurate to one run."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import shutil
from statistics import median

import config
from store import atomic_write, load_state, parse_time, read_table, utc_text

TOP_TAG_GRIDS = 15


def number(value):
    if value in ("", None):
        return None
    value = float(value)
    return int(value) if value.is_integer() else value


def hour_of_week(stamp):
    """UTC Monday 00:00 = 0 ... Sunday 23:00 = 167."""
    moment = parse_time(stamp)
    return moment.weekday() * 24 + moment.hour


def outcomes(launch_rows):
    """code -> {'24': row, '144': row}, keeping the latest row per stage."""
    result = defaultdict(dict)
    for row in launch_rows:
        result[row["code"]][row["stage"]] = row
    return result


def timing_grids(islands, by_code):
    """Per hour-of-week counts: [n24, took24, pick24, n144, took144, pick144, median h to pickup, median peak]."""
    groups = defaultdict(lambda: [[0, 0, 0, 0, 0, 0, [], []] for _ in range(168)])
    tag_counts = Counter()
    for island in islands:
        if island["source"] != "head" or island["code"] not in by_code:
            continue
        stages = by_code[island["code"]]
        tags = [t for t in island["tags"].split("|") if t]
        tag_counts.update(tags)
        keys = ["all", island["created_in"] or "unknown"] + [f"tag:{t}" for t in tags]
        slot = hour_of_week(island["first_seen"])
        early, final = stages.get("24"), stages.get("144")
        for key in keys:
            cell = groups[key][slot]
            if early:
                peak = number(early["peak_ccu"]) or 0
                cell[0] += 1
                cell[1] += peak >= config.TRACTION_CCU
                cell[2] += bool(early["pickup_at"])
            if final:
                peak = number(final["peak_ccu"]) or 0
                cell[3] += 1
                cell[4] += peak >= config.TRACTION_CCU
                cell[5] += bool(final["pickup_at"])
                if final["hours_to_pickup"]:
                    cell[6].append(float(final["hours_to_pickup"]))
                if peak:
                    cell[7].append(peak)
    keep = {"all", "UEFN", "FNC"} | {f"tag:{t}" for t, _ in tag_counts.most_common(TOP_TAG_GRIDS)}
    return {key: [c[:6] + [round(median(c[6]), 1) if c[6] else None, median(c[7]) if c[7] else None] for c in cells]
            for key, cells in groups.items() if key in keep}


def success_table(islands, by_code):
    """Take-off and pickup rates by tag and build tool, from finished 6-day outcomes."""
    rows = defaultdict(lambda: [0, 0, 0, []])
    for island in islands:
        final = by_code.get(island["code"], {}).get("144")
        if not final:
            continue
        peak = number(final["peak_ccu"]) or 0
        tags = [t for t in island["tags"].split("|") if t]
        for key in [("tool", island["created_in"] or "unknown"), ("tags", str(min(len(tags), 4)))] + [("tag", t) for t in tags]:
            entry = rows[key]
            entry[0] += 1
            entry[1] += peak >= config.TRACTION_CCU
            entry[2] += bool(final["pickup_at"])
            entry[3].append(peak)
    return [dict(kind=kind, name=name, launches=n, took_off=took, picked_up=picked, median_peak=median(peaks))
            for (kind, name), (n, took, picked, peaks) in rows.items() if n >= 5]


def titles(islands, state):
    names = {row["code"]: dict(title=row["title"], creator=row["creator"], tags=row["tags"].split("|") if row["tags"] else [],
                               created_in=row["created_in"]) for row in islands}
    for code, (title, creator, tags, created_in, _) in state.get("meta", {}).items():
        names.setdefault(code, dict(title=title, creator=creator, tags=tags, created_in=created_in))
    return names


def leaders(rankings, names, state):
    if not rankings:
        return None
    latest = max(row["hour"] for row in rankings)
    day_before = utc_text(parse_time(latest) - timedelta(hours=24))
    earlier = {(row["genre"], row["code"]): int(row["rank"]) for row in rankings if row["hour"] == day_before}
    genre_names = dict(state.get("genres", {}).get("list", []))
    boards = defaultdict(list)
    for row in rankings:
        if row["hour"] == latest and int(row["rank"]) <= 25:
            before = earlier.get((row["genre"], row["code"]))
            info = names.get(row["code"], {})
            boards[row["genre"]].append(dict(rank=int(row["rank"]), code=row["code"], title=info.get("title", ""),
                                             creator=info.get("creator", ""), change=before - int(row["rank"]) if before else None,
                                             new=before is None and bool(earlier)))
    return dict(hour=latest, compared_to=day_before if earlier else None,
                genres=[dict(slug=slug, name=genre_names.get(slug, slug), rows=sorted(rows, key=lambda r: r["rank"]))
                        for slug, rows in sorted(boards.items())])


def keyword_table(keyword_rows):
    if not keyword_rows:
        return None
    dates = sorted({row["date"] for row in keyword_rows})
    latest = dates[-1]
    week = max((d for d in dates if d <= utc_text(parse_time(latest + "T00:00:00Z") - timedelta(days=7))[:10]), default=None)
    before = {(row["kind"], row["term"]): row for row in keyword_rows if row["date"] == week}
    rows = []
    for row in keyword_rows:
        if row["date"] != latest:
            continue
        old = before.get((row["kind"], row["term"]))
        ranked, players = int(row["ranked"]), int(row["unique_players"])
        rows.append(dict(kind=row["kind"], term=row["term"], islands=int(row["islands"]), new_7d=int(row["new_7d"]),
                         ranked=ranked, players=players, plays=int(row["plays"]),
                         players_per_ranked=round(players / ranked) if ranked else None,
                         players_change=players - int(old["unique_players"]) if old else None,
                         islands_change=int(row["islands"]) - int(old["islands"]) if old else None))
    words = sorted((r for r in rows if r["kind"] == "word"), key=lambda r: -r["players"])
    return dict(date=latest, compared_to=week, tags=[r for r in rows if r["kind"] == "tag"],
                words=words[:400] + sorted(words[400:], key=lambda r: -r["new_7d"])[:100])


LAUNCH_KEYS = ["peak_ccu", "peak_at", "pickup_at", "hours_to_pickup", "plays", "minutes_played", "favorites",
               "recommendations", "unique_players", "avg_minutes", "d1", "d7", "best_rank", "best_rank_genre"]


def map_records(data_dir=None, state=None, now=None, days=30):
    """Everything the tracker recorded per map, for the map page: release time, launch results,
    player surges, latest genre rank. Covers recent launches, recent surges and ranked maps."""
    now = now or datetime.now(timezone.utc)
    state = load_state() if state is None else state
    since = utc_text(now - timedelta(days=days))
    records = {}
    for row in read_table("islands", since[:7], data_dir):
        if row["first_seen"] >= since:
            records[row["code"]] = dict(first_seen=row["first_seen"], source=row["source"])
    for row in read_table("launches", since[:7], data_dir):
        if row["code"] in records:
            records[row["code"]].setdefault("launch", {})[row["stage"]] = {k: number(row[k]) if k not in ("peak_at", "pickup_at", "best_rank_genre") else (row[k] or None) for k in LAUNCH_KEYS}
    for row in read_table("pickups", since[:7], data_dir):
        if row["at"] >= since:
            records.setdefault(row["code"], {}).setdefault("surges", []).append([row["at"], number(row["ccu_before"]), number(row["ccu_after"])])
    ranked = state.get("ranked", {})
    for code, (genre, rank) in ranked.get("codes", {}).items():
        records.setdefault(code, {})["rank"] = [genre, rank, ranked["hour"]]
    return dict(generated_at=utc_text(now), tracking_since=min((r["started"] for r in read_table("runs", data_dir=data_dir)), default=None),
                genres=dict(state.get("genres", {}).get("list", [])), maps=records)


def analyze(data_dir=None, state=None, now=None):
    now = now or datetime.now(timezone.utc)
    state = load_state() if state is None else state
    runs = read_table("runs", data_dir=data_dir)
    islands = read_table("islands", data_dir=data_dir)
    by_code = outcomes(read_table("launches", data_dir=data_dir))
    names = titles(islands, state)
    week_ago, day_ago = utc_text(now - timedelta(days=7)), utc_text(now - timedelta(days=1))
    three_days = utc_text(now - timedelta(days=3))

    live = []
    for code, entry in state.get("launch", {}).items():
        info = names.get(code) or {}
        stages = by_code.get(code, {})
        live.append(dict(code=code, title=info.get("title", ""), creator=info.get("creator", ""), tags=info.get("tags", []),
                         created_in=info.get("created_in", ""), peak=entry.get("peak", 0), ccu=entry.get("ccu", 0),
                         pickup=entry.get("pickup"), spark=entry.get("spark", []), checked=entry.get("at"),
                         peak_24h=number(stages["24"]["peak_ccu"]) if "24" in stages else None))
    first_seen = {row["code"]: (row["first_seen"], row["source"]) for row in islands if row["first_seen"] >= week_ago}
    live = [dict(item, first_seen=first_seen[item["code"]][0], source=first_seen[item["code"]][1])
            for item in live if item["code"] in first_seen]
    live.sort(key=lambda item: (-item["peak"], item["first_seen"]))

    pickups = []
    for row in read_table("pickups", three_days[:7], data_dir):
        if row["at"] >= three_days:
            info = names.get(row["code"], {})
            pickups.append(dict(row, title=info.get("title", ""), creator=info.get("creator", ""),
                                age_hours=number(row["age_hours"]), ccu_before=number(row["ccu_before"]),
                                ccu_after=number(row["ccu_after"])))
    pickups.sort(key=lambda row: row["at"], reverse=True)

    new_by_day = Counter(row["first_seen"][:10] for row in islands if row["source"] == "head")
    finished = [row["finished"] for row in runs]
    return dict(
        generated_at=utc_text(now),
        latest_run=max(finished) if finished else None,
        tracking_since=min(row["started"] for row in runs) if runs else None,
        runs_24h=sum(f >= day_ago for f in finished),
        new_24h=sum(row["first_seen"] >= day_ago for row in islands),
        new_7d=sum(row["first_seen"] >= week_ago for row in islands),
        launches_finished=sum("144" in stages for stages in by_code.values()),
        launches_early=sum("24" in stages for stages in by_code.values()),
        settings=dict(traction_ccu=config.TRACTION_CCU, pickup_min_ccu=config.PICKUP_MIN_CCU,
                      pickup_factor=config.PICKUP_FACTOR, window_hours=config.LAUNCH_WINDOW_HOURS,
                      stale_minutes=config.STALE_MINUTES),
        timing=timing_grids(islands, by_code),
        success=success_table(islands, by_code),
        live=live[:config.LIVE_LIMIT],
        pickups=pickups[:200],
        leaders=leaders(read_table("rankings", utc_text(now - timedelta(days=2))[:7], data_dir), names, state),
        keywords=keyword_table(read_table("keywords", utc_text(now - timedelta(days=9))[:7], data_dir)),
        new_per_day=sorted(new_by_day.items())[-30:],
    )


def main():
    result = analyze()
    atomic_write(config.OUTPUT, json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    maps = map_records()
    atomic_write(config.OUTPUT.with_name("maps.json"), json.dumps(maps, ensure_ascii=False, separators=(",", ":")))
    if config.CATALOG_INDEX.exists():
        shutil.copyfile(config.CATALOG_INDEX, config.OUTPUT.with_name("catalog.json"))
    print(f"Analyzed: {len(result['live'])} live launches, {result['launches_finished']} finished launches, "
          f"{len(result['pickups'])} recent surges, {len(maps['maps'])} map records")


if __name__ == "__main__":
    main()
