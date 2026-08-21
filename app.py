"""
Enclave FPL Intelligence — Streamlit entrypoint.

Run:  streamlit run app.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from enclave_fpl import fpl
from enclave_fpl.ui import render_graphics_section

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

st.set_page_config(page_title="Enclave FPL Intelligence", page_icon="⚽", layout="wide")

st.title("⚽ Enclave FPL Intelligence")
st.caption("Data-driven Fantasy Premier League command centre for private Classic Leagues.")

with st.sidebar:
    st.header("League Settings")
    league_id = st.number_input(
        "Classic League ID", min_value=1, value=fpl.DEFAULT_LEAGUE_ID, step=1
    )
    if st.button("🔄 Refresh FPL Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------
try:
    with st.spinner("Connecting to the FPL API…"):
        league, rows, raw_response = fpl.all_managers(int(league_id))
        df = fpl.manager_df(rows)
        gw = fpl.current_gw()
except Exception as e:
    logging.exception("Failed to load FPL data")
    st.error(f"Could not load FPL data: {e}")
    st.stop()

if df.empty:
    st.warning("No managers were returned.")
    with st.expander("🔍 Debug raw API response"):
        st.json(raw_response)
    st.stop()

leader = df.sort_values("Total Points", ascending=False).iloc[0]
best = df.sort_values("GW Points", ascending=False).iloc[0]
climber = df.sort_values("Rank Movement", ascending=False).iloc[0]
faller = df.sort_values("Rank Movement").iloc[0]
league_name = league.get("name", f"League {league_id}")

# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------
st.subheader(f"{league_name} · Gameweek {gw}")
a, b, c, d = st.columns(4)
a.metric("Managers", len(df))
b.metric("Leader", leader["Manager"], f'{int(leader["Total Points"]):,} pts')
c.metric("GW High", best["Manager"], f'{int(best["GW Points"]):,} pts')
d.metric("Biggest Climber", climber["Manager"], f'{int(climber["Rank Movement"]):+d}')

st.divider()
st.header("🏆 League Table")
show = df[
    ["Rank", "Manager", "Team", "GW Points", "Total Points", "Rank Movement", "Gap to Leader"]
].copy()
show["Rank Movement"] = show["Rank Movement"].map(lambda x: f"{int(x):+d}")
show["Gap to Leader"] = show["Gap to Leader"].map(lambda x: f"{int(x):,}")
st.dataframe(show, use_container_width=True, hide_index=True)

st.divider()
st.header("📊 Gameweek Snapshot")
x, y, z = st.columns(3)
x.metric("🚀 Biggest Climber", climber["Manager"], f'{int(climber["Rank Movement"]):+d} positions')
y.metric("💥 Biggest Fall", faller["Manager"], f'{int(faller["Rank Movement"]):+d} positions')
z.metric("🔥 Highest GW Score", best["Manager"], f'{int(best["GW Points"])} pts')

# --------------------------------------------------------------------------
# Graphics — replaces the old PIL create_snapshot_image()
# --------------------------------------------------------------------------
st.divider()
render_graphics_section(df, gw)

# --------------------------------------------------------------------------
# Manager drilldown
# --------------------------------------------------------------------------
st.divider()
st.header("🧠 Manager Intelligence")
manager_map = dict(zip(df["Manager"].astype(str), df["Entry ID"]))
selected = st.selectbox("Select a manager", list(manager_map))
entry_id = int(manager_map[selected])

try:
    hist = fpl.history_df(fpl.manager_history(entry_id))
except Exception as e:
    st.warning(f"Could not load manager history: {e}")
    hist = pd.DataFrame()

if not hist.empty:
    latest = hist.iloc[-1]
    a, b, c, d = st.columns(4)
    a.metric("Season Points", f'{int(latest["Total Points"]):,}')
    b.metric(
        "Current Rank",
        f'{int(latest["Overall Rank"]):,}' if pd.notna(latest.get("Overall Rank")) else "—",
    )
    c.metric("Latest GW", f'{int(latest["Points"]):,}')
    d.metric("Transfers", f'{int(latest["Transfers"]):,}')

    st.subheader("Gameweek Performance")
    st.line_chart(hist[["GW", "Points"]].dropna().set_index("GW")["Points"], height=300)
    with st.expander("Manager history"):
        st.dataframe(hist, use_container_width=True, hide_index=True)

    completed = sorted(hist["GW"].dropna().astype(int).unique().tolist())
    st.subheader("🎯 Gameweek Squad Intelligence")
    if completed:
        pick_gw = st.selectbox("Gameweek", completed, index=len(completed) - 1)
        try:
            st.dataframe(
                fpl.squad_df(entry_id, pick_gw), use_container_width=True, hide_index=True
            )
        except Exception as e:
            st.warning(f"Could not load gameweek picks: {e}")
    else:
        st.info("No completed gameweeks to display yet.")

st.divider()
st.header("🔄 Transfer Activity")
try:
    st.dataframe(fpl.transfers_df(entry_id), use_container_width=True, hide_index=True)
except Exception as e:
    st.warning(f"Could not load transfers: {e}")

st.divider()
st.caption(f"Last refresh: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}")
st.caption(
    "Data source: Fantasy Premier League API. "
    "Independent analytics tool; not affiliated with the Premier League."
)
