from binance.client import Client
from binance import AsyncClient

def get_binance_supported_currencies():
    client = Client()
    try:
        # pobiera wszystkie pary handlowe z binance
        exchange_info = client.get_exchange_info()
        symbols = exchange_info['symbols']

        currencies = set()
        for symbol in symbols:
            currencies.add(symbol['baseAsset'])
            currencies.add(symbol['quoteAsset'])

        return sorted(list(currencies))
    except Exception as e:
        print(f"Error fetching currencies from Binance: {e}")
        return []

async def get_current_market_price(symbol: str):
    """Pobiera aktualną cenę rynkową z Binance"""

    client = await AsyncClient.create()
    try:
        ticker = await client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    finally:
        await client.close_connection()