import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime, timedelta
import requests

# ==========================================
# [1] الإعدادات الأساسية (تأكد من وضع التوكن الخاص بك)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 
exchange = ccxt.gateio({'enableRateLimit': True})

# أسماء ملفات السجلات الثلاثة
FILE_SIGNALS = 'signals_log.csv'
FILE_ACTIVE = 'active_trades.csv'
FILE_HISTORY = 'trade_history.csv'

# إنشاء الملفات إذا لم تكن موجودة
for f, h in [(FILE_SIGNALS, ['Time', 'Symbol', 'Score', 'Price', 'RSI', 'Body_Ratio']),
             (FILE_ACTIVE, ['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price']),
             (FILE_HISTORY, ['Exit_Time', 'Symbol', 'Entry_Price', 'Exit_Price', 'PNL%', 'Max_Rise%'])]:
    if not os.path.exists(f):
        with open(f, 'w', newline='') as file: csv.writer(file).writerow(h)

active_virtual_trades = {}
MAX_VIRTUAL_TRADES = 100 
BOOT_TIME = datetime.now()

# ==========================================
# [2] المحرك الفني المتقدم
# ==========================================
def calculate_master_metrics(df):
    # Bollinger Bands
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20'] * 2)
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, 0.001))))
    
    # Divergence (كشف الانحراف)
    df['price_rising'] = df['close'] > df['close'].shift(1)
    df['rsi_falling'] = df['rsi'] < df['rsi'].shift(1)
    df['divergence'] = df['price_rising'] & df['rsi_falling']

    # Body Ratio (جودة الشمعة)
    candle_range = df['high'] - df['low']
    body_range = abs(df['close'] - df['open'])
    df['body_ratio'] = (body_range / candle_range.replace(0, 0.001)) * 100
    
    # ATR
    tr = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    return df

def get_master_score(df):
    last = df.iloc[-1]
    score = 0
    if last['close'] >= last['bb_u'] * 0.995: score += 40
    if last['body_ratio'] > 60: score += 30 
    if 55 < last['rsi'] < 75: score += 30
    if last['divergence']: score -= 50 # عقوبة للانحراف السلبي
    return score

# ==========================================
# [3] إدارة الصفقات والمسح
# ==========================================
def process_coin(sym):
    global active_virtual_trades
    try:
        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 40000 or ticker['last'] == 0: return 

        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=50)
        df = calculate_master_metrics(pd.DataFrame(bars, columns=['t','o','h','l','close','volume']))
        
        score = get_master_score(df)
        last_row = df.iloc[-1]
        
        # تسجيل الإشارة
        if score >= 70:
            with open(FILE_SIGNALS, 'a', newline='') as f:
                csv.writer(f).writerow([datetime.now().strftime('%H:%M:%S'), sym, score, last_row['close'], f"{last_row['rsi']:.1f}", f"{last_row['body_ratio']:.1f}"])

        # الدخول الافتراضي
        if score >= 80 and len(active_virtual_trades) < MAX_VIRTUAL_TRADES and sym not in active_virtual_trades:
            price, atr_val = last_row['close'], last_row['atr']
            active_virtual_trades[sym] = {'entry': price, 'sl': price - (atr_val*1.5), 'high': price, 'time': datetime.now()}
            save_active_to_csv()
            send_msg(f"🔬 **إشارة علمية:** #{sym.split('_')[0]}\nالسكور: `{score}` | جسم الشمعة: `{last_row['body_ratio']:.1f}%`")
            threading.Thread(target=monitor_trailing, args=(sym, price, atr_val), daemon=True).start()
    except: pass

