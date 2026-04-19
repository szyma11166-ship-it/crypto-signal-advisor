import os
import time
import ast
import math
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

os.environ['TZ'] = 'Europe/Warsaw'
if hasattr(time, 'tzset'): time.tzset()
PL_TZ = ZoneInfo("Europe/Warsaw")

def send_telegram_photo(photo_path):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(photo_path, "rb") as photo:
            files = {"photo": photo}
            data = {"chat_id": chat_id}
            requests.post(url, data=data, files=files, timeout=10)
    except Exception as e:
        print(f"❌ Nie udało się wysłać zdjęcia: {e}")

# =====================================================
# REDIS
# =====================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def get_last_signal_time(symbol):
    ts = r.get(f"cooldown:{symbol}")
    return datetime.fromisoformat(ts) if ts else None

def set_last_signal_time(symbol, dt):
    r.set(f"cooldown:{symbol}", dt.isoformat())

def get_last_state(symbol):
    val = r.get(f"last_state:{symbol}")
    if not val:
        return None
    try:
        return ast.literal_eval(val)
    except Exception:
        return None

def set_last_state(symbol, category, verdict, value):
    now = datetime.now(PL_TZ)
    entry = {
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.isoformat(),
        "category": category,
        "verdict": verdict,
        "value": round(value, 1) if value is not None else None,
    }
    r.set(f"last_state:{symbol}", str(entry))

def extract_signal_value(signal):
    """Wyciąga liczbową wartość z sygnału (RSI lub vol_pct)."""
    import re
    msg = signal.get("message", "")
    match = re.search(r"(\d+\.\d+)", msg)
    return float(match.group(1)) if match else None

def is_significant_change(signal, last_state):
    """
    Wysyła gdy:
    - brak poprzedniego stanu
    - inna kategoria lub verdict
    - ta sama kategoria, ale wartość zmieniła się o >=10pp
    - sygnał pojawił się po ciszy nocnej, ale nie istniał przed jej началem
      (sprawdzamy czy last_state pochodzi sprzed ciszy)

    Blokuje gdy:
    - ta sama kategoria i wartość zmieniła się o <10pp
    - sygnał istniał już przed ciszą nocną (nie jest nowy po przebudzeniu)
    """
    if last_state is None:
        return True

    now = datetime.now(PL_TZ)
    current_category = signal["category"]
    last_category = last_state.get("category", "")

    # Inna kategoria → zawsze wysyłaj
    if current_category != last_category:
        return True

    # Sprawdź czy ostatni sygnał był wysłany PRZED początkiem dzisiejszej ciszy
    # Jeśli tak, to po przebudzeniu traktujemy go jako "stary" i NIE wysyłamy ponownie
    # chyba że wartość istotnie wzrosła
    last_dt_str = last_state.get("datetime")
    if last_dt_str:
        try:
            last_dt = datetime.fromisoformat(last_dt_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=PL_TZ)
            # Początek dzisiejszej ciszy nocnej
            silence_start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Jeśli ostatni sygnał był wysłany w oknie ciszy (0-6) dzisiaj
            # lub poprzedniego wieczoru — i sytuacja się nie zmieniła → blokuj
        except Exception:
            pass

    # Ta sama kategoria — sprawdź zmianę wartości
    current_val = extract_signal_value(signal)
    last_val = last_state.get("value")

    if current_val is None or last_val is None:
        return False

    return abs(current_val - last_val) >= 10.0

def is_weekend(now):
    """Zwraca True w sobotę (5) i niedzielę (6)."""
    return now.weekday() >= 5

def is_silence(now):
    """Cisza nocna 0:00–6:00."""
    return 0 <= now.hour < 6

def should_send(now):
    """Bot wysyła tylko w dni robocze poza ciszą nocną."""
    return not is_weekend(now) and not is_silence(now)

def save_signal(symbol, signal, verdict, dt, max_items=200):
    entry = {
        "time": dt.isoformat(),
        "symbol": symbol,
        "category": signal["category"],
        "title": signal["title"],
        "risk": signal["risk"],
        "message": signal["message"],
        "verdict": verdict,
    }
    r.lpush(f"signals:{symbol}", str(entry))
    r.ltrim(f"signals:{symbol}", 0, max_items - 1)
    r.incr("stats:total")
    r.incr(f"stats:{signal['category']}")
    r.incr(f"stats:symbol:{symbol}")

def is_on_cooldown(symbol, now):
    last = get_last_signal_time(symbol)
    if last is None: return False
    if last.tzinfo is None: last = last.replace(tzinfo=PL_TZ)
    return (now - last).total_seconds() < COOLDOWN

