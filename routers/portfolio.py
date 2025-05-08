import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from binance_service import get_binance_supported_currencies
from crud import update_user_balance
from models.user import Portfolio, PortfolioAsset, User, CurrencyBalance, Order, OrderType, OrderStatus
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


@router.post("/orders/create")
async def create_order(
        portfolio_id: int,
        symbol: str,
        order_type: OrderType,
        amount: float,
        price: float = None,  # None dla zleceń rynkowych
        currency: str = "USD",
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Tworzy nowe zlecenie kupna/sprzedaży"""
    # Walidacja portfela
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Walidacja waluty
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

    # Tworzenie zlecenia
    new_order = Order(
        user_id=current_user.id,
        portfolio_id=portfolio_id,
        symbol=symbol,
        order_type=order_type,
        amount=amount,
        price=price,
        currency=currency,
        status=OrderStatus.PENDING
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)


    return {
        "message": "Order created successfully",
        "order_id": new_order.id,
        "status": new_order.status.value
    }


@router.put("/orders/{order_id}/modify")
async def modify_order(
        order_id: int,
        new_amount: float = None,
        new_price: float = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Modyfikuje istniejące zlecenie (tylko dla zleceń w statusie PENDING).
    Można zmienić ilość (amount) i/lub cenę (price).
    """
    # Pobierz zlecenie
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Only PENDING orders can be modified"
        )

    # Walidacja nowych wartości
    if new_amount is not None and new_amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Amount must be positive"
        )

    if new_price is not None and new_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Price must be positive"
        )

    # Aktualizacja zlecenia
    try:
        if new_amount is not None:
            order.amount = new_amount

        if new_price is not None:
            order.price = new_price

        db.commit()
        db.refresh(order)

        return {
            "message": "Order modified successfully",
            "order_id": order.id,
            "new_amount": order.amount,
            "new_price": order.price,
            "status": order.status.value
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to modify order: {str(e)}"
        )


