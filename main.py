import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- [1] الإعدادات الأساسية ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

TRADING_LOG = 'final_professional_report.csv'
INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
used_balance = 0.0

active_monitoring = {}
post_trade_watchlist = {}
market_status = "Unknown"

app = Flask('')
@app.route('/')
def home(): return f"Omega v55.0 Active. Portfolio: {current_balance:.2f} USDT"

# --- [2] وظائف التحليل التقني (المحرك الداخلي) ---

def get_technical_data(symbol):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=5min"
        res = requests.get(url, timeout=10).json()
        if 'data' not in res or not res['data']: return 50, 0, 0
        closes = [float(c[2]) for c in res['data'][:20]]
        closes.reverse()
        diffs = np.diff(closes)
        gains = [d if d > 0 else 0 for d in diffs]
        losses = [-d if d < 0 else 0 for d in diffs]
        avg_gain = sum(gains[-14:])/14; avg_loss = sum(losses[-14:])/14
        rsi = 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100
        ema_20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        return rsi, ema_20, closes[-1]
    except: return 50, 0, 0

# --- [3] نظام التسجيل والمراقبة ---

def log_master_report(data, exit_p, final_chg, post_h=0, post_l=0):
    headers = [
        'Symbol', 'Score', 'Entry_Price', 'Exit_Price', 'Result_%', 
        'Time_to_+3%', 'Time_to_+5%', 'Time_to_-2%', 
        'Max_During_%', 'Min_During_%', 'Max_Post_%', 'Min_Post_%', 'Final_Balance'
    ]
    file_exists = os.path.isfile(TRADING_LOG)
    with open(TRADING_LOG, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists: writer.writeheader()
        writer.writerow({
            'Symbol': data['sym'], 'Score': data['score'],
            'Entry_Price': f"{data['entry_p']:.8f}", 'Exit_Price': f"{exit_p:.8f}",
            'Result_%': f"{final_chg:+.2f}%",
            'Time_to_+3%': data.get('t_3', 'N/A'), 'Time_to_+5%': data.get('t_5', 'N/A'),
            'Time_to_-2%': data.get('t_m2', 'N/A'),
            'Max_During_%': f"{((data['max_h'] - data['entry_p']) / data['entry_p'] * 100):+.2f}%",
            'Min_During_%': f"{((data['min_l'] - data['entry_p']) / data['entry_p'] * 100):+.2f}%",
            'Max_Post_%': f"{post_h:+.2f}%", 'Min_Post_%': f"{post_l:+.2f}%",
            'Final_Balance': f"{current_balance:.2f}$"
        })

def performance_judger():
    global current_balance, used_balance
    while True:
        # مراقبة الصفقات المفتوحة
        for sym, data in list(active_monitoring.items()):
            try:
                p_res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                p = float(p_res['data']['price'])
                now = datetime.now()
                chg = (p - data['entry_p']) / data['entry_p'] * 100
                
                data['max_h'] = max(data['max_h'], p)
                data['min_l'] = min(data['min_l'], p)

                # رصد السرعة الزمنية
                if chg >= 3.0 and not data['t_3']: data['t_3'] = str(now - data['start_time']).split('.')[0]
                if chg >= 5.0 and not data['t_5']: data['t_5'] = str(now - data['start_time']).split('.')[0]
                if chg <= -2.0 and not data['t_m2']: data['t_m2'] = str(now - data['start_time']).split('.')[0]

                # ملاحقة الأرباح Trailing
                if chg >= 7.0:
                    new_sl = data['max_h'] * 0.98
                    if new_sl > data['sl']: data['sl'] = new_sl
                elif chg >= 2.0 and not data.get('be'):
                    data['sl'] = data['entry_p']; data['be'] = True

                # الخروج
                if p <= data['sl']:
                    prof = data['alloc'] * (chg / 100)
                    current_balance += prof
                    used_balance -= data['alloc']
                    post_trade_watchlist[sym] = {
                        'sym': sym, 'score': data['score'], 'entry_p': data['entry_p'],
                        'max_h': data['max_h'], 'min_l': data['min_l'],
                        't_3': data['t_3'], 't_5': data['t_5'], 't_m2': data['t_m2'],
                        'ex_p': p, 'f_chg': chg, 'p_max': chg, 'p_min': chg, 'at': now,
                        'start_time': data['start_time']
                    }
                    send_msg(f"🏁 إغلاق {sym}: {chg:+.2f}%")
                    del active_monitoring[sym]
            except: continue

        # مراقبة ما بعد البيع (30 دقيقة)
        for sym, pdata in list(post_trade_watchlist.items()):
            try:
                if (datetime.now() - pdata['at']).seconds > 1800:
                    log_master_report(pdata, pdata['ex_p'], pdata['f_chg'], pdata['p_max'], pdata['p_min'])
                    del post_trade_watchlist[sym]
                    continue
                p_res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                p = float(p_res['data']['price'])
                c_chg = (p - pdata['entry_p']) / pdata['entry_p'] * 100
                pdata['p_max'] = max(pdata['p_max'], c_chg)
                pdata['p_min'] = min(pdata['p_min'], c_chg)
            except: continue
        
        time.sleep(10)

# --- [4] محرك الرصد والأوامر ---

def discovery_engine():
    global used_balance
    while True:
        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers", timeout=15).json()
            for t in res['data']['ticker']:
                sym, last_p = t['symbol'], float(t['last'])
                vol_24h = float(t['volValue'])
                if not sym.endswith("-USDT") or vol_24h < 300000: continue
                
                score = (float(t['changeRate']) * 100) + (np.log10(vol_24h) * 2)
                if score >= 90 and sym not in active_monitoring:
                    rsi, ema, _ = get_technical_data(sym)
                    if rsi < 70 and last_p > ema:
                        trade_alloc = 150.0 if score >= 95 else 50.0
                        if trade_alloc <= (current_balance - used_balance):
                            used_balance += trade_alloc
                            active_monitoring[sym] = {
                                'sym': sym, 'score': round(score,1), 'entry_p': last_p, 
                                'alloc': trade_alloc, 'max_h': last_p, 'min_l': last_p,
                                'sl': last_p * 0.97, 'tp2': last_p * 1.10, 'be': False,
                                'start_time': datetime.now(), 't_3': None, 't_5': None, 't_m2': None
                            }
                            send_msg(f"🚀 دخول: #{sym} (${trade_alloc}) Score: {round(score,1)}")
        except: pass
        time.sleep(25)

def send_msg(text):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except: pass

def etat(update: Update, context: CallbackContext):
    msg = f"📊 Balance: {current_balance:.2f}$\n📦 Active: {len(active_monitoring)}\n🔍 Tracking: {len(post_trade_watchlist)}"
    update.message.reply_text(msg)

def resultat(update: Update, context: CallbackContext):
    if os.path.exists(TRADING_LOG):
        context.bot.send_document(chat_id=update.effective_chat.id, document=open(TRADING_LOG, 'rb'))
    else: update.message.reply_text("⏳ السجل قيد المعالجة...")

def run_telegram():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("etat", etat))
    dp.add_handler(CommandHandler("resultat", resultat))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    threading.Thread(target=discovery_engine, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
