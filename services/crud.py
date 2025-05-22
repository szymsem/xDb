from sqlalchemy.orm import Session
from passlib.context import CryptContext
from models.user import User, CurrencyBalance

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


def get_user_balance(db: Session, user_id: int, currency: str ):
    return db.query(CurrencyBalance).filter(
        CurrencyBalance.user_id == user_id,
        CurrencyBalance.currency == currency
    ).first()


def create_user_balance(db: Session, user_id: int, currency: str, initial_amount: float = 0.0):
    balance = CurrencyBalance(
        user_id=user_id,
        currency=currency,
        amount=initial_amount
    )
    db.add(balance)
    db.commit()
    db.refresh(balance)
    return balance


def update_user_balance(db: Session, user_id: int, currency: str, amount_change: float):
    balance = get_user_balance(db, user_id, currency)
    if not balance:
        balance = create_user_balance(db, user_id, currency)

    balance.amount += amount_change
    db.commit()
    db.refresh(balance)
    return balance