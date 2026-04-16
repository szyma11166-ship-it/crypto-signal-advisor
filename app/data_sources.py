import requests


def get_market_history(instrument: str, limit: int = 100):
    """
    Abstrakcyjne źródło danych rynkowych.
    Technicznie: feed testowy.
    Semantycznie: instrument finansowy (akcja / indeks / ETF).
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",   # FEED TECHNICZNY (do podmiany na akcje)
        "interval": "1h",
        "limit": limit
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    prices = []
    volumes = []

    for candle in response.json():
        prices.append(float(candle[4]))   # close
        volumes.append(float(candle[5]))  # volume

    return prices, volumes
