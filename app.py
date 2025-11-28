import streamlit as st
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
import pgeocode
import re
from math import radians, cos, sin, asin, sqrt
import folium
from streamlit_folium import st_folium

# --- Configuration & Setup ---
st.set_page_config(page_title="Grandir Central Command", layout="wide", page_icon="👶")

KML_FILE = 'creche.kml'
CANDIDATES_FILE = 'liste-des-candidatures_anonymized.xls'
JOBS_FILE = 'liste-des-postes_anonymized.xls'

# --- Helper Functions (Cached) ---

@st.cache_data
def load_data():
    try:
        df_c = pd.read_excel(CANDIDATES_FILE)
        df_j = pd.read_excel(JOBS_FILE)
    except FileNotFoundError:
        df_c = pd.read_csv('Liste des candidatures.csv')
        df_j = pd.read_csv('Liste des annonces.csv')
    return df_c, df_j

@st.cache_data
def parse_kml_and_geocode(kml_path):
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    nursery_zips = {} 
    nursery_locations = {}

    try:
        tree = ET.parse(kml_path)
        root = tree.getroot()
        placemarks = root.findall('.//kml:Placemark', ns)
        
        for p in placemarks:
            name = p.find('kml:name', ns).text
            if not name: continue
            
            zip_code = None
            for data in p.findall('.//kml:Data', ns):
                if data.get('name') == 'CODE POSTAL':
                    zip_code = data.find('kml:value', ns).text
                    break
            if zip_code:
                nursery_zips[name] = str(zip_code).strip()
                
    except Exception as e:
        st.error(f"Failed to parse KML: {e}")
        return {}, {}

    # Geocode Zips
    nomi = pgeocode.Nominatim('fr')
    unique_zips = list(set(nursery_zips.values()))
    if unique_zips:
        geo_results = nomi.query_postal_code(unique_zips)
        zip_to_coords = {}
        for _, row in geo_results.iterrows():
            if not pd.isna(row['latitude']) and not pd.isna(row['longitude']):
                zip_to_coords[row['postal_code']] = (row['latitude'], row['longitude'])

        for name, zip_code in nursery_zips.items():
            if zip_code in zip_to_coords:
                nursery_locations[name] = zip_to_coords[zip_code]
                
    return nursery_locations, zip_to_coords

def extract_zip(val):
    if pd.isna(val): return None
    match = re.search(r'\b\d{5}\b', str(val))
    return match.group(0) if match else None

def haversine(lon1, lat1, lon2, lat2):
    if pd.isna(lon1) or pd.isna(lat1) or pd.isna(lon2) or pd.isna(lat2): return None
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 
    return c * r

# --- Scoring Logic ---

def get_candidate_cat(row):
    diplomas = [
        str(row.get('Diplôme', '')),
        str(row.get('Diplôme pour Auxiliaire Petite Enfance', '')),
        str(row.get('Titulaire du diplôme Auxiliaire Puériculture', '')),
        str(row.get('Titulaire du diplôme Educateur Jeune Enfant', ''))
    ]
    combined = " ".join(diplomas).lower()
    if "auxiliaire de puériculture" in combined or "eje" in combined or "educateur jeune enfant" in combined or "infirmier" in combined:
        return "CAT 1"
    elif "cap petite enfance" in combined or "cap aepe" in combined:
        return "CAT 2"
    return "Unqualified"

def calculate_ai_quality(row):
    score = 0
    
    # 1. Source Intelligence
    source = str(row.get('Provenance', '')).lower()
    if any(x in source for x in ['cooptation', 'chasse', 'interne']):
        score += 15
    elif any(x in source for x in ['indeed', 'hellowork']):
        score += 0 # Neutral
        
    # 2. Stability Signals (Tags & Diplôme)
    text_blob = (str(row.get('Tags', '')) + " " + str(row.get('Diplôme', ''))).lower()
    if any(x in text_blob for x in ['confirmé', 'expérimenté', 'diplômé']):
        score += 10
        
    # 3. Process Velocity
    status = str(row.get('Statut', '')).lower()
    etape = str(row.get('Etape', '')).lower()
    if 'entretien' in status or 'entretien' in etape:
        score += 20
        
    return min(score, 100) # Cap at some reasonable max if needed, though formula handles it

