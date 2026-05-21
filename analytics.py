"""
Statistical calculations for driver/stint performance analysis.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd


# ── Lap time conversion ───────────────────────────────────────────────────────

def lap_to_seconds(lap_str: str) -> float | None:
    """'1:23.456' → 83.456.  Returns None for empty/invalid strings."""
    if not lap_str or lap_str.strip() in ("", "-", "--", "0:00.000"):
        return None
    m = re.match(r"(\d+):(\d{2})\.(\d+)", lap_str.strip())
    if m:
        mins, secs, ms_str = m.groups()
        ms = float(ms_str) / (10 ** len(ms_str))
        return int(mins) * 60 + int(secs) + ms
    try:
        return float(lap_str)
    except ValueError:
        return None


def seconds_to_lap(secs: float) -> str:
    """83.456 → '1:23.456'"""
    if secs is None or np.isnan(secs):
        return "--:--.---"
    m = int(secs // 60)
    s = secs - m * 60
    return f"{m}:{s:06.3f}"


# ── Per-driver statistics ─────────────────────────────────────────────────────

def compute_driver_stats(laps_df: pd.DataFrame) -> pd.DataFrame:
    """
    Input DataFrame columns expected:
        driver, stint, lap_number, lap_time (str), timestamp (float)

    Returns one row per driver with aggregated stats.
    """
    if laps_df.empty:
        return pd.DataFrame()

    df = laps_df.copy()
    df["seconds"] = df["lap_time"].apply(lap_to_seconds)
    df = df.dropna(subset=["seconds"])

    # Exclude obvious outliers (pit laps, safety car): > 150 % of median
    median_all = df["seconds"].median()
    df = df[df["seconds"] <= median_all * 1.5]

    rows = []
    for driver, grp in df.groupby("driver"):
        s = grp["seconds"]
        rows.append({
            "Pilote": driver,
            "Tours": len(grp),
            "Dernier tour": seconds_to_lap(grp.iloc[-1]["seconds"]),
            "Meilleur tour": seconds_to_lap(s.min()),
            "Moins bon tour": seconds_to_lap(s.max()),
            "Moyenne": seconds_to_lap(s.mean()),
            "Médiane": seconds_to_lap(s.median()),
            "Écart-type (s)": round(s.std(), 3),
            "_best_s": s.min(),
            "_med_s": s.median(),
        })

    return pd.DataFrame(rows)


def compute_stint_stats(laps_df: pd.DataFrame) -> pd.DataFrame:
    """One row per (driver, stint) with the same metrics."""
    if laps_df.empty:
        return pd.DataFrame()

    df = laps_df.copy()
    df["seconds"] = df["lap_time"].apply(lap_to_seconds)
    df = df.dropna(subset=["seconds"])

    median_all = df["seconds"].median() if not df.empty else 999
    df = df[df["seconds"] <= median_all * 1.5]

    rows = []
    for (driver, stint), grp in df.groupby(["driver", "stint"]):
        s = grp["seconds"]
        rows.append({
            "Pilote": driver,
            "Relais": int(stint),
            "Tours": len(grp),
            "Meilleur (s)": round(s.min(), 3),
            "Médiane (s)": round(s.median(), 3),
            "Moyenne (s)": round(s.mean(), 3),
            "Degradation": _degradation(s),
        })

    return pd.DataFrame(rows).sort_values(["Pilote", "Relais"])


def _degradation(series: pd.Series) -> str:
    """Linear regression slope over lap index → degradation in ms/lap."""
    if len(series) < 3:
        return "N/A"
    x = np.arange(len(series))
    slope = np.polyfit(x, series.values, 1)[0]
    return f"{slope * 1000:+.0f} ms/tour"


def lap_time_series(laps_df: pd.DataFrame, driver: str) -> pd.DataFrame:
    """Return seconds-per-lap for a specific driver (for Plotly chart)."""
    df = laps_df[laps_df["driver"] == driver].copy()
    df["seconds"] = df["lap_time"].apply(lap_to_seconds)
    return df[["lap_number", "seconds", "stint"]].dropna(subset=["seconds"])


# ── Gap calculations ──────────────────────────────────────────────────────────

def parse_gap(gap_str: str) -> float | None:
    """
    '+1L' → large positive number (lapped)
    '+12.345' or '12.345' → 12.345
    '-3.2' → -3.2  (we are ahead)
    """
    if not gap_str or gap_str.strip() in ("", "-", "Leader"):
        return 0.0
    s = gap_str.strip()
    laps_m = re.match(r"[+-]?(\d+)\s*[Ll](?:ap)?", s)
    if laps_m:
        sign = -1 if s.startswith("-") else 1
        return sign * int(laps_m.group(1)) * 10_000  # large sentinel
    num_m = re.search(r"[+-]?\d+\.?\d*", s)
    if num_m:
        return float(num_m.group())
    return None


# ── Driver time / stint tracking ──────────────────────────────────────────────

def compute_team_summary(
    laps_df: pd.DataFrame,
    drivers: list[str],
    min_stints: int,
) -> pd.DataFrame:
    """
    Returns per-driver summary for the team panel.
    """
    rows = []
    for driver in drivers:
        drv_laps = laps_df[laps_df["driver"] == driver]
        total_seconds = (
            drv_laps["seconds"].sum()
            if "seconds" in drv_laps.columns
            else drv_laps["lap_time"].apply(lap_to_seconds).sum()
        )
        stints_done = int(drv_laps["stint"].nunique()) if not drv_laps.empty else 0
        stints_left = max(0, min_stints - stints_done)
        rows.append({
            "Pilote": driver,
            "Tours": len(drv_laps),
            "Temps roulage": _fmt_duration(total_seconds),
            "Relais effectués": stints_done,
            "Relais restants (min)": stints_left,
        })
    return pd.DataFrame(rows)


def _fmt_duration(secs: float) -> str:
    if not secs or np.isnan(secs):
        return "0:00:00"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h}:{m:02d}:{s:02d}"
