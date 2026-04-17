import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- [1] الإعدادات الأساسية ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

TRADING_LOG = 'market_radar_v57.csv'
INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
used_balance = 0.0

active_monitoring = {}
current_market_regime = "Unknown"

app = Flask('')
@app.route('/')
def home(): return f"Omega v57.0 Active. Market: {current_market_regime}"

# --- [2] وظائف التحليل المتقدمة ---

def get_technical_data(symbol):
    try:
        # جلب الشموع لتحليل RSI و EMA وانفجار السيولة
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=5min"
        res = requests.get(url, timeout=10).json()
        if 'data' not in res or len(res['data']) < 20: return 50, 0, 0, 1.0
        
        # ترتيب البيانات من الأقدم للأحدث
        candles = res['data'][::-1]
        closes = [float(c[2]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        
        # حساب RSI
        diffs = np.diff(closes)
        gains = [d if d > 0 else 0 for d in diffs]
        losses = [-d if d < 0 else 0 for d in diffs]
        avg_gain = sum(gains[-14:])/14; avg_loss = sum(losses[-14:])/14
        rsi = 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100
        
        # حساب EMA20
        ema_20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        
        # حساب انفجار السيولة (حجم آخر شمعة مقارنة بمتوسط آخر 10 شموع)
        avg_vol = sum(volumes[-11:-1]) / 10
        vol_spike = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
        
        return rsi, ema_20, closes[-1], vol_spike
    except: return 50, 0, 0, 1.0

def update_market_regime():
    global current_market_regime
    while True:
        try:
            url = f"{BASE_URL}/api/v1/market/candles?symbol=BTC-USDT&type=15min"
            res = requests.get(url, timeout=10).json()
            closes = [float(c[2]) for c in res['data'][:20]]
            ema_20 = pd.Series(closes[::-1]).ewm(span=20, adjust=False).mean().iloc[-1]
            current_market_regime = "BULLISH 🟢" if closes[0] > ema_20 else "BEARISH 🔴"
        except: pass
        time.sleep(300)

# --- [3] نظام التسجيل والرادار ---

def log_radar(sym, score, rsi, spike, action, reason="N/A", result_pct=None):
    headers = [
        'Time', 'Market', 'Symbol', 'Score', 'RSI', 'Vol_Spike', 
        'Action', 'Reason', 'Final_Result_%'
    ]
    file_exists = os.path.isfile(TRADING_LOG)
    with open(TRADING_LOG, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists: writer.writeheader()
        writer.writerow({
            'Time': datetime.now().strftime('%H:%M:%S'),
            'Market': current_market_regime, 'Symbol': sym,
            'Score': score, 'RSI': round(rsi, 1), 'Vol_Spike': f"{spike:.2f}x",
            'Action': action, 'Reason': reason,
            'Final_Result_%': result_pct if result_pct else ""
        })

# --- [4] محرك المراقبة والقرار ---

def performance_judger():
    global current_balance, used_balance
