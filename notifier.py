import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(text: str, chat_id=None):
    url = f"{BASE_URL}/sendMessage"

    # jeśli nie podano chat_id → użyj domyślnego (np. kanał)
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Telegram error: {e}")


def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 1}

    if offset:
        params["offset"] = offset

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()["result"]