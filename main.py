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

def send_telegram_photo(photo_path):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    try:
        with open(photo_path, "rb") as photo:
            files = {"photo": photo}
            data = {"chat_id": chat_id}
            requests.post(url, data=data, files=files, timeout=10)
    except Exception as e:
        print(f"❌ Nie udało się wysłać zdjęcia: {e}")

# =====================================================
# REDIS – JEDYNE ŹRÓDŁO STANU
# =====================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_last_signal_time(symbol):
    ts = r.get(f"cooldown:{symbol}")
    return datetime.fromisoformat(ts) if ts else None


def set_last_signal_time(symbol, dt):
    r.set(f"cooldown:{symbol}", dt.isoformat())


def get_last_state(symbol):
    return r.get(f"last_state:{symbol}")


def set_last_state(symbol, state):
    r.set(f"last_state:{symbol}", state)


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

    # statystyki
    r.incr("stats:total")
    r.incr(f"stats:{signal['category']}")
    r.incr(f"stats:symbol:{symbol}")


# =====================================================
# PEŁNE NAZWY + RYNKI
# =====================================================
COMPANY_NAMES = {
    "NVDA": "NVIDIA Corporation",
    "MSFT": "Microsoft Corporation",
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
    "MCD": "McDonald's Corporation",
    "COST": "Costco Wholesale Corporation",
    "JPM": "JPMorgan Chase & Co.",
    "GS": "Goldman Sachs Group, Inc.",
    "LMT": "Lockheed Martin Corporation",
    "RTX": "RTX Corporation",
    "ASML": "ASML Holding N.V.",
    "SAP": "SAP SE",
    "PKO": "PKO Bank Polski",
    "PEO": "Bank Pekao S.A.",
    "PZU": "PZU S.A.",
    "ING": "ING Bank Śląski S.A.",
    "KGH": "KGHM Polska Miedź S.A.",
    "XTB": "XTB S.A.",
    "11B": "11 bit studios S.A.",
    "CDR": "CD Projekt S.A.",
}

GPW_SYMBOLS = {
    "PKO", "PEO", "PZU", "ING", "KGH",
    "XTB", "11B", "CDR", "ALE", "LPP",
    "DNP", "KTY", "ALR", "ENA", "PKN"
}

# Jawna lista Yahoo – **tylko to**
YAHOO_SYMBOLS = {
    "AAPL", "AMZN", "META", "MSFT", "NVDA",
    "TSLA", "MCD", "COST", "JPM", "GS",
    "LMT", "RTX", "XOM", "CVX", "VLO",
    "AMD", "INTC", "IBM", "ORCL",
    "ASML", "SAP", "TSM", "GLD",
    "SLV", "4GLD.DE"
}

ALL_SYMBOLS = sorted(set(INSTRUMENTS) | YAHOO_SYMBOLS)


# =====================================================
# USTAWIENIA CZASOWE
# =====================================================
SILENCE_START, SILENCE_END = 0, 6
COMMAND_CHECK_INTERVAL = 3        # sekundy
MARKET_ANALYSIS_INTERVAL = 300    # 5 minut

last_update_id = None
last_check_time = "Brak"
last_command_check = 0
last_market_check = 0


def is_night_silence(now):
    return SILENCE_START <= now.hour < SILENCE_END


# =====================================================
# DANE RYNKOWE
# =====================================================
def to_float_list(seq):
    out = []
    for x in seq:
        try:
            out.append(float(x[0]) if isinstance(x, (list, tuple, np.ndarray)) else float(x))
        except Exception:
            pass
    return out


def get_market_data(symbol):
    symbol = symbol.upper()

    # ===== USA / EU → YAHOO =====
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

    # ===== DOMYŚLNIE → STOOQ / GPW =====
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


