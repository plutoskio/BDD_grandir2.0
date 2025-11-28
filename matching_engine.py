import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
import pgeocode
import re
from math import radians, cos, sin, asin, sqrt

# --- Configuration ---
KML_FILE = 'creche.kml'
CANDIDATES_FILE = 'liste-des-candidatures_anonymized.xls'
JOBS_FILE = 'liste-des-postes_anonymized.xls'

print("Initializing Grandir Central Command - Precision Geolocation Engine...")

# --- 1. Load Data ---
print("Loading datasets...")
try:
    df_candidates = pd.read_excel(CANDIDATES_FILE)
    df_jobs = pd.read_excel(JOBS_FILE)
except FileNotFoundError:
    df_candidates = pd.read_csv('Liste des candidatures.csv')
    df_jobs = pd.read_csv('Liste des annonces.csv')

print(f"Loaded {len(df_candidates)} candidates and {len(df_jobs)} jobs.")

# --- 2. Supply Side: Parse KML & Geocode Nurseries ---
print("Parsing KML and Geocoding Nurseries...")

ns = {'kml': 'http://www.opengis.net/kml/2.2'}
nursery_locations = {} # Name -> (Lat, Lon)
nursery_zips = {} # Name -> Zip

try:
    tree = ET.parse(KML_FILE)
    root = tree.getroot()
    placemarks = root.findall('.//kml:Placemark', ns)
    
    for p in placemarks:
        name = p.find('kml:name', ns).text
        if not name:
            continue
            
        # Extract Zip from ExtendedData
        zip_code = None
        for data in p.findall('.//kml:Data', ns):
            if data.get('name') == 'CODE POSTAL':
                zip_code = data.find('kml:value', ns).text
                break
        
        if zip_code:
            nursery_zips[name] = str(zip_code).strip()
            
except Exception as e:
    print(f"Warning: Failed to parse KML: {e}")

# Use pgeocode to get Lat/Lon for Nurseries (since KML lacked explicit coordinates)
nomi = pgeocode.Nominatim('fr')

# Batch geocode unique zips to save time
unique_zips = list(set(nursery_zips.values()))
geo_results = nomi.query_postal_code(unique_zips)
zip_to_coords = {}

for _, row in geo_results.iterrows():
    if not pd.isna(row['latitude']) and not pd.isna(row['longitude']):
        zip_to_coords[row['postal_code']] = (row['latitude'], row['longitude'])

# Map back to Nurseries
for name, zip_code in nursery_zips.items():
    if zip_code in zip_to_coords:
        nursery_locations[name] = zip_to_coords[zip_code]

print(f"Geocoded {len(nursery_locations)} nurseries from KML.")

# --- 3. Demand Side: Geocode Candidates ---
print("Geocoding Candidates...")

def extract_zip(val):
    if pd.isna(val):
        return None
    match = re.search(r'\b\d{5}\b', str(val))
    if match:
        return match.group(0)
    return None

df_candidates['Candidate_Zip'] = df_candidates['Code postal du candidat'].apply(extract_zip)

# Batch geocode candidates
cand_zips = df_candidates['Candidate_Zip'].unique()
cand_zips = [z for z in cand_zips if z] # Filter None
cand_geo_results = nomi.query_postal_code(cand_zips)
cand_zip_map = {}

for _, row in cand_geo_results.iterrows():
    if not pd.isna(row['latitude']) and not pd.isna(row['longitude']):
        cand_zip_map[row['postal_code']] = (row['latitude'], row['longitude'])

def get_cand_coords(zip_code):
    return cand_zip_map.get(zip_code, (None, None))

# Apply to DataFrame
coords = df_candidates['Candidate_Zip'].apply(get_cand_coords)
df_candidates['Cand_Lat'] = coords.apply(lambda x: x[0])
df_candidates['Cand_Lon'] = coords.apply(lambda x: x[1])

# --- 4. Merge & Match ---
print("Merging Data...")

# Filter Candidates (Interview Pool)
target_statuses = ["Présélection", "A contacter", "Entretien", "Qualification"]
status_pattern = "|".join(target_statuses)
df_pool = df_candidates[
    df_candidates['Statut'].str.contains(status_pattern, case=False, na=False) | 
    df_candidates['Etape'].str.contains(status_pattern, case=False, na=False)
].copy()

# Prepare Jobs Data
df_jobs['Job_Zip'] = df_jobs['Localisation'].apply(extract_zip)

# Function to get Job Coords (Try KML Name match, then Zip fallback)
def get_job_coords(row):
    name = str(row.get('CRECHES', ''))
    
    # Exact match
    if name in nursery_locations:
        return nursery_locations[name]
    
    # Fuzzy match could go here, but for now fallback to Zip
    zip_code = row.get('Job_Zip')
    if zip_code in zip_to_coords:
        return zip_to_coords[zip_code]
        
    # Fallback: query pgeocode if not in cache
    if zip_code:
        res = nomi.query_postal_code(zip_code)
        if not pd.isna(res['latitude']):
             return (res['latitude'], res['longitude'])
             
    return (None, None)

