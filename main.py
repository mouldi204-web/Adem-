import ccxt
import pandas as pd
import numpy as np
import time
import threading
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# CONFIG
# =========================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CSV_FILE = "signals.csv"

exchange = ccxt.gateio({'enableRateLimit': True})

# =========================
# SCORE ENGINE HELPERS
# =========================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calculate_adx(df, period=14):
    high = df['h']
    low = df['l']

    tr = (high - low)
    atr = tr.rolling(period).mean()

    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(period).mean()


# =========================
# SCORE FUNCTION
# =========================
def calculate_score(sym):
    try:
        df15 = pd.DataFrame(
            exchange.fetch_ohlcv(sym, '15m', limit=200),
            columns=['t','o','h','l','c','v']
        )

        df4h = pd.DataFrame(
            exchange.fetch_ohlcv(sym, '4h', limit=300),
            columns=['t','o','h','l','c','v']
        )

        df15 = df15.dropna()
        df4h = df4h.dropna()

        df15['ma9'] = df15['c'].rolling(9).mean()
        df15['ma21'] = df15['c'].rolling(21).mean()
        df15['rsi'] = calculate_rsi(df15['c'])
        df4h['ma200'] = df4h['c'].rolling(200).mean()

        l15 = df15.iloc[-1]
        l4h = df4h.iloc[-1]

        score = 0
        details = []

        # Trend
        if not pd.isna(l4h['ma200']) and l4h['c'] > l4h['ma200']:
            score += 25
            details.append("Trend")

        # Momentum
        if l15['c'] > l15['ma9'] > l15['ma21']:
            score += 20
            details.append("Momentum")

        # Volume
        avg_vol = df15['v'].rolling(20).mean().iloc[-1]
        if l15['v'] > avg_vol * 1.5:
            score += 15
            details.append("Volume")

        # ADX
        adx = calculate_adx(df15).iloc[-1]
        if adx > 20:
            score += 15
            details.append("ADX")

        # Squeeze
        sma20 = df15['c'].rolling(20).mean()
        std20 = df15['c'].rolling(20).std()
        bbw = (2 * std20 / sma20)

        if bbw.iloc[-1] < 0.04:
            score += 15
            details.append("Squeeze")

        # RSI filter
        if not pd.isna(l15['rsi']):
            if 45 < l15['rsi'] < 70:
                score += 10
            elif l15['rsi'] > 75:
                score -= 10

        return max(0, min(100, score)), "|".join(details)

    except Exception as e:
        print("Score error:", sym, e)
        return 0, ""


# =========================
# SCANNER + TRACKER
# =========================
def scan_market():
    print("START SCAN...")

    markets = exchange.load_markets()
    symbols = [s for s in markets if "/USDT" in s]

    results = []

    for i, sym in enumerate(symbols[:1500]):
        try:
            score, details = calculate_score(sym)

            if score >= 60:

                ohlcv = exchange.fetch_ohlcv(sym, '15m', limit=50)
                closes = [x[4] for x in ohlcv]

                entry = closes[-1]
                max_price = max(closes)
                min_price = min(closes)

                max_pump = ((max_price - entry) / entry) * 100
                max_dump = ((min_price - entry) / entry) * 100

                # RULE ENGINE
                if max_pump >= 5 and max_dump > -3:
                    status = "SUCCESS"
                elif max_dump <= -3 and max_pump < 5:
                    status = "FAIL"
                else:
                    status = "PENDING"

                results.append({
                    "symbol": sym,
                    "score": score,
                    "entry_price": entry,
                    "max_pump_%": round(max_pump, 2),
                    "max_dump_%": round(max_dump, 2),
                    "status": status,
                    "details": details,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

            print(f"{i}/1500 {sym} => {score}")

            time.sleep(0.2)

        except Exception as e:
            print("ERR:", sym, e)

    df = pd.DataFrame(results)
    df.to_csv(CSV_FILE, index=False)

    print("SCAN COMPLETE")


# =========================
# TELEGRAM BOT
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot ready: /scan /file")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scanning started...")

    threading.Thread(target=scan_market).start()


async def file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_document(open(CSV_FILE, "rb"))
    except:
        await update.message.reply_text("No file yet. Run /scan first.")


# =========================
# RUN BOT
# =========================
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("scan", scan))
app.add_handler(CommandHandler("file", file))

print("BOT RUNNING...")
app.run_polling()
