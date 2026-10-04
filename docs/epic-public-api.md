# Epic's public Fortnite Data API: complete reference

Everything Epic's public API exposes, checked live on **3–4 October 2026**: the official spec, every endpoint called with real responses, the response headers, the limits measured in practice, and the places where Epic's documentation disagrees with what the API actually returns.

Notes marked **Interpretation** are my reading of the evidence, not something Epic states.

- Docs page (Swagger UI): https://api.fortnite.com/ecosystem/v1/docs
- Raw spec (OpenAPI 3.1.1, 1,287 lines): https://api.fortnite.com/ecosystem/v1/docs/openapi.yaml
- Epic's guide: https://dev.epicgames.com/documentation/fortnite/using-fortnite-data-api-in-fortnite
- Spec title and version: **"Fortnite Data API" v1.1.0**, described as *"A public API to retrieve a list of Fortnite islands and their corresponding engagement metrics."*

---

## 1. The basics

| | |
|---|---|
| Base URL | `https://api.fortnite.com/ecosystem/v1` |
| Login | **None.** No key, no token. |
| Methods | `GET` only |
| Format | JSON (`application/json; charset=utf-8`) |
| Browser use | Allowed: every response has `Access-Control-Allow-Origin: *`. This is why our map page can call it straight from your browser. |
| Front door | Cloudflare (`server: cloudflare`, `cf-cache-status: DYNAMIC`, meaning responses are not cached). Unlike fortnite.gg and fortnite.com, there is **no bot challenge**. |
| Tracing header | `x-epic-correlation-id: <uuid>` on every response. **Interpretation:** Epic's request ID, useful if you ever report a bug to them. |
| Rate-limit headers | **None.** No `X-RateLimit-*` or `Retry-After`. The only signal is a `429` (or, seen once, an empty `200`). |
| Unknown paths | Plain-text `404` reading `THESE ARE NOT THE LLAMAS YOU'RE LOOKING FOR`. Unknown API versions (`/ecosystem/v2`, `/v1beta`) answer `401 "Jwt is missing"` from `fn-gateway` instead. |

### Rules that apply everywhere (Epic's own notes)
1. **History is limited to 7 days.**
2. **Only public, discoverable islands** are included. Private, unlisted or unreleased islands don't exist here.
3. **An island needs at least 5 unique players in a bucket**, or that bucket's value is `null`.
4. **Favorites and recommendations return 0 for some Epic-made games.**

### Time buckets
- `interval` is `day`, `hour` or `minute`. **`minute` means 10-minute buckets** (`:00, :10, :20…`).
- Timestamps are UTC and mark the **start** of the bucket.
- `from` is inclusive; `to` is exclusive.
- Defaults when you omit `from`: day → start of the previous day; hour → now − 24h; minute → now − 60 min.
- **Measured:** `from` can't be earlier than **midnight UTC 7 days ago**. Error: *"The from timestamp cannot be before Sun, 27 Sep 2026 00:00:00 GMT."* One request can cover the whole window at any interval (a 7-day `minute` request returns 1,008 points).
- **Measured lag:** the newest 10-minute buckets come back `null` for about 20–30 minutes before they fill in.

### Pagination (catalog and genre rankings)
- Cursor-based: `after=<cursor>` for the next page, `before=<cursor>` for the previous one. Every record carries its own `meta.page.cursor`, and each page has `meta.page.nextCursor` / `prevCursor` plus `links.next` / `links.prev` (ready-made paths).
- `size`: default 100, **max 1000**.
- **Interpretation:** cursors are just base64. For the catalog, `MzUxMi0wOTM1LTQ3Nzk=` decodes to the island code `3512-0935-4779`. For rankings, `Mg==` decodes to `2` (a row offset).

### Rate limits (measured; Epic publishes none)
| Endpoint | What happened |
|---|---|
| `/islands` catalog | 289 pages of 1,000 back to back in ~50 s: no throttling |
| Per-island metrics | Sequential, ~3 requests/s: fine for hundreds in a row. 10 in parallel: `429` after ~25 requests. |
| Genre rankings | A quick burst of ~40: throttled, with an empty body |

---

## 2. All 18 endpoints

