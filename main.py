import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# =========================
# CONFIG
# =========================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "-1003692815602"

exchange = ccxt.gateio({'enableRateLimit': True})

MAX_TRADES = 10
active_trades = 0
lock = threading.Lock()

# =========================
# FILES
# =========================
FILE_ENTRIES = "entries.csv"
FILE_WATCH = "watchlist.csv"
FILE_EXPLOSIONS = "explosions.csv"
FILE_RESULTS = "explosion_results.csv"

for f, h in [
    (FILE_ENTRIES, ["time","symbol","score","price","balance"]),
    (FILE_WATCH, ["time","symbol","score","price"]),
    (FILE_EXPLOSIONS, ["time","symbol","score","expected"]),
    (FILE_RESULTS, ["time","symbol","entry","max","expected","status","time"])
]:
    if not os.path.exists(f):
        with open(f,'w',newline='') as file:
            csv.writer(file).writerow(h)

# =========================
# MEMORY
# =========================
watch_memory = {}
explosion_memory = {}

# =========================
# TELEGRAM
# =========================
def send_msg(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text}
        )
    except:
        pass

def send_channel(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHANNEL_ID, "text": text}
        )
    except:
        pass

# =========================
# BALANCE
# =========================
def get_balance():
    try:
        bal = exchange.fetch_balance()
        return bal['total'].get('USDT', 0)
    except:
        return 0

# =========================
# INDICATORS
# =========================
def calculate(df):
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20'] * 2)

    df['vol_avg'] = df['volume'].rolling(50).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['momentum'] = df['close'].pct_change(3)
    return df

# =========================
# ORDER BOOK
# =========================
def order_book(sym):
    try:
        ob = exchange.fetch_order_book(sym, limit=20)
        bid = sum([b[1] for b in ob['bids'][:10]])
        ask = sum([a[1] for a in ob['asks'][:10]])

        if ask == 0:
            return "NONE"

        ratio = bid / ask

        if ratio > 1.5:
            return "BUY"
        elif ratio < 0.7:
            return "SELL"
        return "NEUTRAL"
    except:
        return "NONE"

# =========================
# LOGS
# =========================
def log_entry(sym, score, price, bal):
    with open(FILE_ENTRIES,'a',newline='') as f:
        csv.writer(f).writerow([datetime.now(),sym,score,price,bal])

def log_watch(sym, score, price):
    with open(FILE_WATCH,'a',newline='') as f:
        csv.writer(f).writerow([datetime.now(),sym,score,price])

def log_explosion(sym, score, expected):
    with open(FILE_EXPLOSIONS,'a',newline='') as f:
        csv.writer(f).writerow([datetime.now(),sym,score,expected])

# =========================
# TRADE MONITOR
# =========================
def monitor(sym, entry):
    global active_trades

    highest = entry
    sl = entry * 0.97
    secure = entry * 1.02

    while True:
        try:
            price = exchange.fetch_ticker(sym)['last']
            pnl = (price-entry)/entry*100

            if price > highest:
                highest = price
                sl = highest * 0.98

            if price >= secure:
                sl = entry

            if price <= sl or pnl >= 15:
                send_msg(f"🏁 CLOSED {sym} | {pnl:.2f}%")
                break

            time.sleep(10)
        except:
            pass

    with lock:
        active_trades -= 1

# =========================
# EXPLOSION TRACKER
# =========================
def update_explosions():
    while True:
        try:
            for sym in list(explosion_memory.keys()):

                d = explosion_memory[sym]

                price = exchange.fetch_ticker(sym)['last']
                entry = d["entry"]

                change = (price-entry)/entry*100
                d["max"] = max(d["max"], change)

                expected = d["expected"]

                if change >= expected:
                    status = "BEAT_EXPECTATION"
                elif change >= 5:
                    status = "SUCCESS"
                elif change <= -3:
                    status = "FAIL"
                else:
                    continue

                t = (datetime.now()-d["time"]).seconds/60

                with open(FILE_RESULTS,'a',newline='') as f:
                    csv.writer(f).writerow([
                        datetime.now(),sym,entry,
                        d["max"],expected,status,
                        f"{t:.1f}"
                    ])

                send_msg(f"""
💥 EXPLOSION RESULT
{sym}
📈 Actual: {d['max']:.2f}%
🎯 Expected: {expected:.2f}%
⏱ {t:.1f} min
📊 {status}
""")

                del explosion_memory[sym]

            time.sleep(20)

        except:
            time.sleep(5)

