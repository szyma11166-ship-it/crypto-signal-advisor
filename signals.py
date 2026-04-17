import numpy as np
import pandas as pd


# ---------------- RSI ----------------
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None

    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0

    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        up_val = max(delta, 0)
        down_val = max(-delta, 0)
        up = (up * (period - 1) + up_val) / period
        down = (down * (period - 1) + down_val) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi[-1]


# ---------------- EMA ----------------
def calculate_ema(prices, period=200):
    if len(prices) < period:
        return None
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]


# ---------------- GŁÓWNA LOGIKA ----------------
def detect_market_signals(
    prices,
    volumes,
    volatility_threshold,
    volume_multiplier,
    rsi_period=14
):
    signals = []

    if len(prices) < 50 or len(volumes) < 20:
        return signals

    current_price = prices[-1]
    rsi = calculate_rsi(prices, rsi_period)
    ema200 = calculate_ema(prices, 200)

    # === 1️⃣ SYGNAŁY MOMENTUM / TREND ===
    if rsi is not None and rsi < 30:
        if ema200 and current_price > ema200:
            # ✅ sygnał w trendzie
            signals.append({
                "category": "TREND_CONFIRMATION",
                "title": "Korekta w trendzie wzrostowym",
                "message": (
                    f"RSI={rsi:.1f}, cena powyżej EMA200.\n"
                    "Spółka znajduje się w trendzie wzrostowym "
                    "i przechodzi korektę."
                ),
                "risk": "NISKIE–ŚREDNIE"
            })
        else:
            # ⚠️ sygnał kontrariański
            signals.append({
                "category": "CONTRARIAN",
                "title": "Silne wyprzedanie w trendzie spadkowym",
                "message": (
                    f"RSI={rsi:.1f}, cena poniżej EMA200.\n"
                    "To sygnał kontrariański — podwyższone ryzyko."
                ),
                "risk": "WYSOKIE"
            })

    if rsi is not None and rsi > 70:
        signals.append({
            "category": "BEHAVIOR_CHANGE",
            "title": "Rynek przegrzany",
            "message": (
                f"RSI={rsi:.1f}.\n"
                "Wysokie momentum wzrostowe – możliwa korekta lub konsolidacja."
            ),
            "risk": "ŚREDNIE"
        })

    # === 2️⃣ SYGNAŁ ZACHOWANIA RYNKU (WOLUMEN) ===
    avg_volume = np.mean(volumes[-20:-1])
    current_volume = volumes[-1]

    if avg_volume > 0 and current_volume > avg_volume * volume_multiplier:
        signals.append({
            "category": "BEHAVIOR_CHANGE",
            "title": "Nietypowo wysoka aktywność",
            "message": (
                f"Wolumen {current_volume/avg_volume:.1f}× powyżej średniej.\n"
                "Rynek zwraca uwagę na spółkę."
            ),
            "risk": "ZMIENNE"
        })

    return signals
