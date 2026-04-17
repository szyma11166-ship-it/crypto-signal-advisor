import os
import time
import ast
from datetime import datetime, timezone

import requests
import yfinance as yf
import numpy as np
import redis

from config import (
    INSTRUMENTS,
    VOLATILITY_THRESHOLD,
    VOLUME_MULTIPLIER,
    COOLDOWN,
)
from signals import detect_market_signals
from notifier import send_telegram_message, get_updates


# ================= REDIS =================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_last_signal_time(symbol):
    ts = r.get(f"cooldown:{symbol}")
    return datetime.fromisoformat(ts) if ts else None


def set_last_signal_time(symbol, dt):
    r.set(f"cooldown:{symbol}", dt.isoformat())


def save_signal(symbol, signal, verdict, dt, max_items=200):
    entry = {
        "time": dt.isoformat(),
        "symbol": symbol,
        "category": signal["category"],
        "title": signal["title"],
        "risk": signal["risk"],
        "message": signal["message"],
        "verdict": verdict,
    }
    r.lpush(f"signals:{symbol}", str(entry))
    r.ltrim(f"signals:{symbol}", 0, max_items - 1)
    r.incr("stats:total")
    r.incr(f"stats:{signal['category']}")
    r.incr(f"stats:symbol:{symbol}")


# ================= RYNKI =================
GPW_SYMBOLS = {
    "PKO", "PEO", "PZU", "ING", "KGH", "XTB",
    "11B", "CDR", "ALE", "LPP", "DNP", "KTY",
    "ALR", "ENA", "PKN"
}

YAHOO_SYMBOLS = {
    "AAPL", "AMZN", "META", "MSFT", "NVDA",
    "TSLA", "MCD", "COST", "JPM", "GS",
    "LMT", "RTX", "XOM", "CVX", "VLO",
    "AMD", "INTC", "IBM", "ORCL",
    "ASML", "SAP", "TSM", "GLD", "SLV", "4GLD.DE"
}

ALL_SYMBOLS = sorted(set(INSTRUMENTS) | YAHOO_SYMBOLS)


# ================= POMOCNICZE =================
SILENCE_START, SILENCE_END = 0, 6
COMMAND_CHECK_INTERVAL = 3     # sekundy
MARKET_ANALYSIS_INTERVAL = 300 # sekundy

last_update_id = None
last_check_time = "Brak"

last_command_check = 0
last_market_check = 0


def is_night_silence(now):
    return SILENCE_START <= now.hour < SILENCE_END


def to_float_list(seq):
    out = []
    for x in seq:
        try:
            out.append(float(x[0]) if isinstance(x, (list, tuple, np.ndarray)) else float(x))
        except Exception:
            pass
    return out


# ================= DANE =================
def get_market_data(symbol):
    symbol = symbol.upper()

    if symbol in GPW_SYMBOLS:
        try:
            url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return [], []

            lines = resp.text.splitlines()[1:]
            prices, volumes = [], []
            for row in lines[-300:]:
                p = row.split(",")
                if len(p) >= 6:
                    prices.append(float(p[4]))
                    volumes.append(float(p[5]))
            return prices, volumes
        except Exception:
            return [], []

    if symbol in YAHOO_SYMBOLS:
        try:
            data = yf.download(symbol, period="1y", interval="1d", progress=False)
            if data.empty:
                return [], []
            return (
                to_float_list(data["Close"].values),
                to_float_list(data["Volume"].values),
            )
        except Exception:
            return [], []

    return [], []


# ================= KOMENDY =================
def handle_telegram_commands():
    global last_update_id

    updates = get_updates(last_update_id)
    if not updates:
        return

    for upd in updates:
        last_update_id = upd["update_id"] + 1
        text = upd.get("message", {}).get("text", "").strip()

        if text == "/status":
            send_telegram_message(
                f"🤖 Status bota\n"
                f"Ostatni skan: {last_check_time}\n"
                f"Spółek: {len(ALL_SYMBOLS)}"
            )

        elif text == "/stats":
            send_telegram_message(
                f"📊 Statystyki\n"
                f"Łącznie: {r.get('stats:total') or 0}\n"
                f"Trendowe: {r.get('stats:TREND_CONFIRMATION') or 0}\n"
                f"Kontrariańskie: {r.get('stats:CONTRARIAN') or 0}\n"
                f"Zmiana zachowania: {r.get('stats:BEHAVIOR_CHANGE') or 0}"
            )


# ================= ANALIZA =================
def analyze_market():
    global last_check_time
    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    for symbol in ALL_SYMBOLS:
        last = get_last_signal_time(symbol)
        if last and (now - last).total_seconds() < COOLDOWN:
            continue

        prices, vols = get_market_data(symbol)
        if len(prices) < 50:
            continue

        signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
        if not signals or is_night_silence(now):
            continue

        for s in signals:
            if s["category"] == "TREND_CONFIRMATION":
                verdict = "KUPUJ"
            elif s["category"] == "CONTRARIAN":
                verdict = "SPRZEDAJ / OMIJAJ"
            else:
                verdict = "TRZYMAJ / OBSERWUJ"

            msg = f"{symbol}\n{s['title']}\nWerdykt: {verdict}"
            send_telegram_message(msg)
            save_signal(symbol, s, verdict, now)
            set_last_signal_time(symbol, now)
            time.sleep(1)


# ================= START =================
if __name__ == "__main__":
    print("🚀 Bot uruchomiony (responsywny)")

    while True:
        now_ts = time.time()

        if now_ts - last_command_check >= COMMAND_CHECK_INTERVAL:
            handle_telegram_commands()
            last_command_check = now_ts

        if now_ts - last_market_check >= MARKET_ANALYSIS_INTERVAL:
            analyze_market()
            last_market_check = now_ts

        time.sleep(1)
