
import sqlite3
import os
import google.generativeai as genai
import json
import time
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
if "GOOGLE_API_KEY" not in os.environ:
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

def calculate_diploma_score(candidate_diplomas, required_category):
    diploma_str = " ".join([d['diploma_name'] for d in candidate_diplomas]).lower()
    
    if not required_category:
        return 5.0 
        
    req = required_category.upper().strip()
    
    has_eje = "educateur" in diploma_str or "eje" in diploma_str
    has_ap = "auxiliaire" in diploma_str or "puériculture" in diploma_str or "ap" in diploma_str
    has_cap = "cap" in diploma_str or "aepe" in diploma_str or "petite enfance" in diploma_str
    has_ide = "infirmier" in diploma_str or "infirmière" in diploma_str or "ide" in diploma_str
    
    # 0-10 Scale
    score = 0.0
    
    if req == "EJE":
        if has_eje: score = 10.0
        elif has_ap: score = 4.0
        elif has_cap: score = 2.0
        
    elif req == "AP":
        if has_ap: score = 10.0
        elif has_eje or has_ide: score = 10.0
        elif has_cap: score = 5.0
        
    elif req == "CAP" or req == "NONE":
        if has_cap or has_ap or has_eje: score = 10.0
        else: score = 3.0
        
    elif req == "IDE":
        if has_ide: score = 10.0
        else: score = 1.0
        
    elif req == "PSY":
        if "psy" in diploma_str: score = 10.0
        else: score = 1.0
        
    else:
        if has_cap or has_ap or has_eje: score = 8.0
        else: score = 2.0
        
    return score

def calculate_skills_score(skills, summary_text):
    """
    More variance:
    - Base 2.0
    - +1 for every 2 generic skills?
    - +2 for strong keywords
    """
    if not skills and not summary_text:
        return 2.0
    
    score = 2.0 # Low base
    
    summary_lower = str(summary_text).lower()
    
    # Core Childcare Keywords (High Value)
    core_keywords = ["douceur", "patience", "sécurité", "hygiène", "éveil", "bienveillance"]
    matches_core = sum(1 for k in core_keywords if k in summary_lower)
    score += (matches_core * 1.5)
    
    # Soft Skill Keywords (Medium Value)
    soft_keywords = ["équipe", "autonomie", "dynamique", "relationnel", "communication", "écoute"]
    matches_soft = sum(1 for k in soft_keywords if k in summary_lower)
    score += (matches_soft * 0.5)
    
    # Skills List Length Bonus
    if skills:
        score += min(3.0, len(skills) * 0.5)
        
    return min(10.0, score)

def update_scores():
    conn = get_db_connection()
    cursor = conn.cursor()

    print("--- 1. Enriching Candidates (AI) ---")
    candidates = cursor.execute("SELECT candidate_id, ai_summary, years_of_experience FROM dim_candidates").fetchall()
    
    for cand in candidates:
        cid = cand['candidate_id']
        current_exp = cand['years_of_experience']
        
        if current_exp is None and cand['ai_summary']:
            print(f"Enriching Candidate {cid}...")
            years, skills = extract_experience_and_skills(cand['ai_summary'])
            cursor.execute("UPDATE dim_candidates SET years_of_experience = ?, extracted_skills = ? WHERE candidate_id = ?", 
                           (years, json.dumps(skills), cid))
            conn.commit()
            time.sleep(6) 
    
    print("\n--- 2. Calculating Detailed Match Scores (0-10 Scale) ---")
    
    query = """
    SELECT 
        a.application_id,
        a.distance_km,
        c.candidate_id,
        c.years_of_experience,
        c.extracted_skills,
        c.ai_summary,
        p.role_id,
        r.required_diploma_category
    FROM fact_applications a
    JOIN dim_candidates c ON a.candidate_id = c.candidate_id
    JOIN fact_postings p ON a.posting_id = p.posting_id
    LEFT JOIN dim_roles r ON p.role_id = r.role_id
    """
    
    apps = cursor.execute(query).fetchall()
    
    for app in apps:
        aid = app['application_id']
        
        # 1. DISTANCE (0-10)
        dist = app['distance_km'] if app['distance_km'] is not None else 50.0
        # 0km = 10, 30km = 0
        score_dist = max(0.0, 10.0 - (dist * 0.33))
        
        # 2. EXPERIENCE (0-10)
        exp = app['years_of_experience'] if app['years_of_experience'] is not None else 0
        # 5 years = 10 pts. 1 year = 2 pts.
        score_exp = min(10.0, float(exp) * 2.0)
        
        # 3. DIPLOMA (0-10)
        dips = cursor.execute("SELECT diploma_name FROM candidate_diplomas WHERE candidate_id = ?", (app['candidate_id'],)).fetchall()
        role_cat = app['required_diploma_category']
        score_dip = calculate_diploma_score(dips, role_cat)
        
        # 4. SKILLS (0-10)
        skills = json.loads(app['extracted_skills']) if app['extracted_skills'] else []
        score_skills = calculate_skills_score(skills, app['ai_summary'])
        
        # FINAL WEIGHTED SCORE
        # Dist: 30%, Dip: 30%, Exp: 20%, Skill: 20%
        raw_score = (0.3 * score_dist) + (0.3 * score_dip) + (0.2 * score_exp) + (0.2 * score_skills)
        
        # --- PREREQUISITE PENALTY ---
        # If diploma requirement is definitely not met (score < 5), crush the score.
        final_score = raw_score
        if score_dip < 4.5:
             # Severe penalty for missing prerequisites
             # Cap at 2.9 OR apply heavy multiplier
             final_score = min(final_score * 0.3, 2.9)
        
        final_score = round(final_score, 1)
        
        print(f"App {aid}: D={score_dist:.1f} E={score_exp:.1f} Dip={score_dip:.1f} S={score_skills:.1f} -> Final={final_score}")
        
        cursor.execute("""
            UPDATE fact_applications 
            SET match_score = ?,
                score_distance = ?,
                score_experience = ?,
                score_diploma = ?,
                score_skills = ?
            WHERE application_id = ?
        """, (final_score, score_dist, score_exp, score_dip, score_skills, aid))
    
    conn.commit()
    conn.close()
    print("Scoring update complete.")

if __name__ == "__main__":
    update_scores()
