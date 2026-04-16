import time
from datetime import datetime, timezone
import requests
import yfinance as yf
import numpy as np
import pandas as pd

from config import INSTRUMENTS, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER
from signals import detect_volatility_signal, detect_volume_anomaly
from notifier import send_telegram_message, get_updates
from state import get_last_signal_time, set_last_signal_time
from history import add_signal, get_last_signal

# ================== KONFIGURACJA CZASOWA ==================
CHECK_INTERVAL = 3600
COOLDOWN = 10800
SILENCE_START, SILENCE_END = 0, 6

last_update_id = None
last_check_time = None

def is_night_silence(now: datetime) -> bool:
    return SILENCE_START <= now.hour < SILENCE_END

def load_portfolio_groups():
    import json, os
    path = "portfolio.json"
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f: return json.load(f).get("groups", {})
    except: return {}

def portfolio_context(symbol: str):
    groups = load_portfolio_groups()
    weight = 0.0
    hits = []
    for name, grp in groups.items():
        if symbol in grp.get("instruments", []):
            w = float(grp.get("weight", 0))
            weight += w
            hits.append((name, int(w * 100)))
    return weight, hits

def to_float_list(seq):
    return [float(x[0]) if isinstance(x, (list, np.ndarray)) else float(x) for x in seq]

# ================== INTELIGENTNE POBIERANIE DANYCH ==================
def get_market_data(symbol: str):
    symbol = symbol.upper()
    # Rozpoznawanie rynku: jeśli symbol jest krótki i bez kropki, uznajemy go za GPW
    # (Możesz tu dodać więcej symboli GPW)
    gpw_symbols = ["PKO", "PEO", "MBK", "ING", "PZU", "ALE", "KGH", "DNP", "LPP", "SANTANDER", "CDR"]
    
    if symbol in gpw_symbols:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        try:
            r = requests.get(url, timeout=10)
            lines = r.text.splitlines()[1:]
            prices, volumes = [], []
            for row in lines[-100:]:
                parts = row.split(",")
                if len(parts) >= 6:
                    prices.append(float(parts[4]))
                    volumes.append(float(parts[5]))
            return prices, volumes
        except: return [], []

    # USA / Global (Yahoo Finance)
    try:
        data = yf.download(symbol, period="10d", interval="1h", progress=False)
        if data.empty: return [], []
        prices = to_float_list(data["Close"].dropna().values)
        volumes = to_float_list(data["Volume"].dropna().values)
        return prices, volumes
    except: return [], []

# ================== TELEGRAM ==================
def handle_telegram_commands():
    global last_update_id
    try:
        updates = get_updates(last_update_id)
        for update in updates:
            last_update_id = update["update_id"] + 1
            text = update.get("message", {}).get("text", "").strip()
            if text == "/status":
                msg = f"<b>🤖 Status Maszyny</b>\n\n✅ Działa\n📊 Śledzi: {len(INSTRUMENTS)} spółek\n🕒 Ost. analiza: {last_check_time}"
                send_telegram_message(msg)
    except: pass

# ================== GŁÓWNA ANALIZA (LOOP PO LIŚCIE) ==================
def analyze_market():
    global last_check_time
    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    print(f"--- START ANALIZY: {len(INSTRUMENTS)} instrumentów ---")

    for symbol in INSTRUMENTS:
        prices, volumes = get_market_data(symbol)
        if len(prices) < 20: continue # Potrzebujemy min. 20 dla RSI

        signals = []
        v_signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)
        vol_signal = detect_volume_anomaly(volumes, multiplier=VOLUME_MULTIPLIER)

        if v_signal: signals.append(v_signal)
        if vol_signal: signals.append(vol_signal)

        if signals:
            # Sprawdź cooldown DLA TEJ KONKRETNEJ SPÓŁKI
            last_time = get_last_signal_time(symbol)
            if last_time:
                diff = (now - last_time).total_seconds()
                if diff < COOLDOWN:
                    print(f"Pominięto {symbol} - cooldown (jeszcze {int((COOLDOWN-diff)/60)} min)")
                    continue 

            if is_night_silence(now):
                continue
            
            # ... wysyłanie wiadomości ...
            
            send_telegram_message(msg)
            
            # ZAPAMIĘTAJ, że dla tej spółki już wysłałeś alert
            set_last_signal_time(symbol, now)
            add_signal(symbol, "akcje", signals, now)

            time.sleep(1) # Anty-spam Telegrama

if __name__ == "__main__":
    while True:
        try:
            handle_telegram_commands()
            analyze_market()
        except Exception as e:
            print(f"Błąd pętli: {e}")
        time.sleep(60) # Sprawdzaj co minutę (ale cooldowny w funkcjach pilnują spamu)
