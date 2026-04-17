import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# [1] الإعدادات الأساسية (تأكد من الـ Token)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 
exchange = ccxt.gateio({'enableRateLimit': True})

FILE_ACTIVE = 'active_trades.csv'
FILE_RESULTS = 'scanner_results.csv'
MAX_VIRTUAL_TRADES = 100  # رفعنا الحد لـ 100 لاستيعاب النشاط المكثف
TRADE_AMOUNT = 20

active_scans = {}

# تهيئة الجداول
for f, h in [(FILE_ACTIVE, ['Time', 'Symbol', 'Price', 'Goal(+5%)', 'Stop(-3%)']),
             (FILE_RESULTS, ['Time', 'Symbol', 'Entry', 'Max_Rise', 'Max_Drop', 'Final_Status'])]:
    if not os.path.exists(f):
        pd.DataFrame(columns=h).to_csv(f, index=False)

# ==========================================
# [2] محرك الإشعارات (Telegram)
# ==========================================
def send_alert(msg, type="INFO"):
    headers = {"ENTRY": "✅ **دخول ومراقبة**", "EXIT": "🏁 **حسم النتيجة**", "DISCOVERY": "📡 **رصد نشاط**"}
    full_msg = f"{headers.get(type, '📢')} \n{msg}"
    for c in TARGET_CHATS:
        try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": c, "text": full_msg, "parse_mode": "Markdown"})
        except: pass

# ==========================================
# [3] فلتر المسح الواسع (Scoring)
# ==========================================
def process_coin(sym):
    global active_scans
    try:
        if sym in active_scans or len(active_scans) >= MAX_VIRTUAL_TRADES: return 

        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 500: return # فلتر سيولة منخفض لزيادة العملات

        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=30)
        df = pd.DataFrame(bars, columns=['t','o','h','l','close','v'])
        
        # مؤشرات سريعة
        last_close = df['close'].iloc[-1]
        sma = df['close'].rolling(20).mean().iloc[-1]
        rsi = calculate_rsi(df).iloc[-1]
        
        # سكور مرن (50 كافي للدخول)
        score = 0
        if last_close > sma: score += 25
        if 40 < rsi < 75: score += 25
        if last_close > df['close'].iloc[-2]: score += 10

        if score >= 50:
            active_scans[sym] = True
            # 1. الكتابة في جدول العملات النشطة
            with open(FILE_ACTIVE, 'a', newline='') as f:
                csv.writer(f).writerow([datetime.now().strftime('%H:%M:%S'), sym, last_close, last_close*1.05, last_close*0.97])
            
            # 2. إرسال إشعار الدخول
            send_alert(f"العملة: #{sym.split('_')[0]}\nالسعر: `{last_close}`\nالسكور: `{score}`", "ENTRY")
            
            threading.Thread(target=track_performance, args=(sym, last_close), daemon=True).start()
    except: pass

def calculate_rsi(df, periods=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss.replace(0, 0.001)
    return 100 - (100 / (1 + rs))

# ==========================================
# [4] المراقبة والتدوين النهائي
# ==========================================
def track_performance(sym, entry_p):
    global active_scans
    hi, lo = entry_p, entry_p
    while True:
        try:
            time.sleep(15)
            curr = exchange.fetch_ticker(sym)['last']
            hi, lo = max(hi, curr), min(lo, curr)
            pnl = ((curr - entry_p) / entry_p) * 100

            if pnl >= 5.0 or pnl <= -3.0:
                status = "SUCCESS 🟢" if pnl >= 5.0 else "FAILED 🔴"
                # الكتابة في جدول النتائج النهائي
                with open(FILE_RESULTS, 'a', newline='') as f:
                    csv.writer(f).writerow([datetime.now(), sym, entry_p, f"{((hi-entry_p)/entry_p)*100:.2f}%", f"{((lo-entry_p)/entry_p)*100:.2f}%", status])
                
                # إشعار الخروج
                send_alert(f"العملة: #{sym}\nالنتيجة: `{pnl:.2f}%`\nالحالة: {status}", "EXIT")
                del active_scans[sym]
                break
        except: break

def main():
    print("📡 Adem_100: High-Activity Mode Started.")
    send_alert("بدء الرادار بنظام النشاط المكثف.. ترقب الإشعارات والجداول الآن.", "DISCOVERY")
    while True:
        try:
            exchange.load_markets()
            pairs = [s for s in exchange.symbols if s.endswith('_USDT')]
            for i in range(0, len(pairs), 50):
                batch = pairs[i:i+50]
                threads = [threading.Thread(target=process_coin, args=(s,)) for s in batch]
                for t in threads: t.start()
                for t in threads: t.join()
            time.sleep(10)
        except: time.sleep(5)

if __name__ == "__main__": main()
