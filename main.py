# main.py
from fastapi import FastAPI
from routers import crypto_history, crypto_websocket, auth
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS configuration (adjust as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crypto_history.router, prefix="/api", tags=["Crypto History"])
app.include_router(crypto_websocket.router, prefix="/api", tags=["Crypto WebSocket"])
app.include_router(auth.router, prefix="/api", tags=["Authentication"])

@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to the Crypto API"}

@app.get("/api/secure-data")
async def read_secure_data(current_user: auth.User = Depends(auth.get_current_active_user)):
    return {"message": "This is secure data", "user": current_user.username}