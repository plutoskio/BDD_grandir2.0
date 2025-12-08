import os
import glob
import time
import json
import google.generativeai as genai
from pathlib import Path

# Config
# API_KEY will be passed via env var or hardcoded here for this one-off script
API_KEY = "AIzaSyCIOqxQau7Wsaqctzu4Qf4iADb1zUKbb8w"
CV_DIR = "export_cv (1)"
OUTPUT_FILE = "diploma_analysis.json"
RPM_DELAY = 4.5  # 15 RPM = 4s, adding buffer

def extract_diplomas():
    if not API_KEY:
        print("No API Key provided.")
        return

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash-exp')

    pdf_files = list(Path(CV_DIR).glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {CV_DIR}")
        return

    print(f"Found {len(pdf_files)} PDFs. Starting extraction...")
    
    results = []
    
    for i, pdf_path in enumerate(pdf_files):
        print(f"[{i+1}/{len(pdf_files)}] Processing {pdf_path.name}...")
        
        try:
            # Prepare file data
            file_data = pdf_path.read_bytes()
            
            prompt = """
            You are a rigorous data extraction assistant. 
            Analyze this CV and extract EVERY single diploma, degree, certificate, or qualification mentioned.
            Include everything from high school diplomas (Bac) to professional certifications (CAP, DE, Master, Licence, etc.).
            
            Return ONLY a valid JSON object in this format:
            {
                "diplomas": ["Diploma 1", "Diploma 2", ...]
            }
            If no diplomas are found, return {"diplomas": []}.
            Do not include Markdown formatting like ```json.
            """
            
            response = model.generate_content([
                {'mime_type': 'application/pdf', 'data': file_data},
                prompt
            ])
            
            text = response.text.strip()
            # Clean md blocks if present
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            if text.startswith("```"): # Sometimes just ```
                text = text[3:]
                
            try:
                data = json.loads(text)
                dips = data.get("diplomas", [])
                print(f"   -> Found {len(dips)} diplomas.")
                results.append({
                    "filename": pdf_path.name,
                    "diplomas": dips
                })
            except json.JSONDecodeError:
                print(f"   -> Failed to parse JSON: {text[:100]}...")
                results.append({
                    "filename": pdf_path.name,
                    "diplomas": [],
                    "error": "JSON Parse Error",
                    "raw_response": text
                })
                
        except Exception as e:
            print(f"   -> Error: {e}")
            results.append({
                "filename": pdf_path.name,
                "diplomas": [],
                "error": str(e)
            })
            
        # Rate Limit Sleep
        print(f"   Sleeping {RPM_DELAY}s...")
        time.sleep(RPM_DELAY)

    # Save Results
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved analysis to {OUTPUT_FILE}")
    
    # Summary
    all_dips = []
    for r in results:
        all_dips.extend(r.get("diplomas", []))
    
    unique_dips = sorted(list(set(all_dips)))
    print(f"Total Diplomas Extracted: {len(all_dips)}")
    print(f"Unique Diplomas: {len(unique_dips)}")
    
    with open("unique_diplomas_list.txt", "w", encoding='utf-8') as f:
        for d in unique_dips:
            f.write(d + "\n")
    print("Saved unique list to unique_diplomas_list.txt")

if __name__ == "__main__":
    extract_diplomas()
