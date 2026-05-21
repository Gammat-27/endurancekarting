"""
Race state manager: tracks stints, driver assignments, and persists data to disk.

All state lives here so Streamlit re-runs don't lose it (we store in st.session_state
AND on disk for crash recovery).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from config import RACE_DATA_FILE, SESSION_CONFIG_FILE
from analytics import lap_to_seconds


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class LapRecord:
    lap_number: int
    lap_time: str          # "1:23.456"
    driver: str
    stint: int
    timestamp: float       # unix time


@dataclass
class Stint:
    stint_number: int
    driver: str
    start_time: float      # unix time
    end_time: float | None = None
    fuel_stop: bool = False


@dataclass
class RaceConfig:
    apex_url: str = ""
    our_team_id: str = ""          # team name or kart number
    drivers: list[str] = field(default_factory=list)
    driver_order: list[str] = field(default_factory=list)  # planned rotation
    min_stints: int = 2
    min_fuel_stops: int = 1
    max_stint_minutes: int = 60
    race_duration_minutes: int = 0  # 0 = unknown


@dataclass
class RaceState:
    config: RaceConfig = field(default_factory=RaceConfig)
    laps: list[LapRecord] = field(default_factory=list)
    stints: list[Stint] = field(default_factory=list)
    current_driver: str = ""
    current_stint: int = 0
    race_started: bool = False
    start_time: float = 0.0


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _state_to_dict(state: RaceState) -> dict:
    return {
        "config": asdict(state.config),
        "laps": [asdict(l) for l in state.laps],
        "stints": [asdict(s) for s in state.stints],
        "current_driver": state.current_driver,
        "current_stint": state.current_stint,
        "race_started": state.race_started,
        "start_time": state.start_time,
    }


def _state_from_dict(d: dict) -> RaceState:
    cfg = RaceConfig(**d.get("config", {}))
    laps = [LapRecord(**l) for l in d.get("laps", [])]
    stints = [Stint(**s) for s in d.get("stints", [])]
    return RaceState(
        config=cfg,
        laps=laps,
        stints=stints,
        current_driver=d.get("current_driver", ""),
        current_stint=d.get("current_stint", 0),
        race_started=d.get("race_started", False),
        start_time=d.get("start_time", 0.0),
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def save_state(state: RaceState):
    try:
        RACE_DATA_FILE.write_text(
            json.dumps(_state_to_dict(state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def load_state() -> RaceState | None:
    if not RACE_DATA_FILE.exists():
        return None
    try:
        data = json.loads(RACE_DATA_FILE.read_text(encoding="utf-8"))
        return _state_from_dict(data)
    except Exception:
        return None


def save_config(config: RaceConfig):
    try:
        SESSION_CONFIG_FILE.write_text(
            json.dumps(asdict(config), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def load_config() -> RaceConfig | None:
    if not SESSION_CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_CONFIG_FILE.read_text(encoding="utf-8"))
        return RaceConfig(**data)
    except Exception:
        return None


# ── State operations ──────────────────────────────────────────────────────────

def start_race(state: RaceState):
    state.race_started = True
    state.start_time = time.time()
    save_state(state)


def declare_driver_in(state: RaceState, driver: str, fuel_stop: bool = False):
    """Called when a driver enters the track (pit out)."""
    now = time.time()

    # Close previous stint
    if state.stints and state.stints[-1].end_time is None:
        state.stints[-1].end_time = now
        state.stints[-1].fuel_stop = fuel_stop

    # Open new stint
    state.current_stint += 1
    state.current_driver = driver
    state.stints.append(Stint(
        stint_number=state.current_stint,
        driver=driver,
        start_time=now,
    ))
    save_state(state)


def record_lap_from_apex(
    state: RaceState,
    lap_number: int,
    lap_time: str,
):
    """Called when a new lap for our kart appears on Apex Timing."""
    if not state.current_driver:
        return
    # Avoid duplicates
    existing = {(l.lap_number, l.driver) for l in state.laps}
    if (lap_number, state.current_driver) in existing:
        return
    state.laps.append(LapRecord(
        lap_number=lap_number,
        lap_time=lap_time,
        driver=state.current_driver,
        stint=state.current_stint,
        timestamp=time.time(),
    ))
    save_state(state)


def add_manual_lap(state: RaceState, lap_time: str, driver: str | None = None):
    """Manually add a lap (for offline mode or corrections)."""
    drv = driver or state.current_driver
    if not drv:
        return
    lap_number = max((l.lap_number for l in state.laps), default=0) + 1
    state.laps.append(LapRecord(
        lap_number=lap_number,
        lap_time=lap_time,
        driver=drv,
        stint=state.current_stint,
        timestamp=time.time(),
    ))
    save_state(state)


# ── DataFrames ────────────────────────────────────────────────────────────────

def laps_to_dataframe(state: RaceState) -> pd.DataFrame:
    if not state.laps:
        return pd.DataFrame(
            columns=["lap_number", "lap_time", "driver", "stint", "timestamp", "seconds"]
        )
    df = pd.DataFrame([asdict(l) for l in state.laps])
    df["seconds"] = df["lap_time"].apply(lap_to_seconds)
    return df


def stints_to_dataframe(state: RaceState) -> pd.DataFrame:
    if not state.stints:
        return pd.DataFrame(
            columns=["stint_number", "driver", "start_time", "end_time",
                     "fuel_stop", "duration_min"]
        )
    df = pd.DataFrame([asdict(s) for s in state.stints])
    now = time.time()
    df["duration_min"] = df.apply(
        lambda r: round((r["end_time"] or now - r["start_time"]) / 60, 1),
        axis=1,
    )
    return df


# ── Alerts ────────────────────────────────────────────────────────────────────

def get_alerts(state: RaceState) -> list[str]:
    alerts = []
    if not state.stints:
        return alerts

    # Current stint duration
    current = state.stints[-1]
    if current.end_time is None:
        elapsed_min = (time.time() - current.start_time) / 60
        limit = state.config.max_stint_minutes
        if limit > 0 and elapsed_min >= limit * 0.9:
            alerts.append(
                f"⚠️ {state.current_driver} approche la limite de relais "
                f"({elapsed_min:.0f}/{limit} min)"
            )

    # Fuel stops
    fuel_done = sum(1 for s in state.stints if s.fuel_stop)
    if fuel_done < state.config.min_fuel_stops:
        remaining = state.config.min_fuel_stops - fuel_done
        alerts.append(f"⛽ Ravitaillements restants obligatoires : {remaining}")

    # Minimum stints per driver
    if state.config.drivers:
        df = laps_to_dataframe(state)
        for driver in state.config.drivers:
            drv_stints = len([s for s in state.stints if s.driver == driver])
            if drv_stints < state.config.min_stints:
                remaining = state.config.min_stints - drv_stints
                alerts.append(
                    f"🏎️ {driver} doit encore effectuer {remaining} relais min."
                )

    return alerts
