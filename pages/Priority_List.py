
import streamlit as st
import json
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Base, Nursery, Job, Candidate, Metier, Application

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

jobs_df, candidates_df = load_data()

# Filters
with st.sidebar:
    st.header("Search Filters")
    # Job Filter (Fixing user issue)
    # We want to filter generally? Or is this a global list?
    # "Priority Call List" usually implies finding candidates for *specific* jobs.
    # Let's add a Global Job Filter if easy, or just fix the matching logic first.
    # The user said "when I change job opening positions". This implies they are on the Main Page or drilling down.
    # BUT this file is `Priority_List.py`. It lists ALL priority matches.
    # Maybe the user was referring to `app.py`? "notice how when I change job opening positions the candidate list doesnt change".
    # THAT IS IN `app.py`.
    # `Priority_List.py` generates a big table.
    
    # I should fix `app.py` for the "Job Filter" issue.
    # I should fix `Priority_List.py` for the "Prerequisite Met" column logic.
    pass

max_dist = st.sidebar.slider("Max Distance (km)", 5, 50, 20)

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
            cand_norm = str(cand.get('normalized_diploma', 'UNKNOWN'))
            
            if cand_norm != "UNKNOWN" and cand_norm in required_dips:
                p_score = 1
            elif not required_dips: 
                # If no strict reqs, maybe it's open? Or strict No?
                # Let's be lenient if job has no reqs defined?
                pass
            
            matches.append({
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
    
    st.dataframe(
        df_m[display_cols],
        column_config={
            "Urgency": st.column_config.Column("Urgency", width="small"),
            "AI Score": st.column_config.NumberColumn("Match /10", format="%.2f"),
            "Distance": st.column_config.NumberColumn("Dist (km)", format="%.1f")
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No matches found within criteria.")
