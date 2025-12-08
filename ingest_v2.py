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
# Configure Gemini
API_KEY = "AIzaSyCIOqxQau7Wsaqctzu4Qf4iADb1zUKbb8w"
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash-exp') # Updated model too
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
        if len(text.strip()) < 50: return None
        return text
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return None

def clean_phone(phone):
    if pd.isna(phone): return ""
    phone = str(phone)
    phone = re.sub(r'[\s\.\-\(\)]', '', phone)
    # normalize +33
    if phone.startswith('+33'): phone = '0' + phone[3:]
    return phone

def get_candidate_info_from_pdf_ai(pdf_path):
    """Fallback: Use Gemini to read scanned PDF and finding candidate identity."""
    if not model: return None, None, None, None, None
    
    try:
        # Upload file (or send parts)
        # Simplified: We can't easily upload file in this environment without 'genai.upload_file' 
        # but let's assume we can read bytes and generic 'document' processing.
        # Actually, let's try to extract text via a simple image-based approach if we can't upload?
        # No, 'gemini-1.5-flash' and '2.0-flash-exp' support PDF.
        # implementation:
        file_data = pdf_path.read_bytes()
        
        prompt = """
        This is a CV. Extract the candidate's identity in JSON:
        {"first_name": "...", "last_name": "...", "email": "...", "phone": "...", "city": "...", "zip_code": "..."}
        If you can't read it, return empty JSON.
        """
        
        # Retry Logic
        for attempt in range(3):
            try:
                response = model.generate_content([
                    {'mime_type': 'application/pdf', 'data': file_data},
                    prompt
                ])
                break
            except Exception as e:
                if "429" in str(e) or "Resource exhausted" in str(e):
                    print(f"Rate Limit Hit. Sleeping 60s... (Attempt {attempt+1}/3)")
                    time.sleep(60)
                else:
                    raise e
        else:
             print(f"Failed to extract {pdf_path.name} after retries.")
             return None, None, None, None, None

        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
            
        data = json.loads(text)
        name_parts = str(data.get('first_name', '') + " " + data.get('last_name', '')).strip().split()
        first = data.get('first_name') or (name_parts[0] if name_parts else 'Unknown')
        last = data.get('last_name') or (" ".join(name_parts[1:]) if len(name_parts)>1 else 'Unknown')
        
        # Rate limit safety for subsequent calls
        time.sleep(2) 
        
        return data.get('email'), data.get('phone'), f"{first} {last}", data.get('zip_code'), data.get('city')
        
    except Exception as e:
        print(f"AI OCR Error for {pdf_path.name}: {e}")
        return None, None, None, None, None

