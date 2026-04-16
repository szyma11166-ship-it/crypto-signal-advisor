import statistics


def detect_volatility_signal(prices: list, threshold: float):
    if len(prices) < 10:
        return None

    returns = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
    ]

    volatility = statistics.stdev(returns)

    if volatility > threshold:
        return {
            "type": "PODWYŻSZONA_ZMIENNOŚĆ",
            "value": round(volatility, 4),
            "message": (
                "Zaobserwowano istotny wzrost zmienności. "
                "Może to oznaczać zmianę reżimu rynkowego lub wzrost niepewności."
            ),
        }

    return None


def detect_volume_anomaly(volumes: list, multiplier: float = 2.0):
    if len(volumes) < 20:
        return None

    average_volume = statistics.mean(volumes[:-1])
    last_volume = volumes[-1]

    if last_volume > average_volume * multiplier:
        return {
            "type": "ANOMALIA_WOLUMENU",
            "value": round(last_volume / average_volume, 2),
            "message": (
                "Ostatni wolumen był znacząco wyższy niż średnia. "
                "Może to wskazywać na zwiększoną aktywność uczestników rynku."
            ),
        }

    return None