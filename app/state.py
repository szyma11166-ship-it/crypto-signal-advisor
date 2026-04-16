import json
import os
from datetime import datetime

STATE_FILE = "state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_last_signal_time():
    state = load_state()
    ts = state.get("last_signal_time")
    if ts:
        return datetime.fromisoformat(ts)
    return None


def set_last_signal_time(dt: datetime):
    state = load_state()
    state["last_signal_time"] = dt.isoformat()
    save_state(state)
