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

    # Pobierz aktualną cenę z Binance
    try:
        current_price = await get_current_market_price(symbol)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch price for {symbol} from Binance: {str(e)}"
        )

    # Tworzenie zlecenia z aktualną ceną
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

    asyncio.create_task(execute_order(new_order.id, db))

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

            current_price = await get_current_market_price(order.symbol)
            total_value = order.amount * (order.price or current_price)

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



# @router.post("/orders/{order_id}/execute")
# async def execute_order(
#         order_id: int,
#         db: Session = Depends(get_db),
#         current_user: User = Depends(get_current_user)
# ):
#     """Ręczne zatwierdzanie i wykonanie zlecenia"""
#
#     local_db = SessionLocal()
#
#     order = db.query(Order).filter(
#         Order.id == order_id,
#         Order.user_id == current_user.id
#     ).first()
#
#     if not order:
#         raise HTTPException(status_code=404, detail="Order not found")
#
#     if order.status != OrderStatus.PENDING:
#         raise HTTPException(
#             status_code=400,
#             detail="Only PENDING orders can be executed"
#         )
#
#     try:
#         if order.order_type == OrderType.BUY:
#             # Logika kupna
#             current_price = await get_current_market_price(order.symbol)
#             total_cost = order.amount * (order.price or current_price)
#
#             # Sprawdź saldo
#             balance = db.query(CurrencyBalance).filter(
#                 CurrencyBalance.user_id == order.user_id,
#                 CurrencyBalance.currency == order.currency
#             ).first()
#
#             if not balance or balance.amount < total_cost:
#                 order.status = OrderStatus.FAILED
#                 order.executed_at = datetime.utcnow()
#                 db.commit()
#                 raise HTTPException(
#                     status_code=400,
#                     detail="Insufficient funds to execute this order"
#                 )
#
#             # Realizacja kupna
#             balance.amount -= total_cost
#             asset = db.query(PortfolioAsset).filter(
#                 PortfolioAsset.portfolio_id == order.portfolio_id,
#                 PortfolioAsset.symbol == order.symbol
#             ).first()
#
#             if asset:
#                 new_amount = asset.amount + order.amount
#                 avg_price = ((asset.amount * asset.buy_price) + (
#                             order.amount * (order.price or current_price))) / new_amount
#                 asset.amount = new_amount
#                 asset.buy_price = avg_price
#             else:
#                 asset = PortfolioAsset(
#                     portfolio_id=order.portfolio_id,
#                     symbol=order.symbol,
#                     currency_type=order.currency,
#                     amount=order.amount,
#                     buy_price=order.price,
#                     buy_currency=order.currency
#                 )
#                 local_db.add(asset)
#
#             order.status = OrderStatus.COMPLETED
#
#         elif order.order_type == OrderType.SELL:
#             # Logika sprzedaży
#             asset = db.query(PortfolioAsset).filter(
#                 PortfolioAsset.portfolio_id == order.portfolio_id,
#                 PortfolioAsset.symbol == order.symbol
#             ).first()
#
#             if not asset or asset.amount < order.amount:
#                 order.status = OrderStatus.FAILED
#                 db.commit()
#                 raise HTTPException(
#                     status_code=400,
#                     detail="Insufficient assets to execute this order"
#                 )
#
#             current_price = await get_current_market_price(order.symbol)
#             total_value = order.amount * (order.price or current_price)
#
#             # Znajdź lub utwórz balans w walucie docelowej
#             balance = db.query(CurrencyBalance).filter(
#                 CurrencyBalance.user_id == order.user_id,
#                 CurrencyBalance.currency == order.currency
#             ).first()
#
#             if not balance:
#                 balance = CurrencyBalance(
#                     user_id=order.user_id,
#                     currency=order.currency,
#                     amount=0.0
#                 )
#                 db.add(balance)
#
#             # Realizacja sprzedaży
#             asset.amount -= order.amount
#             if asset.amount <= 0:
#                 db.delete(asset)
#
#             balance.amount += total_value
#             order.status = OrderStatus.COMPLETED
#
#         order.executed_at = datetime.utcnow()
#         db.commit()
#
#         return {
#             "message": "Order executed successfully",
#             "order_id": order.id,
#             "status": order.status.value,
#             "executed_at": order.executed_at.isoformat()
#         }
#
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(
#             status_code=500,
#             detail=f"Order execution failed: {str(e)}"
#         )

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