# Pre-calculate Job Coords
job_coords = df_jobs.apply(get_job_coords, axis=1)
df_jobs['Job_Lat'] = job_coords.apply(lambda x: x[0])
df_jobs['Job_Lon'] = job_coords.apply(lambda x: x[1])

# Merge
df_merged = pd.merge(
    df_pool,
    df_jobs[['Référence', 'CAT', 'Quelle est la couleur de la crèche ?', 'Job_Lat', 'Job_Lon', "Titre de l'annonce", 'CRECHES']],
    left_on='Référence de l’annonce',
    right_on='Référence',
    how='left'
)

# --- 5. Distance & Scoring ---

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
    r = 6371 # Radius of earth in kilometers. Use 3956 for miles
    return c * r

df_merged['Distance_KM'] = df_merged.apply(
    lambda row: haversine(row['Cand_Lon'], row['Cand_Lat'], row['Job_Lon'], row['Job_Lat']), axis=1
)

def get_distance_score(km):
    if pd.isna(km):
        return 0
    if km < 3:
        return 100
    elif km < 10:
        return 80
    elif km < 20:
        return 50
    else:
        return 0

df_merged['Distance_Score'] = df_merged['Distance_KM'].apply(get_distance_score)

# Compliance & Urgency (Same as before)
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

df_merged['Candidate_CAT'] = df_merged.apply(get_candidate_cat, axis=1)

def get_compliance_score(cand_cat, job_cat):
    if pd.isna(job_cat): return 0
    job_cat_str = str(job_cat).upper()
    if cand_cat == "Unqualified": return 0
    if "CAT 1" in job_cat_str:
        return 100 if cand_cat == "CAT 1" else 0
    elif "CAT 2" in job_cat_str:
        return 100 if cand_cat in ["CAT 1", "CAT 2"] else 0
    elif "CAT 3" in job_cat_str:
         return 100
    return 0

df_merged['Compliance_Score'] = df_merged.apply(lambda row: get_compliance_score(row['Candidate_CAT'], row['CAT']), axis=1)

def get_urgency_score(color):
    if pd.isna(color): return 30
    color = str(color).lower()
    if "rouge" in color: return 100
    elif "orange" in color: return 70
    else: return 30

df_merged['Urgency_Score'] = df_merged['Quelle est la couleur de la crèche ?'].apply(get_urgency_score)

df_merged['Grandir_Score'] = (
    df_merged['Urgency_Score'] * 0.4 +
    df_merged['Distance_Score'] * 0.3 +
    df_merged['Compliance_Score'] * 0.3
)

# --- 6. Outputs ---

# Hot List
hot_list = df_merged.sort_values(by='Grandir_Score', ascending=False).head(20)
print("\n=== THE HOT LIST (Top 20) ===")
hot_list['Candidate_ID'] = hot_list.index
cols = ['Candidate_ID', 'Statut', 'Distance_KM', 'Grandir_Score', 'Candidate_CAT', 'Urgency_Score']
print(hot_list[cols].to_string(index=False))


# Opportunity Radar
print("\n=== OPPORTUNITY RADAR (Redirections) ===")
# Criteria: Applied to Green (Urgency <= 30) AND Distance > 10km
candidates_to_check = df_merged[
    (df_merged['Urgency_Score'] <= 30) & 
    (df_merged['Distance_KM'] > 10) &
    (df_merged['Candidate_CAT'] != "Unqualified")
].copy()

# High Urgency Jobs (Red)
red_jobs = df_jobs[
    df_jobs['Quelle est la couleur de la crèche ?'].str.contains("Rouge", case=False, na=False)
].copy()

# We need Red Jobs Coords
red_jobs = red_jobs.dropna(subset=['Job_Lat', 'Job_Lon'])

redirects = []

for _, cand in candidates_to_check.iterrows():
    c_lat, c_lon = cand['Cand_Lat'], cand['Cand_Lon']
    if pd.isna(c_lat): continue
    
    # Find Red Jobs < 5km
    # Vectorized distance calc would be better but loop is okay for prototype
    
    # Quick filter by lat/lon box to avoid calc for all
    # 1 deg lat ~ 111km. 5km ~ 0.045 deg
    nearby_jobs = red_jobs[
        (red_jobs['Job_Lat'].between(c_lat - 0.05, c_lat + 0.05)) &
        (red_jobs['Job_Lon'].between(c_lon - 0.05, c_lon + 0.05))
    ]
    
    for _, job in nearby_jobs.iterrows():
        dist = haversine(c_lon, c_lat, job['Job_Lon'], job['Job_Lat'])
        if dist < 5:
            # Check Compliance
            if get_compliance_score(cand['Candidate_CAT'], job['CAT']) == 100:
                redirects.append({
                    "Candidate_ID": cand.name, # Index
                    "Current_Job_Dist": round(cand['Distance_KM'], 1),
                    "Redirect_Nursery": job['CRECHES'],
                    "Redirect_Dist": round(dist, 1),
                    "Distance_Saved": round(cand['Distance_KM'] - dist, 1)
                })
                break # Found one good redirect, move to next candidate

df_redirects = pd.DataFrame(redirects)
if not df_redirects.empty:
    print(df_redirects.head(20).to_string(index=False))
else:
    print("No redirections found.")
