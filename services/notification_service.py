from datetime import datetime
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from models.user import User
from typing import Union
from models.user import Order, OrderFuture
from mail import fm


async def send_email_notification(
    user: User,
    subject: str,
    template_name: str,
    context: dict
):
    if not user.email:
        return

    message = MessageSchema(
        subject=subject,
        recipients=[user.email],
        template_body=context,
        subtype="html"
    )

    await fm.send_message(message, template_name=template_name)

async def notify_order_status_change(
    user: User,
    order: Union[Order, OrderFuture],
    old_status: str = None
):
    await send_email_notification(
        user=user,
        subject=f"Zmiana statusu zlecenia {order.id}",
        template_name="order_status.html",
        context={
            "order_id": order.id,
            "symbol": order.symbol,
            "order_type": order.order_type.value,
            "status": order.status.value,
            "old_status": old_status,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )

async def notify_order_execution(
    user: User,
    order: Union[Order, OrderFuture]
):
    await send_email_notification(
        user=user,
        subject=f"Zlecenie {order.id} wykonane",
        template_name="order_executed.html",
        context={
            "order_id": order.id,
            "symbol": order.symbol,
            "order_type": order.order_type.value,
            "amount": order.amount,
            "price": order.price,
            "date": order.executed_at.strftime("%Y-%m-%d %H:%M:%S")
        }
    )