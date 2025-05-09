import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker
from typing import List

from binance_service import get_binance_supported_currencies
from crud import update_user_balance
from models.user import Portfolio, PortfolioAsset, User, CurrencyBalance, Order, OrderType, OrderStatus, SessionLocal
from db import get_db
from auth import get_current_user

router = APIRouter()

@router.post("/portfolios/")
def create_portfolio(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Tworzy portfel dla uzytkownika"""
    db_portfolio = Portfolio(name=name, user_id=current_user.id)
    db.add(db_portfolio)
    db.commit()
    db.refresh(db_portfolio)
    return db_portfolio


@router.get("/portfolios/", response_model=List[dict])
def get_portfolios(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Wyswietla portfele uzytkownika"""
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    return [{"id": p.id, "name": p.name} for p in portfolios]


@router.get("/portfolios/{portfolio_id}")
def get_portfolio_details(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    assets = db.query(PortfolioAsset).filter(
        PortfolioAsset.portfolio_id == portfolio_id
    ).all()

    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "assets": [{
            "symbol": a.symbol,
            "currency_type": a.currency_type,
            "amount": a.amount,
            "buy_price": a.buy_price,
            "buy_currency": a.buy_currency
        } for a in assets]
    }


@router.get("/portfolio/currencies")
async def get_supported_currencies():
    """Zwraca listę walut wspieranych przez Binance"""
    try:
        currencies = get_binance_supported_currencies()
        return currencies
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch currencies from Binance: {str(e)}"
        )


@router.get("/portfolio/{portfolio_id}/value")
def get_portfolio_value(
        portfolio_id: int,
        target_currency: str = "USD",
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):

    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    assets = db.query(PortfolioAsset).filter(
        PortfolioAsset.portfolio_id == portfolio_id
    ).all()

    total_value = sum(
        asset.amount * asset.buy_price
        for asset in assets
    )

    return {
        "portfolio_id": portfolio_id,
        "total_value": total_value,
        "currency": target_currency,
        "assets_count": len(assets)
    }


@router.get("/balances")
def get_all_balances(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Pobiera wszystkie balanse użytkownika"""
    balances = db.query(CurrencyBalance).filter(
        CurrencyBalance.user_id == current_user.id
    ).all()

    return [{
        "currency": balance.currency,
        "amount": balance.amount
    } for balance in balances]



@router.post("/balances/deposit")
async def deposit_funds(
        currency: str,
        amount: float,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Wpłaca środki w określonej walucie z walidacją"""
    currencies = get_binance_supported_currencies()
    if currency not in currencies:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported currency",
                "supported_currencies": currencies,
                "received_currency": currency
            }
        )

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    balance = update_user_balance(db, current_user.id, currency, amount)
    return {
        "message": "Funds deposited successfully",
        "currency": currency,
        "new_balance": balance.amount
    }


@router.post("/balances/transfer")
async def transfer_between_currencies(
        source_currency: str,
        target_currency: str,
        amount: float,
        exchange_rate: float,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Transferuje środki między walutami z walidacją"""
    currencies = get_binance_supported_currencies()

    # Walidacja obu walut
    for currency in [source_currency, target_currency]:
        if currency.upper() not in currencies:
            raise HTTPException(
                status_code=400,
                detail=f"Currency {currency} not supported. Valid currencies: {currencies}"
            )

    source_balance = db.query(CurrencyBalance).filter(
        CurrencyBalance.user_id == current_user.id,
        CurrencyBalance.currency == source_currency
    ).first()

    if not source_balance or source_balance.amount < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds in {source_currency}"
        )

    target_balance = db.query(CurrencyBalance).filter(
        CurrencyBalance.user_id == current_user.id,
        CurrencyBalance.currency == target_currency
    ).first()

    if not target_balance:
        target_balance = CurrencyBalance(
            user_id=current_user.id,
            currency=target_currency,
            amount=0.0
        )
        db.add(target_balance)

    try:
        source_balance.amount -= amount
        target_balance.amount += amount * exchange_rate
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Transfer failed: {str(e)}"
        )

    return {
        "message": "Transfer completed successfully",
        "source_currency": source_currency,
        "source_new_balance": source_balance.amount,
        "target_currency": target_currency,
        "target_new_balance": target_balance.amount,
        "exchange_rate": exchange_rate
    }

