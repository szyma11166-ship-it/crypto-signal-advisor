
from app.config import SYMBOL, VOLATILITY_THRESHOLD
from app.data_sources import get_price_history
from app.signals import detect_volatility_signal
from app.notifier import send_telegram_message

def run():
    prices = get_price_history(SYMBOL)
    signal = detect_volatility_signal(prices, VOLATILITY_THRESHOLD)

    if signal:
        send_telegram_message(
            f"📡 *Sygnał rynkowy*\n\n"
            f"Instrument: `{SYMBOL}`\n"
            f"Typ: *{signal['type']}*\n"
            f"Wartość: `{signal['value']}`\n\n"
            f"{signal['message']}\n\n"
            f"_Informacja analityczna – bez rekomendacji._"
        )

if __name__ == "__main__":
    run()
