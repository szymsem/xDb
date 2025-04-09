from fastapi import FastAPI
from routers import crypto_history, crypto_websocket

app = FastAPI()

app.include_router(crypto_history.router, prefix="/api", tags=["Crypto History"])
app.include_router(crypto_websocket.router, prefix="/api", tags=["Crypto WebSocket"])

@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to the Crypto API"}