import numpy as np

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            up_chg = delta
            down_chg = 0
        else:
            up_chg = 0
            down_chg = -delta
        up = (up * (period - 1) + up_chg) / period
        down = (down * (period - 1) + down_chg) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi[-1]

def calculate_ema(prices, period=200):
    if len(prices) < period:
        return None
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

def detect_market_signals(prices, volumes, volatility_threshold, vol_multiplier):
    signals = []
    current_price = prices[-1]
    
    # --- 1. RSI (Termometr) ---
    rsi = calculate_rsi(prices)
    
    # --- 2. EMA 200 (Kompas) ---
    import pandas as pd # potrzebne do ewm
    ema200 = calculate_ema(prices, 200)
    
    # --- 3. Logika Sygnałów Inteligentnych ---
    if rsi < 30:
        if ema200 and current_price > ema200:
            signals.append({
                "type": "🔥 MOCNE KUPUJ (Pullback)",
                "value": f"RSI: {rsi:.1f}",
                "message": "Cena w trendzie wzrostowym (nad EMA200) zaliczyła korektę. Statystycznie to świetny moment na wejście."
            })
        else:
            signals.append({
                "type": "⚠️ WYPRZEDANIE (Ryzyko)",
                "value": f"RSI: {rsi:.1f}",
                "message": "Cena jest nisko, ALE trend jest spadkowy (pod EMA200). Uważaj na łapanie spadającego noża!"
            })
            
    if rsi > 70:
        signals.append({
            "type": "🔔 WYSOKIE RSI",
            "value": f"RSI: {rsi:.1f}",
            "message": "Spółka może być przegrzana. Rozważ realizację zysków."
        })

    # --- 4. Wolumen (Potwierdzenie) ---
    avg_vol = np.mean(volumes[-20:-1])
    current_vol = volumes[-1]
    if current_vol > avg_vol * vol_multiplier:
        signals.append({
            "type": "📊 SKOK WOLUMENU",
            "value": f"x{current_vol/avg_vol:.1f}",
            "message": "Nietypowa aktywność! Gruby kapitał wszedł do gry."
        })

    return signals