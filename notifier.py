import os
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(text: str, chat_id=None):
    # Najpierw spróbuj wziąć token z os.getenv (Railway go tam trzyma)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if chat_id is None:
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print(f"❌ Brak danych do wysyłki: token={bool(token)}, chat={bool(chat_id)}")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Telegram error: {e}")


def get_updates(offset=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return []
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 10, "offset": offset}
    
    try:
        response = requests.get(url, params=params, timeout=15)
        # To jest kluczowe: jeśli nie 200 OK, rzuci błąd, który zaraz złapiemy
        response.raise_for_status() 
        return response.json().get("result", [])
    except Exception as e:
        # Zamiast wywalać bota, tylko logujemy błąd i zwracamy pustą listę
        print(f"⚠️ Telegram API Connection Error: {e}")
        return []
    