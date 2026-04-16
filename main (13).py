import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات (ضع بياناتك هنا)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

# إعدادات المحاكاة (الرصيد 1000$ والحد 10 صفقات)
initial_balance = 1000.0
available_balance = initial_balance
MAX_TRADES = 10
open_trades = []

# ملفات السجلات (قاعدة بياناتك)
TRADE_LOG = 'trading_master_log.csv'
ANALYSE_LOG = 'market_discovery_log.csv'
JOURNAL_LOG = 'bot_journal.txt'

TRADE_HEADERS = ['Symbol', 'Result', 'Quality', 'Entry', 'Exit', 'P_Pct', 'Size_Used', 'Duration', 'RSI', 'BTC', 'Session']
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Score', 'RSI', 'Vol_24h', 'BTC_Status', 'Rank']

app = Flask('')
@app.route('/')
def home(): return f"Omega v35.0 Signal System Active. Active Signals: {len(open_trades)}/10"

# ==========================================
# 2. نظام التواصل والتحليل
# ==========================================

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except: print("❌ خطأ في إرسال رسالة تيليجرام")

def custom_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(JOURNAL_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}")

def calculate_rsi(symbol, period=14):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=5min"
        data = requests.get(url).json()['data'][:period+1]
        closes = [float(c[2]) for c in data]
        diffs = np.diff(closes)
        avg_gain = sum([d if d > 0 else 0 for d in diffs])/period
        avg_loss = sum([-d if d < 0 else 0 for d in diffs])/period
        return round(100 - (100 / (1 + (avg_gain/avg_loss))), 2) if avg_loss != 0 else 100
    except: return 50

# ==========================================
# 3. محرك الرصد وإرسال الإشارات (Scanner)
# ==========================================

def discovery_engine():
    global available_balance
    while True:
        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers").json()
            tickers = res['data']['ticker']
            
            # جلب حالة البيتكوين
            btc_res = requests.get(f"{BASE_URL}/api/v1/market/stats?symbol=BTC-USDT").json()
            btc_chg = float(btc_res['data']['changeRate']) * 100
            btc_status = "Bullish 🟢" if btc_chg > 0.5 else "Bearish 🔴" if btc_chg < -1.5 else "Sideways 🟡"
            
            scored = []
            for t in tickers:
                sym = t['symbol']
                if not sym.endswith("-USDT") or any(x in sym for x in ["3L", "3S", "UP", "DOWN"]): continue
                vol = float(t['volValue'])
                if vol < 80000: continue
                score = 80 + (float(t['changeRate'])*150) + (np.log10(vol)*2)
                scored.append({'symbol': sym, 'price': float(t['last']), 'score': round(score, 1), 'vol': vol})

            top_10 = sorted(scored, key=lambda x: x['score'], reverse=True)[:10]
            
            for i, opp in enumerate(top_10):
                rsi_val = calculate_rsi(opp['symbol'])
                
                # تسجيل البيانات للتحليل
                with open(ANALYSE_LOG, 'a', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=ANALYSE_HEADERS)
                    if f.tell() == 0: writer.writeheader()
                    writer.writerow({'Timestamp': datetime.now().strftime("%H:%M:%S"), 'Symbol': opp['symbol'], 'Score': opp['score'], 'RSI': rsi_val, 'Vol_24h': round(opp['vol'], 0), 'BTC_Status': btc_status, 'Rank': i+1})

                # إرسال إشارة دخول إذا كانت الفرصة ممتازة
                if i < 3 and len(open_trades) < MAX_TRADES and opp['symbol'] not in [t['symbol'] for t in open_trades]:
                    if rsi_val < 65:
                        # تحديد الجودة
                        quality = "⭐⭐⭐ ذهبية" if opp['score'] > 95 else "⭐⭐ متوسطة"
                        trade_size = available_balance * (0.10 if opp['score'] > 95 else 0.075)
                        
                        available_balance -= trade_size
                        open_trades.append({
                            'symbol': opp['symbol'], 'entry': opp['price'], 'size': trade_size,
                            'sl': opp['price'] * 0.96, 'tp': opp['price'] * 1.05,
                            'score': opp['score'], 'quality': quality, 'rsi_entry': rsi_val,
                            'btc_entry': btc_status, 'start_time': datetime.now()
                        })
                        
                        # رسالة الإشارة للمستخدم
                        msg = (f"🎯 **إشارة تداول جديدة (يدوي)**\n\n"
                               f"🔹 **العملة:** `{opp['symbol']}`\n"
                               f"🔹 **الجودة:** {quality}\n"
                               f"🔹 **سعر الدخول:** `{opp['price']}`\n"
                               f"🔹 **الهدف (TP):** `{round(opp['price']*1.05, 6)}` (+5%)\n"
                               f"🔹 **الوقف (SL):** `{round(opp['price']*0.96, 6)}` (-4%)\n\n"
                               f"💡 *السبب:* سكور {opp['score']} و RSI {rsi_val}")
                        send_msg(msg)
                        custom_log(f"📡 Signal Sent: {opp['symbol']}")

        except Exception as e: print(f"Error in Scanner: {e}")
        time.sleep(40)

