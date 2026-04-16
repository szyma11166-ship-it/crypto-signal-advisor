import time
from datetime import datetime, timezone

from app.config import INSTRUMENT, MARKET_TYPE, VOLATILITY_THRESHOLD
from app.data_sources import get_market_history
from app.signals import (
    detect_volatility_signal,
    detect_volume_anomaly,
)
from app.notifier import send_telegram_message, get_updates
from app.state import get_last_signal_time, set_last_signal_time
from app.history import add_signal, get_last_signal


CHECK_INTERVAL = 3600   # 1h
COOLDOWN = 10800        # 3h

last_update_id = None
last_check_time = None


# -------- POMOCNICZE: KONTEKST PORTFELA (GRUPY) --------
def load_portfolio_groups():
    import json
    import os

    path = "app/portfolio.json"
    if not os.path.exists(path):
        return {}

    with open(path, "r") as f:
        return json.load(f).get("groups", {})


def portfolio_relevance_for_instrument(instrument: str):
    groups = load_portfolio_groups()
    total_weight = 0.0
    hit_groups = []

    for name, group in groups.items():
        if instrument in group.get("instruments", []):
            w = float(group.get("weight", 0))
            total_weight += w
            hit_groups.append((name, w))

    return total_weight, hit_groups


# -------- TELEGRAM COMMANDS --------
def handle_telegram_commands():
    global last_update_id

    updates = get_updates(last_update_id)
    for update in updates:
        last_update_id = update["update_id"] + 1

        message = update.get("message", {})
        text = message.get("text", "").strip()

        if text == "/status":
            response = (
                "🤖 Status bota\n\n"
                "✅ Działa\n"
                f"📊 Instrument: {INSTRUMENT}\n"
                f"🏷️ Rynek: {MARKET_TYPE}\n"
                f"⏱️ Interwał analizy: {CHECK_INTERVAL // 60} min\n"
                f"🔕 Cooldown alertów: {COOLDOWN // 3600} h\n"
            )

            if last_check_time:
                response += f"\n🕒 Ostatnia analiza: {last_check_time} UTC"

            send_telegram_message(response)

        elif text == "/help":
            response = (
                "ℹ️ Pomoc – bot sygnałów rynkowych\n\n"
                "Komendy:\n"
                "/status – status działania\n"
                "/last   – ostatni zapisany sygnał\n"
                "/help   – ta pomoc\n\n"
                "Bot analizuje rynek i odnosi sygnały\n"
                "do struktury Twojego portfela.\n"
                "Nie jest to rekomendacja inwestycyjna."
            )

            send_telegram_message(response)

        elif text == "/last":
            last = get_last_signal()
            if not last:
                send_telegram_message("❌ Brak zapisanych sygnałów.")
                return

            response = (
                "🕒 *Ostatni sygnał*\n\n"
                f"Instrument: `{last['instrument']}`\n"
                f"Rynek: `{last['market']}`\n"
                f"Czas: `{last['timestamp']}`\n\n"
            )

            for s in last["signals"]:
                response += (
                    f"• *{s['type']}* ({s['value']})\n"
                    f"  {s['message']}\n\n"
                )

            response += "_Dane archiwalne – bez rekomendacji._"
            send_telegram_message(response)


# -------- ANALIZA RYNKU --------
def analyze_market():
    global last_check_time

    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%Y-%m-%d %H:%M:%S")

    prices, volumes = get_market_history(INSTRUMENT)

    signals = []

    s1 = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)
    if s1:
        signals.append(s1)

    s2 = detect_volume_anomaly(volumes)
    if s2:
        signals.append(s2)

    if not signals:
        return

    last_signal_time = get_last_signal_time()
    if last_signal_time:
        diff = (now - last_signal_time).total_seconds()
        if diff < COOLDOWN:
            return

    weight, groups = portfolio_relevance_for_instrument(INSTRUMENT)

    if weight >= 0.4:
        relevance = "WYSOKIE"
    elif weight >= 0.2:
        relevance = "ŚREDNIE"
    elif weight > 0:
        relevance = "NISKIE"
    else:
        relevance = "BRAK"

    message = (
        "📡 *Sygnały rynkowe*\n\n"
        f"Instrument: `{INSTRUMENT}`\n"
        f"Rynek: `{MARKET_TYPE}`\n"
        f"Znaczenie dla portfela: *{relevance}* (~{int(weight*100)}%)\n\n"
    )

    if groups:
        message += "Dotyczy grup:\n"
        for g, w in groups:
            message += f"• {g} ({int(w*100)}%)\n"
        message += "\n"

    for s in signals:
        message += (
            f"• *{s['type']}* ({s['value']})\n"
            f"  {s['message']}\n\n"
        )

    message += "_Informacja analityczna – bez rekomendacji._"

    send_telegram_message(message)

    add_signal(INSTRUMENT, MARKET_TYPE, signals, now)
    set_last_signal_time(now)


# -------- LOOP --------
if __name__ == "__main__":
    while True:
        try:
            handle_telegram_commands()
            analyze_market()
        except Exception as e:
            print("Błąd:", e)

        time.sleep(30)
