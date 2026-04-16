import time
import requests
import pandas as pd
import numpy as np
import joblib
import os
import threading
from flask import Flask

# =========================
# KEEP ALIVE SERVER
# =========================
app = Flask("")

@app.route("/")
def home():
    return "BOT RUNNING"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# =========================
# CONFIG (FROM ENV - SAFE)
# =========================
TOKEN = os.getenv("8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68")
CHAT_ID = os.getenv("5067771509")

BASE_URL = "https://api.kucoin.com"

TRADE_SIZE = 100
MIN_SCORE = 75
MIN_PROB = 0.85

open_trades = []
last_heartbeat = 0

# =========================
# TELEGRAM SAFE SEND
# =========================
def send(msg):
    if not TOKEN or not CHAT_ID:
        print("Telegram not configured")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)

# =========================
# AI MODEL
# =========================
model = joblib.load("model.pkl") if os.path.exists("model.pkl") else None

def ai_prob(features):
    if model is None:
        return 0.5
    return model.predict_proba([features])[0][1]

# =========================
# DATA
# =========================
def get_symbols():
    data = requests.get(BASE_URL + "/api/v1/symbols").json()['data']
    return [s['symbol'] for s in data if s['quoteCurrency'] == 'USDT'][:500]


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
    df['ema50'] = df['c'].ewm(50).mean()
    df['vol_ma'] = df['v'].rolling(20).mean()

    return df

# =========================
# PRE FILTER
# =========================
def pre_filter(df):

    last = df.iloc[-1]

    ema9 = df['c'].ewm(9).mean().iloc[-1]
    ema21 = df['c'].ewm(21).mean().iloc[-1]
    ema50 = df['c'].ewm(50).mean().iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]
    resistance = df['h'].rolling(20).max().iloc[-2]

    return all([
        last['v'] > 1.8 * vol_ma,
        last['c'] > resistance,
        ema9 > ema21,
        ema21 > ema50
    ])

# =========================
# SCORE ENGINE
# =========================
def coin_rank(df):

    last = df.iloc[-1]

    features = [
        last['c'],
        last['v'],
        df['v'].rolling(20).mean().iloc[-1],
        last['ema9'],
        last['ema50']
    ]

    prob = ai_prob(features)

    tech = 0

    if last['v'] > 2 * df['v'].rolling(20).mean().iloc[-1]:
        tech += 25

    if last['ema9'] > last['ema21']:
        tech += 20

    if last['ema21'] > last['ema50']:
        tech += 20

    if last['c'] > df['h'].rolling(20).max().iloc[-2]:
        tech += 25

    ai = int(prob * 30)

    return min(tech + ai, 100), prob

# =========================
# TRAILING STOP
# =========================
def trailing_stop(trade, price):

    entry = trade["entry"]

    profit = (price - entry) / entry

    if profit < 0.01:
        return None

    if "high" not in trade:
        trade["high"] = price

    if price > trade["high"]:
        trade["high"] = price

    return trade["high"] * 0.98

# =========================
# TRADE SYSTEM
# =========================
def open_trade(symbol, price):

    open_trades.append({
        "symbol": symbol,
        "entry": price
    })

    send(f"🚀 OPEN\n{symbol}\n{price}")


def close_trade(trade, price):

    profit = (price - trade["entry"]) * TRADE_SIZE

    send(f"📉 CLOSE\n{trade['symbol']}\nProfit: {profit:.2f}$")

# =========================
# CHECK TRADES
# =========================
def check_trades():

    for t in open_trades[:]:

        df = indicators(klines(t["symbol"]))
        price = df['c'].iloc[-1]

        stop = trailing_stop(t, price)

        if stop and price < stop:

            close_trade(t, price)
            open_trades.remove(t)

# =========================
# SCANNER
# =========================
def scan_coin(symbol):

    df = klines(symbol)
    df = indicators(df)

    if not pre_filter(df):
        return None

    score, prob = coin_rank(df)

    if score >= MIN_SCORE and prob >= MIN_PROB:

        send(f"🔥 SIGNAL\n{symbol}\nScore {score}")

        return symbol, score, prob

    return None


def scanner():

    symbols = get_symbols()
    results = []

    for s in symbols:

        try:
            r = scan_coin(s)
            if r:
                results.append(r)
        except:
            continue

    results.sort(key=lambda x: x[1], reverse=True)

    return results

# =========================
# HEARTBEAT
# =========================
def heartbeat():
    send("🟢 BOT ACTIVE - searching for explosions 🔍")

# =========================
# MAIN LOOP
# =========================
def run():

    global last_heartbeat

    send("🚀 BOT STARTED")

    last_heartbeat = time.time()

    while True:

        try:

            results = scanner()

            for r in results[:5]:
                open_trade(r[0], 0)

            check_trades()

            if time.time() - last_heartbeat > 1800:
                heartbeat()
                last_heartbeat = time.time()

            time.sleep(60)

        except Exception as e:
            send(f"⚠️ ERROR {e}")
            time.sleep(5)

if __name__ == "__main__":
    run()
