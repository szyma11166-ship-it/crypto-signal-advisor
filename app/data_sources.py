import requests


def get_price_history(instrument: str, limit: int = 100):
    """
    Tymczasowe źródło danych.
    Technicznie: krypto feed.
    Semantycznie: abstrakcyjny instrument.
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",   # FEED TECHNICZNY (do podmiany później)
        "interval": "1h",
        "limit": limit
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    return [float(candle[4]) for candle in response.json()]