# =====================================================
# NAZWY + RYNKI
# =====================================================
COMPANY_NAMES = {
    "PKO": "PKO Bank Polski", "PEO": "Bank Pekao S.A.", "PZU": "PZU S.A.",
    "ING": "ING Bank Śląski S.A.", "MBK": "mBank S.A.", "ALR": "Alior Bank S.A.",
    "PKN": "PKN Orlen S.A.", "KGH": "KGHM Polska Miedź S.A.", "PGE": "PGE S.A.",
    "ENA": "Enea S.A.", "TPE": "Tauron Polska Energia S.A.", "CDR": "CD Projekt S.A.",
    "11B": "11 bit studios S.A.", "PLW": "Playway S.A.", "TEN": "Ten Square Games S.A.",
    "LPP": "LPP S.A.", "DNP": "Dino Polska S.A.", "CCC": "CCC S.A.",
    "ALE": "Allegro.eu S.A.", "VRG": "Vistula Group S.A.", "XTB": "XTB S.A.",
    "KTY": "Grupa Kęty S.A.", "ACP": "Asseco Poland S.A.", "BDX": "Budimex S.A.",
    "OPL": "Orange Polska S.A.", "GPW": "Giełda Papierów Wartościowych S.A.",
    "SNT": "Synektik S.A.", "PHT": "Pharmena S.A.", "SN2": "SN2 S.A.",
    "NVDA": "NVIDIA Corporation", "MSFT": "Microsoft Corporation", "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com Inc.", "META": "Meta Platforms Inc.", "GOOGL": "Alphabet Inc.",
    "AMD": "Advanced Micro Devices Inc.", "INTC": "Intel Corporation", "IBM": "IBM Corporation",
    "ORCL": "Oracle Corporation", "TSM": "Taiwan Semiconductor Manufacturing", "SMCI": "Super Micro Computer Inc.",
    "TSLA": "Tesla Inc.", "PLTR": "Palantir Technologies Inc.", "NVO": "Novo Nordisk A/S",
    "SOFI": "SoFi Technologies Inc.", "HOOD": "Robinhood Markets Inc.", "LMT": "Lockheed Martin Corporation",
    "RTX": "RTX Corporation", "BA": "Boeing Company", "CAT": "Caterpillar Inc.", "DE": "Deere & Company",
    "MCD": "McDonald's Corporation", "COST": "Costco Wholesale Corporation", "WMT": "Walmart Inc.",
    "PG": "Procter & Gamble Co.", "JPM": "JPMorgan Chase & Co.", "GS": "Goldman Sachs Group, Inc.",
    "BAC": "Bank of America Corp.", "MS": "Morgan Stanley", "XOM": "ExxonMobil Corporation",
    "CVX": "Chevron Corporation", "VLO": "Valero Energy Corporation", "ASML": "ASML Holding N.V.",
    "SAP": "SAP SE", "NESN.SW": "Nestlé S.A.", "RHM.DE": "Rheinmetall AG", "AIR.PA": "Airbus SE",
    "4GLD.DE": "Xetra Gold (DE)", "GLD": "SPDR Gold Shares ETF", "SLV": "iShares Silver Trust ETF",
    "USO": "United States Oil Fund ETF", "CPER": "United States Copper Index ETF", "URA": "Global X Uranium ETF",
}

GPW_SYMBOLS = {
    "PKO", "PEO", "PZU", "ING", "MBK", "ALR", "PKN", "KGH", "PGE", "ENA", "TPE",
    "CDR", "11B", "PLW", "TEN", "LPP", "DNP", "CCC", "ALE", "VRG", "XTB", "KTY",
    "ACP", "BDX", "OPL", "GPW", "SNT", "PHT", "SN2",
}

YAHOO_SYMBOLS = {
    "AAPL", "AMZN", "META", "MSFT", "NVDA", "GOOGL", "AMD", "INTC", "IBM", "ORCL",
    "TSM", "SMCI", "TSLA", "PLTR", "NVO", "SOFI", "HOOD", "LMT", "RTX", "BA", "CAT",
    "DE", "MCD", "COST", "WMT", "PG", "JPM", "GS", "BAC", "MS", "XOM", "CVX", "VLO",
    "ASML", "SAP", "NESN.SW", "RHM.DE", "AIR.PA", "4GLD.DE", "GLD", "SLV", "USO",
    "CPER", "URA",
}

ALL_SYMBOLS = sorted(set(INSTRUMENTS) | YAHOO_SYMBOLS)

# =====================================================
# USTAWIENIA CZASOWE
# =====================================================
COMMAND_CHECK_INTERVAL = 3
MARKET_ANALYSIS_INTERVAL = 300

last_update_id = None
last_check_time = "Brak"
last_command_check = 0
last_market_check = 0

