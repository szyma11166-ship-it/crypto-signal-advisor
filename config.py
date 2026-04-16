import os

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# LISTA TWOICH INSTRUMENTÓW
INSTRUMENTS = [
    # Polska
    "PKO", "PEO", "PKN", "PZU", "ING", "KGH", "ALE", "LPP", "DNP", "XTB", "KTY", "11B", "SNT", "PHT", "SN2",
    # USA
    "NVDA", "MSFT", "GOOGL", "META", "LMT", "MCD", "NVO", "VLO", "CVX",
    # Surowce (Xetra Gold)
    "4GLD.DE"
]

# Parametry analizy
VOLATILITY_THRESHOLD = 2.0  
RSI_PERIOD = 14
VOLUME_MULTIPLIER = 2.0     
COOLDOWN = 10800  # 3 godziny spokoju po wysłaniu alertu o danej spółce