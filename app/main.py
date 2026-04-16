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


CHECK_INTERVAL = 3600   # 1h
COOLDOWN = 10800        # 3h

last_update_id = None
last_check_time = None


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
                f"✅ Działa\n"
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
                "Dostępne komendy:\n"
                "/status – status bota i ostatnia analiza\n"
                "/help – ta pomoc\n\n"
                "Sygnały:\n"
                "• PODWYŻSZONA_ZMIENNOŚĆ – wzrost zmienności ceny\n"
                "• ANOMALIA_WOLUMENU – nietypowo wysoka aktywność rynku\n\n"
                "Bot dostarcza informacji analitycznych.\n"
                "Nie jest to rekomendacja inwestycyjna."
            )

            send_telegram_message(response)



def analyze_market():
    global last_check_time

    now = datetime.now(timezone.utc)
    last_check_time = now.strftime("%Y-%m-%d %H:%M:%S")

    prices, volumes = get_market_history(INSTRUMENT)

    signals = []

    vol_signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)
    if vol_signal:
        signals.append(vol_signal)

    volume_signal = detect_volume_anomaly(volumes)
    if volume_signal:
        signals.append(volume_signal)

    if not signals:
        return

    last_signal_time = get_last_signal_time()
    if last_signal_time:
        diff = (now - last_signal_time).total_seconds()
        if diff < COOLDOWN:
            return

    message = (
        "📡 *Sygnały rynkowe*\n\n"
        f"Instrument: `{INSTRUMENT}`\n"
        f"Rynek: `{MARKET_TYPE}`\n\n"
    )

    for s in signals:
        message += (
            f"• *{s['type']}* (wartość: `{s['value']}`)\n"
            f"  {s['message']}\n\n"
        )

    message += "_Informacja analityczna – bez rekomendacji._"

    send_telegram_message(message)
    set_last_signal_time(now)


if __name__ == "__main__":
    while True:
        try:
            handle_telegram_commands()
            analyze_market()
        except Exception as e:
            print("Błąd:", e)

        time.sleep(30)
