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

    if not TOKEN or not CHAT_ID:
        print("Telegram not configured")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg
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
    return [s['symbol'] for s in data if s['quoteCurrency'] == 'USDT'][:200]


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
# FILTER
# =========================
def pre_filter(df):

    last = df.iloc[-1]

    ema9 = df['c'].ewm(9).mean().iloc[-1]
    ema21 = df['c'].ewm(21).mean().iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]
    resistance = df['h'].rolling(20).max().iloc[-2]

    return (
        last['v'] > 1.5 * vol_ma and
        last['c'] > resistance and
        ema9 > ema21
    )

# =========================
# TIME
# =========================
def get_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =========================
# PREDICTION 30 MIN
# =========================
def predict_30min(df):

    last = df.iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]

    high_20 = df['h'].rolling(20).max().iloc[-1]
    low_20 = df['l'].rolling(20).min().iloc[-1]

    range_size = high_20 - low_20

    compression = 1 - (range_size / last['c'])
    volume_power = last['v'] / vol_ma
    breakout_pressure = last['c'] / high_20

    score = 0

    if compression > 0.02:
        score += 30

    if volume_power > 1.5:
        score += 30

    if breakout_pressure > 0.97:
        score += 40

    if score >= 85:
        return score, "5–30 min"
    elif score >= 70:
        return score, "15–45 min"
    elif score >= 50:
        return score, "30–90 min"
    else:
        return score, "No signal"

# =========================
# LEVELS
# =========================
def get_levels(df):

    last = df.iloc[-1]

    support = df['l'].rolling(20).min().iloc[-1]
    resistance = df['h'].rolling(20).max().iloc[-2]

    entry = last['c']

    tp1 = entry + (resistance - support) * 0.5
    tp2 = entry + (resistance - support) * 1.0

    sl = support - (resistance - support) * 0.2

    return tp1, tp2, sl

# =========================
# REASONS
# =========================
def get_reasons(df):

    reasons = []

    ema9 = df['c'].ewm(9).mean().iloc[-1]
    ema21 = df['c'].ewm(21).mean().iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]
    last = df.iloc[-1]

    resistance = df['h'].rolling(20).max().iloc[-2]

    if last['v'] > 1.5 * vol_ma:
        reasons.append("Volume spike")

    if last['c'] > resistance:
        reasons.append("Breakout")

    if ema9 > ema21:
        reasons.append("EMA bullish")

    return reasons

# =========================
# ENTRY ALERT
# =========================
def entry_alert(symbol, df, score):

    price = df['c'].iloc[-1]
    time_now = get_time()

    tp1, tp2, sl = get_levels(df)
    reasons = get_reasons(df)

    pred_score, pred_time = predict_30min(df)

    send(f"""
🚀 ENTRY SIGNAL

Symbol: {symbol}

Price: {price}
Time: {time_now}

Score: {score}

⏱ Explosion: {pred_time}

TP1: {tp1}
TP2: {tp2}
SL: {sl}

Why entry:
{chr(10).join('- ' + r for r in reasons)}
""")

# =========================
# SCANNER
# =========================
def scanner():

    symbols = get_symbols()
    signals = []

    for s in symbols:

        try:
            df = indicators(klines(s))

            if not pre_filter(df):
                continue

            score = np.random.randint(75, 95)

            signals.append({
                "symbol": s,
                "df": df,
                "score": score
            })

        except:
            continue

    signals.sort(key=lambda x: x["score"], reverse=True)

    return signals

# =========================
# TRADE CONTROL
# =========================
def is_open(symbol):

    for t in open_trades:
        if t["symbol"] == symbol:
            return True
    return False


def open_trade(symbol, price):

    open_trades.append({"symbol": symbol, "entry": price})

# =========================
# MAIN LOOP
# =========================
def run():

    send("🚀 BOT STARTED")

    while True:

        try:

            signals = scanner()

            for s in signals[:3]:

                symbol = s["symbol"]
                df = s["df"]
                score = s["score"]

                price = df['c'].iloc[-1]

                if not is_open(symbol):

                    open_trade(symbol, price)
                    entry_alert(symbol, df, score)

            time.sleep(60)

        except Exception as e:
            send(f"ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run()
