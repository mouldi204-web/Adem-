import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- [1] الإعدادات ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1003692815602"] # ضع معرف قناتك هنا

FILE_TRADES = 'trades_history.csv'
FILE_ANALYSE = 'market_analysis.csv'

INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
used_balance = 0.0
active_monitoring = {}
current_market_regime = "Unknown"

app = Flask('')
@app.route('/')
def home(): return f"Omega v72.0 Active. Balance: {current_balance:.2f}"

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

# --- [3] محرك الأداء ومراقبة الأهداف الزمنية ---

def performance_judger():
    global current_balance, used_balance
    while True:
        for sym, data in list(active_monitoring.items()):
            try:
                res = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                p = float(res['data']['price'])
                chg = (p - data['entry_p']) / data['entry_p'] * 100
                data['max_h'] = max(data['max_h'], p)
                
                now = datetime.now()
                # رصد اللحظات الزمنية للأهداف
                if chg >= 3.0 and not data.get('t3'):
                    data['t3'] = str(now - data['start_time']).split('.')[0]
                if chg >= 5.0 and not data.get('t5'):
                    data['t5'] = str(now - data['start_time']).split('.')[0]
                if chg <= -2.0 and not data.get('tm2'):
                    data['tm2'] = str(now - data['start_time']).split('.')[0]

                # خوارزمية الخروج (Trailing Stop)
                if chg >= 5.0:
                    new_sl = data['max_h'] * 0.985
                    if new_sl > data['sl']: data['sl'] = new_sl
                elif chg >= 2.0 and not data.get('be'):
                    data['sl'] = data['entry_p']; data['be'] = True

                if p <= data['sl']:
                    prof = data['alloc'] * (chg / 100)
                    current_balance += prof; used_balance -= data['alloc']
                    duration = str(now - data['start_time']).split('.')[0]
                    max_p = ((data['max_h']-data['entry_p'])/data['entry_p']*100)
                    
                    # شكل إشعار الإغلاق المطور
                    msg = (
                        f"🏁 *إغلاق صفقة: #{sym}*\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"💵 *الربح/الخسارة:* `{chg:+.2f}%` (`{prof:+.2f}$`)\n"
                        f"🔝 *أعلى قمة:* `{max_p:+.2f}%` 📈\n"
                        f"⏱ *سجل سرعة الانفجار:*\n"
                        f"  ▫️ وصول +3%: `{data.get('t3', '---')}`\n"
                        f"  ▫️ وصول +5%: `{data.get('t5', '---')}`\n"
                        f"  ▫️ هبوط -2%: `{data.get('tm2', '---')}`\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🕒 *المدة الإجمالية:* `{duration}`\n"
                        f"💰 *رصيد المحفظة:* `{current_balance:.2f} USDT`"
                    )
                    send_msg(msg)
                    
                    # تدوين في CSV بشكل منظم
                    log_to_csv(FILE_TRADES, {
                        'Close_Time': now.strftime('%Y-%m-%d %H:%M'),
                        'Symbol': sym,
                        'Profit_%': f"{chg:+.2f}%",
                        'Peak_%': f"{max_p:+.2f}%",
                        'T_+3%': data.get('t3', 'N/A'),
                        'T_+5%': data.get('t5', 'N/A'),
                        'T_-2%': data.get('tm2', 'N/A'),
                        'Duration': duration
                    })
                    del active_monitoring[sym]
            except: continue
        time.sleep(15)

# --- [4] محرك البحث والتحليل الفني ---

def get_technical_data(symbol):
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol}&type=5min"
        res = requests.get(url, timeout=10).json()
        candles = res['data'][::-1]
        closes = [float(c[2]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        rsi = 100 - (100 / (1 + (sum([max(0, closes[i]-closes[i-1]) for i in range(-14, 0)]) / (sum([max(0, closes[i-1]-closes[i]) for i in range(-14, 0)]) or 1))))
        ema_20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        spike = volumes[-1] / (sum(volumes[-11:-1])/10 or 1)
        return rsi, ema_20, spike
    except: return 50, 0, 1.0

def discovery_engine():
    global used_balance
    while True:
        try:
            res = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=15).json()
            for t in res['data']['ticker']:
                sym, last_p = t['symbol'], float(t['last'])
                vol_24h = float(t['volValue'])
                if not sym.endswith("-USDT") or vol_24h < 200000: continue
                score = round((float(t['changeRate']) * 100) + (np.log10(vol_24h) * 2), 1)
                
                if score >= 80 and sym not in active_monitoring:
                    rsi, ema, spike = get_technical_data(sym)
                    
                    # تحليل البيانات للتخزين في ملف analyse
                    status = "SKIPPED"
                    reason = "N/A"
                    
                    if rsi >= 70: reason = "RSI High"
                    elif last_p <= ema: reason = "Below EMA20"
                    elif spike < 1.5: reason = "Low Vol Spike"
                    else:
                        alloc = 150.0 if score >= 95 else 50.0
                        if (current_balance - used_balance) >= alloc:
                            used_balance += alloc
                            active_monitoring[sym] = {
                                'sym': sym, 'entry_p': last_p, 'alloc': alloc, 
                                'max_h': last_p, 'sl': last_p * 0.97, 'start_time': datetime.now()
                            }
                            status = "ENTERED"
                            # إشعار الدخول المطور
                            roi_est = 5.0 + (spike * 0.5) + ((score - 80) / 10)
                            msg = (
                                f"🚀 *دخول فرصة: #{sym}*\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"🎯 *هدف تقديري:* `+{roi_est:.1f}%` 🔥\n"
                                f"📊 *المعطيات:* سكور `{score}` | RSI `{round(rsi,1)}`\n"
                                f"🔥 *الزخم:* `{spike:.2f}x` | 🌍 `{current_market_regime}`\n"
                                f"💰 *السعر:* `{last_p:.8f}`"
                            )
                            send_msg(msg)
                    
                    log_to_csv(FILE_ANALYSE, {
                        'Time': datetime.now().strftime('%H:%M:%S'),
                        'Symbol': sym, 'Score': score, 'RSI': round(rsi,1),
                        'Spike': f"{spike:.2f}x", 'Action': status, 'Reason': reason
                    })
        except: pass
        time.sleep(30)

# --- [5] تشغيل النظام ---

def update_market_logic():
    global current_market_regime
    while True:
        try:
            url = "https://api.kucoin.com/api/v1/market/candles?symbol=BTC-USDT&type=15min"
            res = requests.get(url, timeout=10).json()
            closes = [float(c[2]) for c in res['data'][:20]]
            ema_20 = pd.Series(closes[::-1]).ewm(span=20, adjust=False).mean().iloc[-1]
            current_market_regime = "BULLISH 🟢" if closes[0] > ema_20 else "BEARISH 🔴"
        except: pass
        time.sleep(300)

def run_telegram():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("etat", lambda u, c: u.message.reply_text(f"💰 Balance: {current_balance:.2f}$ | Market: {current_market_regime}")))
    dp.add_handler(CommandHandler("analyse", lambda u, c: c.bot.send_document(chat_id=u.effective_chat.id, document=open(FILE_ANALYSE, 'rb'))))
    dp.add_handler(CommandHandler("resultat", lambda u, c: c.bot.send_document(chat_id=u.effective_chat.id, document=open(FILE_TRADES, 'rb'))))
    updater.start_polling(); updater.idle()

if __name__ == "__main__":
    threading.Thread(target=update_market_logic, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
