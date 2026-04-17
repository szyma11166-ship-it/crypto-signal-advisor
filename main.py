import time
from datetime import datetime, timezone
import requests
import yfinance as yf
import numpy as np

from config import INSTRUMENTS, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER, COOLDOWN
from signals import detect_market_signals
from notifier import send_telegram_message, get_updates
from state import get_last_signal_time, set_last_signal_time

SILENCE_START, SILENCE_END = 0, 6
last_update_id = None
last_check_time = "Brak"


def is_night_silence(now: datetime) -> bool:
    return SILENCE_START <= now.hour < SILENCE_END


def portfolio_context(symbol: str) -> float:
    import json, os
    if not os.path.exists("portfolio.json"):
        return 0.0
    try:
        with open("portfolio.json", "r") as f:
            groups = json.load(f).get("groups", {})
            return sum(
                float(g.get("weight", 0))
                for g in groups.values()
                if symbol in g.get("instruments", [])
            )
    except Exception:
        return 0.0


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
    gpw = ["PKO", "PEO", "PZU", "ING", "KGH", "ALE", "LPP", "CDR"]

    if symbol in gpw:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        try:
            r = requests.get(url, timeout=10)
            lines = r.text.splitlines()[1:]
            prices, volumes = [], []
            for row in lines[-300:]:
                parts = row.split(",")
                if len(parts) >= 6:
                    prices.append(float(parts[4]))
                    volumes.append(float(parts[5]))
            return prices, volumes
        except Exception:
            return [], []

    try:
        data = yf.download(symbol, period="1y", interval="1d", progress=False)
        if data.empty:
            return [], []
        return (
            to_float_list(data["Close"].dropna().values),
            to_float_list(data["Volume"].dropna().values),
        )
    except Exception:
        return [], []


def handle_telegram_commands():
    global last_update_id
    try:
        updates = get_updates(last_update_id)
        for update in updates or []:
            last_update_id = update["update_id"] + 1
            text = update.get("message", {}).get("text", "")
            if text == "/status":
                send_telegram_message(
                    f"🤖 Bot online\n"
                    f"🕒 Ostatni skan: {last_check_time}\n"
                    f"⏳ Cooldown: {COOLDOWN // 3600}h"
                )
    except Exception:
        pass


def analyze_market():
    global last_check_time
    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    print(f"[{last_check_time}] Skanowanie rynku...")

    for symbol in INSTRUMENTS:
        # ⛔ NIE zagnieżdżamy try w try
        # ⛔ Jeden try = jeden except
        try:
            last_time = get_last_signal_time(symbol)
            if last_time and (now - last_time).total_seconds() < COOLDOWN:
                continue

            prices, volumes = get_market_data(symbol)
            if len(prices) < 50:
                continue

            signals = detect_market_signals(
                prices, volumes,
                VOLATILITY_THRESHOLD,
                VOLUME_MULTIPLIER
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

            msg = f"📡 <b>{symbol}</b>\nStatus: {relevance}\n\n"
            for s in signals:
                msg += (
                    f"<b>{s['title']}</b>\n"
                    f"Typ: {s['category']}\n"
                    f"Ryzyko: {s['risk']}\n"
                    f"{s['message']}\n\n"
                )

            send_telegram_message(msg)
            set_last_signal_time(symbol, now)
            time.sleep(1)

        except Exception as e:
            print(f"❌ Błąd dla {symbol}: {e}"))
     time.sleep(300)
