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


# ================= SPÓŁKI – PEŁNE NAZWY =================
COMPANY_NAMES = {
    "NVDA": "NVIDIA Corporation",
    "MSFT": "Microsoft Corporation",
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "MCD": "McDonald's Corporation",
    "LMT": "Lockheed Martin Corporation",
    "RTX": "RTX Corporation",
    "JPM": "JPMorgan Chase & Co.",
    "GS": "Goldman Sachs Group",
    "ASML": "ASML Holding N.V.",
    "SAP": "SAP SE",
    "PZU": "PZU S.A.",
    "PKO": "PKO Bank Polski",
    "PEO": "Bank Pekao S.A.",
}

MARKET_MAP = {
    "GPW": "Polska – GPW",
    "USA": "USA – Wall Street",
    "EU": "Europa"
}


# ================= WATCHLIST =================
WATCHLIST_EXTRA = {
    # USA / Global
    "AAPL", "AMZN", "META", "MSFT", "NVDA",
    "TSLA", "MCD", "COST", "JPM", "GS",
    "LMT", "RTX",
    # Europa
    "ASML", "SAP",
}

ALL_SYMBOLS = list(set(INSTRUMENTS) | WATCHLIST_EXTRA)


# ================= USTAWIENIA =================
SILENCE_START, SILENCE_END = 0, 6
CHECK_INTERVAL = 300
last_update_id = None
last_check_time = "Brak"


def is_night_silence(now):
    return SILENCE_START <= now.hour < SILENCE_END


# ================= DANE RYNKOWE =================
def to_float_list(seq):
    return [float(x[0]) if isinstance(x, (list, tuple, np.ndarray)) else float(x) for x in seq if x is not None]


def get_market_data(symbol):
    symbol = symbol.upper()
    GPW = {"PKO", "PEO", "PZU", "ING", "KGH", "XTB", "11B", "CDR"}

    if symbol in GPW:
        try:
            url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
            r_resp = requests.get(url, timeout=10)
            lines = r_resp.text.splitlines()[1:]
            prices, volumes = [], []
            for row in lines[-300:]:
                p = row.split(",")
                if len(p) >= 6:
                    prices.append(float(p[4]))
                    volumes.append(float(p[5]))
            return prices, volumes
        except:
            return [], []

    try:
        data = yf.download(symbol, period="1y", interval="1d", progress=False)
        if data.empty:
            return [], []
        return (
            to_float_list(data["Close"].values),
            to_float_list(data["Volume"].values),
        )
    except:
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
                f"🤖 <b>Status bota</b>\n\n"
                f"🕒 Ostatni skan: {last_check_time}\n"
                f"📊 Spółek w radarze: {len(ALL_SYMBOLS)}\n"
                f"⏳ Cooldown: {COOLDOWN//3600}h"
            )

        elif text == "/stats":
            send_telegram_message(
                f"📊 <b>Statystyki</b>\n\n"
                f"Łącznie: {r.get('stats:total') or 0}\n"
                f"✅ Trendowe: {r.get('stats:TREND_CONFIRMATION') or 0}\n"
                f"⚠️ Kontrariańskie: {r.get('stats:CONTRARIAN') or 0}\n"
                f"📊 Zmiana zachowania: {r.get('stats:BEHAVIOR_CHANGE') or 0}"
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
                verdict = "✅ KUPUJ"
            elif s["category"] == "CONTRARIAN":
                verdict = "❌ SPRZEDAJ / OMIJAJ"
            else:
                verdict = "⏸ TRZYMAJ / OBSERWUJ"

            company = COMPANY_NAMES.get(symbol, symbol)
            market = "Polska – GPW" if symbol in {"PKO","PEO","PZU","ING","KGH","XTB","11B","CDR"} else "USA / EU"

            msg = (
                f"📡 <b>{company} ({symbol})</b>\n"
                f"Rynek: {market}\n\n"
                f"Sytuacja: {s['title']}\n"
                f"Werdykt: <b>{verdict}</b>\n\n"
                f"Typ: {s['category']}\n"
                f"Ryzyko: {s['risk']}\n\n"
                f"{s['message']}"
            )

            send_telegram_message(msg)
            save_signal(symbol, s, verdict, now)
            set_last_signal_time(symbol, now)
            time.sleep(1)


# ================= START =================
if __name__ == "__main__":
    print("🚀 Bot uruchomiony")
    while True:
        handle_telegram_commands()
        analyze_market()
        time.sleep(CHECK_INTERVAL)
