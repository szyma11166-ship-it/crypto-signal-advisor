import requests

def get_price_history(symbol: str, limit: int = 100):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": limit
    }
    response = requests.get(url, params=params)
    response.raise_for_status()

    return [float(candle[4]) for candle in response.json()]
