import time
import requests
import pandas as pd
import numpy as np
import threading
from flask import Flask

# =========================
# TELEGRAM (INSIDE CODE)
# =========================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"

def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
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
    return "OMEGA BOT RUNNING"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

BASE_URL = "https://api.kucoin.com"

# =========================
# MEMORY (SELF LEARNING)
# =========================
trade_memory = []

def record_trade(symbol, result):
    trade_memory.append({"symbol": symbol, "result": result})

def adaptive_threshold():
    if len(trade_memory) < 20:
        return 70

    recent = trade_memory[-50:]
    win_rate = sum(t["result"] > 0 for t in recent) / len(recent)

    if win_rate > 0.75:
        return 60
    elif win_rate < 0.5:
        return 80
    return 70

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

def indicators(df):
    df['ema9'] = df['c'].ewm(9).mean()
    df['ema21'] = df['c'].ewm(21).mean()
    return df

# =========================
# SMART MONEY
# =========================
def smart_money(df):
    vol = df['v'].iloc[-1]
    vol_ma = df['v'].rolling(20).mean().iloc[-1]

    price = df['c'].iloc[-1]
    high = df['h'].rolling(20).max().iloc[-1]
    low = df['l'].rolling(20).min().iloc[-1]

    position = (price - low) / (high - low)

    return vol > 1.4 * vol_ma and position > 0.85

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
    if smart_money(df):
        score += 25

    return min(score, 100)

# =========================
# TIME PREDICTION
# =========================
def omega_time(score):
    if score >= 90:
        return "1–8 min ⚡"
    elif score >= 80:
        return "5–20 min"
    elif score >= 70:
        return "15–45 min"
    return "No setup"

# =========================
# WATCHLIST FILTER
# =========================
def fast_filter(df):
    return df['v'].iloc[-1] > df['v'].rolling(20).mean().iloc[-1]

# =========================
# ENTRY CONDITION
# =========================
def entry(df):
    last = df.iloc[-1]
    vol_ma = df['v'].rolling(20).mean().iloc[-1]

    return (
        last['c'] > df['h'].rolling(20).max().iloc[-2] and
        last['v'] > 1.5 * vol_ma and
        last['c'] > last['o']
    )

# =========================
# OMEGA SCANNER
# =========================
def omega_scan():

    symbols = get_symbols()

    candidates = []
    threshold = adaptive_threshold()

    for s in symbols:

        try:
            df = indicators(klines(s))

            if not fast_filter(df):
                continue

            score = omega_score(df)

            if score >= threshold:
                candidates.append((s, score, df))

        except:
            continue

    candidates.sort(key=lambda x: x[1], reverse=True)

    return candidates[:3]

# =========================
# SMART ALERTS
# =========================
def send_watch(symbol, score, time_pred):

    send(f"""
🟡 WATCHLIST ALERT

{symbol}
Score: {score}
Time: {time_pred}

⚠️ Preparing for possible breakout
""")

def send_entry(symbol, price, score):

    send(f"""
🚀 ENTRY SIGNAL

{symbol}
Price: {price}
Score: {score}

🔥 Breakout confirmed
""")

def send_exit(symbol, profit):

    send(f"""
📉 EXIT

{symbol}
Profit: {profit}$
""")

# =========================
# MAIN LOOP
# =========================
open_trades = []

def run():

    send("⚛️ OMEGA BOT STARTED")

    last_heartbeat = time.time()

    while True:

        try:

            top = omega_scan()

            for s, score, df in top:

                price = df['c'].iloc[-1]
                tpred = omega_time(score)

                send_watch(s, score, tpred)

                if entry(df):

                    open_trades.append({"symbol": s, "entry": price})

                    send_entry(s, price, score)

            # heartbeat كل 30 دقيقة
            if time.time() - last_heartbeat > 1800:

                send("🟢 OMEGA BOT STILL RUNNING")
                last_heartbeat = time.time()

            time.sleep(60)

        except Exception as e:
            send(f"⚠️ ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run()
