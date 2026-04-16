import numpy as np
import pandas as pd

# ================== WSKAŹNIKI TECHNICZNE ==================
def calculate_rsi(prices, period=14):
    """Oblicza klasyczny wskaźnik RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return None
    
    s = pd.Series(prices)
    delta = s.diff()
    
    # Wilder's smoothing (prawidłowe wyliczenie RSI)
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


# ================== DETEKCJA SYGNAŁÓW ==================
def detect_volatility_signal(prices, threshold):
    """
    Łączy klasyczną zmienność z profesjonalnym wskaźnikiem RSI.
    Zwraca sygnał tylko wtedy, gdy sytuacja jest naprawdę warta uwagi.
    """
    if len(prices) < 20:
        return None

    current_price = prices[-1]
    previous_price = prices[-2]
    
    # 1. Sprawdzamy RSI
    rsi = calculate_rsi(prices)
    if rsi is not None:
        if rsi < 30:
            return {
                "type": "Wyprzedanie (RSI)",
                "value": f"RSI: {rsi:.1f}",
                "message": "Wskaźnik RSI spadł poniżej 30. Aktywo może być silnie niedowartościowane (potencjalny dołek)."
            }
        elif rsi > 70:
            return {
                "type": "Wykupienie (RSI)",
                "value": f"RSI: {rsi:.1f}",
                "message": "Wskaźnik RSI wzrósł powyżej 70. Aktywo jest przewartościowane (uwaga na możliwą korektę)."
            }

    # 2. Klasyczna zmiana procentowa (Twój stary bezpiecznik, jeśli RSI milczy)
    price_change = ((current_price - previous_price) / previous_price) * 100
    if abs(price_change) >= threshold:
        direction = "Wzrost" if price_change > 0 else "Spadek"
        return {
            "type": f"Gwałtowny {direction}",
            "value": f"{price_change:.2f}%",
            "message": f"Cena zmieniła się o ponad {threshold}% w ciągu jednego interwału."
        }

    return None


def detect_volume_anomaly(volumes, period=20, multiplier=2.0):
    """
    Sprawdza, czy wolumen jest X razy większy niż średnia z ostatnich 'period' interwałów.
    To filtruje normalne rynkowe wahania.
    """
    if len(volumes) < period + 1:
        return None

    recent_vol = volumes[-1]
    # Srednia z ostatnich 20 okresów (bez uwzględniania obecnego)
    avg_vol = np.mean(volumes[-period-1:-1]) 

    if avg_vol > 0 and recent_vol > (avg_vol * multiplier):
        return {
            "type": "Potężny Wolumen",
            "value": f"{recent_vol:,.0f}",
            "message": f"Obecny wolumen jest ponad {multiplier}-krotnie wyższy niż średnia. Duzi gracze (instytucje) weszli do gry!"
        }
    
    return None