def get_compliance_score(cand_cat, job_cat):
    if pd.isna(job_cat): return 0
    job_cat_str = str(job_cat).upper()
    if cand_cat == "Unqualified": return 0
    if "CAT 1" in job_cat_str: return 100 if cand_cat == "CAT 1" else 0
    elif "CAT 2" in job_cat_str: return 100 if cand_cat in ["CAT 1", "CAT 2"] else 0
    elif "CAT 3" in job_cat_str: return 100
    return 0

def get_urgency_score(color):
    if pd.isna(color): return 30
    if "rouge" in str(color).lower(): return 100
    elif "orange" in str(color).lower(): return 70
    else: return 30

def get_distance_score(km):
    if pd.isna(km): return 0
    if km < 3: return 100
    elif km < 10: return 80
    elif km < 20: return 50
    else: return 0

def process_data(df_c, df_j, nursery_locations, zip_to_coords):
    # 1. Geocode Candidates
    nomi = pgeocode.Nominatim('fr')
    df_c['Candidate_Zip'] = df_c['Code postal du candidat'].apply(extract_zip)
    cand_zips = [z for z in df_c['Candidate_Zip'].unique() if z]
    
    cand_zip_map = {}
    if cand_zips:
        res = nomi.query_postal_code(cand_zips)
        for _, row in res.iterrows():
            if not pd.isna(row['latitude']):
                cand_zip_map[row['postal_code']] = (row['latitude'], row['longitude'])
    
    df_c['Cand_Lat'] = df_c['Candidate_Zip'].map(lambda z: cand_zip_map.get(z, (None, None))[0])
    df_c['Cand_Lon'] = df_c['Candidate_Zip'].map(lambda z: cand_zip_map.get(z, (None, None))[1])
    
    # 2. Prepare Jobs
    df_j['Job_Zip'] = df_j['Localisation'].apply(extract_zip)
    
    def get_job_coords(row):
        name = str(row.get('CRECHES', ''))
        if name in nursery_locations: return nursery_locations[name]
        zip_code = row.get('Job_Zip')
        if zip_code in zip_to_coords: return zip_to_coords[zip_code]
        return (None, None)

    coords = df_j.apply(get_job_coords, axis=1)
    df_j['Job_Lat'] = coords.apply(lambda x: x[0])
    df_j['Job_Lon'] = coords.apply(lambda x: x[1])
    
    # 3. Merge
    # Filter Pool
    target_statuses = ["Présélection", "A contacter", "Entretien", "Qualification"]
    status_pattern = "|".join(target_statuses)
    df_pool = df_c[
        df_c['Statut'].str.contains(status_pattern, case=False, na=False) | 
        df_c['Etape'].str.contains(status_pattern, case=False, na=False)
    ].copy()
    
    df_merged = pd.merge(
        df_pool,
        df_j[['Référence', 'CAT', 'Quelle est la couleur de la crèche ?', 'Job_Lat', 'Job_Lon', "Titre de l'annonce", 'CRECHES']],
        left_on='Référence de l’annonce',
        right_on='Référence',
        how='left'
    )
    
    # 4. Scores
    df_merged['Distance_KM'] = df_merged.apply(
        lambda row: haversine(row['Cand_Lon'], row['Cand_Lat'], row['Job_Lon'], row['Job_Lat']), axis=1
    )
    
    df_merged['Distance_Score'] = df_merged['Distance_KM'].apply(get_distance_score)
    
    df_merged['Candidate_CAT'] = df_merged.apply(get_candidate_cat, axis=1)
    
    df_merged['Compliance_Score'] = df_merged.apply(lambda row: get_compliance_score(row['Candidate_CAT'], row['CAT']), axis=1)
    
    df_merged['Urgency_Score'] = df_merged['Quelle est la couleur de la crèche ?'].apply(get_urgency_score)
    
    df_merged['AI_Quality_Score'] = df_merged.apply(calculate_ai_quality, axis=1)
    
    # GrandirScore=(Distance×0.3)+(Urgency×0.3)+(Compliance×0.2)+(AI_Quality×0.2)
    df_merged['Grandir_Score'] = (
        df_merged['Distance_Score'] * 0.3 +
        df_merged['Urgency_Score'] * 0.3 +
        df_merged['Compliance_Score'] * 0.2 +
        df_merged['AI_Quality_Score'] * 0.2
    )
    
    # Recommended Action
    def get_action(score):
        if score >= 90: return "Call Immediately"
        elif score >= 70: return "Review"
        else: return "Hold"
    df_merged['Recommended_Action'] = df_merged['Grandir_Score'].apply(get_action)
    
    # Candidate ID (Index)
    df_merged['Candidate_ID'] = df_merged.index
    
    return df_merged, df_j

