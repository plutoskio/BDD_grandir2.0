from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Metier
import json

def update_diplomas():
    engine = create_engine('sqlite:///grandir.db')
    Session = sessionmaker(bind=engine)
    session = Session()

    # Manual Mapping based on CSV Analysis & Job Titles
    # Key: Substring or exact match for Metier Title
    # Value: Name of the CSV column containing the diploma requirement (or logic)
    
    # We will store the "Column Name" as the prerequisite for now, 
    # so the app knows which column to check for a candidate.
    
    mapping = {
        'Auxiliaire Petite Enfance': 'Diplôme pour Auxiliaire Petite Enfance',
        'Auxiliaire de Puériculture': 'Titulaire du diplôme Auxiliaire Puériculture',
        'Educateur de Jeunes Enfants': 'Titulaire du diplôme Educateur Jeune Enfant',
        'Directeur de Crèche': 'Diplôme pour Directeur de Crèche', # Broad match
        'Directeur de Crèche MICRO': 'Diplôme pour Directeur de Crèche-Micro', # Specific match first
        'Directeur de Crèche Adjoint': 'Diplôme pour Directeur de Crèche Adjoint',
        'Psychologue': 'Titulaire du diplôme Psychologue',
        'Infirmier': 'Titulaire du diplôme Infirmier',
        'Psychomotricien': 'Titulaire du diplôme Psychomotricien',
        'Référent Santé & Accueil Inclusif': 'Diplôme pour Référent Santé & Accueil Inclusif',
        'Référent Technique': 'Diplôme pour Référent Technique',
        'Médecin': "Titulaire d'un diplôme en Médecine"
    }

    metiers = session.query(Metier).all()
    count = 0
    
    print("Updating Metier Prerequisites...")
    
    for m in metiers:
        title = m.title
        req_col = None
        
        # Find best match (longest substring match to be specific)
        best_match_len = 0
        
        for key, col in mapping.items():
            if key.lower() in title.lower():
                if len(key) > best_match_len:
                    best_match_len = len(key)
                    req_col = col
        
        if req_col:
            # We store it as a JSON dict for flexibility
            # {"required_diploma_column": "Col Name"}
            m.prerequisites = json.dumps({"required_diploma_column": req_col}, ensure_ascii=False)
            count += 1
            print(f"Updated '{title}': {req_col}")
        else:
             # Default fallback or leave empty
             # Some jobs like 'Cuisinier' or 'Agent de Service' might not have specific cols in this dataset
             print(f"Skipping '{title}': No mapping found.")

    session.commit()
    print(f"\nUpdated {count} Metiers.")

if __name__ == "__main__":
    update_diplomas()
