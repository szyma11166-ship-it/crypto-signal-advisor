import time
from datetime import datetime, timezone

import requests
import yfinance as yf

from app.config import INSTRUMENT, VOLATILITY_THRESHOLD
from app.signals import detect_volatility_signal, detect_volume_anomaly
from app.notifier import send_telegram_message, get_updates
from app.state import get_last_signal_time, set_last_signal_time
from app.history import add_signal, get_last_signal


# ================== KONFIGURACJA ==================
CHECK_INTERVAL = 3600          # 1 godzina
COOLDOWN = 10800               # 3 godziny
SILENCE_START = 0              # 00:00
SILENCE_END = 6                # 06:00

last_update_id = None
last_check_time = None


# ================== CISZA NOCNA ==================
def is_night_silence(now: datetime) -> bool:
    return SILENCE_START <= now.hour < SILENCE_END


# ================== PORTFEL GRUPOWY ==================
def load_portfolio_groups():
    import json, os
    path = "app/portfolio.json"
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f).get("groups", {})


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


# ================== DANE RYNKOWE ==================
def get_market_data(symbol: str):
    # Polska – Stooq (daily)
    if symbol.upper() in ["PKO", "PEO", "MBK", "ING", "PZU", "SANTANDER"]:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        r = requests.get(url)
        lines = r.text.splitlines()[1:]

        prices, volumes = [], []
        for row in lines[-100:]:
            parts = row.split(",")
            prices.append(float(parts[4]))
            volumes.append(float(parts[5]))

        return prices, volumes

    # USA / global – Yahoo Finance (1h)
    data = yf.download(symbol, period="7d", interval="1h", progress=False)

    prices = data["Close"].dropna().values.tolist()
    volumes = data["Volume"].dropna().values.tolist()

    return prices, volumes


# ================== TELEGRAM ==================
def handle_telegram_commands():
    global last_update_id

    updates = get_updates(last_update_id)
    for update in updates:
        last_update_id = update["update_id"] + 1
        text = update.get("message", {}).get("text", "").strip()

        if text == "/status":
            msg = (
                "🤖 **Status bota**\n\n"
                "✅ Działa\n"
                f"📊 Instrument: {INSTRUMENT}\n"
                "🏷️ Rynek: Akcje\n"
                "⏱️ Interwał analizy: 60 minut\n"
                "🔕 Cooldown alertów: 3 godziny\n"
                "🌙 Cisza nocna: 00:00–06:00\n"
            )
            if last_check_time:
                msg += f"\n🕒 Ostatnia analiza: {last_check_time} UTC"

            send_telegram_message(msg)

        elif text == "/help":
            send_telegram_message(
                "ℹ️ **Pomoc**\n\n"
                "/status – status działania bota\n"
                "/last – ostatni zapisany sygnał\n"
                "/help – ta pomoc\n\n"
                "Bot analizuje realne ceny akcji (Yahoo + Stooq)\n"
                "i ocenia ich znaczenie dla Twojego portfela.\n"
                "Nie generuje rekomendacji inwestycyjnych."
            )

        elif text == "/last":
            last = get_last_signal()
            if not last:
                send_telegram_message("❌ Brak zapisanych sygnałów.")
                return

            msg = (
                "🕒 **Ostatni sygnał**\n\n"
                f"Instrument: {last['instrument']}\n"
                f"Czas: {last['timestamp']}\n\n"
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

    v_signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)
    vol_signal = detect_volume_anomaly(volumes)

    if v_signal:
        signals.append(v_signal)
    if vol_signal:
        signals.append(vol_signal)

    if not signals:
        return

    last_signal_time = get_last_signal_time()
    if last_signal_time:
        if (now - last_signal_time).total_seconds() < COOLDOWN:
            return

    if is_night_silence(now):
        return

    weight, groups = portfolio_context(INSTRUMENT)

    if weight >= 0.4:
        relevance = "Wysokie znaczenie"
    elif weight >= 0.2:
        relevance = "Średnie znaczenie"
    elif weight > 0:
        relevance = "Niskie znaczenie"
    else:
        relevance = "Brak znaczenia"

    msg = (
        f"📡 **Sygnały rynkowe**\n\n"
        f"Instrument: {INSTRUMENT}\n"
        f"Znaczenie dla portfela: {relevance} (~{int(weight*100)}%)\n\n"
    )

    if groups:
        msg += "Dotyczy grup:\n"
        for g, w in groups:
            msg += f"• {g} ({w}%)\n"
        msg += "\n"

    for s in signals:
        msg += f"• {s['type']} ({s['value']})\n{s['message']}\n\n"

    send_telegram_message(msg)

    add_signal(INSTRUMENT, "akcje", signals, now)
    set_last_signal_time(now)


# ================== PĘTLA ==================
if __name__ == "__main__":
    while True:
        try:
            handle_telegram_commands()
            analyze_market()
        except Exception as e:
            print("Błąd:", e)

        time.sleep(30)
