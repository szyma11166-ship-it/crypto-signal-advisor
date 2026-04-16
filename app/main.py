import time
from datetime import datetime, timezone

from app.config import INSTRUMENT, MARKET_TYPE, VOLATILITY_THRESHOLD
from app.signals import detect_volatility_signal, detect_volume_anomaly
from app.notifier import send_telegram_message, get_updates
from app.state import get_last_signal_time, set_last_signal_time
from app.history import add_signal, get_last_signal

import yfinance as yf
import requests


# ================== KONFIG ==================
CHECK_INTERVAL = 3600         # 1h
COOLDOWN = 10800              # 3h
NIGHT_SILENCE_START = 0       # 00:00
NIGHT_SILENCE_END = 6         # 06:00

last_update_id = None
last_check_time = None


# ================== PORTFEL GRUPOWY ==================
def load_portfolio_groups():
    import json, os
    path = "app/portfolio.json"
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f).get("groups", {})


def portfolio_context(instrument):
    groups = load_portfolio_groups()
    weight = 0.0
    hits = []

    for name, grp in groups.items():
        if instrument in grp.get("instruments", []):
            w = grp.get("weight", 0)
            weight += w
            hits.append((name, w))

    return weight, hits


# ================== CISZA NOCNA ==================
def is_night_silence(now):
    hour = now.hour
    return NIGHT_SILENCE_START <= hour < NIGHT_SILENCE_END


# ================== DANE RYNKOWE ==================
def get_market_data(symbol):
    # Polska -> Stooq (daily)
    if symbol.isupper() and len(symbol) <= 4 and symbol not in ["AAPL", "TSLA", "NVDA", "MCD"]:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        r = requests.get(url)
        lines = r.text.splitlines()[1:]
        prices = []
        volumes = []

        for l in lines[-100:]:
            parts = l.split(",")
            prices.append(float(parts[4]))
            volumes.append(float(parts[5]))

        return prices, volumes

    # Reszta -> Yahoo Finance
    data = yf.download(symbol, period="7d", interval="1h", progress=False)
    prices = data["Close"].dropna().tolist()
    volumes = data["Volume"].dropna().tolist()
    return prices, volumes


# ================== TELEGRAM ==================
def handle_telegram_commands():
    global last_update_id

    updates = get_updates(last_update_id)
    for update in updates:
        last_update_id = update["update_id"] + 1
        txt = update.get("message", {}).get("text", "").strip()

        if txt == "/status":
            msg = (
                "🤖 Status bota\n\n"
                "✅ Działa\n"
                f"📊 Instrument: {INSTRUMENT}\n"
                f"🏷️ Rynek: {MARKET_TYPE}\n"
                f"⏱️ Interwał analizy: 60 min\n"
                f"🔕 Cooldown alertów: 3 h\n"
            )
            if last_check_time:
                msg += f"\n🕒 Ostatnia analiza: {last_check_time} UTC"
            send_telegram_message(msg)

        elif txt == "/help":
            send_telegram_message(
                "ℹ️ Pomoc\n\n"
                "/status – status pracy bota\n"
                "/last – ostatni zapisany sygnał\n"
                "/help – pomoc\n\n"
                "Cisza nocna: 00:00–06:00\n"
                "Źródła danych: Yahoo Finance + Stooq\n"
            )

        elif txt == "/last":
            last = get_last_signal()
            if not last:
                send_telegram_message("❌ Brak zapisanych sygnałów.")
                return

            msg = (
                "🕒 Ostatni sygnał\n\n"
                f"{last['instrument']} | {last['timestamp']}\n\n"
            )
            for s in last["signals"]:
                msg += f"• {s['type']} ({s['value']})\n{s['message']}\n\n"

            send_telegram_message(msg)


# ================== ANALIZA ==================
def analyze_market():
    global last_check_time

    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%Y-%m-%d %H:%M:%S")

    prices, volumes = get_market_data(INSTRUMENT)

    signals = []
    s1 = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)
    s2 = detect_volume_anomaly(volumes)

    if s1:
        signals.append(s1)
    if s2:
        signals.append(s2)

    if not signals:
        return

    last_signal_time = get_last_signal_time()
    if last_signal_time:
        if (now - last_signal_time).total_seconds() < COOLDOWN:
            return

    weight, groups = portfolio_context(INSTRUMENT)

    if is_night_silence(now):
        return

    msg = (
        f"📡 Sygnały rynkowe\n\n"
        f"Instrument: {INSTRUMENT}\n"
        f"Znaczenie portfela: ~{int(weight*100)}%\n\n"
    )

    if groups:
        msg += "Dotyczy grup:\n"
        for g, w in groups:
            msg += f"• {g} ({int(w*100)}%)\n"
        msg += "\n"

    for s in signals:
        msg += f"• {s['type']} ({s['value']})\n{s['message']}\n\n"

    send_telegram_message(msg)

    add_signal(INSTRUMENT, MARKET_TYPE, signals, now)
    set_last_signal_time(now)


# ================== LOOP ==================
if __name__ == "__main__":
    while True:
        try:
            handle_telegram_commands()
            analyze_market()
        except Exception as e:
            print("Błąd:", e)

        time.sleep(30)
