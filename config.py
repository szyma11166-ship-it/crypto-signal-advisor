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
    "LPP", "DNP", "CCC", "ALE", "VRG",
    # Technologia / pozostałe
    "XTB", "KTY", "ACP",
    # Budownictwo / infrastruktura
    "BDX",
    # Nowe dodatki GPW
    "OPL",   # Orange Polska – dywidendowa, stabilna
    "GPW",   # GPW S.A. – meta-instrument giełdy
    "SNT",   # Synektik
    "PHT",   # Pharmena / sektor medyczny
    "SN2",   # S.A.

    # ================= USA – WALL STREET =================
    # Big Tech / AI
    "NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL",
    "AMD", "INTC", "IBM", "ORCL",
    # Półprzewodniki / hardware
    "TSM",
    "SMCI",  # Super Micro Computer – AI infrastructure
    # Przemysł / obronność
    "LMT", "RTX", "BA", "CAT", "DE",
    # Konsumpcja
    "MCD", "COST", "WMT", "PG",
    # Finanse
    "JPM", "GS", "BAC", "MS",
    # Energia
    "XOM", "CVX", "VLO",
    # EV / nowe technologie
    "TSLA",
    # AI / Dane / obronność
    "PLTR",  # Palantir – AI/obronność, wysoka popularność
    # Biofarma / healthcare
    "NVO",   # Novo Nordisk – GLP-1, ogromny trend
    # Fintech
    "SOFI",  # SoFi Technologies
    "HOOD",  # Robinhood

    # ================= EUROPA =================
    "ASML",       # ASML Holding – fotolitografia, kluczowy dla chipów
    "SAP",        # SAP SE – enterprise software
    "NESN.SW",    # Nestlé – stabilna konsumpcja
    "RHM.DE",     # Rheinmetall – obronność Europa
    "AIR.PA",     # Airbus – lotnictwo

    # ================= SUROWCE / PROXY =================
    "4GLD.DE",    # Xetra Gold – złoto fizyczne (Niemcy)
    "GLD",        # ETF złoto (USA)
    "SLV",        # ETF srebro (USA)
    "USO",        # ETF ropa naftowa
    "CPER",       # ETF miedź – korelacja z KGH
    "URA",        # ETF uran – trend energetyczny/obronny
]

# Parametry analizy
VOLATILITY_THRESHOLD = 2.0
RSI_PERIOD = 14
VOLUME_MULTIPLIER = 2.0
COOLDOWN = 10800  # 3 godziny spokoju po wysłaniu alertu o danej spółce