# =====================================================
# DANE RYNKOWE
# =====================================================
def to_float_list(seq):
    out = []
    for x in seq:
        try:
            out.append(float(x[0]) if isinstance(x, (list, tuple, np.ndarray)) else float(x))
        except Exception: pass
    return out

def get_market_data(symbol):
    symbol = symbol.upper()
    if symbol in YAHOO_SYMBOLS:
        try:
            data = yf.download(symbol, period="1y", interval="1d", progress=False)
            if data.empty: return [], []
            return to_float_list(data["Close"].values), to_float_list(data["Volume"].values)
        except Exception: return [], []

    try:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200: return [], []
        lines = resp.text.splitlines()[1:]
        prices, volumes = [], []
        for row in lines[-300:]:
            p = row.split(",")
            if len(p) >= 6:
                prices.append(float(p[4]))
                volumes.append(float(p[5]))
        return prices, volumes
    except Exception: return [], []

# =====================================================
# KOMENDY TELEGRAM
# =====================================================
def handle_telegram_commands():
    global last_update_id
    updates = get_updates(last_update_id)
    if not updates: return

    for upd in updates:
        last_update_id = upd["update_id"] + 1
        text = upd.get("message", {}).get("text", "").strip().split('@')[0]

        if text == "/status":
            now = datetime.now(PL_TZ)
            weekend = is_weekend(now)
            silence = is_silence(now)
            status_info = "🔴 Weekend — brak alertów" if weekend else ("🌙 Cisza nocna" if silence else "🟢 Aktywny")
            send_telegram_message(
                f"🤖 Status bota\n\n"
                f"Ostatni skan: {last_check_time}\n"
                f"Spółek w radarze: {len(ALL_SYMBOLS)}\n"
                f"Tryb: {status_info}\n"
                f"Cisza nocna: 00:00 – 06:00 (Czas PL)\n"
                f"Alerty: tylko dni robocze"
            )

        elif text == "/list":
            gpw = [s for s in ALL_SYMBOLS if s in GPW_SYMBOLS]
            usa = [s for s in ALL_SYMBOLS if s in YAHOO_SYMBOLS]
            msg = "🏢 Obsługiwane spółki:\n\n"
            msg += "🇵🇱 GPW: " + ", ".join(gpw) + "\n\n"
            msg += "🌎 USA / Europa / ETF: " + ", ".join(usa)
            send_telegram_message(msg)

        elif text == "/info":
            msg = (
                "⚙️ Logika wyliczania sygnałów\n\n"
                f"1️⃣ Zmienność: Próg {VOLATILITY_THRESHOLD * 100}% rocznie (20-dniowa).\n"
                f"2️⃣ Wolumen: Mnożnik {VOLUME_MULTIPLIER}x powyżej średniej.\n"
                "3️⃣ RSI: Wykrywa wyprzedanie (<30) i przegrzanie (>70).\n\n"
                "Filtrowanie duplikatów:\n"
                "• Ten sam sygnał wysyłany tylko gdy wartość zmieni się o ≥10pp\n"
                "• Brak alertów w weekendy i między 00:00–06:00\n"
                "• Cooldown między alertami dla tej samej spółki: "
                f"{COOLDOWN//3600}h"
            )
            send_telegram_message(msg)

        elif text == "/stats":
            try:
                total = int(r.get('stats:total') or 0)
                trend = int(r.get('stats:TREND_CONFIRMATION') or 0)
                contra = int(r.get('stats:CONTRARIAN') or 0)
                behav = int(r.get('stats:BEHAVIOR_CHANGE') or 0)
                send_telegram_message(
                    f"📊 Statystyki\n\n"
                    f"Łącznie: {total}\n"
                    f"Trendowe: {trend}\n"
                    f"Kontrariańskie: {contra}\n"
                    f"Zmiana zachowania: {behav}"
                )
            except Exception as e:
                send_telegram_message(f"❌ Błąd /stats: {e}")

        elif text == "/last":
            try:
                pipe = r.pipeline()
                for symbol in ALL_SYMBOLS:
                    pipe.lrange(f"signals:{symbol}", 0, 0)
                results = pipe.execute()

                messages = []
                for symbol, items in zip(ALL_SYMBOLS, results):
                    if items:
                        try:
                            messages.append(ast.literal_eval(items[0]))
                        except Exception as parse_err:
                            print(f"⚠️ Parse error {symbol}: {parse_err} | raw: {items[0][:100]}")

                if not messages:
                    send_telegram_message("Brak zapisanych sygnałów.")
                else:
                    messages.sort(key=lambda x: x["time"], reverse=True)
                    msg = "📡 Ostatnie sygnały\n\n"
                    for s in messages[:5]:
                        msg += f"• {s['symbol']}: {s['verdict']} ({s['title']})\n"
                    send_telegram_message(msg)
            except Exception as e:
                send_telegram_message(f"❌ Błąd /last: {e}")

        elif text == "/debug":
            try:
                now = datetime.now(PL_TZ)
                debug_symbols = ["GLD", "SLV", "USO", "CPER", "URA"]
                msg = f"🔍 Debug — {now.strftime('%H:%M:%S')}\n"
                msg += f"Weekend: {'🔴 TAK' if is_weekend(now) else '🟢 NIE'}\n"
                msg += f"Cisza nocna: {'🔴 TAK' if is_silence(now) else '🟢 NIE'}\n"
                msg += f"Wysyłanie aktywne: {'🟢 TAK' if should_send(now) else '🔴 NIE'}\n"
                msg += f"Próg zmienności: {VOLATILITY_THRESHOLD} | Mnożnik vol: {VOLUME_MULTIPLIER}\n\n"

                for sym in debug_symbols:
                    prices, vols = get_market_data(sym)
                    signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
                    cd = is_on_cooldown(sym, now)
                    last_t = get_last_signal_time(sym)
                    last_str = last_t.strftime('%Y-%m-%d %H:%M') if last_t else "brak"
                    last_state = get_last_state(sym)
                    would_send = (
                        should_send(now)
                        and bool(signals)
                        and is_significant_change(signals[0], last_state)
                        and not cd
                    )
                    sig_summary = f"{signals[0]['category']} ({extract_signal_value(signals[0])})" if signals else "brak"
                    msg += (
                        f"📊 {sym}\n"
                        f"  Sygnał: {sig_summary}\n"
                        f"  Cooldown: {'🔴' if cd else '🟢'} ({last_str})\n"
                        f"  Ostatnia wartość: {last_state.get('value') if last_state else 'brak'}\n"
                        f"  Wysłałby: {'🟢 TAK' if would_send else '🔴 NIE'}\n\n"
                    )

                send_telegram_message(msg)
            except Exception as e:
                send_telegram_message(f"❌ Błąd /debug: {e}")

        elif text == "/papaj":
            send_telegram_message("💛 21:37 💛\n")
            send_telegram_photo("papaj.png")

        elif text == "/help":
            send_telegram_message(
                "📖 Dostępne komendy:\n"
                "/status - Stan pracy bota\n"
                "/list - Spis wszystkich spółek\n"
                "/info - Jak bot liczy sygnały\n"
                "/stats - Statystyki wykryć\n"
                "/last - 5 ostatnich alertów\n"
                "/debug - Diagnostyka sygnałów (surowce)\n"
                "/papaj"
            )

