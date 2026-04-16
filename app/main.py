import time
from datetime import datetime

from app.config import SYMBOL, VOLATILITY_THRESHOLD
from app.data_sources import get_price_history
from app.signals import detect_volatility_signal
from app.notifier import send_telegram_message
from app.state import get_last_signal_time, set_last_signal_time


CHECK_INTERVAL = 3600      # co ile sprawdzamy rynek (sekundy) -> 1 godzina
COOLDOWN = 10800           # minimalny odstęp między alertami -> 3 godziny


def analyze_market():
    prices = get_price_history(SYMBOL)
    signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)

    if signal is None:
        return

    now = datetime.utcnow()
    last_time = get_last_signal_time()

    # cooldown – nie spamujemy
    if last_time is not None:
        diff = (now - last_time).total_seconds()
        if diff < COOLDOWN:
            return

    message = (
        "📡 Sygnał rynkowy\n\n"
        f"Instrument: {SYMBOL}\n"
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
            analyze_market()
        except Exception as error:
            print("Błąd analizy:", error)

        time.sleep(CHECK_INTERVAL)
