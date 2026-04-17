import os
import time
import ast
from datetime import datetime, timezone
from zoneinfo import ZoneInfo  # Dodane dla obsługi stref czasowych

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

# Ustawienie strefy czasowej dla systemu i Pythona
os.environ['TZ'] = 'Europe/Warsaw'
if hasattr(time, 'tzset'): time.tzset()
PL_TZ = ZoneInfo("Europe/Warsaw")

def send_telegram_photo(photo_path):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

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

    # statystyki
    r.incr("stats:total")
    r.incr(f"stats:{signal['category']}")
    r.incr(f"stats:symbol:{symbol}")


# =====================================================
# PEŁNE NAZWY + RYNKI
# =====================================================
COMPANY_NAMES = {
    # GPW – Polska
    "PKO":     "PKO Bank Polski",
    "PEO":     "Bank Pekao S.A.",
    "PZU":     "PZU S.A.",
    "ING":     "ING Bank Śląski S.A.",
    "MBK":     "mBank S.A.",
    "ALR":     "Alior Bank S.A.",
    "PKN":     "PKN Orlen S.A.",
    "KGH":     "KGHM Polska Miedź S.A.",
    "PGE":     "PGE S.A.",
    "ENA":     "Enea S.A.",
    "TPE":     "Tauron Polska Energia S.A.",
    "CDR":     "CD Projekt S.A.",
    "11B":     "11 bit studios S.A.",
    "PLW":     "Playway S.A.",
    "TEN":     "Ten Square Games S.A.",
    "LPP":     "LPP S.A.",
    "DNP":     "Dino Polska S.A.",
    "CCC":     "CCC S.A.",
    "ALE":     "Allegro.eu S.A.",
    "VRG":     "Vistula Group S.A.",
    "XTB":     "XTB S.A.",
    "KTY":     "Grupa Kęty S.A.",
    "ACP":     "Asseco Poland S.A.",
    "BDX":     "Budimex S.A.",
    "OPL":     "Orange Polska S.A.",
    "GPW":     "Giełda Papierów Wartościowych S.A.",
    "SNT":     "Synektik S.A.",
    "PHT":     "Pharmena S.A.",
    "SN2":     "SN2 S.A.",
    # USA – Big Tech / AI
    "NVDA":    "NVIDIA Corporation",
    "MSFT":    "Microsoft Corporation",
    "AAPL":    "Apple Inc.",
    "AMZN":    "Amazon.com Inc.",
    "META":    "Meta Platforms Inc.",
    "GOOGL":   "Alphabet Inc.",
    "AMD":     "Advanced Micro Devices Inc.",
    "INTC":    "Intel Corporation",
    "IBM":     "IBM Corporation",
    "ORCL":    "Oracle Corporation",
    "TSM":     "Taiwan Semiconductor Manufacturing",
    "SMCI":    "Super Micro Computer Inc.",
    "TSLA":    "Tesla Inc.",
    "PLTR":    "Palantir Technologies Inc.",
    "NVO":     "Novo Nordisk A/S",
    "SOFI":    "SoFi Technologies Inc.",
    "HOOD":    "Robinhood Markets Inc.",
    # USA – Przemysł / obronność
    "LMT":     "Lockheed Martin Corporation",
    "RTX":     "RTX Corporation",
    "BA":      "Boeing Company",
    "CAT":     "Caterpillar Inc.",
    "DE":      "Deere & Company",
    # USA – Konsumpcja
    "MCD":     "McDonald's Corporation",
    "COST":    "Costco Wholesale Corporation",
    "WMT":     "Walmart Inc.",
    "PG":      "Procter & Gamble Co.",
    # USA – Finanse
    "JPM":     "JPMorgan Chase & Co.",
    "GS":      "Goldman Sachs Group, Inc.",
    "BAC":     "Bank of America Corp.",
    "MS":      "Morgan Stanley",
    # USA – Energia
    "XOM":     "ExxonMobil Corporation",
    "CVX":     "Chevron Corporation",
    "VLO":     "Valero Energy Corporation",
    # Europa
    "ASML":    "ASML Holding N.V.",
    "SAP":     "SAP SE",
    "NESN.SW": "Nestlé S.A.",
    "RHM.DE":  "Rheinmetall AG",
    "AIR.PA":  "Airbus SE",
    # Surowce / ETF
    "4GLD.DE": "Xetra Gold (DE)",
    "GLD":     "SPDR Gold Shares ETF",
    "SLV":     "iShares Silver Trust ETF",
    "USO":     "United States Oil Fund ETF",
    "CPER":    "United States Copper Index ETF",
    "URA":     "Global X Uranium ETF",
}

