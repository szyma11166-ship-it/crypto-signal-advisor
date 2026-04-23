import os
import time
import ast
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import yfinance as yf
import numpy as np
import redis

from config import (
    INSTRUMENTS,
    VOLATILITY_THRESHOLD,
    VOLUME_MULTIPLIER,
    COOLDOWN,
)
from signals import detect_market_signals
from notifier import send_telegram_message, get_updates


# ================= TIMEZONE =================
os.environ["TZ"] = "Europe/Warsaw"
if hasattr(time, "tzset"):
    time.tzset()
PL_TZ = ZoneInfo("Europe/Warsaw")


# ================= TELEGRAM =================
def ensure_no_webhook():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("⚠️ No TELEGRAM_BOT_TOKEN")
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/deleteWebhook",
            timeout=10
        ).json()
        print(f"🔧 deleteWebhook: {r.get('description')}")
    except Exception as e:
        print(f"⚠️ deleteWebhook error: {e}")


def send_telegram_photo(photo_path):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        with open(photo_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id},
                files={"photo": f},
                timeout=10
            )
    except Exception as e:
        print(f"Photo send error: {e}")


# ================= REDIS =================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_last_signal_time(symbol):
    ts = r.get(f"cooldown:{symbol}")
    return datetime.fromisoformat(ts).replace(tzinfo=PL_TZ) if ts else None


def set_last_signal_time(symbol, dt):
    # Oczekuje, że COOLDOWN to liczba sekund, np. 86400 (24h)
    r.set(f"cooldown:{symbol}", dt.isoformat(), ex=COOLDOWN)


def get_last_state(symbol):
    raw = r.get(f"last_state:{symbol}")
    if not raw:
        return None
    try:
        return ast.literal_eval(raw)
    except Exception:
        return None


def set_last_state(symbol, category, verdict, value):
    now = datetime.now(PL_TZ)
    r.set(
        f"last_state:{symbol}",
        str({
            "category": category,
            "verdict": verdict,
            "value": round(value, 1) if value is not None else None,
            "datetime": now.isoformat()
        })
    )


# ================= HELPERS =================
def extract_signal_value(signal):
    m = re.search(r"(\d+(?:\.\d+)?)", signal.get("message", ""))
    return float(m.group(1)) if m else None


def is_significant_change(signal, last_state):
    if last_state is None:
        return True 
    if signal["category"] != last_state.get("category"):
        return True
    v1, v2 = extract_signal_value(signal), last_state.get("value")
    if v1 is None or v2 is None:
        return False
    return abs(v1 - v2) >= 4.0


def is_weekend(now):
    return now.weekday() >= 5


def is_night(now):
    return 0 <= now.hour < 6


def should_send(now):
    return not is_weekend(now) and not is_night(now)


def save_signal(symbol, signal, verdict, dt):
    r.lpush(
        f"signals:{symbol}",
        str({
            "time": dt.isoformat(),
            "symbol": symbol,
            "category": signal["category"],
            "title": signal["title"],
            "verdict": verdict
        })
    )
    r.incr("stats:total")
    r.incr(f"stats:{signal['category']}")
    r.incr(f"stats:symbol:{symbol}")


# ================= MARKETS =================
GPW_SYMBOLS = {
    "PKO","PEO","PZU","ING","MBK","ALR","PKN","KGH","PGE","ENA","TPE",
    "CDR","11B","PLW","TEN","LPP","DNP","CCC","ALE","XTB","KTY",
    "ACP","BDX","OPL","SNT"
}

YAHOO_SYMBOLS = {
    "AAPL","AMZN","META","MSFT","NVDA","GOOGL","AMD","INTC","IBM","ORCL",
    "TSM","TSLA","PLTR","NVO","SOFI","HOOD","LMT","RTX","BA","CAT","DE",
    "MCD","COST","WMT","PG","JPM","GS","BAC","MS","XOM","CVX","VLO",
    "ASML","SAP","GLD","SLV","USO"
}

ALL_SYMBOLS = sorted(set(INSTRUMENTS) | YAHOO_SYMBOLS)


