import pandas as pd
import os

def clean_data():
    candidates_file = 'candidates.csv'
    jobs_file = 'jobs.csv'
    
    print("--- Cleaning Candidates Data ---")
    try:
        df_c = pd.read_csv(candidates_file, low_memory=False)
        original_len = len(df_c)
        print(f"Original Count: {original_len}")
        
        # 1. Drop Duplicates
        df_c.drop_duplicates(inplace=True)
        print(f"After dropping duplicates: {len(df_c)}")
        
        # 2. Drop rows with no address (Code postal du candidat)
        df_c.dropna(subset=['Code postal du candidat'], inplace=True)
        print(f"After dropping missing addresses: {len(df_c)}")
        
        # 3. Drop PII and Specific Columns
        cols_to_drop = ['Prénom', 'Nom', 'Email', 'Numéro de téléphone', 'Tags']
        # Only drop if they exist
        cols_to_drop = [c for c in cols_to_drop if c in df_c.columns]
        if cols_to_drop:
            df_c.drop(columns=cols_to_drop, inplace=True)
            print(f"Dropped columns: {cols_to_drop}")
            
        # 4. Drop fully empty columns
        # axis=1 drops columns, how='all' drops if all values are NA
        cleaned_cols_before = len(df_c.columns)
        df_c.dropna(axis=1, how='all', inplace=True)
        cleaned_cols_after = len(df_c.columns)
        print(f"Dropped {cleaned_cols_before - cleaned_cols_after} fully empty columns.")
        
        # Save
        df_c.to_csv(candidates_file, index=False)
        print("candidates.csv updated.")
        
    except Exception as e:
        print(f"Error cleaning candidates: {e}")

    print("\n--- Cleaning Jobs Data ---")
    try:
        df_j = pd.read_csv(jobs_file, low_memory=False)
        original_len = len(df_j)
        print(f"Original Count: {original_len}")
        
        # 1. Drop Duplicates
        df_j.drop_duplicates(inplace=True)
        print(f"After dropping duplicates: {len(df_j)}")
        
        # 2. Drop fully empty columns
        cleaned_cols_before = len(df_j.columns)
        df_j.dropna(axis=1, how='all', inplace=True)
        cleaned_cols_after = len(df_j.columns)
        print(f"Dropped {cleaned_cols_before - cleaned_cols_after} fully empty columns.")
        
        # Save
        df_j.to_csv(jobs_file, index=False)
        print("jobs.csv updated.")
        
    except Exception as e:
        print(f"Error cleaning jobs: {e}")

if __name__ == "__main__":
    clean_data()
