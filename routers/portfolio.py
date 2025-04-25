
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from binance_service import get_binance_supported_currencies
from crud import update_user_balance
from models.user import Portfolio, PortfolioAsset, User, CurrencyBalance, Account
from db import get_db
from auth import get_current_user

router = APIRouter()
router = APIRouter()

@router.post("/portfolios/")
def create_portfolio(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_portfolio = Portfolio(name=name, user_id=current_user.id)
    db.add(db_portfolio)
    db.commit()
    db.refresh(db_portfolio)
    return db_portfolio


@router.get("/portfolios/", response_model=List[dict])
def get_portfolios(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    return [{"id": p.id, "name": p.name} for p in portfolios]


@router.post("/portfolios/{portfolio_id}/buy")
def buy_asset(
        portfolio_id: int,
        symbol: str,
        currency_type: str,
        amount: float,
        price: float,
        payment_currency: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Kupuje asset płacąc w określonej walucie"""
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    total_cost = amount * price

    payment_balance = db.query(CurrencyBalance).filter(
        CurrencyBalance.user_id == current_user.id,
        CurrencyBalance.currency == payment_currency
    ).first()

    if not payment_balance or payment_balance.amount < total_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds in {payment_currency}"
        )

    asset = db.query(PortfolioAsset).filter(
        PortfolioAsset.portfolio_id == portfolio_id,
        PortfolioAsset.symbol == symbol,
        PortfolioAsset.currency_type == currency_type
    ).first()

    if asset:
        new_amount = asset.amount + amount
        new_avg_price = ((asset.amount * asset.buy_price) + (amount * price)) / new_amount
        asset.amount = new_amount
        asset.buy_price = new_avg_price
    else:
        asset = PortfolioAsset(
            portfolio_id=portfolio_id,
            symbol=symbol,
            currency_type=currency_type,
            amount=amount,
            buy_price=price,
            buy_currency=payment_currency
        )
        db.add(asset)

    payment_balance.amount -= total_cost
    db.commit()

    return {
        "message": "Asset purchased successfully",
        "new_balance": payment_balance.amount,
        "currency": payment_currency
    }
@router.post("/portfolios/{portfolio_id}/sell")
def sell_asset(
    portfolio_id: int,
    symbol: str,
    currency_type: str,
    amount: float,
    price: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # sprawdza czy portfolio nalezy do uzytkownika
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # znajduje asset
    asset = db.query(PortfolioAsset).filter(
        PortfolioAsset.portfolio_id == portfolio_id,
        PortfolioAsset.symbol == symbol
    ).first()

    if not asset or asset.amount < amount:
        raise HTTPException(status_code=400, detail="Insufficient assets")

    # oblicza zysk i aktualizuje balans
    profit = amount * price
    current_user.balance += profit

    # aktualizuje assety
    asset.amount -= amount
    if asset.amount <= 0:
        db.delete(asset)

    db.commit()
    return {"message": "Asset sold successfully"}


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


@router.post("/accounts/create")
def create_account(
        currency: str,
        initial_balance: float = 0.0,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # pobiera waluty i je normalizuje (duze litery)
    supported_currencies = [c.upper() for c in get_binance_supported_currencies()]
    requested_currency = currency.upper()

    if requested_currency not in supported_currencies:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported currency",
                "requested_currency": requested_currency,
                "supported_currencies": supported_currencies
            }
        )

    # sprawdza czy konto w podanej walucie juz istnieje
    existing_account = db.query(Account).filter(
        Account.user_id == current_user.id,
        Account.currency == currency
    ).first()

    if existing_account:
        raise HTTPException(status_code=400, detail="Account in this currency already exists")

    new_account = Account(
        user_id=current_user.id,
        currency=currency,
        balance=initial_balance
    )
    db.add(new_account)
    db.commit()
    db.refresh(new_account)

    return {
        "message": "Account created successfully",
        "account_id": new_account.id,
        "currency": new_account.currency,
        "balance": new_account.balance
    }


@router.get("/accounts")
def get_user_accounts(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Zwraca listę wszystkich kont użytkownika"""
    accounts = db.query(Account).filter(Account.user_id == current_user.id).all()

    return {
        "accounts": [{
            "id": acc.id,
            "currency": acc.currency,
            "balance": acc.balance,
            "created_at": acc.created_at.isoformat() if acc.created_at else None
        } for acc in accounts],
        "total_balance": sum(acc.balance for acc in accounts)
    }

@router.post("/balances/deposit")
def deposit_funds(
        currency: str,
        amount: float,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Wpłaca środki w określonej walucie"""
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    balance = update_user_balance(db, current_user.id, currency, amount)
    return {
        "message": "Funds deposited successfully",
        "currency": currency,
        "new_balance": balance.amount
    }


@router.post("/balances/withdraw")
def withdraw_funds(
        currency: str,
        amount: float,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Wypłaca środki z określonej waluty"""
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    balance = get_user_balance(db, current_user.id, currency)
    if not balance or balance.amount < amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    balance = update_user_balance(db, current_user.id, currency, -amount)
    return {
        "message": "Funds withdrawn successfully",
        "currency": currency,
        "new_balance": balance.amount
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


@router.post("/balances/transfer")
def transfer_between_currencies(
        source_currency: str,
        target_currency: str,
        amount: float,
        exchange_rate: float,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Transferuje środki między walutami"""

    source_balance = db.query(CurrencyBalance).filter(
        CurrencyBalance.user_id == current_user.id,
        CurrencyBalance.currency == source_currency
    ).first()

    if not source_balance or source_balance.amount < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds in {source_currency}"
        )

    # znajduje lub tworzy docelowy balans
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

    # transfer
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
@router.get("/user/balance")
def get_user_balance(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"balance": current_user.balance}