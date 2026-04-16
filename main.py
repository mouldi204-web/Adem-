import time
import requests
import pandas as pd
import numpy as np
import threading
from flask import Flask

# =========================
# TELEGRAM CONFIG
# =========================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"

CHAT_IDS = [
    "5067771509",
    "-1003692815602"  # -100xxxxxxxx
]

def send(msg):
    for chat_id in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": msg,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
        except:
            pass

# =========================
# KEEP ALIVE SERVER
# =========================
app = Flask("")

@app.route("/")
def home():
    return "BOT RUNNING"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

BASE_URL = "https://api.kucoin.com"

# =========================
# PAPER TRADING
# =========================
INITIAL_BALANCE = 100
TRADE_SIZE = 100
STOP_LOSS = -0.02
TRAIL_START = 0.01
TRAIL_GAP = 0.015

balance = INITIAL_BALANCE
open_trade = None

# =========================
# DATA
# =========================
def get_symbols():
    data = requests.get(BASE_URL + "/api/v1/symbols").json()['data']
    return [s['symbol'] for s in data if s['quoteCurrency'] == 'USDT'][:1200]

def klines(symbol):
    url = BASE_URL + f"/api/v1/market/candles?type=5min&symbol={symbol}"
    data = requests.get(url).json()['data']

    df = pd.DataFrame(data, columns=['t','o','c','h','l','v','x'])
    df = df.iloc[::-1]

    for c in ['o','c','h','l','v']:
        df[c] = df[c].astype(float)

    return df

# =========================
# INDICATORS
# =========================
def indicators(df):
    df['ema9'] = df['c'].ewm(9).mean()
    df['ema21'] = df['c'].ewm(21).mean()
    return df

# =========================
# OMEGA SCORE
# =========================
def omega_score(df):

    last = df.iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]
    high = df['h'].rolling(20).max().iloc[-1]
    low = df['l'].rolling(20).min().iloc[-1]

    compression = (high - low) / last['c']
    volume = last['v'] / vol_ma
    breakout = last['c'] / high

    score = 0

    if compression < 0.02:
        score += 25
    if volume > 1.3:
        score += 25
    if breakout > 0.985:
        score += 25
    if last['c'] > last['o']:
        score += 25

    return min(score, 100)

# =========================
# ORDER BOOK (WHALER PRO)
# =========================
whale_memory = {}

def get_orderbook(symbol):
    url = f"{BASE_URL}/api/v1/market/orderbook/level2_20?symbol={symbol}"
    data = requests.get(url).json()["data"]
    return data["bids"], data["asks"]

def snapshot_whales(symbol):

    bids, asks = get_orderbook(symbol)

    bid_vol = sum(float(b[1]) for b in bids)
    ask_vol = sum(float(a[1]) for a in asks)

    total = bid_vol + ask_vol
    if total == 0:
        return 0

    return (bid_vol - ask_vol) / total

def track_whales(symbol):

    if symbol not in whale_memory:
        whale_memory[symbol] = []

    whale_memory[symbol].append(snapshot_whales(symbol))
    whale_memory[symbol] = whale_memory[symbol][-10:]

    return whale_memory[symbol]

def whale_behavior(symbol):

    history = track_whales(symbol)

    if len(history) < 5:
        return "neutral"

    trend = np.mean(history[-3:]) - np.mean(history[:3])

    if trend > 0.15:
        return "accumulation"
    elif trend < -0.15:
        return "distribution"
    return "neutral"

def spoofing_detect(bids, asks):

    big_bids = sum(1 for b in bids if float(b[1]) > 5)
    big_asks = sum(1 for a in asks if float(a[1]) > 5)

    return big_bids > 5 and big_asks > 5

def whaler_pro(symbol):

    bids, asks = get_orderbook(symbol)

    imbalance = snapshot_whales(symbol)
    behavior = whale_behavior(symbol)
    spoof = spoofing_detect(bids, asks)

    score = 0
    reasons = []

    if imbalance > 0.25:
        score += 25
        reasons.append("🐋 BUY pressure")

    if behavior == "accumulation":
        score += 35
        reasons.append("🐋 Accumulation")

    if behavior == "distribution":
        score -= 20
        reasons.append("🐋 Distribution")

    if spoof:
        score -= 15
        reasons.append("⚠️ Spoofing detected")

    return score, reasons

# =========================
# FILTERS
# =========================
def fast_filter(df):
    return df['v'].iloc[-1] > df['v'].rolling(20).mean().iloc[-1]

def entry(df):
    last = df.iloc[-1]
    return last['c'] > df['h'].rolling(20).max().iloc[-2]

# =========================
# TRADE SYSTEM
# =========================
def open_position(symbol, price, reason):

    global open_trade

    open_trade = {
        "symbol": symbol,
        "entry": price,
        "peak": price,
        "time": time.time(),
        "reason": reason
    }

    send(f"""
🚀 ENTRY SIGNAL

Symbol: {symbol}
Price: {price}
Time: {time.strftime("%Y-%m-%d %H:%M:%S")}

Why entry:
- {reason}
""")

def close_position(price, reason):

    global open_trade, balance

    entry = open_trade["entry"]

    pnl = ((price - entry) / entry) * TRADE_SIZE
    balance += pnl

    duration = int(time.time() - open_trade["time"])

    send(f"""
📉 TRADE CLOSED

Symbol: {open_trade['symbol']}
Entry: {entry}
Exit: {price}

Result: {round(pnl,2)}$
Reason: {reason}
Duration: {duration}s

Balance: {round(balance,2)}$
""")

    open_trade = None

def update_trade(price):

    global open_trade

    if not open_trade:
        return

    entry = open_trade["entry"]

    change = (price - entry) / entry

    if price > open_trade["peak"]:
        open_trade["peak"] = price

    peak = (open_trade["peak"] - entry) / entry

    if change <= STOP_LOSS:
        close_position(price, "Stop Loss")
        return

    if peak >= TRAIL_START:
        trail = open_trade["peak"] * (1 - TRAIL_GAP)
        if price < trail:
            close_position(price, "Trailing Stop")
            return

# =========================
# SCANNER
# =========================
def scan():

    symbols = get_symbols()
    results = []

    for s in symbols:

        try:
            df = indicators(klines(s))

            if not fast_filter(df):
                continue

            omega = omega_score(df)
            whale, reason = whaler_pro(s)

            score = omega + whale

            if score >= 75:
                results.append((s, score, df, reason))

        except:
            continue

    results.sort(key=lambda x: x[1], reverse=True)

    return results[:3]

# =========================
# MAIN LOOP
# =========================
def run():

    send("⚛️ FINAL BOT STARTED (OMEGA + WHALER PRO)")

    while True:

        try:

            top = scan()

            for s, score, df, reason in top:

                price = df['c'].iloc[-1]

                text_reason = " + ".join(reason) if reason else "Omega breakout"

                if entry(df) and open_trade is None:
                    open_position(s, price, text_reason)

                if open_trade:
                    update_trade(price)

            time.sleep(60)

        except Exception as e:
            send(f"ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run()