| # | Endpoint | Returns |
|---|---|---|
| 1 | `GET /islands` | Catalog of every public island, newest release first |
| 2 | `GET /islands/{code}` | One island's metadata |
| 3 | `GET /islands/{code}/metrics` | All metrics, daily buckets |
| 4 | `GET /islands/{code}/metrics/{interval}` | All (or chosen) metrics at day/hour/10-min |
| 5–12 | `GET /islands/{code}/metrics/{interval}/{metric}` | One metric: `peak-ccu`, `favorites`, `minutes-played`, `average-minutes-per-player`, `recommendations`, `unique-players`, `plays`, `retention` |
| 13 | `GET /islands/{code}/rankings` | The island's genre rank(s), hourly |
| 14 | `GET /genres` | The 13 genres |
| 15 | `GET /genres/{slug}/rankings` | A genre's full leaderboard at an hour |
| 16 | `GET /metrics/{interval}` | All-of-Fortnite player counts |
| 17 | `GET /metrics/{interval}/in-client-peak-ccu` | Peak players with the game open |
| 18 | `GET /metrics/{interval}/in-match-peak-ccu` | Peak players in a match |

---

### 1. `GET /islands`: the catalog
Epic: *"Retrieves a sorted list of islands. The islands returned are sorted by initial release date … with newest releases first."*

Parameters: `after`, `before`, `size` (1–1000).

```json
{"links":{"next":"/ecosystem/v1/islands?after=ODAxMS02MzY0LTQwNzI%3D&size=2","prev":null},
 "meta":{"count":2,"page":{"nextCursor":"ODAxMS02MzY0LTQwNzI=","prevCursor":null}},
 "data":[{"code":"3512-0935-4779","creatorCode":"neoncreate","title":"TALKVERSE - VOICE COMMUNITY 🌎 CHILL",
          "createdIn":"UEFN","tags":["party game","casual","music","puzzle"],"meta":{"page":{"cursor":"MzUxMi0wOTM1LTQ3Nzk="}}}, …]}
```

