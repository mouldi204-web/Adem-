import pandas as pd
import numpy as np
import requests
import time
import sqlite3
import threading
from flask import Flask
import joblib
import os

# =========================
# KEEP ALIVE SERVER
# =========================
app = Flask("")

@app.route("/")
def home():
    return "Bot is alive"

def run_server():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = threading.Thread(target=run_server)
    t.start()

keep_alive()

# =========================
# CONFIG
# =========================
BASE_URL = "https://api.kucoin.com"

BALANCE = 500
TRADE_AMOUNT = 100
MAX_TRADES = 5

open_trades = []

# =========================
# TELEGRAM
# =========================
TELEGRAM_TOKEN = "PUT_TOKEN"
CHAT_ID = "PUT_CHAT_ID"

def send(msg):
    print(msg)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# =========================
# DATABASE (SQLite)
# =========================
conn = sqlite3.connect("trades.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    entry REAL,
    amount REAL,
    status TEXT,
    profit REAL DEFAULT 0
)
""")
conn.commit()

def save_trade(symbol, entry, amount):
    cursor.execute("""
    INSERT INTO trades (symbol, entry, amount, status)
    VALUES (?, ?, ?, 'OPEN')
    """, (symbol, entry, amount))
    conn.commit()

def close_trade_db(symbol, profit):
    cursor.execute("""
    UPDATE trades
    SET status='CLOSED', profit=?
    WHERE symbol=? AND status='OPEN'
    """, (profit, symbol))
    conn.commit()

def load_trades():
    cursor.execute("SELECT symbol, entry, amount FROM trades WHERE status='OPEN'")
    return cursor.fetchall()

# =========================
# LOAD MODEL (ML)
# =========================
# model.pkl يجب وضعه بجانب main.py
if os.path.exists("model.pkl"):
    model = joblib.load("model.pkl")
else:
    model = None

# =========================
# DATA
# =========================
def get_symbols():
    data = requests.get(BASE_URL + "/api/v1/symbols").json()['data']
    return [s['symbol'] for s in data if s['quoteCurrency'] == 'USDT'][:20]

def get_klines(symbol):
    url = BASE_URL + f"/api/v1/market/candles?type=5min&symbol={symbol}"
    data = requests.get(url).json()['data']

    df = pd.DataFrame(data, columns=[
        'time','open','close','high','low','volume','turnover'
    ])

    df = df.iloc[::-1]

    for col in ['open','close','high','low','volume']:
        df[col] = df[col].astype(float)

    return df

# =========================
# FEATURES (ML)
# =========================
def make_features(df):
    df['return'] = df['close'].pct_change()
    df['ema10'] = df['close'].ewm(span=10).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['vol_ma'] = df['volume'].rolling(20).mean()

    last = df.iloc[-1]

    return np.array([[
        last['return'],
        last['ema10'],
        last['ema50'],
        last['volume'],
        last['vol_ma']
    ]])

def predict(df):
    if model is None:
        return 0.5  # fallback

    X = make_features(df)
    return model.predict_proba(X)[0][1]

# =========================
# INDICATORS
# =========================
def analyze(df):
    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()

    df['vol_ma'] = df['volume'].rolling(20).mean()

    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_width'] = df['bb_std'] * 2

    df['atr'] = (df['high'] - df['low']).rolling(14).mean()

    return df

# =========================
# SCORE
# =========================
def get_score(df):

    last = df.iloc[-1]

    score = 0

    if last['volume'] > 2 * last['vol_ma']:
        score += 3

    if last['close'] > df['high'].rolling(20).max().iloc[-2]:
        score += 3

    if last['close'] > last['ema50']:
        score += 2

    if df['atr'].iloc[-1] > df['atr'].rolling(20).mean().iloc[-1]:
        score += 2

    return score

# =========================
# TRAILING AI EXIT
# =========================
def ai_exit(df, trade):

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0

    if last['close'] < last['ema20']:
        score += 3

    if last['volume'] < df['volume'].rolling(10).mean().iloc[-1]:
        score += 2

    if prev['close'] > last['close']:
        score += 2

    return score

# =========================
# TRADE FUNCTIONS
# =========================
def open_trade(symbol, price):
    global BALANCE

    if len(open_trades) >= MAX_TRADES:
        return

    trade = {
        "symbol": symbol,
        "entry": price,
        "amount": TRADE_AMOUNT,
        "highest": price,
        "trail": False,
        "partial": False,
        "sl": price * 0.98
    }

    open_trades.append(trade)
    save_trade(symbol, price, TRADE_AMOUNT)

    BALANCE -= TRADE_AMOUNT

    send(f"🟢 OPEN {symbol} @ {price}\nBalance: {BALANCE}")

# =========================
# CHECK TRADES (AI + TRAILING)
# =========================
def check_trades():

    global BALANCE

    for trade in open_trades[:]:

        df = get_klines(trade['symbol'])
        df = analyze(df)

        price = df['close'].iloc[-1]
        entry = trade['entry']
        atr = df['atr'].iloc[-1]

        # ===== Break-even =====
        if price >= entry * 1.025:
            trade['sl'] = entry

        # ===== Partial TP =====
        if not trade['partial'] and price >= entry * 1.04:
            profit = trade['amount'] * 0.04 * 0.5
            BALANCE += profit
            trade['amount'] *= 0.5
            trade['partial'] = True
            send(f"💸 Partial TP {trade['symbol']} +{profit:.2f}$")

        # ===== Trailing =====
        if price >= entry * 1.03:
            trade['trail'] = True

        if trade['trail']:
            if price > trade['highest']:
                trade['highest'] = price

            trail_stop = trade['highest'] - atr * 1.5

            if price <= trail_stop:
                profit = trade['amount'] * ((price - entry) / entry)

                BALANCE += trade['amount'] + profit

                close_trade_db(trade['symbol'], profit)
                open_trades.remove(trade)

                send(f"🏁 EXIT {trade['symbol']} PROFIT {profit:.2f}$")
                continue

        # ===== AI EXIT =====
        if ai_exit(df, trade) >= 5:
            profit = trade['amount'] * ((price - entry) / entry)

            BALANCE += trade['amount'] + profit

            close_trade_db(trade['symbol'], profit)
            open_trades.remove(trade)

            send(f"🤖 AI EXIT {trade['symbol']} {profit:.2f}$")
            continue

        # ===== Stop Loss =====
        if price <= trade['sl']:
            loss = trade['amount'] * 0.02

            BALANCE += trade['amount'] - loss

            close_trade_db(trade['symbol'], -loss)
            open_trades.remove(trade)

            send(f"❌ SL {trade['symbol']} -{loss}$")

# =========================
# BOT LOOP
# =========================
def run():

    global BALANCE

    send("🚀 FULL AI BOT STARTED")

    # restore trades
    restored = load_trades()

    for t in restored:
        open_trades.append({
            "symbol": t[0],
            "entry": t[1],
            "amount": t[2],
            "highest": t[1],
            "trail": False,
            "partial": False,
            "sl": t[1] * 0.98
        })

    send(f"♻ Restored {len(restored)} trades")

    while True:

        try:
            check_trades()

            symbols = get_symbols()

            for symbol in symbols:

                df = get_klines(symbol)
                df = analyze(df)

                score = get_score(df)
                prob = predict(df)

                if score >= 4 and prob > 0.65:
                    price = df['close'].iloc[-1]
                    open_trade(symbol, price)

                time.sleep(0.3)

        except Exception as e:
            print(e)

        time.sleep(60)

if __name__ == "__main__":
    run()
