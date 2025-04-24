from sqlalchemy.orm import Session
from passlib.context import CryptContext
from models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_user(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def create_user(db: Session, username: str, password: str,role:str = "user"):
    hashed_password = pwd_context.hash(password)
    db_user = User(username=username, hashed_password=hashed_password,role=role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)
def update_user_role(db: Session, username: str, new_role: str):
    user = db.query(User).filter(User.username == username).first()
    if user:
        user.role = new_role
        db.commit()
        db.refresh(user)
    return user