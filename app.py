import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Metier, Nursery, Job, Candidate, Application
import json
from math import radians, cos, sin, asin, sqrt

# --- Configuration & Setup ---
st.set_page_config(page_title="Grandir Central Command", layout="wide", page_icon="📍")

# Connect to DB
engine = create_engine('sqlite:///grandir.db')
Session = sessionmaker(bind=engine)
session = Session()

# --- Helper Functions ---

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance in kilometers between two points 
    on the earth (specified in decimal degrees)
    """
    if pd.isna(lon1) or pd.isna(lat1) or pd.isna(lon2) or pd.isna(lat2):
        return None

    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r

@st.cache_data(ttl=600)
def load_nurseries():
    # Load all nurseries into a DataFrame for easy mapping
    query = session.query(Nursery).statement
    df = pd.read_sql(query, session.bind)
    return df

def get_jobs_for_nursery(nursery_name):
    # Return list of jobs for this nursery
    return session.query(Job).join(Metier).filter(Job.nursery_name == nursery_name).all()

def load_candidates_for_job(job, max_distance=50):
    # 1. Determine Prerequisites
    req_col = None
    if job.metier.prerequisites:
        try:
            req_data = json.loads(job.metier.prerequisites)
            req_col = req_data.get('required_diploma_column')
        except:
            pass
            
    # 2. Query Candidates (In a real scalable app, we'd do geospatial query in SQL. 
    # For SQLite/Prototype, loading candidates then filtering is okay if < 50k simple rows)
    # We fetch relevant columns + the dynamic requirement column
    
    # Selecting ALL candidates is heavy. 
    # Optimization: Filter by a broad bounding box if possible, or just load all for now (36k rows is manageable in memory)
    query = session.query(Candidate).statement
    df_cand = pd.read_sql(query, session.bind)
    
    # 3. Filter by Diploma
    if req_col and req_col in df_cand.columns:
        # User wants people WHO HAVE the diploma.
        # So exclude Nulls and exclude explicit 'Non'
        # Also exclude empty strings
        df_cand = df_cand[df_cand[req_col].notna()]
        df_cand = df_cand[df_cand[req_col] != 'Non']
        df_cand = df_cand[df_cand[req_col] != '']
    elif req_col:
        # Column exists in DB logic but maybe not in this DF if we didn't select it?
        # In current schema, Candidate object attributes match columns. 
        # But 'current_diploma' is the generic one.
        # Wait, the CSV columns became attributes on the Candidate? 
        # Checking init_db.py... Candidate class only has specific fixed columns.
        # AH! I made a mistake in init_db.py. I didn't add all the dynamic columns to the Candidate model.
        # The data migration script probably failed to save them or saved them to valid cols.
        # Let's check init_db.py content... 
        # It has: city, zip_code, latitude, longitude, current_diploma, experience_years.
        # It DOES NOT have specific columns like 'Titulaire du diplôme Infirmier'.
        
        # FIX: We need to access the ORIGINAL data or generic 'current_diploma' column.
        # However, the user explicitly asked to filter using "the diplomas that were colons in the original csv".
        # Since I dropped them in the SQL model, I cannot query them directly via ORM unless I stored them.
        
        # Workaround: Re-load from CSV for the candidate attributes since the DB model is slim?
        # Or did I migrate them? In migrate_to_sql.py, I instantiated Candidate with fixed fields. I did NOT store the extra columns.
        
        # CRITICAL STOP: The SQL DB does not have the detailed diploma columns.
        # Ideally I should update `init_db.py` to include a JSON column `attributes` or similar.
        # For now, to unblock the user quickly, I will hybridize: 
        # Load Candidates from CSV (which is cleaned) to get the detailed columns, 
        # but use DB for Nurseries/Jobs structure.
        # OR: Just rely on CSV for candidates entirely for this part.
        pass

    return df_cand, req_col

# Temporary Fix: Load candidates from CSV to get all columns
@st.cache_data
def load_candidates_csv():
    return pd.read_csv('candidates.csv', low_memory=False)

# --- Main App ---

st.title("🗺️ Grandir Nursery Map")

# 1. Sidebar Controls
with st.sidebar:
    st.header("Settings")
    max_dist = st.slider("Max Distance (km)", 0, 50, 20)
    urgency_filter = st.multiselect("Nursery Urgency", ["Rouge", "Orange", "Verte"], default=["Rouge", "Orange"])

# 2. Map
df_nurseries = load_nurseries()

# Filter Nurseries
if urgency_filter:
    # simple substring match
    pattern = '|'.join([u.lower() for u in urgency_filter])
    df_nurseries = df_nurseries[df_nurseries['urgency_color'].str.lower().str.contains(pattern, na=False)]

st.subheader(f"Active Nurseries ({len(df_nurseries)})")

m = folium.Map(location=[46.603354, 1.888334], zoom_start=6)

# Create a map data dict for fast interaction
nursery_map_data = {}

for _, row in df_nurseries.iterrows():
    if pd.isna(row['latitude']) or pd.isna(row['longitude']): continue
    
    color = 'green'
    if 'rouge' in str(row['urgency_color']).lower(): color = 'red'
    elif 'orange' in str(row['urgency_color']).lower(): color = 'orange'
    
    folium.Marker(
        [row['latitude'], row['longitude']],
        popup=row['name'],
        tooltip=row['name'],
        icon=folium.Icon(color=color, icon='home')
    ).add_to(m)

output = st_folium(m, width=1200, height=600)

# 3. Drill Down
if output['last_object_clicked_popup']:
    selected_nursery_name = output['last_object_clicked_popup']
    st.markdown(f"### 📍 {selected_nursery_name}")
    
    # Get details from DB
    nursery = session.query(Nursery).get(selected_nursery_name)
    if nursery and nursery.urgency_color:
        st.caption(f"Urgency: {nursery.urgency_color}")

    # Show Jobs
    jobs = get_jobs_for_nursery(selected_nursery_name)
    
    if not jobs:
        st.warning("No active jobs found for this nursery.")
    else:
        # Job Selector
        job_options = {f"{j.title} ({j.reference})": j for j in jobs}
        selected_job_label = st.selectbox("Select Position to Staff:", list(job_options.keys()))
        selected_job = job_options[selected_job_label]
        
        # prerequisites
        st.info(f"**Metier**: {selected_job.metier.title} | **Contract**: {selected_job.contract_type}")
        
        # Load Candidates (from CSV for now to get full columns)
        df_c = load_candidates_csv()
        
        # Filter Logic
        req_col = None
        if selected_job.metier.prerequisites:
            try:
                data = json.loads(selected_job.metier.prerequisites)
                req_col = data.get('required_diploma_column')
            except:
                pass
        
        # Display filtering info
        if req_col:
            st.markdown(f"**Required Diploma**: `{req_col}`")
            # Filter
            if req_col in df_c.columns:
                initial_count = len(df_c)
                df_c = df_c[df_c[req_col].notna() & (df_c[req_col] != 'Non') & (df_c[req_col] != '')]
                st.write(f"Filtered {initial_count} -> {len(df_c)} eligible candidates.")
            else:
                st.error(f"Column '{req_col}' not found in candidate data.")
        else:
            st.write("No specific diploma requirement defined for this metier.")
            
        # Distance Calc
        # We need nursery coords
        n_lat, n_lon = nursery.latitude, nursery.longitude
        
        if n_lat is not None:
            # Vectorized Haversine would be faster but apply is fine for subset
            # Actually we are calculating for ALL 36k candidates? That might be slow every click.
            # Optimization: Pre-filter by roughly lat/lon box?
            # Or just do it, Python is fast enough for 30k simple math ops.
            
            # Ensure coords
            # df_c should have 'Cand_Lat', 'Cand_Lon' or similar?
            # In clean_data/migrate we used 'Code postal du candidat'.
            # app.py's load_data (old) visualized this. 
            # The CSV DOES NOT have Lat/Lon columns unless we saved them.
            # 'clean_data.py' dropped cols but didn't Add lat/lon. 
            # `matching_engine.py` added them. 
            # `migrate_to_sql.py` added them to DB but we are loading CSV.
            
            # -> We need to merge DB lat/lon back to CSV or use DB candidates and JOIN with CSV for columns.
            # Strategy: Load DB Candidates (has ID, Lat, Lon). Merge with CSV (assume index matches or 'Matricule'?). 
            # Actually `migrate_to_sql` iterated row by row.
            # Best bet: Use the `candidates.csv` BUT we need to geocode it on the fly or load the geocoded version?
            # Wait, `matching_engine` SAVED nothing. 
            # `migrate_to_sql` SAVED to DB.
            
            # Solution: Load DB Candidates (ID, Lat, Lon, Zip).
            # Load CSV (Full Data). 
            # Assume 1:1 mapping if row order preserved? 
            # Safety: Join on 'Code postal du candidat' is ambiguous (many candidates same zip).
            # 
            # Let's check `candidates.csv` columns again. 
            # It has 'Code postal du candidat'.
            # We can re-geocode fast using cached pgeocode or just generic pgeocode.
            
            import pgeocode
            nomi = pgeocode.Nominatim('fr')
            
            # Quick Zip Lookup Map
            @st.cache_resource
            def get_zip_map(unique_zips):
                res = nomi.query_postal_code(list(unique_zips))
                return {row['postal_code']: (row['latitude'], row['longitude']) for _, row in res.iterrows()}

            # Extract zips
            df_c['clean_zip'] = df_c['Code postal du candidat'].astype(str).str.extract(r'(\d{5})')
            unique_zips = df_c['clean_zip'].dropna().unique()
            zip_map = get_zip_map(unique_zips)
            
            def get_coords(z):
                return zip_map.get(z, (None, None))
                
            coords = df_c['clean_zip'].map(get_coords)
            df_c['lat'] = coords.apply(lambda x: x[0])
            df_c['lon'] = coords.apply(lambda x: x[1])
            
            # Distance
            df_c['distance_km'] = df_c.apply(
                lambda row: haversine(row['lon'], row['lat'], n_lon, n_lat), axis=1
            )
            
            # Filter Actions
            df_c = df_c[df_c['distance_km'] <= max_dist]
            df_c = df_c.sort_values('distance_km')
            
            # Display
            st.dataframe(
                df_c[['Statut', 'distance_km', 'Ville du candidat', 'Diplôme', req_col] if req_col else ['Statut', 'distance_km', 'Ville du candidat', 'Diplôme']],
                use_container_width=True
            )
        else:
            st.error("Nursery coordinates missing.")

else:
    st.info("Click on a nursery pin to see details.")