# =========================
# WATCH TRACKER
# =========================
def update_watch():
    while True:
        try:
            for sym in list(watch_memory.keys()):

                price = exchange.fetch_ticker(sym)['last']
                entry = watch_memory[sym]["entry"]

                change = (price-entry)/entry*100

                watch_memory[sym]["high"] = max(watch_memory[sym].get("high",0), change)
                watch_memory[sym]["low"] = min(watch_memory[sym].get("low",0), change)

                if change >= 5:
                    status = "SUCCESS"
                elif change <= -3:
                    status = "FAIL"
                else:
                    continue

                with open("watch_results.csv","a",newline="") as f:
                    csv.writer(f).writerow([
                        datetime.now(),sym,entry,
                        watch_memory[sym]["high"],
                        watch_memory[sym]["low"],
                        status
                    ])

                del watch_memory[sym]

            time.sleep(20)

        except:
            time.sleep(5)

# =========================
# ULTRA SCORE ENGINE
# =========================
def process(sym):
    global active_trades

    try:
        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 2_000_000:
            return

        bars = exchange.fetch_ohlcv(sym,'15m',limit=120)
        df = pd.DataFrame(bars, columns=['t','o','h','l','close','volume'])
        df = calculate(df)

        price = df['close'].iloc[-1]

        # ATR
        atr = (df['high']-df['low']).rolling(14).mean().iloc[-1]

        # =========================
        # SCORE 2.0
        # =========================
        score = 0

        trend_up = price > df['ema50'].iloc[-1]
        if trend_up:
            score += 20

        if price >= df['bb_u'].iloc[-1]:
            score += 20

        rel_vol = df['volume'].iloc[-1] / df['vol_avg'].iloc[-1]
        if rel_vol > 3:
            score += 30
        elif rel_vol > 2:
            score += 20
        elif rel_vol > 1.5:
            score += 10

        momentum = df['momentum'].iloc[-1]
        if 0.01 < momentum < 0.05:
            score += 20

        ob = order_book(sym)
        if ob == "BUY":
            score += 20
        elif ob == "SELL":
            score -= 15

        bb_width = (df['bb_u'] - df['sma20']) / df['sma20']
        squeeze = 1 - bb_width.iloc[-1]

        if squeeze > 0.85:
            score += 20
        elif squeeze > 0.75:
            score += 10

        expected = (atr/price)*100*3

        # =========================
        # EXPLOSION ALERT
        # =========================
        if score >= 75 and squeeze > 0.85:

            explosion_memory[sym] = {
                "entry": price,
                "expected": expected,
                "time": datetime.now(),
                "max": 0
            }

            log_explosion(sym, score, expected)

            send_msg(f"💥 EXPLOSION ALERT\n{sym}\n+{expected:.2f}% expected")

        # =========================
        # WATCHLIST
        # =========================
        elif 80 <= score < 90:

            watch_memory[sym] = {
                "entry": price,
                "high": 0,
                "low": 0
            }

            log_watch(sym, score, price)

        # =========================
        # ENTRY
        # =========================
        if score >= 90:

            balance = get_balance()

            with lock:
                if active_trades >= MAX_TRADES:
                    return
                active_trades += 1

            log_entry(sym, score, price, balance)

            send_msg(f"""
🚀 ENTRY SIGNAL
💎 {sym}
📊 Score: {score}/100
📈 Expected: +{expected:.2f}%
💰 Price: {price}
💵 Balance: {balance:.2f}
🛑 SL: -3%
🔒 Secure: +2%
""")

            threading.Thread(target=monitor,
                             args=(sym, price),
                             daemon=True).start()

    except:
        pass

# =========================
# MAIN
# =========================
def main():
    print("🔥 ADEM EXPLOSION AI ULTRA FINAL RUNNING")

    threading.Thread(target=update_explosions, daemon=True).start()
    threading.Thread(target=update_watch, daemon=True).start()

    while True:
        try:
            exchange.load_markets()
            pairs = [s for s in exchange.symbols if s.endswith('/USDT')][:1000]

            for sym in pairs:
                process(sym)

            time.sleep(60)

        except Exception as e:
            print(e)
            time.sleep(5)

if __name__ == "__main__":
    main()
