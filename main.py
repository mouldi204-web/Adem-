import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime, timedelta
import requests

# ==========================================
# [1] الإعدادات الأساسية
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 
exchange = ccxt.gateio({'enableRateLimit': True})

FILE_SIGNALS = 'signals_log.csv'
FILE_ACTIVE = 'active_trades.csv'
FILE_HISTORY = 'trade_history.csv'

# تهيئة الملفات
for f, h in [(FILE_SIGNALS, ['Time', 'Symbol', 'Score', 'Price', 'RSI', 'Body_Ratio']),
             (FILE_ACTIVE, ['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price']),
             (FILE_HISTORY, ['Exit_Time', 'Symbol', 'Entry_Price', 'Exit_Price', 'PNL%', 'Max_Rise%'])]:
    if not os.path.exists(f):
        with open(f, 'w', newline='') as file: csv.writer(file).writerow(h)

active_virtual_trades = {}
MAX_VIRTUAL_TRADES = 150 
BOOT_TIME = datetime.now()

# ==========================================
# [2] المحرك الفني (الحساسية القصوى)
# ==========================================
def calculate_metrics(df):
    # Bollinger Bands
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20'] * 2)
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, 0.001))))
    
    # جودة الشمعة
    candle_range = df['high'] - df['low']
    body_range = abs(df['close'] - df['open'])
    df['body_ratio'] = (body_range / candle_range.replace(0, 0.001)) * 100
    
    # ATR
    tr = pd.concat([df['high']-df['low'], abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    return df

def get_final_score(df):
    last = df.iloc[-1]
    score = 0
    # شرط القرب من الانفجار (99% من البولنجر العلوي)
    if last['close'] >= last['bb_u'] * 0.990: score += 40
    # شرط جسم الشمعة الممتلئ (أكبر من 55%)
    if last['body_ratio'] > 55: score += 30 
    # شرط الزخم المرن (بداية الصعود)
    if 45 < last['rsi'] < 75: score += 30
    return score

# ==========================================
# [3] المعالجة وأوامر تليجرام
# ==========================================
def process_coin(sym):
    global active_virtual_trades
    try:
        ticker = exchange.fetch_ticker(sym)
        # فلتر سيولة مرن للمراقبة (أعلى من 30 ألف دولار)
        if ticker['quoteVolume'] < 30000: return 

        bars = exchange.fetch_ohlcv(sym, timeframe='15m', limit=50)
        df = calculate_metrics(pd.DataFrame(bars, columns=['t','o','h','l','close','volume']))
        
        score = get_final_score(df)
        last_row = df.iloc[-1]
        
        if score >= 70:
            with open(FILE_SIGNALS, 'a', newline='') as f:
                csv.writer(f).writerow([datetime.now().strftime('%H:%M:%S'), sym, score, last_row['close'], f"{last_row['rsi']:.1f}", f"{last_row['body_ratio']:.1f}"])

        if score >= 80 and len(active_virtual_trades) < MAX_VIRTUAL_TRADES and sym not in active_virtual_trades:
            p, atr = last_row['close'], last_row['atr']
            active_virtual_trades[sym] = {'entry': p, 'sl': p - (atr*1.5), 'high': p, 'time': datetime.now()}
            save_active_to_csv()
            send_msg(f"🕵️ **رصد إشارة:** #{sym.split('_')[0]}\nالسكور: `{score}` | السعر: `{p:.6f}`")
            threading.Thread(target=monitor_trailing, args=(sym, p, atr), daemon=True).start()
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
                if (hi_p - sl_dist) > curr_sl: curr_sl = hi_p - sl_dist
            
            if curr_p <= curr_sl:
                pnl = ((curr_p - entry_p) / entry_p) * 100
                with open(FILE_HISTORY, 'a', newline='') as f:
                    csv.writer(f).writerow([datetime.now(), sym, entry_p, curr_p, f"{pnl:.2f}%", f"{((hi_p-entry_p)/entry_p)*100:.2f}%"])
                send_msg(f"🏁 **نهاية:** {sym} | النتيجة: `{pnl:.2f}%`")
                if sym in active_virtual_trades: del active_virtual_trades[sym]
                save_active_to_csv()
                break
            time.sleep(30)
        except: break

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
                    uptime = str(datetime.now() - BOOT_TIME).split('.')[0]
                    send_msg(f"📊 **État du Bot**\nOrdres: `{len(active_virtual_trades)}` | Uptime: `{uptime}`", cid)
                elif txt == "/active": send_doc(cid, FILE_ACTIVE, "Liste des ordres")
                elif txt == "/get_history": send_doc(cid, FILE_HISTORY, "Historique")
                elif txt == "/get_signals": send_doc(cid, FILE_SIGNALS, "Log des Signaux")
                elif txt == "/stats":
                    df = pd.read_csv(FILE_HISTORY)
                    if not df.empty:
                        avg = df['PNL%'].str.replace('%','').astype(float).mean()
                        send_msg(f"📈 Moyenne PNL: `{avg:.2f}%` | Total: `{len(df)}`", cid)
        except: time.sleep(5)

# [دوال المساعدة send_msg, send_doc, save_active_to_csv...]
def save_active_to_csv():
    with open(FILE_ACTIVE, 'w', newline='') as f:
        writer = csv.writer(f); writer.writerow(['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price'])
        for s, d in active_virtual_trades.items(): writer.writerow([d['time'], s, d['entry'], d['sl'], d['high']])

def send_msg(text, cid=None):
    for c in ([cid] if cid else TARGET_CHATS): requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": c, "text": text, "parse_mode": "Markdown"})

def send_doc(cid, file, cap):
    if os.path.exists(file):
        with open(file, 'rb') as f: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", files={'document': f}, data={'chat_id': cid, 'caption': cap})

# ==========================================
# [4] المحرك الرئيسي (1500 عملة / 150 دفعة)
# ==========================================
def main():
    print("💎 Adem_100 Universal Hunter Ready.")
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
