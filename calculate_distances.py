#!/usr/bin/env python3
"""
Distance Calculation Script for BDD_GRANDIR
Calculates distances between candidates and nurseries, populates fact_applications.distance_km
"""

import sqlite3
import xml.etree.ElementTree as ET
from math import radians, cos, sin, asin, sqrt
import pgeocode

# Database connection
DB_NAME = "grandir.db"

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points on Earth (in km)
    Using the Haversine formula
    """
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Radius of Earth in kilometers
    km = 6371 * c
    return round(km, 2)


def get_nursery_coordinates_from_db():
    """
    Get nursery coordinates by geocoding their postal codes from the database
    Returns dict: {nursery_id: (latitude, longitude)}
    """
    print(f"Geocoding nursery locations from postal codes...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT nursery_id, nursery_name, postal_code FROM dim_nurseries")
    nurseries = cursor.fetchall()
    conn.close()
    
    nomi = pgeocode.Nominatim('fr')  # France
    nursery_coords = {}
    
    for nursery_id, nursery_name, postal_code in nurseries:
        if not postal_code:
            continue
            
        # Clean postal code
        if isinstance(postal_code, float):
            postal_code = str(int(postal_code))
        else:
            postal_code = str(postal_code).strip().replace(' ', '')
            # Remove .0 suffix if present
            if '.' in postal_code:
                postal_code = postal_code.split('.')[0]
        
        location = nomi.query_postal_code(postal_code)
        
        if location is not None and not location.isna().all():
            nursery_coords[nursery_id] = (location.latitude, location.longitude)
    
    print(f"Found {len(nursery_coords)} nurseries with coordinates")
    return nursery_coords


def get_candidate_coordinates_from_db(candidate_id):
    """
    Get GPS coordinates for a candidate from the database
    Returns (latitude, longitude) or None if not found
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT latitude, longitude FROM dim_candidates WHERE candidate_id = ?", (candidate_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0] is not None and result[1] is not None:
        return (result[0], result[1])
    
    return None


def calculate_and_update_distances():
    """
    Main function to calculate distances and update the database
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get nursery coordinates by geocoding postal codes
    nursery_coords = get_nursery_coordinates_from_db()
    
    # Get all applications with candidate and nursery information
    query = """
    SELECT 
        fa.application_id,
        c.candidate_id,
        c.first_name,
        c.last_name,
        c.postal_code as candidate_postal,
        n.nursery_id,
        n.nursery_name
        FROM fact_applications fa
    JOIN dim_candidates c ON fa.candidate_id = c.candidate_id
    JOIN fact_postings fp ON fa.posting_id = fp.posting_id
    JOIN dim_nurseries n ON fp.nursery_id = n.nursery_id
    WHERE fa.distance_km IS NULL
    """
    
    cursor.execute(query)
    applications = cursor.fetchall()
    
    print(f"\nProcessing {len(applications)} applications...")
    
    # Cache for candidate coordinates
    candidate_coords_cache = {}
    
    updated_count = 0
    skipped_count = 0
    
    for app in applications:
        app_id, cand_id, first_name, last_name, cand_postal, nurs_id, nurs_name = app
        
        # Get candidate coordinates from database (AI-geocoded)
        if cand_id not in candidate_coords_cache:
            cand_coords = get_candidate_coordinates_from_db(cand_id)
            candidate_coords_cache[cand_id] = cand_coords
        else:
            cand_coords = candidate_coords_cache[cand_id]
        
        if cand_coords is None:
            print(f"⚠️  No coordinates for candidate {first_name} {last_name}")
            skipped_count += 1
            continue
        
        # Get nursery coordinates from geocoding (using nursery_id)
        nurs_coords = nursery_coords.get(nurs_id)
        
        if nurs_coords is None:
            print(f"⚠️  Could not geocode nursery: {nurs_name}")
            skipped_count += 1
            continue
        
        # Calculate distance
        cand_lat, cand_lon = cand_coords
        nurs_lat, nurs_lon = nurs_coords
        
        distance = haversine(cand_lat, cand_lon, nurs_lat, nurs_lon)
        
        # Update database
        cursor.execute(
            "UPDATE fact_applications SET distance_km = ? WHERE application_id = ?",
            (distance, app_id)
        )
        
        updated_count += 1
        
        if updated_count % 10 == 0:
            print(f"✓ Processed {updated_count} applications...")
    
    # Commit changes
    conn.commit()
    
    print(f"\n{'='*60}")
    print(f"✅ COMPLETE: Updated {updated_count} applications")
    print(f"⚠️  Skipped {skipped_count} applications (missing coordinates)")
    print(f"{'='*60}")
    
    # Show sample results
    print("\nSample distances calculated:")
    cursor.execute("""
        SELECT 
            c.first_name || ' ' || c.last_name as candidate,
            n.nursery_name,
            fa.distance_km
        FROM fact_applications fa
        JOIN dim_candidates c ON fa.candidate_id = c.candidate_id
        JOIN fact_postings fp ON fa.posting_id = fp.posting_id
        JOIN dim_nurseries n ON fp.nursery_id = n.nursery_id
        WHERE fa.distance_km IS NOT NULL
        ORDER BY fa.distance_km
        LIMIT 10
    """)
    
    print("\nClosest matches:")
    for row in cursor.fetchall():
        print(f"  {row[0]:30} → {row[1]:40} ({row[2]:.2f} km)")
    
    conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("BDD_GRANDIR Distance Calculation")
    print("=" * 60)
    calculate_and_update_distances()
