import json
import os
from datetime import datetime

HISTORY_FILE = "signal_history.json"
MAX_ENTRIES = 50


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []

    with open(HISTORY_FILE, "r") as f:
        return json.load(f)


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


def add_signal(instrument, market, signals, timestamp):
    history = load_history()

    entry = {
        "timestamp": timestamp.isoformat(),
        "instrument": instrument,
        "market": market,
        "signals": signals,
    }

    history.insert(0, entry)
    history = history[:MAX_ENTRIES]

    save_history(history)


def get_last_signal():
    history = load_history()
    if history:
        return history[0]
    return None