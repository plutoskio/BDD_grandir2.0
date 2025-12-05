
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Candidate, Job, Nursery, Metier
import math

st.set_page_config(layout="wide")
st.title("📞 Priority Call List")

# DB Setup
DB_URL = "sqlite:///grandir.db"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Helpers
def haversine(lon1, lat1, lon2, lat2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

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

# Logic
# We want to list Candidates matched to Urgent Jobs.
# This implies a Cross-Join or localized search. 
# Since we have ~1000 jobs and ~100 candidates (with CVs), we can do full cross check or optimized.

# Filters
max_dist = st.sidebar.slider("Max Distance (km)", 5, 50, 20)

matches = []

# Iterate over Jobs (filtering for Open status?)
open_jobs = jobs_df[jobs_df['status'] == 'Open']

with st.spinner("Calculating optimal matches..."):
    for _, job in open_jobs.iterrows():
        # Nursery Loc
        n_lat, n_lon = job['latitude'], job['longitude']
        if pd.isna(n_lat): continue
        
        # Urgency Score
        u_score = 1
        # Handle column name (suffixes only applied if collision)
        col_name = 'urgency_color_nurs' if 'urgency_color_nurs' in job else 'urgency_color'
        u_color = str(job.get(col_name, '')).lower()
        if 'rouge' in u_color: u_score = 3
        elif 'orange' in u_color: u_score = 2
        
        # Find Candidates in Range
        # Optimization: Pre-filter rough box? Skipping for small N.
        
        for _, cand in candidates_df.iterrows():
            if pd.isna(cand['latitude']): continue
            
            dist = haversine(cand['longitude'], cand['latitude'], n_lon, n_lat)
            if dist > max_dist: continue
            
            # Prereq Score & AI Score
            # Prereq: Does Candidate Diploma contain Job Metier keywords?
            # Simple heuristic
            p_score = 0
            job_title = str(job['title']).lower()
            cand_dip = str(cand['diploma_ai']).lower()
            
            # EJE
            if 'eje' in job_title or 'educateur' in job_title:
                if 'eje' in cand_dip or 'educateur' in cand_dip: p_score = 1
            # Auxiliaire
            elif 'auxiliaire' in job_title:
                if 'auxiliaire' in cand_dip or 'ap' in cand_dip or 'cap' in cand_dip: p_score = 1
            # Infirmier
            elif 'infirmier' in job_title or 'ide' in job_title:
                 if 'infirmier' in cand_dip or 'ide' in cand_dip: p_score = 1
            
            # Fallback: if AI score is high, assume Prereq met?
            # User wants separate sort: Urgency -> Prereq -> Qual Score.
            
            matches.append({
                'Candidate Name': f"{cand['first_name']} {cand['last_name']}",
                'Candidate Phone': cand['phone'],
                'Candidate Email': cand['email'],
                'Job Title': job['title'],
                'Nursery': job['nursery_name'],
                'Urgency': job.get(col_name, ''),
                'Distance': dist,
                'Prerequisite Met': "✅" if p_score else "❓",
                'AI Score': (cand['closeness_score'] / 10.0) if pd.notna(cand['closeness_score']) else 0.0,
                '_u_score': u_score,
                '_p_score': p_score
            })

# Convert to DF
if matches:
    df_m = pd.DataFrame(matches)
    
    # Sort
    # 1. Urgency (Desc)
    # 2. Prereq (Desc)
    # 3. AI Score (Desc)
    # 4. Distance (Asc)
    df_m = df_m.sort_values(by=['_u_score', '_p_score', 'AI Score', 'Distance'], ascending=[False, False, False, True])
    
    # Cleanup display
    display_cols = ['Urgency', 'Prerequisite Met', 'AI Score', 'Candidate Name', 'Candidate Phone', 'Job Title', 'Nursery', 'Distance']
    
    # Stylized
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