# ================= DATA =================
def to_float_list(arr):
    out = []
    for x in arr:
        try:
            out.append(float(x) if not isinstance(x, (list,np.ndarray)) else float(x[0]))
        except Exception:
            pass
    return out

def get_market_data(symbol):
    symbol = symbol.upper()
    
    yf_symbol = f"{symbol}.WA" if symbol in GPW_SYMBOLS else symbol
    
    try:
        df = yf.download(yf_symbol, period="1y", interval="1d", 
                        progress=False, multi_level_index=False)
        if df.empty:
            print(f"⚠️ Brak danych dla {yf_symbol}")
            return [], []
        prices = df['Close'].dropna().tolist()
        volumes = df['Volume'].dropna().tolist()
        return prices, volumes
    except Exception as e:
        print(f"❌ yfinance error {yf_symbol}: {e}")
        return [], []

# ================= WHY =================
def explain_symbol(symbol, now):
    prices, vols = get_market_data(symbol)
    if len(prices) < 50:
        return f"❌ Brak danych – pobrano {len(prices)} punktów dla {symbol}"
    signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
    if not signals:
        return "⏸ Brak sygnałów"
    last_state = get_last_state(symbol)
    out = []
    for s in signals:
        if last_state is None:
            out.append("🛑 Hydratacja Redis – brak baseline’u")
        elif not is_significant_change(s, last_state):
            out.append("🛑 Brak istotnej zmiany (<4 pp / ta sama kategoria)")
        elif not should_send(now):
            out.append("🛑 Weekend lub cisza nocna")
        elif get_last_signal_time(symbol):
            out.append("🛑 Cooldown")
        else:
            out.append("✅ Alert byłby wysłany")
            
    # Zwróć unikalne odpowiedzi (zachowując ich oryginalną kolejność, jeśli ma to znaczenie)
    return "\n".join(list(dict.fromkeys(out))) 


# ================= COMMANDS =================
last_update_id = None

def handle_telegram_commands():
    global last_update_id
    updates = get_updates(last_update_id)
    if not updates:
        return

    for u in updates:
        last_update_id = u["update_id"] + 1
        text = u.get("message", {}).get("text","").split("@")[0].strip()
        now = datetime.now(PL_TZ)

        if text == "/status":
            send_telegram_message("🟢 Bot działa")

        elif text == "/list":
            send_telegram_message("📈 " + ", ".join(ALL_SYMBOLS))

        elif text == "/info":
            send_telegram_message(
                "⚙️ Logika bota:\n\n"
                "• Skanuje spółki z config (radar), portfel jest osobno.\n"
                "• RSI wykrywa wyprzedanie (<30) i przegrzanie (>70).\n"
                "• Wolumen: alert gdy > średnia * mnożnik.\n"
                "• Alert TYLKO gdy zmiana kategorii LUB ≥10 pp.\n"
                "• Cooldown zapobiega spamowi.\n"
                "• Cisza nocna: 00:00–06:00.\n"
                "• Brak alertów w weekend.\n"
                "• Po restarcie: hydratacja Redis (bez alertów).\n\n"
                "Explainability:\n\n"
                    "⚙️ Logika wyliczania sygnałów\n\n"
                f"1️⃣ Zmienność: Próg {VOLATILITY_THRESHOLD * 100}% rocznie (20-dniowa).\n"
                f"2️⃣ Wolumen: Mnożnik {VOLUME_MULTIPLIER}x powyżej średniej.\n"
                "3️⃣ RSI: Wykrywa wyprzedanie (<30) i przegrzanie (>70).\n\n"
                "Filtrowanie duplikatów:\n"
                "• Ten sam sygnał wysyłany tylko gdy wartość zmieni się o ≥4pp\n"
                "• Brak alertów w weekendy i między 00:00–06:00\n"
                f"• Cooldown między alertami: {COOLDOWN//3600}h\n"
                "• Przy restarcie: cichy przebieg (hydratacja Redis)"
            )

        elif text == "/stats":
            send_telegram_message(
                f"📊 total={r.get('stats:total')} "
                f"trend={r.get('stats:TREND_CONFIRMATION')} "
                f"contra={r.get('stats:CONTRARIAN')} "
                f"behaviour={r.get('stats:BEHAVIOR_CHANGE')}"
            )

        elif text == "/last":
            msgs = []
            for s in ALL_SYMBOLS:
                it = r.lrange(f"signals:{s}", 0, 0)
                if it:
                    msgs.append(ast.literal_eval(it[0]))
            msgs.sort(key=lambda x: x["time"], reverse=True)
            if not msgs:
                send_telegram_message("Brak alertów")
            else:
                send_telegram_message(
                    "\n".join(f"{m['symbol']} {m['verdict']}" for m in msgs[:5])
                )

        elif text.startswith("/why"):
            p = text.split()
            if len(p) != 2:
                send_telegram_message("Użycie: /why SYMBOL")
            else:
                send_telegram_message(explain_symbol(p[1].upper(), now))

        elif text == "/debug":
            send_telegram_message(f"DEBUG: symbols={len(ALL_SYMBOLS)} first_run={IS_FIRST_RUN}")

        elif text == "/papaj":
            send_telegram_message("💛 21:37 💛")
            send_telegram_photo("papaj.png")

        elif text == "/help":
            send_telegram_message(
                "/status /debug – status bota\n"
                "/stats – statystyki\n"
                "/last – ostatnie sygnały\n"
                "/help – pomoc\n"
                "/info - logika\n"
                "/why - poprawność logiki\n"
                "/papaj"
            )


