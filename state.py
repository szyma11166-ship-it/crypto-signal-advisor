import json
import os
from datetime import datetime, timezone

STATE_FILE = "state_cache.json"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"Błąd zapisu stanu: {e}")

def get_last_signal_time(symbol):
    state = load_state()
    last_time_str = state.get(symbol)
    if last_time_str:
        try:
            return datetime.fromisoformat(last_time_str).replace(tzinfo=timezone.utc)
        except:
            return None
    return None

def set_last_signal_time(symbol, dt):
    state = load_state()
    state[symbol] = dt.isoformat()
    save_state(state)
