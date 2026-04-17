import ccxt
import time, pandas as pd, os, csv, threading
from datetime import datetime
import requests
import json

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
FILE_WATCH = "watch_results.csv"
FILE_EXPLOSIONS = "explosion_results.csv"

for f, h in [
    (FILE_ENTRIES, ["time","symbol","score","price","balance"]),
    (FILE_WATCH, ["time","symbol","entry","high","low","status"]),
    (FILE_EXPLOSIONS, ["time","symbol","entry","max","expected","status","time"])
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
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def send_doc(chat_id, file_path, caption):
    try:
        with open(file_path,'rb') as f:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f}
            )
    except:
        pass

# =========================
# BALANCE
# =========================
def get_balance():
    try:
        return exchange.fetch_balance()['total'].get('USDT',0)
    except:
        return 0

# =========================
# INDICATORS
# =========================
def calculate(df):
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20']*2)
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
        return "BUY" if bid > ask else "SELL"
    except:
        return "NONE"

# =========================
# LOGS
# =========================
def log_entry(sym, score, price, bal):
    csv.writer(open(FILE_ENTRIES,'a',newline='')).writerow([datetime.now(),sym,score,price,bal])

def log_watch(sym, entry):
    csv.writer(open(FILE_WATCH,'a',newline='')).writerow([
        datetime.now(),sym,entry,0,0,"WATCH"
    ])

def log_explosion(sym, entry, expected):
    csv.writer(open(FILE_EXPLOSIONS,'a',newline='')).writerow([
        datetime.now(),sym,entry,0,expected,"PENDING",0
    ])

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
# PROCESS ENGINE
# =========================
def process(sym):
    global active_trades

    try:
        t = exchange.fetch_ticker(sym)
        if t['quoteVolume'] < 2000000:
            return

        bars = exchange.fetch_ohlcv(sym,'15m',limit=120)
        df = pd.DataFrame(bars,columns=['t','o','h','l','close','volume'])
        df = calculate(df)

        price = df['close'].iloc[-1]

        score = 0

        if price > df['ema50'].iloc[-1]:
            score += 20

        if price >= df['bb_u'].iloc[-1]:
            score += 20

        vol = df['volume'].iloc[-1] / df['vol_avg'].iloc[-1]
        score += 30 if vol > 3 else 15 if vol > 2 else 5

        mom = df['momentum'].iloc[-1]
        if mom > 0.02:
            score += 20

        if order_book(sym) == "BUY":
            score += 20

        expected = 2.5  # simplified

        # =========================
        # WATCHLIST
        # =========================
        if 80 <= score < 90:
            watch_memory[sym] = price
            log_watch(sym, price)

        # =========================
        # ENTRY
        # =========================
        if score >= 90:

            bal = get_balance()

            with lock:
                if active_trades >= MAX_TRADES:
                    return
                active_trades += 1

            log_entry(sym,score,price,bal)

            send_msg(f"""
🚀 ENTRY
💎 {sym}
📊 Score {score}
💰 {price}
💵 {bal}
🛑 SL -3%
🔒 Secure +2%
""")

            threading.Thread(target=monitor,args=(sym,price),daemon=True).start()

    except:
        pass

# =========================
# TELEGRAM LISTENER (4 COMMANDS)
# =========================
def telegram_listener():
    last_id = 0

    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates").json()

            for u in r.get("result",[]):
                if u["update_id"] > last_id:
                    last_id = u["update_id"]

                    if "message" in u:
                        txt = u["message"].get("text","")
                        cid = u["message"]["chat"]["id"]

                        if txt == "/status":
                            send_msg(f"""
📊 STATUS

🚀 Trades: {active_trades}
💰 Balance: {get_balance()}
💥 System: RUNNING
""")

                        elif txt == "/get_entries":
                            send_doc(cid,FILE_ENTRIES,"📊 Entries")

                        elif txt == "/get_watchlist":
                            send_doc(cid,FILE_WATCH,"👀 Watchlist")

                        elif txt == "/get_explosions":
                            send_doc(cid,FILE_EXPLOSIONS,"💥 Explosions")

            time.sleep(3)
        except:
            time.sleep(5)

# =========================
# MAIN
# =========================
def main():
    print("🔥 ADEM FINAL BOT RUNNING")

    threading.Thread(target=telegram_listener,daemon=True).start()

    while True:
        try:
            exchange.load_markets()
            pairs = [s for s in exchange.symbols if s.endswith('/USDT')][:800]

            for sym in pairs:
                process(sym)

            time.sleep(60)

        except Exception as e:
            print(e)
            time.sleep(5)

if __name__ == "__main__":
    main()
