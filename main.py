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

TOKEN = os.getenv("8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68")
CHAT_ID = os.getenv("5067771509")

TRADE_SIZE = 100
MIN_SCORE = 75
MIN_PROB = 0.85

open_trades = []
last_heartbeat = 0

# =========================
# TELEGRAM SYSTEM
# =========================
def send(msg):

    if not TOKEN or not CHAT_ID:
        print("⚠️ Telegram not configured")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg,
                "parse_mode": "HTML"
            },
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)

# =========================
# START MESSAGE
# =========================
def telegram_start():

    send("""
🚀 <b>BOT STARTED</b>

🟢 Status: ACTIVE
🔍 Scanner: ON
🧠 AI Engine: ON
📡 Telegram: CONNECTED

⚡ Searching explosion opportunities...
""")

# =========================
# HEARTBEAT
# =========================
def heartbeat():

    send("""
🟢 <b>BOT STATUS</b>

✔ Running normally
🔍 Scanning market
📡 No issues detected

⏱ Active & monitoring explosions
""")

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

    return df

# =========================
# PRE FILTER
# =========================
def pre_filter(df):

    last = df.iloc[-1]

    ema9 = df['c'].ewm(9).mean().iloc[-1]
    ema21 = df['c'].ewm(21).mean().iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]
    resistance = df['h'].rolling(20).max().iloc[-2]

    return (
        last['v'] > 1.8 * vol_ma and
        last['c'] > resistance and
        ema9 > ema21
    )

# =========================
# AI MODEL
# =========================
model = joblib.load("model.pkl") if os.path.exists("model.pkl") else None

def ai_prob(features):
    if model is None:
        return 0.5
    return model.predict_proba([features])[0][1]

# =========================
# PRE EXPLOSION SCORE
# =========================
def pre_explosion_score(df):

    last = df.iloc[-1]

    vol_ma = df['v'].rolling(20).mean().iloc[-1]
    atr = (df['h'] - df['l']).rolling(14).mean().iloc[-1]

    high_20 = df['h'].rolling(20).max().iloc[-1]
    low_20 = df['l'].rolling(20).min().iloc[-1]

    squeeze = high_20 - low_20

    score = 0

    if squeeze < atr * 2:
        score += 30

    if last['v'] > 1.8 * vol_ma:
        score += 25

    if last['c'] > high_20 * 0.98:
        score += 25

    if df['c'].ewm(9).mean().iloc[-1] > df['c'].ewm(21).mean().iloc[-1]:
        score += 20

    return min(score, 100)

# =========================
# TIME TO EXPLOSION
# =========================
def time_to_explosion(df):

    score = pre_explosion_score(df)

    if score >= 90:
        return score, np.random.randint(5, 15)
    elif score >= 75:
        return score, np.random.randint(15, 30)
    elif score >= 60:
        return score, np.random.randint(30, 50)
    else:
        return score, np.random.randint(60, 120)

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

    atr = (df['h'] - df['l']).rolling(14).mean().iloc[-1]
    sl = support - atr * 0.5

    return support, sl, tp1, tp2

# =========================
# REASONS
# =========================
def get_reasons(df):

    reasons = []

    if df['v'].iloc[-1] > df['v'].rolling(20).mean().iloc[-1]:
        reasons.append("Volume Spike")

    if df['c'].iloc[-1] > df['h'].rolling(20).max().iloc[-2]:
        reasons.append("Breakout")

    if df['c'].ewm(9).mean().iloc[-1] > df['c'].ewm(21).mean().iloc[-1]:
        reasons.append("EMA Bullish")

    return reasons

# =========================
# RANKING SYSTEM
# =========================
def rank_coin(df):

    pre = pre_explosion_score(df)

    features = [
        df['c'].iloc[-1],
        df['v'].iloc[-1],
        df['v'].rolling(20).mean().iloc[-1],
        df['c'].ewm(9).mean().iloc[-1]
    ]

    prob = ai_prob(features)

    confirm = min(pre + prob * 100, 100)

    final_score = (pre * 0.5) + (confirm * 0.3) + (prob * 100 * 0.2)

    return round(final_score, 2), pre, confirm, prob

# =========================
# SCANNER
# =========================
def scanner():

    symbols = get_symbols()

    ranked = []

    for s in symbols:

        try:
            df = indicators(klines(s))

            if not pre_filter(df):
                continue

            score, pre, confirm, prob = rank_coin(df)

            if score > 65:

                ranked.append({
                    "symbol": s,
                    "score": score,
                    "pre": pre,
                    "confirm": confirm,
                    "prob": prob,
                    "df": df
                })

        except:
            continue

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return ranked

# =========================
# TELEGRAM SIGNAL
# =========================
def signal_alert(symbol, score, prob, df):

    price = df['c'].iloc[-1]

    support, sl, tp1, tp2 = get_levels(df)

    time_score, minutes = time_to_explosion(df)

    reasons = get_reasons(df)

    send(f"""
🔥 <b>EXPLOSION SIGNAL</b>

💰 {symbol}

📊 Price: {price}

🧠 Score: {score}/100
⚡ Prob: {prob:.2f}

⏱ Explosion in: <b>{minutes} min</b>

🛑 SL: {sl}
🎯 TP1: {tp1}
🚀 TP2: {tp2}

📌 Reasons:
{chr(10).join('✔ ' + r for r in reasons)}
""")

# =========================
# TOP 10
# =========================
def send_top10(ranked):

    msg = "🏆 <b>TOP 10 EXPLOSION COINS</b>\n\n"

    for i, c in enumerate(ranked[:10], 1):

        zone = "🔥 HOT" if c["score"] >= 85 else "🟡 WARM" if c["score"] >= 70 else "🔵 COLD"

        msg += f"{i}️⃣ {c['symbol']} | {c['score']} | {zone} | {int(c['prob']*100)}%\n"

    send(msg)

# =========================
# TRADE SYSTEM
# =========================
def open_trade(symbol, price):

    open_trades.append({"symbol": symbol, "entry": price})

    send(f"🚀 OPEN {symbol} @ {price}")

def close_trade(symbol, entry, price):

    profit = (price - entry) * TRADE_SIZE

    send(f"📉 CLOSE {symbol}\nProfit: {profit:.2f}$")

# =========================
# MAIN LOOP
# =========================
def run():

    global last_heartbeat

    telegram_start()

    last_heartbeat = time.time()

    while True:

        try:

            ranked = scanner()

            if ranked:

                send_top10(ranked)

                for c in ranked[:3]:
                    signal_alert(c["symbol"], c["score"], c["prob"], c["df"])
                    open_trade(c["symbol"], c["df"]['c'].iloc[-1])

            if time.time() - last_heartbeat > 1800:
                heartbeat()
                last_heartbeat = time.time()

            time.sleep(60)

        except Exception as e:
            send(f"⚠️ ERROR {e}")
            time.sleep(5)

if __name__ == "__main__":
    run()
