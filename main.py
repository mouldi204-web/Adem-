import time
import requests
import pandas as pd
import numpy as np
import threading
from flask import Flask
from datetime import datetime

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
# KEEP ALIVE
# =========================
app = Flask("")
@app.route("/")
def home():
    return "BOT RUNNING"

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080)).start()

# =========================
# CONFIG
# =========================
BASE_URL = "https://api.kucoin.com"
open_trades = []

# =========================
# DATA
# =========================
def get_symbols():
    data = requests.get(BASE_URL + "/api/v1/symbols").json()['data']
    return [s['symbol'] for s in data if s['quoteCurrency'] == 'USDT'][:150]

def klines(symbol, tf):
    url = BASE_URL + f"/api/v1/market/candles?type={tf}&symbol={symbol}"
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
    df['ema200'] = df['c'].ewm(200).mean()
    return df

# =========================
# TREND CHECK
# =========================
def trend_ok(df):
    return (
        df['ema9'].iloc[-1] > df['ema21'].iloc[-1] >
        df['ema50'].iloc[-1]
    )

# =========================
# SQUEEZE
# =========================
def squeeze(df):
    high = df['h'].rolling(20).max().iloc[-1]
    low = df['l'].rolling(20).min().iloc[-1]
    return (high - low) / df['c'].iloc[-1] < 0.02

# =========================
# GOLDEN CROSS
# =========================
def golden_cross(df):
    return (
        df['ema50'].iloc[-2] < df['ema200'].iloc[-2] and
        df['ema50'].iloc[-1] > df['ema200'].iloc[-1]
    )

# =========================
# CANDLE CONFIRMATION
# =========================
def candle_confirm(df):
    last = df.iloc[-1]
    vol_ma = df['v'].rolling(20).mean().iloc[-1]

    return (
        last['c'] > last['o'] and
        last['v'] > 1.5 * vol_ma and
        last['c'] > (last['h'] * 0.98)
    )

# =========================
# SCORE
# =========================
def score_system(df5, df15, df1h):

    score = 0

    # Trend (multi TF)
    if trend_ok(df5) and trend_ok(df15) and trend_ok(df1h):
        score += 35

    # Squeeze (2 TF)
    if squeeze(df5) and squeeze(df15):
        score += 25

    # Golden Cross (any TF)
    if golden_cross(df5) or golden_cross(df15) or golden_cross(df1h):
        score += 20

    # Candle confirmation
    if candle_confirm(df5):
        score += 20

    return score

# =========================
# TIME PREDICTION
# =========================
def predict_time(score):
    if score >= 90:
        return "5–20 min"
    elif score >= 85:
        return "15–40 min"
    else:
        return "No setup"

# =========================
# EXPECTED MOVE
# =========================
def expected_move(df):
    atr = (df['h'] - df['l']).rolling(14).mean().iloc[-1]
    price = df['c'].iloc[-1]
    return round((atr / price) * 100 * 2.5, 2)

# =========================
# LEVELS
# =========================
def get_levels(df):
    support = df['l'].rolling(20).min().iloc[-1]
    resistance = df['h'].rolling(20).max().iloc[-2]
    entry = df['c'].iloc[-1]

    tp1 = entry + (resistance - support) * 0.5
    tp2 = entry + (resistance - support)
    sl = support

    return tp1, tp2, sl

# =========================
# ALERT
# =========================
def alert(symbol, score, df5):

    price = df5['c'].iloc[-1]
    time_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tp1, tp2, sl = get_levels(df5)
    exp_move = expected_move(df5)
    t_pred = predict_time(score)

    send(f"""
🚀 EXPLOSION SETUP

{symbol}

Price: {price}
Time: {time_now}

Score: {score}/100

⏱ Time: {t_pred}
📈 Move: ~{exp_move}%

TP1: {tp1}
TP2: {tp2}
SL: {sl}
""")

# =========================
# SCANNER
# =========================
def scanner():

    symbols = get_symbols()

    for s in symbols:

        try:
            df5 = indicators(klines(s, "5min"))
            df15 = indicators(klines(s, "15min"))
            df1h = indicators(klines(s, "1hour"))

            score = score_system(df5, df15, df1h)

            if score >= 85:
                alert(s, score, df5)

        except:
            continue

# =========================
# MAIN LOOP
# =========================
def run():

    send("🚀 BOT STARTED - ULTRA STRICT MODE")

    while True:
        scanner()
        time.sleep(120)

if __name__ == "__main__":
    run()
