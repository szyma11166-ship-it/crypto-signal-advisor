import time
from datetime import datetime, timezone
import requests
import yfinance as yf
import numpy as np
import pandas as pd

# Importy z Twoich plików
from config import INSTRUMENTS, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER, COOLDOWN
from signals import detect_volatility_signal, detect_volume_anomaly
from notifier import send_telegram_message, get_updates
from state import get_last_signal_time, set_last_signal_time
from history import add_signal

# ================== KONFIGURACJA CZASOWA ==================
SILENCE_START, SILENCE_END = 0, 6

last_update_id = None
last_check_time = "Brak"

def is_night_silence(now: datetime) -> bool:
    return SILENCE_START <= now.hour < SILENCE_END

def load_portfolio_groups():
    import json, os
    path = "portfolio.json"
    if not os.path.exists(path): return {}
    try:
        with open(path, "r") as f: 
            data = json.load(f)
            return data.get("groups", {})
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
    
    # Rozszerzona lista Twoich spółek z GPW na podstawie screenów
    gpw_list = [
        "PKO", "PEO", "PKN", "PZU", "ING", "KGH", "ALE", "LPP", 
        "DNP", "XTB", "KTY", "11B", "SNT", "PHT", "SN2", "CDR"
    ]
    
    if symbol in gpw_list:
        # Stooq dla GPW
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
        # Obsługa złota (4GLD.DE) i innych tickerów z kropką
        data = yf.download(symbol, period="10d", interval="1h", progress=False)
        if data.empty: return [], []
        prices = to_float_list(data["Close"].dropna().values)
        volumes = to_float_list(data["Volume"].dropna().values)
        return prices, volumes
    except: return [], []

# ================== TELEGRAM COMMANDS ==================
def handle_telegram_commands():
    global last_update_id
    try:
        updates = get_updates(last_update_id)
        for update in updates:
            last_update_id = update["update_id"] + 1
            msg_obj = update.get("message", {})
            text = msg_obj.get("text", "").strip()
            
            if text == "/status":
                status_msg = (
                    f"<b>🤖 Status Marka Towarka</b>\n\n"
                    f"✅ Maszyna działa\n"
                    f"📊 Śledzi: {len(INSTRUMENTS)} spółek\n"
                    f"🕒 Ost. analiza: {last_check_time}"
                )
                send_telegram_message(status_msg)
    except: pass

# ================== GŁÓWNA ANALIZA ==================
def analyze_market():
    global last_check_time
    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    print(f"[{last_check_time}] Rozpoczynam skanowanie {len(INSTRUMENTS)} instrumentów...")

    for symbol in INSTRUMENTS:
        try:
            # 1. Anty-spam: Sprawdź cooldown dla konkretnej spółki
            last_time = get_last_signal_time(symbol)
            if last_time:
                diff = (now - last_time).total_seconds()
                if diff < COOLDOWN:
                    continue # Pomijamy, bo niedawno był alert

            # 2. Pobierz dane
            prices, volumes = get_market_data(symbol)
            if len(prices) < 20:
                continue

            # 3. Wykryj sygnały
            signals = []
            v_signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)
            vol_signal = detect_volume_anomaly(volumes, multiplier=VOLUME_MULTIPLIER)

            if v_signal: signals.append(v_signal)
            if vol_signal: signals.append(vol_signal)

            # 4. Jeśli są sygnały - wyślij raport
            if signals:
                if is_night_silence(now):
                    print(f"Sygnał dla {symbol} zignorowany (cisza nocna).")
                    continue
                
                weight, groups = portfolio_context(symbol)
                relevance = "Wysokie" if weight >= 0.3 else "Normalne" if weight > 0 else "Obserwowane"
                
                msg = f"📡 <b>Sygnał: {symbol}</b>\nStatus: {relevance} (~{int(weight*100)}%)\n\n"
                for s in signals:
                    msg += f"• <b>{s['type']}</b> ({s['value']})\n{s['message']}\n\n"
                
                send_telegram_message(msg)
                
                # 5. Zapamiętaj wysłanie alertu
                set_last_signal_time(symbol, now)
                add_signal(symbol, "akcje", signals, now)
                
                time.sleep(1) # Mała przerwa między tickerami

        except Exception as e:
            print(f"Błąd przy analizie {symbol}: {e}")

# ================== PĘTLA GŁÓWNA ==================
if __name__ == "__main__":
    print("🚀 Maszyna Marek Towarek URUCHOMIONA")
    while True:
        try:
            handle_telegram_commands()
            analyze_market()
        except Exception as e:
            print(f"KRYTYCZNY BŁĄD PĘTLI: {e}")
        
        # Czekaj 5 minut przed kolejnym sprawdzeniem całego rynku
        # (cooldowny wewnątrz analyze_market i tak pilnują spamu)
        time.sleep(300) 
