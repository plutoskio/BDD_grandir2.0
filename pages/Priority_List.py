
import streamlit as st
import json
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Base, Nursery, Job, Candidate, Metier, Application

st.set_page_config(page_title="Priority Worklist", page_icon="⚡", layout="wide")

# DB Setup
DB_URL = "sqlite:///grandir.db"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)
session = Session()

# ... (Helpers)
from math import radians, cos, sin, asin, sqrt

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 # Radius of earth in kilometers. Use 3956 for miles
    return c * r

@st.cache_data
def load_data():
    # Load all needed data
    nurseries = pd.read_sql(session.query(Nursery).statement, session.bind)
    jobs = pd.read_sql(session.query(Job).statement, session.bind)
    candidates = pd.read_sql(session.query(Candidate).statement, session.bind)
    metiers = pd.read_sql(session.query(Metier).statement, session.bind)
    
    # Merge Jobs with Nurseries and Metiers
    jobs = jobs.merge(nurseries, left_on='nursery_name', right_on='name', suffixes=('_job', '_nurs'))
    jobs = jobs.merge(metiers, left_on='metier_id', right_on='id', suffixes=('', '_met'))
    
    return jobs, candidates

def get_diploma_list(row):
    """Safe extraction of normalized diplomas list"""
    try:
        norm_json = row.get('normalized_diplomas')
        if norm_json:
            l = json.loads(norm_json)
            if l: return l
    except: pass
    
    # Fallback
    single = row.get('normalized_diploma')
    if single and single != 'UNKNOWN': return [single]
    
    return []

# --- Custom CSS ---
st.markdown("""
<style>
    .stDataFrame { border: 1px solid #ddd; }
    .dip-tag {
        background-color: #e0f2f1;
        color: #00695c;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.85em;
        margin-right: 4px;
        display: inline-block;
        margin-bottom: 4px;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Priority Worklist")

jobs_df, candidates_df = load_data()

# Filters
with st.sidebar:
    st.header("Search Filters")
    max_dist = st.slider("Max Distance (km)", 5, 50, 20)

matches = []
open_jobs = jobs_df[jobs_df['status'] == 'Open']

with st.spinner("Calculating optimal matches..."):
    for _, job in open_jobs.iterrows():
        n_lat, n_lon = job['latitude'], job['longitude']
        if pd.isna(n_lat): continue
        
        # Urgency
        col_name = 'urgency_color_nurs' if 'urgency_color_nurs' in job else 'urgency_color'
        u_score = 1
        u_color = str(job.get(col_name, '')).lower()
        if 'rouge' in u_color: u_score = 3
        elif 'orange' in u_color: u_score = 2
        
        # Requirements (Standardized)
        reqs_json = job.get('required_diplomas', '[]')
        try:
            required_dips = json.loads(reqs_json)
        except:
            required_dips = []
            
        for _, cand in candidates_df.iterrows():
            if pd.isna(cand['latitude']): continue
            
            dist = haversine(cand['longitude'], cand['latitude'], n_lon, n_lat)
            if dist > max_dist: continue
            
            # Prereq Score (Standardized)
            p_score = 0
            
            # Get Candidate Diplomas Set
            cand_dips = set()
            try:
                cand_dips.update(json.loads(cand.get('normalized_diplomas', '[]')))
            except: pass
            
            # Fallback
            single = str(cand.get('normalized_diploma', 'UNKNOWN'))
            if single != 'UNKNOWN': cand_dips.add(single)
            
            # Check Match
            if required_dips:
                reqs_set = set(required_dips)
                if not reqs_set.isdisjoint(cand_dips):
                    p_score = 1
            else:
                pass
            
            matches.append({
                'candidate_id': cand['id'], # For selection
                'Candidate Name': f"{cand['first_name']} {cand['last_name']}",
                'Candidate Phone': cand['phone'],
                'Candidate Email': cand['email'],
                'Job Title': job['title'],
                'Nursery': job['nursery_name'],
                'Urgency': job.get(col_name, ''),
                'Distance': dist,
                'Prerequisite Met': "Yes" if p_score else "No",
                'AI Score': (cand['closeness_score'] / 10.0) if pd.notna(cand['closeness_score']) else 0.0,
                '_u_score': u_score,
                '_p_score': p_score
            })

# Convert to DF
if matches:
    df_m = pd.DataFrame(matches)
    df_m = df_m.sort_values(by=['_u_score', '_p_score', 'AI Score', 'Distance'], ascending=[False, False, False, True])
    
    display_cols = ['Urgency', 'Prerequisite Met', 'AI Score', 'Candidate Name', 'Candidate Phone', 'Job Title', 'Nursery', 'Distance']
    
    st.info("Select a row to view full Candidate Profile details below.")
    
    selection = st.dataframe(
        df_m[display_cols + ['candidate_id']], # Including ID for logic, but hiding it
        column_config={
            "Urgency": st.column_config.Column("Urgency", width="small"),
            "AI Score": st.column_config.NumberColumn("Match /10", format="%.2f"),
            "Distance": st.column_config.NumberColumn("Dist (km)", format="%.1f"),
            "candidate_id": None # Hide ID
        },
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # --- Detail View Logic ---
    if selection.selection and selection.selection.rows:
        idx = selection.selection.rows[0]
        # Get ID from the sorted dataframe
        # Note: df_m is Sorted. selection.rows[0] is the index in the SORTED (displayed) view.
        selected_cand_id = df_m.iloc[idx]['candidate_id']
        
        # Get Full Candidate Row
        selected_row = candidates_df.loc[candidates_df['id'] == selected_cand_id].iloc[0]
        
        st.divider()
        st.markdown(f"## 👤 {selected_row['first_name']} {selected_row['last_name']}")
        
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.markdown(f"**📍 Location:** {selected_row['city']} ({selected_row['zip_code']})")
            st.markdown(f"**📧 Email:** {selected_row['email']}")
            st.markdown(f"**📱 Phone:** {selected_row['phone']}")
            
            exp_ai = selected_row.get('experience_ai', 'Unknown')
            st.info(f"**Experience:** {exp_ai}")

        with c2:
            st.markdown("### 🎓 Qualifications")
            
            dips = get_diploma_list(selected_row)
            if dips:
                html = "".join([f"<span class='dip-tag'>{d}</span>" for d in dips])
                st.markdown(f"<div>{html}</div>", unsafe_allow_html=True)
            else:
                st.write("No standardized diplomas.")
                
            st.markdown("### 🤖 Qualitiative Analysis")
            st.write(selected_row.get('qualitative_analysis', 'No analysis available.'))
            
            with st.expander("📄 View Raw CV Text"):
                st.text(selected_row.get('cv_text', ''))

else:
    st.info("No matches found within criteria.")
