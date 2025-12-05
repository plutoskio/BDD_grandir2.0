import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import textwrap

# --- Configuration ---
OUTPUT_FILE = 'Grandir_Data_Quality_Report.pdf'
CANDIDATES_FILE = 'liste-des-candidatures_anonymized.xls'
JOBS_FILE = 'liste-des-postes_anonymized.xls'

# --- Load Data ---
print("Loading data...")
try:
    df_c = pd.read_excel(CANDIDATES_FILE)
    df_j = pd.read_excel(JOBS_FILE)
except FileNotFoundError:
    df_c = pd.read_csv('Liste des candidatures.csv')
    df_j = pd.read_csv('Liste des annonces.csv')

print(f"Loaded {len(df_c)} candidates and {len(df_j)} jobs.")

# --- Helper for Text Page ---
def create_text_page(pdf, title, text_lines):
    plt.figure(figsize=(11.69, 8.27)) # A4 Landscape
    plt.axis('off')
    
    plt.text(0.5, 0.9, title, ha='center', va='top', fontsize=24, weight='bold', color='#2c3e50')
    
    y = 0.8
    for line in text_lines:
        wrapped = textwrap.fill(line, width=90)
        plt.text(0.1, y, wrapped, ha='left', va='top', fontsize=12, family='monospace')
        y -= 0.05 * (wrapped.count('\n') + 1)
        
    pdf.savefig()
    plt.close()

# --- Generate Report ---
print("Generating PDF Report...")

with PdfPages(OUTPUT_FILE) as pdf:
    
    # 1. Executive Summary
    summary_text = [
        "Objective: Analyze data quality and availability to determine feasibility of the 'Grandir Central Command'.",
        "",
        f"Total Candidates: {len(df_c)}",
        f"Total Jobs: {len(df_j)}",
        "",
        "Key Findings:",
        "- Data Completeness: Significant gaps in 'Diplôme' and Contact Info.",
        "- Data Consistency: 'Diplôme' field contains free-text with high variability.",
        "- Geolocation: Zip codes are the primary location key; validity needs checking.",
        "- Process: High volume of candidates in early stages ('Présélection')."
    ]
    create_text_page(pdf, "Grandir Data Quality: Executive Summary", summary_text)
    
    # 2. Missing Data Heatmap (Candidates)
    plt.figure(figsize=(12, 8))
    sns.heatmap(df_c.isnull(), cbar=False, yticklabels=False, cmap='viridis')
    plt.title("The Swiss Cheese: Missing Data Heatmap (Candidates)", fontsize=16)
    plt.xlabel("Columns")
    plt.ylabel("Rows (Candidates)")
    plt.tight_layout()
    pdf.savefig()
    plt.close()
    
    # 3. The Diploma Jungle
    plt.figure(figsize=(12, 8))
    top_diplomas = df_c['Diplôme'].value_counts().head(20)
    sns.barplot(y=top_diplomas.index, x=top_diplomas.values, palette='viridis')
    plt.title("The Diploma Jungle: Top 20 Raw Diploma Variations", fontsize=16)
    plt.xlabel("Count")
    plt.tight_layout()
    pdf.savefig()
    plt.close()
    
    # 4. Status Funnel
    plt.figure(figsize=(12, 8))
    status_counts = df_c['Statut'].value_counts()
    sns.barplot(x=status_counts.index, y=status_counts.values, palette='magma')
    plt.title("The Leaky Bucket: Candidate Status Distribution", fontsize=16)
    plt.xticks(rotation=45, ha='right')
    plt.ylabel("Count")
    plt.tight_layout()
    pdf.savefig()
    plt.close()
    
    # 5. Urgency Distribution (Jobs)
    plt.figure(figsize=(10, 6))
    urgency_counts = df_j['Quelle est la couleur de la crèche ?'].value_counts()
    plt.pie(urgency_counts, labels=urgency_counts.index, autopct='%1.1f%%', colors=['red', 'orange', 'green'])
    plt.title("Supply Urgency: Job Color Distribution", fontsize=16)
    pdf.savefig()
    plt.close()
    
    # 6. Geolocation Validity
    # Check valid 5-digit zip codes
    valid_zips = df_c['Code postal du candidat'].astype(str).str.contains(r'^\d{5}$', na=False).sum()
    invalid_zips = len(df_c) - valid_zips
    
    plt.figure(figsize=(8, 6))
    plt.bar(['Valid Zip (5 digits)', 'Invalid/Missing'], [valid_zips, invalid_zips], color=['#27ae60', '#c0392b'])
    plt.title("Geolocation Readiness: Candidate Zip Code Validity", fontsize=16)
    plt.ylabel("Count")
    
    # Add text annotation
    plt.text(0, valid_zips/2, f"{valid_zips} ({valid_zips/len(df_c):.1%})", ha='center', color='white', weight='bold')
    plt.text(1, invalid_zips/2, f"{invalid_zips} ({invalid_zips/len(df_c):.1%})", ha='center', color='white', weight='bold')
    
    pdf.savefig()
    plt.close()

print(f"Report saved to {OUTPUT_FILE}")
