from fastapi import APIRouter, WebSocket
from binance import AsyncClient, BinanceSocketManager
from services.logger import logger
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
            logger.error(f"websocket error: {str(e)}",)
        finally:
            await client.close_connection()
            await websocket.close()