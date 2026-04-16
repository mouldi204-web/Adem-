import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. إعدادات الاتصال (ضع بياناتك هنا مباشرة)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"

BASE_URL = "https://api.kucoin.com"

# نظام إدارة السيولة
initial_balance = 2000.0
available_balance = initial_balance
MAX_TRADES = 15
open_trades = []
monitored_assets = {} 

# ملفات السجلات
TRADE_LOG = 'trading_master_log.csv'
ANALYSE_LOG = 'market_discovery_log.csv'

app = Flask('')

@app.route('/')
def home():
    return f"Omega v21.0 Online. Active Trades: {len(open_trades)}/15"

# ==========================================
# 2. وظائف الإشعارات والملفات
# ==========================================
def send_smart_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def log_to_csv(file, headers, data):
    file_exists = os.path.isfile(file)
    with open(file, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists: writer.writeheader()
        writer.writerow(data)

def send_file(file_path, caption):
    if os.path.exists(file_path):
        url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption}, files={'document': f})
    else:
        send_smart_msg("❌ السجل المطلوب غير موجود حالياً.")

# ==========================================
# 3. إدارة أوامر التيليجرام (/balance, /csv, /analyse)
# ==========================================
def handle_commands():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_id + 1}&timeout=20"
            res = requests.get(url, timeout=25).json()
            for update in res.get("result", []):
                last_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                
                if text == "/balance":
                    send_smart_msg(f"💰 *الرصيد المتاح:* `${round(available_balance, 2)}` \n🕒 *الآن:* `{datetime.now().strftime('%H:%M')}`\n📊 *الصفقات:* `{len(open_trades)}/15`")
                elif text == "/csv":
                    send_file(TRADE_LOG, "📂 سجل التداول الحقيقي")
                elif text == "/analyse":
                    send_file(ANALYSE_LOG, "📊 سجل تحليل جودة الفرص المكتشفة")
        except: time.sleep(5)
        time.sleep(1)

# ==========================================
# 4. محرك التحليل والرصد (القلب النابض)
# ==========================================
def discovery_and_trading_engine():
    global available_balance, monitored_assets
    # إشعار البداية الفوري
    send_smart_msg("🚀 **انطلاق نظام أوميجا v21.0**\nالبوت يعمل الآن ويبحث عن أقوى الفرص...")
    
    while True:
        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers").json()
            tickers = res['data']['ticker']
            
            scored = []
            for t in tickers:
                if "-USDT" in t['symbol']:
                    chg = float(t['changeRate']) * 100
                    vol = float(t['volValue'])
                    score = 80 + (chg * 1.6) + (np.log10(vol) if vol > 0 else 0)
                    scored.append({'symbol': t['symbol'], 'price': float(t['last']), 'score': score})
            
            top_3 = sorted(scored, key=lambda x: x['score'], reverse=True)[:3]
            now_time = datetime.now().strftime("%H:%M:%S")

            for item in top_3:
                symbol = item['symbol']
                price = item['price']
                
                if symbol not in monitored_assets:
                    monitored_assets[symbol] = {
                        'symbol': symbol, 'entry_p': price, 'discovery_time': now_time,
                        'max_high': price, 'max_low': price, 'h_time': now_time, 'l_time': now_time, 'finalized': False
                    }
                
                asset = monitored_assets[symbol]
                if not asset['finalized']:
                    if price > asset['max_high']: 
                        asset['max_high'] = price
                        asset['h_time'] = now_time
                    if price < asset['max_low']: 
                        asset['max_low'] = price
                        asset['l_time'] = now_time
                    
                    pump = ((asset['max_high'] - asset['entry_p']) / asset['entry_p']) * 100
                    dump = ((asset['max_low'] - asset['entry_p']) / asset['entry_p']) * 100
                    
                    status = ""
                    if pump >= 4.0: status = "نجاح ✅"
                    elif dump <= -2.0: status = "فشل ❌"
                    
                    if status:
                        asset['finalized'] = True
                        log_to_csv(ANALYSE_LOG, ['Symbol', 'Discovery_Time', 'Initial_Price', 'Max_Pump_%', 'Peak_High_Time', 'Max_Dump_%', 'Peak_Low_Time', 'Status'], {
                            'Symbol': symbol, 'Discovery_Time': asset['discovery_time'], 'Initial_Price': asset['entry_p'],
                            'Max_Pump_%': round(pump, 2), 'Peak_High_Time': asset['h_time'],
                            'Max_Dump_%': round(dump, 2), 'Peak_Low_Time': asset['l_time'], 'Status': status
                        })

            # --- إدارة الدخول في صفقات حقيقية ---
            if len(open_trades) < MAX_TRADES:
                for opp in top_3:
                    if opp['symbol'] not in [t['symbol'] for t in open_trades]:
                        score = opp['score']
                        amount = 150.0 if score > 92 else 50.0
                        
                        if available_balance >= amount:
                            available_balance -= amount
                            open_trades.append({
                                'symbol': opp['symbol'], 'entry': opp['price'], 'size': amount,
                                'tp1': opp['price'] * 1.03, 'sl': opp['price'] * 0.96, 'partial_done': False
                            })
                            send_smart_msg(f"⚡ *إشارة دخول* | {opp['symbol']}\nالمبلغ: `${amount}` | السكور: `{round(score,1)}`")
                            break

        except: pass
        time.sleep(30)

# ==========================================
# 5. تشغيل الخادم والخدمات
# ==========================================
if __name__ == "__main__":
    # تشغيل الخيوط الخلفية
    threading.Thread(target=handle_commands, daemon=True).start()
    threading.Thread(target=discovery_and_trading_engine, daemon=True).start()
    
    # تشغيل خادم الويب باستخدام Waitress
    # Railway يمرر المنفذ تلقائياً، وإذا لم يجده يستخدم 8080
    port = int(os.environ.get('PORT', 8080))
    serve(app, host='0.0.0.0', port=port)
