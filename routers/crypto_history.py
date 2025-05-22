from fastapi import APIRouter
from binance.client import Client
import json
import redis.asyncio as redis  
from services.logger import logger

router = APIRouter()
client = Client()


redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)

async def get_from_cache(key: str):
    """
    Pobiera dane z cache Redis.
    """
    try:
        data = await redis_client.get(key)
        if data:
            print(f"[CACHE HIT] Klucz: {key}")  
        else:
            print(f"[CACHE MISS] Klucz: {key}")  
        return data
    except Exception as e:
        logger.error(f"failed to get cache {str(e)}", exc_info=True)
        return None

async def set_to_cache(key: str, value: str, expire: int = 3600):
    """
    Zapisuje dane do cache Redis z czasem wygaśnięcia.
    """
    try:
        await redis_client.set(key, value, ex=expire)
        print(f"[CACHE SET] Klucz: {key}, Czas wygaśnięcia: {expire}s")  
    except Exception as e:
        logger.error(f"redis error: {str(e)}", exc_info=True)
@router.get("/crypto/history/{symbol}")
async def get_crypto_history(symbol: str, interval: str = "1d", limit: int = 100):
    """
    Pobiera historię cen dla danego symbolu z Binance.
    """
    cache_key = f"{symbol}:{interval}:{limit}"  

    
    cached_data = await get_from_cache(cache_key)
    if cached_data:
        print(f"[REDIS] Dane dla {symbol} pobrane z cache.")  
        return {"symbol": symbol, "interval": interval, "data": json.loads(cached_data)}

    try:
        print(f"[BINANCE] Pobieranie danych dla {symbol} z Binance...")
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        
        await set_to_cache(cache_key, json.dumps(klines))

        print(f"[BINANCE] Dane dla {symbol} zapisane w cache.")  
        return {"symbol": symbol, "interval": interval, "data": klines}
    except Exception as e:
        logger.error(f"Error during download from Binance: {str(e)}",exc_info=True)
        return {"error": str(e)}
