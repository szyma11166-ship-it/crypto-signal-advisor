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


# =====================================================
# REDIS
# =====================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_last_signal_time(symbol: str):
    ts = r.get(f"cooldown:{symbol}")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def set_last_signal_time(symbol: str, dt: datetime):
    r.set(f"cooldown:{symbol}", dt.isoformat())


def save_signal(symbol: str, signal: dict, dt: datetime, max_items=50):
    key = f"signals:{symbol}"
    entry = {
        "time": dt.isoformat(),
        "symbol": symbol,
        "category": signal["category"],
        "title": signal["title"],
        "risk": signal["risk"],
        "message": signal["message"],
    }
    r.lpush(key, str(entry))
    r.ltrim(key, 0, max_items - 1)


def get_last_signals(limit_per_symbol=1, max_symbols=5):
    """
    Zwraca ostatnie sygnały z Redis dla kilku spółek.
    """
    results = []
    for symbol in INSTRUMENTS[:max_symbols]:
        key = f"signals:{symbol}"
        items = r.lrange(key, 0, limit_per_symbol - 1)
        for item in items:
            try:
                results.append(ast.literal_eval(item))
            except Exception:
                pass
    return results


# =====================================================
# USTAWIENIA OGÓLNE
# =====================================================
SILENCE_START = 0
SILENCE_END = 6
CHECK_INTERVAL = 300  # 5 minut

last_update_id = None
last_check_time = "Brak"


def is_night_silence(now: datetime) -> bool:
    return SILENCE_START <= now.hour < SILENCE_END


# =====================================================
# PORTFEL
# =====================================================
def portfolio_context(symbol: str) -> float:
    import json

    if not os.path.exists("portfolio.json"):
        return 0.0

    try:
        with open("portfolio.json", "r") as f:
            groups = json.load(f).get("groups", {})
            weight = 0.0
            for grp in groups.values():
                if symbol in grp.get("instruments", []):
                    weight += float(grp.get("weight", 0))
            return weight
    except Exception:
        return 0.0


# =====================================================
# DANE RYNKOWE
# =====================================================
def to_float_list(seq):
    result = []
    for x in seq:
        try:
            if isinstance(x, (list, tuple, np.ndarray)):
                result.append(float(x[0]))
            else:
                result.append(float(x))
        except Exception:
            pass
    return result


def get_market_data(symbol: str):
    symbol = symbol.upper()

    GPW_SYMBOLS = {
        "PKO", "PEO", "PKN", "PZU", "ING", "KGH",
        "ALE", "LPP", "DNP", "XTB", "KTY",
        "11B", "CDR", "PHT", "SN2", "SNK", "SNT"
    }

    # ---------- GPW → STOOQ ----------
    if symbol in GPW_SYMBOLS:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return [], []

            lines = resp.text.splitlines()[1:]
            prices, volumes = [], []

            for row in lines[-300:]:
                parts = row.split(",")
                if len(parts) >= 6:
                    prices.append(float(parts[4]))
                    volumes.append(float(parts[5]))

            return prices, volumes
        except Exception:
            return [], []

    # ---------- USA / EU → YAHOO ----------
    try:
        data = yf.download(symbol, period="1y", interval="1d", progress=False)
        if data.empty:
            return [], []

        prices = to_float_list(data["Close"].dropna().values)
        volumes = to_float_list(data["Volume"].dropna().values)
        return prices, volumes
    except Exception:
        return [], []


# =====================================================
# TELEGRAM – KOMENDY
# =====================================================
def handle_telegram_commands():
    global last_update_id

    try:
        updates = get_updates(last_update_id)
        if not updates:
            return

        for update in updates:
            last_update_id = update["update_id"] + 1
            text = update.get("message", {}).get("text", "").strip()

            print(f"[CMD] {text}")

            if text == "/status":
                msg = (
                    "🤖 <b>Status bota</b>\n\n"
                    f"🕒 Ostatni skan: {last_check_time}\n"
                    f"📈 Interwał danych: D1\n"
                    f"⏳ Cooldown: {COOLDOWN // 3600} h\n"
                    f"🌙 Cisza nocna: 00–06\n"
                    f"🧠 Storage: Redis\n"
                    f"📊 Liczba instrumentów: {len(INSTRUMENTS)}"
                )
                send_telegram_message(msg)

            elif text == "/help":
                send_telegram_message(
                    "📖 <b>Dostępne komendy</b>\n\n"
                    "/status – stan bota\n"
                    "/last – ostatnie sygnały\n"
                    "/help – pomoc\n\n"
                    "Bot analizuje rynek i wysyła sygnały kontekstowe."
                )

            elif text == "/last":
                last_signals = get_last_signals(limit_per_symbol=1, max_symbols=10)
                if not last_signals:
                    send_telegram_message("Brak zapisanych sygnałów.")
                else:
                    msg = "📡 <b>Ostatnie sygnały</b>\n\n"
                    for s in last_signals:
                        msg += (
                            f"<b>{s['symbol']}</b>\n"
                            f"{s['title']}\n"
                            f"Typ: {s['category']}\n"
                            f"Ryzyko: {s['risk']}\n"
                            f"{s['message']}\n\n"
                        )
                    send_telegram_message(msg)

    except Exception as e:
        print(f"❌ Błąd komend: {e}")


# =====================================================
# ANALIZA RYNKU
# =====================================================
def analyze_market():
    global last_check_time

    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    print(f"[{last_check_time}] ⏳ Skanowanie rynku...")

    for symbol in INSTRUMENTS:
        try:
            last_time = get_last_signal_time(symbol)
            if last_time and (now - last_time).total_seconds() < COOLDOWN:
                continue

            prices, volumes = get_market_data(symbol)
            if len(prices) < 50 or len(volumes) < 20:
                continue

            signals = detect_market_signals(
                prices,
                volumes,
                VOLATILITY_THRESHOLD,
                VOLUME_MULTIPLIER,
            )

            if not signals:
                continue

            if is_night_silence(now):
                continue

            weight = portfolio_context(symbol)
            relevance = (
                "Wysokie" if weight >= 0.3
                else "Normalne" if weight > 0
                else "Obserwowane"
            )

            msg = f"📡 <b>{symbol}</b>\nZnaczenie: {relevance}\n\n"

            for s in signals:
                msg += (
                    f"<b>{s['title']}</b>\n"
                    f"Typ: {s['category']}\n"
                    f"Ryzyko: {s['risk']}\n"
                    f"{s['message']}\n\n"
                )
                save_signal(symbol, s, now)

            send_telegram_message(msg)
            set_last_signal_time(symbol, now)

            time.sleep(1)

        except Exception as e:
            print(f"❌ Błąd {symbol}: {e}")


# =====================================================
# START
# =====================================================
if __name__ == "__main__":
    print("🚀 Bot uruchomiony (Redis)")
    while True:
        handle_telegram_commands()
        analyze_market()
        time.sleep(CHECK_INTERVAL)
