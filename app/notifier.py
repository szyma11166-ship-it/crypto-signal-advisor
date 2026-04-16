import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(text: str):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()


def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 1}
    if offset:
        params["offset"] = offset

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()["result"]
