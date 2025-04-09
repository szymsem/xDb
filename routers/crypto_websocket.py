from fastapi import APIRouter, WebSocket
from binance import AsyncClient, BinanceSocketManager
import asyncio

router = APIRouter()

@router.websocket("/crypto/ws/{symbol}")
async def crypto_websocket(websocket: WebSocket, symbol: str):
    """
    WebSocket do odbierania aktualnych cen z Binance.
    """
    await websocket.accept()

    client = await AsyncClient.create()
    bsm = BinanceSocketManager(client)

    stream = bsm.symbol_ticker_socket(symbol)

    async with stream as ticker_socket:
        try:
            while True:
                msg = await ticker_socket.recv()
                await websocket.send_json(msg)
        except Exception as e:
            print(f"WebSocket error: {e}")
        finally:
            await client.close_connection()
            await websocket.close()