# =====================================================
# SYMBOLE GPW (routing → Stooq)
# =====================================================
GPW_SYMBOLS = {
    "PKO", "PEO", "PZU", "ING", "MBK", "ALR",
    "PKN", "KGH", "PGE", "ENA", "TPE",
    "CDR", "11B", "PLW", "TEN",
    "LPP", "DNP", "CCC", "ALE", "VRG",
    "XTB", "KTY", "ACP",
    "BDX", "OPL", "GPW",
    "SNT", "PHT", "SN2",
}

# =====================================================
# SYMBOLE YAHOO (USA + Europa z sufixami + ETF)
# =====================================================
YAHOO_SYMBOLS = {
    # USA – Big Tech / AI
    "AAPL", "AMZN", "META", "MSFT", "NVDA", "GOOGL",
    "AMD", "INTC", "IBM", "ORCL", "TSM", "SMCI",
    "TSLA", "PLTR", "NVO", "SOFI", "HOOD",
    # USA – Przemysł / obronność
    "LMT", "RTX", "BA", "CAT", "DE",
    # USA – Konsumpcja
    "MCD", "COST", "WMT", "PG",
    # USA – Finanse
    "JPM", "GS", "BAC", "MS",
    # USA – Energia
    "XOM", "CVX", "VLO",
    # Europa (Yahoo obsługuje .SW, .DE, .PA natywnie)
    "ASML", "SAP",
    "NESN.SW",   # Nestlé – Swiss Exchange
    "RHM.DE",    # Rheinmetall – XETRA
    "AIR.PA",    # Airbus – Euronext Paris
    # Surowce / ETF
    "4GLD.DE",   # Xetra Gold
    "GLD",       # złoto ETF
    "SLV",       # srebro ETF
    "USO",       # ropa ETF
    "CPER",      # miedź ETF
    "URA",       # uran ETF
}

ALL_SYMBOLS = sorted(set(INSTRUMENTS) | YAHOO_SYMBOLS)


# =====================================================
# USTAWIENIA CZASOWE
# =====================================================
SILENCE_START, SILENCE_END = 0, 6
COMMAND_CHECK_INTERVAL = 3         # sekundy
MARKET_ANALYSIS_INTERVAL = 300     # 5 minut

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
        except Exception:
            pass
    return out


def get_market_data(symbol):
    symbol = symbol.upper()

    # ===== USA / Europa / ETF → YAHOO =====
    if symbol in YAHOO_SYMBOLS:
        try:
            data = yf.download(symbol, period="1y", interval="1d", progress=False)
            if data.empty:
                return [], []

            return (
                to_float_list(data["Close"].values),
                to_float_list(data["Volume"].values),
            )
        except Exception:
            return [], []

    # ===== DOMYŚLNIE → STOOQ / GPW =====
    try:
        url = f"https://stooq.pl/q/d/l/?s={symbol.lower()}&i=d"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return [], []

        lines = resp.text.splitlines()[1:]
        prices, volumes = [], []
        for row in lines[-300:]:
            p = row.split(",")
            if len(p) >= 6:
                prices.append(float(p[4]))
                volumes.append(float(p[5]))

        return prices, volumes
    except Exception:
        return [], []


