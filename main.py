import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# [1] الإعدادات الأساسية والربط
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] # حسابك الشخصي + القناة

exchange = ccxt.kucoin({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# أسماء الملفات لتخزين البيانات
FILE_AUDIT = 'trade_audit_log.csv'
FILE_ANALYSE = 'market_analysis_report.csv'

# متغيرات الحالة العامة
market_status = "STABLE ✅"
daily_pnl_tracker = []

# ==========================================
# [2] محرك الإشعارات والأوامر (Telegram Interface)
# ==========================================
def send_msg(text):
    for chat_id in TARGET_CHATS:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=5)
        except: pass

def send_document(chat_id, file_path, caption):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            requests.post(url, files={'document': f}, data={'chat_id': chat_id, 'caption': caption}, timeout=10)
    except: pass

def notify(event, sym, score=0, price=0, res="", pnl=0, mfi=0, r_vol=0):
    url_sym = sym.replace("/", "-")
    trading_url = f"https://www.kucoin.com/trade/{url_sym}"
    clean_s = sym.replace("/", "").replace("-", "")
    
    if event == "ENTRY":
        msg = (f"🚀 **إشارة دخول (Buy Signal)**\n━━━━━━━━━━━━━━━━━━\n"
               f"💎 **العملة:** [#{clean_s}]({trading_url})\n🔥 **السكور:** `{score}/100`\n"
               f"💧 **MFI:** `{mfi:.1f}` | 📊 **Vol:** `{r_vol:.1f}x`\n━━━━━━━━━━━━━━━━━━\n"
               f"🟢 **الدخول:** `{price:.8f}`\n🛑 **الوقف:** `{price*0.97:.8f}`\n"
               f"🎯 **الهدف:** `+5% ~ +12%`\n📡 #Adem_100_Entry")
    elif event == "BURST":
        msg = (f"🔍 **رادار الانفجار (Burst Watch)**\n━━━━━━━━━━━━━━━━━━\n"
               f"📡 **العملة:** [#{clean_s}]({trading_url})\n⚠️ **السكور:** `{score}/100`\n"
               f"💡 **الحالة:** زخم سيولة متصاعد.. مراقبة الاختراق\n📡 #Adem_100_Scanner")
    elif event == "EXIT":
        icon = "✅" if pnl > 0 else "❌"
        msg = (f"{icon} **تقرير النتيجة (Trade Result)**\n━━━━━━━━━━━━━━━━━━\n"
               f"🏁 **العملة:** #{clean_s}\n🏁 **النتيجة:** `{res}`\n📈 **الربح:** `{pnl:+.2f}%` \n━━━━━━━━━━━━━━━━━━\n"
               f"📡 #Adem_100_Audit")
    elif event == "STATUS":
        msg = (f"📊 **حالة النظام (System Status)**\n━━━━━━━━━━━━━━━━━━\n"
               f"🛡️ **BTC:** `{res}`\n🔄 **Pairs:** `800+ USDT`\n💰 **أرباح اليوم:** `{pnl:+.2f}%`\n"
               f"📅 **تحديث:** `{datetime.now().strftime('%H:%M')}`\n📡 #Adem_100_Status")
    send_msg(msg)

# ==========================================
# [3] الفلاتر والمحرك الرياضي (The Guardian Core)
# ==========================================
def calculate_metrics(df):
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20'] * 2)
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['volume']
    pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + pos_f / neg_f))
    df['vol_sma_long'] = df['volume'].rolling(50).mean()
    return df

def get_score(df):
    last = df.iloc[-1]
    score = 0
    # 1. الاختراق
    if last['close'] >= last['bb_u']: score += 30
    # 2. تدفق الأموال
    if 60 <= last['mfi'] <= 82: score += 30
    # 3. السيولة النسبية
    rel_vol = last['volume'] / last['vol_sma_long'] if last['vol_sma_long'] > 0 else 0
    if rel_vol > 1.8: score += 40
    # 4. فلاتر الحماية (عقوبات)
    dist = ((last['close'] - last['sma20'])/last['sma20'])*100
    if dist > 3.5: score -= 50 # عقوبة المسافة
    body = abs(last['close'] - last['open'])
    wick = last['high'] - max(last['close'], last['open'])
    if wick > (body * 0.8): score -= 60 # عقوبة الذيل العلوي
    return score, rel_vol, last['mfi']

# ==========================================
# [4] إدارة الأوامر والملفات (Command Listener)
# ==========================================
def telegram_listener():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": last_id + 1, "timeout": 30}).json()
            for up in r.get("result", []):
                last_id = up["update_id"]
                msg = up.get("message", {})
                txt = msg.get("text", "")
                cid = msg.get("chat", {}).get("id")
                if txt == "/get_audit": send_document(cid, FILE_AUDIT, "سجل الصفقات")
                elif txt == "/get_analysis": send_document(cid, FILE_ANALYSE, "تحليل السوق")
                elif txt == "/status": notify("STATUS", "GLOBAL", res=market_status, pnl=sum(daily_pnl_tracker))
        except: time.sleep(5)

# ==========================================
# [5] تتبع الصفقات والمسح (Execution)
# ==========================================
def monitor_trade(sym, entry_p, score):
    sl = entry_p * 0.97
    tp1_hit = False
    start = datetime.now()
    while (datetime.now() - start).seconds < 14400:
        try:
            curr_p = exchange.fetch_ticker(sym)['last']
            pnl = (curr_p - entry_p) / entry_p * 100
            if pnl >= 3.5 and not tp1_hit:
                tp1_hit = True
                sl = entry_p * 1.01 # حجز ربح
            if pnl >= 7.0: sl = max(sl, entry_p * 1.04) # رفع الوقف
            if curr_p <= sl or pnl >= 12.0:
                res = "SUCCESS ✅" if pnl > 0 else "FAILED ❌"
                notify("EXIT", sym, res=res, pnl=pnl)
                daily_pnl_tracker.append(pnl)
                break
            time.sleep(20)
        except: continue

def process_coin(sym):
    try:
        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 1500000: return
        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=60)
        df = calculate_metrics(pd.DataFrame(bars, columns=['t','o','h','l','close','volume']))
        score, r_vol, mfi_val = get_score(df)
        price = df['close'].iloc[-1]
        
        if score >= 90:
            notify("ENTRY", sym, score, price, mfi=mfi_val, r_vol=r_vol)
            threading.Thread(target=monitor_trade, args=(sym, price, score), daemon=True).start()
        elif 80 <= score < 90:
            notify("BURST", sym, score, price)
    except: pass

def main():
    print("💎 Adem_100 Master Engine Online.")
    threading.Thread(target=telegram_listener, daemon=True).start()
    while True:
        try:
            exchange.load_markets()
            pairs = [s for s in exchange.symbols if s.endswith('/USDT')][:800]
            for i in range(0, 800, 200):
                chunk = pairs[i:i+200]
                threads = [threading.Thread(target=process_coin, args=(s,)) for s in chunk]
                for t in threads: t.start()
                for t in threads: t.join()
            time.sleep(60)
        except: time.sleep(10)

if __name__ == "__main__":
    main()
