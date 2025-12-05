import pandas as pd
import glob
import os
import json
import re
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Base, Metier, Nursery, Job, Candidate, Application
from pypdf import PdfReader
import google.generativeai as genai
import time
import pgeocode

# --- Configuration ---
DB_URL = 'sqlite:///grandir.db'
CANDIDATE_CSV = 'candidates_fresh.csv'
JOBS_CSV = 'jobs_fresh.csv'
CV_DIR = 'export_cv (1)'  # User's folder name

# Configure Gemini
API_KEY = os.environ.get("GOOGLE_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
else:
    print("WARNING: GOOGLE_API_KEY not found. AI extraction will be skipped.")
    model = None

# --- Helpers ---
def extract_text_from_pdf(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return ""

def clean_phone(phone):
    if pd.isna(phone): return ""
    phone = str(phone)
    phone = re.sub(r'[\s\.\-\(\)]', '', phone)
    # normalize +33
    if phone.startswith('+33'): phone = '0' + phone[3:]
    return phone

def get_ai_data(cv_text, job_context="Recruitment"):
    if not model:
        return None
    
    prompt = f"""
    You are an expert recruiter. Analyze the following CV text.
    Extract the following information in JSON format:
    1. "diploma_ai": The highest relevant diploma for childcare (e.g., "Infirmier", "CAP AEPE", "EJE", "Auxiliaire de Puériculture"). If none, return "None".
    2. "experience_ai": Total years of experience in childcare/health sector as a number or string (e.g. "5 years").
    3. "closeness_score": A score from 0 to 100 on how well this candidate fits a general childcare role based on stability and relevant experience.
    4. "qualitative_analysis": A 1-sentence explanation of the score.

    CV Text:
    {cv_text[:3000]}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text
        # Extract JSON from code block if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
            
        data = json.loads(text)
        return data
    except Exception as e:
        print(f"AI Error: {e}")
        return None

# --- Ingestion Logic ---

def run_ingestion():
    # 1. Setup DB
    engine = create_engine(DB_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # 2. Load Candidates Data
    print("Loading Candidates CSV...")
    df_c = pd.read_csv(CANDIDATE_CSV, low_memory=False)
    
    # Create Index: Email -> Row, CleanPhone -> Row, "Name Surname" -> Row
    # We prioritize Email.
    candidates_index = {}
    
    print("Indexing Candidates...")
    for idx, row in df_c.iterrows():
        # Helpers
        email = str(row.get('Email', '')).strip().lower()
        if email and '@' in email:
            candidates_index[email] = row
            
        # Name matching logic (Fallback)
        first = str(row.get('Prénom', '')).strip().lower()
        last = str(row.get('Nom', '')).strip().lower()
        full = f"{first} {last}"
        if len(full) > 2:
           candidates_index[full] = row
           # Also simplified "Last First"
           candidates_index[f"{last} {first}"] = row

    # 3. Process CVs
    print(f"Processing CVs in {CV_DIR}...")
    pdf_files = list(Path(CV_DIR).glob("*.pdf"))
    
    matched_count = 0
    
    # Geocoder
    nomi = pgeocode.Nominatim('fr')
    
    for pdf_path in pdf_files:
        # Extract Text
        content = extract_text_from_pdf(pdf_path)
        if not content: continue
        
        # 1. Email Match
        found_emails = re.findall(r'[\w\.-]+@[\w\.-]+', content)
        for e in found_emails:
            if e.lower() in candidates_index:
                match_row = candidates_index[e.lower()]
                break
        
        # 2. Phone Match (if no email match)
        if match_row is None:
            # Extract potential phone numbers (digit sequences len 10+)
            # Normalize content phones?
            # Simple heuristic: look for 10 digit sequences
            found_nums = re.findall(r'\d{2}[\s\.-]?\d{2}[\s\.-]?\d{2}[\s\.-]?\d{2}[\s\.-]?\d{2}', content)
            found_nums = [clean_phone(n) for n in found_nums]
            
            # We need a Phone Index. (Let's build it on the fly or pre-build? Pre-build is better but index is currently partial)
            # Let's just scan the `candidates_index` keys if they look like phones? 
            # Better: In Step 2 (Indexing), we didn't index phones. Let's rely on Full Scans for now or add Phone Index.
            # Adding Phone Index to 'candidates_index' in Step 2 would be cleaner. 
            pass 

        # 3. Content Name Match (Robust Fallback)
        if match_row is None:
            # For 50 PDFs, we can afford to scan the index logic inverted?
            # Or better: Extract "Proper Nouns" from text? No.
            # Check if *Candidate Name* is in Text.
            # But which candidate? We have 36k. 
            # Optimization: 36k checks * 50 files = 1.8M string searches. Python can do this.
            # Iterate through df_c directly?
            
            content_lower = content.lower()
            # Heuristic: Check "First Last" and "Last First"
            # We prioritize less common names? No, just First+Last.
            
            # This is slow but effective for small N_CVs.
            # We assume df_c is available here.
            for _, row in df_c.iterrows():
                p = str(row.get('Prénom', '')).strip().lower()
                n = str(row.get('Nom', '')).strip().lower()
                if len(p) < 2 or len(n) < 2: continue
                
                full_1 = f"{p} {n}"
                full_2 = f"{n} {p}"
                
                if full_1 in content_lower or full_2 in content_lower:
                    match_row = row
                    break
        
        if match_row is None:
            print(f"Skipping {pdf_path.name} (No match found. Text len: {len(content)}. 'Image-only'?: {len(content) < 100})")
            continue
            
        matched_count += 1
        print(f"Match! {match_row['Prénom']} {match_row['Nom']} ({pdf_path.name})")
        
        # AI Extraction
        ai_data = get_ai_data(content)
        
        # Geocode
        lat, lon = None, None
        zip_code = match_row.get('Code postal', match_row.get('Code postal du candidat', ''))
        if pd.notna(zip_code):
            z = str(zip_code)[:5] # clean
            loc = nomi.query_postal_code(z)
            if not pd.isna(loc.latitude):
                lat, lon = loc.latitude, loc.longitude
        
        # Create Candidate
        cand = Candidate(
            first_name=match_row.get('Prénom', ''),
            last_name=match_row.get('Nom', ''),
            email=match_row.get('Email', ''),
            phone=str(match_row.get('Téléphone', '')),
            city=match_row.get('Ville', match_row.get('Ville du candidat', '')),
            zip_code=str(zip_code),
            latitude=lat, 
            longitude=lon,
            current_diploma=match_row.get('Diplôme', match_row.get('Diplôme du candidat', '')),
            experience_years=match_row.get("Années d'expérience", ''),
            
            # New Fields
            cv_text=content,
            diploma_ai=ai_data.get('diploma_ai') if ai_data else None,
            experience_ai=ai_data.get('experience_ai') if ai_data else None,
            closeness_score=ai_data.get('closeness_score') if ai_data else None,
            qualitative_analysis=ai_data.get('qualitative_analysis') if ai_data else None
        )
        session.add(cand)
        
    session.commit()
    print(f"Ingested {matched_count} candidates from CVs.")
    
    # 4. Load Jobs
    print("Loading Jobs...")
    df_j = pd.read_csv(JOBS_CSV, low_memory=False)
    
    # Helpers for Metier
    def get_cat(title):
        t = str(title).lower()
        if 'auxiliaire' in t: return 'CAT 2'
        if 'infirmier' in t or 'eje' in t or 'educateur' in t or 'directeur' in t: return 'CAT 1'
        return 'Other'
        
    # Cache Metiers
    metiers_cache = {}
    
    jobs_count = 0
    for _, row in df_j.iterrows():
        title = row.get("Titre de l'annonce", row.get('Libellé du poste', row.get('Intitulé de poste', 'Unknown')))
        # Debug Title
        # print(f"DEBUG TITLE: {title}")
        if pd.isna(title): continue
        
        # Metier
        if title not in metiers_cache:
            m = session.query(Metier).filter_by(title=title).first()
            if not m:
                m = Metier(title=title, category=get_cat(title))
                session.add(m)
                session.commit() # commit to get ID
            metiers_cache[title] = m
        else:
            m = metiers_cache[title]
            
        # Nursery
        # CSV has 'CRECHES' for name, and 'Localisation' for address (e.g. "Address,  Zip City, France")
        n_name = row.get('CRECHES', row.get('Etablissement', 'Unknown'))
        if pd.isna(n_name): n_name = "Unknown Nursery"
        
        # Geocode Nursery if needed
        existing_n = session.query(Nursery).get(n_name)
        if not existing_n:
            # Parse Localisation
            raw_loc = str(row.get('Localisation', ''))
            # Regex to find Zip (5 digits)
            # Example: "30 Rue Eugène Berthoud,  93400 Saint-Ouen-sur-Seine, France"
            n_zip = ""
            n_city = ""
            n_addr = raw_loc
            
            zip_match = re.search(r'\b(\d{5})\b', raw_loc)
            if zip_match:
                n_zip = zip_match.group(1)
                # Assume city is after zip?
                # Simple split attempt:
                parts = raw_loc.split(n_zip)
                if len(parts) > 1:
                     # parts[0] is address, parts[1] is " City, France"
                     n_addr = parts[0].strip().strip(',')
                     n_city = parts[1].split(',')[0].strip()
            
            lat, lon = None, None
            if n_zip:
                loc = nomi.query_postal_code(n_zip)
                if not pd.isna(loc.latitude):
                    lat, lon = loc.latitude, loc.longitude
            
            # Urgency Color query
            urgency = row.get('Quelle est la couleur de la crèche ?', 'Rouge')
            
            existing_n = Nursery(
                name=n_name,
                address=n_addr or raw_loc,
                zip_code=n_zip,
                city=n_city,
                latitude=lat,
                longitude=lon,
                urgency_color=urgency
            )
            session.add(existing_n)
            
        # Job
        job = Job(
            reference=str(row.get('Référence', '')),
            title=title,
            nursery_name=n_name,
            metier_id=m.id,
            contract_type=str(row.get('Type de contrat', 'CDI')),
            status='Open'
        )
        session.add(job)
        jobs_count += 1
        
    session.commit()
    print(f"Ingested {jobs_count} jobs.")

if __name__ == "__main__":
    if os.path.exists('grandir.db'):
        os.remove('grandir.db')
        print("Wiped old DB.")
    run_ingestion()
