import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# [1] الإعدادات الأساسية (الربط والملفات)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 

exchange = ccxt.kucoin({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# ملفات السجلات والتدقيق
FILE_AUDIT = 'trade_audit_log.csv'
FILE_BURST_PERF = 'burst_performance_report.csv'
FILE_ANALYSE = 'market_analysis.csv'

# تهيئة الجداول بالعناوين الصحيحة
for f_path, headers in [
    (FILE_AUDIT, ['Timestamp', 'Symbol', 'Result', 'PNL%']),
    (FILE_BURST_PERF, ['Time_Alert', 'Symbol', 'Price_At_Alert', 'Expected_Gain%', 'Max_Price_1h', 'Actual_Max_Gain%', 'Success_Status', 'Time_To_Peak']),
    (FILE_ANALYSE, ['Timestamp', 'Symbol', 'Score', 'MFI'])
]:
    if not os.path.exists(f_path):
        with open(f_path, 'w', newline='') as f:
            csv.writer(f).writerow(headers)

market_status = "STABLE ✅"
daily_pnl_tracker = []

# ==========================================
# [2] محرك الإشعارات (The Notification Engine)
# ==========================================
def send_msg(text):
    for chat_id in TARGET_CHATS:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=5)
        except: pass

def send_doc(chat_id, file_path, caption):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            requests.post(url, files={'document': f}, data={'chat_id': chat_id, 'caption': caption}, timeout=10)
    except: pass

def notify(event, sym, score=0, price=0, res="", pnl=0, mfi=0, r_vol=0, exp_gain=0):
    url_sym = sym.replace("/", "-")
    trading_url = f"https://www.kucoin.com/trade/{url_sym}"
    clean_s = sym.replace("/", "").replace("-", "")
    
    if event == "ENTRY":
        msg = (f"🚀 **إشارة دخول مؤكدة**\n━━━━━━━━━━━━━━━━━━\n"
               f"💎 **العملة:** [#{clean_s}]({trading_url})\n🔥 **السكور:** `{score}/100` 🏆\n"
               f"💧 **MFI:** `{mfi:.1f}` | 📊 **Vol:** `{r_vol:.1f}x`\n━━━━━━━━━━━━━━━━━━\n"
               f"🟢 **الدخول:** `{price:.8f}`\n🛑 **الوقف:** `ATR Dynamic`\n📡 #Adem_100_Entry")
    elif event == "BURST":
        msg = (f"🔍 **رادار الانفجار المتوقع**\n━━━━━━━━━━━━━━━━━━\n"
               f"📡 **العملة:** [#{clean_s}]({trading_url})\n⚠️ **السكور:** `{score}/100`\n"
               f"📈 **الربح المتوقع:** `+{exp_gain:.2f}%`\n💡 **الحالة:** زخم سيولة عالٍ.. مراقبة الاختراق\n📡 #Adem_100_Scanner")
    elif event == "EXIT":
        icon = "✅" if pnl > 0 else "❌"
        msg = (f"{icon} **تقرير النتيجة النهائية**\n━━━━━━━━━━━━━━━━━━\n"
               f"🏁 **العملة:** #{clean_s}\n🏁 **النتيجة:** `{res}`\n📈 **صافي الربح:** `{pnl:+.2f}%` \n📡 #Adem_100_Audit")
    elif event == "STATUS":
        msg = (f"📊 **حالة النظام والارباح**\n━━━━━━━━━━━━━━━━━━\n"
               f"🛡️ **BTC:** `{res}`\n🔄 **Pairs:** `800+ Pairs`\n💰 **أرباح اليوم:** `{pnl:+.2f}%` \n📡 #Adem_100_Status")
    send_msg(msg)

# ==========================================
# [3] خبير التدقيق والأوامر (Audit & Commands)
# ==========================================
def audit_burst_event(sym, alert_price, expected_gain):
    start_time = datetime.now()
    max_price = alert_price
    time_to_peak = "N/A"
    while (datetime.now() - start_time).seconds < 3600:
        try:
            curr_p = exchange.fetch_ticker(sym)['last']
            if curr_p > max_price:
                max_price = curr_p
                elapsed = datetime.now() - start_time
                time_to_peak = f"{elapsed.seconds // 60} min"
            if ((max_price - alert_price) / alert_price) * 100 > expected_gain + 5: break
            time.sleep(20)
        except: continue
    actual_gain = ((max_price - alert_price) / alert_price) * 100
    success = "✅ YES" if actual_gain >= expected_gain else "❌ NO"
    with open(FILE_BURST_PERF, 'a', newline='') as f:
        csv.writer(f).writerow([start_time.strftime('%H:%M:%S'), sym, f"{alert_price:.8f}", f"{expected_gain:.2f}%", f"{max_price:.8f}", f"{actual_gain:.2f}%", success, time_to_peak])

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
                
                if txt == "/get_audit": send_doc(cid, FILE_AUDIT, "📊 سجل الصفقات")
                elif txt == "/get_bursts": send_doc(cid, FILE_BURST_PERF, "💥 تقرير دقة الانفجارات")
                elif txt == "/burst_stats":
                    df = pd.read_csv(FILE_BURST_PERF)
                    total = len(df); wins = len(df[df['Success_Status'].str.contains("YES")])
                    rate = (wins/total*100) if total > 0 else 0
                    send_msg(f"📈 **إحصائيات اليوم:**\n🎯 رصد: `{total}` | ✅ نجاح: `{wins}`\n📊 دقة التوقع: `{rate:.1f}%`")
                elif txt == "/status": notify("STATUS", "GLOBAL", res=market_status, pnl=sum(daily_pnl_tracker))
        except: time.sleep(5)

# ==========================================
# [4] المحرك الفني والفلاتر (The Sovereign Core)
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
    df['tr'] = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()
    return df

def is_btc_safe():
    try:
        btc = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=2)
        change = (btc[-1][4] - btc[-2][4]) / btc[-2][4] * 100
        return change > -0.8
    except: return True

