import time
from datetime import datetime

from app.config import INSTRUMENT, MARKET_TYPE, VOLATILITY_THRESHOLD
from app.data_sources import get_price_history
from app.signals import detect_volatility_signal
from app.notifier import send_telegram_message
from app.state import get_last_signal_time, set_last_signal_time


CHECK_INTERVAL = 3600      # 1 godzina
COOLDOWN = 10800           # 3 godziny


def analyze_market():
    prices = get_price_history(INSTRUMENT)
    signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)

    if signal is None:
        return

    now = datetime.utcnow()
    last_time = get_last_signal_time()

    if last_time is not None:
        diff = (now - last_time).total_seconds()
        if diff < COOLDOWN:
            return

    message = (
        "📡 Sygnał rynkowy\n\n"
        f"Instrument: {INSTRUMENT}\n"
        f"Rynek: {MARKET_TYPE}\n"
        f"Typ sygnału: {signal['type']}\n"
        f"Wartość: {signal['value']}\n\n"
        f"{signal['message']}\n\n"
        "Informacja analityczna – nie stanowi rekomendacji."
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
