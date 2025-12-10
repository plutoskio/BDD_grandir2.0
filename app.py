import streamlit as st
import pandas as pd
import sqlite3
import folium
from streamlit_folium import st_folium

# --- Configuration ---
DB_PATH = "grandir.db"
PARIS_COORDS = [48.8566, 2.3522]
DEFAULT_ZOOM = 12

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_data():
    """
    Loads nursery locations and determines their urgency color
    based on the most urgent open posting.
    """
    conn = get_db_connection()
    
    # Query to get nurseries, their max urgency (for open postings) and application count
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
    
    # Map score back to color
    def score_to_color(score):
        if score == 3: return 'red'
        if score == 2: return 'orange'
        if score == 1: return 'green'
        return 'gray' # No open postings or no urgency info
        
    df['color'] = df['max_urgency_score'].apply(score_to_color)
    return df

def main():
    st.set_page_config(page_title="Grandir Central Command", layout="wide")
    st.title("📍 Grandir Network Map")

    # Load Data
    with st.spinner("Loading nursery data..."):
        df_nurseries = load_data()
    
    # Sidebar Filters
    st.sidebar.header("Filters")
    
    # Checkbox for Applications
    show_only_with_applications = st.sidebar.checkbox("Has Applications Only")
    
    selected_colors = st.sidebar.multiselect(
        "Select Urgency Levels",
        options=['red', 'orange', 'green', 'gray'],
        default=['red', 'orange', 'green', 'gray'],
        format_func=lambda x: x.capitalize()
    )

    # Filter Data
    filtered_df = df_nurseries[df_nurseries['color'].isin(selected_colors)]
    
    if show_only_with_applications:
        filtered_df = filtered_df[filtered_df['application_count'] > 0]

    # Create Map
    m = folium.Map(location=PARIS_COORDS, zoom_start=DEFAULT_ZOOM)

    # Add Markers
    for _, row in filtered_df.iterrows():
        folium.Marker(
            location=[row['latitude'], row['longitude']],
            popup=f"<b>{row['nursery_name']}</b><br>Apps: {row['application_count']}",
            tooltip=f"{row['nursery_name']} ({row['application_count']} apps)",
            icon=folium.Icon(color=row['color'], icon='info-sign')
        ).add_to(m)

    # Display Map
    st_folium(m, width="100%", height=600)

if __name__ == "__main__":
    main()
