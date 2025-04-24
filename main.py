from fastapi import FastAPI
from routers import crypto_history, crypto_websocket,auth
from fastapi.openapi.utils import get_openapi



app = FastAPI()

 
app.include_router(crypto_history.router, prefix="/api", tags=["Crypto History"])
app.include_router(crypto_websocket.router, prefix="/api", tags=["Crypto WebSocket"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to the Crypto API"}