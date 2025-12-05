from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Grandir Data Strategy & Target Data Model', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.set_fill_color(200, 220, 255)
        self.cell(0, 6, title, 0, 1, 'L', 1)
        self.ln(4)

    def chapter_body(self, body):
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 5, body)
        self.ln()

pdf = PDF()
pdf.add_page()

# 1. Introduction
pdf.chapter_title("1. The Reality: Why We Need a New Data Model")
pdf.chapter_body(
    "We have analyzed the current data landscape and confirmed what you suspected: it is messy. "
    "Data comes from disparate legacy systems, Excel exports are manually maintained, and critical fields like "
    "Diplomas and Locations are inconsistent. This 'Swiss Cheese' data quality prevents us from automating "
    "recruitment effectively.\n\n"
    "To build a robust 'Central Command', we must move from unstructured text to a structured Relational Data Model."
)

# 2. Target Data Model
pdf.chapter_title("2. Target Data Model: The Foundation")
pdf.chapter_body(
    "We propose a normalized SQL-based schema with four core entities. This structure ensures data integrity and enables advanced matching algorithms."
)

# Candidates Table
pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "A. Candidates Table (The Talent)", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "- candidate_id (PK): Unique Identifier (UUID)\n"
    "- full_name: Anonymized or Encrypted\n"
    "- email / phone: Contact details\n"
    "- zip_code: Validated 5-digit code (Critical for Geolocation)\n"
    "- diploma_category: ENUM ('CAT 1', 'CAT 2', 'Unqualified') - No more free text!\n"
    "- experience_years: Integer\n"
    "- source: ENUM ('Cooptation', 'Indeed', 'Internal')\n"
)
pdf.ln(2)

# Jobs Table
pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "B. Jobs Table (The Demand)", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "- job_id (PK): Unique Identifier\n"
    "- nursery_id (FK): Link to Nursery entity\n"
    "- title: Standardized Job Title\n"
    "- required_category: ENUM ('CAT 1', 'CAT 2')\n"
    "- urgency_level: ENUM ('Red', 'Orange', 'Green')\n"
    "- status: ENUM ('Open', 'Closed')\n"
)
pdf.ln(2)

# Nurseries Table
pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "C. Nurseries Table (The Locations)", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "- nursery_id (PK): Unique Identifier\n"
    "- name: Official Name\n"
    "- address: Full physical address\n"
    "- latitude / longitude: Precise GPS coordinates (Decimal)\n"
    "- capacity: Number of cribs (for future forecasting)\n"
)
pdf.ln(2)

# Applications Table
pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "D. Applications Table (The Funnel)", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "- application_id (PK): Unique Identifier\n"
    "- candidate_id (FK): Link to Candidate\n"
    "- job_id (FK): Link to Job\n"
    "- application_date: Timestamp\n"
    "- current_stage: ENUM ('New', 'Screening', 'Interview', 'Offer', 'Hired', 'Rejected')\n"
)
pdf.ln(5)

# 3. Data Acquisition Strategy
pdf.chapter_title("3. Data Acquisition: How to Fill the Gaps")
pdf.chapter_body(
    "Missing data is not a fatality. We can implement specific strategies to ensure our model is populated with high-quality data."
)

pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "Problem 1: Inconsistent Diplomas", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "Current State: Free text fields like 'CAP Petite Enfance (en cours)'.\n"
    "Solution: Implement a Dropdown Menu in the ATS application form. Candidates must select from a standardized list of state-recognized diplomas. This maps directly to our 'diploma_category' field."
)
pdf.ln(3)

pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "Problem 2: Missing Geolocation", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "Current State: Only Zip Codes, often invalid.\n"
    "Solution: Integrate a Geocoding API (Google Places or OpenStreetMap) at the point of entry. When a candidate types their address, it auto-completes and saves the precise Lat/Lon in the background."
)
pdf.ln(3)

pdf.set_font('Arial', 'B', 11)
pdf.cell(0, 5, "Problem 3: Stale Statuses", 0, 1)
pdf.set_font('Arial', '', 11)
pdf.multi_cell(0, 5, 
    "Current State: Manual Excel updates.\n"
    "Solution: Two-way sync between the 'Central Command' dashboard and the ATS. When a recruiter clicks 'Call' in the dashboard, the status automatically updates to 'Contacted'."
)

# Output
pdf.output("Data_Strategy/Grandir_Data_Strategy.pdf")
print("PDF Generated Successfully.")
