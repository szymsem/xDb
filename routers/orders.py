import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker
from typing import List
from db import SessionLocal

from binance_service import get_binance_supported_currencies, get_current_market_price
from crud import update_user_balance
from models.user import Portfolio, PortfolioAsset, User, CurrencyBalance, Order, OrderType, OrderStatus, SessionLocal, \
    AdvancedOrderType, OrderFuture
from db import get_db
from auth import get_current_user

router = APIRouter()


@router.post("/orders/create_market_order")
async def create_order(
        portfolio_id: int,
        symbol: str,
        order_type: OrderType,
        amount: float,
        currency: str = "USDT",
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Tworzy nowe zlecenie kupna/sprzedaży z aktualną ceną z Binance"""
    # walidacja portfela
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # walidacja waluty
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

    # pobiera cene z binance
    try:
        current_price = await get_current_market_price(symbol)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch price for {symbol} from Binance: {str(e)}"
        )

    new_order = Order(
        user_id=current_user.id,
        portfolio_id=portfolio_id,
        symbol=symbol,
        order_type=order_type,
        amount=amount,
        price=current_price,
        currency=currency,
        status=OrderStatus.PENDING
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    asyncio.create_task(execute_market_order(new_order.id))

    return {
        "message": "Order created successfully (pending execution)",
        "order_id": new_order.id,
        "status": new_order.status.value,
        "symbol": symbol,
        "current_price": current_price,
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

    # aktualizacja zlecenia
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


async def execute_market_order(order_id: int):
    """Główna funkcja wykonująca zlecenie"""



    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order or order.status != OrderStatus.PENDING:
            return

        if order.order_type == OrderType.BUY:
            await execute_buy(order, db)
        elif order.order_type == OrderType.SELL:
            await execute_sell(order, db)

    except Exception as e:
        print(f"Order execution error: {str(e)}")
    finally:
        db.close()


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


async def execute_buy(order: Order, db: Session) -> None:
    """Realizuje zlecenie kupna"""
    try:
        current_price = await get_current_market_price(order.symbol)
        total_cost = order.amount * current_price

        balance = db.query(CurrencyBalance).filter(
            CurrencyBalance.user_id == order.user_id,
            CurrencyBalance.currency == order.currency
        ).first()

        if not balance or balance.amount < total_cost:
            order.status = OrderStatus.FAILED
            order.executed_at = datetime.utcnow()
            db.commit()
            raise ValueError("Insufficient funds")

        asset = db.query(PortfolioAsset).filter(
            PortfolioAsset.portfolio_id == order.portfolio_id,
            PortfolioAsset.symbol == order.symbol
        ).first()

        balance.amount -= total_cost

        if asset:
            new_amount = asset.amount + order.amount
            total_investment = (asset.amount * asset.buy_price) + (order.amount * current_price)
            asset.buy_price = total_investment / new_amount
            asset.amount = new_amount
        else:
            asset = PortfolioAsset(
                portfolio_id=order.portfolio_id,
                symbol=order.symbol,
                currency_type="crypto",
                amount=order.amount,
                buy_price=current_price,
                buy_currency=order.currency
            )
            db.add(asset)

        order.status = OrderStatus.COMPLETED
        order.executed_at = datetime.utcnow()
        order.price = current_price
        db.commit()

    except Exception as e:
        db.rollback()
        raise ValueError(f"Buy execution failed: {str(e)}")


async def execute_sell(order: Order, db: Session) -> None:
    """Realizuje zlecenie sprzedaży"""
    amount=(0-order.amount)
    try:
        current_price = await get_current_market_price(order.symbol)
        total_value = amount * current_price

        asset = db.query(PortfolioAsset).filter(
            PortfolioAsset.portfolio_id == order.portfolio_id,
            PortfolioAsset.symbol == order.symbol
        ).first()

        if not asset or asset.amount < order.amount:
            order.status = OrderStatus.FAILED
            db.commit()
            raise ValueError("Insufficient assets")

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

        asset.amount -= amount
        if asset.amount <= 0.000001:
            db.delete(asset)

        balance.amount += total_value

        order.status = OrderStatus.COMPLETED
        order.executed_at = datetime.utcnow()
        order.price = current_price
        db.commit()

    except Exception as e:
        db.rollback()
        raise ValueError(f"Sell execution failed: {str(e)}")


async def process_order(order, current_price, db: Session):
    """
    Obsługuje różne typy zleceń, zapisuje zmiany w bazie i usuwa zrealizowane zlecenia.

    Args:
        order: Obiekt zlecenia.
        current_price: Aktualna cena rynkowa.
        execute_buy: Funkcja realizacji kupna.
        execute_sell: Funkcja realizacji sprzedaży.
        db: Sesja bazy danych.
    """
    try:
        # Obsługa zleceń LIMIT
        if order.order_type == AdvancedOrderType.LIMIT:
            if order.price and current_price <= order.price and order.amount > 0:
                await execute_buy(order, db)
                db.delete(order)
                db.commit()
                return True
            elif order.price and current_price >= order.price and order.amount < 0:
                await execute_sell(order, db)
                db.delete(order)
                db.commit()
                return True

        # Obsługa zleceń STOP_LIMIT
        elif order.order_type == AdvancedOrderType.STOP_LIMIT:
            if order.stop_price and current_price >= order.stop_price:
                order.order_type = AdvancedOrderType.LIMIT
                db.commit()
                return process_order(order, current_price, db)

        # Obsługa zleceń STOP_MARKET
        elif order.order_type == AdvancedOrderType.STOP_MARKET:
            if order.stop_price and current_price >= order.stop_price:
                if order.amount > 0:
                    await execute_buy(order, db)
                elif order.amount < 0:
                    await execute_sell(order, db)
                db.delete(order)
                db.commit()
                return True

        # Obsługa zleceń TAKE_PROFIT_LIMIT
        elif order.order_type == AdvancedOrderType.TAKE_PROFIT_LIMIT:
            if order.stop_price and current_price >= order.stop_price:
                order.order_type = AdvancedOrderType.LIMIT
                db.commit()
                return process_order(order, current_price, db)

        # Obsługa zleceń TAKE_PROFIT_MARKET
        elif order.order_type == AdvancedOrderType.TAKE_PROFIT_MARKET:
            if order.stop_price and current_price >= order.stop_price:
                if order.amount > 0:
                    await execute_buy(order, db)
                elif order.amount < 0:
                    await execute_sell(order, db)
                db.delete(order)
                db.commit()
                return True

        return False

    except Exception as e:
        db.rollback()
        print(f"Error processing order {order.id}: {e}")
        return False


@router.post("/orders/create_advanced_order")
async def create_advanced_order(
        portfolio_id: int,
        symbol: str,
        order_type: AdvancedOrderType,
        amount: float,
        price: float = None,
        stop_price: float = None,
        currency: str = "USDT",
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Tworzy zaawansowane zlecenie (limit, stop-limit, take-profit itp.)"""
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == current_user.id
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    new_order = OrderFuture(
        user_id=current_user.id,
        portfolio_id=portfolio_id,
        symbol=symbol,
        order_type=order_type,
        amount=amount,
        price=price,
        stop_price=stop_price,
        currency=currency,
        status=OrderStatus.PENDING
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return {
        "message": "Advanced order created successfully",
        "order_id": new_order.id,
        "status": new_order.status.value,
        "order_type": new_order.order_type.value,
    }


async def process_orders_in_background():
    """
    Funkcja działająca w tle, która co sekundę przetwarza zlecenia w tabeli OrdersFuture.
    """
    while True:
        db: Session = SessionLocal()
        try:
            pending_orders = db.query(OrderFuture).filter(OrderFuture.status == OrderStatus.PENDING).all()

            for order in pending_orders:

                current_price = await get_current_market_price(order.symbol)


                result = await process_order(order, current_price, db)

                if result:
                    print(f"Order {order.id} processed successfully.")
                else:
                    print(f"Order {order.id} not executed.")

        except Exception as e:
            print(f"Error processing orders: {e}")
        finally:
            db.close()

        await asyncio.sleep(1)