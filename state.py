import redis
import os
from datetime import datetime, timezone

# Railway automatycznie podaje zmienną REDIS_URL lub REDIS_PUBLIC_URL
# Jeśli Twoja zmienna nazywa się inaczej, zmień nazwę w os.getenv
REDIS_URL = os.getenv("REDIS_URL")

# Łączymy się z bazą
try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    print("✅ Połączono z Redisem")
except Exception as e:
    print(f"❌ Błąd połączenia z Redisem: {e}")
    r = None

def get_last_signal_time(symbol):
    if r is None: return None
    
    last_time_str = r.get(f"alert:{symbol}")
    if last_time_str:
        try:
            return datetime.fromisoformat(last_time_str).replace(tzinfo=timezone.utc)
        except:
            return None
    return None

def set_last_signal_time(symbol, dt):
    if r is None: return
    
    # Zapisujemy timestamp do Redisa
    # Możemy też ustawić automatyczne wygasanie klucza (TTL), 
    # ale zostawmy to w logice bota dla pełnej kontroli.
    r.set(f"alert:{symbol}", dt.isoformat())