# ================= MARKET LOOP =================
IS_FIRST_RUN = True

def analyze_market():
    global IS_FIRST_RUN
    now = datetime.now(PL_TZ)
    for s in ALL_SYMBOLS:
        prices, vols = get_market_data(s)
        if len(prices) < 50:
            continue
        sigs = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
        last_state = get_last_state(s)
        for sig in sigs:
            verdict = (
                "✅ KUPUJ" if sig["category"]=="TREND_CONFIRMATION"
                else "❌ SPRZEDAJ / OMIJAJ" if sig["category"]=="CONTRARIAN"
                else "⏸ OBSERWUJ"
            )
            if not is_significant_change(sig, last_state):
                continue
            set_last_state(s, sig["category"], verdict, extract_signal_value(sig))
            if not should_send(now) or IS_FIRST_RUN:
                continue
            if get_last_signal_time(s):
                continue
            market = "🇵🇱 GPW" if s in GPW_SYMBOLS else "🇺🇸 USA/ETF"
msg = (
    f"📡 <b>{s}</b>\n"
    f"Rynek: {market}\n\n"
    f"Sytuacja: {sig['title']}\n"
    f"Werdykt: {verdict}\n\n"
    f"{sig.get('message', '')}"
)
send_telegram_message(msg)

            save_signal(s, sig, verdict, now)
            set_last_signal_time(s, now)
            time.sleep(1)
    IS_FIRST_RUN = False

# ================= INSTANCE LOCK =================
LOCK_KEY = "bot:instance_lock"
LOCK_TTL = 30

def acquire_lock():
    return r.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL)

def refresh_lock():
    r.expire(LOCK_KEY, LOCK_TTL)

def release_lock():
    r.delete(LOCK_KEY)


# ================= MAIN =================
COMMAND_CHECK_INTERVAL = 3
MARKET_ANALYSIS_INTERVAL = 300
last_command_check = 0
last_market_check = 0

if __name__ == "__main__":
    ensure_no_webhook()
    print("🚀 Bot uruchomiony | czekam na lock...")

    for _ in range(35):
        if acquire_lock():
            break
        print("⏳ Inna instancja aktywna, czekam...")
        time.sleep(1)
    else:
        print("❌ Nie udało się zająć locka – kończę")
        exit(1)

    print("✅ Lock zajęty | tryb stabilny")

    try:
        while True:
            refresh_lock()
            t = time.time()
            if t - last_command_check >= COMMAND_CHECK_INTERVAL:
                handle_telegram_commands()
                last_command_check = t
            if t - last_market_check >= MARKET_ANALYSIS_INTERVAL:
                analyze_market()
                last_market_check = time.time()
            time.sleep(1)
    finally:
        release_lock()
        print("🔓 Lock zwolniony")