# =====================================================
# KOMENDY TELEGRAM
# =====================================================
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
                f"🤖 Status bota\n\n"
                f"Ostatni skan: {last_check_time}\n"
                f"Spółek w radarze: {len(ALL_SYMBOLS)}"
            )

        elif text == "/stats":
            send_telegram_message(
                f"📊 Statystyki\n\n"
                f"Łącznie: {r.get('stats:total') or 0}\n"
                f"Trendowe: {r.get('stats:TREND_CONFIRMATION') or 0}\n"
                f"Kontrariańskie: {r.get('stats:CONTRARIAN') or 0}\n"
                f"Zmiana zachowania: {r.get('stats:BEHAVIOR_CHANGE') or 0}"
            )

        elif text == "/last":
            messages = []
            for symbol in ALL_SYMBOLS:
                items = r.lrange(f"signals:{symbol}", 0, 0)
                if items:
                    try:
                        messages.append(ast.literal_eval(items[0]))
                    except Exception:
                        pass

            if not messages:
                send_telegram_message("Brak zapisanych sygnałów.")
            else:
                messages.sort(key=lambda x: x["time"], reverse=True)
                msg = "📡 Ostatnie sygnały\n\n"
                for s in messages[:5]:
                    msg += (
                        f"{s['symbol']}\n"
                        f"{s['title']}\n"
                        f"Werdykt: {s['verdict']}\n\n"
                    )
                send_telegram_message(msg)

        elif text == "/papaji":
            send_telegram_photo("papaj.png")

        elif text == "/help":
            send_telegram_message(
                "/status – status bota\n"
                "/stats – statystyki\n"
                "/last – ostatnie sygnały\n"
                "/help – pomoc\n"
                "/papaj"
            )

# =====================================================
# ANALIZA RYNKU (ZMIANA STANU, NIE CZAS)
# =====================================================
def analyze_market():
    global last_check_time
    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%H:%M:%S")

    for symbol in ALL_SYMBOLS:
        prices, vols = get_market_data(symbol)
        if len(prices) < 50:
            continue

        signals = detect_market_signals(
            prices,
            vols,
            VOLATILITY_THRESHOLD,
            VOLUME_MULTIPLIER,
        )

        if not signals or is_night_silence(now):
            continue

        for s in signals:
            if s["category"] == "TREND_CONFIRMATION":
                verdict = "✅ KUPUJ"
            elif s["category"] == "CONTRARIAN":
                verdict = "❌ SPRZEDAJ / OMIJAJ"
            else:
                verdict = "⏸ TRZYMAJ / OBSERWUJ"

            current_state = f"{s['category']}|{verdict}"
            last_state = get_last_state(symbol)

            if current_state == last_state:
                continue  # brak zmiany → cisza

            # zapis nowego stanu
            set_last_state(symbol, current_state)

            company = COMPANY_NAMES.get(symbol, symbol)
            market = "Polska – GPW" if symbol in GPW_SYMBOLS else "USA / Europa"

            msg = (
                f"📡 {company} ({symbol})\n"
                f"Rynek: {market}\n\n"
                f"Sytuacja: {s['title']}\n"
                f"Werdykt: {verdict}\n\n"
                f"Typ: {s['category']}\n"
                f"Ryzyko: {s['risk']}\n\n"
                f"{s['message']}"
            )

            send_telegram_message(msg)
            save_signal(symbol, s, verdict, now)
            set_last_signal_time(symbol, now)
            time.sleep(1)


# =====================================================
# START – RESPONSYWNA PĘTLA
# =====================================================
if __name__ == "__main__":
    print("🚀 Bot uruchomiony (stabilny, responsywny)")

    while True:
        now_ts = time.time()

        if now_ts - last_command_check >= COMMAND_CHECK_INTERVAL:
            handle_telegram_commands()
            last_command_check = now_ts

        if now_ts - last_market_check >= MARKET_ANALYSIS_INTERVAL:
            analyze_market()
            last_market_check = now_ts

        time.sleep(1)
