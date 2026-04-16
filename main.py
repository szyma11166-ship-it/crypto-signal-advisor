import time
from datetime import datetime, timezone
import requests
import yfinance as yf
import numpy as np
import pandas as pd

from config import INSTRUMENTS, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER, COOLDOWN
from signals import detect_market_signals
from notifier import send_telegram_message, get_updates
from state import get_last_signal_time, set_last_signal_time

# ================== KONFIGURACJA ==================
SILENCE_START, SILENCE_END = 0, 6
last_update_id = None
last_check_time = "Brak"

def is_night_silence(now: datetime) -> bool:
    return SILENCE_START <= now.hour < SILENCE_END

def portfolio_context(symbol: str):
    import json, os
    path = "portfolio.json"
    if not os.path.exists(path): return 0.0, []
    try:
        with open(path, "r") as f:
            data = json.load(f).get("groups", {})
            weight = 0.0
            for name, grp in data.items():
                if symbol in grp.get("instruments", []):
                    weight += float(grp.get("weight", 0))
            return weight, []
    except: return 0.0, []

def to_float_list(seq):
    return [float(x[0]) if isinstance(x, (list, np.ndarray)) else float(x) for x in seq]

# ================== POPRAWIONE POBIERANIE DANYCH ==================
def get_market_data(symbol: str):
    symbol = symbol.upper()
    gpw_list = ["PKO", "PEO", "PKN", "PZU", "ING", "KGH", "ALE", "LPP", "DNP", "XTB", "KTY", "11B", "SNT", "PHT", "SN2", "CDR"]
    
    # HEADERS: Udajemy przeglądarkę, żeby Stooq nas nie blokował
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    if symbol in gpw_list:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if "Brak danych" in r.text or r.status_code != 200:
                return [], []
            
            lines = r.text.strip().splitlines()[1:]
            prices, volumes = [], []
            for row in lines[-300:]: # Ostatnie 300 dni dla EMA200
                parts = row.split(",")
                if len(parts) >= 6:
                    prices.append(float(parts[4]))
                    volumes.append(float(parts[5]))
            return prices, volumes
        except Exception as e:
            print(f"Błąd Stooq {symbol}: {e}")
            return [], []

    # USA
    try:
        data = yf.download(symbol, period="1y", interval="1d", progress=False)
        if data.empty: return [], []
        prices = to_float_list(data["Close"].dropna().values)
        volumes = to_float_list(data["Volume"].dropna().values)
        return prices, volumes
    except Exception as e:
        print(f"Błąd Yahoo {symbol}: {e}")
        return [], []

# ================== ANALIZA ==================
def analyze_market():
    global last_check_time
    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    print(f"[{last_check_time}] Skanowanie {len(INSTRUMENTS)} spółek...")

    for symbol in INSTRUMENTS:
        try:
            # Cooldown
            last_time = get_last_signal_time(symbol)
            if last_time and (now - last_time).total_seconds() < COOLDOWN:
                continue

            prices, volumes = get_market_data(symbol)
            
            # Musi być min 20 świec, żeby RSI w ogóle drgnęło
            if len(prices) < 20:
                print(f"[{symbol}] Za mało danych ({len(prices)} świec).")
                continue

            signals = detect_market_signals(prices, volumes, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)

            if signals:
                if is_night_silence(now): continue
                
                weight, _ = portfolio_context(symbol)
                relevance = "Wysokie" if weight >= 0.3 else "Normalne" if weight > 0 else "Obserwowane"
                
                msg = f"📡 <b>Sygnał: {symbol}</b>\nStatus: {relevance} (~{int(weight*100)}%)\n\n"
                for s in signals:
                    msg += f"• <b>{s['type']}</b>\n{s['message']}\n\n"
                
                send_telegram_message(msg)
                set_last_signal_time(symbol, now)
                time.sleep(1)

        except Exception as e:
            print(f"Błąd {symbol}: {e}")

if __name__ == "__main__":
    print("🚀 Maszyna Marek Towarek PRO URUCHOMIONA")
    while True:
        handle_telegram_commands()
        analyze_market()
        time.sleep(300) # Co 5 minut