@router.put("/orders/{order_id}/cancel")
async def cancel_order(
        order_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Anuluje zlecenie (tylko dla zleceń w statusie PENDING).
    """
    # Pobierz zlecenie
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Only PENDING orders can be cancelled"
        )

    try:
        order.status = OrderStatus.CANCELLED
        order.executed_at = datetime.utcnow()
        db.commit()

        return {
            "message": "Order cancelled successfully",
            "order_id": order.id,
            "status": order.status.value
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel order: {str(e)}"
        )

"""
async def execute_order(order_id: int, db: Session):
    from sqlalchemy.orm import sessionmaker
    from db import SessionLocal

    local_db = SessionLocal()
    try:
        order = local_db.query(Order).filter(Order.id == order_id).first()
        if not order or order.status != OrderStatus.PENDING:
            return

        if order.order_type == OrderType.BUY:
            # Logika kupna
            total_cost = order.amount * (order.price or await get_current_market_price(order.symbol))

            # Sprawdź saldo
            balance = local_db.query(CurrencyBalance).filter(
                CurrencyBalance.user_id == order.user_id,
                CurrencyBalance.currency == order.currency
            ).first()

            if not balance or balance.amount < total_cost:
                order.status = OrderStatus.FAILED
                order.executed_at = datetime.utcnow()
                local_db.commit()
                return

            # Realizacja kupna
            balance.amount -= total_cost
            asset = local_db.query(PortfolioAsset).filter(
                PortfolioAsset.portfolio_id == order.portfolio_id,
                PortfolioAsset.symbol == order.symbol
            ).first()

            if asset:
                new_amount = asset.amount + order.amount
                avg_price = ((asset.amount * asset.buy_price) + (order.amount * order.price)) / new_amount
                asset.amount = new_amount
                asset.buy_price = avg_price
            else:
                asset = PortfolioAsset(
                    portfolio_id=order.portfolio_id,
                    symbol=order.symbol,
                    currency_type=order.currency,
                    amount=order.amount,
                    buy_price=order.price,
                    buy_currency=order.currency
                )
                local_db.add(asset)

            order.status = OrderStatus.COMPLETED

        elif order.order_type == OrderType.SELL:
            # Logika sprzedaży
            asset = local_db.query(PortfolioAsset).filter(
                PortfolioAsset.portfolio_id == order.portfolio_id,
                PortfolioAsset.symbol == order.symbol
            ).first()

            if not asset or asset.amount < order.amount:
                order.status = OrderStatus.FAILED
                local_db.commit()
                return

            total_value = order.amount * (order.price or await get_current_market_price(order.symbol))

            # Znajdź lub utwórz balans w walucie docelowej
            balance = local_db.query(CurrencyBalance).filter(
                CurrencyBalance.user_id == order.user_id,
                CurrencyBalance.currency == order.currency
            ).first()

            if not balance:
                balance = CurrencyBalance(
                    user_id=order.user_id,
                    currency=order.currency,
                    amount=0.0
                )
                local_db.add(balance)

            # Realizacja sprzedaży
            asset.amount -= order.amount
            if asset.amount <= 0:
                local_db.delete(asset)

            balance.amount += total_value
            order.status = OrderStatus.COMPLETED

        order.executed_at = datetime.utcnow()
        local_db.commit()

    except Exception as e:
        print(f"Order execution failed: {e}")
        if order:
            order.status = OrderStatus.FAILED
            local_db.commit()
    finally:
        local_db.close()
"""


@router.post("/orders/{order_id}/execute")
async def execute_order(
        order_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Ręczne zatwierdzanie i wykonanie zlecenia"""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Only PENDING orders can be executed"
        )

    try:
        if order.order_type == OrderType.BUY:
            # Logika kupna
            current_price = await get_current_market_price(order.symbol)
            total_cost = order.amount * (order.price or current_price)

            # Sprawdź saldo
            balance = db.query(CurrencyBalance).filter(
                CurrencyBalance.user_id == order.user_id,
                CurrencyBalance.currency == order.currency
            ).first()

            if not balance or balance.amount < total_cost:
                order.status = OrderStatus.FAILED
                order.executed_at = datetime.utcnow()
                db.commit()
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient funds to execute this order"
                )

            # Realizacja kupna
            balance.amount -= total_cost
            asset = db.query(PortfolioAsset).filter(
                PortfolioAsset.portfolio_id == order.portfolio_id,
                PortfolioAsset.symbol == order.symbol
            ).first()

            if asset:
                new_amount = asset.amount + order.amount
                avg_price = ((asset.amount * asset.buy_price) + (
                            order.amount * (order.price or current_price))) / new_amount
                asset.amount = new_amount
                asset.buy_price = avg_price
            else:
                asset = PortfolioAsset(
                    portfolio_id=order.portfolio_id,
                    symbol=order.symbol,
                    currency_type="crypto",  # Załóżmy, że to krypto
                    amount=order.amount,
                    buy_price=order.price or current_price,
                    buy_currency=order.currency
                )
                db.add(asset)

            order.status = OrderStatus.COMPLETED

        elif order.order_type == OrderType.SELL:
            # Logika sprzedaży
            asset = db.query(PortfolioAsset).filter(
                PortfolioAsset.portfolio_id == order.portfolio_id,
                PortfolioAsset.symbol == order.symbol
            ).first()

            if not asset or asset.amount < order.amount:
                order.status = OrderStatus.FAILED
                db.commit()
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient assets to execute this order"
                )

            current_price = await get_current_market_price(order.symbol)
            total_value = order.amount * (order.price or current_price)

            # Znajdź lub utwórz balans w walucie docelowej
            balance = db.query(CurrencyBalance).filter(
                CurrencyBalance.user_id == order.user_id,
                CurrencyBalance.currency == order.currency
            ).first()

            if not balance:
                balance = CurrencyBalance(
                    user_id=order.user_id,
                    currency=order.currency,
                    amount=0.0
                )
                db.add(balance)

            # Realizacja sprzedaży
            asset.amount -= order.amount
            if asset.amount <= 0:
                db.delete(asset)

            balance.amount += total_value
            order.status = OrderStatus.COMPLETED

        order.executed_at = datetime.utcnow()
        db.commit()

        return {
            "message": "Order executed successfully",
            "order_id": order.id,
            "status": order.status.value,
            "executed_at": order.executed_at.isoformat()
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Order execution failed: {str(e)}"
        )

async def get_current_market_price(symbol: str):
    """Pobiera aktualną cenę rynkową z Binance"""
    from binance import AsyncClient
    client = await AsyncClient.create()
    try:
        ticker = await client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    finally:
        await client.close_connection()


@router.get("/orders")
def get_user_orders(
        status: OrderStatus = None,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Pobiera listę zleceń użytkownika"""
    query = db.query(Order).filter(Order.user_id == current_user.id)

    if status:
        query = query.filter(Order.status == status)

    orders = query.order_by(Order.created_at.desc()).all()

    return [{
        "id": o.id,
        "symbol": o.symbol,
        "type": o.order_type.value,
        "amount": o.amount,
        "price": o.price,
        "currency": o.currency,
        "status": o.status.value,
        "created_at": o.created_at.isoformat(),
        "executed_at": o.executed_at.isoformat() if o.executed_at else None
    } for o in orders]

