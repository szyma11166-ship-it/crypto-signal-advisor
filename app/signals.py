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