- **Size:** 288,880 public islands on 25 Sep 2026: 183k UEFN, 94k Fortnite Creative (`FNC`), ~12k with no `createdIn` (mostly Epic's own modes).
- **The release date itself is not returned**, only the order. **Interpretation:** that's why the tracker records "first seen": polling the newest pages tells you when a map went public, to within one polling interval.
- The order isn't perfectly strict. Some maps fortnite.gg listed as just released sat 400–700 places down, or were missing. **Interpretation:** "initial release" may be when a map was first published privately, so maps made public later sit deeper in the list.
- `before` on the first page returns an empty page (nothing is newer).

### 2. `GET /islands/{code}`: one island
```json
{"code":"3225-0366-8885","creatorCode":"ferins","title":"STEAL THE BRAINROT","createdIn":"UEFN",
 "tags":["simulator","just for fun","casual","tycoon"]}
```
Epic's own modes also return a `displayName`, and **that name works anywhere a code does**:
```json
GET /islands/battle-royale  →  {"displayName":"battle-royale","code":"experience_br","creatorCode":"epic","title":"Battle Royale","createdIn":"UEFN","tags":[]}
GET /islands/playlist_juno  →  {"displayName":"lego-fortnite-odyssey","code":"playlist_juno","creatorCode":"epic","title":"LEGO Fortnite Odyssey","category":"LEGO","tags":[]}
```
Unknown code → `404 {"errorCode":"errors.com.epicgames.fne-public-api.not_found","errorMessage":"Not found","uuid":"…"}`

| Field | Epic's description | Notes |
|---|---|---|
| `code` | The island's code | `1234-5678-9012`, or `playlist_…`/`experience_…`/`set_…` for Epic modes |
| `creatorCode` | The island creator's code | The creator's support-a-creator name, lowercase. `epic` for Epic. |
| `title` | The island's title | As shown in game, emojis and all |
| `tags` | *"A list of tags a creator has attributed to their island (ex: 1v1)"* | **A fixed list of 152 tags**, not free text. Most common: free for all, pvp, just for fun, 1v1, practice, competitive, building. |
| `createdIn` | *"How the island was authored"* | `UEFN` (Unreal Editor for Fortnite) or `FNC` (in-game Creative tools) |
| `category` | *"Island category which for islands utilizing a brand will be the brand code"* | Only on branded islands: `Star Wars` (4,155), `TMNT`, `FALL GUYS`, `LEGO`, `Rocket Racing`, `KPop Demon Hunters`, `SQUID GAME`, `The Walking Dead Universe`. Casing varies (`STAR WARS` vs `Star Wars`). |
| `displayName` | Friendly name for Epic's playlists | Epic modes only |

### 3. `GET /islands/{code}/metrics`: daily buckets
Same as #4 with `interval=day`. Parameters: `from`, `to`. Default: yesterday and today.
```json
{"averageMinutesPerPlayer":[{"value":81.85,"timestamp":"2026-10-03T00:00:00.000Z"},{"value":23.54,"timestamp":"2026-10-04T00:00:00.000Z"}],
 "peakCCU":[{"value":584106,…},{"value":27850,…}], "favorites":[…], "minutesPlayed":[…], "recommendations":[…],
 "plays":[…], "uniquePlayers":[…], "retention":[{"d1":0.62,"d7":0.47,"timestamp":"2026-10-03T00:00:00.000Z"}, …]}
```
Today's bucket is partial and fills in as the day goes on.

### 4. `GET /islands/{code}/metrics/{interval}`: choose the interval and metrics
Parameters: `interval` (`day`/`hour`/`minute`), `metrics` (repeatable), `from`, `to`.
`metrics` can be: `averageMinutesPerPlayer`, `peakCCU`, `favorites`, `minutesPlayed`, `recommendations`, `plays`, `uniquePlayers`, `retention`.

Which metrics each interval returns (**measured**):

| Metric | day | hour | 10-min |
|---|---|---|---|
| peakCCU | ✓ | ✓ | ✓ |
| plays | ✓ | ✓ | ✓ |
| uniquePlayers | ✓ | ✓ | ✓ |
| minutesPlayed | ✓ | ✓ | ✓ |
| favorites | ✓ | ✓ | ✓ |
| recommendations | ✓ | ✓ | ✓ |
| averageMinutesPerPlayer | ✓ | ✓ | dropped silently |
| retention (d1/d7) | ✓ | dropped silently | dropped silently |

Bad interval (e.g. `week`) → `400 request-validation`: *"Invalid enum value. Expected 'day' | 'hour' | 'minute', received 'week'"*.

### 5–12. Single-metric endpoints
`/islands/{code}/metrics/{interval}/peak-ccu` · `/favorites` · `/minutes-played` · `/average-minutes-per-player` · `/recommendations` · `/unique-players` · `/plays` · `/retention`

Same data as #4, one metric, wrapped in `intervals`:
```json
GET …/metrics/day/peak-ccu   → {"intervals":[{"value":584106,"timestamp":"2026-10-03T00:00:00.000Z"},{"value":27850,"timestamp":"2026-10-04T00:00:00.000Z"}]}
GET …/metrics/day/retention  → {"intervals":[{"d1":0.62,"d7":0.47,"timestamp":"2026-10-03T00:00:00.000Z"}, …]}
```
- `retention` at hour or minute → `404` (documented).
- `average-minutes-per-player` at minute → `404`, but **at hour it works**, although the spec says day only.

### 13. `GET /islands/{code}/rankings`: an island's genre rank
Parameters: `from`, `to`. With both omitted you get **only the latest hourly snapshot**; with a range you get an hourly series (up to 7 days).
```json
{"data":[{"timestamp":"2026-10-04T02:00:00.000Z","genres":[{"genreSlug":"simulation-tycoon","genre":"Simulation & Tycoon","rank":1}]}]}
```
- An island can rank in several genres at once (`genres` is a list).
- Epic's modes (`battle-royale`) return `{"data":[]}`.
- The spec's 404 text says *"not found **or is not enabled for data access**"*. **Interpretation:** a hint that some islands are excluded from rankings, or that a creator-level opt-in exists or is planned.

### 14. `GET /genres`
13 genres:

| slug | name |
|---|---|
| `survival` | Survival |
| `strategy` | Strategy |
| `sports-racing` | Sports & Racing |
| `simulation-tycoon` | Simulation & Tycoon |
| `shooter` | Shooter |
| `roleplaying-social` | Roleplaying & Social |
| `roguelike` | Roguelike |
| `party-mini-games` | Party & Mini Games |
| `music-rhythm` | Music & Rhythm |
| `horror` | Horror |
| `deathrun-platformer` | Deathrun & Platformer |
| `battle-royale` | Battle Royale |
| `adventure-rpg` | Adventure & RPG |

**Interpretation:** these match Discover's "genre / play style" rows. Epic's Discover guide points creators to this API *"to gain insights into where and how often your island is appearing across Discover"*, so a high genre rank is the closest public proxy for how high a map is offered in its genre row. A proxy, not a placement record.

### 15. `GET /genres/{slug}/rankings`: a genre's full leaderboard
Parameters: `at` (hour; default the latest; at most 7 days old), `after`, `before`, `size` (≤1000).
```json
{"links":{"next":"/ecosystem/v1/genres/simulation-tycoon/rankings?after=Mg%3D%3D&size=3&at=2026-10-04T02%3A00%3A00.000Z","prev":null},
 "meta":{"count":3,"total":6577,"snapshotAvailable":true,"snapshot":"2026-10-04T02:00:00.000Z","page":{"nextCursor":"Mg==","prevCursor":null}},
 "data":[{"islandCode":"3225-0366-8885","rank":1,…},{"islandCode":"7865-8305-9184","rank":2,…},{"islandCode":"7875-7934-3852","rank":3,…}]}
```
- `total` = how many islands are ranked in that genre that hour. Measured: Simulation & Tycoon ~6,600; Party & Mini Games ~11,000; **Shooter ~134,700** (most PvP maps land there).
- `snapshotAvailable: false` means Epic never imported that hour (an outage), which is different from an empty genre.
- **Lag:** on 25 Sep the newest filled hour was ~4 hours old (later hours returned `total: 0`). On 4 Oct the newest was under an hour old. So the lag varies, and the tracker re-checks empty hours.
- Unknown slug → `404 "Unknown genre: brainrot"`. Genres are fixed; you can't rank by keyword.

**What the rank is based on (Interpretation, measured 3 Oct 23:00 UTC, top 40 of two genres):** Epic doesn't say. Rank lines up strongly with player volume, but no single metric matches it exactly:

| Correlation of rank with… | Simulation & Tycoon | Shooter |
|---|---|---|
| Peak players that hour | 0.88 | 0.95 |
| Unique players that hour | 0.92 | 0.94 |
| Plays that hour | 0.93 | 0.91 |
| Minutes played that hour | 0.89 | 0.95 |
| Peak players, last 24h | 0.89 | 0.97 |
| Favorites, last 24h | 0.79 | 0.70 |
| Recommends, last 24h | 0.83 | 0.74 |

In Simulation & Tycoon, #2 had **twice** the concurrent players of #1 that hour, but #1 had far more unique players over 24 hours. Best guess: a **blended engagement score over a trailing window** (players, plays and time played), not live player count. Favorites and recommends matter much less.

### 16–18. Ecosystem: all of Fortnite
`GET /metrics/{interval}` (optional `metrics=inMatchPeakCCU|inClientPeakCCU`), `/metrics/{interval}/in-client-peak-ccu`, `/metrics/{interval}/in-match-peak-ccu`
```json
GET /metrics/day → {"inMatchPeakCCU":[{"value":2346244,"timestamp":"2026-10-03T00:00:00.000Z"},…],
                    "inClientPeakCCU":[{"value":3515815,"timestamp":"2026-10-03T00:00:00.000Z"},…]}
```
- `inClientPeakCCU`: peak players with Fortnite open (lobby, menus, in game).
- `inMatchPeakCCU`: peak players actually inside a match or island.
- **Interpretation:** the gap between them (3.5M vs 2.3M on 3 Oct) is roughly how many people sat in the lobby or menus, i.e. the audience browsing Discover at peak. Useful context for "best time to publish": the hours when lots of players are online.

---

## 3. Every metric explained

| Metric | Epic says | What it really looks like | What I think it means for you |
|---|---|---|---|
| `peakCCU` | Peak concurrent players | Highest player count inside the bucket | "Players now". Best signal for spikes, i.e. when something sent players your way. |
| `uniquePlayers` | Distinct players | Distinct accounts in the bucket. **Not additive:** summing 10-min buckets over-counts. | Reach. Use daily buckets for true daily uniques. |
| `plays` | *"Number of times players started to play"*; repeats count | Sessions started | Plays ÷ unique players = how often people re-queue (Steal the Brainrot ≈ 4 per player on 3 Oct). |
| `minutesPlayed` | Total minutes | Additive across buckets | Total engagement, likely a big input to creator payouts. |
| `averageMinutesPerPlayer` | Average minutes per player | Day and hour only | Session depth. Discover's guide lists playtime as a key signal. |
| `favorites` | Times favorited in the bucket | **New favorites**, not a running total | Commitment. fortnite.gg also shows favorites per 1,000 players. |
| `recommendations` | Times recommended | New recommends in the bucket | Word of mouth. Epic's Discover guide names recommends as a signal. |
| `retention.d1` / `d7` | *"The number of players retained"* | **Actually a fraction** (`0.62` = 62%), not a count | D1: share of yesterday's players who came back. D7: share of last week's players. Discover rewards this heavily. |
| `inClientPeakCCU` | Peak clients connected | All of Fortnite | Size of the total audience online |
| `inMatchPeakCCU` | Peak players in a match | All of Fortnite | Players actually in games |

---

## 4. Where the docs and reality disagree

1. **`retention` is a fraction, not a count.** The spec says *"The number of players retained…"* but values are `0.53`, `0.62`.
2. **Average minutes per player works hourly.** The single-metric endpoint says day only and 404 otherwise; hourly works on both endpoints.
3. **10-minute buckets include `uniquePlayers`.** Not mentioned anywhere; useful but not additive.
4. **`type` is listed as a required field on islands but is never returned.**
5. **The 7-day window is "midnight UTC seven days ago"**, slightly more than 7×24 hours for daily queries.
6. **Throttled requests sometimes return an empty `200`** instead of the documented `429` text.
7. **An unused login scheme is declared.** The spec defines `securitySchemes.Auth`, an OAuth2 *client-credentials* flow with token URL `https://api.epicgames.dev/epic/oauth/v1/token` (Epic Online Services), but no endpoint requires it. **Interpretation:** a leftover, or groundwork for a future keyed tier (higher limits or private data for your own islands). Nothing uses it today.

## 5. Errors you can get
| Status | Body | Cause |
|---|---|---|
| 400 | `errors.com.epicgames.fne-public-api.request-validation` with an `issues` list | Bad enum, e.g. interval `week` |
| 400 | `errors.com.epicgames.fne-public-api.bad_request`, *"The from/at timestamp cannot be before …"* | Past the 7-day window |
| 404 | `errors.com.epicgames.fne-public-api.not_found`, `"Not found"` | Unknown island, or a metric not offered at that interval |
| 404 | `…not_found`, `"Unknown genre: <slug>"` | Bad genre |
| 404 | Plain text `THESE ARE NOT THE LLAMAS YOU'RE LOOKING FOR` | Path doesn't exist |
| 429 | Text, or sometimes an empty `200` | Too fast |
| 401 | `"Jwt is missing"` (`fn-gateway`) | Asking for an API version that isn't public |

## 6. What is **not** in this API
Checked by exhaustive endpoint probing and against Epic's docs:
- **Discover placements**: which row, which position, when. That lives only in the in-game Discover service, which requires a logged-in Fortnite session.
- **Impressions, clicks, click-through rate**: only in Creator Portal → Project Analytics, and only for islands you own.
- **Release / publish / update timestamps and version history**: only the newest-first order. fortnite.gg's "Released / Updated / Version" come from Epic's logged-in map-details service.
- **Submit time** (when a creator uploaded a map for review): not public anywhere.
- **Descriptions, thumbnails, max players, age rating, XP status**: not here.
- **Search terms** players type: not exposed by Epic at all.
- **Creator pages or lists** (`/creators`): don't exist.
- **Anything older than 7 days**: the tracker keeps its own history for exactly this reason.

## 7. How the tracker uses it
| Tracker feature | Endpoints |
|---|---|
| New-release detection ("went public") | `/islands` newest pages every 15 min; full crawl daily |
| Launch results (24h, 6 days), player surges | `/islands/{code}/metrics/minute` (10-min series), `/metrics/day`, `/islands/{code}/rankings` |
| Genre leaders, ranked-map tracking | `/genres`, `/genres/{slug}/rankings` hourly (top 200 followed, top 50 stored) |
| Daily stats of ranked maps | `/islands/{code}/metrics/day` |
| Keyword supply/demand, map search index | Full `/islands` crawl |
| Map page (in your browser) | `/islands/{code}`, `/metrics/hour`, `/metrics/minute`, `/metrics/day`, `/rankings` |
| Not used yet | `/metrics/{interval}` ecosystem totals. They could add a "players online" line to the best-time-to-publish view. |
