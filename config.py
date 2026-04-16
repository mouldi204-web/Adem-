# =========================
# CONFIGURATION
# =========================

BASE_URL = "https://api.kucoin.com"

TRADE_SIZE = 100
MAX_TRADES = 5

SCAN_LIMIT = 1000
BATCH_SIZE = 200

BLACKLIST = ["BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "XRP-USDT"]

# AI thresholds
MIN_SCORE = 75
MIN_PROB = 0.85

# trailing settings
TRAIL_START = 0.01   # +1%
TRAIL_DISTANCE = 0.02  # 2%

# Telegram (ضعهم هنا)
TELEGRAM_TOKEN = "YOUR_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
