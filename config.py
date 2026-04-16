import os

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- LISTA MASZYNY (Wszystko w jednym miejscu) ---
INSTRUMENTS = [
    # Twoje główne spółki z portfela (te co wysyłałeś wcześniej)
    "AAPL", "MSFT", "TSLA", "NVDA", 
    
    # Polskie "Blue Chips" (istotne dla GPW)
    "PKO", "PEO", "ALE", "KGH", "PZU", "DNP", "LPP", "CDR",
    
    # Globalni giganci (uzupełnienie)
    "AMD", "META", "GOOGL", "AMZN", "NFLX"
]

# Parametry analizy
VOLATILITY_THRESHOLD = 2.0  # Alert przy zmianie o 2%
RSI_PERIOD = 14
VOLUME_MULTIPLIER = 2.0     # Alert przy 2x większym wolumenie niż średnia
