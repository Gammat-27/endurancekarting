"""
Apex Timing scraper.

Strategy (tried in order):
1. Intercept XHR/fetch via Playwright — works for any JS-heavy page and lets us
   capture the raw JSON the page itself consumes.
2. Direct JSON endpoint polling — if we already know the endpoint from a
   previous intercept, skip Playwright and hit it directly with requests.
3. SSE / EventSource stream — for sites that push updates via text/event-stream.
4. HTML fallback — parse the rendered <table> with BeautifulSoup.

The caller only ever calls `fetch_standings(url)` and gets back a list of dicts.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ── Data model returned by this module ────────────────────────────────────────

@dataclass
class Standing:
    pos: int
    num: str           # kart / dossard number as string
    team: str
    laps: int
    last_lap: str      # "1:23.456" or "" if no lap yet
    best_lap: str
    gap: str           # gap to leader, e.g. "+1L" or "+12.345"
    pit_count: int
    status: str        # "racing", "pit", "out", etc.
    raw: dict = field(default_factory=dict, repr=False)


# ── Internal state shared between scraper thread and Streamlit ────────────────

class ScraperState:
    def __init__(self):
        self._lock = threading.Lock()
        self.standings: list[Standing] = []
        self.race_info: dict[str, Any] = {}   # name, time_remaining, etc.
        self.last_update: float = 0.0
        self.consecutive_errors: int = 0
        self.last_error: str = ""
        self.known_json_url: str = ""          # cached direct endpoint
        self.running: bool = False

    def update(self, standings: list[Standing], race_info: dict):
        with self._lock:
            self.standings = standings
            self.race_info = race_info
            self.last_update = time.time()
            self.consecutive_errors = 0
            self.last_error = ""

    def record_error(self, msg: str):
        with self._lock:
            self.consecutive_errors += 1
            self.last_error = msg

    def snapshot(self):
        with self._lock:
            return list(self.standings), dict(self.race_info)


_state = ScraperState()


def get_state() -> ScraperState:
    return _state


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _normalise_lap(raw: Any) -> str:
    """Turn whatever Apex returns into 'M:SS.mmm' or '' ."""
    if not raw:
        return ""
    s = str(raw).strip()
    if re.match(r"^\d+:\d{2}\.\d+$", s):
        return s
    # Some sites return total seconds as float
    try:
        secs = float(s)
        m, r = divmod(secs, 60)
        return f"{int(m)}:{r:06.3f}"
    except ValueError:
        return s


def _parse_json_standings(data: Any) -> tuple[list[Standing], dict]:
    """
    Parse the JSON blob returned by Apex Timing.
    Apex Timing is not standardised across events; we try the two most common
    shapes:
      A) {"entries": [...], "session": {...}}
      B) Top-level list  [...]
      C) {"data": [...]}
    """
    race_info: dict = {}

    if isinstance(data, dict):
        entries = (
            data.get("entries")
            or data.get("Entries")
            or data.get("data")
            or data.get("rows")
            or []
        )
        session = data.get("session") or data.get("Session") or {}
        race_info = {
            "name": session.get("name", session.get("Name", "")),
            "time_remaining": session.get("timeRemaining", session.get("TimeLeft", "")),
            "status": session.get("status", session.get("Status", "")),
        }
    elif isinstance(data, list):
        entries = data
    else:
        return [], race_info

    standings: list[Standing] = []
    for i, row in enumerate(entries):
        if not isinstance(row, dict):
            continue
        def g(*keys, default=""):
            for k in keys:
                v = row.get(k)
                if v is not None:
                    return v
            return default

        standings.append(Standing(
            pos=int(g("pos", "Pos", "position", "Position", default=i + 1)),
            num=str(g("num", "Num", "kart", "Kart", "number", "Number", default="?")),
            team=str(g("team", "Team", "name", "Name", "driver", "Driver", default="")),
            laps=int(g("laps", "Laps", "lap", "totalLaps", default=0)),
            last_lap=_normalise_lap(g("lastlap", "LastLap", "last_lap", "lastLap")),
            best_lap=_normalise_lap(g("bestlap", "BestLap", "best_lap", "bestLap")),
            gap=str(g("gap", "Gap", "diff", "Diff", default="")),
            pit_count=int(g("pit", "Pit", "pits", "Pits", "pitCount", default=0)),
            status=str(g("status", "Status", default="racing")),
            raw=row,
        ))

    return standings, race_info


def _parse_html_standings(html: str) -> tuple[list[Standing], dict]:
    """Fallback: parse <table> from rendered HTML."""
    soup = BeautifulSoup(html, "html.parser")
    race_info: dict = {}

    # Try to find a time-remaining element (Apex often uses #timeLeft or .session-time)
    for sel in ["#timeLeft", ".session-time", "#sessionTime", ".time-left"]:
        el = soup.select_one(sel)
        if el:
            race_info["time_remaining"] = el.get_text(strip=True)
            break

    table = soup.find("table", id=re.compile(r"(grid|timing|tbl|result)", re.I))
    if table is None:
        table = soup.find("table")
    if table is None:
        return [], race_info

    rows = table.find_all("tr")
    if not rows:
        return [], race_info

    # Detect header row
    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

    def col(cells, *names, default=""):
        for name in names:
            for i, h in enumerate(headers):
                if name in h and i < len(cells):
                    return cells[i].get_text(strip=True)
        return default

    standings: list[Standing] = []
    for r in rows[1:]:
        cells = r.find_all(["td", "th"])
        if not cells:
            continue
        try:
            pos_txt = col(cells, "pos", "rank", "#")
            pos = int(re.sub(r"\D", "", pos_txt) or len(standings) + 1)
        except ValueError:
            pos = len(standings) + 1

        standings.append(Standing(
            pos=pos,
            num=col(cells, "num", "kart", "no", "n°"),
            team=col(cells, "team", "name", "driver", "pilote"),
            laps=int(re.sub(r"\D", "", col(cells, "lap", "tour")) or 0),
            last_lap=_normalise_lap(col(cells, "last", "dernier")),
            best_lap=_normalise_lap(col(cells, "best", "meilleur")),
            gap=col(cells, "gap", "écart", "diff"),
            pit_count=int(re.sub(r"\D", "", col(cells, "pit", "arr")) or 0),
            status="racing",
            raw={},
        ))

    return standings, race_info


# ── HTTP / SSE fetchers ────────────────────────────────────────────────────────

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
})


def _try_direct_json(url: str) -> tuple[list[Standing], dict] | None:
    """Hit the URL directly; succeed only if response is JSON with standings."""
    try:
        resp = _session.get(url, timeout=10)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "json" in ct or resp.text.lstrip().startswith(("[", "{")):
            data = resp.json()
            standings, race_info = _parse_json_standings(data)
            if standings:
                return standings, race_info
    except Exception:
        pass
    return None


def _try_playwright(url: str) -> tuple[list[Standing], dict, str]:
    """
    Load the page with Playwright, intercept XHR/fetch responses that look like
    standings JSON, and return the parsed result + the captured endpoint URL.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning("Playwright not installed — skipping JS intercept")
        return [], {}, ""

    captured: list[tuple[str, Any]] = []

    def handle_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            body = response.json()
            standings, _ = _parse_json_standings(body)
            if standings:
                captured.append((response.url, body))
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("response", handle_response)
            page.goto(url, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
    except Exception as exc:
        log.warning("Playwright error: %s", exc)
        return [], {}, ""

    if captured:
        endpoint_url, body = captured[-1]  # use the most recent
        standings, race_info = _parse_json_standings(body)
        return standings, race_info, endpoint_url

    # Fallback to HTML parse
    standings, race_info = _parse_html_standings(html)
    return standings, race_info, ""


def _try_sse(url: str) -> tuple[list[Standing], dict] | None:
    """Try to read one batch from an SSE stream (text/event-stream)."""
    try:
        import sseclient
        resp = _session.get(url, stream=True, timeout=15)
        ct = resp.headers.get("Content-Type", "")
        if "event-stream" not in ct:
            return None
        client = sseclient.SSEClient(resp)
        for event in client.events():
            if event.data:
                try:
                    data = json.loads(event.data)
                    standings, race_info = _parse_json_standings(data)
                    if standings:
                        return standings, race_info
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_standings(url: str) -> tuple[list[Standing], dict]:
    """
    One-shot fetch. Returns (standings, race_info).
    Raises on unrecoverable failure; caller handles retries.
    """
    state = get_state()

    # 1. Use cached direct endpoint if available
    if state.known_json_url:
        result = _try_direct_json(state.known_json_url)
        if result:
            return result

    # 2. Try the URL as a direct JSON endpoint
    result = _try_direct_json(url)
    if result:
        return result

    # 3. Try SSE on the same URL
    result = _try_sse(url)
    if result:
        return result

    # 4. Try common Apex Timing JSON endpoint patterns derived from the base URL
    base = url.rstrip("/")
    candidates = [
        f"{base}/timing.php",
        f"{base}/server.php",
        f"{base}/data.json",
        f"{base}/api/standings",
        f"{base}/live.json",
    ]
    for candidate in candidates:
        result = _try_direct_json(candidate)
        if result:
            state.known_json_url = candidate
            return result

    # 5. Full Playwright page load + intercept
    standings, race_info, endpoint = _try_playwright(url)
    if standings:
        if endpoint:
            state.known_json_url = endpoint
        return standings, race_info

    raise RuntimeError(
        "Impossible de récupérer les données depuis cette URL. "
        "Vérifiez l'URL et la connexion réseau."
    )


# ── Background polling thread ──────────────────────────────────────────────────

def _polling_loop(url: str, interval: float):
    state = get_state()
    while state.running:
        try:
            standings, race_info = fetch_standings(url)
            state.update(standings, race_info)
            log.debug("Standings updated: %d entries", len(standings))
        except Exception as exc:
            state.record_error(str(exc))
            log.warning("Scraper error: %s", exc)
        time.sleep(interval)


def start_polling(url: str, interval: float = 5.0):
    """Start background polling thread (idempotent)."""
    state = get_state()
    if state.running:
        return
    state.running = True
    t = threading.Thread(target=_polling_loop, args=(url, interval), daemon=True)
    t.start()
    log.info("Polling started: %s (every %.0fs)", url, interval)


def stop_polling():
    get_state().running = False
