import os
import time
import ast
import re
from datetime import datetime
from zoneinfo import ZoneInfo

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
# STREFA CZASOWA
# =====================================================
os.environ["TZ"] = "Europe/Warsaw"
if hasattr(time, "tzset"):
    time.tzset()
PL_TZ = ZoneInfo("Europe/Warsaw")


# =====================================================
# TELEGRAM – USUWANIE WEBHOOKA (ANTI-409)
# =====================================================
def ensure_no_webhook():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("⚠️ Brak TELEGRAM_BOT_TOKEN – pomijam deleteWebhook")
        return
    url = f"https://api.telegram.org/bot{token}/deleteWebhook"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        print(f"🔧 deleteWebhook: {data.get('description', 'OK')}")
    except Exception as e:
        print(f"⚠️ deleteWebhook error: {e}")


# =====================================================
# REDIS
# =====================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_last_signal_time(symbol):
    ts = r.get(f"cooldown:{symbol}")
    return datetime.fromisoformat(ts).replace(tzinfo=PL_TZ) if ts else None


def set_last_signal_time(symbol, dt):
    r.set(f"cooldown:{symbol}", dt.isoformat())


def get_last_state(symbol):
    raw = r.get(f"last_state:{symbol}")
    if not raw:
        return None
    try:
        return ast.literal_eval(raw)
    except Exception:
        return None


def set_last_state(symbol, category, verdict, value):
    now = datetime.now(PL_TZ)
    entry = {
        "date": now.date().isoformat(),
        "datetime": now.isoformat(),
        "category": category,
        "verdict": verdict,
        "value": round(value, 1) if value is not None else None,
    }
    r.set(f"last_state:{symbol}", str(entry))


def extract_signal_value(signal):
    m = re.search(r"(\d+(?:\.\d+)?)", signal.get("message", ""))
    return float(m.group(1)) if m else None


def is_significant_change(signal, last_state):
    if last_state is None:
        # Brak baseline’u po hydracji -> NIE traktujemy tego jako zmianę
        return False
    if signal["category"] != last_state.get("category"):
        return True
    new_val = extract_signal_value(signal)
    old_val = last_state.get("value")
    if new_val is None or old_val is None:
        return False
    return abs(new_val - old_val) >= 10.0


def is_weekend(now):
    return now.weekday() >= 5


def is_night(now):
    return 0 <= now.hour < 6


def should_send(now):
    return not is_weekend(now) and not is_night(now)


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


# =====================================================
# RYNKI
# =====================================================
GPW_SYMBOLS = {
    "PKO", "PEO", "PZU", "ING", "MBK", "ALR", "PKN",
    "KGH", "PGE", "ENA", "TPE", "CDR", "11B", "PLW",
    "TEN", "LPP", "DNP", "CCC", "ALE", "VRG", "XTB",
    "KTY", "ACP", "BDX", "OPL", "GPW", "SNT", "PHT", "SN2",
}

YAHOO_SYMBOLS = {
    "AAPL", "AMZN", "META", "MSFT", "NVDA", "GOOGL",
    "AMD", "INTC", "IBM", "ORCL", "TSM", "SMCI", "TSLA",
    "PLTR", "NVO", "SOFI", "HOOD", "LMT", "RTX", "BA",
    "CAT", "DE", "MCD", "COST", "WMT", "PG", "JPM", "GS",
    "BAC", "MS", "XOM", "CVX", "VLO",
    "ASML", "SAP", "NESN.SW", "RHM.DE", "AIR.PA",
    "4GLD.DE", "GLD", "SLV", "USO", "CPER", "URA",
}

ALL_SYMBOLS = sorted(set(INSTRUMENTS) | YAHOO_SYMBOLS)


# =====================================================
# DANE RYNKOWE
# =====================================================
def to_float_list(arr):
    out = []
    for x in arr:
        try:
            out.append(float(x[0]) if isinstance(x, (list, tuple, np.ndarray)) else float(x))
        except Exception:
            pass
    return out


def get_market_data(symbol):
    symbol = symbol.upper()
    if symbol in YAHOO_SYMBOLS:
        try:
            data = yf.download(symbol, period="1y", interval="1d", progress=False)
            if data.empty:
                return [], []
            return to_float_list(data["Close"].values), to_float_list(data["Volume"].values)
        except Exception:
            return [], []

    try:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return [], []
        lines = resp.text.splitlines()[1:]
        prices, vols = [], []
        for row in lines[-300:]:
            parts = row.split(",")
            if len(parts) >= 6:
                prices.append(float(parts[4]))
                vols.append(float(parts[5]))
        return prices, vols
    except Exception:
        return [], []


