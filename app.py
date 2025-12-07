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
    if pd.isna(lon1) or pd.isna(lat1) or pd.isna(lon2) or pd.isna(lat2):
        return None
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 
    return c * r

@st.cache_data(ttl=600)
def load_nurseries():
    query = session.query(Nursery).statement
    df = pd.read_sql(query, session.bind)
    return df

def get_jobs_for_nursery(nursery_name):
    return session.query(Job).join(Metier).filter(Job.nursery_name == nursery_name).all()

# --- Main App ---

# --- Custom CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    
    html, body, [class*="css"]  {
        font-family: 'Inter', sans-serif;
        color: #2C3E50;
    }
    
    h1, h2, h3 {
        color: #002B5B;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    
    .stDataFrame {
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border: 1px solid #E5E7EB;
        border-radius: 6px;
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #F8F9FA;
        border-right: 1px solid #E5E7EB;
    }
    
    /* Metrics/Cards (if any) */
    div[data-testid="metric-container"] {
        background-color: white;
        border: 1px solid #E5E7EB;
        padding: 15px;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

st.title("Grandir Central Command")

# 1. Sidebar Controls
with st.sidebar:
    st.header("Search Filters")
    urgency_filter = st.multiselect(
        "Urgency Level",
        options=['Rouge', 'Orange', 'Vert', 'Jaune', 'Bleu'],
        default=['Rouge', 'Orange']
    )
    
    max_dist = st.slider("Max Distance (km)", 5, 50, 20)
    
    # Filter Nurseries
    # (Existing Logic)

# 2. Map
df_nurseries = load_nurseries()

# Filter Nurseries
if urgency_filter:
    pattern = '|'.join([u.lower() for u in urgency_filter])
    df_nurseries = df_nurseries[df_nurseries['urgency_color'].str.lower().str.contains(pattern, na=False)]

# Defaults
if 'selected_nursery_name' not in st.session_state:
    st.session_state['selected_nursery_name'] = None
if 'selected_candidate_id' not in st.session_state:
    st.session_state['selected_candidate_id'] = None

# --- Data Loading & State Management ---
# We need to load data *before* the map to determine what to show
# But map clicks update the nursery.
# Candidate selection usually happens *after* nursery selection.

# 1. Load Nurseries
df_nurseries = load_nurseries()
if urgency_filter:
    pattern = '|'.join([u.lower() for u in urgency_filter])
    df_nurseries = df_nurseries[df_nurseries['urgency_color'].str.lower().str.contains(pattern, na=False)]

# 2. Logic to determine Candidate Selection
# We need to know if a candidate is selected. The selectbox is usually UI driven.
# We will check st.session_state['selected_candidate_id']

# Helper to clear candidate if nursery changes
if 'last_nursery' not in st.session_state: st.session_state['last_nursery'] = None
if st.session_state['selected_nursery_name'] != st.session_state['last_nursery']:
    st.session_state['selected_candidate_id'] = None
    st.session_state['last_nursery'] = st.session_state['selected_nursery_name']

# 3. Prepare Map Data
map_markers = []
map_lines = []
map_center = [48.8566, 2.3522]
map_zoom = 10

# If a Nursery is selected, we need its data
selected_nursery = None
candidates_for_nursery = None
if st.session_state['selected_nursery_name']:
    selected_nursery = session.query(Nursery).get(st.session_state['selected_nursery_name'])
    
    # Load Candidates for this nursery (needed for both map and table)
    if selected_nursery:
        q = session.query(Candidate).statement
        df_c = pd.read_sql(q, session.bind)
        df_c['distance_km'] = df_c.apply(lambda r: haversine(r['longitude'], r['latitude'], selected_nursery.longitude, selected_nursery.latitude), axis=1)
        df_c = df_c[df_c['distance_km'] <= max_dist].sort_values('distance_km')
        candidates_for_nursery = df_c

# CHECK: Is a candidate selected?
# We use a selectbox further down, but we need the value NOW for the map.
# We can use a callback or just read the widget key if it exists?
# Better: We put the candidate selector in the Sidebar or Top if we want Map to update instantly?
# OR we render the map using Session State, and the Selectbox updates Session State.

# Let's put the Candidate Selector Logic here (Pre-Calculation)
target_candidate = None
if candidates_for_nursery is not None and not candidates_for_nursery.empty:
    # We need to allow user to select.
    # To affect the map ABOVE, we need the UI element here OR rely on previous run state.
    # Let's use the layout: Map -> Table -> Selector.
    # If user selects in Selector, script reruns, and we hit this line with updated state.
    if st.session_state['selected_candidate_id']:
        target_candidate = df_c[df_c['id'] == st.session_state['selected_candidate_id']]
        if not target_candidate.empty:
            target_candidate = target_candidate.iloc[0]

# --- Build Map Objects ---

if target_candidate is not None and selected_nursery:
    # ISOLATED VIEW: Nursery + Candidate + Line
    map_markers.append({
        'lat': selected_nursery.latitude, 'lon': selected_nursery.longitude,
        'popup': selected_nursery.name, 'color': 'red', 'icon': 'building'
    })
    map_markers.append({
        'lat': target_candidate['latitude'], 'lon': target_candidate['longitude'],
        'popup': f"{target_candidate['first_name']} {target_candidate['last_name']}",
        'color': 'blue', 'icon': 'person'
    })
    map_lines.append([
        (selected_nursery.latitude, selected_nursery.longitude),
        (target_candidate['latitude'], target_candidate['longitude']),
        f"{target_candidate['distance_km']:.1f} km"
    ])
    # Center between them
    map_center = [(selected_nursery.latitude + target_candidate['latitude'])/2, (selected_nursery.longitude + target_candidate['longitude'])/2]
    map_zoom = 12

else:
    # GLOBAL VIEW
    # Add Nurseries
    for _, row in df_nurseries.iterrows():
        if pd.isna(row['latitude']) or pd.isna(row['longitude']): continue
        color = 'green'
        if 'rouge' in str(row['urgency_color']).lower(): color = 'red'
        elif 'orange' in str(row['urgency_color']).lower(): color = 'orange'
        
        icon = 'building'
        if st.session_state['selected_nursery_name'] == row['name']:
            color = 'blue'; icon = 'map-pin'
            
        map_markers.append({
            'lat': row['latitude'], 'lon': row['longitude'],
            'popup': row['name'], 'color': color, 'icon': icon
        })

# --- Render Map ---
st.subheader(f"Active Nurseries ({len(df_nurseries)})")
m = folium.Map(location=map_center, zoom_start=map_zoom)

for mk in map_markers:
    folium.Marker([mk['lat'], mk['lon']], popup=mk['popup'], icon=folium.Icon(color=mk['color'], icon=mk['icon'])).add_to(m)

for ln in map_lines:
    folium.PolyLine(ln[:2], tooltip=ln[2], weight=2, color='blue').add_to(m)

output = st_folium(m, width=1200, height=600)

# Update Nursery Selection from Map Click (Only if in Global View effectively)
if output['last_object_clicked_popup'] and target_candidate is None:
     clicked_name = output['last_object_clicked_popup']
     if clicked_name in df_nurseries['name'].values:
         if st.session_state['selected_nursery_name'] != clicked_name:
             st.session_state['selected_nursery_name'] = clicked_name
             st.session_state['selected_candidate_id'] = None # Reset candidate
             st.rerun()

# --- Drill Down Section ---
if st.session_state['selected_nursery_name']:
    selected_nursery_name = st.session_state['selected_nursery_name']
    st.divider()
    st.markdown(f"### {selected_nursery_name}")
    
    # Jobs
    jobs = get_jobs_for_nursery(selected_nursery_name)
    
    selected_job_requirements = []
    
    if not jobs:
        st.warning("No active jobs.")
        job_options = {}
    else:
        # Create Options dict
        job_options = {f"{j.title} ({j.reference})": j for j in jobs}
        
        # Select Box
        # Key is crucial for state? No, standard is fine.
        s_job_key = st.selectbox("Position", list(job_options.keys()))
        s_job = job_options[s_job_key]
        
        # Get Requirements for filtering
        import json
        try:
             reqs = json.loads(s_job.metier.required_diplomas) if s_job.metier and s_job.metier.required_diplomas else []
             selected_job_requirements = reqs
        except:
             selected_job_requirements = []

    # Candidates Table
    if candidates_for_nursery is not None:
        st.markdown(f"### Candidates ({len(candidates_for_nursery)} nearby)")
        
        # --- FILTERING LOGIC ---
        df_view = candidates_for_nursery.copy()
        
        # Unified Diploma Display (Use Normalized or nice string)
        def get_display_diploma(row):
            norm = str(row.get('normalized_diploma', 'UNKNOWN'))
            if norm != "UNKNOWN": return norm
            # Fallback
            dip_ai = str(row.get('diploma_ai', '')).strip()
            if dip_ai and dip_ai.lower() != 'none': return dip_ai
            return str(row.get('current_diploma', ''))
            
        df_view['Display Diploma'] = df_view.apply(get_display_diploma, axis=1)
        
        # Apply Job Filter
        if selected_job_requirements:
            st.caption(f"Filtering for: {', '.join(selected_job_requirements)}")
            # Filter
            df_view = df_view[df_view['normalized_diploma'].isin(selected_job_requirements)]
            
            if df_view.empty:
                st.warning("No candidates found matching the specific diploma requirements for this job.")
        else:
            st.caption("No specific diploma requirements found for this job position.")
            
        df_view['Full Name'] = df_view['first_name'] + " " + df_view['last_name']
        df_view['Contact'] = df_view['email'] + " / " + df_view['phone']
        df_view['Dist'] = df_view['distance_km'].apply(lambda x: f"{x:.1f} km")
        df_view['Match Score'] = df_view['closeness_score'] / 10.0

        cols = ['Full Name', 'Contact', 'city', 'Dist', 'Display Diploma', 'Match Score', 'qualitative_analysis']
        
        st.dataframe(
            df_view[cols],
            column_config={
                "Match Score": st.column_config.NumberColumn("Match /10", format="%.2f"),
                "qualitative_analysis": "AI Analysis"
            },
            use_container_width=True
        )
        
        # Candidate Selector for Map Isolation
        st.write("---")
        st.markdown("#### Focus View")
        
        # We use a selectbox that updates session state
        # Add a "None" option to clear selection
        cand_options = [None] + list(candidates_for_nursery.index)
        
        def format_cand(i):
            if i is None: return "Show All (Global View)"
            r = candidates_for_nursery.loc[i]
            return f"{r['first_name']} {r['last_name']} ({r['distance_km']:.1f} km)"
            
        # Get current index for default
        current_idx = None
        if st.session_state['selected_candidate_id']:
             matches = candidates_for_nursery[candidates_for_nursery['id'] == st.session_state['selected_candidate_id']]
             if not matches.empty:
                 current_idx = matches.index[0]
        
        selected_idx_in_ui = st.selectbox(
            "Select a candidate to isolate on map", 
            cand_options, 
            format_func=format_cand,
            index=cand_options.index(current_idx) if current_idx in cand_options else 0,
            key="cand_selector"
        )
        
        # Update State
        new_id = None
        if selected_idx_in_ui is not None:
            new_id = candidates_for_nursery.loc[selected_idx_in_ui, 'id']
            
        if new_id != st.session_state['selected_candidate_id']:
            st.session_state['selected_candidate_id'] = new_id
            st.rerun()

