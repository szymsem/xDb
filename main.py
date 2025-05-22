
from fastapi import FastAPI

from services.orders_service import process_orders_in_background
from services.db import init_db
from routers import crypto_history, crypto_websocket, auth, portfolio, orders, notifications
import asyncio

init_db()

app = FastAPI()

app.include_router(crypto_history.router, prefix="/api", tags=["Crypto History"])
app.include_router(crypto_websocket.router, prefix="/api", tags=["Crypto WebSocket"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(portfolio.router, prefix="/api", tags=["Portfolios"])
app.include_router(orders.router, prefix="/api", tags=["Orders"])
app.include_router(notifications.router, prefix="/api", tags=["Notifications"])


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(process_orders_in_background())

@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to the Crypto API"}