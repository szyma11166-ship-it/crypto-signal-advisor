import os
import time
import ast
from datetime import datetime, timezone
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

# Ustawienie strefy czasowej
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
# REDIS – JEDYNE ŹRÓDŁO STANU
# =====================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def get_last_signal_time(symbol):
    ts = r.get(f"cooldown:{symbol}")
    return datetime.fromisoformat(ts) if ts else None

def set_last_signal_time(symbol, dt):
    r.set(f"cooldown:{symbol}", dt.isoformat())

def get_last_state(symbol):
    return r.get(f"last_state:{symbol}")

def set_last_state(symbol, state):
    r.set(f"last_state:{symbol}", state)

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

# =====================================================
# PEŁNE NAZWY + RYNKI
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
SILENCE_START, SILENCE_END = 0, 6
COMMAND_CHECK_INTERVAL = 3
MARKET_ANALYSIS_INTERVAL = 300

last_update_id = None
last_check_time = "Brak"
last_command_check = 0
last_market_check = 0

def is_night_silence(now):
    return SILENCE_START <= now.hour < SILENCE_END

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

def is_on_cooldown(symbol, now):
    last = get_last_signal_time(symbol)
    if last is None: return False
    if last.tzinfo is None: last = last.replace(tzinfo=PL_TZ)
    return (now - last).total_seconds() < COOLDOWN

# =====================================================
# KOMENDY TELEGRAM
# =====================================================
def handle_telegram_commands():
    global last_update_id
    updates = get_updates(last_update_id)
    if not updates: return

    for upd in updates:
        last_update_id = upd["update_id"] + 1
        text = upd.get("message", {}).get("text", "").strip()

        if text == "/status":
            send_telegram_message(
                f"🤖 Status bota\n\n"
                f"Ostatni skan: {last_check_time}\n"
                f"Spółek w radarze: {len(ALL_SYMBOLS)}\n"
                f"Tryb ciszy: {SILENCE_START}:00 – {SILENCE_END}:00 (Czas PL)"
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
                "Bot analizuje dane historyczne (ostatnie 300 sesji) pod kątem trzech kluczowych parametrów:\n\n"
                f"1️⃣ Zmienność ($V_{{ola}}$): Wyliczana jako odchylenie standardowe zmian procentowych. Sygnał generowany, gdy bieżąca zmienność przekracza próg `{VOLATILITY_THRESHOLD * 100}%`.\n"
                f"2️⃣ Wolumen ($Vol$): Porównanie bieżącego wolumenu do średniej ruchomej. Wymagane przebicie średniej o mnożnik `{VOLUME_MULTIPLIER}`x.\n"
                "3️⃣ Zmiana Zachowania: Bot wykrywa anomalie, gdy cena zachowuje się nietypowo względem trendu z ostatnich 50 dni.\n\n"
                "Kategorie sygnałów:\n"
                "• `TREND_CONFIRMATION` - Silny ruch zgodnie z trendem.\n"
                "• `CONTRARIAN` - Przegrzanie rynku / sygnał odwrotu.\n"
                "• `BEHAVIOR_CHANGE` - Nagłe wyłamanie z konsolidacji."
            )
            send_telegram_message(msg)

        elif text == "/stats":
            send_telegram_message(
                f"📊 Statystyki\n\n"
                f"Łącznie: {r.get('stats:total') or 0}\n"
                f"Trendowe: {r.get('stats:TREND_CONFIRMATION') or 0}\n"
                f"Kontrariańskie: {r.get('stats:CONTRARIAN') or 0}\n"
                f"Zmiana zachowania: {r.get('stats:BEHAVIOR_CHANGE') or 0}"
            )

        elif text == "/last":
            messages = []
            for symbol in ALL_SYMBOLS:
                items = r.lrange(f"signals:{symbol}", 0, 0)
                if items:
                    try: messages.append(ast.literal_eval(items[0]))
                    except Exception: pass
            if not messages:
                send_telegram_message("Brak zapisanych sygnałów.")
            else:
                messages.sort(key=lambda x: x["time"], reverse=True)
                msg = "📡 Ostatnie sygnały\n\n"
                for s in messages[:5]:
                    msg += f"• {s['symbol']}: {s['verdict']} ({s['title']})\n"
                send_telegram_message(msg)

        elif text == "/help":
            send_telegram_message(
                "📖 *Dostępne komendy:*\n"
                "/status - Stan pracy bota\n"
                "/list - Spis wszystkich spółek\n"
                "/info - Jak bot liczy sygnały\n"
                "/stats - Statystyki wykryć\n"
                "/last - 5 ostatnich alertów\n"
                "/papaj"
            )

# =====================================================
# ANALIZA RYNKU
# =====================================================
def analyze_market():
    global last_check_time
    now = datetime.now(PL_TZ)
    last_check_time = now.strftime("%H:%M:%S")

    for symbol in ALL_SYMBOLS:
        prices, vols = get_market_data(symbol)
        if len(prices) < 50: continue

        signals = detect_market_signals(prices, vols, VOLATILITY_THRESHOLD, VOLUME_MULTIPLIER)
        if not signals or is_night_silence(now): continue

        for s in signals:
            verdict = "✅ KUPUJ" if s["category"] == "TREND_CONFIRMATION" else "❌ SPRZEDAJ / OMIJAJ" if s["category"] == "CONTRARIAN" else "⏸ OBSERWUJ"
            current_state = f"{s['category']}|{verdict}"
            if current_state == get_last_state(symbol) or is_on_cooldown(symbol, now): continue

            set_last_state(symbol, current_state)
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
