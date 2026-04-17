import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime, timedelta
from flask import Flask
from waitress import serve
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- [1] الإعدادات الأساسية ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1003692815602"] 

FILE_TRADES = 'trades_history.csv'
FILE_ANALYSE = 'market_analysis.csv'

INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
used_balance = 0.0
active_monitoring = {}
post_trade_watch = {}
market_discovery = {}
current_market_regime = "Unknown"

app = Flask('')
@app.route('/')
def home(): return f"Adem_trading| Adem__trading"

# --- [2] محرك الإشعارات والتوثيق ---

def send_msg(text):
    for chat_id in TARGET_CHATS:
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                         data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
        except: pass

def log_to_csv(file_name, data):
    file_exists = os.path.isfile(file_name)
    headers = list(data.keys())
    with open(file_name, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists: writer.writeheader()
        writer.writerow(data)

# --- [3] محرك مراقبة الأداء وما بعد الخروج ---

def performance_judger():
    global current_balance, used_balance
    while True:
        # 1. مراقبة الصفقات المفتوحة
        for sym, data in list(active_monitoring.items()):
            try:
                p = float(requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={sym}").json()['data']['price'])
                chg = (p - data['entry_p']) / data['entry_p'] * 100
                data['max_up'] = max(data.get('max_up', 0), chg)
                data['max_down'] = min(data.get('max_down', 0), chg)
                data['current_p'] = p

                if p <= data['sl'] or chg >= 15.0:
                    prof = data['alloc'] * (chg / 100)
                    current_balance += prof; used_balance -= data['alloc']
                    duration = str(datetime.now() - data['start_time']).split('.')[0]
                    
                    # نقل للمراقبة البعدية
                    post_trade_watch[sym] = {
                        'exit_p': p, 'exit_time': datetime.now(), 'max_after': 0,
                        'duration': duration, 'final_chg': chg, 'orig_max': data['max_up']
                    }
                    
                    msg = (
                        f"🏁 *إغلاق صفقة: #{sym}*\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"💵 *الربح المحقق:* `{chg:+.2f}%` (`{prof:+.2f}$`)\n"
                        f"🕒 *مدة الصفقة:* `{duration}`\n"
                        f"🔝 *أعلى قمة وصل لها:* `+{data['max_up']:.2f}%` 📈\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"📡 *Adem__trading*"
                    )
                    send_msg(msg)
                    del active_monitoring[sym]
            except: continue

        # 2. مراقبة سلوك العملة بعد الخروج (30 دقيقة)
        for sym, pdata in list(post_trade_watch.items()):
            try:
                p = float(requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={sym}").json()['data']['price'])
                after_chg = (p - pdata['exit_p']) / pdata['exit_p'] * 100
                pdata['max_after'] = max(pdata['max_after'], after_chg)
                
                if (datetime.now() - pdata['exit_time']).seconds > 1800:
                    log_to_csv(FILE_TRADES, {
                        'Close_Time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'Symbol': sym, 'Profit_%': f"{pdata['final_chg']:.2f}%", 
                        'Duration': pdata['duration'], 'Max_During': f"{pdata['orig_max']:.2f}%",
                        'Max_After_Exit': f"{pdata['max_after']:.2f}%",
                        'Behavior': "MOVED UP 📈" if pdata['max_after'] > 2 else "GOOD EXIT ✅"
                    })
                    del post_trade_watch[sym]
            except: continue
        time.sleep(15)

# --- [4] محرك تحليل الاكتشاف (Win/Loss & Speed) ---

def discovery_analyzer():
    global used_balance
    while True:
        try:
            res = requests.get("https://api.kucoin.com/api/v1/market/allTickers").json()
            for t in res['data']['ticker']:
                sym, last_p = t['symbol'], float(t['last'])
                vol = float(t['volValue'])
                if not sym.endswith("-USDT") or vol < 200000: continue
                score = round((float(t['changeRate']) * 100) + (np.log10(vol) * 2), 1)

                if score >= 80 and sym not in market_discovery:
                    market_discovery[sym] = {
                        'start_p': last_p, 'start_time': datetime.now(), 'score': score,
                        't3': None, 't5': None, 'tm2': None, 'tm3': None, 'max_up': 0, 'max_down': 0
                    }
                    # إشعار الدخول المطور
                    if sym not in active_monitoring:
                        alloc = 150.0 if score >= 95 else 50.0
                        if (current_balance - used_balance) >= alloc:
                            used_balance += alloc
                            active_monitoring[sym] = {'sym': sym, 'entry_p': last_p, 'alloc': alloc, 'current_p': last_p, 'sl': last_p * 0.97, 'max_up': 0, 'max_down': 0, 'start_time': datetime.now()}
                            
                            roi_est = 5.0 + (score - 80) / 10
                            surge_est = roi_est + 2.5
                            msg = (
                                f"📥 *دخول صفقة جديدة: #{sym}*\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"🎯 *الهدف التقديري:* `+{roi_est:.1f}%` 🔥\n"
                                f"📈 *الارتفاع المتوقع:* `+{surge_est:.1f}%` 🚀\n"
                                f"📊 *قوة الإشارة (Score):* `{score}`\n"
                                f"💰 *سعر الدخول:* `{last_p:.8f}`\n"
                                f"🛡 *وقف الخسارة:* `-3%`\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"📡 *Adem__trading*"
                            )
                            send_msg(msg)

                if sym in market_discovery:
                    d = market_discovery[sym]
                    curr_chg = (last_p - d['start_p']) / d['start_p'] * 100
                    d['max_up'] = max(d['max_up'], curr_chg)
                    d['max_down'] = min(d['max_down'], curr_chg)
                    now = datetime.now()
                    
                    if curr_chg >= 3.0 and not d['t3']: d['t3'] = str(now - d['start_time']).split('.')[0]
                    if curr_chg >= 5.0 and not d['t5']: d['t5'] = str(now - d['start_time']).split('.')[0]
                    if curr_chg <= -2.0 and not d['tm2']: d['tm2'] = str(now - d['start_time']).split('.')[0]
                    if curr_chg <= -3.0 and not d['tm3']: d['tm3'] = str(now - d['start_time']).split('.')[0]

                    if d['t5'] or d['tm3'] or (now - d['start_time']).seconds > 7200:
                        res_val = "WIN ✅" if (d['t5'] and (not d['tm3'] or d['t5'] < d['tm3'])) else "LOSS ❌"
                        log_to_csv(FILE_ANALYSE, {
                            'Time': d['start_time'].strftime('%H:%M'), 'Symbol': sym, 'Score': d['score'],
                            'Result': res_val, 'T_+5%': d['t5'] or 'N/A', 'T_+3%': d['t3'] or 'N/A',
                            'T_-2%': d['tm2'] or 'N/A', 'Max_Peak': f"{d['max_up']:.2f}%", 'Min_Drop': f"{d['max_down']:.2f}%"
                        })
                        del market_discovery[sym]
        except: pass
        time.sleep(20)

# --- [5] أوامر تليجرام ---

def etat(update: Update, context: CallbackContext):
    floating_pnl = sum([(d['current_p'] - d['entry_p']) / d['entry_p'] * 100 for d in active_monitoring.values()])
    avg_floating = floating_pnl / len(active_monitoring) if active_monitoring else 0
    total_val = current_balance + (used_balance * (1 + avg_floating/100 if active_monitoring else 1))
    
    msg = (
        f"📊 *تقرير أوميجا v76.0:*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔋 *قوة العمل:* `{'HIGH 🔥' if len(active_monitoring) > 3 else 'STABLE 💎'}`\n"
        f"🌍 *حالة السوق:* `{current_market_regime}`\n"
        f"📦 *المفتوحة:* `{len(active_monitoring)}` صفقات\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 *المحفظة:* `{total_val:.2f} USDT`\n"
        f"💵 *المتاح:* `{current_balance - used_balance:.2f} USDT`\n"
        f"📈 *النتيجة العائمة:* `{avg_floating:+.2f}%` 🌊\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📡 *Adem__trading*"
    )
    update.message.reply_text(msg, parse_mode='Markdown')

def update_market_logic():
    global current_market_regime
    while True:
        try:
            res = requests.get("https://api.kucoin.com/api/v1/market/candles?symbol=BTC-USDT&type=15min").json()
            closes = [float(c[2]) for c in res['data'][:20]]
            ema = pd.Series(closes[::-1]).ewm(span=20, adjust=False).mean().iloc[-1]
            current_market_regime = "BULLISH 🟢" if closes[0] > ema else "BEARISH 🔴"
        except: pass
        time.sleep(300)

def run_telegram():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("etat", etat))
    dp.add_handler(CommandHandler("analyse", lambda u, c: c.bot.send_document(chat_id=u.effective_chat.id, document=open(FILE_ANALYSE, 'rb'))))
    dp.add_handler(CommandHandler("resultat", lambda u, c: c.bot.send_document(chat_id=u.effective_chat.id, document=open(FILE_TRADES, 'rb'))))
    updater.start_polling(); updater.idle()

if __name__ == "__main__":
    threading.Thread(target=update_market_logic, daemon=True).start()
    threading.Thread(target=discovery_analyzer, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
