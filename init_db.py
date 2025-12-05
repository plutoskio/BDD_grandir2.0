from sqlalchemy import create_engine, Column, Integer, String, Float, Date, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import os

Base = declarative_base()

class Metier(Base):
    __tablename__ = 'metiers'
    
    id = Column(Integer, primary_key=True)
    title = Column(String, unique=True, nullable=False)
    category = Column(String) # CAT 1, CAT 2 etc.
    prerequisites = Column(Text) # JSON or Text description of diplomas

    jobs = relationship("Job", back_populates="metier")

class Nursery(Base):
    __tablename__ = 'nurseries'
    
    name = Column(String, primary_key=True)
    address = Column(String)
    zip_code = Column(String)
    city = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    urgency_color = Column(String) # Derived from jobs? Or property of nursery context? Storing here for now.

    jobs = relationship("Job", back_populates="nursery")

class Job(Base):
    __tablename__ = 'jobs'
    
    reference = Column(String, primary_key=True) # Référence
    title = Column(String)
    metier_id = Column(Integer, ForeignKey('metiers.id'))
    nursery_name = Column(String, ForeignKey('nurseries.name'))
    contract_type = Column(String)
    date_created = Column(Date)
    status = Column(String)
    
    metier = relationship("Metier", back_populates="jobs")
    nursery = relationship("Nursery", back_populates="jobs")
    applications = relationship("Application", back_populates="job")

class Candidate(Base):
    __tablename__ = 'candidates'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String)
    phone = Column(String)
    city = Column(String)
    zip_code = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    current_diploma = Column(String)
    experience_years = Column(String)
    
    # New AI/CV Fields
    cv_text = Column(Text)
    diploma_ai = Column(String) # Extracted Diploma
    experience_ai = Column(String) # Extracted Years of Experience
    closeness_score = Column(Integer) # 0-100 Score
    qualitative_analysis = Column(Text) # LLM Explanation
    
    applications = relationship("Application", back_populates="candidate")

class Application(Base):
    __tablename__ = 'applications'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey('candidates.id'))
    job_reference = Column(String, ForeignKey('jobs.reference'))
    status = Column(String) # Statut
    step = Column(String) # Etape
    date_applied = Column(String)
    source = Column(String)
    
    candidate = relationship("Candidate", back_populates="applications")
    job = relationship("Job", back_populates="applications")

def init_db(db_name='grandir.db'):
    if os.path.exists(db_name):
        print(f"Database {db_name} already exists.")
        return
        
    engine = create_engine(f'sqlite:///{db_name}')
    Base.metadata.create_all(engine)
    print(f"Database {db_name} initialized with schema.")

if __name__ == "__main__":
    init_db()
