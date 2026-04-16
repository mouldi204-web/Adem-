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
# CONFIG
# =========================
BASE_URL = "https://api.kucoin.com"

TRADE_SIZE = 100

BLACKLIST = ["BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT"]

MIN_SCORE = 75
MIN_PROB = 0.85

HEARTBEAT_INTERVAL = 1800  # 30 minutes

open_trades = []
last_heartbeat = 0

# =========================
# TELEGRAM
# =========================
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"

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
    data = requests.get(BASE_URL + "/api/v1/symbols").json()['data']
    return [s['symbol'] for s in data if s['quoteCurrency']=='USDT'][:1000]


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
# PRE FILTER (FAST SKIP)
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
# SCORE ENGINE (0–100)
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
        tech