# =====================================================
# EXPLAINABILITY (/why)
# =====================================================
def explain_symbol_state(symbol, now):
    prices, vols = get_market_data(symbol)
    if len(prices) < 50:
        return "❌ Brak wystarczających danych (<50 sesji)"

    signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
    if not signals:
        return "⏸ Brak sygnałów technicznych"

    last_state = get_last_state(symbol)
    reasons = []

    for s in signals:
        if last_state is None:
            reasons.append("🛑 Hydratacja Redis – brak baseline’u")
            continue
        if not is_significant_change(s, last_state):
            reasons.append("🛑 Brak istotnej zmiany (ta sama kategoria / <10 pp)")
            continue
        if not should_send(now):
            reasons.append("🛑 Weekend lub cisza nocna")
            continue
        if is_on_cooldown(symbol, now):
            lt = get_last_signal_time(symbol)
            reasons.append(f"🛑 Cooldown (ostatni alert: {lt.strftime('%H:%M') if lt else 'brak'})")
            continue
        reasons.append("✅ Wszystkie warunki spełnione – alert byłby wysłany")

    return "\n".join(reasons) if reasons else "ℹ️ Brak jednoznacznego powodu"


# =====================================================
# KOMENDY TELEGRAM
# =====================================================
last_update_id = None

def handle_telegram_commands():
    global last_update_id
    updates = get_updates(last_update_id)
    if not updates:
        return

    for upd in updates:
        last_update_id = upd["update_id"] + 1
        text = upd.get("message", {}).get("text", "").strip().split("@")[0]
        now = datetime.now(PL_TZ)

        if text.startswith("/why"):
            parts = text.split()
            if len(parts) != 2:
                send_telegram_message("Użycie: /why SYMBOL")
                continue
            symbol = parts[1].upper()
            explanation = explain_symbol_state(symbol, now)
            send_telegram_message(f"🔍 WHY {symbol}\n\n{explanation}")

        elif text == "/debug":
            with_signal = blocked_change = blocked_time = blocked_cooldown = 0
            for sym in ALL_SYMBOLS:
                prices, vols = get_market_data(sym)
                if len(prices) < 50:
                    continue
                signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
                if not signals:
                    continue
                with_signal += 1
                last_state = get_last_state(sym)
                for s in signals:
                    if last_state and not is_significant_change(s, last_state):
                        blocked_change += 1
                    elif not should_send(now):
                        blocked_time += 1
                    elif is_on_cooldown(sym, now):
                        blocked_cooldown += 1

            send_telegram_message(
                "🛠 DEBUG\n\n"
                f"Spółek: {len(ALL_SYMBOLS)}\n"
                f"Z sygnałem: {with_signal}\n\n"
                f"🛑 Blokady:\n"
                f"- brak zmiany: {blocked_change}\n"
                f"- weekend/cisza: {blocked_time}\n"
                f"- cooldown: {blocked_cooldown}"
            )

        elif text == "/stats":
            send_telegram_message(
                "📊 Statystyki\n"
                f"Łącznie: {int(r.get('stats:total') or 0)}\n"
                f"Trendowe: {int(r.get('stats:TREND_CONFIRMATION') or 0)}\n"
                f"Kontrariańskie: {int(r.get('stats:CONTRARIAN') or 0)}\n"
                f"Zmiana zachowania: {int(r.get('stats:BEHAVIOR_CHANGE') or 0)}"
            )


# =====================================================
# ANALIZA RYNKU
# =====================================================
IS_FIRST_RUN = True

def analyze_market():
    global IS_FIRST_RUN
    now = datetime.now(PL_TZ)
    send_alerts = (not IS_FIRST_RUN) and should_send(now)

    for symbol in ALL_SYMBOLS:
        prices, vols = get_market_data(symbol)
        if len(prices) < 50:
            continue

        signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
        if not signals:
            continue

        last_state = get_last_state(symbol)

        for s in signals:
            verdict = (
                "✅ KUPUJ" if s["category"] == "TREND_CONFIRMATION"
                else "❌ SPRZEDAJ / OMIJAJ" if s["category"] == "CONTRARIAN"
                else "⏸ OBSERWUJ"
            )

            value = extract_signal_value(s)

            # ✅ NAJPIERW ZMIANA
            if not is_significant_change(s, last_state):
                continue

            # ✅ ZAWSZE zapisuj nowy stan
            set_last_state(symbol, s["category"], verdict, value)

            if not send_alerts:
                continue
            if is_on_cooldown(symbol, now):
                continue

            msg = (
                f"{symbol}\n"
                f"Sytuacja: {s['title']}\n"
                f"Werdykt: {verdict}\n"
                f"{s['message']}"
            )

            send_telegram_message(msg)
            save_signal(symbol, s, verdict, now)
            set_last_signal_time(symbol, now)
            time.sleep(1)

    IS_FIRST_RUN = False


# =====================================================
# PĘTLA GŁÓWNA
# =====================================================
COMMAND_CHECK_INTERVAL = 3
MARKET_ANALYSIS_INTERVAL = 300

last_command_check = 0
last_market_check = 0

if __name__ == "__main__":
    ensure_no_webhook()
    print("🚀 Bot uruchomiony | tryb stabilny")

    while True:
        now_ts = time.time()

        if now_ts - last_command_check >= COMMAND_CHECK_INTERVAL:
            handle_telegram_commands()
            last_command_check = now_ts

        if now_ts - last_market_check >= MARKET_ANALYSIS_INTERVAL:
            analyze_market()
            last_market_check = time.time()

        time.sleep(1)
