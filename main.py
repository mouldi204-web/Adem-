import time
import requests
import pandas as pd
import numpy as np
import joblib
import os
import threading
from flask import Flask
from datetime import datetime

# =========================
# KEEP ALIVE SERVER
# =========================
app = Flask("")

@app.route("/")
def home():
    return "BOT RUNNING"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# =========================
# CONFIG
# =========================
BASE = "https://api.kucoin.com"

TRADE_SIZE = 100
open_trades = []

daily_profit = 0
daily_trades = 0

BLACKLIST = ["BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT"]

# =========================
# TELEGRAM
# =========================
TELEGRAM_TOKEN = "YOUR_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

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
    data = requests.get(BASE + "/api/v1/symbols").json()['data']
    return [s['symbol'] for s in data if s['quoteCurrency']=='USDT'][:1000]


def klines(symbol):
    url = BASE + f"/api/v1/market/candles?type=5min&symbol={symbol}"
    d = requests.get(url).json()['data']

    df = pd.DataFrame(d, columns=['t','o','c','h','l','v','x'])
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
# AI + TECH SCORE
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
# OPEN TRADE
# =========================
def open_trade(symbol, price):

    global daily_trades

    open_trades.append({
        "symbol": symbol,
        "entry": price
    })

    daily_trades += 1

    send(f"🚀 OPEN TRADE\n{symbol}\nEntry: {price}")

# =========================
# CLOSE TRADE
# =========================
def close_trade(trade, price):

    global daily_profit

    profit = (price - trade["entry"]) * TRADE_SIZE

    daily_profit += profit

    send(
        f"📉 CLOSE TRADE\n{trade['symbol']}\n"
        f"Exit: {price}\nProfit: {profit:.2f}$"
    )

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
# SIGNAL ALERT
# =========================
def signal_alert(symbol, score, prob):

    send(
        f"🔥 SIGNAL DETECTED\n"
        f"{symbol}\n"
        f"Score: {score}/100\n"
        f"Prob: {prob:.2f}"
    )

# =========================
# SCANNER
# =========================
def scan_coin(symbol):

    df = indicators(klines(symbol))

    if not pre_filter(df):
        return None

    score, prob = coin_rank(df)

    if score >= 75 and prob >= 0.85:

        signal_alert(symbol, score, prob)

        return {
            "symbol": symbol,
            "score": score,
            "prob": prob
        }

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

    results.sort(key=lambda x: x["score"], reverse=True)

    return results

# =========================
# DAILY REPORT
# =========================
def daily_report():

    send(
        f"📊 DAILY REPORT\n"
        f"Trades: {daily_trades}\n"
        f"Profit: {daily_profit:.2f}$"
    )

# =========================
# MAIN LOOP
# =========================
def run():

    global daily_profit, daily_trades

    print("🚀 FINAL BOT WITH TELEGRAM STARTED")

    last_report = time.time()

    while True:

        try:

            results = scanner()

            for r in results[:5]:

                df = indicators(klines(r["symbol"]))

                open_trade(r["symbol"], df['c'].iloc[-1])

            check_trades()

            # 📊 daily report every 24h
            if time.time() - last_report > 86400:

                daily_report()

                daily_profit = 0
                daily_trades = 0
                last_report = time.time()

            time.sleep(60)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(5)

if __name__ == "__main__":
    run()
