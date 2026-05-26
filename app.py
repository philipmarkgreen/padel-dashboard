import streamlit as st
import pandas as pd
import trueskill
from collections import defaultdict
from datetime import datetime, timedelta

# --- 1. PAGE SETUP ---
st.set_page_config(page_title="Makeni Padel Leaderboard", page_icon="🎾", layout="wide")
st.title("🏆 Makeni Padel TrueSkill Rankings")

# This link pulls your Google Sheet data live
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR4T2HqnoW1RxaYmW_FXX2NIoI-h03inlqO1rlXHcHah1vze_dKw1tP-NX8CS957dt42AwmgzsgDjtI/pub?output=csv"

# --- 2. DATA LOADING ---
@st.cache_data(ttl=600)
def load_data():
    df = pd.read_csv(SHEET_URL)
    df = df.dropna(subset=['Team 1A', 'Team 1B', 'Team 2A', 'Team 2B', 'Result'])
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=False, errors='coerce')
    
    # --- AUTOMATIC ROUND NUMBERING (Fixed) ---
    # 1. Assign rounds first! This relies on the original top-to-bottom CSV order.
    df['Round'] = df.groupby('Date').cumcount() + 1
    
    # 2. NOW sort by Date AND Round. This guarantees the chronological sequence 
    # is mathematically locked in place forever.
    df = df.sort_values(by=['Date', 'Round'])
    
    return df

data = load_data()

# --- 3. TRUESKILL MATH ---
env = trueskill.TrueSkill(draw_probability=0.05)
env.make_as_global()
players = defaultdict(trueskill.Rating)

aliases = {
    "Gorden": "Gordon", "Mike": "Mike W", "MikeF": "Mike F",
    "Mark VDM": "Mark", "Bran Case": "Brandon C", 
    "Brandon ©": "Brandon C", "Brandon": "Brandon C", "Nic M": "Nic"
}

def clean_name(name):
    return aliases.get(name.strip(), name.strip())

stats = defaultdict(lambda: {"W": 0, "L": 0, "T": 0, "Played": 0})
last_played = {}

for _, row in data.iterrows():
    t1a = clean_name(str(row['Team 1A']))
    t1b = clean_name(str(row['Team 1B']))
    t2a = clean_name(str(row['Team 2A']))
    t2b = clean_name(str(row['Team 2B']))
    
    result = str(row.get('Result', '')).strip().lower()
    match_date = row['Date']
    
    is_tie = ("tie" in result)
    
    # Determine winner based on Team columns
    if "1" in result:
        w1, w2, l1, l2 = t1a, t1b, t2a, t2b
    elif "2" in result:
        w1, w2, l1, l2 = t2a, t2b, t1a, t1b
    else: # Default to tie logic
        w1, w2, l1, l2 = t1a, t1b, t2a, t2b
        
    for p in [w1, w2, l1, l2]:
        stats[p]["Played"] += 1
        last_played[p] = match_date
        
    for p in [w1, w2]:
        if is_tie: stats[p]["T"] += 1
        else: stats[p]["W"] += 1
    for p in [l1, l2]:
        if is_tie: stats[p]["T"] += 1
        else: stats[p]["L"] += 1

    t1, t2 = [players[w1], players[w2]], [players[l1], players[l2]]
    
    if is_tie:
        new_t1, new_t2 = trueskill.rate([t1, t2], ranks=[0, 0])
    else:
        new_t1, new_t2 = trueskill.rate([t1, t2], ranks=[0, 1])
        
    players[w1], players[w2] = new_t1[0], new_t1[1]
    players[l1], players[l2] = new_t2[0], new_t2[1]

# --- 4. BUILD LEADERBOARD ---
latest_match = data['Date'].max()
cutoff_date = latest_match - timedelta(days=90) # This is your 3-month window

leaderboard_data = []
for name, rating in players.items():
    # Only include players who have a rating sigma < 4.5 (reliable data) 
    # AND who have played within the last 90 days
    if rating.sigma < 4.5 and last_played.get(name, datetime.min) >= cutoff_date:
        cons_skill = rating.mu - (3 * rating.sigma)
        win_pct = (stats[name]["W"] / stats[name]["Played"]) * 100
        record = f"{stats[name]['W']}W - {stats[name]['L']}L - {stats[name]['T']}T"
        leaderboard_data.append({"Player": name, "Score": round(cons_skill, 2), "Win Rate %": round(win_pct, 1), "Record": record})
        
df_leaderboard = pd.DataFrame(leaderboard_data).sort_values(by="Score", ascending=False).reset_index(drop=True)
df_leaderboard.index += 1

# --- 5. RENDER DASHBOARD ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"Top 10 Active Players (As of {latest_match.strftime('%b %d, %Y')})")
    # Add .head(10) to slice the table for the top 10 players only!
    st.dataframe(df_leaderboard.head(10), width="stretch")

with col2:
    st.subheader("Match Simulator")
    all_active_players = sorted(df_leaderboard['Player'].tolist())
    
    p1 = st.selectbox("Team A Player 1", all_active_players, index=0)
    p2 = st.selectbox("Team A Player 2", all_active_players, index=1)
    p3 = st.selectbox("Team B Player 1", all_active_players, index=2)
    p4 = st.selectbox("Team B Player 2", all_active_players, index=3)
    
    if st.button("Calculate Odds"):
        avg_A = (players[p1].mu + players[p2].mu) / 2
        avg_B = (players[p3].mu + players[p4].mu) / 2
        prob_A = 1 / (1 + 10**((avg_B - avg_A) / 8))
        st.metric("Team A Win Prob", f"{prob_A * 100:.1f}%")
        st.metric("Team B Win Prob", f"{(1 - prob_A) * 100:.1f}%")

    st.divider()
    st.subheader("Tonight's Pairings Generator")
    players_input = st.text_area(
        "Paste tonight's players (comma separated)", 
        "Marc, Clyde, Kurt, Owen, Mike W, Terry, Phil, Nic M"
    )
    
    if st.button("Generate Fair Teams"):
        raw_names = [n.strip() for n in players_input.split(',')]
        valid_players = []
        
        # Match names to the leaderboard
        for n in raw_names:
            cleaned = clean_name(n)
            if cleaned in df_leaderboard['Player'].values:
                # Get their conservative score from the leaderboard
                score = df_leaderboard[df_leaderboard['Player'] == cleaned]['Score'].values[0]
                valid_players.append((cleaned, score))
            elif n: # If they typed a name that isn't in the system
                st.warning(f"⚠️ Player '{n}' not found in active rankings. Check spelling.")
                
        # Make sure we have an even number of players for teams of 2
        if len(valid_players) % 2 != 0:
            st.error(f"You entered {len(valid_players)} valid players. We need an even number to make teams!")
        elif len(valid_players) > 0:
            # Sort players by score, highest to lowest
            valid_players.sort(key=lambda x: x[1], reverse=True)
            
            # Snake Draft: Pair highest with lowest
            teams = []
            n_teams = len(valid_players) // 2
            for i in range(n_teams):
                p1 = valid_players[i]
                p2 = valid_players[len(valid_players) - 1 - i]
                teams.append({
                    "name": f"Team {chr(65+i)}", # Team A, Team B, etc.
                    "p1": p1[0], "p2": p2[0],
                    "score": p1[1] + p2[1]
                })
                
            st.success("✅ **Optimal Pairings Generated:**")
            for t in teams:
                st.markdown(f"**{t['name']}**: {t['p1']} & {t['p2']} *(Combined Score: {t['score']:.1f})*")
