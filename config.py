import os

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Instrument koncepcyjny (na razie symbol techniczny)
INSTRUMENT = "AAPL"        # docelowo: akcja / indeks / ETF
MARKET_TYPE = "equities"   # equities | indices | forex | crypto

# Parametry analizy
VOLATILITY_THRESHOLD = 0.05
