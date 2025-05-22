import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from models.user import OrderFuture, OrderStatus, SessionLocal, AdvancedOrderType, CurrencyBalance, PortfolioAsset, \
    Order
from services.binance_service import get_current_market_price


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

    except Exception as e: # mozna zrobic dekoratora autorollback, value error nie jest potrzebny
        db.rollback()
        raise ValueError(f"Sell execution failed: {str(e)}")

async def execute_market_sell(order: Order, db: Session) -> None:
    """Realizuje zlecenie sprzedaży"""
    try:
        current_price = await get_current_market_price(order.symbol)
        total_value = order.amount * current_price

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

        asset.amount -= order.amount
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