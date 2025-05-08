
from fastapi import FastAPI
from db import init_db
from routers import crypto_history, crypto_websocket, auth, portfolio

init_db()

app = FastAPI()

app.include_router(crypto_history.router, prefix="/api", tags=["Crypto History"])
app.include_router(crypto_websocket.router, prefix="/api", tags=["Crypto WebSocket"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(portfolio.router, prefix="/api", tags=["Portfolios"])


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to the Crypto API"}