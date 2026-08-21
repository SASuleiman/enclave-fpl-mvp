"""
Fantasy Premier League API client.

Extracted from the original single-file app so the Streamlit layer stays thin
and the graphics engine can be driven from a script or a cron job without
importing any UI code.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests
import streamlit as st

logger = logging.getLogger("enclave.fpl")

BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_LEAGUE_ID = 1138273
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EnclaveFPL/2.0)",
    "Accept": "application/json",
}


def api_get(path: str, params: dict | None = None):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    logger.info("GET %s params=%s", url, params)
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------
# Raw endpoints
# --------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def bootstrap():
    return api_get("bootstrap-static/")


@st.cache_data(ttl=300)
def league_page(league_id: int, page: int = 1):
    return api_get(
        f"leagues-classic/{league_id}/standings/",
        {"page_standings": page, "page_new_entries": 1, "phase": 1},
    )


@st.cache_data(ttl=3600)
def manager_history(entry_id: int):
    return api_get(f"entry/{entry_id}/history/")


@st.cache_data(ttl=3600)
def manager_transfers(entry_id: int):
    return api_get(f"entry/{entry_id}/transfers/")


@st.cache_data(ttl=300)
def manager_picks(entry_id: int, gw: int):
    return api_get(f"entry/{entry_id}/event/{gw}/picks/")


@st.cache_data(ttl=300)
def live_gw(gw: int):
    return api_get(f"event/{gw}/live/")


# --------------------------------------------------------------------------
# Derived
# --------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def current_gw() -> int:
    """The gameweek the league is actually in.

    The original app never resolved this, so every graphic would have had to
    be labelled by hand. `is_current` is set once a gameweek kicks off;
    between deadlines it's the last completed one, which is what you want on
    a results card. Falls back to the next fixture, then to 1 in preseason.
    """
    events = bootstrap().get("events", [])
    for e in events:
        if e.get("is_current"):
            return int(e["id"])
    for e in events:
        if e.get("is_next"):
            return int(e["id"])
    finished = [int(e["id"]) for e in events if e.get("finished")]
    return max(finished) if finished else 1


@st.cache_data(ttl=3600)
def all_managers(league_id: int):
    first = league_page(league_id, 1)
    league = first.get("league", {})
    standings = first.get("standings", {})
    rows = list(standings.get("results", []))

    # Before GW1 settles, standings are empty and everyone sits in new_entries
    # with a different shape. Normalise so the dataframe never sees nulls.
    if not rows:
        rows = list(first.get("new_entries", {}).get("results", []))
        for r in rows:
            r.setdefault(
                "player_name",
                f"{r.get('player_first_name', '')} {r.get('player_last_name', '')}".strip(),
            )
            r.setdefault("total", 0)
            r.setdefault("event_total", 0)
            r.setdefault("rank", 0)
            r.setdefault("last_rank", 0)

    has_next = standings.get("has_next", False)
    page = 2
    while has_next and page <= 1000:
        data = league_page(league_id, page)
        s = data.get("standings", {})
        rows.extend(s.get("results", []))
        has_next = s.get("has_next", False)
        page += 1

    return league, rows, first


def manager_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "Rank": x.get("rank"),
                "Previous Rank": x.get("last_rank"),
                "Manager": x.get("player_name"),
                "Team": x.get("entry_name"),
                "GW Points": x.get("event_total"),
                "Total Points": x.get("total"),
                "Entry ID": x.get("entry"),
            }
            for x in rows
        ]
    )
    if df.empty:
        return df

    for c in ["Rank", "Previous Rank", "GW Points", "Total Points"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    # last_rank is 0 for anyone who wasn't ranked last week — treating that as
    # a real position would report a fake climb of several hundred places.
    prev = df["Previous Rank"].where(df["Previous Rank"] > 0, df["Rank"])
    df["Rank Movement"] = prev - df["Rank"]
    df["Gap to Leader"] = df["Total Points"].max() - df["Total Points"]
    return df


def history_df(data: dict) -> pd.DataFrame:
    df = pd.DataFrame(data.get("current", []))
    if df.empty:
        return df
    df = df.rename(
        columns={
            "event": "GW",
            "points": "Points",
            "total_points": "Total Points",
            "event_transfers": "Transfers",
            "event_transfers_cost": "Transfer Cost",
            "rank_sort": "Overall Rank",
        }
    )
    for c in ["GW", "Points", "Total Points", "Transfers", "Transfer Cost", "Overall Rank"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "value" in df:
        df["Team Value"] = pd.to_numeric(df["value"], errors="coerce") / 10
    if "bank" in df:
        df["Bank"] = pd.to_numeric(df["bank"], errors="coerce") / 10
    return df


def squad_df(entry_id: int, gw: int) -> pd.DataFrame:
    picks = manager_picks(entry_id, gw).get("picks", [])
    bs = bootstrap()
    players = {p["id"]: p for p in bs.get("elements", [])}
    teams = {t["id"]: t["name"] for t in bs.get("teams", [])}
    pos = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    live = {e["id"]: e for e in live_gw(gw).get("elements", [])}

    return pd.DataFrame(
        [
            {
                "Player": players.get(p["element"], {}).get("web_name", p["element"]),
                "Position": pos.get(players.get(p["element"], {}).get("element_type"), ""),
                "Club": teams.get(players.get(p["element"], {}).get("team"), ""),
                "Captain": "⭐" if p.get("is_captain") else "",
                "Vice": "VC" if p.get("is_vice_captain") else "",
                "Multiplier": p.get("multiplier", 1),
                "Squad Position": p.get("position"),
                "GW Points": live.get(p["element"], {}).get("stats", {}).get("total_points", 0),
            }
            for p in picks
        ]
    )


def transfers_df(entry_id: int) -> pd.DataFrame:
    bs = bootstrap()
    players = {p["id"]: p for p in bs.get("elements", [])}
    return pd.DataFrame(
        [
            {
                "GW": t.get("event"),
                "Time": t.get("time"),
                "OUT": players.get(t.get("element_out"), {}).get("web_name", t.get("element_out")),
                "IN": players.get(t.get("element_in"), {}).get("web_name", t.get("element_in")),
                "Cost": t.get("cost", 0),
            }
            for t in manager_transfers(entry_id)
        ]
    )
