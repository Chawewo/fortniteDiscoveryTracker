# Drop Zone — Fortnite discovery tracker

Follows every new Fortnite Creative map through its first six days to find **when to publish** so a map gets picked up, **what successful launches share**, and **which title keywords draw players**.

**Dashboard:** https://chawewo.github.io/fortniteDiscoveryTracker/ (after the first successful Pages deployment).

## Data source

Epic's public [Fortnite Data API](https://api.fortnite.com/ecosystem/v1/docs), no login:

| What | Detail |
|---|---|
| Island catalog | ~290k public islands, newest release first: code, title, creator, tags, UEFN/FNC, brand |
| Island metrics | Peak players, plays, minutes played, favorites, recommendations (10-minute buckets); unique players, average minutes, D1/D7 retention (daily) |
| Genre rankings | Hourly leaderboards for 13 genres, published a few hours late |

Epic keeps only **7 days** of history, so the tracker snapshots it. Metrics are null when fewer than 5 players were on an island. Discover row placements, update history and search terms are **not** in the public API.

fortnite.gg is not used: it blocks non-browser requests with a Cloudflare challenge.

## How a run works (every 15 minutes)

1. **New releases:** scan the newest-first island list until a page has nothing new. A map's `first_seen` is the run that first saw it (accurate to about 15 minutes). The first run records every existing island in `data/seed_codes.txt` so they are never mistaken for new.
2. **Genre rankings:** store the top 50 per genre per hour and backfill any missing hours within Epic's 7-day window.
3. **Launch tracking:** each new map's 10-minute series is checked at 2h, 6h, 24h and 72h. An **early row** (first 24h) is committed at 24h and a **final row** (first 144h) after 150h, before Epic's 7-day window expires. Final rows add unique players, retention, best genre rank and, for maps that reached 50+ players, an hourly curve.
4. **Daily catalog crawl:** catches releases the scan missed (`source=catalog`, excluded from timing because their time is imprecise) and computes keyword supply and demand.
5. **Established maps:** the top 200 per genre are refreshed every 12 hours: daily stats plus hourly players for jump detection.

Each run is time-boxed (~5.5 minutes) and paced at ~3 requests per second. Unfinished work carries over to the next run.

## Definitions

- **Took off:** peak concurrent players reached 100 or more (`TRACTION_CCU`).
- **Sudden pickup:** the first 10-minute bucket at 50+ players (`PICKUP_MIN_CCU`) and at least 4× (`PICKUP_FACTOR`) the previous hour's peak. A jump like that almost always means a Discover row placed the map. It is an inference, not Epic's Discover data.
- **Best time to publish:** launches grouped by the hour of the week they were first seen, shown in the viewer's local time. Cells with too few launches are hatched out. Give it a few weeks: each of the 168 hours needs several launches.
- **Keyword demand:** for each title word, word pair or tag: how many maps use it (supply), how many are new this week, and yesterday's unique players on ranked maps using it (demand). "brain rot" also counts toward "brainrot".

## Storage

`data/` is append-only, in monthly CSVs that roll over at 40 MB:

| Folder | Rows |
|---|---|
| `islands/` | Every new island: first_seen, code, title, creator, tool, brand, tags, source |
| `launches/` | Launch outcomes, `stage` 24 (early) and 144 (final) |
| `curves/` | Hourly players and plays for launches that reached 50+ players |
| `pickups/` | Sudden jumps, for launches and established maps |
| `rankings/` | Hourly genre top 50 |
| `daily/` | Daily stats for ranked maps |
| `keywords/` | Daily keyword and tag supply/demand |
| `runs/` | One row per collection run |

Working state (live checks, sparklines, titles of ranked maps) lives in `.state/`, which is kept in the GitHub Actions cache rather than committed. If it is lost, it rebuilds within a day; committed data is never rebuilt from it.

## Run locally

Python 3.11+, standard library only.

```sh
python -m unittest discover -s tests -v
python collect.py
python analyze.py
python -m http.server 8000 --directory dashboard
```

Tests use a fake API and never touch the network. Avoid running the live collector often: GitHub Actions already runs it every 15 minutes.

## GitHub Actions and Pages

Workflow `.github/workflows/track.yml` runs at minutes 7, 22, 37 and 52 (UTC), on manual dispatch, and on pushes that change code. It tests, collects, analyzes, commits `data/` with `[skip ci]`, and deploys `dashboard/` to Pages. Pages source must be **GitHub Actions**, and workflow permissions must allow writing.

GitHub's schedule is best effort: runs can be delayed, and public-repo schedules pause after 60 days without repository activity (the data commits count as activity).
