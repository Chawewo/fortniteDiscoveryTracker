"""Tracker settings. All timestamps use UTC; the dashboard converts to local time."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATE_FILE = ROOT / ".state" / "state.json"  # Working state, restored from the Actions cache.
CATALOG_INDEX = ROOT / ".state" / "catalog.json"  # Code, title, creator of every public map, for search.
OUTPUT = ROOT / "dashboard" / "data.json"

API = "https://api.fortnite.com/ecosystem/v1"
USER_AGENT = "FortniteDiscoveryTracker/1.0 (+https://github.com/Chawewo/fortniteDiscoveryTracker)"
REQUESTS_PER_SECOND = 3.0   # Measured: ~3/s sustained is fine, bursts of 10 parallel get 429s.
WORKERS = 4
RUN_SECONDS = 330           # Stop starting new API work after this, so a run fits its 15-minute slot.

LIST_PAGE_SIZE = 1000
HEAD_MAX_PAGES = 8          # Newest-first pages scanned each run for new releases.
CATALOG_EVERY_HOURS = 24    # Full catalog crawl: late releases, titles, keyword supply.

RANKING_STORE_DEPTH = 50    # Rows committed per genre per hour.
RANKING_TRACK_DEPTH = 200   # Islands per genre whose stats are followed.
RANKING_HOURS_PER_RUN = 6   # Backfill pace for missing hourly ranking snapshots.
RANKING_GIVE_UP_HOURS = 30  # Hours still empty after this are skipped for good.

LAUNCH_CHECK_HOURS = (2, 6, 24, 72)  # Live checks of new islands after first seen.
EARLY_STAGE_HOURS = 24      # Committed early outcome row.
LAUNCH_WINDOW_HOURS = 144   # Final outcome window: the first 6 days after first seen.
FINAL_AFTER_HOURS = 150     # Epic keeps 7 days, so finals must run between 150h and 168h.
ESTABLISHED_REFRESH_HOURS = 12

TRACTION_CCU = 100          # "Took off": peak concurrent players reached in the window.
PICKUP_MIN_CCU = 50         # Player surge: a jump to at least this many players...
PICKUP_FACTOR = 4           # ...and at least this many times the previous hour's peak.
CURVE_MIN_PEAK = 50         # Hourly launch curves are committed only for islands this big.

KEYWORD_MIN_ISLANDS = 25    # Title terms need this many islands to be reported.
LIVE_LIMIT = 250            # Live launches shown on the dashboard.
FILE_BYTES = 40 * 1024 * 1024  # Monthly CSVs roll over below GitHub's 100 MB file limit.
STALE_MINUTES = 45
