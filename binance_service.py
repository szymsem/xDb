from binance.client import Client


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