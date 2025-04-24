# db.py
from sqlalchemy.orm import sessionmaker
from models.user import Base, engine, SessionLocal

def init_db():
    """Inicjalizuje bazę danych i tworzy tabele"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """
    Dependency to provide a database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

init_db()