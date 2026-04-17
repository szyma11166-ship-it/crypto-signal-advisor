import os
import redis
from datetime import datetime

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

r = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True  # stringi zamiast bytes
)


# ===================== COOLDOWNS =====================
def get_last_signal_time(symbol: str):
    ts = r.get(f"cooldown:{symbol}")
    if not ts:
        return None
    return datetime.fromisoformat(ts)


def set_last_signal_time(symbol: str, dt: datetime):
    r.set(f"cooldown:{symbol}", dt.isoformat())


# ===================== SYGNAŁY =====================
def save_signal(symbol: str, signal: dict, dt: datetime, max_items=100):
    key = f"signals:{symbol}"

    entry = {
        "time": dt.isoformat(),
        "category": signal["category"],
        "title": signal["title"],
        "risk": signal["risk"],
        "message": signal["message"],
    }

    # LPUSH → najnowsze na początku
    r.lpush(key, str(entry))
    # przycinamy listę
    r.ltrim(key, 0, max_items - 1)


def get_last_signals(symbol: str, limit=5):
    key = f"signals:{symbol}"
    items = r.lrange(key, 0, limit - 1)
    return items


# ===================== STATYSTYKI (opcjonalne) =====================
def increment_signal_counter(symbol: str, category: str):
    r.incr(f"stats:{symbol}:{category}")
