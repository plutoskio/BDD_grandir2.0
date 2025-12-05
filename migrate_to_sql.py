import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Metier, Nursery, Job, Candidate, Application, Base
import xml.etree.ElementTree as ET
import pgeocode
import re

# Database connection
engine = create_engine('sqlite:///grandir.db')
Session = sessionmaker(bind=engine)
session = Session()

CANDIDATES_FILE = 'candidates.csv'
JOBS_FILE = 'jobs.csv'
KML_FILE = 'creche.kml'

def extract_zip(val):
    if pd.isna(val): return None
    match = re.search(r'\b\d{5}\b', str(val))
    return match.group(0) if match else None

def migrate():
    print("Loading CSVs...")
    df_c = pd.read_csv(CANDIDATES_FILE, low_memory=False)
    df_j = pd.read_csv(JOBS_FILE, low_memory=False)
    
    print("Parsing KML for Nurseries...")
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    nursery_locations = {}
    try:
        tree = ET.parse(KML_FILE)
        root = tree.getroot()
        placemarks = root.findall('.//kml:Placemark', ns)
        
        # We need to geocode these later or use pgeocode as in matching_engine
        # For this migration, we will use basic extraction and fallback to pgeocode
        nursery_zips = {}
        for p in placemarks:
            name = p.find('kml:name', ns).text
            if name:
                # Find Zip
                for data in p.findall('.//kml:Data', ns):
                    if data.get('name') == 'CODE POSTAL':
                        val = data.find('kml:value', ns).text
                        if val:
                             nursery_zips[name] = str(val).strip()
                             break
        
        # Geocode
        nomi = pgeocode.Nominatim('fr')
        unique_zips = list(set(nursery_zips.values()))
        geo_results = nomi.query_postal_code(unique_zips)
        zip_to_coords = {}
        for _, row in geo_results.iterrows():
            if not pd.isna(row['latitude']):
                zip_to_coords[row['postal_code']] = (row['latitude'], row['longitude'])
                
        for name, zip_c in nursery_zips.items():
            if zip_c in zip_to_coords:
                nursery_locations[name] = zip_to_coords[zip_c] + (zip_c,) # (lat, lon, zip)

    except Exception as e:
        print(f"KML Error: {e}")

    # --- 1. METIERS ---
    print("Migrating Metiers...")
    # Get unique jobs from Jobs file and Candidates (Candidates have 'Métiers' col, Jobs have 'Titre de l'annonce')
    job_titles = set(df_j['Titre de l\'annonce'].unique())
    cand_titles = set(df_c['Métiers'].dropna().unique())
    all_titles = job_titles.union(cand_titles)
    
    # Categorization Logic (Simplified from matching_engine)
    def get_cat(title):
        t = str(title).lower()
        if "infirmier" in t or "eje" in t or "educateur" in t or "auxiliaire de puériculture" in t:
            return "CAT 1"
        if "cap" in t or "auxiliaire petite enfance" in t:
            return "CAT 2"
        return "Unqualified"

    for title in all_titles:
        if pd.isna(title): continue
        if not session.query(Metier).filter_by(title=title).first():
            m = Metier(
                title=title, 
                category=get_cat(title),
                prerequisites="See Diploma Requirements"
            )
            session.add(m)
    session.commit()
    
    # Create map for fast lookup
    metier_map = {m.title: m.id for m in session.query(Metier).all()}
    
    # --- 2. NURSERIES ---
    print("Migrating Nurseries...")
    # From Jobs file + KML
    # Iterate jobs to find unique nurseries
    unique_nurseries = df_j[['CRECHES', 'Quelle est la couleur de la crèche ?', 'Localisation']].drop_duplicates()
    
    for _, row in unique_nurseries.iterrows():
        name = row['CRECHES']
        if pd.isna(name): continue
        
        # Check if exists (primary key)
        if session.query(Nursery).get(name): continue
        
        lat, lon, zip_code = None, None, None
        
        # Try KML first
        if name in nursery_locations:
            lat, lon, zip_code = nursery_locations[name]
        else:
            # Fallback to job location zip
            zip_code = extract_zip(row['Localisation'])
            if zip_code:
                # simple geocode
                res = nomi.query_postal_code(zip_code)
                if not pd.isna(res['latitude']):
                    lat, lon = res['latitude'], res['longitude']

        n = Nursery(
            name=name,
            address=row['Localisation'], # Raw string
            zip_code=zip_code,
            city=None, # Extract if needed
            latitude=lat,
            longitude=lon,
            urgency_color=row['Quelle est la couleur de la crèche ?']
        )
        session.add(n)
    session.commit()
    
    # --- 3. JOBS ---
    print("Migrating Jobs...")
    for _, row in df_j.iterrows():
        ref = row['Référence']
        if pd.isna(ref): continue
        if session.query(Job).get(ref): continue
        
        job = Job(
            reference=ref,
            title=row['Titre de l\'annonce'],
            metier_id=metier_map.get(row['Titre de l\'annonce']),
            nursery_name=row['CRECHES'],
            contract_type=row['Contrat'],
            status="Active" # Default
            # date_created parsing ignored for brevity
        )
        session.add(job)
    session.commit()
    
    # --- 4. CANDIDATES & APPLICATIONS ---
    print("Migrating Candidates & Applications...")
    # This is trickier because candidates can appear multiple times (once per application in the excel)
    # We need to deduplicate candidates but keep applications
    
    # Group by candidate unique identifier? 
    # Use index as ID since names/emails are gone?
    # Actually, we cleaned the data. Each row is an "application" technically in the original file, 
    # but we dropped duplicates. Let's assume each row in Candidates CSV is a unique application
    # but we need to link it to a Candidate IDENTITY.
    # Without Name/Email/Phone, "Candidate Identity" is hard to track across rows if they applied twice.
    # For now, we will create a NEW CANDIDATE for every row, assuming 1 row = 1 candidate profile for that specific app.
    # Ideally we'd deduplicate by key, but we deleted PII keys.
    
    nomi = pgeocode.Nominatim('fr')
    
    # Batch geocode candidates to speed up
    df_c['Zip'] = df_c['Code postal du candidat'].apply(extract_zip)
    unique_zips = df_c['Zip'].unique()
    unique_zips = [z for z in unique_zips if z]
    res = nomi.query_postal_code(unique_zips)
    zip_map = {}
    for _, r in res.iterrows():
        if not pd.isna(r['latitude']):
            zip_map[r['postal_code']] = (r['latitude'], r['longitude'])

    batch_size = 1000
    candidates_list = []
    applications_list = []
    
    for idx, row in df_c.iterrows():
        zip_c = row['Zip']
        lat, lon = zip_map.get(zip_c, (None, None))
        
        # Create Candidate
        cand = Candidate(
            city=row.get('Ville du candidat'),
            zip_code=zip_c,
            latitude=lat,
            longitude=lon,
            current_diploma=row.get('Diplôme'),
            experience_years=None # Not cleanly available
        )
        session.add(cand)
        session.flush() # Get ID
        
        # Create Application
        app = Application(
            candidate_id=cand.id,
            job_reference=row.get('Référence de l’annonce'),
            status=row.get('Statut'),
            step=row.get('Etape'),
            date_applied=row.get('Date'),
            source=row.get('Provenance')
        )
        session.add(app)
        
        if idx % batch_size == 0:
            session.commit()
            print(f"Processed {idx} candidates...")
            
    session.commit()
    print("Migration Complete.")

if __name__ == "__main__":
    migrate()
