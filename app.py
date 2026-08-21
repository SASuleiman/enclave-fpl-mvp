import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone
import logging

# Configure Python logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FPL_Intelligence")

st.set_page_config(page_title="Enclave FPL Intelligence", page_icon="⚽", layout="wide")

BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_LEAGUE_ID = 1138273
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EnclaveFPL/1.0)", "Accept": "application/json"}

def api_get(path, params=None):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    logger.info(f"Fetching API: {url} | Params: {params}")
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    logger.info(f"API Response Status: {r.status_code}")
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=300)
def league_page(league_id, page=1):
    return api_get(f"leagues-classic/{league_id}/standings/", {
        "page_standings": page, "page_new_entries": 1, "phase": 1
    })

@st.cache_data(ttl=3600)
def all_managers(league_id):
    logger.info(f"Starting manager fetch for League ID: {league_id}")
    first = league_page(league_id, 1)
    
    # Log raw keys to inspect returned JSON structure
    logger.info(f"First page response keys: {list(first.keys())}")
    
    league = first.get("league", {})
    standings_data = first.get("standings", {})
    rows = list(standings_data.get("results", []))
    
    logger.info(f"League name retrieved: {league.get('name')}")
    logger.info(f"First page returned {len(rows)} managers")

    if not rows:
        logger.warning(f"No results found in 'standings.results'. Standings payload: {standings_data}")

    has_next = standings_data.get("has_next", False)
    page = 2
    while has_next and page <= 1000:
        logger.info(f"Fetching page {page}...")
        data = league_page(league_id, page)
        standings = data.get("standings", {})
        new_rows = standings.get("results", [])
        rows.extend(new_rows)
        has_next = standings.get("has_next", False)
        page += 1
        
    logger.info(f"Total managers fetched: {len(rows)}")
    return league, rows, first # Returning 'first' for raw UI debug inspection

# --- UI Setup ---
with st.sidebar:
    st.header("League Settings")
    league_id = st.number_input("Classic League ID", min_value=1, value=DEFAULT_LEAGUE_ID, step=1)
    if st.button("🔄 Refresh FPL Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    with st.spinner("Connecting to the FPL API..."):
        league, rows, raw_response = all_managers(int(league_id))
        df = manager_df(rows)
except Exception as e:
    logger.exception("Failed to load FPL data")
    st.error(f"Could not load FPL data: {e}")
    st.stop()

if df.empty:
    st.warning("No managers were returned.")
    # In-app debug expander to view raw response payload
    with st.expander("🔍 Debug Raw API Response"):
        st.json(raw_response)
    st.stop()
