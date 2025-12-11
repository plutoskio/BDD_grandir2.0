import streamlit as st
import pandas as pd
import sqlite3
import folium
from streamlit_folium import st_folium
import math
import base64
import os

# --- Configuration ---
DB_PATH = "grandir.db"
PARIS_COORDS = [48.8566, 2.3522]
DEFAULT_ZOOM = 12

# --- Helper Functions ---

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates Haversine distance in km."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    R = 6371  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def display_pdf(file_path):
    """Generates an iframe to display a PDF."""
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="1000" type="application/pdf"></iframe>'
    return pdf_display

@st.cache_data(ttl=600)
def load_nurseries_map_data(revision):
    """Loads nursery data for the main map."""
    conn = get_db_connection()
    query = """
    SELECT 
        n.nursery_id,
        n.nursery_name,
        n.latitude,
        n.longitude,
        MAX(
            CASE 
                WHEN p.status = 'Open' AND p.urgency_level IN ('Rouge', 'Red') THEN 3
                WHEN p.status = 'Open' AND p.urgency_level IN ('Orange') THEN 2
                WHEN p.status = 'Open' AND p.urgency_level IN ('Verte', 'Green') THEN 1
                ELSE 0
            END
        ) as max_urgency_score,
        COUNT(DISTINCT a.application_id) as application_count
    FROM dim_nurseries n
    LEFT JOIN fact_postings p ON n.nursery_id = p.nursery_id
    LEFT JOIN fact_applications a ON p.posting_id = a.posting_id
    WHERE n.latitude IS NOT NULL AND n.longitude IS NOT NULL
    GROUP BY n.nursery_id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # --- JITTER LOGIC ---
    # We apply a deterministic jitter based on nursery_id to separate overlapping markers.
    # 0.002 degrees is roughly 200 meters, ensuring clear separation.
    def apply_jitter(row):
        # Pseudo-random but deterministic shift based on ID
        import hashlib
        h = hashlib.md5(str(row['nursery_id']).encode()).hexdigest()
        # Take partial hash to create offset between -0.004 and +0.004
        lat_offset = (int(h[0:4], 16) / 65535 - 0.5) * 0.008
        lon_offset = (int(h[4:8], 16) / 65535 - 0.5) * 0.008
        return pd.Series([row['latitude'] + lat_offset, row['longitude'] + lon_offset])
    
    # Apply to all rows
    if not df.empty:
        df[['latitude', 'longitude']] = df.apply(apply_jitter, axis=1)

    def score_to_color(score):
        if score == 3: return 'red'
        if score == 2: return 'orange'
        if score == 1: return 'green'
        return 'gray'
        
    df['color'] = df['max_urgency_score'].apply(score_to_color)
    return df

def get_nursery_details(nursery_id):
    conn = get_db_connection()
    query = "SELECT * FROM dim_nurseries WHERE nursery_id = ?"
    # Ensure int for sqlite
    df = pd.read_sql_query(query, conn, params=(int(nursery_id),))
    conn.close()
    return df.iloc[0] if not df.empty else None

def get_active_roles(nursery_id):
    conn = get_db_connection()
    query = """
    SELECT DISTINCT r.role_id, r.role_name
    FROM fact_postings p
    JOIN dim_roles r ON p.role_id = r.role_id
    WHERE p.nursery_id = ? AND p.status = 'Open'
    """
    df = pd.read_sql_query(query, conn, params=(int(nursery_id),))
    conn.close()
    return df

@st.cache_data(ttl=600)
def get_candidates_for_position(nursery_id, role_id, revision):
    conn = get_db_connection()
    query = """
    SELECT 
        c.*, 
        a.application_id,
        a.current_status,
        a.match_score,
        a.distance_km,
        a.is_diploma_qualified
    FROM fact_applications a
    JOIN dim_candidates c ON a.candidate_id = c.candidate_id
    JOIN fact_postings p ON a.posting_id = p.posting_id
    WHERE p.nursery_id = ? AND p.role_id = ?
    ORDER BY a.match_score DESC
    """ 
    
    df = pd.read_sql_query(query, conn, params=(int(nursery_id), int(role_id)))
    conn.close()
    return df

def get_better_opportunity(candidate_lat, candidate_lon, target_dist, role_id):
    """Finds the SINGLE CLOSEST nursery with SAME role OPEN that is CLOSER than target_dist."""
    conn = get_db_connection()
    # Get all nurseries with open posting for this role
    query = """
    SELECT DISTINCT n.nursery_id, n.nursery_name, n.latitude, n.longitude
    FROM fact_postings p
    JOIN dim_nurseries n ON p.nursery_id = n.nursery_id
    WHERE p.role_id = ? AND p.status = 'Open' AND n.latitude IS NOT NULL
    """
    df_others = pd.read_sql_query(query, conn, params=(int(role_id),))
    conn.close()
    
    opportunities = []
    for _, row in df_others.iterrows():
        dist = haversine_distance(candidate_lat, candidate_lon, row['latitude'], row['longitude'])
        if dist is not None and dist < target_dist:
             opportunities.append({
                 'nursery_name': row['nursery_name'],
                 'latitude': row['latitude'],
                 'longitude': row['longitude'],
                 'distance': dist
             })
             
    # Sort by distance (asc) and take the first one (closest)
    if opportunities:
        opportunities.sort(key=lambda x: x['distance'])
        return opportunities[0] # Return the single best opportunity
    return None

@st.cache_data(ttl=600)
def get_application_history(candidate_id, current_nursery_id, revision):
    conn = get_db_connection()
    query = """
    SELECT DISTINCT n.nursery_name, n.latitude, n.longitude, r.role_name, a.current_status, a.application_date
    FROM fact_applications a
    JOIN fact_postings p ON a.posting_id = p.posting_id
    JOIN dim_nurseries n ON p.nursery_id = n.nursery_id
    JOIN dim_roles r ON p.role_id = r.role_id
    WHERE a.candidate_id = ? AND n.nursery_id != ?
    """
    df = pd.read_sql_query(query, conn, params=(int(candidate_id), int(current_nursery_id)))
    conn.close()
    return df

def update_application_status(application_id, new_status):
    conn = get_db_connection()
    conn.execute(
        "UPDATE fact_applications SET current_status = ?, last_update_date = CURRENT_TIMESTAMP WHERE application_id = ?",
        (new_status, int(application_id))
    )
    conn.commit()
    conn.close()
    # Increment revision to invalidate cache
    if 'data_revision' in st.session_state:
        st.session_state['data_revision'] += 1

@st.cache_data(ttl=600)
def get_all_applications_ranked(selected_urgency_colors, revision):
    conn = get_db_connection()
    # Build dynamic placeholders for IN clause
    placeholders = ','.join(['?'] * len(selected_urgency_colors))
    
    # Map colors to urgency levels (if needed) or assuming colors match logic
    # In load_nurseries_map_data we had: Red/Rouge, Orange, Green/Verte.
    # We should probably filter by the color logic.
    # Simpler approach: Fetch all open applications and filter in pandas or improved SQL?
    # Let's align with the map logic: 
    # Red -> ('Rouge', 'Red')
    # Orange -> ('Orange')
    # Green -> ('Verte', 'Green')
    
    urgency_filters = []
    params = []
    
    if 'red' in selected_urgency_colors:
        urgency_filters.append("p.urgency_level IN ('Rouge', 'Red')")
    if 'orange' in selected_urgency_colors:
        urgency_filters.append("p.urgency_level = 'Orange'")
    if 'green' in selected_urgency_colors:
        urgency_filters.append("p.urgency_level IN ('Verte', 'Green')")
        
    where_clause = " OR ".join(urgency_filters)
    if not where_clause:
        where_clause = "1=0" # Select nothing if no colors
        
    query = f"""
    SELECT 
        c.*, 
        a.application_id,
        a.current_status,
        a.match_score,
        a.distance_km,
        a.is_diploma_qualified,
        n.nursery_name,
        n.latitude as nursery_lat,
        n.longitude as nursery_lon,

        n.nursery_id,
        p.role_id,
        r.role_name
    FROM fact_applications a
    JOIN dim_candidates c ON a.candidate_id = c.candidate_id
    JOIN fact_postings p ON a.posting_id = p.posting_id
    JOIN dim_nurseries n ON p.nursery_id = n.nursery_id
    JOIN dim_roles r ON p.role_id = r.role_id
    WHERE p.status = 'Open' AND ({where_clause})
    ORDER BY a.match_score DESC
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def display_candidate_card(cand, nursery_context):
    """
    Reusable component to display a candidate card.
    cand: Series/Dict with candidate info + app info
    nursery_context: Dict with 'nursery_name', 'latitude', 'longitude', 'nursery_id' (if available)
    """
    score = round(cand['match_score'], 1) if cand['match_score'] else 0
    
    # Header format depends on context
    # If Global List, show Role & Nursery in header
    if 'role_name' in cand:
        header_text = f"{cand['first_name']} {cand['last_name']} ({cand['role_name']} @ {cand.get('nursery_name', '')}) - Match: {score}%"
    else:
        header_text = f"{cand['first_name']} {cand['last_name']} - Match: {score}%"

    with st.expander(header_text):
        col1, col2 = st.columns([1, 2])
        
        # Column 1: Profile
        with col1:
            # Status Editor
            current_status = cand.get('current_status') or 'Candidature'
            status_options = ['Candidature', 'Entretien', 'Refus', 'Embauché']
            
            if current_status not in status_options:
                status_options.append(current_status)
                
            new_status = st.selectbox(
                "Application Status",
                options=status_options,
                index=status_options.index(current_status),
                key=f"status_{cand['application_id']}"
            )
            
            if new_status != current_status:
                update_application_status(cand['application_id'], new_status)
                st.toast(f"Status updated to {new_status}!")
                st.rerun()

            st.markdown(f"**Email:** {cand['email']}")
            st.markdown(f"**Phone:** {cand['phone']}")
            st.markdown(f"**Distance:** {round(cand.get('distance_km', 0) or 0, 1)} km")
            st.metric("Match Score", f"{score}%")
            
            if cand['ai_summary']:
                st.info(f"**AI Summary:**\n{cand['ai_summary']}")
            else:
                st.text("No AI Summary available.")
                
            # Other Applications (Grouped by Status)
            # Use nursery_id from context for exclusion
            nursery_id_for_query = nursery_context.get('nursery_id', 0) 
            # If global list, cand['nursery_id'] might not be passed directly in nursery_context if it varies
            # But the query uses params. Let's rely on what we have.
            # History
            nursery_id_for_query = nursery_context.get('nursery_id', 0)
            history = get_application_history(cand['candidate_id'], nursery_id_for_query, st.session_state['data_revision'])
            if not history.empty:
                st.divider()
                st.markdown("**Prior Applications**")
                
                status_groups = history.groupby('current_status')
                for status, group in status_groups:
                    st.caption(f"**Stage: {status}**")
                    for _, app in group.iterrows():
                        st.markdown(f"- **{app['role_name']}** @ {app['nursery_name']}")
                        st.caption(f"Date: {app['application_date']}")
            else:
                st.divider()
                st.caption("No prior applications found.")

        # Column 2: Logistics Map
        with col2:
            st.markdown("**Logistics Map**")
            st.caption(":blue[Candidate] | :red[Target Nursery] | :green[Better Opportunity] | :grey[Other App]")
            
            cand_lat, cand_lon = cand.get('latitude'), cand.get('longitude')
            # Handle different field names if coming from different queries
            nurs_lat = nursery_context.get('latitude') or cand.get('nursery_lat')
            nurs_lon = nursery_context.get('longitude') or cand.get('nursery_lon')
            nurs_name = nursery_context.get('nursery_name') or cand.get('nursery_name')
            
            if cand_lat and cand_lon and nurs_lat and nurs_lon:
                viz_map = folium.Map(location=[cand_lat, cand_lon], zoom_start=11)
                
                # 1. Blue: Candidate
                folium.Marker(
                    [cand_lat, cand_lon], 
                    tooltip="Candidate Home",
                    icon=folium.Icon(color='blue', icon='user', prefix='fa')
                ).add_to(viz_map)
                
                # 2. Red: Target Nursery
                folium.Marker(
                    [nurs_lat, nurs_lon],
                    tooltip=f"Target: {nurs_name}",
                    icon=folium.Icon(color='red', icon='star', prefix='fa')
                ).add_to(viz_map)
                
                # 3. Gray: History
                # (Already fetched above, reuse?)
                for _, hist in history.iterrows():
                     folium.Marker(
                        [hist['latitude'], hist['longitude']],
                        tooltip=f"Applied: {hist['nursery_name']}",
                        icon=folium.Icon(color='gray', icon='history', prefix='fa')
                    ).add_to(viz_map)

                # 4. Green: Better Opportunity (Single Closest)
                # Need role_id. 
                # In Map View: selected_role_id available? No, passed via context? 
                # Wait, get_candidates_for_position returns joined columns. Does it select role_id?
                # get_candidates_for_position query: "SELECT c.*, a.application_id..." 
                # It does NOT explicitly select role_id from postings.
                # However, for Map View, we KNOW the role_id because we selected it in the UI (selected_role_id).
                # For Global View, we updated the query to include p.role_id.
                
                role_id_for_opp = cand.get('role_id')
                # Fallback for Map View if 'role_id' not in cand (it might not be in get_candidates_for_position DF yet)
                # Actually, in Map View calling display_candidate_card, we know the role logic.
                # Let's rely on cand['role_id'] being present. 
                # If it's missing in Map View's DF, we must ensure it's there.
                # get_candidates_for_position logic:
                # "SELECT c.*, ... FROM fact_applications a JOIN dim_candidates c ... JOIN fact_postings p ..."
                # We should add p.role_id to that query too if we want to be safe, OR pass it in context.
                # But wait, looking at lines 460+, we have `selected_role_id`.
                # Let's try to grab it from cand first.
                
                if not role_id_for_opp and 'role_id' in nursery_context:
                     role_id_for_opp = nursery_context['role_id']
                
                # If we still don't have it (e.g. Map View DF didn't have it and context didn't have it), we can't show opps.
                # NOTE: We need to ensure get_candidates_for_position includes role_id or we pass it.
                # I will assume we might need to patch get_candidates_for_position OR pass it in context.
                # Let's pass it in context in the main loop to be safe.
                
                if role_id_for_opp and cand.get('distance_km'):
                     better_opp = get_better_opportunity(cand_lat, cand_lon, cand['distance_km'], role_id_for_opp)
                     
                     if better_opp:
                         folium.Marker(
                            [better_opp['latitude'], better_opp['longitude']],
                            tooltip=f"Better Opportunity: {better_opp['nursery_name']} ({round(better_opp['distance'], 1)} km)",
                            icon=folium.Icon(color='green', icon='thumbs-up', prefix='fa') # changed icon
                        ).add_to(viz_map)
                
                st_folium(viz_map, width="100%", height=300, key=f"map_{cand['application_id']}") # Use app_id for unique key
            else:
                st.warning("Location data missing for map.")

        # CV Display (Full Width)
        st.divider()
        cv_path = os.path.join("export_cv (1)", cand['cv_filename']) if cand.get('cv_filename') else None
        
        if cv_path and os.path.exists(cv_path):
            if st.checkbox("View CV", key=f"show_cv_{cand['application_id']}"):
                with open(cv_path, "rb") as pdf_file:
                    st.download_button(
                        label="Download CV",
                        data=pdf_file,
                        file_name=cand['cv_filename'],
                        mime='application/pdf',
                        key=f"dl_{cand['application_id']}"
                    )
                pdf_html = display_pdf(cv_path)
                st.markdown(pdf_html, unsafe_allow_html=True)
        else:
            st.warning(f"CV file not found: {cand.get('cv_filename', 'Unknown')}")