# --- Main App ---

st.title("🚀 Grandir Central Command")
st.markdown("**Recruitment Optimization Platform** | *Precision Geolocation & AI Scoring*")

# Load Data
with st.spinner("Loading Data & Geocoding..."):
    df_candidates, df_jobs = load_data()
    nursery_locations, zip_to_coords = parse_kml_and_geocode(KML_FILE)
    df_main, df_jobs_processed = process_data(df_candidates, df_jobs, nursery_locations, zip_to_coords)

# --- Sidebar Filters ---
st.sidebar.header("Filters")

urgency_options = ["Rouge", "Orange", "Verte"]
selected_urgency = st.sidebar.multiselect("Urgency Level", urgency_options, default=["Rouge", "Orange"])

max_distance = st.sidebar.slider("Max Distance (km)", 0, 50, 20)

status_options = df_main['Statut'].unique().tolist()
selected_status = st.sidebar.multiselect("Candidate Status", status_options, default=status_options)

# Apply Filters
filtered_df = df_main.copy()

# Urgency Filter
if selected_urgency:
    # Map selection to color strings in data
    urgency_map = [u.lower() for u in selected_urgency]
    filtered_df = filtered_df[filtered_df['Quelle est la couleur de la crèche ?'].str.lower().apply(lambda x: any(u in str(x) for u in urgency_map))]

# Distance Filter
filtered_df = filtered_df[filtered_df['Distance_KM'] <= max_distance]

# Status Filter
if selected_status:
    filtered_df = filtered_df[filtered_df['Statut'].isin(selected_status)]

st.sidebar.markdown("---")
st.sidebar.metric("Candidates Matched", len(filtered_df))

# --- Tabs ---
tab1, tab2, tab3 = st.tabs(["🗺️ The War Room", "🔥 The Hot List", "📡 Opportunity Radar"])

