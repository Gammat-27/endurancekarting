"""
Karting Endurance Strategy App — main entry point.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import time
from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh  # pip install streamlit-autorefresh

import scraper
import analytics
import state_manager as sm
from config import (
    DASHBOARD_REFRESH_MS,
    DEFAULT_MAX_STINT_MINUTES,
    DEFAULT_MIN_FUEL_STOPS,
    DEFAULT_MIN_STINTS,
    POLL_INTERVAL_SECONDS,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🏁 Endurance Karting Strategy",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state init ────────────────────────────────────────────────────────

def _init_session():
    if "race_state" not in st.session_state:
        loaded = sm.load_state()
        st.session_state.race_state = loaded or sm.RaceState()
    if "last_apex_laps" not in st.session_state:
        st.session_state.last_apex_laps = 0


_init_session()
rs: sm.RaceState = st.session_state.race_state


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(
        "https://via.placeholder.com/220x60/E8002D/FFFFFF?text=🏎️+PIT+WALL",
        use_container_width=True,
    )
    st.markdown("---")
    page = st.radio(
        "Navigation",
        ["⚙️ Paramétrage", "🏁 Pit Wall (Live)", "📊 Dashboard", "📈 Performances", "👥 Équipe & Relais"],
        label_visibility="collapsed",
    )
    st.markdown("---")

    # Connexion status
    scraper_state = scraper.get_state()
    if scraper_state.running:
        if scraper_state.consecutive_errors == 0:
            st.success("🟢 Apex Timing connecté")
        elif scraper_state.consecutive_errors < 4:
            st.warning(f"🟡 Reconnexion ({scraper_state.consecutive_errors} err.)")
        else:
            st.error(f"🔴 Hors-ligne\n{scraper_state.last_error[:80]}")
    else:
        st.info("⏸️ Non connecté")

    if rs.race_started and rs.current_driver:
        elapsed = time.time() - rs.stints[-1].start_time if rs.stints else 0
        st.metric("Pilote en piste", rs.current_driver,
                  delta=f"Relais {rs.current_stint} — {elapsed/60:.1f} min")

    # Alerts in sidebar
    alerts = sm.get_alerts(rs)
    if alerts:
        st.markdown("---")
        for a in alerts:
            st.warning(a)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — PARAMÉTRAGE
# ═══════════════════════════════════════════════════════════════════════════════

if page == "⚙️ Paramétrage":
    st.title("⚙️ Paramétrage de course")
    cfg = rs.config

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🌐 Connexion Apex Timing")
        apex_url = st.text_input(
            "URL Apex Timing (live)",
            value=cfg.apex_url,
            placeholder="https://www.apex-timing.com/live-timing/XXXXX/",
        )
        our_team = st.text_input(
            "Nom / Numéro de NOTRE équipe",
            value=cfg.our_team_id,
            help="Utilisé pour filtrer les données et associer les tours à nos pilotes",
        )

        st.subheader("🏁 Paramètres de course")
        race_duration = st.number_input(
            "Durée de la course (min)", min_value=0, value=cfg.race_duration_minutes, step=30
        )
        min_stints = st.number_input(
            "Relais minimum par pilote", min_value=1, value=cfg.min_stints or DEFAULT_MIN_STINTS
        )
        min_fuel = st.number_input(
            "Ravitaillements minimum", min_value=0, value=cfg.min_fuel_stops or DEFAULT_MIN_FUEL_STOPS
        )
        max_stint = st.number_input(
            "Durée max d'un relais (min, 0 = illimité)",
            min_value=0,
            value=cfg.max_stint_minutes or DEFAULT_MAX_STINT_MINUTES,
        )

    with col2:
        st.subheader("👥 Gestion de l'équipe")

        drivers_text = st.text_area(
            "Pilotes (un par ligne : Prénom NOM)",
            value="\n".join(cfg.drivers),
            height=150,
            placeholder="Alice DUPONT\nBob MARTIN\nCarla ROUX",
        )
        drivers = [d.strip() for d in drivers_text.splitlines() if d.strip()]

        if drivers:
            st.subheader("📋 Ordre de passage planifié")
            order_text = st.text_area(
                "Ordre des relais (un pilote par ligne, peut se répéter)",
                value="\n".join(cfg.driver_order or drivers),
                height=150,
            )
            driver_order = [d.strip() for d in order_text.splitlines() if d.strip()]
        else:
            driver_order = []

    st.markdown("---")
    c1, c2, c3 = st.columns([2, 2, 4])
    with c1:
        if st.button("💾 Sauvegarder la configuration", type="primary", use_container_width=True):
            cfg.apex_url = apex_url.strip()
            cfg.our_team_id = our_team.strip()
            cfg.drivers = drivers
            cfg.driver_order = driver_order
            cfg.min_stints = int(min_stints)
            cfg.min_fuel_stops = int(min_fuel)
            cfg.max_stint_minutes = int(max_stint)
            cfg.race_duration_minutes = int(race_duration)
            sm.save_config(cfg)
            sm.save_state(rs)
            st.success("Configuration sauvegardée ✅")

    with c2:
        if st.button("🔄 Réinitialiser la COURSE (garde la config)", use_container_width=True):
            rs.laps.clear()
            rs.stints.clear()
            rs.current_driver = ""
            rs.current_stint = 0
            rs.race_started = False
            rs.start_time = 0.0
            scraper.stop_polling()
            sm.save_state(rs)
            st.warning("Course réinitialisée.")

    with c3:
        st.info(
            "💡 Sauvegardez d'abord la configuration, puis allez sur **🏁 Pit Wall** "
            "pour démarrer la connexion et gérer les relais."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — PIT WALL (LIVE)
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🏁 Pit Wall (Live)":
    st_autorefresh(interval=DASHBOARD_REFRESH_MS, key="pit_wall_refresh")
    st.title("🏁 Pit Wall — Contrôle en direct")

    cfg = rs.config
    scraper_state = scraper.get_state()

    # ── Connection control ─────────────────────────────────────────────────────
    col_conn1, col_conn2, col_conn3 = st.columns([3, 1, 1])
    with col_conn1:
        st.markdown(f"**URL :** `{cfg.apex_url or 'Non configurée'}`")
    with col_conn2:
        if not scraper_state.running:
            if st.button("▶️ Démarrer la connexion", type="primary", use_container_width=True):
                if cfg.apex_url:
                    scraper.start_polling(cfg.apex_url, POLL_INTERVAL_SECONDS)
                    if not rs.race_started:
                        sm.start_race(rs)
                    st.rerun()
                else:
                    st.error("Configurez d'abord l'URL Apex Timing.")
        else:
            if st.button("⏹️ Arrêter", use_container_width=True):
                scraper.stop_polling()
                st.rerun()
    with col_conn3:
        if scraper_state.last_update:
            delta_s = time.time() - scraper_state.last_update
            st.caption(f"MàJ il y a {delta_s:.0f}s")

    # ── Sync Apex laps to our kart ─────────────────────────────────────────────
    if scraper_state.running and cfg.our_team_id and rs.current_driver:
        standings, _ = scraper_state.snapshot()
        our_entry = next(
            (s for s in standings
             if cfg.our_team_id.lower() in s.team.lower()
             or cfg.our_team_id == s.num),
            None,
        )
        if our_entry and our_entry.laps > st.session_state.last_apex_laps:
            sm.record_lap_from_apex(rs, our_entry.laps, our_entry.last_lap)
            st.session_state.last_apex_laps = our_entry.laps

    st.markdown("---")

    # ── Driver declaration ─────────────────────────────────────────────────────
    st.subheader("🔁 Déclarer un pilote en piste")
    if not cfg.drivers:
        st.warning("Aucun pilote configuré. Allez dans ⚙️ Paramétrage.")
    else:
        dc1, dc2, dc3, dc4 = st.columns([3, 2, 1, 2])
        with dc1:
            new_driver = st.selectbox(
                "Pilote qui entre en piste",
                cfg.drivers,
                index=0 if not rs.current_driver
                else (cfg.drivers.index(rs.current_driver)
                      if rs.current_driver in cfg.drivers else 0),
            )
        with dc2:
            fuel_stop = st.checkbox("⛽ Ravitaillement lors de cet arrêt")
        with dc3:
            st.write("")
            st.write("")
            if st.button("✅ Valider", type="primary", use_container_width=True):
                sm.declare_driver_in(rs, new_driver, fuel_stop)
                st.rerun()
        with dc4:
            if rs.current_driver:
                elapsed_s = time.time() - rs.stints[-1].start_time if rs.stints else 0
                st.metric(
                    f"🏎️ {rs.current_driver}",
                    f"Relais {rs.current_stint}",
                    delta=f"{elapsed_s/60:.1f} min en piste",
                )

    # ── Manual lap entry ───────────────────────────────────────────────────────
    with st.expander("✍️ Saisie manuelle d'un tour (mode hors-ligne / correction)"):
        mc1, mc2, mc3 = st.columns([2, 2, 1])
        with mc1:
            manual_time = st.text_input("Temps (ex: 1:23.456)", key="manual_lap")
        with mc2:
            manual_driver = st.selectbox(
                "Pilote", cfg.drivers or ["—"], key="manual_driver_sel"
            )
        with mc3:
            st.write("")
            st.write("")
            if st.button("➕ Ajouter", use_container_width=True):
                if manual_time:
                    sm.add_manual_lap(rs, manual_time, manual_driver)
                    st.success("Tour ajouté.")

    st.markdown("---")

    # ── Live standings table ───────────────────────────────────────────────────
    st.subheader("🏆 Classement en direct (Apex Timing)")
    standings, race_info = scraper_state.snapshot()

    if race_info.get("time_remaining"):
        ri1, ri2 = st.columns(2)
        ri1.metric("Temps restant", race_info.get("time_remaining", "--"))
        ri2.metric("Session", race_info.get("name", "--"))

    if standings:
        rows = []
        for s in standings:
            is_us = (
                cfg.our_team_id.lower() in s.team.lower()
                or cfg.our_team_id == s.num
            )
            rows.append({
                "Pos": s.pos,
                "Dossard": s.num,
                "Équipe": ("🏎️ " if is_us else "") + s.team,
                "Tours": s.laps,
                "Dernier tour": s.last_lap,
                "Meilleur tour": s.best_lap,
                "Écart": s.gap,
                "Arrêts": s.pit_count,
            })
        df = pd.DataFrame(rows)

        def highlight_us(row):
            if "🏎️" in str(row.get("Équipe", "")):
                return ["background-color: #3a1a00; color: #ffaa00; font-weight: bold"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df.style.apply(highlight_us, axis=1),
            hide_index=True,
            use_container_width=True,
            height=400,
        )
    else:
        st.info("En attente des données Apex Timing…")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — DASHBOARD GLOBAL
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📊 Dashboard":
    st_autorefresh(interval=DASHBOARD_REFRESH_MS, key="dashboard_refresh")
    st.title("📊 Dashboard Global — Stratégie")

    cfg = rs.config
    scraper_state = scraper.get_state()
    standings, race_info = scraper_state.snapshot()

    # Find our entry
    our_entry = None
    if standings and cfg.our_team_id:
        our_entry = next(
            (s for s in standings
             if cfg.our_team_id.lower() in s.team.lower()
             or cfg.our_team_id == s.num),
            None,
        )

    # ── KPI row ───────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        pos = our_entry.pos if our_entry else "—"
        st.metric("Position", pos)
    with k2:
        laps = our_entry.laps if our_entry else (
            max((l.lap_number for l in rs.laps), default=0) if rs.laps else 0
        )
        st.metric("Tours couverts", laps)
    with k3:
        st.metric("Temps restant", race_info.get("time_remaining", "—"))
    with k4:
        # Gap to car ahead
        if our_entry and our_entry.pos > 1:
            ahead = next((s for s in standings if s.pos == our_entry.pos - 1), None)
            gap_ahead = f"+{ahead.gap if ahead else '—'}" if ahead else "—"
        else:
            gap_ahead = "Leader 🥇" if our_entry else "—"
        st.metric("Gap voiture devant", gap_ahead)
    with k5:
        if our_entry:
            behind = next((s for s in standings if s.pos == our_entry.pos + 1), None)
            gap_behind = behind.gap if behind else "—"
        else:
            gap_behind = "—"
        st.metric("Gap voiture derrière", gap_behind)

    st.markdown("---")

    # ── Best laps ─────────────────────────────────────────────────────────────
    col_bl1, col_bl2, col_bl3 = st.columns(3)
    with col_bl1:
        if standings:
            best_overall = min(
                (s.best_lap for s in standings if s.best_lap),
                default="—",
                key=lambda x: analytics.lap_to_seconds(x) or 9999,
            )
        else:
            best_overall = "—"
        st.metric("Meilleur tour absolu (course)", best_overall)
    with col_bl2:
        our_best = our_entry.best_lap if our_entry else (
            analytics.seconds_to_lap(
                min((analytics.lap_to_seconds(l.lap_time) or 9999 for l in rs.laps), default=None) or 0
            ) if rs.laps else "—"
        )
        st.metric("Notre meilleur tour", our_best or "—")
    with col_bl3:
        if rs.race_started and rs.start_time:
            elapsed = time.time() - rs.start_time
            st.metric("Temps de course écoulé", str(timedelta(seconds=int(elapsed))))
        else:
            st.metric("Temps de course écoulé", "—")

    # ── Position chart over laps (if we have our own lap data) ────────────────
    if len(rs.laps) > 2:
        st.markdown("---")
        st.subheader("📉 Évolution des temps au tour (notre équipe)")
        laps_df = sm.laps_to_dataframe(rs)
        fig = px.scatter(
            laps_df,
            x="lap_number",
            y="seconds",
            color="driver",
            hover_data=["lap_time", "stint"],
            title="",
            labels={"lap_number": "N° tour", "seconds": "Temps (s)", "driver": "Pilote"},
        )
        fig.update_traces(mode="lines+markers")
        fig.update_layout(
            plot_bgcolor="#1C1F26",
            paper_bgcolor="#1C1F26",
            font_color="#FAFAFA",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Recent laps table ─────────────────────────────────────────────────────
    if rs.laps:
        st.subheader("🕐 10 derniers tours enregistrés")
        recent = sm.laps_to_dataframe(rs).tail(10).iloc[::-1]
        st.dataframe(
            recent[["lap_number", "lap_time", "driver", "stint"]].rename(
                columns={
                    "lap_number": "Tour",
                    "lap_time": "Temps",
                    "driver": "Pilote",
                    "stint": "Relais",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — PERFORMANCES
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📈 Performances":
    st.title("📈 Module Performances")

    laps_df = sm.laps_to_dataframe(rs)

    if laps_df.empty:
        st.info("Aucun tour enregistré pour l'instant.")
        st.stop()

    # ── Stats globales par pilote ─────────────────────────────────────────────
    st.subheader("🏅 Statistiques par pilote")
    driver_stats = analytics.compute_driver_stats(laps_df)
    if not driver_stats.empty:
        display_cols = [c for c in driver_stats.columns if not c.startswith("_")]
        st.dataframe(driver_stats[display_cols], hide_index=True, use_container_width=True)

    # ── Stats par relais ──────────────────────────────────────────────────────
    st.subheader("📋 Détail par relais")
    stint_stats = analytics.compute_stint_stats(laps_df)
    if not stint_stats.empty:
        st.dataframe(stint_stats, hide_index=True, use_container_width=True)

    st.markdown("---")

    # ── Per-driver lap time chart ─────────────────────────────────────────────
    st.subheader("📉 Évolution des chronos par pilote")
    drivers = laps_df["driver"].unique().tolist()
    if not drivers:
        st.info("Pas de données.")
        st.stop()

    selected_driver = st.selectbox("Pilote", drivers)
    series = analytics.lap_time_series(laps_df, selected_driver)

    if series.empty:
        st.info("Pas de tours valides pour ce pilote.")
    else:
        # Median reference line
        med = series["seconds"].median()

        fig = go.Figure()
        for stint_id, grp in series.groupby("stint"):
            fig.add_trace(go.Scatter(
                x=grp["lap_number"],
                y=grp["seconds"],
                mode="lines+markers",
                name=f"Relais {int(stint_id)}",
                hovertemplate="Tour %{x}<br>%{customdata}<extra></extra>",
                customdata=[analytics.seconds_to_lap(s) for s in grp["seconds"]],
            ))

        fig.add_hline(
            y=med,
            line_dash="dash",
            line_color="#E8002D",
            annotation_text=f"Médiane {analytics.seconds_to_lap(med)}",
            annotation_position="bottom right",
        )

        fig.update_layout(
            xaxis_title="N° tour",
            yaxis_title="Temps (s)",
            plot_bgcolor="#1C1F26",
            paper_bgcolor="#1C1F26",
            font_color="#FAFAFA",
            legend_title="Relais",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Distribution histogram
        fig2 = px.histogram(
            series,
            x="seconds",
            nbins=20,
            color="stint",
            title=f"Distribution des chronos — {selected_driver}",
            labels={"seconds": "Temps (s)"},
        )
        fig2.update_layout(
            plot_bgcolor="#1C1F26",
            paper_bgcolor="#1C1F26",
            font_color="#FAFAFA",
        )
        st.plotly_chart(fig2, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — ÉQUIPE & RELAIS
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "👥 Équipe & Relais":
    st.title("👥 Équipe & Gestion des Relais")

    cfg = rs.config
    if not cfg.drivers:
        st.warning("Aucun pilote configuré. Allez dans ⚙️ Paramétrage.")
        st.stop()

    laps_df = sm.laps_to_dataframe(rs)

    # ── Team summary ─────────────────────────────────────────────────────────
    st.subheader("🧑‍🤝‍🧑 Récapitulatif de l'équipe")
    summary_df = analytics.compute_team_summary(laps_df, cfg.drivers, cfg.min_stints)

    def color_remaining(val):
        if isinstance(val, int) and val > 0:
            return "background-color: #4a0000; color: #ff6666; font-weight: bold"
        return ""

    st.dataframe(
        summary_df.style.applymap(color_remaining, subset=["Relais restants (min)"]),
        hide_index=True,
        use_container_width=True,
    )

    # ── Stint log ─────────────────────────────────────────────────────────────
    st.subheader("📋 Journal des relais")
    stints_df = sm.stints_to_dataframe(rs)
    if stints_df.empty:
        st.info("Aucun relais enregistré.")
    else:
        display = stints_df[["stint_number", "driver", "duration_min", "fuel_stop"]].rename(
            columns={
                "stint_number": "Relais",
                "driver": "Pilote",
                "duration_min": "Durée (min)",
                "fuel_stop": "⛽ Ravito",
            }
        )
        st.dataframe(display, hide_index=True, use_container_width=True)

        # Gantt-style bar chart per driver
        st.subheader("⏱️ Durée des relais par pilote")
        fig = px.bar(
            stints_df,
            x="duration_min",
            y="driver",
            color="driver",
            orientation="h",
            text="duration_min",
            labels={"duration_min": "Durée (min)", "driver": "Pilote"},
        )
        fig.update_layout(
            showlegend=False,
            plot_bgcolor="#1C1F26",
            paper_bgcolor="#1C1F26",
            font_color="#FAFAFA",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Fuel stops ────────────────────────────────────────────────────────────
    st.subheader("⛽ Suivi des ravitaillements")
    fuel_done = sum(1 for s in rs.stints if s.fuel_stop)
    fuel_needed = max(0, cfg.min_fuel_stops - fuel_done)
    col_f1, col_f2 = st.columns(2)
    col_f1.metric("Ravitaillements effectués", fuel_done)
    col_f2.metric("Ravitaillements restants (min)", fuel_needed,
                  delta_color="inverse" if fuel_needed > 0 else "off")

    # ── Planned rotation ──────────────────────────────────────────────────────
    if cfg.driver_order:
        st.subheader("📋 Planning théorique des relais")
        plan_rows = [
            {"Ordre": i + 1, "Pilote": d}
            for i, d in enumerate(cfg.driver_order)
        ]
        plan_df = pd.DataFrame(plan_rows)
        # Highlight completed stints
        actual = [s.driver for s in rs.stints]
        def highlight_done(row):
            idx = int(row["Ordre"]) - 1
            if idx < len(actual):
                if actual[idx] == row["Pilote"]:
                    return ["background-color: #003300; color: #00ff00"] * len(row)
                return ["background-color: #330000; color: #ff4444"] * len(row)
            return [""] * len(row)

        st.dataframe(
            plan_df.style.apply(highlight_done, axis=1),
            hide_index=True,
            use_container_width=True,
            height=min(400, 40 + len(plan_rows) * 35),
        )
