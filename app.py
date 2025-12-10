import streamlit as st
import pandas as pd
import sqlite3
import folium
from streamlit_folium import st_folium
import math

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

def load_nurseries_map_data():
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

def get_candidates_for_position(nursery_id, role_id):
    conn = get_db_connection()
    query = """
    SELECT 
        c.*, 
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

def get_closer_opportunities(candidate_lat, candidate_lon, target_dist, role_id):
    """Finds other nurseries with SAME role OPEN that are CLOSER."""
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
    return opportunities

def get_application_history(candidate_id, current_nursery_id):
    conn = get_db_connection()
    query = """
    SELECT DISTINCT n.nursery_name, n.latitude, n.longitude
    FROM fact_applications a
    JOIN fact_postings p ON a.posting_id = p.posting_id
    JOIN dim_nurseries n ON p.nursery_id = n.nursery_id
    WHERE a.candidate_id = ? AND n.nursery_id != ? AND n.latitude IS NOT NULL
    """
    df = pd.read_sql_query(query, conn, params=(int(candidate_id), int(current_nursery_id)))
    conn.close()
    return df

# --- Main App ---

def main():
    st.set_page_config(page_title="Grandir Central Command", layout="wide")
    st.title("📍 Grandir Network Map")

    if 'selected_nursery' not in st.session_state:
        st.session_state['selected_nursery'] = None

    # Load Main Data
    df_nurseries = load_nurseries_map_data()
    
    # filters
    st.sidebar.header("Map Filters")
    show_apps_only = st.sidebar.checkbox("Has Applications Only")
    selected_colors = st.sidebar.multiselect(
        "Urgency Levels",
        options=['red', 'orange', 'green', 'gray'],
        default=['red', 'orange', 'green', 'gray'],
        format_func=lambda x: x.capitalize()
    )
    
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

    # --- Dashboard ---
    if st.session_state['selected_nursery']:
        nursery_id = st.session_state['selected_nursery']
        nursery_data = get_nursery_details(nursery_id)
        
        st.divider()
        st.header(f"🏥 Recruitment Dashboard: {nursery_data['nursery_name']}")
        
        # Position Filter
        active_roles = get_active_roles(nursery_id)
        if active_roles.empty:
            st.warning("No active job postings for this nursery.")
        else:
            role_options = {row['role_name']: row['role_id'] for _, row in active_roles.iterrows()}
            selected_role_name = st.selectbox("Select Position", options=list(role_options.keys()))
            selected_role_id = role_options[selected_role_name]
            
            # Candidate List
            candidates = get_candidates_for_position(nursery_id, selected_role_id)
            
            if candidates.empty:
                st.info("No candidates found for this position.")
            else:
                st.subheader(f"Candidates ({len(candidates)})")
                
                for _, cand in candidates.iterrows():
                    score = round(cand['match_score'], 1) if cand['match_score'] else 0
                    
                    with st.expander(f"👤 {cand['first_name']} {cand['last_name']} - Match: {score}%"):
                        col1, col2 = st.columns([1, 2])
                        
                        # Column 1: Profile
                        with col1:
                            st.markdown(f"**Email:** {cand['email']}")
                            st.markdown(f"**Phone:** {cand['phone']}")
                            st.markdown(f"**Distance:** {round(cand.get('distance_km', 0) or 0, 1)} km")
                            st.metric("Match Score", f"{score}%")
                            
                            if cand['ai_summary']:
                                st.info(f"**AI Summary:**\n{cand['ai_summary']}")
                            else:
                                st.text("No AI Summary available.")
                                
                            st.markdown("[📄 View CV (Mock Link)](https://example.com)")

                        # Column 2: Logistics Map
                        with col2:
                            st.markdown("**🗺️ Logistics Map**")
                            
                            # Legend
                            st.caption("🔵 Candidate | 🔴 This Nursery | 🟢 Closer Opportunities | ⚪ Other App")
                            
                            cand_lat, cand_lon = cand['latitude'], cand['longitude']
                            nurs_lat, nurs_lon = nursery_data['latitude'], nursery_data['longitude']
                            
                            if cand_lat and cand_lon:
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
                                    tooltip=f"Target: {nursery_data['nursery_name']}",
                                    icon=folium.Icon(color='red', icon='star', prefix='fa')
                                ).add_to(viz_map)
                                
                                # 3. Gray: Other App
                                history = get_application_history(cand['candidate_id'], nursery_id)
                                for _, hist in history.iterrows():
                                    folium.Marker(
                                        [hist['latitude'], hist['longitude']],
                                        tooltip=f"Applied: {hist['nursery_name']}",
                                        icon=folium.Icon(color='gray', icon='history', prefix='fa')
                                    ).add_to(viz_map)
                                    
                                # 4. Green: Closer Opportunities
                                current_dist = haversine_distance(cand_lat, cand_lon, nurs_lat, nurs_lon)
                                if current_dist:
                                    closer_ops = get_closer_opportunities(cand_lat, cand_lon, current_dist, selected_role_id)
                                    for op in closer_ops:
                                        folium.Marker(
                                            [op['latitude'], op['longitude']],
                                            tooltip=f"Closer: {op['nursery_name']} ({round(op['distance'],1)}km)",
                                            icon=folium.Icon(color='green', icon='arrow-up', prefix='fa')
                                        ).add_to(viz_map)
                                        
                                st_folium(viz_map, width="100%", height=300, key=f"map_{cand['candidate_id']}")
                            else:
                                st.warning("Candidate has no geocoded location.")

if __name__ == "__main__":
    main()