with tab1:
    st.header("Nursery Network & Candidates")
    
    # Map
    m = folium.Map(location=[48.8566, 2.3522], zoom_start=11)
    
    # Add Nursery Pins
    # Filter jobs based on urgency selection too, to show relevant nurseries
    jobs_to_plot = df_jobs_processed.dropna(subset=['Job_Lat', 'Job_Lon'])
    if selected_urgency:
        urgency_map = [u.lower() for u in selected_urgency]
        jobs_to_plot = jobs_to_plot[jobs_to_plot['Quelle est la couleur de la crèche ?'].str.lower().apply(lambda x: any(u in str(x) for u in urgency_map))]
    
    # Group by Nursery to avoid duplicate pins
    nurseries = jobs_to_plot.groupby(['CRECHES', 'Job_Lat', 'Job_Lon', 'Quelle est la couleur de la crèche ?']).size().reset_index()
    
    for _, row in nurseries.iterrows():
        color = 'green'
        if 'rouge' in str(row['Quelle est la couleur de la crèche ?']).lower(): color = 'red'
        elif 'orange' in str(row['Quelle est la couleur de la crèche ?']).lower(): color = 'orange'
        
        folium.Marker(
            [row['Job_Lat'], row['Job_Lon']],
            popup=row['CRECHES'],
            tooltip=row['CRECHES'],
            icon=folium.Icon(color=color, icon='home')
        ).add_to(m)
        
    output = st_folium(m, width=1000, height=500)
    
    # Interaction
    if output['last_object_clicked_popup']:
        selected_nursery = output['last_object_clicked_popup']
        st.subheader(f"Top Matches for: {selected_nursery}")
        
        # Filter main df for this nursery
        nursery_matches = df_main[df_main['CRECHES'] == selected_nursery].sort_values(by='Grandir_Score', ascending=False).head(5)
        
        if not nursery_matches.empty:
            st.dataframe(nursery_matches[['Candidate_ID', 'Statut', 'Grandir_Score', 'Distance_KM', 'Recommended_Action']])
        else:
            st.info("No active candidates found for this nursery.")

with tab2:
    st.header("Actionable Candidate List")
    
    display_cols = ['Candidate_ID', 'Statut', 'Grandir_Score', 'Distance_KM', 'Recommended_Action', 'CRECHES', 'Urgency_Score', 'AI_Quality_Score']
    
    # Highlight logic
    def highlight_high_score(s):
        return ['background-color: #d4edda' if v >= 90 else '' for v in s]

    st.dataframe(
        filtered_df[display_cols].sort_values(by='Grandir_Score', ascending=False).style.apply(highlight_high_score, subset=['Grandir_Score']),
        use_container_width=True
    )

with tab3:
    st.header("Smart Redirections")
    
    # Logic: Green Job (>10km) -> Red Job (<5km)
    # Use full dataset for this, not filtered
    candidates_to_check = df_main[
        (df_main['Urgency_Score'] <= 30) & 
        (df_main['Distance_KM'] > 10) &
        (df_main['Candidate_CAT'] != "Unqualified")
    ].copy()
    
    red_jobs = df_jobs_processed[
        df_jobs_processed['Quelle est la couleur de la crèche ?'].str.contains("Rouge", case=False, na=False)
    ].dropna(subset=['Job_Lat', 'Job_Lon'])
    
    redirects = []
    total_saved_km = 0
    
    # Optimize: Pre-filter candidates with coords
    candidates_to_check = candidates_to_check.dropna(subset=['Cand_Lat', 'Cand_Lon'])
    
    for _, cand in candidates_to_check.iterrows():
        c_lat, c_lon = cand['Cand_Lat'], cand['Cand_Lon']
        
        # Simple box filter
        nearby_jobs = red_jobs[
            (red_jobs['Job_Lat'].between(c_lat - 0.05, c_lat + 0.05)) &
            (red_jobs['Job_Lon'].between(c_lon - 0.05, c_lon + 0.05))
        ]
        
        for _, job in nearby_jobs.iterrows():
            dist = haversine(c_lon, c_lat, job['Job_Lon'], job['Job_Lat'])
            if dist < 5:
                 # Check Compliance
                if get_compliance_score(cand['Candidate_CAT'], job['CAT']) == 100:
                    saved = cand['Distance_KM'] - dist
                    redirects.append({
                        "Candidate_ID": cand['Candidate_ID'],
                        "Current_Nursery": cand['CRECHES'],
                        "Current_Dist": round(cand['Distance_KM'], 1),
                        "Redirect_Nursery": job['CRECHES'],
                        "Redirect_Dist": round(dist, 1),
                        "Distance_Saved": round(saved, 1)
                    })
                    total_saved_km += saved
                    break 

    st.metric("Potential Commute Km Saved", f"{int(total_saved_km)} km")
    
    if redirects:
        df_redirects = pd.DataFrame(redirects)
        st.dataframe(df_redirects, use_container_width=True)
    else:
        st.info("No redirection opportunities found.")
