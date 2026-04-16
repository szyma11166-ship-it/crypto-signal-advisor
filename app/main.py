import time
from datetime import datetime

from app.config import SYMBOL, VOLATILITY_THRESHOLD
from app.data_sources import get_price_history
from app.signals import detect_volatility_signal
from app.notifier import send_telegram_message

CHECK_INTERVAL = 3600
COOLDOWN = 10800

last_signal_time = None


def analyze_market():
    global last_signal_time

    prices = get_price_history(SYMBOL)
    signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)

    if signal is None:
        return

    now = datetime.utcnow()

    if last_signal_time is not None:
        diff = (now - last_signal_time).total_seconds()
        if diff < COOLDOWN:
            return

    text = (
        "📡 Sygnał rynkowy\n\n"
        f"Instrument: {SYMBOL}\n"
        f"Typ: {signal['type']}\n"
        f"Wartość: {signal['value']}\n\n"
        f"{signal['message']}\n\n"
        "Informacja analityczna – bez rekomendacji."
    )

    send_telegram_message(text)
    last_signal_time = now


if __name__ == "__main__":
    while True:
        try:
            analyze_market()
        except Exception as e:
            print("Błąd:", e)

        time.sleep(CHECK_INTERVAL)