def monitor_trailing(sym, entry_p, atr):
    global active_virtual_trades
    hi_p, sl_dist = entry_p, (atr * 1.5)
    curr_sl = entry_p - sl_dist
    
    while True:
        try:
            curr_p = exchange.fetch_ticker(sym)['last']
            if curr_p > hi_p:
                hi_p = curr_p
                if (hi_p - sl_dist) > curr_sl: 
                    curr_sl = hi_p - sl_dist
                    active_virtual_trades[sym].update({'sl': curr_sl, 'high': hi_p})
            
            if curr_p <= curr_sl:
                pnl = ((curr_p - entry_p) / entry_p) * 100
                max_rise = ((hi_p - entry_p) / entry_p) * 100
                with open(FILE_HISTORY, 'a', newline='') as f:
                    csv.writer(f).writerow([datetime.now(), sym, entry_p, curr_p, f"{pnl:.2f}%", f"{max_rise:.2f}%"])
                send_msg(f"🏁 **خروج:** {sym}\nالربح: `{pnl:.2f}%` | القمة: `{max_rise:.2f}%` 🚀")
                if sym in active_virtual_trades: del active_virtual_trades[sym]
                save_active_to_csv()
                break
            time.sleep(30)
        except: break

# ==========================================
# [4] أوامر تليجرام الكاملة
# ==========================================
def telegram_listener():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": last_id + 1, "timeout": 30}).json()
            for up in r.get("result", []):
                last_id, msg = up["update_id"], up.get("message", {})
                txt, cid = msg.get("text", "").lower(), msg.get("chat", {}).get("id")
                
                if txt in ["/etat", "/status"]:
                    uptime = datetime.now() - BOOT_TIME
                    status_txt = (f"📊 **حالة المختبر**\n━━━━━━━━━━━━\n"
                                  f"📦 الصفقات المفتوحة: `{len(active_virtual_trades)} / {MAX_VIRTUAL_TRADES}`\n"
                                  f"⏱️ مدة التشغيل: `{str(uptime).split('.')[0]}`\n"
                                  f"🔌 API: Gate.io Connected")
                    send_msg(status_txt, cid)
                
                elif txt == "/active": send_doc(cid, FILE_ACTIVE, "📄 Ordres Ouverts (CSV)")
                elif txt == "/get_history": send_doc(cid, FILE_HISTORY, "📊 Historique Complet (CSV)")
                elif txt == "/get_signals": send_doc(cid, FILE_SIGNALS, "📡 Log des Signaux (CSV)")
                elif txt == "/stats":
                    df_h = pd.read_csv(FILE_HISTORY)
                    if not df_h.empty:
                        avg_p = df_h['PNL%'].str.replace('%','').astype(float).mean()
                        send_msg(f"📈 **إحصائيات:**\nإجمالي الصفقات: `{len(df_h)}` \nمتوسط الربح: `{avg_p:.2f}%`", cid)
        except: time.sleep(5)

# ==========================================
# [5] الوظائف المساعدة والتشغيل
# ==========================================
def save_active_to_csv():
    with open(FILE_ACTIVE, 'w', newline='') as f:
        writer = csv.writer(f); writer.writerow(['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price'])
        for s, d in active_virtual_trades.items(): writer.writerow([d['time'], s, d['entry'], d['sl'], d['high']])

def send_msg(text, cid=None):
    chats = [cid] if cid else TARGET_CHATS
    for c in chats: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": c, "text": text, "parse_mode": "Markdown"})

def send_doc(cid, file, cap):
    if os.path.exists(file):
        with open(file, 'rb') as f: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", files={'document': f}, data={'chat_id': cid, 'caption': cap})

def main():
    print("💎 Adem_100 Ultra Scientific Master: Starting...")
    threading.Thread(target=telegram_listener, daemon=True).start()
    while True:
        try:
            exchange.load_markets()
            all_pairs = [s for s in exchange.symbols if s.endswith('_USDT')][:1500]
            for i in range(0, len(all_pairs), 150):
                batch = all_pairs[i:i+150]
                threads = [threading.Thread(target=process_coin, args=(s,)) for s in batch]
                for t in threads: t.start()
                for t in threads: t.join()
                time.sleep(12) 
            time.sleep(60)
        except: time.sleep(10)

if __name__ == "__main__": main()
