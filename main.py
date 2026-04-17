import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات والروابط الأساسية
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

ANALYSE_LOG = 'omega_event_log.csv'
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Event', 'Price', 'Detail']
active_monitoring = {}
market_status = "Unknown"

# استبعاد العملات الثقيلة
BLACKLIST = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT', 'ADA-USDT', 'AVAX-USDT']

app = Flask('')
@app.route('/')
def home(): return f"Omega v45.0 Status: {market_status} | Monitoring: {len(active_monitoring)}"

# ==========================================
# 2. وظائف التحليل التقني والسيولة
# ==========================================

def get_technical_data(symbol):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=5min"
        res = requests.get(url, timeout=10).json()
        if 'data' not in res or not res['data']: return 50, 0, 0
        closes = [float(c[2]) for c in res['data'][:20]]
        closes.reverse()
        
        # RSI 14
        diffs = np.diff(closes)
        gains = [d if d > 0 else 0 for d in diffs]
        losses = [-d if d < 0 else 0 for d in diffs]
        avg_gain = sum(gains[-14:])/14
        avg_loss = sum(losses[-14:])/14
        rsi = 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100
        
        # EMA 20
        ema_20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        return rsi, ema_20, closes[-1]
    except: return 50, 0, 0

def check_explosion_signals(symbol):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=1min"
        res = requests.get(url, timeout=10).json()
        if 'data' not in res or len(res['data']) < 15: return 1.0, 10.0
        candles = res['data']
        
        # تسارع السيولة اللحظي
        current_vol = float(candles[0][5])
        avg_past_vol = sum([float(c[5]) for c in candles[1:11]]) / 10
        vol_spike = current_vol / avg_past_vol if avg_past_vol > 0 else 1.0
        
        # الانضغاط السعري
        prices = [float(c[2]) for c in candles[:10]]
        price_range = (max(prices) - min(prices)) / min(prices) * 100
        return vol_spike, price_range
    except: return 1.0, 10.0

# ==========================================
# 3. نظام تسجيل الأحداث والتقرير الدوري
# ==========================================

def log_event(sym, event, price, detail=""):
    file_exists = os.path.isfile(ANALYSE_LOG)
    with open(ANALYSE_LOG, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=ANALYSE_HEADERS)
        if not file_exists: writer.writeheader()
        writer.writerow({
            'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Symbol': sym, 'Event': event, 'Price': price, 'Detail': detail
        })

def send_msg(text):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                       data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ==========================================
# 4. محركات الرصد والمراقبة الذكية
# ==========================================

def update_market_regime():
    global market_status
    while True:
        try:
            url = f"{BASE_URL}/api/v1/market/candles?symbol=BTC-USDT&type=1hour"
            res = requests.get(url, timeout=10).json()
            curr_btc = float(res['data'][0][2])
            closes = [float(c[2]) for c in res['data'][:20]]
            ma20 = sum(closes) / 20
            
            new_status = "🟢 صاعد (Bullish)" if curr_btc > ma20 else "🔴 هابط (Bearish)"
            if new_status != market_status:
                market_status = new_status
                send_msg(f"🌍 **تغير حالة السوق العام**\nالحالة الآن: `{market_status}`\nسعر BTC: `${curr_btc:,.0f}`")
        except: pass
        time.sleep(300)

def discovery_engine():
    while True:
        try:
            if "🔴" in market_status: 
                time.sleep(60); continue
                
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers", timeout=15).json()
            for t in res['data']['ticker']:
                sym = t['symbol']
                vol_24h = float(t['volValue'])
                
                # فلاتر الاستبعاد والسيولة
                if not sym.endswith("-USDT") or sym in BLACKLIST or vol_24h < 300000 or vol_24h > 50000000: continue
                
                # فحص إشارة الانفجار
                vol_spike, price_range = check_explosion_signals(sym)
                if vol_spike > 2.5 and price_range < 0.7:
                    rsi, ema_20, last_price = get_technical_data(sym)
                    if rsi < 70 and last_price > ema_20:
                        if sym not in active_monitoring:
                            entry_p = float(t['last'])
                            log_event(sym, "دخول (ENTRY)", entry_p, f"RSI: {round(rsi,1)}")
                            active_monitoring[sym] = {
                                'entry_price': entry_p, 'sl': entry_p * 0.97, 'tp2': entry_p * 1.07,
                                'be_activated': False, 'start_time': datetime.now()
                            }
                            send_msg(f"🚀 **دخول انفجار**\nالعملة: #{sym}\nالسعر: `{entry_p}`\nالهدف: `+7%` | الوقف: `-3%`")
        except: pass
        time.sleep(25)

def performance_judger():
    while True:
        for sym, data in list(active_monitoring.items()):
            try:
                res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                curr_p = float(res['data']['price'])
                change = (curr_p - data['entry_price']) / data['entry_price'] * 100

                # 1. تأمين الربح (Break-even)
                if change >= 2.0 and not data['be_activated']:
                    data['sl'] = data['entry_price']
                    data['be_activated'] = True
                    log_event(sym, "تأمين (BE)", curr_p, "الربح +2%، الوقف عند الدخول")
                    send_msg(f"🛡️ **تأمين صفقة:** #{sym}\nنقل الوقف لسعر الدخول.")

                # 2. الخروج (الربح أو الوقف)
                if curr_p >= data['tp2']:
                    log_event(sym, "خروج (TP2)", curr_p, f"ربح نهائي: {round(change,2)}%")
                    send_msg(f"✅ **خروج بنجاح:** #{sym}\nالربح المحقق: `+{round(change,2)}%`")
                    del active_monitoring[sym]
                elif curr_p <= data['sl']:
                    reason = "خروج آمن (BE)" if data['be_activated'] else "خسارة (SL)"
                    log_event(sym, f"خروج ({reason})", curr_p, f"النتيجة: {round(change,2)}%")
                    send_msg(f"🏁 **إغلاق صفقة:** #{sym}\nالنتيجة: `{reason}`")
                    del active_monitoring[sym]
            except: continue
        time.sleep(15)

if __name__ == "__main__":
    send_msg("🛡️ **أوميجا v45.0 قيد التشغيل**\nتم تفعيل نظام السجلات الفورية وإدارة المخاطر.")
    threading.Thread(target=update_market_regime, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
