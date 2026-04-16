
import time
from datetime import datetime

from app.config import SYMBOL, VOLATILITY_THRESHOLD
from app.data_sources import get_price_history
from app.signals import detect_volatility_signal
from app.notifier import send_telegram_message

CHECK_INTERVAL = 60 * 60      # co ile sprawdzamy (1h)
COOLDOWN = 3 * 60 * 60        # minimalny odstęp między alertami (3h)

last_signal_time = None


def analyze_market():
    global last_signal_time

    prices = get_price_history(SYMBOL)
    signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)

    if not signal:
        return

    now = datetime.utcnow()

    # cooldown – żeby nie spamować
    if last_signal_time:
        delta = (now - last_signal_time).total_seconds()
        if delta < COOLDOWN:
            return

    message = (
        f"📡 *Sygnał rynkowy*\n\n"
        f"Instrument: `{SYMBOL}`\n"
        f"Typ: *{signal['type']}*\n"
        f"Wartość: `{signal['value']}`\n\n"
        f"{signal['message']}\n\n"
        f"_Informacja analityczna – bez rekomendacji._"
    )

    send_telegram_message(message)
    last_signal_time = now


if __name__ == "__main__":
    while True:
        try:
            analyze_market()
        except Exception as e:
            print("Błąd analizy:", e)

        time.sleep(CHECK_INTERVAL)
``