def get_ai_data(cv_text, job_context="Recruitment"):
    if not model:
        return None
    
    prompt = f"""
    You are an expert recruiter. Analyze the following CV text.
    Extract the following information in JSON format:
    1. "diplomas_list": A list of ALL diplomas/certificates found (e.g. ["Bac Pro ASSP", "CAP Petite Enfance", "BAFA"]).
    2. "diploma_ai": The SINGLE highest diploma relevant for childcare (e.g. "DE EJE").
    3. "experience_ai": Total years of experience in childcare/health sector as a number or string (e.g. "5 years").
    4. "closeness_score": A score from 0 to 100 on how well this candidate fits a general childcare role.
    5. "qualitative_analysis": A 1-sentence explanation of the score.

    CV Text:
    {cv_text[:5000]}
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

# --- Normalization Logic ---
def normalize_diplomas(diploma_list):
    """
    Takes a list of strings (diplomas) and returns a list of Standardized Enums.
    """
    if not diploma_list: return []
    if isinstance(diploma_list, str): diploma_list = [diploma_list]
    
    normalized = set()
    
    for d in diploma_list:
        t = str(d).lower()
        
        # --- GROUP A: CAT 1 (High Qual) ---
        if any(x in t for x in ['infirmier', 'ide', 'nurse', 'scienc', 'soins infirmiers']): 
            normalized.add("DE_INFIRMIER")
        if any(x in t for x in ['puericultrice', 'puéricultrice']) and not 'auxiliaire' in t:
             normalized.add("DE_PUERICULTRICE")
        if any(x in t for x in ['eje', 'educateur jeunes enfants', 'éducatrice de jeunes enfants', 'deeje']):
             normalized.add("DE_EJE")
        if any(x in t for x in ['psycho']):
             normalized.add("PSYCHOLOGIE")
             
        # --- GROUP B: CAT 2 (Skilled) ---
        # AP / Auxiliaire check - stricter
        if 'auxiliaire' in t or 'deap' in t or 'pueri' in t:
             # Exclude Puericultrice (handled above) if it's just "Auxiliaire"
             normalized.add("DE_AUXILIAIRE_PUERICULTURE")
        elif ' ap' in t or t.startswith('ap ') or t == 'ap': # " AP" or "AP " or "AP"
             normalized.add("DE_AUXILIAIRE_PUERICULTURE")
        elif 'aide soignante' in t:
             normalized.add("OTHER_HEALTH")
             
        # CAP / AEPE
        if 'aepe' in t or 'petite enfance' in t or 'accompagnant éducatif' in t:
             normalized.add("CAP_AEPE")
        elif 'cap' in t: # "CAP" is short, check context if needed, but often "CAP ..."
             if "petite enfance" in t or "aepe" in t:
                 normalized.add("CAP_AEPE")
             # Else generic CAP? Ignoring for now to be safe
             
        # BAC ASSP
        if 'assp' in t:
             normalized.add("BAC_ASSP")
        elif ('bac' in t or 'baccalauréat' in t) and ('accompagnement' in t):
             normalized.add("BAC_ASSP")
             
        # BEP CSS
        if 'css' in t or 'sanitaires et sociales' in t:
             normalized.add("BEP_CSS")
             
        # --- GROUP C: Support ---
        if 'bafa' in t: normalized.add("BAFA")
        if 'advf' in t or 'vie aux familles' in t: normalized.add("TITRE_ADVF")
        if 'meef' in t or "sciences de l'education" in t: normalized.add("TEACHING")

    return list(normalized)

def normalize_diploma(text):
    # BACKWARD COMPATIBILITY WRAPPER
    res = normalize_diplomas([text])
    return res[0] if res else "UNKNOWN"

def get_required_diplomas(job_title):
    t = str(job_title).lower()
    # Logic defining strict requirements
    if 'infirmier' in t: return json.dumps(["DE_INFIRMIER"])
    if 'eje' in t or 'educateur' in t or 'directeur' in t: return json.dumps(["DE_EJE", "DE_INFIRMIER"]) # Directeurs can be either
    if 'auxiliaire' in t: return json.dumps(["DE_AUXILIAIRE"])
    return json.dumps([]) # No strict requirement or Unknown

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
    
    # Create Index: Email -> Row, Phone -> Row, "Name Surname" -> Row
    candidates_index = {}
    phone_index = {}
    
    print("Indexing Candidates...")
    for idx, row in df_c.iterrows():
        # Email
        email = str(row.get('Email', '')).strip().lower()
        if email and '@' in email:
            candidates_index[email] = row
            
        # Phone
        raw_phone = str(row.get('Téléphone', ''))
        c_phone = clean_phone(raw_phone)
        if len(c_phone) >= 9: # Valid length check
            phone_index[c_phone] = row
            
        # Name matching logic (Fallback)
        first = str(row.get('Prénom', '')).strip().lower()
        last = str(row.get('Nom', '')).strip().lower()
        full = f"{first} {last}"
        if len(full) > 2:
           candidates_index[full] = row
           candidates_index[f"{last} {first}"] = row

    # 3. Process CVs (and unify with CSV data)
    # Strategy: Iterate CSV rows (All Candidates) OR just CVs?
    # Requirement: "We keep only candidates with CVs".
    # So we stick to iterating PDF files. 
    # BUT, we need to populate Normalized Diploma even if AI fails?
    # Users said "We keep only candidates with CVs". So iterating PDF files is correct.
    
    print(f"Processing CVs in {CV_DIR}...")
    pdf_files = list(Path(CV_DIR).glob("*.pdf"))
    
    matched_count = 0
    nomi = pgeocode.Nominatim('fr')
    
    for pdf_path in pdf_files:
        content = extract_text_from_pdf(pdf_path)
        
        # OCR FALLBACK / AI Data Prep
        ai_identity = {} 
        is_scanned = False
        
        if not content:
             # Text extraction failed, try AI Vision/OCR approach
             is_scanned = True
             print(f"File {pdf_path.name} seems image-based. Attempting AI Extraction...")
             email, phone, name, zip_c, city = get_candidate_info_from_pdf_ai(pdf_path)
             if email or phone or name != 'Unknown Unknown':
                 content = f"OCR_RECOVERY Name: {name} Email: {email} Phone: {phone}" 
                 ai_identity = {'email': email, 'phone': phone, 'name': name, 'zip': zip_c, 'city': city}

        match_row = None
        
        # 1. Match from AI Identity (if scanned or forced)
        if ai_identity:
             if ai_identity.get('email') and ai_identity['email'].lower() in candidates_index:
                 match_row = candidates_index[ai_identity['email'].lower()]
        
        if match_row is None and content:
            # 2. Email Match (Regex)
            found_emails = re.findall(r'[\w\.-]+@[\w\.-]+', content)
            for e in found_emails:
                if e.lower() in candidates_index:
                    match_row = candidates_index[e.lower()]
                    break
        
        if match_row is None and content:
            # 3. Phone Match 
            found_nums = re.findall(r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}', content)
            if ai_identity.get('phone'): found_nums.append(ai_identity['phone'])
            
            for n in found_nums:
                cp = clean_phone(n)
                if cp in phone_index:
                    match_row = phone_index[cp]
                    break
                if len(cp) == 9 and ('0'+cp) in phone_index:
                    match_row = phone_index['0'+cp]
                    break
        
        # 4. Name Match
        if match_row is None and content:
             content_lower = content.lower()
             for _, row in df_c.iterrows():
                 p = str(row.get('Prénom', '')).strip().lower()
                 n = str(row.get('Nom', '')).strip().lower()
                 if len(p) < 2 or len(n) < 2: continue
                 if f"{p} {n}" in content_lower:
                     match_row = row
                     break
        
        if match_row is None and not ai_identity:
             # Try force extraction on non-scanned text if we failed to match
             if content:
                 print(f"Force-extracting identity for {pdf_path.name}...")
                 e, p, n, z, c = get_candidate_info_from_pdf_ai(pdf_path)
                 if e or p or n != 'Unknown Unknown':
                     ai_identity = {'email': e, 'phone': p, 'name': n, 'zip': z, 'city': c}

        # AI Analysis (Standard)
        ai_data = None
        if content and not is_scanned and model:
             # Regular extraction for Score/Diploma
             ai_data = get_ai_data(content)
        
        # --- CREATE CANDIDATE ---
        if match_row is not None:
            # CSV MATCHED
            matched_count += 1
            print(f"Match! {match_row['Prénom']} {match_row['Nom']}")
            
            lat, lon = None, None
            zip_code = match_row.get('Code postal', match_row.get('Code postal du candidat', ''))
            if pd.notna(zip_code):
                z = str(zip_code)[:5]
                loc = nomi.query_postal_code(z)
                if not pd.isna(loc.latitude): lat, lon = loc.latitude, loc.longitude

            # Prepare Diploma Data
            csv_dip = match_row.get('Diplôme', match_row.get('Diplôme du candidat', ''))
            ai_dip = ai_data.get('diploma_ai') if ai_data else None
            ai_dip_list = ai_data.get('diplomas_list', []) if ai_data else []
            
            # Normalize
            norm_list = normalize_diplomas(ai_dip_list)
            if not norm_list and csv_dip:
                 # Fallback to CSV diploma if AI found nothing or failed
                 norm_list = normalize_diplomas([csv_dip])
            
            # Legacy Single Norm (Keep for now)
            norm_single = normalize_diploma(ai_dip)
            if norm_single == "UNKNOWN": norm_single = normalize_diploma(csv_dip)
            
            cand = Candidate(
                first_name=match_row.get('Prénom', ''),
                last_name=match_row.get('Nom', ''),
                email=match_row.get('Email', ''),
                phone=str(match_row.get('Téléphone', '')),
                city=match_row.get('Ville', match_row.get('Ville du candidat', '')),
                zip_code=str(zip_code),
                latitude=lat, longitude=lon,
                current_diploma=str(csv_dip),
                experience_years=match_row.get("Années d'expérience", ''),
                cv_text=content[:5000] if content else "",
                diploma_ai=ai_dip,
                experience_ai=ai_data.get('experience_ai') if ai_data else None,
                closeness_score=ai_data.get('closeness_score') if ai_data else None,
                qualitative_analysis=ai_data.get('qualitative_analysis') if ai_data else None,
                normalized_diploma=norm_single,
                diplomas_json=json.dumps(ai_dip_list),
                normalized_diplomas=json.dumps(norm_list)
            )
            session.add(cand)
            
        elif ai_identity:
            # NO CSV MATCH -> "CV Only" Candidate
            matched_count += 1
            print(f"Created from CV Only: {ai_identity['name']}")
            
            lat, lon = None, None
            if ai_identity.get('zip'):
                 z = str(ai_identity['zip'])[:5]
                 loc = nomi.query_postal_code(z)
                 if not pd.isna(loc.latitude): lat, lon = loc.latitude, loc.longitude
            
            # Use data from generic extraction if available
            ai_dip = ai_data.get('diploma_ai') if ai_data else None
            ai_dip_list = ai_data.get('diplomas_list', []) if ai_data else []
            
            norm_single = normalize_diploma(ai_dip)
            norm_list = normalize_diplomas(ai_dip_list)
            
            raw_name = ai_identity.get('name', 'Unknown Unknown')
            parts = raw_name.split() if raw_name else ['Unknown']
            f_name = parts[0]
            l_name = " ".join(parts[1:]) if len(parts)>1 else ""
            
            cand = Candidate(
                first_name=f_name,
                last_name=l_name,
                email=ai_identity.get('email', ''),
                phone=ai_identity.get('phone', ''),
                city=ai_identity.get('city', ''),
                zip_code=ai_identity.get('zip', ''),
                latitude=lat, longitude=lon,
                current_diploma="CV Only",
                experience_years="Unknown",
                cv_text=content[:5000] if content else "AI Extracted",
                diploma_ai=ai_dip,
                experience_ai=ai_data.get('experience_ai') if ai_data else None,
                closeness_score=ai_data.get('closeness_score') if ai_data else None,
                qualitative_analysis=ai_data.get('qualitative_analysis') if ai_data else "Extracted from CV only.",
                normalized_diploma=norm_single,
                diplomas_json=json.dumps(ai_dip_list),
                normalized_diplomas=json.dumps(norm_list)
            )
            session.add(cand)
        else:
            print(f"Skipping {pdf_path.name} (Unreadable/Unmatched)")
            

        
    session.commit()
    print(f"Ingested {matched_count} candidates.")
    
    # 4. Load Jobs
    print("Loading Jobs...")
    df_j = pd.read_csv(JOBS_CSV, low_memory=False)
    
    def get_cat(title):
         t = str(title).lower()
         if 'auxiliaire' in t: return 'CAT 2'
         if 'infirmier' in t or 'eje' in t or 'educateur' in t or 'directeur' in t: return 'CAT 1'
         return 'Other'
        
    metiers_cache = {}
    jobs_count = 0
    
    for _, row in df_j.iterrows():
        title = row.get("Titre de l'annonce", row.get('Libellé du poste', row.get('Intitulé de poste', 'Unknown')))
        if pd.isna(title): continue
        
        if title not in metiers_cache:
            existing_m = session.query(Metier).filter_by(title=title).first()
            if not existing_m:
                existing_m = Metier(
                    title=title, 
                    category=get_cat(title),
                    required_diplomas=get_required_diplomas(title) # Define Requirements
                )
                session.add(existing_m)
                session.commit()
            metiers_cache[title] = existing_m
        else:
             m = metiers_cache[title]
        
        m = metiers_cache[title]
        
        # Nursery (Use cached lookup for speed if optimizing, but simple here)
        n_name = row.get('CRECHES', row.get('Etablissement', 'Unknown'))
        if pd.isna(n_name): n_name = "Unknown Nursery"
        
        # Geocode/Create Nursery (simplified loop check)
        existing_n = session.query(Nursery).get(n_name)
        if not existing_n:
             # ... (Nursery creation logic same as before, condensed)
             raw_loc = str(row.get('Localisation', ''))
             match = re.search(r'\b(\d{5})\b', raw_loc)
             z_code = match.group(1) if match else ""
             lat, lon = None, None
             if z_code:
                 l = nomi.query_postal_code(z_code)
                 if not pd.isna(l.latitude): lat, lon = l.latitude, l.longitude
             
             existing_n = Nursery(
                 name=n_name, 
                 address=raw_loc, 
                 zip_code=z_code, 
                 latitude=lat, 
                 longitude=lon,
                 urgency_color=row.get('Quelle est la couleur de la crèche ?', 'Rouge')
             )
             session.add(existing_n)
             
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