# =====================================================
# COOLDOWN – pomocnicza walidacja
# =====================================================
def is_on_cooldown(symbol, now):
    """Zwraca True jeśli od ostatniego alertu minęło mniej niż COOLDOWN sekund."""
    last = get_last_signal_time(symbol)
    if last is None:
        return False
    # Porównujemy daty w tej samej polskiej strefie czasowej
    if last.tzinfo is None:
        last = last.replace(tzinfo=PL_TZ)
    
    elapsed = (now - last).total_seconds()
    return elapsed < COOLDOWN


# =====================================================
# KOMENDY TELEGRAM
# =====================================================
def handle_telegram_commands():
    global last_update_id

    updates = get_updates(last_update_id)
    if not updates:
        return

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
                    try:
                        messages.append(ast.literal_eval(items[0]))
                    except Exception:
                        pass

            if not messages:
                send_telegram_message("Brak zapisanych sygnałów.")
            else:
                messages.sort(key=lambda x: x["time"], reverse=True)
                msg = "📡 Ostatnie sygnały\n\n"
                for s in messages[:5]:
                    msg += (
                        f"{s['symbol']}\n"
                        f"{s['title']}\n"
                        f"Werdykt: {s['verdict']}\n\n"
                    )
                send_telegram_message(msg)

        elif text == "/papaj":
            send_telegram_photo("papaj.png")

        elif text == "/help":
            send_telegram_message(
                "/status – status bota\n"
                "/stats – statystyki\n"
                "/last – ostatnie sygnały\n"
                "/help – pomoc\n"
                "/papaj"
            )


# =====================================================
# ANALIZA RYNKU (ZMIANA STANU + COOLDOWN)
# =====================================================
def analyze_market():
    global last_check_time
    # Pobieramy czas polski zamiast UTC
    now = datetime.now(PL_TZ)
    last_check_time = now.strftime("%H:%M:%S")

    for symbol in ALL_SYMBOLS:
        prices, vols = get_market_data(symbol)
        if len(prices) < 50:
            continue

        signals = detect_market_signals(
            prices,
            vols,
            VOLATILITY_THRESHOLD,
            VOLUME_MULTIPLIER,
        )

        if not signals or is_night_silence(now):
            continue

        for s in signals:
            if s["category"] == "TREND_CONFIRMATION":
                verdict = "✅ KUPUJ"
            elif s["category"] == "CONTRARIAN":
                verdict = "❌ SPRZEDAJ / OMIJAJ"
            else:
                verdict = "⏸ TRZYMAJ / OBSERWUJ"

            current_state = f"{s['category']}|{verdict}"
            last_state = get_last_state(symbol)

            # Brak zmiany stanu → cisza
            if current_state == last_state:
                continue

            # Cooldown – nie spamuj nawet przy zmianie stanu
            if is_on_cooldown(symbol, now):
                continue

            # Zapis nowego stanu
            set_last_state(symbol, current_state)

            company = COMPANY_NAMES.get(symbol, symbol)
            market = "Polska – GPW" if symbol in GPW_SYMBOLS else "USA / Europa / ETF"

            msg = (
                f"📡 {company} ({symbol})\n"
                f"Rynek: {market}\n\n"
                f"Sytuacja: {s['title']}\n"
                f"Werdykt: {verdict}\n\n"
                f"Typ: {s['category']}\n"
                f"Ryzyko: {s['risk']}\n\n"
                f"{s['message']}"
            )

            send_telegram_message(msg)
            save_signal(symbol, s, verdict, now)
            set_last_signal_time(symbol, now)
            time.sleep(1)


# =====================================================
# START – RESPONSYWNA PĘTLA
# =====================================================
if __name__ == "__main__":
    print(f"🚀 Bot uruchomiony (Czas Polski) | Spółek: {len(ALL_SYMBOLS)}")

    while True:
        now_ts = time.time()

        if now_ts - last_command_check >= COMMAND_CHECK_INTERVAL:
            handle_telegram_commands()
            last_command_check = now_ts

        if now_ts - last_market_check >= MARKET_ANALYSIS_INTERVAL:
            analyze_market()
            last_market_check = now_ts

        time.sleep(1)
