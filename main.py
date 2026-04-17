import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# [1] الإعدادات الأساسية والمالية
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 
exchange = ccxt.gateio({'enableRateLimit': True})

FILE_SCANNER = 'scanner_results.csv'
MAX_VIRTUAL_TRADES = 50   
TRADE_AMOUNT = 20         
STOP_LOSS_PCT = 0.03      # وقف خسارة عند -3%

active_scans = {}
BOOT_TIME = datetime.now()

# تهيئة جدول النتائج
if not os.path.exists(FILE_SCANNER):
    with open(FILE_SCANNER, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Discovery_Time', 'Symbol', 'Discovery_Price', 'Max_Rise%', 'Max_Drop%', 'Status'])

# ==========================================
# [2] نظام الإشعارات المتطور
# ==========================================
def send_alert(msg, alert_type="INFO"):
    headers = {
        "EXPLOSION": "🔥 **إنفجار سعري وشيك** 🔥",
        "ENTRY": "✅ **دخول صفقة جديدة**",
        "EXIT": "🏁 **خروج وتأمين الأرباح**",
        "STATUS": "📊 **تحديث الحالة**",
        "DISCOVERY": "📡 **اكتشاف عملة مرشحة**"
    }
    header = headers.get(alert_type, "📢 **تنبيه**")
    full_msg = f"{header}\n{msg}"
    
    for c in TARGET_CHATS:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                          data={"chat_id": c, "text": full_msg, "parse_mode": "Markdown"})
        except: pass

# ==========================================
# [3] محرك الرصد (Explosion Detector)
# ==========================================
def process_coin(sym):
    global active_scans
    try:
        if sym in active_scans: return 

        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 5000: return 

        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['t','o','h','l','close','volume'])
        
        # حساب المؤشرات الفنية
        df['sma20'] = df['close'].rolling(20).mean()
        df['std20'] = df['close'].rolling(20).std()
        df['bb_u'] = df['sma20'] + (df['std20'] * 2)
        df['bb_w'] = (df['bb_u'] - (df['sma20'] - (df['std20'] * 2))) / df['sma20'] # عرض البولنجر
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 1. إشعار اكتشاف (Discovery): إذا اقتربت من الاختراق
        if last['close'] >= last['bb_u'] * 0.98 and last['close'] < last['bb_u']:
             print(f"📡 Discovery: {sym} near breakout.")

        # 2. منطق الانفجار: تضيق (Squeeze) + اختراق قوي للسعر والفوليوم
        is_squeeze = df['bb_w'].iloc[-10:-2].mean() < 0.03 
        is_breakout = last['close'] > prev['bb_u']
        volume_spike = last['volume'] > df['volume'].iloc[-10:-1].mean() * 1.5

        if is_breakout and (is_squeeze or volume_spike):
            price = last['close']
            # توقع الارتفاع بناءً على زخم الانفجار
            expected_rise = round(((last['close'] - prev['close']) / prev['close']) * 100 * 2.5, 2)
            if expected_rise < 5: expected_rise = 8.5 # حد أدنى للتوقع
            
            explosion_msg = (f"العملة: #{sym.split('_')[0]}\n"
                             f"سعر الدخول: `{price:.8f}`\n"
                             f"الارتفاع المتوقع: `+{expected_rise}%` 🚀")
            send_alert(explosion_msg, "EXPLOSION")
            
            active_scans[sym] = True
            threading.Thread(target=track_performance, args=(sym, price), daemon=True).start()
    except: pass

# ==========================================
# [4] متابعة الأداء (Trailing & 5/3 Rule)
# ==========================================
def track_performance(sym, entry_p):
    global active_scans
    max_p = entry_p
    min_p = entry_p
    start_time = datetime.now().strftime('%H:%M:%S')

    while True:
        try:
            time.sleep(20)
            curr_ticker = exchange.fetch_ticker(sym)
            curr_p = curr_ticker['last']

            if curr_p > max_p: max_p = curr_p
            if curr_p < min_p: min_p = curr_p

            rise_pct = ((max_p - entry_p) / entry_p) * 100
            drop_pct = ((min_p - entry_p) / entry_p) * 100
            current_pnl = ((curr_p - entry_p) / entry_p) * 100

            # شرط الفشل: -3% قبل النجاح
            if current_pnl <= -3.0:
                finish_trade(sym, entry_p, curr_p, rise_pct, drop_pct, "فشل (خسارة 3%)")
                break

            # شرط النجاح: +5% 
            elif current_pnl >= 5.0:
                finish_trade(sym, entry_p, curr_p, rise_pct, drop_pct, "نجاح (ربح 5%)")
                break
        except: break

def finish_trade(sym, entry_p, exit_p, rise, drop, status):
    global active_scans
    pnl = ((exit_p - entry_p) / entry_p) * 100
    profit_usd = (TRADE_AMOUNT * pnl) / 100
    
    # تعمير الجدول
    with open(FILE_SCANNER, 'a', newline='') as f:
        csv.writer(f).writerow([datetime.now(), sym, entry_p, f"{rise:.2f}%", f"{drop:.2f}%", status])
    
    # إشعار الخروج
    icon = "🟢" if "نجاح" in status else "🔴"
    exit_msg = (f"العملة: #{sym.split('_')[0]}\n"
                f"النتيجة: `{pnl:.2f}%` (${profit_usd:.2f})\n"
                f"أقصى صعود: `{rise:.2f}%` | الحالة: {status}")
    send_alert(exit_msg, "EXIT")
    
    if sym in active_scans: del active_scans[sym]

# ==========================================
# [5] التشغيل والتحكم
# ==========================================
def telegram_listener():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            r = requests.get(url, params={'offset': last_id + 1, 'timeout': 30}).json()
            for up in r.get("result", []):
                last_id = up["update_id"]
                msg = up.get("message", {})
                txt = msg.get("text", "").lower()
                cid = msg.get("chat", {}).get("id")

                if txt == "/status":
                    send_alert(f"الرادار يعمل..\nعدد العملات تحت المراقبة: `{len(active_scans)}`", "STATUS")
                elif txt == "/get_results":
                    if os.path.exists(FILE_SCANNER):
                        with open(FILE_SCANNER, 'rb') as f:
                            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", params={'chat_id': cid}, files={'document': f})
        except: time.sleep(5)

def main():
    print("🚀 Adem_100 Explosion Hunter: Online.")
    threading.Thread(target=telegram_listener, daemon=True).start()
    send_alert("تم تفعيل الرادار الشامل.\nإدارة رأس المال: 20$ لكل صفقة\nالهدف: +5% | الوقف: -3%", "STATUS")
    
    while True:
        try:
            exchange.load_markets()
            all_pairs = [s for s in exchange.symbols if s.endswith('_USDT')]
            for i in range(0, len(all_pairs), 100):
                batch = all_pairs[i:i+100]
                threads = [threading.Thread(target=process_coin, args=(s,)) for s in batch]
                for t in threads: t.start()
                for t in threads: t.join()
                time.sleep(2)
            time.sleep(30)
        except: time.sleep(10)

if __name__ == "__main__":
    main()
