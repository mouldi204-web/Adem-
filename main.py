import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# [1] الإعدادات المالية والبرمجية
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 
exchange = ccxt.gateio({'enableRateLimit': True})

# ملفات الجداول
FILE_SIGNALS = 'signals_log.csv'
FILE_ACTIVE = 'active_trades.csv'
FILE_HISTORY = 'trade_history.csv'

# إعدادات إدارة رأس المال
MAX_VIRTUAL_TRADES = 50   # الحد الأقصى للصفقات
TRADE_AMOUNT = 20         # قيمة كل صفقة بالدولار

# تهيئة الجداول بأعمدة مالية
for f, h in [(FILE_SIGNALS, ['Time', 'Symbol', 'Score', 'Price', 'RSI']),
             (FILE_ACTIVE, ['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price', 'Amount_$']),
             (FILE_HISTORY, ['Exit_Time', 'Symbol', 'Entry_Price', 'Exit_Price', 'PNL%', 'Profit_$', 'Max_Rise%'])]:
    if not os.path.exists(f):
        with open(f, 'w', newline='') as file: csv.writer(file).writerow(h)

active_virtual_trades = {}
BOOT_TIME = datetime.now()

# ==========================================
# [2] المحرك الفني (نفس الإعدادات المرنة السابقة)
# ==========================================
def calculate_metrics(df):
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20'] * 2)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, 0.001))))
    tr = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['body_ratio'] = (abs(df['close'] - df['open']) / (df['high'] - df['low']).replace(0, 0.001)) * 100
    return df

def get_score(df):
    last = df.iloc[-1]
    score = 0
    if last['close'] >= last['bb_u'] * 0.975: score += 40
    if last['body_ratio'] > 25: score += 30 
    if 40 < last['rsi'] < 85: score += 30
    return score

# ==========================================
# [3] إدارة الصيد المالي والتعمير التلقائي
# ==========================================
def process_coin(sym):
    global active_virtual_trades
    try:
        ticker = exchange.fetch_ticker(sym)
        if ticker['quoteVolume'] < 5000: return 

        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=50)
        df = calculate_metrics(pd.DataFrame(bars, columns=['t','o','h','l','close','volume']))
        score = get_score(df)
        last_p = df['close'].iloc[-1]
        
        # تسجيل الإشارات
        if score >= 60:
            with open(FILE_SIGNALS, 'a', newline='') as f:
                csv.writer(f).writerow([datetime.now().strftime('%H:%M:%S'), sym, score, last_p, f"{df['rsi'].iloc[-1]:.1f}"])

        # دخول الصفقة (بشرط عدم تجاوز 50 صفقة)
        if score >= 75 and len(active_virtual_trades) < MAX_VIRTUAL_TRADES and sym not in active_virtual_trades:
            atr = df['atr'].iloc[-1]
            active_virtual_trades[sym] = {
                'entry': last_p, 'sl': last_p - (atr*2), 'high': last_p, 
                'time': datetime.now(), 'amount': TRADE_AMOUNT
            }
            save_active_to_csv()
            send_msg(f"💰 **صفقة جديدة (20$):** #{sym.split('_')[0]}\nالسكور: `{score}` | المجموع الحالي: `{len(active_virtual_trades)}/50`")
            threading.Thread(target=monitor_trailing, args=(sym, last_p, atr), daemon=True).start()
    except: pass

def monitor_trailing(sym, entry_p, atr):
    global active_virtual_trades
    hi_p, sl_dist = entry_p, (atr * 2)
    curr_sl = entry_p - sl_dist
    while True:
        try:
            curr_p = exchange.fetch_ticker(sym)['last']
            if curr_p > hi_p:
                hi_p = curr_p
                if (hi_p - sl_dist) > curr_sl: curr_sl = hi_p - sl_dist
            
            if curr_p <= curr_sl:
                pnl_pct = ((curr_p - entry_p) / entry_p) * 100
                profit_usd = (TRADE_AMOUNT * pnl_pct) / 100
                
                # تعمير جدول النتائج مالياً
                with open(FILE_HISTORY, 'a', newline='') as f:
                    csv.writer(f).writerow([
                        datetime.now(), sym, entry_p, curr_p, 
                        f"{pnl_pct:.2f}%", f"{profit_usd:.2f}$", 
                        f"{((hi_p-entry_p)/entry_p)*100:.2f}%"
                    ])
                
                color = "🟢" if profit_usd > 0 else "🔴"
                send_msg(f"{color} **إغلاق صفقة:** {sym}\nالربح: `{profit_usd:.2f}$` ({pnl_pct:.2f}%)")
                
                if sym in active_virtual_trades: del active_virtual_trades[sym]
                save_active_to_csv()
                break
            time.sleep(30)
        except: break

# ... [دوال تليجرام /get_history /active /status تبقى كما هي] ...

def save_active_to_csv():
    with open(FILE_ACTIVE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price', 'Amount_$'])
        for s, d in active_virtual_trades.items():
            writer.writerow([d['time'], s, d['entry'], d['sl'], d['high'], d['amount']])

def send_msg(text, cid=None):
    for c in ([cid] if cid else TARGET_CHATS):
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": c, "text": text, "parse_mode": "Markdown"})

def send_doc(cid, file, cap):
    if os.path.exists(file):
        with open(file, 'rb') as f:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", files={'document': f}, data={'chat_id': cid, 'caption': cap})

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
                    send_msg(f"📊 **الحالة المالية:**\nالصفقات المفتوحة: `{len(active_virtual_trades)}/50` \nالميزانية المستخدمة: `${len(active_virtual_trades)*20}`", cid)
                elif txt == "/active": send_doc(cid, FILE_ACTIVE, "الصفقات المفتوحة")
                elif txt == "/get_history": send_doc(cid, FILE_HISTORY, "سجل الأرباح والخسائر")
        except: time.sleep(5)

def main():
    print("🚀 Adem_100 Capital Manager: Started (50 trades x 20$).")
    threading.Thread(target=telegram_listener, daemon=True).start()
    while True:
        try:
            exchange.load_markets()
            all_pairs = [s for s in exchange.symbols if s.endswith('_USDT')]
            for i in range(0, len(all_pairs), 200):
                batch = all_pairs[i:i+200]
                threads = [threading.Thread(target=process_coin, args=(s,)) for s in batch]
                for t in threads: t.start()
                for t in threads: t.join()
                time.sleep(5)
            time.sleep(30)
        except: time.sleep(10)

if __name__ == "__main__": main()
