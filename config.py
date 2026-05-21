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
POLL_INTERVAL_SECONDS = 5          # Delay between polling cycles
NETWORK_TIMEOUT_SECONDS = 10       # HTTP request timeout
MAX_CONSECUTIVE_ERRORS = 6         # ~30 s of Wi-Fi outage before showing error
PLAYWRIGHT_WAIT_MS = 3000          # ms to wait for JS after page load

# ── Race defaults ─────────────────────────────────────────────────────────────
DEFAULT_MIN_STINTS = 2
DEFAULT_MIN_FUEL_STOPS = 1
DEFAULT_MAX_STINT_MINUTES = 60     # Alert if driver exceeds this

# ── Display ───────────────────────────────────────────────────────────────────
LAP_TIME_FORMAT = "%M:%S.%f"       # For display formatting

# Streamlit auto-refresh interval (ms) — must stay > POLL_INTERVAL_SECONDS * 1000
DASHBOARD_REFRESH_MS = 5000