# --- Main App ---

def main():
    st.set_page_config(page_title="Grandir Central Command", layout="wide")
    st.title("Grandir Network Map")

    if 'selected_nursery' not in st.session_state:
        st.session_state['selected_nursery'] = None
    if 'data_revision' not in st.session_state:
        st.session_state['data_revision'] = 0

    # Load Main Data
    df_nurseries = load_nurseries_map_data(st.session_state['data_revision'])
    
    # Navigation
    st.sidebar.title("Navigation")
    view = st.sidebar.radio("Go to", ["Map View", "Global Candidates"])
    
    # --- VIEW: Map View ---
    if view == "Map View":
        # Filters (Only visible in Map View)
        st.sidebar.divider()
        st.sidebar.header("Map Filters")
        show_apps_only = st.sidebar.checkbox("Has Applications Only")
        selected_colors = st.sidebar.multiselect(
            "Urgency Levels",
            options=['red', 'orange', 'green', 'gray'],
            default=['red', 'orange', 'green', 'gray'],
            format_func=lambda x: x.capitalize()
        )
        
        # Apply Filters
        filtered_df = df_nurseries[df_nurseries['color'].isin(selected_colors)]
        if show_apps_only:
            filtered_df = filtered_df[filtered_df['application_count'] > 0]

        # Main Map
        m = folium.Map(location=PARIS_COORDS, zoom_start=DEFAULT_ZOOM)
        for _, row in filtered_df.iterrows():
            folium.Marker(
                location=[row['latitude'], row['longitude']],
                popup=f"<b>{row['nursery_name']}</b><br>Apps: {row['application_count']}",
                tooltip=f"{row['nursery_name']} ({row['application_count']} apps)",
                icon=folium.Icon(color=row['color'], icon='info-sign')
            ).add_to(m)
            
        map_data = st_folium(m, width="100%", height=500)

        # Click Handling
        if map_data['last_object_clicked']:
            clicked_lat = map_data['last_object_clicked']['lat']
            clicked_lng = map_data['last_object_clicked']['lng']
            
            # Find nursery by close coordinate match
            match = df_nurseries[
                (abs(df_nurseries['latitude'] - clicked_lat) < 0.0001) & 
                (abs(df_nurseries['longitude'] - clicked_lng) < 0.0001)
            ]
            if not match.empty:
                # We must use .item() to convert numpy int to native python int
                selected_id = match.iloc[0]['nursery_id'].item()
                if st.session_state['selected_nursery'] != selected_id:
                    st.session_state['selected_nursery'] = selected_id
                    st.rerun()

        # Nursery Detail Dashboard
        if st.session_state['selected_nursery']:
            nursery_id = st.session_state['selected_nursery']
            nursery_data = get_nursery_details(nursery_id)
            
            st.divider()
            st.divider()
            st.header(f"Recruitment Dashboard: {nursery_data['nursery_name']}")
            
            # Position Filter
            active_roles = get_active_roles(nursery_id)
            if active_roles.empty:
                st.warning("No active job postings for this nursery.")
            else:
                role_options = {row['role_name']: row['role_id'] for _, row in active_roles.iterrows()}
                selected_role_name = st.selectbox("Select Position", options=list(role_options.keys()))
                selected_role_id = role_options[selected_role_name]
                
                # Candidate List
                candidates = get_candidates_for_position(nursery_id, selected_role_id, st.session_state['data_revision'])
                
                if candidates.empty:
                    st.info("No candidates found for this position.")
                else:
                    st.subheader(f"Candidates ({len(candidates)})")
                    
                    for _, cand in candidates.iterrows():
                        # Pass context
                        nursery_context = {
                            'nursery_id': nursery_id,
                            'nursery_name': nursery_data['nursery_name'],
                            'latitude': nursery_data['latitude'],
                            'longitude': nursery_data['longitude'],
                            'role_id': selected_role_id # Pass role_id for Map View context
                        }
                        display_candidate_card(cand, nursery_context)

    # --- VIEW: Global List ---
    elif view == "Global Candidates":
        # No sidebar filters here, or use defaults effectively meaning "All"
        # We fetch ALL urgency levels for the global list as per plan
        all_colors = ['red', 'orange', 'green']
        
        st.header("All Candidates (Global List)")
        st.caption("Sorted by Match Score (High to Low). Excludes closed positions.")
        
        all_candidates = get_all_applications_ranked(all_colors, st.session_state['data_revision'])
        
        if all_candidates.empty:
            st.info("No active applications found.")
        else:
            for _, cand in all_candidates.iterrows():
                # For global list, we pass context from the row
                nursery_context = {
                    'nursery_id': cand['nursery_id'],
                    'nursery_name': cand['nursery_name'],
                    'latitude': cand['nursery_lat'],
                    'longitude': cand['nursery_lon']
                }
                display_candidate_card(cand, nursery_context)

if __name__ == "__main__":
    main()