# ==========================================
# [5] التشغيل والتحليل (Execution)
# ==========================================
def monitor_trade(sym, entry_p, atr):
    sl = entry_p - (atr * 2); highest = entry_p; start = datetime.now()
    while (datetime.now() - start).seconds < 14400:
        try:
            curr = exchange.fetch_ticker(sym)['last']
            pnl = (curr - entry_p) / entry_p * 100
            if curr > highest: highest = curr; sl = max(sl, highest - (atr * 1.5))
            if curr <= sl or pnl >= 12.0:
                res = "WIN ✅" if pnl > 0 else "LOSS ❌"
                notify("EXIT", sym, res=res, pnl=pnl)
                with open(FILE_AUDIT, 'a', newline='') as f: csv.writer(f).writerow([datetime.now(), sym, res, f"{pnl:.2f}%"])
                daily_pnl_tracker.append(pnl); break
            time.sleep(20)
        except: continue

def process_coin(sym):
    try:
        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 1500000: return
        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=100)
        df = calculate_metrics(pd.DataFrame(bars, columns=['t','o','h','l','close','volume']))
        price = df['close'].iloc[-1]; atr_val = df['atr'].iloc[-1]
        
        # حساب السكور
        score = 0
        if price >= df['bb_u'].iloc[-1]: score += 30
        if 60 <= df['mfi'].iloc[-1] <= 82: score += 30
        rel_vol = df['volume'].iloc[-1] / df['volume'].rolling(50).mean().iloc[-1]
        if rel_vol > 1.8: score += 40
        if not is_btc_safe(): score = 0
        
        exp_gain = (atr_val / price) * 100 * 1.5 
        if score >= 90:
            notify("ENTRY", sym, score, price, mfi=df['mfi'].iloc[-1], r_vol=rel_vol)
            threading.Thread(target=monitor_trade, args=(sym, price, atr_val), daemon=True).start()
        elif 80 <= score < 90:
            notify("BURST", sym, score, price, exp_gain=exp_gain)
            threading.Thread(target=audit_burst_event, args=(sym, price, exp_gain), daemon=True).start()
    except: pass

def main():
    print("🛡️ Adem_100 Sovereign Auditor: System Online.")
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

if __name__ == "__main__": main()
