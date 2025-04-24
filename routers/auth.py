
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from models.user import SessionLocal, CurrencyBalance, User
from db import get_db
from crud import get_user, create_user, verify_password, update_user_role, create_user_balance, pwd_context
from auth import create_access_token,get_current_user, require_role

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")



@router.post("/register")
def register(username: str, password: str, db: Session = Depends(get_db)):
    if get_user(db, username):
        raise HTTPException(status_code=400, detail="Username already registered")
    user = User(
        username=username,
        hashed_password=pwd_context.hash(password),
        role="user"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(CurrencyBalance(
        user_id=user.id,
        currency="USD",
        amount=1000.00  # balans startowy ( tylko na potrzeby testow)
    ))
    db.add(CurrencyBalance(
        user_id=user.id,
        currency="EUR",
        amount=0.00
    ))
    db.commit()

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = get_user(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}
@router.get("/admin")
def admin_endpoint(user = Depends(require_role("admin"))):
    """
    Endpoint dostępny tylko dla administratorów.
    """
    return {"message": "Welcome, admin!"}

@router.get("/user")
def user_endpoint(user = Depends(require_role("user"))):
    """
    Endpoint dostępny tylko dla zwykłych użytkowników.
    """
    return {"message": f"Welcome, {user.username}!"}
@router.put("/user/{username}/role")

def change_user_role(
    username: str, new_role: str, db: Session = Depends(get_db), admin=Depends(require_role("admin"))
):
    """
    Endpoint do zmiany rangi użytkownika. Dostępny tylko dla administratorów.
    """
    user = get_user(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_user_role(db, username, new_role)
    return {"message": f"Role of user {username} has been updated to {new_role}"}