# user.py (rozszerzenie)
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, create_engine, ForeignKey, DateTime, UniqueConstraint, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from enum import Enum as PyEnum

DATABASE_URL = "sqlite:///./users.db"

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    email = Column(String, unique=True, index=True)
    role = Column(String, default="user")
    portfolios = relationship("Portfolio", back_populates="owner")
    currency_balances = relationship("CurrencyBalance", back_populates="user")
    accounts = relationship("Account", back_populates="user")
    orders = relationship("Order", back_populates="user")

class CurrencyBalance(Base):
    __tablename__ = "currency_balances"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    currency = Column(String, index=True)
    amount = Column(Float, default=0.0)
    user = relationship("User", back_populates="currency_balances")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    currency = Column(String, index=True)  # USD, EUR, PLN, BTC itp.
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="accounts")

    __table_args__ = (
        UniqueConstraint('user_id', 'currency', name='_user_currency_uc'),
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="portfolios")
    assets = relationship("PortfolioAsset", back_populates="portfolio")


class PortfolioAsset(Base):
    __tablename__ = "portfolio_assets"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    symbol = Column(String, index=True)  # np. "BTC", "ETH", "USD"
    currency_type = Column(String, index=True)  # "crypto", "fiat", "stock"
    amount = Column(Float)
    buy_price = Column(Float)
    buy_currency = Column(String)  # W jakiej walucie był zakup (np. "USD")
    portfolio = relationship("Portfolio", back_populates="assets")


class OrderType(PyEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(PyEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    symbol = Column(String)
    order_type = Column(Enum(OrderType))
    amount = Column(Float)
    price = Column(Float)  # Cena zlecenia (może być None dla zleceń rynkowych)
    currency = Column(String)  # Waluta płatności
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)

    user = relationship("User", back_populates="orders")
    portfolio = relationship("Portfolio")


# Tworzenie tabel w bazie danych
Base.metadata.create_all(bind=engine)