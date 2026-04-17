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

# ✅ تهيئة ملف CSV بشكل صحيح مع التأكد من وجود الأعمدة
def init_csv():
    """تهيئة ملف CSV مع الأعمدة إذا كان غير موجود أو فارغ"""
    if not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0:
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Time', 'Symbol', 'Score', 'Entry', 'Max_Rise%', 'Max_Drop%', 'Status', 'Details'])
        print(f"✅ ملف CSV تم إنشاؤه: {CSV_FILE}")

init_csv()

# =========================
# [2] نظام الإشعارات (Telegram)
# =========================
def send_msg(text):
    """دالة إرسال الرسائل النصية"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Error sending msg: {e}")

def send_file():
    """دالة إرسال ملف النتائج"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    try:
        if os.path.exists(CSV_FILE) and os.path.getsize(CSV_FILE) > 0:
            with open(CSV_FILE, "rb") as f:
                requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f}, timeout=10)
            send_msg("📁 **تم إرسال ملف التقرير بنجاح!**")
        else:
            send_msg("⚠️ **الملف فارغ أو غير موجود!**")
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
        
        # التأكد من وجود بيانات كافية
        if len(df15) < 50 or len(df4h) < 50:
            return 0, ""
            
        df15['ma9'] = df15['c'].rolling(9).mean()
        df15['ma21'] = df15['c'].rolling(21).mean()
        df4h['ma200'] = df4h['c'].rolling(200).mean()
        l15, l4h = df15.iloc[-1], df4h.iloc[-1]
        score = 0
        desc = []
        
        if l4h['c'] > l4h['ma200']: 
            score += 25
            desc.append("Trend4H")
        if l15['c'] > l15['ma9'] > l15['ma21']: 
            score += 25
            desc.append("MOM")
        
        vol_avg = df15['v'].rolling(20).mean().iloc[-1]
        if l15['v'] > vol_avg * 1.5: 
            score += 20
            desc.append("VOL")
        
        adx = calculate_adx(df15).iloc[-1]
        if adx > 20: 
            score += 15
            desc.append("ADX")
        
        sma20 = df15['c'].rolling(20).mean()
        std20 = df15['c'].rolling(20).std()
        if len(sma20) > 0 and len(std20) > 0 and (2 * std20 / sma20).iloc[-1] < 0.04: 
            score += 15
            desc.append("SQZ")
            
        return score, "|".join(desc)
    except Exception as e:
        print(f"Error in get_score for {sym}: {e}")
        return 0, ""

# =========================
# [4] مراقبة السوق (Scanner)
# =========================
def run_scanner():
    """المسح الشامل مع تحسين الكتابة في CSV"""
    start_time = datetime.now().strftime("%H:%M:%S")
    send_msg(f"🔍 **بدء المسح الشامل الآن...**\n⏰ التوقيت: `{start_time}`\n📊 الأهداف: `1500 عملة` (USDT)")
    
    try:
        markets = exchange.load_markets()
        symbols = [s for s in markets if "/USDT" in s][:1500]
        found_count = 0
        results = []  # تخزين النتائج مؤقتاً

        for i, sym in enumerate(symbols):
            score, details = get_score(sym)
            if score >= 60:
                found_count += 1
                entry = exchange.fetch_ticker(sym)['last']
                row = [datetime.now().strftime("%H:%M"), sym, score, entry, "0%", "0%", "WATCHING", details]
                results.append(row)
                
                # ✅ كتابة فورية في الملف مع flush
                with open(CSV_FILE, "a", newline="", encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
                    f.flush()  # تأكيد الكتابة الفورية
                
                print(f"✅ تمت الكتابة: {sym} - Score: {score}")  # للتتبع
                
                # إشعار مباشر في حال وجود عملة قوية جداً
                if score >= 85:
                    send_msg(f"🔥 **فرصة ذهبية!**\nالعملة: #{sym.split('/')[0]}\nالسكور: `{score}`\nالسعر: `{entry}`")
            
            time.sleep(0.1)
        
        # ✅ إذا لم يتم العثور على أي عملة، اكتب سجل توضيحي
        if found_count == 0:
            with open(CSV_FILE, "a", newline="", encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().strftime("%H:%M"), "NO_SIGNAL", 0, 0, "0%", "0%", "SCAN_COMPLETED", f"تم فحص {len(symbols)} عملة"])
                f.flush()
            send_msg(f"⚠️ **لم يتم العثور على فرص بدرجة 60+**\n📊 تم فحص `{len(symbols)}` عملة")

        send_msg(f"✅ **انتهى المسح بنجاح!**\n📈 عدد الفرص المكتشفة (60+): `{found_count}`\nأرسل `/file` لتحميل التقرير.")
        
        # إرسال إحصائية بعد المسح
        if found_count > 0:
            send_msg(f"📊 **ملخص المسح:**\n✅ تم تسجيل `{found_count}` فرصة في ملف CSV")
            
    except Exception as e:
        error_msg = f"⚠️ **حدث خطأ أثناء المسح:**\n`{str(e)}`"
        print(error_msg)
        send_msg(error_msg)
        
        # تسجيل الخطأ في CSV
        with open(CSV_FILE, "a", newline="", encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.now().strftime("%H:%M"), "ERROR", 0, 0, "0%", "0%", "SCAN_ERROR", str(e)])
            f.flush()

# =========================
# [5] مستمع الأوامر والتشغيل
# =========================
def telegram_bot():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            r = requests.get(url, params={'offset': last_id + 1, 'timeout': 30}, timeout=35)
            data = r.json()
            
            for up in data.get("result", []):
                last_id = up["update_id"]
                txt = up.get("message", {}).get("text", "").lower()
                
                if txt == "/scan":
                    send_msg("🔄 **جاري بدء المسح...** يرجى الانتظار")
                    threading.Thread(target=run_scanner).start()
                elif txt == "/file":
                    send_file()
                elif txt == "/etat":
                    # التحقق من حالة الملف
                    if os.path.exists(CSV_FILE):
                        size = os.path.getsize(CSV_FILE)
                        send_msg(f"🤖 **حالة البوت:** متصل\n📡 **المنصة:** Gate.io\n📁 **حجم ملف CSV:** {size} bytes")
                    else:
                        send_msg(f"🤖 **حالة البوت:** متصل\n📡 **المنصة:** Gate.io\n⚠️ **ملف CSV غير موجود**")
        except Exception as e:
            print(f"Telegram bot error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("🚀 BOT RUNNING...")
    boot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    send_msg(f"🚀 **البوت في حالة تشغيل الآن!**\n📅 التاريخ: `{boot_time}`\n\nأرسل `/scan` لبدء المسح\nأرسل `/file` للحصول على التقرير\nأرسل `/etat` لمعرفة حالة البوت")
    
    # تشغيل البوت
    telegram_bot()
