import pandas as pd
from sqlalchemy import create_engine
from init_db import Candidate

DB_URL = 'sqlite:///grandir.db'

def verify():
    try:
        engine = create_engine(DB_URL)
        df = pd.read_sql("SELECT first_name, last_name, diplomas_json, normalized_diplomas, normalized_diploma FROM candidates", engine)
        
        print(f"Total Candidates: {len(df)}")
        print("\n--- Sample Candidates with Multiple Diplomas ---")
        
        # Filter for non-empty lists
        df['norm_len'] = df['normalized_diplomas'].apply(lambda x: len(x) if x else 0)
        
        subset = df.sample(10) if len(df) > 10 else df
        for _, row in subset.iterrows():
            print(f"Name: {row['first_name']} {row['last_name']}")
            print(f"  Raw JSON: {row['diplomas_json']}")
            print(f"  Norm List: {row['normalized_diplomas']}")
            print(f"  Single (Legacy): {row['normalized_diploma']}")
            print("-" * 30)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify()
