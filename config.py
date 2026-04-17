import os

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# LISTA INSTRUMENTÓW – ROZSZERZONA, ISTOTNE RYNKI
INSTRUMENTS = [
    # ================= POLSKA – GPW =================
    # Banki / finanse
    "PKO", "PEO", "ING", "MBK", "ALR",
    # Ubezpieczenia
    "PZU",
    # Energia / surowce
    "PKN", "KGH", "PGE", "ENA", "TPE",
    # Gry
    "CDR", "11B", "PLW", "TEN",
    # Handel / konsumpcja
    "LPP", "DNP", "CCC", "ALE",
    # Technologia / pozostałe
    "XTB", "KTY", "ACP",

    # ================= USA – WALL STREET =================
    # Big Tech / AI
    "NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL",
    "AMD", "INTC", "IBM", "ORCL",
    # Półprzewodniki / hardware
    "TSM",
    # Przemysł / obronność
    "LMT", "RTX", "BA", "CAT", "DE",
    # Konsumpcja
    "MCD", "COST", "WMT", "PG",
    # Finanse
    "JPM", "GS", "BAC", "MS",
    # Energia
    "XOM", "CVX", "VLO",

    # ================= EUROPA =================
    "ASML", "SAP", "NESN.SW", "RHM.DE", "AIR.PA",

    # ================= SUROWCE / PROXY =================
    "4GLD.DE",   # złoto (Xetra Gold)
    "GLD",       # ETF złoto
    "SLV"        # ETF srebro
]

# Parametry analizy
VOLATILITY_THRESHOLD = 2.0
RSI_PERIOD = 14
VOLUME_MULTIPLIER = 2.0
COOLDOWN = 10800  # 3 godziny spokoju po wysłaniu alertu o danej spółce
``
