from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from init_db import Metier, Nursery, Job, Candidate, Application

def verify():
    engine = create_engine('sqlite:///grandir.db')
    Session = sessionmaker(bind=engine)
    session = Session()
    
    num_metiers = session.query(Metier).count()
    num_nurseries = session.query(Nursery).count()
    num_jobs = session.query(Job).count()
    num_candidates = session.query(Candidate).count()
    num_applications = session.query(Application).count()
    
    print(f"Metiers: {num_metiers}")
    print(f"Nurseries: {num_nurseries}")
    print(f"Jobs: {num_jobs}")
    print(f"Candidates: {num_candidates}")
    print(f"Applications: {num_applications}")
    
    print("\n--- Top 5 Metiers ---")
    for m in session.query(Metier).limit(5):
        print(f"ID: {m.id}, Title: {m.title}, Cat: {m.category}")

if __name__ == "__main__":
    verify()
