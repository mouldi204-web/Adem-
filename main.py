import ccxt
import pandas as pd
import numpy as np
import time
import threading
import os
import csv
from datetime import datetime
import requests

# =========================
# [1] الإعدادات الأساسية
# =========================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509" 
CSV_FILE = "signals_report.csv"

exchange = ccxt.gateio({'enableRateLimit': True})

# تهيئة ملف CSV
if not os.path.exists(CSV_FILE):
    pd.DataFrame(columns=['Time', 'Symbol', 'Score', 'Entry', 'Max_Rise%', 'Max_Drop%', 'Status', 'Details']).to_csv(CSV_FILE, index=False)

# =========================
# [2] نظام الإشعارات (Telegram)
# =========================
def send_msg(text):
    """دالة إرسال الرسائل النصية"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error sending msg: {e}")

def send_file():
    """دالة إرسال ملف النتائج"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    try:
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "rb") as f:
                requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})
    except Exception as e:
        print(f"Error sending file: {e}")

# =========================
# [3] المحرك الفني (سكور 60+)
# =========================
def calculate_adx(df, period=14):
    df = df.copy()
    df['h-l'] = df['h'] - df['l']
    df['h-pc'] = abs(df['h'] - df['c'].shift(1))
    df['l-pc'] = abs(df['l'] - df['c'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    plus_dm = np.where((df['h'] - df['h'].shift(1)) > (df['l'].shift(1) - df['l']), np.maximum(df['h'] - df['h'].shift(1), 0), 0)
    minus_dm = np.where((df['l'].shift(1) - df['l']) > (df['h'] - df['h'].shift(1)), np.maximum(df['l'].shift(1) - df['l'], 0), 0)
    tr_s = df['tr'].rolling(period).sum()
    plus_di = 100 * (pd.Series(plus_dm).rolling(period).sum() / tr_s)
    minus_di = 100 * (pd.Series(minus_dm).rolling(period).sum() / tr_s)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(period).mean()

def get_score(sym):
    try:
        df15 = pd.DataFrame(exchange.fetch_ohlcv(sym, '15m', limit=100), columns=['t','o','h','l','c','v'])
        df4h = pd.DataFrame(exchange.fetch_ohlcv(sym, '4h', limit=100), columns=['t','o','h','l','c','v'])
        df15['ma9'] = df15['c'].rolling(9).mean()
        df15['ma21'] = df15['c'].rolling(21).mean()
        df4h['ma200'] = df4h['c'].rolling(200).mean()
        l15, l4h = df15.iloc[-1], df4h.iloc[-1]
        score = 0
        desc = []
        if l4h['c'] > l4h['ma200']: score += 25; desc.append("Trend4H")
        if l15['c'] > l15['ma9'] > l15['ma21']: score += 25; desc.append("MOM")
        vol_avg = df15['v'].rolling(20).mean().iloc[-1]
        if l15['v'] > vol_avg * 1.5: score += 20; desc.append("VOL")
        adx = calculate_adx(df15).iloc[-1]
        if adx > 20: score += 15; desc.append("ADX")
        sma20 = df15['c'].rolling(20).mean()
        std20 = df15['c'].rolling(20).std()
        if (2 * std20 / sma20).iloc[-1] < 0.04: score += 15; desc.append("SQZ")
        return score, "|".join(desc)
    except: return 0, ""

# =========================
# [4] مراقبة السوق (Scanner)
# =========================
def run_scanner():
    # إشعار عند بداية المسح
    start_time = datetime.now().strftime("%H:%M:%S")
    send_msg(f"🔍 **بدء المسح الشامل الآن...**\n⏰ التوقيت: `{start_time}`\n📊 الأهداف: `1500 عملة` (USDT)")
    
    try:
        markets = exchange.load_markets()
        symbols = [s for s in markets if "/USDT" in s][:1500]
        found_count = 0

        for i, sym in enumerate(symbols):
            score, details = get_score(sym)
            if score >= 60:
                found_count += 1
                entry = exchange.fetch_ticker(sym)['last']
                with open(CSV_FILE, "a", newline="") as f:
                    csv.writer(f).writerow([datetime.now().strftime("%H:%M"), sym, score, entry, "0%", "0%", "WATCHING", details])
                
                # إشعار مباشر في حال وجود عملة قوية جداً
                if score >= 85:
                    send_msg(f"🔥 **فرصة ذهبية!**\nالعملة: #{sym.split('/')[0]}\nالسكور: `{score}`\nالسعر: `{entry}`")
            
            time.sleep(0.1) 

        send_msg(f"✅ **انتهى المسح بنجاح!**\n📈 عدد الفرص المكتشفة (60+): `{found_count}`\nأرسل `/file` لتحميل التقرير.")
    except Exception as e:
        send_msg(f"⚠️ **حدث خطأ أثناء المسح:**\n`{str(e)}`")

# =========================
# [5] مستمع الأوامر والتشغيل
# =========================
def telegram_bot():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            r = requests.get(url, params={'offset': last_id + 1, 'timeout': 30}).json()
            for up in r.get("result", []):
                last_id = up["update_id"]
                txt = up.get("message", {}).get("text", "").lower()
                
                if txt == "/scan":
                    threading.Thread(target=run_scanner).start()
                elif txt == "/file":
                    send_file()
                elif txt == "/etat":
                    send_msg(f"🤖 **حالة البوت:** متصل\n📡 **المنصة:** Gate.io")
        except: time.sleep(5)

if __name__ == "__main__":
    print("BOT RUNNING...")
    # إشعار عند بداية عمل البوت لأول مرة
    boot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    send_msg(f"🚀 **البوت في حالة تشغيل الآن!**\n📅 التاريخ: `{boot_time}`\n\nأرسل `/scan` لبدء فحص السوق.")
    telegram_bot()
