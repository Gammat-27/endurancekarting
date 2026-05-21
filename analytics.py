"""
Statistical calculations for driver/stint performance analysis.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd


# ── Lap time conversion ───────────────────────────────────────────────────────

def lap_to_seconds(lap_str: Any) -> float | None:
    """'1:23.456' → 83.456.  Returns None for empty/invalid strings."""
    if not lap_str or str(lap_str).strip() in ("", "-", "--", "0:00.000"):
        return None
    s = str(lap_str).strip()
    m = re.match(r"(\d+):(\d{2})\.(\d+)", s)
    if m:
        mins, secs, ms_str = m.groups()
        ms = float(ms_str) / (10 ** len(ms_str))
        return int(mins) * 60 + int(secs) + ms
    try:
        return float(s)
    except ValueError:
        return None


def seconds_to_lap(secs: Any) -> str:
    """83.456 → '1:23.456'"""
    try:
        if secs is None or np.isnan(float(secs)):
            return "--:--.---"
    except (TypeError, ValueError):
        return "--:--.---"
    secs = float(secs)
    m = int(secs // 60)
    s = secs - m * 60
    return f"{m}:{s:06.3f}"


# ── Filtering helpers ─────────────────────────────────────────────────────────

def _clean_laps(df: pd.DataFrame, exclude_sc: bool = True) -> pd.DataFrame:
    """Remove safety-car laps and outliers (> 150% of overall median)."""
    out = df.copy()
    if "seconds" not in out.columns:
        out["seconds"] = out["lap_time"].apply(lap_to_seconds)
    out = out.dropna(subset=["seconds"])
    out = out[out["seconds"] > 10]  # sanity: min 10 s

    if exclude_sc and "safety_car" in out.columns:
        out = out[~out["safety_car"]]

    if out.empty:
        return out
    med = out["seconds"].median()
    return out[out["seconds"] <= med * 1.5]


# ── Sliding median ────────────────────────────────────────────────────────────

def sliding_median(laps_df: pd.DataFrame, driver: str | None = None, n: int = 5) -> float | None:
    """Median of the last n clean laps. If driver is None, use all laps."""
    df = laps_df.copy()
    if driver:
        df = df[df["driver"] == driver]
    df = _clean_laps(df)
    if df.empty:
        return None
    return float(df["seconds"].tail(n).median())


# ── Per-driver statistics ─────────────────────────────────────────────────────

def compute_driver_stats(laps_df: pd.DataFrame) -> pd.DataFrame:
    if laps_df.empty:
        return pd.DataFrame()

    df = _clean_laps(laps_df)
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
            "Écart-type (s)": round(s.std(), 3) if len(s) > 1 else 0.0,
            "_best_s": s.min(),
            "_med_s": s.median(),
        })
    return pd.DataFrame(rows)


def compute_stint_stats(laps_df: pd.DataFrame) -> pd.DataFrame:
    if laps_df.empty:
        return pd.DataFrame()

    df = _clean_laps(laps_df)
    rows = []
    for (driver, stint), grp in df.groupby(["driver", "stint"]):
        s = grp["seconds"]
        rows.append({
            "Pilote": driver,
            "Relais": int(stint),
            "Tours": len(grp),
            "Meilleur": seconds_to_lap(s.min()),
            "Médiane": seconds_to_lap(s.median()),
            "Moyenne": seconds_to_lap(s.mean()),
            "Dégradation": _degradation(s),
        })
    return pd.DataFrame(rows).sort_values(["Pilote", "Relais"])


def _degradation(series: pd.Series) -> str:
    if len(series) < 3:
        return "N/A"
    x = np.arange(len(series))
    slope = np.polyfit(x, series.values, 1)[0]
    return f"{slope * 1000:+.0f} ms/tour"


def lap_time_series(laps_df: pd.DataFrame, driver: str) -> pd.DataFrame:
    """Return clean seconds-per-lap for a driver (Plotly charts)."""
    df = laps_df[laps_df["driver"] == driver].copy()
    if "seconds" not in df.columns:
        df["seconds"] = df["lap_time"].apply(lap_to_seconds)
    return df[["lap_number", "seconds", "stint"]].dropna(subset=["seconds"])


# ── Kart factor analysis ──────────────────────────────────────────────────────

def compute_kart_factor(laps_df: pd.DataFrame) -> pd.DataFrame:
    """Median lap time per kart number — isolates chassis performance."""
    if laps_df.empty or "kart_number" not in laps_df.columns:
        return pd.DataFrame()

    df = _clean_laps(laps_df)
    df = df[df["kart_number"].notna() & (df["kart_number"] != "")]
    if df.empty or df["kart_number"].nunique() < 2:
        return pd.DataFrame()

    rows = []
    overall_med = df["seconds"].median()
    for kart, grp in df.groupby("kart_number"):
        med = grp["seconds"].median()
        delta = med - overall_med
        rows.append({
            "Kart": kart,
            "Tours": len(grp),
            "Médiane": seconds_to_lap(med),
            "Meilleur": seconds_to_lap(grp["seconds"].min()),
            "Δ médiane (s)": f"{delta:+.3f}",
            "_med_s": med,
        })
    df_out = pd.DataFrame(rows).sort_values("_med_s")
    return df_out.drop(columns=["_med_s"])


# ── Gap calculations ──────────────────────────────────────────────────────────

def parse_gap(gap_str: str) -> float | None:
    if not gap_str or gap_str.strip() in ("", "-", "Leader", "—"):
        return 0.0
    s = gap_str.strip()
    laps_m = re.match(r"[+-]?(\d+)\s*[Ll](?:ap)?", s)
    if laps_m:
        sign = -1 if s.startswith("-") else 1
        return sign * int(laps_m.group(1)) * 10_000
    num_m = re.search(r"[+-]?\d+\.?\d*", s)
    if num_m:
        return float(num_m.group())
    return None


# ── Team summary ──────────────────────────────────────────────────────────────

def compute_team_summary(laps_df: pd.DataFrame, drivers: list[str], min_stints: int) -> pd.DataFrame:
    rows = []
    for driver in drivers:
        drv_laps = laps_df[laps_df["driver"] == driver] if not laps_df.empty else laps_df
        secs_col = drv_laps["seconds"] if "seconds" in drv_laps.columns else drv_laps["lap_time"].apply(lap_to_seconds)
        total_s = secs_col.sum() if not drv_laps.empty else 0.0
        stints_done = int(drv_laps["stint"].nunique()) if not drv_laps.empty else 0
        rows.append({
            "Pilote": driver,
            "Tours": len(drv_laps),
            "Temps roulage": _fmt_duration(total_s),
            "Relais effectués": stints_done,
            "Relais restants (min)": max(0, min_stints - stints_done),
            "_total_s": total_s,
        })
    return pd.DataFrame(rows)


def _fmt_duration(secs: Any) -> str:
    try:
        secs = float(secs)
    except (TypeError, ValueError):
        return "0:00:00"
    if not secs or np.isnan(secs):
        return "0:00:00"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    return f"{h}:{m:02d}:{s:02d}"
