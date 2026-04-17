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


# ---------------- ZMIENNOŚĆ (annualized volatility) ----------------
def calculate_volatility(prices, period=20):
    """
    Annualizowana zmienność historyczna na bazie dziennych zwrotów logarytmicznych.
    Zwraca wartość w procentach (np. 35.2 oznacza 35,2% rocznie).
    """
    if len(prices) < period + 1:
        return None

    recent = prices[-(period + 1):]
    log_returns = np.diff(np.log(recent))
    daily_std = np.std(log_returns, ddof=1)
    annualized = daily_std * np.sqrt(252) * 100  # w procentach
    return annualized


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
    vol_pct = calculate_volatility(prices, period=20)

    # === 1️⃣ SYGNAŁY MOMENTUM / TREND ===
    if rsi is not None and rsi < 30:
        if ema200 and current_price > ema200:
            # ✅ sygnał w trendzie wzrostowym
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

    # === 3️⃣ SYGNAŁ ZMIENNOŚCI (volatility_threshold) ===
    # Używamy teraz volatility_threshold – poprzednio parametr był ignorowany
    if vol_pct is not None and vol_pct > volatility_threshold * 10:
        # Domyślnie volatility_threshold=2.0, więc próg to 20% rocznie.
        # Mnożnik ×10 pozwala zachować dotychczasową konfigurację bez zmian.
        risk_level = "WYSOKIE" if vol_pct > volatility_threshold * 20 else "ŚREDNIE"
        signals.append({
            "category": "BEHAVIOR_CHANGE",
            "title": "Podwyższona zmienność historyczna",
            "message": (
                f"Zmienność 20-dniowa (annualizowana): {vol_pct:.1f}%.\n"
                "Instrument wykazuje ponadnormatywne wahania cen – "
                "szersze stop-lossy lub mniejsza pozycja."
            ),
            "risk": risk_level
        })

    return signals