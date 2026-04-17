import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# ==========================================
# 1. الإعدادات والبيانات المالية (Paper Trading)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

INITIAL_BALANCE = 1000.0  # رصيد البداية الوهمي
current_balance = INITIAL_BALANCE
used_balance = 0.0

ANALYSE_LOG = 'omega_paper_trading_log.csv'
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Event', 'Price', 'Detail']
active_monitoring = {}
market_status = "Unknown"
last_scan_gems = []

app = Flask('')
@app.route('/')
def home(): 
    return f"Omega v47.0 Active. Balance: {current_balance:.2f} USDT | Active Orders: {len(active_monitoring)}"

# ==========================================
# 2. وظائف التحليل التقني (Logic)
# ==========================================

def get_technical_data(symbol):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=5min"
        res = requests.get(url, timeout=10).json()
        if 'data' not in res or not res['data']: return 50, 0, 0
        closes = [float(c[2]) for c in res['data'][:20]]
        closes.reverse()
        diffs = np.diff(closes)
        gains = [d if d > 0 else 0 for d in diffs]; losses = [-d if d < 0 else 0 for d in diffs]
        avg_gain = sum(gains[-14:])/14; avg_loss = sum(losses[-14:])/14
        rsi = 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100
        ema_20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        return rsi, ema_20, closes[-1]
    except: return 50, 0, 0

def check_explosion_signals(symbol):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=1min"
        res = requests.get(url, timeout=10).json()
        candles = res['data']
        vol_spike = float(candles[0][5]) / (sum([float(c[5]) for c in candles[1:11]]) / 10)
        prices = [float(c[2]) for c in candles[:10]]
        price_range = (max(prices) - min(prices)) / min(prices) * 100
        return vol_spike, price_range
    except: return 1.0, 10.0

# ==========================================
# 3. إدارة السجلات والرسائل
# ==========================================

def log_event(sym, event, price, detail=""):
    file_exists = os.path.isfile(ANALYSE_LOG)
    with open(ANALYSE_LOG, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=ANALYSE_HEADERS)
        if not file_exists: writer.writeheader()
        writer.writerow({'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'Symbol': sym, 'Event': event, 'Price': price, 'Detail': detail})

def send_msg(text):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ==========================================
# 4. محركات البوت (Discovery & Judger)
# ==========================================

def update_market_regime():
    global market_status
    while True:
        try:
            url = f"{BASE_URL}/api/v1/market/candles?symbol=BTC-USDT&type=1hour"
            res = requests.get(url, timeout=10).json()
            curr_btc = float(res['data'][0][2])
            ma20 = sum([float(c[2]) for c in res['data'][:20]]) / 20
            market_status = "🟢 صاعد" if curr_btc > ma20 else "🔴 هابط"
        except: pass
        time.sleep(300)

def discovery_engine():
    global used_balance, last_scan_gems
    while True:
        try:
            if "🔴" in market_status: time.sleep(60); continue
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers").json()
            temp_gems = []
            for t in res['data']['ticker']:
                sym, vol_24h = t['symbol'], float(t['volValue'])
                if not sym.endswith("-USDT") or vol_24h < 300000: continue
                
                score = (float(t['changeRate']) * 100) + (np.log10(vol_24h) * 2)
                if score >= 90:
                    rsi, ema_20, last_price = get_technical_data(sym)
                    temp_gems.append({'sym': sym.replace('-USDT',''), 'score': round(score,1), 'rsi': round(rsi,1)})
                    
                    if rsi < 70 and last_price > ema_20 and sym not in active_monitoring:
                        # تخصيص السيولة: 150 للسكور العالي و 50 للعادي
                        trade_alloc = 150.0 if score >= 95 else 50.0
                        if trade_alloc <= (current_balance - used_balance):
                            used_balance += trade_alloc
                            active_monitoring[sym] = {
                                'entry_price': last_price, 'allocated_amount': trade_alloc,
                                'sl': last_price * 0.97, 'tp2': last_price * 1.07,
                                'be_activated': False, 'is_closed': False, 'start_time': datetime.now()
                            }
                            log_event(sym, "دخول (ENTRY)", last_price, f"المبلغ: {trade_alloc}$ | Score: {round(score,1)}")
                            send_msg(f"🚀 **دخول صفقة**\nالعملة: #{sym}\nالمبلغ: `${trade_alloc}`\nالسكور: `{round(score,1)}`")
            last_scan_gems = sorted(temp_gems, key=lambda x: x['score'], reverse=True)
        except: pass
        time.sleep(25)

def performance_judger():
    global current_balance, used_balance
    while True:
        for sym, data in list(active_monitoring.items()):
            try:
                res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}").json()
                curr_p = float(res['data']['price'])
                change = (curr_p - data['entry_price']) / data['entry_price'] * 100
                
                if not data['is_closed']:
                    if change >= 2.0 and not data['be_activated']:
                        data['sl'] = data['entry_price']; data['be_activated'] = True
                        log_event(sym, "تأمين (BE)", curr_p, "نقل الوقف للدخول")
                    
                    if curr_p >= data['tp2'] or curr_p <= data['sl']:
                        profit_usdt = data['allocated_amount'] * (change / 100)
                        current_balance += profit_usdt
                        used_balance -= data['allocated_amount']
                        reason = "Success ✅" if curr_p >= data['tp2'] else "Safe/SL 🛡️"
                        log_event(sym, f"إغلاق ({reason})", curr_p, f"الربح: {profit_usdt:+.2f}$")
                        send_msg(f"🏁 **إغلاق صفقة:** #{sym}\nالربح: `{profit_usdt:+.2f}$` ({change:.2f}%)")
                        del active_monitoring[sym]
            except: continue
        time.sleep(15)

# ==========================================
# 5. أوامر تليجرام (Telegram Commands)
# ==========================================

def etat(update: Update, context: CallbackContext):
    msg = (f"📊 **حالة المحفظة الورقية**\n━━━━━━━━━━━━━━\n"
           f"🌍 السوق: `{market_status}`\n💰 الرصيد الكلي: `{current_balance:.2f}$`\n"
           f"🔓 المتاح: `{current_balance - used_balance:.2f}$`\n📈 الصفقات النشطة: `{len(active_monitoring)}`")
    update.message.reply_text(msg, parse_mode='Markdown')

def ord_ouv(update: Update, context: CallbackContext):
    if not active_monitoring: update.message.reply_text("📭 لا توجد صفقات.")
    else:
        msg = "📂 **الصفقات المفتوحة:**\n"
        for s, d in active_monitoring.items():
            msg += f"🔸 {s}: `{d['allocated_amount']}$` | مؤمنة: `{d['be_activated']}`\n"
        update.message.reply_text(msg)

def resultat(update: Update, context: CallbackContext):
    if os.path.exists(ANALYSE_LOG): context.bot.send_document(chat_id=update.effective_chat.id, document=open(ANALYSE_LOG, 'rb'))
    else: update.message.reply_text("❌ لا يوجد سجل.")

def analyse(update: Update, context: CallbackContext):
    if not last_scan_gems: update.message.reply_text("🔍 لا يوجد عملات +90.")
    else:
        msg = "🌟 **أعلى سكور (بدون دخول):**\n"
        for g in last_scan_gems[:5]: msg += f"🔸 #{g['sym']}: {g['score']}\n"
        update.message.reply_text(msg)

def run_telegram():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("etat", etat))
    dp.add_handler(CommandHandler("ord_ouv", ord_ouv))
    dp.add_handler(CommandHandler("resultat", resultat))
    dp.add_handler(CommandHandler("analyse", analyse))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    threading.Thread(target=update_market_regime, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
