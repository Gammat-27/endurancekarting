"""
Race state manager: tracks stints, driver assignments, and persists data to disk.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from config import RACE_DATA_FILE, SESSION_CONFIG_FILE
from analytics import lap_to_seconds


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class LapRecord:
    lap_number: int
    lap_time: str
    driver: str
    stint: int
    timestamp: float
    safety_car: bool = False
    kart_number: str = ""


@dataclass
class Stint:
    stint_number: int
    driver: str
    start_time: float
    end_time: float | None = None
    fuel_stop: bool = False
    kart_number: str = ""


@dataclass
class RaceConfig:
    apex_url: str = ""
    our_team_id: str = ""
    drivers: list[str] = field(default_factory=list)
    driver_order: list[str] = field(default_factory=list)
    min_stints: int = 2
    min_fuel_stops: int = 1
    max_stint_minutes: int = 45
    race_duration_minutes: int = 0
    min_pit_lane_seconds: int = 90
    rivals_mode: str = "auto"              # "auto" or "manual"
    manual_rivals: list[str] = field(default_factory=list)
    kart_tracking: bool = False
    locked: bool = False


@dataclass
class RaceState:
    config: RaceConfig = field(default_factory=RaceConfig)
    laps: list[LapRecord] = field(default_factory=list)
    stints: list[Stint] = field(default_factory=list)
    current_driver: str = ""
    current_stint: int = 0
    current_kart: str = ""
    race_started: bool = False
    start_time: float = 0.0
    safety_car_active: bool = False
    pit_in_time: float = 0.0
    rival_lap_history: dict = field(default_factory=dict)   # key -> [s, s, ...]
    rival_prev_laps: dict = field(default_factory=dict)     # key -> last lap count


# ── Serialisation ─────────────────────────────────────────────────────────────

def _state_to_dict(state: RaceState) -> dict:
    return {
        "config": asdict(state.config),
        "laps": [asdict(l) for l in state.laps],
        "stints": [asdict(s) for s in state.stints],
        "current_driver": state.current_driver,
        "current_stint": state.current_stint,
        "current_kart": state.current_kart,
        "race_started": state.race_started,
        "start_time": state.start_time,
        "safety_car_active": state.safety_car_active,
        "pit_in_time": state.pit_in_time,
        "rival_lap_history": state.rival_lap_history,
        "rival_prev_laps": state.rival_prev_laps,
    }


def _state_from_dict(d: dict) -> RaceState:
    cd = d.get("config", {})
    cfg = RaceConfig(
        apex_url=cd.get("apex_url", ""),
        our_team_id=cd.get("our_team_id", ""),
        drivers=cd.get("drivers", []),
        driver_order=cd.get("driver_order", []),
        min_stints=cd.get("min_stints", 2),
        min_fuel_stops=cd.get("min_fuel_stops", 1),
        max_stint_minutes=cd.get("max_stint_minutes", 45),
        race_duration_minutes=cd.get("race_duration_minutes", 0),
        min_pit_lane_seconds=cd.get("min_pit_lane_seconds", 90),
        rivals_mode=cd.get("rivals_mode", "auto"),
        manual_rivals=cd.get("manual_rivals", []),
        kart_tracking=cd.get("kart_tracking", False),
        locked=cd.get("locked", False),
    )
    laps = [
        LapRecord(
            lap_number=l["lap_number"],
            lap_time=l["lap_time"],
            driver=l["driver"],
            stint=l["stint"],
            timestamp=l["timestamp"],
            safety_car=l.get("safety_car", False),
            kart_number=l.get("kart_number", ""),
        )
        for l in d.get("laps", [])
    ]
    stints = [
        Stint(
            stint_number=s["stint_number"],
            driver=s["driver"],
            start_time=s["start_time"],
            end_time=s.get("end_time"),
            fuel_stop=s.get("fuel_stop", False),
            kart_number=s.get("kart_number", ""),
        )
        for s in d.get("stints", [])
    ]
    return RaceState(
        config=cfg,
        laps=laps,
        stints=stints,
        current_driver=d.get("current_driver", ""),
        current_stint=d.get("current_stint", 0),
        current_kart=d.get("current_kart", ""),
        race_started=d.get("race_started", False),
        start_time=d.get("start_time", 0.0),
        safety_car_active=d.get("safety_car_active", False),
        pit_in_time=d.get("pit_in_time", 0.0),
        rival_lap_history=d.get("rival_lap_history", {}),
        rival_prev_laps=d.get("rival_prev_laps", {}),
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
        cfg_keys = RaceConfig.__dataclass_fields__.keys()
        return RaceConfig(**{k: v for k, v in data.items() if k in cfg_keys})
    except Exception:
        return None


# ── Race operations ───────────────────────────────────────────────────────────

def start_race(state: RaceState):
    state.race_started = True
    state.start_time = time.time()
    save_state(state)


def set_safety_car(state: RaceState, active: bool):
    state.safety_car_active = active
    save_state(state)


def declare_pit_in(state: RaceState):
    state.pit_in_time = time.time()
    save_state(state)


def clear_pit_countdown(state: RaceState):
    state.pit_in_time = 0.0
    save_state(state)


def declare_driver_in(
    state: RaceState,
    driver: str,
    fuel_stop: bool = False,
    kart_number: str = "",
):
    now = time.time()
    if state.stints and state.stints[-1].end_time is None:
        state.stints[-1].end_time = now
        state.stints[-1].fuel_stop = fuel_stop

    state.current_stint += 1
    state.current_driver = driver
    state.current_kart = kart_number
    state.pit_in_time = 0.0  # clear pit countdown on pit-out
    state.stints.append(Stint(
        stint_number=state.current_stint,
        driver=driver,
        start_time=now,
        kart_number=kart_number,
    ))
    save_state(state)


def record_lap_from_apex(state: RaceState, lap_number: int, lap_time: str):
    if not state.current_driver:
        return
    existing = {(l.lap_number, l.driver) for l in state.laps}
    if (lap_number, state.current_driver) in existing:
        return
    state.laps.append(LapRecord(
        lap_number=lap_number,
        lap_time=lap_time,
        driver=state.current_driver,
        stint=state.current_stint,
        timestamp=time.time(),
        safety_car=state.safety_car_active,
        kart_number=state.current_kart,
    ))
    save_state(state)


def add_manual_lap(state: RaceState, lap_time: str, driver: str | None = None):
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
        safety_car=state.safety_car_active,
        kart_number=state.current_kart,
    ))
    save_state(state)


def update_rival_history(state: RaceState, standings: list[Any]):
    """Track lap-by-lap times for rivals from Apex standings updates."""
    changed = False
    for entry in standings:
        key = str(entry.num) if (entry.num and entry.num not in ("", "?")) else entry.team
        if not key:
            continue
        prev = state.rival_prev_laps.get(key, 0)
        if entry.laps > prev and entry.last_lap:
            secs = lap_to_seconds(entry.last_lap)
            if secs and 10 < secs < 600:
                hist = state.rival_lap_history.get(key, [])
                hist.append(secs)
                state.rival_lap_history[key] = hist[-5:]
                changed = True
        state.rival_prev_laps[key] = entry.laps
    if changed:
        save_state(state)


# ── DataFrames ────────────────────────────────────────────────────────────────

def laps_to_dataframe(state: RaceState) -> pd.DataFrame:
    if not state.laps:
        return pd.DataFrame(
            columns=["lap_number", "lap_time", "driver", "stint",
                     "timestamp", "seconds", "safety_car", "kart_number"]
        )
    df = pd.DataFrame([asdict(l) for l in state.laps])
    df["seconds"] = df["lap_time"].apply(lap_to_seconds)
    return df


def stints_to_dataframe(state: RaceState) -> pd.DataFrame:
    if not state.stints:
        return pd.DataFrame(
            columns=["stint_number", "driver", "start_time", "end_time",
                     "fuel_stop", "kart_number", "duration_min"]
        )
    df = pd.DataFrame([asdict(s) for s in state.stints])
    now = time.time()
    df["duration_min"] = df.apply(
        lambda r: round(
            ((r["end_time"] if pd.notna(r["end_time"]) else now) - r["start_time"]) / 60, 1
        ),
        axis=1,
    )
    return df


# ── Alerts ────────────────────────────────────────────────────────────────────

def get_alerts(state: RaceState) -> list[str]:
    alerts = []
    if not state.stints:
        return alerts

    current = state.stints[-1]
    if current.end_time is None:
        elapsed_min = (time.time() - current.start_time) / 60
        limit = state.config.max_stint_minutes
        if limit > 0 and elapsed_min >= limit * 0.92:
            alerts.append(
                f"🚨 {state.current_driver} — limite relais imminente "
                f"({elapsed_min:.0f}/{limit} min)"
            )
        elif limit > 0 and elapsed_min >= limit * 0.78:
            alerts.append(
                f"⚠️ {state.current_driver} — approche la limite relais "
                f"({elapsed_min:.0f}/{limit} min)"
            )

    fuel_done = sum(1 for s in state.stints if s.fuel_stop)
    if fuel_done < state.config.min_fuel_stops:
        alerts.append(
            f"⛽ Ravitaillements obligatoires restants : "
            f"{state.config.min_fuel_stops - fuel_done}"
        )

    if state.config.drivers:
        for driver in state.config.drivers:
            drv_stints = sum(1 for s in state.stints if s.driver == driver)
            if drv_stints < state.config.min_stints:
                rem = state.config.min_stints - drv_stints
                alerts.append(f"🏎️ {driver} : {rem} relais min. restant(s)")

    return alerts
