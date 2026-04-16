import json
import os
from datetime import datetime

STATE_FILE = "state.json"

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_last_signal_time(symbol):
    state = load_state()
    ts = state.get(f"last_ts_{symbol}")
    if ts:
        return datetime.fromisoformat(ts)
    return None

def set_last_signal_time(symbol, dt):
    state = load_state()
    state[f"last_ts_{symbol}"] = dt.isoformat()
    save_state(state)
