
import sqlite3
import os
import google.generativeai as genai
import json
import time
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
# NOTE: Using process environment variable for API key. 
# Ensure GOOGLE_API_KEY is set in the environment where this runs.
if "GOOGLE_API_KEY" not in os.environ:
    # Fallback or error - for now assume it helps key not being found to fail fast
    print("WARNING: GOOGLE_API_KEY not found in environment.")

genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

DB_PATH = "grandir.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def extract_experience_and_skills(summary_text):
    """
    Uses Gemini to extract years of experience and a skills score/list from the summary.
    """
    if not summary_text:
        return 0, []

    model = genai.GenerativeModel("gemini-2.0-flash-exp")
    prompt = f"""
    Analyze the following professional summary for a candidate in the childcare industry (Crèche):
    "{summary_text}"

    Extract:
    1. Total years of relevant experience (as an integer). If less than 1 year or just stages, count as 0 or 1. If not specified, estimate conservatively.
    2. A list of key soft skills and hard skills (max 5).

    Return ONLY a JSON object:
    {{
        "years_of_experience": <int>,
        "skills": ["skill1", "skill2", ...]
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Clean up code blocks if present
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
        
        data = json.loads(text)
        return data.get("years_of_experience", 0), data.get("skills", [])
    except Exception as e:
        print(f"Error extracting with AI: {e}")
        return 0, []

def calculate_diploma_score(candidate_diplomas, role_category):
    """
    Calculates a score (0-100) based on diploma match.
    Logic:
    - CAT 1 requires specific diplomas (EJE, Auxiliaire de Puériculture, Infirmière, Psychomotricien).
    - CAT 2 requires CAP AEPE or similar.
    - If candidate has HIGHER qualification than required, full score.
    - If candidate matches, full score.
    - If partial/related, partial score.
    """
    # Simply flatten diploma list for checking
    diploma_str = " ".join([d['diploma_name'] for d in candidate_diplomas]).lower()
    
    # Define keywords
    cat1_keywords = ["educatrice de jeunes enfants", "eje", "auxiliaire de puériculture", "ap", "infirmière", "infirrnier", "psychomotricien", "puéricultrice"]
    cat2_keywords = ["cap", "aepe", "petite enfance", "bep", "bac pro assp", "titre professionnel"]
    
    has_cat1 = any(k in diploma_str for k in cat1_keywords)
    has_cat2 = any(k in diploma_str for k in cat2_keywords)

    if role_category == "CAT 1":
        if has_cat1: return 100
        if has_cat2: return 40 # Has some childcare qual but not the right one
        return 0
    elif role_category == "CAT 2":
        if has_cat1: return 100 # Overqualified is good
        if has_cat2: return 100
        return 20 # Maybe has experience but no diploma
    else: # CAT 3 or unspecified
        if has_cat1 or has_cat2: return 100
        return 50 # General entry level

def calculate_skills_score(skills, summary_text):
    """
    Heuristic scoring for skills quality.
    Realistically this would compare against job description, but we want a general candidate quality score here.
    """
    if not skills and not summary_text:
        return 50 # Neutral
    
    score = 70 # Base good score
    
    # Bonus for key terms
    good_keywords = ["patience", "douceur", "équipe", "motivation", "dynamique", "autonomie", "bienveillance"]
    text_blob = (summary_text + " " + " ".join(skills)).lower()
    
    matches = sum(1 for k in good_keywords if k in text_blob)
    score += (matches * 5)
    
    return min(100, score)

def update_scores():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Update Candidates with Experience/Skills if missing
    print("--- 1. Enriching Candidates ---")
    candidates = cursor.execute("SELECT candidate_id, ai_summary, years_of_experience FROM dim_candidates").fetchall()
    
    for cand in candidates:
        cid = cand['candidate_id']
        summary = cand['ai_summary']
        current_exp = cand['years_of_experience']
        
        # Only run AI if we haven't already (or simple check if null)
        if current_exp is None and summary:
            print(f"Enriching Candidate {cid}...")
            years, skills = extract_experience_and_skills(summary)
            cursor.execute("UPDATE dim_candidates SET years_of_experience = ?, extracted_skills = ? WHERE candidate_id = ?", 
                           (years, json.dumps(skills), cid))
            conn.commit()
            time.sleep(10) # 10 RPM limit = 6s+ delay. Using 10s to be safe.
    
    # 2. Calculate Application Scores
    print("\n--- 2. Calculating Match Scores ---")
    
    # Join necessary tables
    query = """
    SELECT 
        a.application_id,
        a.distance_km,
        c.candidate_id,
        c.years_of_experience,
        c.extracted_skills,
        c.ai_summary,
        p.role_id,
        r.required_diploma_category -- Assuming checking dim_roles via posting is mostly implicit or we look at job CAT
    FROM fact_applications a
    JOIN dim_candidates c ON a.candidate_id = c.candidate_id
    JOIN fact_postings p ON a.posting_id = p.posting_id
    LEFT JOIN dim_roles r ON p.role_id = r.role_id
    """
    
    apps = cursor.execute(query).fetchall()
    
    for app in apps:
        aid = app['application_id']
        
        # --- FACTOR 1: DISTANCE (30%) ---
        dist = app['distance_km'] if app['distance_km'] is not None else 50
        # Formula: 100 at 0km, 0 at 30km? Or gentler?
        # Let's say: 100 - (distance * 3). 10km = 70. 30km = 10.
        dist_score = max(0, 100 - (dist * 3))
        
        # --- FACTOR 2: EXPERIENCE (20%) ---
        exp = app['years_of_experience'] if app['years_of_experience'] is not None else 0
        # 1 year = 20pts, 5 years = 100pts
        exp_score = min(100, exp * 20)
        
        # --- FACTOR 3: DIPLOMA (30%) ---
        # Get candidate diplomas
        dips = cursor.execute("SELECT diploma_name FROM candidate_diplomas WHERE candidate_id = ?", (app['candidate_id'],)).fetchall()
        # Simplification: Assume most postings in this dataset are CAT 2 or mix. 
        # Ideally we read 'CAT' from posting context or role. 
        # For now, let's assume robust matching logic isn't fully in DB yet, so heuristic:
        # If posting role suggests "Auxiliaire" -> CAT 1. Else CAT 2.
        # But wait, looking at file listings, 'job_reference' helps.
        # Let's just use a general 'Quality of Qualification' score if specific CAT is missing.
        # Queries show 'required_diploma_category' in dim_roles.
        role_cat = app['required_diploma_category'] if app['required_diploma_category'] else "CAT 2" 
        dip_score = calculate_diploma_score(dips, role_cat)
        
        # --- FACTOR 4: SKILLS (20%) ---
        skills = json.loads(app['extracted_skills']) if app['extracted_skills'] else []
        skill_score = calculate_skills_score(skills, app['ai_summary'])
        
        # --- FINAL SCORE ---
        final_score = (0.30 * dist_score) + (0.30 * dip_score) + (0.20 * exp_score) + (0.20 * skill_score)
        
        # --- VARIANCE & SCALING ---
        # Round it, maybe add a tiny hash-based jitter if needed, but the inputs should be varied enough.
        final_score = round(final_score, 1)
        
        print(f"App {aid} (C{app['candidate_id']}): Dist={dist_score:.1f}, Exp={exp_score}, Dip={dip_score}, Skill={skill_score} -> FINAL={final_score}")
        
        cursor.execute("UPDATE fact_applications SET match_score = ? WHERE application_id = ?", (final_score, aid))
    
    conn.commit()
    conn.close()
    print("Done.")

if __name__ == "__main__":
    update_scores()
