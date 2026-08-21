import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone
import logging
import io
from PIL import Image, ImageDraw, ImageFont

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
    
    league = first.get("league", {})
    standings_data = first.get("standings", {})
    rows = list(standings_data.get("results", []))
    
    # If standings are empty (e.g., before GW1 finishes), check new_entries
    if not rows:
        new_entries = first.get("new_entries", {})
        rows = list(new_entries.get("results", []))
        for r in rows:
            if "player_name" not in r:
                r["player_name"] = f"{r.get('player_first_name', '')} {r.get('player_last_name', '')}".strip()
            if "total" not in r:
                r["total"] = 0
                r["event_total"] = 0
            if "rank" not in r:
                r["rank"] = 0
            if "last_rank" not in r:
                r["last_rank"] = 0
                
    has_next = standings_data.get("has_next", False)
    page = 2
    while has_next and page <= 1000:
        data = league_page(league_id, page)
        standings = data.get("standings", {})
        rows.extend(standings.get("results", []))
        has_next = standings.get("has_next", False)
        page += 1
        
    return league, rows, first

@st.cache_data(ttl=3600)
def manager_history(entry_id):
    return api_get(f"entry/{entry_id}/history/")

@st.cache_data(ttl=3600)
def manager_transfers(entry_id):
    return api_get(f"entry/{entry_id}/transfers/")

@st.cache_data(ttl=300)
def manager_picks(entry_id, gw):
    return api_get(f"entry/{entry_id}/event/{gw}/picks/")

@st.cache_data(ttl=3600)
def bootstrap():
    return api_get("bootstrap-static/")

@st.cache_data(ttl=300)
def live_gw(gw):
    return api_get(f"event/{gw}/live/")

def manager_df(rows):
    df = pd.DataFrame([{
        "Rank": x.get("rank"), "Previous Rank": x.get("last_rank"),
        "Manager": x.get("player_name"), "Team": x.get("entry_name"),
        "GW Points": x.get("event_total"), "Total Points": x.get("total"),
        "Entry ID": x.get("entry")
    } for x in rows])
    if not df.empty:
        df["Rank Movement"] = df["Previous Rank"].fillna(0) - df["Rank"].fillna(0)
        df["Gap to Leader"] = df["Total Points"].max() - df["Total Points"]
    return df

def history_df(data):
    df = pd.DataFrame(data.get("current", []))
    if df.empty: return df
    df = df.rename(columns={"event": "GW", "points": "Points",
                            "total_points": "Total Points",
                            "event_transfers": "Transfers",
                            "event_transfers_cost": "Transfer Cost",
                            "rank_sort": "Overall Rank"})
    for c in ["GW", "Points", "Total Points", "Transfers", "Transfer Cost", "Overall Rank"]:
        if c in df: df[c] = pd.to_numeric(df[c], errors="coerce")
    if "value" in df: df["Team Value"] = pd.to_numeric(df["value"], errors="coerce") / 10
    if "bank" in df: df["Bank"] = pd.to_numeric(df["bank"], errors="coerce") / 10
    return df

def create_snapshot_image(league_name, leader, best, climber, faller):
    """Generates an image summary of the GW for sharing."""
    img = Image.new('RGB', (800, 600), color=(17, 24, 39))
    draw = ImageDraw.Draw(img)
    
    try:
        # Tries to load standard fonts, falls back to default if not installed
        font_title = ImageFont.truetype("Arial", 40)
        font_header = ImageFont.truetype("Arial", 24)
        font_text = ImageFont.truetype("Arial", 20)
    except:
        font_title = font_header = font_text = ImageFont.load_default()

    # Draw Title
    draw.text((400, 50), f"{league_name} - GW Snapshot", fill="white", font=font_title, anchor="mt")

    # Top Manager Card
    draw.rectangle([50, 150, 375, 300], fill=(31, 41, 55), outline=(59, 130, 246), width=2)
    draw.text((60, 160), "🏆 Top Manager", fill=(96, 165, 250), font=font_header)
    draw.text((60, 210), f"{leader['Manager']}", fill="white", font=font_text)
    draw.text((60, 250), f"Total: {leader['Total Points']} pts", fill=(156, 163, 175), font=font_text)

    # GW High Card
    draw.rectangle([425, 150, 750, 300], fill=(31, 41, 55), outline=(16, 185, 129), width=2)
    draw.text((435, 160), "🚀 GW High Score", fill=(52, 211, 153), font=font_header)
    draw.text((435, 210), f"{best['Manager']}", fill="white", font=font_text)
    draw.text((435, 250), f"GW Pts: {best['GW Points']} pts", fill=(156, 163, 175), font=font_text)

    # Biggest Climber Card
    draw.rectangle([50, 350, 375, 500], fill=(31, 41, 55), outline=(245, 158, 11), width=2)
    draw.text((60, 360), "📈 Biggest Climber", fill=(251, 191, 36), font=font_header)
    draw.text((60, 410), f"{climber['Manager']}", fill="white", font=font_text)
    draw.text((60, 450), f"+{int(climber['Rank Movement'])} ranks", fill=(156, 163, 175), font=font_text)

    # Biggest Faller Card
    draw.rectangle([425, 350, 750, 500], fill=(31, 41, 55), outline=(239, 68, 68), width=2)
    draw.text((435, 360), "📉 Biggest Fall", fill=(248, 113, 113), font=font_header)
    draw.text((435, 410), f"{faller['Manager']}", fill="white", font=font_text)
    draw.text((435, 450), f"{int(faller['Rank Movement'])} ranks", fill=(156, 163, 175), font=font_text)

    # Convert to bytes
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    return img_buf

