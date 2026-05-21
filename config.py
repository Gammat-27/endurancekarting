"""
Constants and configuration helpers for the karting strategy app.
"""

from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
RACE_DATA_FILE = DATA_DIR / "race_data.json"
SESSION_CONFIG_FILE = DATA_DIR / "session_config.json"

DATA_DIR.mkdir(exist_ok=True)

# ── Scraper ───────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 5
NETWORK_TIMEOUT_SECONDS = 10
MAX_CONSECUTIVE_ERRORS = 6
PLAYWRIGHT_WAIT_MS = 3000

# ── Race defaults ─────────────────────────────────────────────────────────────
DEFAULT_MIN_STINTS = 2
DEFAULT_MIN_FUEL_STOPS = 1
DEFAULT_MAX_STINT_MINUTES = 45
DEFAULT_MIN_PIT_LANE_SECONDS = 90   # 1 min 30 s minimum in pit lane

# ── Pit countdown thresholds (% of minimum pit time elapsed) ─────────────────
PIT_WARN_PCT = 70     # bar turns orange above this
PIT_CRIT_PCT = 90     # bar turns red above this

# ── Stint gauge thresholds (% of max stint time elapsed) ─────────────────────
STINT_WARN_PCT = 78   # gauge turns orange
STINT_CRIT_PCT = 92   # gauge turns red

# ── Display / refresh ─────────────────────────────────────────────────────────
DASHBOARD_REFRESH_MS = 5000
PIT_ACTIVE_REFRESH_MS = 1000        # 1 s refresh during pit countdown
LAP_TIME_FORMAT = "%M:%S.%f"
