import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.binance_service import get_binance_supported_currencies, get_current_market_price
from models.user import Portfolio, PortfolioAsset, User, CurrencyBalance, Order, OrderType, OrderStatus, SessionLocal, \
    AdvancedOrderType, OrderFuture
from services.db import get_db
from services.auth import get_current_user
from services.orders_service import execute_market_sell, execute_buy
from services.notification_service import notify_order_status_change, notify_order_execution

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
    """Tworzy zlecenie typu limit, stop-limit, take-profit itp"""
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


@router.put("/orders/{order_id}/modify")
async def modify_order(
        order_id: int,
        order_type: str = "advanced",  # 'market' lub 'advanced'
        new_amount: float = None,
        new_price: float = None,
        new_stop_price: float = None,  # Tylko dla zleceń advanced
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Modyfikuje istniejące zlecenie (tylko dla zlecen  PENDING).
    """
    if order_type == "market":
        order = db.query(Order).filter(
            Order.id == order_id,
            Order.user_id == current_user.id
        ).first()
    elif order_type == "advanced":
        order = db.query(OrderFuture).filter(
            OrderFuture.id == order_id,
            OrderFuture.user_id == current_user.id
        ).first()
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid order_type. Use 'market' or 'advanced'"
        )

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Only PENDING orders can be modified"
        )

    # Walidacja parametrów
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

    if order_type == "advanced" and new_stop_price is not None and new_stop_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Stop price must be positive"
        )

    try:
        if new_amount is not None:
            order.amount = new_amount

        if new_price is not None:
            order.price = new_price

        if order_type == "advanced" and new_stop_price is not None:
            order.stop_price = new_stop_price

        db.commit()
        db.refresh(order)

        response = {
            "message": "Order modified successfully",
            "order_id": order.id,
            "type": order_type,
            "new_amount": order.amount,
            "status": order.status.value
        }

        if new_price is not None:
            response["new_price"] = order.price

        if order_type == "advanced" and new_stop_price is not None:
            response["new_stop_price"] = order.stop_price

        return response

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to modify order: {str(e)}"
        )

@router.put("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    order_type: str = "advanced",  # 'market' lub 'advanced'
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Anuluje zlecenie (tylko dla zlecen PENDING).
    """
    if order_type == "market":
        order = db.query(Order).filter(
            Order.id == order_id,
            Order.user_id == current_user.id
        ).first()
    elif order_type == "advanced":
        order = db.query(OrderFuture).filter(
            OrderFuture.id == order_id,
            OrderFuture.user_id == current_user.id
        ).first()
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid order_type. Use 'market' or 'advanced'"
        )

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
            "type": order_type,
            "status": order.status.value
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel order: {str(e)}"
        )


async def execute_market_order(order_id: int):
    """Główna funkcja wykonująca zlecenie market"""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order or order.status != OrderStatus.PENDING:
            return

        if order.order_type == OrderType.BUY:
            await execute_buy(order, db)
        elif order.order_type == OrderType.SELL:
            await execute_market_sell(order, db)

    except Exception as e:
        print(f"Order execution error: {str(e)}")
    finally:
        db.close()


@router.get("/orders")
def get_user_orders(
        status: OrderStatus = None,
        advanced: bool = False,  # Nowy parametr do filtrowania typów zleceń
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Pobiera listę zleceń użytkownika
    :param status: Filtruj po statusie
    :param advanced: Jeśli True, zwraca tylko zlecenia zaawansowane. Jeśli False, tylko podstawowe.
                    Jeśli None, zwraca wszystkie typy zleceń.
    """
    result = []

    # Pobierz podstawowe zlecenia
    if advanced is False or advanced is None:
        query = db.query(Order).filter(Order.user_id == current_user.id)
        if status:
            query = query.filter(Order.status == status)
        orders = query.order_by(Order.created_at.desc()).all()

        for o in orders:
            result.append({
                "id": o.id,
                "type": "market",
                "symbol": o.symbol,
                "order_type": o.order_type.value,
                "amount": o.amount,
                "price": o.price,
                "currency": o.currency,
                "status": o.status.value,
                "created_at": o.created_at.isoformat(),
                "executed_at": o.executed_at.isoformat() if o.executed_at else None
            })

    # Pobierz zaawansowane zlecenia
    if advanced is True or advanced is None:
        future_query = db.query(OrderFuture).filter(OrderFuture.user_id == current_user.id)
        if status:
            future_query = future_query.filter(OrderFuture.status == status)
        future_orders = future_query.order_by(OrderFuture.created_at.desc()).all()

        for o in future_orders:
            result.append({
                "id": o.id,
                "type": "advanced",
                "symbol": o.symbol,
                "order_type": o.order_type.value,
                "amount": o.amount,
                "price": o.price,
                "stop_price": o.stop_price,
                "currency": o.currency,
                "status": o.status.value,
                "created_at": o.created_at.isoformat(),
                "executed_at": o.executed_at.isoformat() if o.executed_at else None
            })

    # Sortuj wszystkie wyniki po dacie utworzenia
    result.sort(key=lambda x: x['created_at'], reverse=True)

    return result