# --- UI Setup ---
st.title("⚽ Enclave FPL Intelligence")
st.caption("Data-driven Fantasy Premier League command centre for private Classic Leagues.")

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
    with st.expander("🔍 Debug Raw API Response"):
        st.json(raw_response)
    st.stop()

leader = df.sort_values("Total Points", ascending=False).iloc[0]
best = df.sort_values("GW Points", ascending=False).iloc[0]
worst = df.sort_values("GW Points").iloc[0]
climber = df.sort_values("Rank Movement", ascending=False).iloc[0]
faller = df.sort_values("Rank Movement").iloc[0]

league_name = league.get("name", f"League {league_id}")
st.subheader(league_name)
a,b,c,d = st.columns(4)
a.metric("Managers", len(df))
b.metric("Leader", leader["Manager"], f'{int(leader["Total Points"]):,} pts')
c.metric("GW High", best["Manager"], f'{int(best["GW Points"]):,} pts')
d.metric("Biggest Climber", climber["Manager"], f'+{int(climber["Rank Movement"])}' if climber["Rank Movement"] > 0 else int(climber["Rank Movement"]))

st.divider()
st.header("🏆 League Table")
show = df[["Rank","Manager","Team","GW Points","Total Points","Rank Movement","Gap to Leader"]].copy()
show["Rank Movement"] = show["Rank Movement"].map(lambda x: f"+{int(x)}" if x > 0 else str(int(x)))
show["Gap to Leader"] = show["Gap to Leader"].map(lambda x: f"{int(x):,}")
st.dataframe(show, use_container_width=True, hide_index=True)

st.divider()
st.header("📊 Gameweek Snapshot")
x,y,z = st.columns(3)
x.metric("🚀 Biggest Climber", climber["Manager"], f'{int(climber["Rank Movement"]):+d} positions')
y.metric("💥 Biggest Fall", faller["Manager"], f'{int(faller["Rank Movement"]):+d} positions')
z.metric("🔥 Highest GW Score", best["Manager"], f'{int(best["GW Points"])} pts')

# Download Button for the Image
generated_image = create_snapshot_image(league_name, leader, best, climber, faller)
st.download_button(
    label="📸 Download Snapshot for Group Chat",
    data=generated_image,
    file_name=f"gw_snapshot_{datetime.now().strftime('%Y%m%d')}.png",
    mime="image/png",
    use_container_width=True
)

st.divider()
st.header("🧠 Manager Intelligence")
manager_map = dict(zip(df["Manager"].astype(str), df["Entry ID"]))
selected = st.selectbox("Select a manager", list(manager_map))
entry_id = int(manager_map[selected])

try:
    hist = history_df(manager_history(entry_id))
except Exception as e:
    st.warning(f"Could not load manager history: {e}")
    hist = pd.DataFrame()

if not hist.empty:
    latest = hist.iloc[-1]
    a,b,c,d = st.columns(4)
    a.metric("Season Points", f'{int(latest["Total Points"]):,}')
    b.metric("Current Rank", f'{int(latest["Overall Rank"]):,}' if pd.notna(latest.get("Overall Rank")) else "—")
    c.metric("Latest GW", f'{int(latest["Points"]):,}')
    d.metric("Transfers", f'{int(latest["Transfers"]):,}')
    st.subheader("Gameweek Performance")
    chart = hist[["GW","Points"]].dropna().set_index("GW")
    st.line_chart(chart["Points"], height=300)
    with st.expander("Manager history"):
        st.dataframe(hist, use_container_width=True, hide_index=True)

    completed = sorted(hist["GW"].dropna().astype(int).unique().tolist())
    st.subheader("🎯 Gameweek Squad Intelligence")
    if completed:
        gw = st.selectbox("Gameweek", completed, index=len(completed)-1)
        try:
            picks = manager_picks(entry_id, gw).get("picks", [])
            bs = bootstrap()
            players = {p["id"]: p for p in bs.get("elements", [])}
            teams = {t["id"]: t["name"] for t in bs.get("teams", [])}
            pos = {1:"GKP",2:"DEF",3:"MID",4:"FWD"}
            live = {e["id"]: e for e in live_gw(gw).get("elements", [])}
            rows2 = []
            for p in picks:
                pl = players.get(p["element"], {})
                pts = live.get(p["element"], {}).get("stats", {}).get("total_points", 0)
                rows2.append({
                    "Player": pl.get("web_name", p["element"]),
                    "Position": pos.get(pl.get("element_type"), ""),
                    "Club": teams.get(pl.get("team"), ""),
                    "Captain": "⭐" if p.get("is_captain") else "",
                    "Vice": "VC" if p.get("is_vice_captain") else "",
                    "Multiplier": p.get("multiplier", 1),
                    "Squad Position": p.get("position"),
                    "GW Points": pts
                })
            st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)
        except Exception as e:
            st.warning(f"Could not load Gameweek picks: {e}")
    else:
        st.info("No completed gameweeks to display yet.")

st.divider()
st.header("🔄 Transfer Activity")
try:
    transfers = manager_transfers(entry_id)
    bs = bootstrap()
    players = {p["id"]: p for p in bs.get("elements", [])}
    trows = [{
        "GW": t.get("event"), "Time": t.get("time"),
        "OUT": players.get(t.get("element_out"), {}).get("web_name", t.get("element_out")),
        "IN": players.get(t.get("element_in"), {}).get("web_name", t.get("element_in")),
        "Cost": t.get("cost", 0)
    } for t in transfers]
    st.dataframe(pd.DataFrame(trows), use_container_width=True, hide_index=True)
except Exception as e:
    st.warning(f"Could not load transfers: {e}")

st.divider()
st.caption(f"Last refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
st.caption("Data source: Fantasy Premier League API. Independent analytics tool; not affiliated with the Premier League.")
