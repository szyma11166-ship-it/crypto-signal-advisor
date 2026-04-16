import time
from datetime import datetime

from app.config import INSTRUMENT, MARKET_TYPE, VOLATILITY_THRESHOLD
from app.data_sources import get_price_history
from app.signals import detect_volatility_signal
from app.notifier import send_telegram_message, get_updates
from app.state import get_last_signal_time, set_last_signal_time

CHECK_INTERVAL = 3600
COOLDOWN = 10800

last_update_id = None
last_check_time = None


def handle_telegram_commands():
    global last_update_id

    updates = get_updates(last_update_id)
    for update in updates:
        last_update_id = update["update_id"] + 1

        message = update.get("message", {})
        text = message.get("text", "")

        if text.strip() == "/status":
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


def analyze_market():
    global last_check_time

    last_check_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    prices = get_price_history(INSTRUMENT)
    signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)

    if signal is None:
        return

    now = datetime.utcnow()
    last_signal_time = get_last_signal_time()

    if last_signal_time:
        diff = (now - last_signal_time).total_seconds()
        if diff < COOLDOWN:
            return

    message = (
        "📡 Sygnał rynkowy\n\n"
        f"Instrument: {INSTRUMENT}\n"
        f"Rynek: {MARKET_TYPE}\n"
        f"Typ: {signal['type']}\n"
        f"Wartość: {signal['value']}\n\n"
        f"{signal['message']}\n\n"
        "Informacja analityczna – bez rekomendacji."
    )

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