# ==========================================
# 4. محرك إدارة المحاكاة والأوامر
# ==========================================

def manage_trades():
    global available_balance
    while True:
        for trade in open_trades[:]:
            try:
                res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={trade['symbol']}").json()
                curr_p = float(res['data']['price'])
                p_pct = (curr_p - trade['entry']) / trade['entry'] * 100

                # فحص الهدف أو الوقف
                if curr_p <= trade['sl'] or curr_p >= trade['tp']:
                    res_txt = "WIN ✅" if curr_p >= trade['tp'] else "LOSS ❌"
                    duration = round((datetime.now() - trade['start_time']).total_seconds() / 60, 1)
                    
                    with open(TRADE_LOG, 'a', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=TRADE_HEADERS)
                        if f.tell() == 0: writer.writeheader()
                        writer.writerow({
                            'Symbol': trade['symbol'], 'Result': res_txt, 'Quality': trade['quality'],
                            'Entry': trade['entry'], 'Exit': curr_p, 'P_Pct': round(p_pct, 2),
                            'Size_Used': round(trade['size'], 2), 'Duration': duration,
                            'RSI': trade['rsi_entry'], 'BTC': trade['btc_entry'], 
                            'Session': "Active"
                        })
                    
                    available_balance += (trade['size'] * (1 + p_pct/100))
                    open_trades.remove(trade)
                    send_msg(f"🏁 **تحديث الإشارة**\nتم الخروج من `{trade['symbol']}`\nالنتيجة: {res_txt}\nالربح/الخسارة: `{round(p_pct, 2)}%`")
            except: continue
        time.sleep(20)

def handle_commands():
    last_id = 0
    custom_log("⌨️ Telegram Command System Active...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_id + 1}&timeout=20"
            res = requests.get(url, timeout=25).json()
            for update in res.get("result", []):
                last_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                
                if text == "/balance":
                    total = available_balance + sum([t['size'] for t in open_trades])
                    send_msg(f"💰 **المحفظة الافتراضية**\nمتاح: `${round(available_balance, 2)}`\nإشارات مفتوحة: {len(open_trades)}\nالقيمة الكلية: `${round(total, 2)}`")
                elif text == "/csv": send_doc(TRADE_LOG)
                elif text == "/analyse": send_doc(ANALYSE_LOG)
                elif text == "/journal": send_doc(JOURNAL_LOG)
        except: time.sleep(10)

def send_doc(path):
    if os.path.exists(path):
        with open(path, 'rb') as f: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data={'chat_id': CHAT_ID}, files={'document': f})

if __name__ == "__main__":
    send_msg("💎 **Omega v35.0 Signal System** متصل الآن بنجاح!\nأرسل `/balance` لتجربة الأوامر.")
    # تشغيل الخيوط برمجياً
    threading.Thread(target=handle_commands, daemon=True).start()
    threading.Thread(target=manage_trades, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    # تشغيل سيرفر الويب للبقاء حياً
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
