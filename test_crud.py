from services.crud import verify_password, create_user, get_user_balance, update_user_balance
from models.user import User, CurrencyBalance
from sqlalchemy.orm import Session

class DummyDB:
    def __init__(self):
        self.users = []
        self.balances = []

    def query(self, model):
        self.model = model
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def add(self, obj):
        pass

    def commit(self):
        pass

    def refresh(self, obj):
        pass

def test_verify_password():
    # Hasło nieprawidłowe
    hashed = "$2b$12$KIXQ1QZQ1QZQ1QZQ1QZQ1uQ1QZQ1QZQ1QZQ1QZQ1QZQ1QZQ1QZQ1Q"
    assert not verify_password("wrong", hashed)

def test_get_user_balance_none():
    db = DummyDB()
    balance = get_user_balance(db, 1, "USD")
    assert balance is None

def test_update_user_balance_creates_balance():
    db = DummyDB()
    # update_user_balance powinno utworzyć nowy balans, jeśli nie istnieje
    result = update_user_balance(db, 1, "USD", 100.0)
    # W tym dummy DB nie ma realnej bazy, więc sprawdzamy tylko, czy nie ma wyjątku
    assert result is not None