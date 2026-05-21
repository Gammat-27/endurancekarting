"""
Karting Endurance Strategy App — Mobile-First Pit Wall
Run with:  streamlit run app.py
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import analytics
import scraper
import state_manager as sm
from config import (
    DASHBOARD_REFRESH_MS,
    DEFAULT_MAX_STINT_MINUTES,
    DEFAULT_MIN_FUEL_STOPS,
    DEFAULT_MIN_PIT_LANE_SECONDS,
    DEFAULT_MIN_STINTS,
    PIT_ACTIVE_REFRESH_MS,
    PIT_CRIT_PCT,
    PIT_WARN_PCT,
    POLL_INTERVAL_SECONDS,
    STINT_CRIT_PCT,
    STINT_WARN_PCT,
)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG & MOBILE CSS
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="🏁 Pit Wall",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

MOBILE_CSS = """
<style>
/* ── Base ── */
html, body, [class*="css"] { font-size: 17px !important; }
.block-container { padding: 0.6rem 0.8rem 2rem !important; max-width: 100% !important; }
section[data-testid="stSidebar"] { display: none; }

/* ── Tabs: bigger touch targets ── */
[data-testid="stTabs"] button {
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    padding: 0.6rem 0.5rem !important;
    min-height: 52px !important;
}

/* ── Metrics: large & card-style ── */
[data-testid="metric-container"] {
    background: #1C1F26;
    border: 2px solid #2e3340;
    border-radius: 14px;
    padding: 14px 12px 10px !important;
    text-align: center;
}
[data-testid="stMetricLabel"] { font-size: 0.78rem !important; color: #9ba3b0 !important; }
[data-testid="stMetricValue"] {
    font-size: 2.0rem !important;
    font-weight: 900 !important;
    color: #FAFAFA !important;
    line-height: 1.1 !important;
}
[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }

/* ── Buttons: big touch targets ── */
.stButton > button {
    font-size: 1.1rem !important;
    font-weight: 800 !important;
    min-height: 56px !important;
    border-radius: 12px !important;
    width: 100% !important;
    padding: 0.6rem 1rem !important;
    letter-spacing: 0.03em;
}
.stButton > button[kind="primary"] { background-color: #E8002D !important; }

/* ── Safety Car banner animation ── */
@keyframes sc-blink {
    0%,49%  { background:#ffcc00; color:#1a1200; border-color:#ffcc00; }
    50%,100%{ background:#4a3800; color:#ffcc00; border-color:#ffcc00; }
}
.sc-banner {
    animation: sc-blink 0.9s infinite;
    border: 3px solid #ffcc00;
    border-radius: 14px;
    padding: 18px;
    text-align: center;
    font-size: 1.7rem;
    font-weight: 900;
    margin-bottom: 12px;
}
.sc-inactive {
    border: 3px solid #2e3340;
    border-radius: 14px;
    padding: 14px;
    text-align: center;
    font-size: 1.1rem;
    font-weight: 700;
    color: #9ba3b0;
    margin-bottom: 12px;
    background: #1C1F26;
}

/* ── Driver zone ── */
.driver-zone {
    background: #0d1f0d;
    border: 3px solid #00E676;
    border-radius: 16px;
    padding: 16px;
    text-align: center;
    margin-bottom: 12px;
}
.driver-name  { font-size: 2.6rem; font-weight: 900; color: #00E676; line-height:1.1; }
.kart-badge   { font-size: 1.2rem; color: #9ba3b0; margin-top: 4px; }

/* ── Pit countdown ── */
.pit-time { font-size: 3.6rem; font-weight: 900; text-align:center; letter-spacing:2px; }
.pit-label{ font-size: 1.1rem; font-weight: 700; text-align:center; margin-bottom:10px; }

/* ── Trend arrows ── */
.trend-up   { color: #ff4444; font-weight: 700; }
.trend-down { color: #00E676; font-weight: 700; }
.trend-flat { color: #9ba3b0; font-weight: 700; }

/* ── Section divider ── */
hr { border-color: #2e3340 !important; margin: 12px 0 !important; }

/* ── Data tables: larger text ── */
[data-testid="stDataFrame"] table { font-size: 0.95rem !important; }

/* ── Alert boxes ── */
.alert-ok  { background:#0d1f0d; border:2px solid #00E676; border-radius:10px; padding:10px; color:#00E676; font-weight:700; text-align:center; }
.alert-warn{ background:#1f1800; border:2px solid #FFAB00; border-radius:10px; padding:10px; color:#FFAB00; font-weight:700; text-align:center; }
.alert-crit{ background:#1f0000; border:2px solid #FF1744; border-radius:10px; padding:10px; color:#FF1744; font-weight:700; text-align:center; }
</style>
"""
st.markdown(MOBILE_CSS, unsafe_allow_html=True)


# ── Plotly dark theme helper ──────────────────────────────────────────────────
def _dark_fig(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        plot_bgcolor="#1C1F26",
        paper_bgcolor="#0E1117",
        font_color="#FAFAFA",
        margin=dict(t=30, b=30, l=10, r=10),
    )
    return fig


# ── HTML component helpers ────────────────────────────────────────────────────

def _stint_gauge_html(elapsed_min: float, max_min: int) -> str:
    if max_min <= 0:
        return ""
    pct = min(100.0, elapsed_min / max_min * 100)
    if pct < STINT_WARN_PCT:
        color, cls, label = "#00E676", "alert-ok", "✅ Nominal"
    elif pct < STINT_CRIT_PCT:
        color, cls, label = "#FFAB00", "alert-warn", "⚠️ Attention"
    else:
        color, cls, label = "#FF1744", "alert-crit", "🚨 CRITIQUE"
    return f"""
    <div style="margin:6px 0">
      <div style="display:flex;justify-content:space-between;margin-bottom:5px">
        <span style="color:{color};font-weight:800;font-size:1.05rem">{label}</span>
        <span style="color:#9ba3b0;font-size:0.95rem">{elapsed_min:.1f} / {max_min} min</span>
      </div>
      <div style="background:#2e3340;border-radius:10px;height:28px;overflow:hidden">
        <div style="width:{pct:.1f}%;background:{color};height:28px;border-radius:10px;
             transition:width 0.4s ease;display:flex;align-items:center;padding-left:8px;
             color:#000;font-weight:900;font-size:0.85rem">{pct:.0f}%</div>
      </div>
    </div>"""


def _pit_countdown_html(elapsed_s: float, total_s: float) -> str:
    remaining = total_s - elapsed_s
    pct = min(100.0, elapsed_s / total_s * 100)
    if remaining > 0:
        mins, secs = int(remaining // 60), int(remaining % 60)
        time_str = f"{mins}:{secs:02d}"
        if pct < PIT_WARN_PCT:
            color, label = "#00E676", "ATTENDRE"
        elif pct < PIT_CRIT_PCT:
            color, label = "#FFAB00", "BIENTÔT…"
        else:
            color, label = "#FF1744", "PRÊT !"
    else:
        time_str, color, label, pct = "00:00", "#00E676", "✅ SORTIE AUTORISÉE", 100.0
    return f"""
    <div style="background:#1C1F26;border:3px solid {color};border-radius:16px;padding:16px;margin:8px 0;text-align:center">
      <div class="pit-time" style="color:{color}">{time_str}</div>
      <div class="pit-label" style="color:{color}">{label}</div>
      <div style="background:#2e3340;border-radius:10px;height:32px;overflow:hidden;margin-top:8px">
        <div style="width:{pct:.1f}%;background:{color};height:32px;border-radius:10px;transition:width 0.4s ease"></div>
      </div>
    </div>"""


def _trend_html(delta_s: float | None) -> str:
    if delta_s is None:
        return '<span class="trend-flat">—</span>'
    sign = f"{delta_s:+.2f}s"
    if delta_s < -0.1:
        return f'<span class="trend-down">▼ {sign}</span>'
    elif delta_s > 0.1:
        return f'<span class="trend-up">▲ {sign}</span>'
    return f'<span class="trend-flat">≈ {sign}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

def _init():
    if "race_state" not in st.session_state:
        loaded = sm.load_state()
        st.session_state.race_state = loaded or sm.RaceState()
    if "last_apex_laps" not in st.session_state:
        st.session_state.last_apex_laps = 0
    if "future_plan" not in st.session_state:
        st.session_state.future_plan = None


_init()
rs: sm.RaceState = st.session_state.race_state
cfg = rs.config
scraper_state = scraper.get_state()


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH (1 s during active pit, 5 s otherwise)
# ══════════════════════════════════════════════════════════════════════════════
_pit_active = rs.pit_in_time > 0 and (time.time() - rs.pit_in_time) < cfg.min_pit_lane_seconds + 10
_refresh_ms = PIT_ACTIVE_REFRESH_MS if _pit_active else DASHBOARD_REFRESH_MS
st_autorefresh(interval=_refresh_ms, key="global_refresh")


# ══════════════════════════════════════════════════════════════════════════════
# APEX SYNC (runs every refresh, not tied to any tab)
# ══════════════════════════════════════════════════════════════════════════════
if scraper_state.running and cfg.our_team_id:
    standings_live, race_info_live = scraper_state.snapshot()
    our_entry = next(
        (s for s in standings_live
         if cfg.our_team_id.lower() in s.team.lower() or cfg.our_team_id == s.num),
        None,
    )
    if our_entry and our_entry.laps > st.session_state.last_apex_laps and rs.current_driver:
        sm.record_lap_from_apex(rs, our_entry.laps, our_entry.last_lap)
        st.session_state.last_apex_laps = our_entry.laps
    sm.update_rival_history(rs, standings_live)
else:
    standings_live, race_info_live = [], {}
    our_entry = None


# ── Helper: find our entry from any standings snapshot ───────────────────────
def _find_our_entry(standings):
    if not cfg.our_team_id or not standings:
        return None
    return next(
        (s for s in standings
         if cfg.our_team_id.lower() in s.team.lower() or cfg.our_team_id == s.num),
        None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab1, tab2, tab3, tab4 = st.tabs([
    "⚙️  Config",
    "🏁  Stands",
    "🧠  Stratégie",
    "📊  Analyse",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    if cfg.locked:
        st.markdown(
            '<div class="alert-warn" style="font-size:1.2rem;margin-bottom:16px">'
            '🔒 Configuration verrouillée — Course en cours</div>',
            unsafe_allow_html=True,
        )
        if st.button("🔓 Déverrouiller la configuration", use_container_width=True):
            cfg.locked = False
            sm.save_config(cfg)
            sm.save_state(rs)
            st.rerun()
        st.stop()

    st.markdown("### ⚙️ Configuration de course")

    col1, col2 = st.columns([1, 1], gap="medium")

    with col1:
        st.markdown("#### 🌐 Connexion Apex Timing")
        apex_url = st.text_input(
            "URL Apex Timing (live)",
            value=cfg.apex_url,
            placeholder="https://www.apex-timing.com/live-timing/XXXXX/",
        )
        our_team = st.text_input(
            "Nom / N° de NOTRE équipe (filtre)",
            value=cfg.our_team_id,
        )

        st.markdown("#### 🏁 Règlement & Durées")
        race_duration = st.number_input("Durée totale (min)", min_value=0,
                                        value=cfg.race_duration_minutes, step=30)
        max_stint = st.number_input("Relais max (min, 0=illimité)", min_value=0,
                                    value=cfg.max_stint_minutes or DEFAULT_MAX_STINT_MINUTES)
        min_pit_m = cfg.min_pit_lane_seconds // 60
        min_pit_s = cfg.min_pit_lane_seconds % 60
        pit_col1, pit_col2 = st.columns(2)
        with pit_col1:
            min_pit_minutes = st.number_input("Pit-lane min — min", min_value=0,
                                              max_value=10, value=min_pit_m)
        with pit_col2:
            min_pit_seconds = st.number_input("Pit-lane min — sec", min_value=0,
                                              max_value=59, value=min_pit_s)
        min_stints = st.number_input("Relais minimum par pilote", min_value=1,
                                     value=cfg.min_stints or DEFAULT_MIN_STINTS)
        min_fuel = st.number_input("Ravitaillements minimum", min_value=0,
                                   value=cfg.min_fuel_stops or DEFAULT_MIN_FUEL_STOPS)

    with col2:
        st.markdown("#### 👥 Équipage")
        drivers_text = st.text_area(
            "Pilotes (un par ligne)",
            value="\n".join(cfg.drivers),
            height=130,
            placeholder="Alice DUPONT\nBob MARTIN\nCarla ROUX",
        )
        drivers = [d.strip() for d in drivers_text.splitlines() if d.strip()]

        if drivers:
            order_text = st.text_area(
                "Ordre de passage planifié (un pilote/ligne, répétitions OK)",
                value="\n".join(cfg.driver_order or drivers),
                height=130,
            )
            driver_order = [d.strip() for d in order_text.splitlines() if d.strip()]
        else:
            driver_order = []

        st.markdown("#### 🎯 Mode Concurrents")
        rivals_mode = st.radio(
            "Suivi des rivaux",
            ["auto", "manual"],
            index=0 if cfg.rivals_mode == "auto" else 1,
            format_func=lambda x: "Automatique (P-1 / P+1)" if x == "auto" else "Manuel (3 équipes)",
            horizontal=True,
        )
        if rivals_mode == "manual":
            rivals_text = st.text_area(
                "Équipes rivales (nom ou n° kart, une par ligne, max 3)",
                value="\n".join(cfg.manual_rivals),
                height=90,
                max_chars=200,
            )
            manual_rivals = [r.strip() for r in rivals_text.splitlines() if r.strip()][:3]
        else:
            manual_rivals = cfg.manual_rivals

        kart_tracking = st.checkbox(
            "Activer le suivi Châssis (Facteur Kart)",
            value=cfg.kart_tracking,
            help="Associe chaque tour au numéro de kart pour comparer les châssis",
        )

    st.markdown("---")
    ca, cb, cc = st.columns([3, 2, 3])
    with ca:
        if st.button("💾 Sauvegarder la configuration", type="primary", use_container_width=True):
            cfg.apex_url = apex_url.strip()
            cfg.our_team_id = our_team.strip()
            cfg.drivers = drivers
            cfg.driver_order = driver_order
            cfg.min_stints = int(min_stints)
            cfg.min_fuel_stops = int(min_fuel)
            cfg.max_stint_minutes = int(max_stint)
            cfg.race_duration_minutes = int(race_duration)
            cfg.min_pit_lane_seconds = int(min_pit_minutes) * 60 + int(min_pit_seconds)
            cfg.rivals_mode = rivals_mode
            cfg.manual_rivals = manual_rivals
            cfg.kart_tracking = kart_tracking
            st.session_state.future_plan = None  # reset plan cache on config change
            sm.save_config(cfg)
            sm.save_state(rs)
            st.success("✅ Configuration sauvegardée")
    with cb:
        if st.button("🔄 Reset COURSE", use_container_width=True):
            rs.laps.clear()
            rs.stints.clear()
            rs.current_driver = ""
            rs.current_stint = 0
            rs.current_kart = ""
            rs.race_started = False
            rs.start_time = 0.0
            rs.safety_car_active = False
            rs.pit_in_time = 0.0
            rs.rival_lap_history.clear()
            rs.rival_prev_laps.clear()
            st.session_state.last_apex_laps = 0
            st.session_state.future_plan = None
            scraper.stop_polling()
            sm.save_state(rs)
            st.warning("Course réinitialisée.")
    with cc:
        st.markdown(
            '<div class="alert-ok" style="font-size:0.9rem">'
            '⬇️ Verrouiller la config évite les modifications accidentelles pendant la course</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    if st.button("🔒 Verrouiller et Initialiser la Course", type="primary", use_container_width=True):
        if not cfg.apex_url:
            st.error("⚠️ Configurez l'URL Apex Timing avant de démarrer.")
        elif not cfg.drivers:
            st.error("⚠️ Ajoutez au moins un pilote.")
        else:
            cfg.locked = True
            sm.save_config(cfg)
            if not rs.race_started:
                sm.start_race(rs)
            if cfg.apex_url and not scraper_state.running:
                scraper.start_polling(cfg.apex_url, POLL_INTERVAL_SECONDS)
            st.success("🚦 Configuration verrouillée — Course démarrée !")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — STANDS (LIVE PIT WALL)
# ══════════════════════════════════════════════════════════════════════════════

with tab2:

    # ── Connexion status & Safety Car ─────────────────────────────────────────
    conn_col, sc_col = st.columns([1, 1], gap="small")

    with conn_col:
        if scraper_state.running:
            if scraper_state.consecutive_errors == 0:
                delta_s = time.time() - scraper_state.last_update if scraper_state.last_update else 0
                st.markdown(
                    f'<div class="alert-ok">🟢 CONNECTÉ — MàJ il y a {delta_s:.0f}s</div>',
                    unsafe_allow_html=True,
                )
            elif scraper_state.consecutive_errors < 4:
                st.markdown(
                    f'<div class="alert-warn">🟡 Reconnexion ({scraper_state.consecutive_errors} err.)</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="alert-crit">🔴 HORS-LIGNE</div>',
                    unsafe_allow_html=True,
                )
            if st.button("⏹️ Déconnecter", use_container_width=True):
                scraper.stop_polling()
                st.rerun()
        else:
            st.markdown('<div class="alert-warn">⏸️ Non connecté</div>', unsafe_allow_html=True)
            if st.button("▶️ Connecter Apex Timing", type="primary", use_container_width=True):
                if cfg.apex_url:
                    scraper.start_polling(cfg.apex_url, POLL_INTERVAL_SECONDS)
                    if not rs.race_started:
                        sm.start_race(rs)
                    st.rerun()
                else:
                    st.error("URL non configurée — allez dans ⚙️ Config")

    with sc_col:
        if rs.safety_car_active:
            st.markdown('<div class="sc-banner">⚠️ SAFETY CAR / FCY ⚠️</div>',
                        unsafe_allow_html=True)
            if st.button("🟢 Reprendre la course", use_container_width=True):
                sm.set_safety_car(rs, False)
                st.rerun()
        else:
            st.markdown('<div class="sc-inactive">🟢 Course normale</div>',
                        unsafe_allow_html=True)
            if st.button("⚠️ SAFETY CAR / FCY", use_container_width=True):
                sm.set_safety_car(rs, True)
                st.rerun()

    st.markdown("---")

    # ── KPI strip ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    oe = our_entry or _find_our_entry(standings_live)
    with k1:
        pos_val = oe.pos if oe else "—"
        st.metric("🏆 Position", pos_val)
    with k2:
        laps_val = oe.laps if oe else (
            max((l.lap_number for l in rs.laps), default=0) if rs.laps else 0
        )
        st.metric("🔢 Tours", laps_val)
    with k3:
        t_rem = race_info_live.get("time_remaining", "—")
        st.metric("⏱️ Temps restant", t_rem)
    with k4:
        if rs.race_started and rs.start_time:
            elapsed = time.time() - rs.start_time
            st.metric("🕐 Course écoulée", str(timedelta(seconds=int(elapsed))))
        else:
            st.metric("🕐 Course écoulée", "—")

    st.markdown("---")

    # ── Driver zone + stint gauge ─────────────────────────────────────────────
    driver_col, pit_col = st.columns([1, 1], gap="medium")

    with driver_col:
        if rs.current_driver:
            elapsed_min = (
                (time.time() - rs.stints[-1].start_time) / 60
                if rs.stints and rs.stints[-1].end_time is None
                else 0.0
            )
            kart_txt = f"Kart n°{rs.current_kart}" if rs.current_kart else ""
            st.markdown(
                f'<div class="driver-zone">'
                f'<div class="driver-name">{rs.current_driver}</div>'
                f'<div class="kart-badge">{kart_txt} &nbsp;·&nbsp; Relais {rs.current_stint}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                _stint_gauge_html(elapsed_min, cfg.max_stint_minutes),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="driver-zone"><div class="driver-name" style="color:#9ba3b0">—</div>'
                '<div class="kart-badge">Aucun pilote déclaré</div></div>',
                unsafe_allow_html=True,
            )

    with pit_col:
        st.markdown("#### 🔧 Module BOX")
        if rs.pit_in_time > 0:
            elapsed_pit = time.time() - rs.pit_in_time
            st.markdown(
                _pit_countdown_html(elapsed_pit, cfg.min_pit_lane_seconds),
                unsafe_allow_html=True,
            )
            if elapsed_pit >= cfg.min_pit_lane_seconds:
                if st.button("✅ Réinitialiser le chrono pit", use_container_width=True):
                    sm.clear_pit_countdown(rs)
                    st.rerun()
        else:
            if st.button(
                "🛑 ENTRÉE STANDS",
                type="primary",
                use_container_width=True,
                help=f"Démarre le chrono pit-lane ({cfg.min_pit_lane_seconds}s min)",
            ):
                sm.declare_pit_in(rs)
                st.rerun()

    st.markdown("---")

    # ── BOX declare next driver out ───────────────────────────────────────────
    st.markdown("#### 🔁 Déclarer le prochain pilote en piste")
    if not cfg.drivers:
        st.info("Configurez les pilotes dans ⚙️ Config")
    else:
        dout_c1, dout_c2 = st.columns([2, 1], gap="small")
        with dout_c1:
            cur_idx = (cfg.drivers.index(rs.current_driver)
                       if rs.current_driver in cfg.drivers else 0)
            new_driver = st.selectbox("Pilote sortant", cfg.drivers, index=cur_idx,
                                      label_visibility="collapsed")
            drow = st.columns([1, 1, 1])
            with drow[0]:
                fuel_stop = st.checkbox("⛽ Ravito")
            kart_num = ""
            if cfg.kart_tracking:
                with drow[1]:
                    kart_num = st.text_input("Kart n°", value=rs.current_kart,
                                             label_visibility="collapsed",
                                             placeholder="Kart n°")
        with dout_c2:
            st.write("")
            if st.button("✅ EN PISTE", type="primary", use_container_width=True):
                sm.declare_driver_in(rs, new_driver, fuel_stop, kart_num)
                st.rerun()

    st.markdown("---")

    # ── Last 5 laps with trend ────────────────────────────────────────────────
    laps_df = sm.laps_to_dataframe(rs)
    if not laps_df.empty and rs.current_driver:
        st.markdown(f"#### 📋 Derniers tours — {rs.current_driver}")
        drv_laps = laps_df[laps_df["driver"] == rs.current_driver].copy()
        drv_clean = drv_laps[drv_laps["seconds"].notna() & (drv_laps["seconds"] > 10)]
        drv_med = drv_clean["seconds"].median() if not drv_clean.empty else None

        recent5 = drv_laps.tail(5).iloc[::-1]
        table_rows = []
        for _, row in recent5.iterrows():
            s = analytics.lap_to_seconds(row["lap_time"])
            delta = (s - drv_med) if (s and drv_med) else None
            sc_flag = "⚠️" if row.get("safety_car") else ""
            table_rows.append({
                "Tour": int(row["lap_number"]),
                "Temps": row["lap_time"],
                "Δ Médiane": _trend_html(delta) if delta is not None else "—",
                "SC": sc_flag,
            })

        if table_rows:
            rows_html = "".join(
                f"<tr>"
                f"<td style='padding:6px 8px;font-size:1.05rem'>{r['Tour']}</td>"
                f"<td style='padding:6px 8px;font-size:1.1rem;font-weight:700'>{r['Temps']}</td>"
                f"<td style='padding:6px 8px'>{r['Δ Médiane']}</td>"
                f"<td style='padding:6px 8px'>{r['SC']}</td>"
                f"</tr>"
                for r in table_rows
            )
            med_str = analytics.seconds_to_lap(drv_med) if drv_med else "—"
            st.markdown(
                f"<div style='margin-bottom:4px;color:#9ba3b0;font-size:0.85rem'>"
                f"Médiane de référence : <b style='color:#FAFAFA'>{med_str}</b></div>"
                f"<table style='width:100%;border-collapse:collapse'>"
                f"<thead><tr style='color:#9ba3b0;font-size:0.8rem'>"
                f"<th style='text-align:left;padding:4px 8px'>Tour</th>"
                f"<th style='text-align:left;padding:4px 8px'>Temps</th>"
                f"<th style='text-align:left;padding:4px 8px'>Δ</th>"
                f"<th style='text-align:left;padding:4px 8px'>SC</th>"
                f"</tr></thead><tbody>{rows_html}</tbody></table>",
                unsafe_allow_html=True,
            )

    # ── Manual lap entry ──────────────────────────────────────────────────────
    with st.expander("✍️ Saisie manuelle / correction de tour"):
        mc1, mc2, mc3 = st.columns([2, 2, 1])
        with mc1:
            manual_time = st.text_input("Temps (ex: 1:23.456)", key="manual_lap")
        with mc2:
            manual_drv = st.selectbox("Pilote", cfg.drivers or ["—"], key="manual_drv")
        with mc3:
            st.write("")
            if st.button("➕", use_container_width=True):
                if manual_time:
                    sm.add_manual_lap(rs, manual_time, manual_drv)
                    st.success("Ajouté.")

    st.markdown("---")

    # ── Radar de course (concurrents) ─────────────────────────────────────────
    st.markdown("#### 🎯 Radar de Course")
    oe_live = _find_our_entry(standings_live)
    our_sliding = analytics.sliding_median(laps_df) if not laps_df.empty else None

    def _rival_row(entry, our_med_s):
        key = str(entry.num) if (entry.num and entry.num not in ("", "?")) else entry.team
        hist = rs.rival_lap_history.get(key, [])
        rival_med = float(np.median(hist[-3:])) if len(hist) >= 1 else None
        if our_med_s and rival_med:
            delta = our_med_s - rival_med  # positive = we're slower (bad), negative = faster (good)
        else:
            delta = None
        rival_med_str = analytics.seconds_to_lap(rival_med) if rival_med else "—"
        our_med_str = analytics.seconds_to_lap(our_med_s) if our_med_s else "—"
        trend = _trend_html(delta)
        return {
            "Pos": entry.pos,
            "Équipe": entry.team[:18],
            "Écart": entry.gap,
            "Rythme rival": rival_med_str,
            "Notre rythme": our_med_str,
            "Tendance": trend,
            "Arrêts": entry.pit_count,
        }

    rivals: list = []
    if standings_live and oe_live:
        if cfg.rivals_mode == "auto":
            ahead = next((s for s in standings_live if s.pos == oe_live.pos - 1), None)
            behind = next((s for s in standings_live if s.pos == oe_live.pos + 1), None)
            rivals = [x for x in [ahead, behind] if x]
        else:
            for rid in cfg.manual_rivals:
                match = next(
                    (s for s in standings_live
                     if rid.lower() in s.team.lower() or rid == s.num),
                    None,
                )
                if match:
                    rivals.append(match)

    if rivals:
        radar_html_rows = "".join(
            f"<tr>"
            f"<td style='padding:7px 8px;font-weight:700'>{r['Pos']}</td>"
            f"<td style='padding:7px 8px'>{r['Équipe']}</td>"
            f"<td style='padding:7px 8px;color:#FFAB00'>{r['Écart']}</td>"
            f"<td style='padding:7px 8px'>{r['Rythme rival']}</td>"
            f"<td style='padding:7px 8px'>{r['Notre rythme']}</td>"
            f"<td style='padding:7px 8px'>{r['Tendance']}</td>"
            f"<td style='padding:7px 8px;text-align:center'>{r['Arrêts']}</td>"
            f"</tr>"
            for r in [_rival_row(e, our_sliding) for e in rivals]
        )
        st.markdown(
            f"<div style='overflow-x:auto'>"
            f"<table style='width:100%;border-collapse:collapse;font-size:0.95rem'>"
            f"<thead><tr style='color:#9ba3b0;font-size:0.78rem;border-bottom:1px solid #2e3340'>"
            f"<th style='padding:4px 8px;text-align:left'>Pos</th>"
            f"<th>Équipe</th><th>Écart</th>"
            f"<th>Rythme rival</th><th>Notre rythme</th>"
            f"<th>Tendance</th><th>Arrêts</th>"
            f"</tr></thead><tbody>{radar_html_rows}</tbody></table></div>",
            unsafe_allow_html=True,
        )
    elif oe_live:
        if cfg.rivals_mode == "auto":
            st.info("Classement seul disponible — pas de voisins détectés.")
        else:
            st.info("Aucun rival manuel trouvé dans le classement.")

    # ── Full standings (collapsed) ────────────────────────────────────────────
    with st.expander("📋 Classement complet Apex Timing"):
        if standings_live:
            rows_s = []
            for s in standings_live:
                is_us = cfg.our_team_id and (
                    cfg.our_team_id.lower() in s.team.lower() or cfg.our_team_id == s.num
                )
                rows_s.append({
                    "Pos": s.pos,
                    "N°": s.num,
                    "Équipe": ("🏎️ " if is_us else "") + s.team,
                    "Tours": s.laps,
                    "Dernier": s.last_lap,
                    "Meilleur": s.best_lap,
                    "Écart": s.gap,
                    "Pits": s.pit_count,
                })
            df_s = pd.DataFrame(rows_s)

            def _hl_us(row):
                if "🏎️" in str(row.get("Équipe", "")):
                    return ["background-color:#2a1500;color:#FFAB00;font-weight:700"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_s.style.apply(_hl_us, axis=1),
                hide_index=True,
                use_container_width=True,
                height=360,
            )
        else:
            st.info("En attente des données Apex Timing…")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — STRATÉGIE & ÉQUIPAGE
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    laps_df = sm.laps_to_dataframe(rs)
    stints_df = sm.stints_to_dataframe(rs)
    alerts = sm.get_alerts(rs)

    # ── Alertes actives ────────────────────────────────────────────────────────
    if alerts:
        for a in alerts:
            cls = "alert-crit" if "🚨" in a else "alert-warn"
            st.markdown(f'<div class="{cls}">{a}</div>', unsafe_allow_html=True)
        st.markdown("")

    # ── Temps de roulage cumulé (bar chart horizontal) ─────────────────────────
    st.markdown("#### ⏱️ Roulage cumulé par pilote")
    if cfg.drivers:
        summary_df = analytics.compute_team_summary(laps_df, cfg.drivers, cfg.min_stints)
        # Stacked bar: clean laps (non SC) vs SC laps
        bar_data = []
        for drv in cfg.drivers:
            drv_laps = laps_df[laps_df["driver"] == drv] if not laps_df.empty else laps_df
            if drv_laps.empty:
                normal_s, sc_s = 0.0, 0.0
            elif "safety_car" in drv_laps.columns:
                normal_s = drv_laps[~drv_laps["safety_car"]]["seconds"].sum()
                sc_s = drv_laps[drv_laps["safety_car"]]["seconds"].sum()
            else:
                normal_s = drv_laps["seconds"].sum()
                sc_s = 0.0
            bar_data.append({"Pilote": drv, "Normal (min)": normal_s / 60, "Safety Car (min)": sc_s / 60})
        bar_df = pd.DataFrame(bar_data)
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            y=bar_df["Pilote"], x=bar_df["Normal (min)"],
            orientation="h", name="Normal", marker_color="#00E676",
            text=[f"{v:.1f} min" for v in bar_df["Normal (min)"]],
            textposition="inside",
        ))
        fig_bar.add_trace(go.Bar(
            y=bar_df["Pilote"], x=bar_df["Safety Car (min)"],
            orientation="h", name="Safety Car", marker_color="#FFAB00",
            text=[f"{v:.1f} min" if v > 0 else "" for v in bar_df["Safety Car (min)"]],
            textposition="inside",
        ))
        fig_bar.update_layout(
            barmode="stack", height=max(150, len(cfg.drivers) * 60),
            xaxis_title="Minutes", showlegend=True,
            legend=dict(orientation="h", y=1.12),
        )
        _dark_fig(fig_bar)
        st.plotly_chart(fig_bar, use_container_width=True)

        # Summary table
        disp = summary_df.drop(columns=["_total_s"], errors="ignore")
        st.dataframe(disp, hide_index=True, use_container_width=True)
    else:
        st.info("Configurez les pilotes dans ⚙️ Config.")

    st.markdown("---")

    # ── Planning dynamique des relais ─────────────────────────────────────────
    st.markdown("#### 📋 Planning dynamique des relais")

    stints_done_count = rs.current_stint  # number of stints opened so far

    # Completed stints (read-only display)
    if not stints_df.empty:
        past = stints_df.copy()
        past["Statut"] = past.apply(
            lambda r: "✅ Terminé" if r["end_time"] else "🏎️ En cours", axis=1
        )
        st.dataframe(
            past[["stint_number", "driver", "kart_number", "duration_min", "fuel_stop", "Statut"]].rename(
                columns={
                    "stint_number": "Relais", "driver": "Pilote",
                    "kart_number": "Kart", "duration_min": "Durée (min)",
                    "fuel_stop": "⛽",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

    # Future stints — editable
    st.markdown("**Relais à venir (modifiable) :**")
    planned_remaining = cfg.driver_order[stints_done_count:] if stints_done_count < len(cfg.driver_order) else []
    default_dur = cfg.max_stint_minutes if cfg.max_stint_minutes > 0 else 45

    # Initialise or re-sync plan cache
    if st.session_state.future_plan is None or len(st.session_state.future_plan) != max(len(planned_remaining), 1):
        st.session_state.future_plan = pd.DataFrame([
            {"Pilote": d, "Durée prévue (min)": default_dur}
            for d in (planned_remaining or [""])
        ])

    edited_plan = st.data_editor(
        st.session_state.future_plan,
        column_config={
            "Pilote": st.column_config.SelectboxColumn(
                "Pilote", options=cfg.drivers + [""], required=False
            ),
            "Durée prévue (min)": st.column_config.NumberColumn(
                "Durée (min)", min_value=1, max_value=300, step=5
            ),
        },
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="future_plan_editor",
    )
    st.session_state.future_plan = edited_plan

    # Compute estimated start/end times
    now_ts = time.time()
    if rs.stints and rs.stints[-1].end_time is None:
        # Currently on track — estimate end of current stint
        next_start_ts = rs.stints[-1].start_time + default_dur * 60
    else:
        next_start_ts = now_ts

    plan_rows = []
    for i, row in edited_plan.iterrows():
        drv = row.get("Pilote", "") or "—"
        dur_min = float(row.get("Durée prévue (min)", default_dur) or default_dur)
        end_ts = next_start_ts + dur_min * 60
        plan_rows.append({
            "Relais": stints_done_count + int(i) + 1,
            "Pilote": drv,
            "Durée": f"{dur_min:.0f} min",
            "Départ estimé": datetime.fromtimestamp(next_start_ts).strftime("%H:%M:%S"),
            "Fin estimée": datetime.fromtimestamp(end_ts).strftime("%H:%M:%S"),
        })
        next_start_ts = end_ts

    if plan_rows:
        race_end = None
        if cfg.race_duration_minutes and rs.start_time:
            race_end = rs.start_time + cfg.race_duration_minutes * 60
        if race_end and plan_rows:
            last_fin_ts = next_start_ts
            delta_min = (last_fin_ts - race_end) / 60
            if abs(delta_min) > 1:
                msg = f"{'⚠️ Plan dépasse' if delta_min > 0 else '⚠️ Plan finit'} la course de {abs(delta_min):.1f} min"
                st.markdown(f'<div class="alert-warn">{msg}</div>', unsafe_allow_html=True)

        st.dataframe(pd.DataFrame(plan_rows), hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — ANALYSE & MÉDIANES
# ══════════════════════════════════════════════════════════════════════════════

with tab4:
    laps_df = sm.laps_to_dataframe(rs)

    if laps_df.empty:
        st.info("Aucun tour enregistré pour l'instant. Commencez la course dans 🏁 Stands.")
        st.stop()

    # ── Stats par pilote ───────────────────────────────────────────────────────
    st.markdown("#### 🏅 Statistiques par pilote")
    driver_stats = analytics.compute_driver_stats(laps_df)
    if not driver_stats.empty:
        display_cols = [c for c in driver_stats.columns if not c.startswith("_")]
        st.dataframe(driver_stats[display_cols], hide_index=True, use_container_width=True)

    # ── Stats par relais ───────────────────────────────────────────────────────
    with st.expander("📋 Détail par relais"):
        stint_stats = analytics.compute_stint_stats(laps_df)
        if not stint_stats.empty:
            st.dataframe(stint_stats, hide_index=True, use_container_width=True)

    st.markdown("---")

    # ── Boxplot comparateur de régularité ─────────────────────────────────────
    st.markdown("#### 📦 Comparateur de régularité (Boxplot)")
    drivers_present = laps_df["driver"].dropna().unique().tolist()
    if drivers_present:
        fig_box = go.Figure()
        palette = ["#00E676", "#FFAB00", "#FF1744", "#40C4FF", "#EA80FC"]
        for i, drv in enumerate(drivers_present):
            drv_clean = analytics._clean_laps(laps_df[laps_df["driver"] == drv])
            if drv_clean.empty:
                continue
            fig_box.add_trace(go.Box(
                y=drv_clean["seconds"],
                name=drv,
                boxmean="sd",
                marker_color=palette[i % len(palette)],
                hovertemplate="<b>%{name}</b><br>%{y:.3f}s<extra></extra>",
            ))
        fig_box.update_layout(
            yaxis_title="Temps (s)",
            showlegend=False,
            height=400,
        )
        _dark_fig(fig_box)
        st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.info("Pas de données de pilotes.")

    # ── Scatter chronos par pilote ─────────────────────────────────────────────
    st.markdown("#### 📉 Évolution des chronos")
    sel_drv = st.selectbox("Pilote", drivers_present, key="perf_drv")
    series = analytics.lap_time_series(laps_df, sel_drv)
    if not series.empty:
        med_s = series["seconds"].median()
        fig_sc = go.Figure()
        palette2 = ["#00E676", "#FFAB00", "#40C4FF", "#FF1744", "#EA80FC"]
        for j, (stint_id, grp) in enumerate(series.groupby("stint")):
            fig_sc.add_trace(go.Scatter(
                x=grp["lap_number"],
                y=grp["seconds"],
                mode="lines+markers",
                name=f"Relais {int(stint_id)}",
                marker_color=palette2[j % len(palette2)],
                hovertemplate="Tour %{x}<br>%{customdata}<extra></extra>",
                customdata=[analytics.seconds_to_lap(s) for s in grp["seconds"]],
            ))
        fig_sc.add_hline(
            y=med_s, line_dash="dash", line_color="#FFAB00",
            annotation_text=f"Médiane {analytics.seconds_to_lap(med_s)}",
            annotation_position="bottom right",
        )
        fig_sc.update_layout(xaxis_title="N° tour", yaxis_title="Temps (s)", height=380)
        _dark_fig(fig_sc)
        st.plotly_chart(fig_sc, use_container_width=True)

    st.markdown("---")

    # ── Kart factor ───────────────────────────────────────────────────────────
    if cfg.kart_tracking:
        st.markdown("#### 🏎️ Analyseur de Châssis (Facteur Kart)")
        kart_df = analytics.compute_kart_factor(laps_df)
        if not kart_df.empty:
            def _color_kart(val):
                try:
                    v = float(val)
                    if v < -0.2:
                        return "color:#00E676;font-weight:700"
                    if v > 0.2:
                        return "color:#FF1744;font-weight:700"
                except (ValueError, TypeError):
                    pass
                return ""
            st.dataframe(
                kart_df.style.map(_color_kart, subset=["Δ médiane (s)"]),
                hide_index=True,
                use_container_width=True,
            )
            best_kart = kart_df.iloc[0]["Kart"]
            best_med = kart_df.iloc[0]["Médiane"]
            st.markdown(
                f'<div class="alert-ok">🏆 Meilleur châssis : Kart <b>{best_kart}</b> — médiane {best_med}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "Pas encore assez de données multi-karts. "
                "Activez le suivi Châssis dans ⚙️ Config et déclarez le numéro de kart à chaque relais."
            )
    else:
        st.info("Suivi Châssis désactivé — activez l'option dans ⚙️ Config pour comparer les karts.")