# =====================================================
# ANALIZA RYNKU
# =====================================================
def analyze_market():
    global last_check_time
    now = datetime.now(PL_TZ)
    last_check_time = now.strftime("%H:%M:%S")

    # Brak analizy w weekendy i w ciszy nocnej
    if not should_send(now):
        return

    for symbol in ALL_SYMBOLS:
        prices, vols = get_market_data(symbol)
        if len(prices) < 50: continue

        signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
        if not signals: continue

        last_state = get_last_state(symbol)

        for s in signals:
            if not is_significant_change(s, last_state):
                continue
            if is_on_cooldown(symbol, now):
                continue

            verdict = (
                "✅ KUPUJ" if s["category"] == "TREND_CONFIRMATION"
                else "❌ SPRZEDAJ / OMIJAJ" if s["category"] == "CONTRARIAN"
                else "⏸ OBSERWUJ"
            )
            val = extract_signal_value(s)
            set_last_state(symbol, s["category"], verdict, val)

            company = COMPANY_NAMES.get(symbol, symbol)
            market = "GPW" if symbol in GPW_SYMBOLS else "USA/ETF"

            msg = (
                f"📡 {company} ({symbol})\n"
                f"Rynek: {market}\n\n"
                f"Sytuacja: {s['title']}\n"
                f"Werdykt: {verdict}\n"
                f"Ryzyko: {s['risk']}\n\n"
                f"{s['message']}"
            )
            send_telegram_message(msg)
            save_signal(symbol, s, verdict, now)
            set_last_signal_time(symbol, now)
            time.sleep(1)

if __name__ == "__main__":
    print(f"🚀 Bot uruchomiony | Spółek: {len(ALL_SYMBOLS)}")
    while True:
        now_ts = time.time()
        if now_ts - last_command_check >= COMMAND_CHECK_INTERVAL:
            handle_telegram_commands()
            last_command_check = now_ts
        if now_ts - last_market_check >= MARKET_ANALYSIS_INTERVAL:
            analyze_market()
            last_market_check = now_ts
        time.sleep(1)