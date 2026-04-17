import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- [1] الإعدادات ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1003692815602"] 

FILE_TRADES = 'trades_history.csv'
FILE_ANALYSE = 'market_analysis.csv'

INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
used_balance = 0.0
active_monitoring = {}
current_market_regime = "Unknown"

app = Flask('')
@app.route('/')
def home(): return f"Omega v73.0 Active"

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

# --- [3] محرك المراقبة وتحديد (النجاح/الفشل) ---

def performance_judger():
    global current_balance, used_balance
    while True:
        for sym, data in list(active_monitoring.items()):
            try:
                res = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                p = float(res['data']['price'])
                chg = (p - data['entry_p']) / data['entry_p'] * 100
                
                # تحديث أعلى صعود وأقل نزول
                data['max_up'] = max(data.get('max_up', 0), chg)
                data['max_down'] = min(data.get('max_down', 0), chg)
                data['current_p'] = p # لتحديث الربح العائم في etat

                # منطق النجاح والفشل (الهدف 5% قبل -3%)
                if not data.get('result'):
                    if chg >= 5.0: data['result'] = "SUCCESS ✅"
                    elif chg <= -3.0: data['result'] = "FAILED ❌"

                # خوارزمية الخروج (Trailing Stop)
                if chg >= 5.0:
                    new_sl = (data['entry_p'] * (1 + data['max_up']/100)) * 0.985
                    if new_sl > data['sl']: data['sl'] = new_sl
                elif chg >= 2.0 and not data.get('be'):
                    data['sl'] = data['entry_p']; data['be'] = True

                if p <= data['sl']:
                    prof = data['alloc'] * (chg / 100)
                    current_balance += prof; used_balance -= data['alloc']
                    
                    msg = (
                        f"🏁 *إغلاق صفقة: #{sym}*\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"🏆 *النتيجة النهائية:* `{data.get('result', 'NEUTRAL ⚖️')}`\n"
                        f"💵 *الربح الحقيقي:* `{chg:+.2f}%` (`{prof:+.2f}$`)\n"
                        f"📈 *أعلى صعود:* `+{data['max_up']:.2f}%`\n"
                        f"📉 *أقل نزول:* `{data['max_down']:.2f}%`\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"💰 *الرصيد الجديد:* `{current_balance:.2f} USDT`"
                    )
                    send_msg(msg)
                    
                    log_to_csv(FILE_TRADES, {
                        'Time': datetime.now().strftime('%H:%M'), 'Symbol': sym,
                        'Result': data.get('result', 'N/A'), 'Profit_%': f"{chg:+.2f}%",
                        'Max_Up': f"{data['max_up']:.2f}%", 'Max_Down': f"{data['max_down']:.2f}%",
                        'Entry': data['entry_p'], 'Exit': p
                    })
                    del active_monitoring[sym]
            except: continue
        time.sleep(10)

# --- [4] محرك البحث والتحليل ---

def discovery_engine():
    global used_balance
    while True:
        try:
            res = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=15).json()
            for t in res['data']['ticker']:
                sym, last_p = t['symbol'], float(t['last'])
                if not sym.endswith("-USDT") or float(t['volValue']) < 200000: continue
                score = round((float(t['changeRate']) * 100) + (np.log10(float(t['volValue'])) * 2), 1)
                
                if score >= 80 and sym not in active_monitoring:
                    # جلب بيانات فنية سريعة
                    # (هنا نستخدم السعر والوقت كبداية للاكتشاف والمراقبة)
                    alloc = 100.0 if score >= 90 else 50.0
                    if (current_balance - used_balance) >= alloc:
                        used_balance += alloc
                        active_monitoring[sym] = {
                            'sym': sym, 'entry_p': last_p, 'alloc': alloc, 'current_p': last_p,
                            'sl': last_p * 0.97, 'max_up': 0, 'max_down': 0, 
                            'start_time': datetime.now(), 'score': score
                        }
                        send_msg(f"🚀 *اكتشاف فرصة:* #{sym} | سكور: `{score}` | السعر: `{last_p}`")
                    
                    log_to_csv(FILE_ANALYSE, {
                        'Discover_Time': datetime.now().strftime('%H:%M:%S'),
                        'Symbol': sym, 'Price_at_Disc': last_p, 'Score': score
                    })
        except: pass
        time.sleep(30)

# --- [5] أوامر تليجرام المحدثة (ETAT) ---

def etat(update: Update, context: CallbackContext):
    # حساب الربح العائم
    floating_pnl = 0
    for sym, data in active_monitoring.items():
        floating_pnl += (data['current_p'] - data['entry_p']) / data['entry_p'] * 100
    
    avg_floating = floating_pnl / len(active_monitoring) if active_monitoring else 0
    total_val = current_balance + (used_balance * (1 + avg_floating/100 if active_monitoring else 1))
    
    status_power = "HIGH 🔥" if len(active_monitoring) > 3 else "STABLE 💎"
    
    msg = (
        f"📊 *حالة النظام اللحظية:*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔋 *قوة العمل:* `{status_power}`\n"
        f"🌍 *حالة السوق:* `{current_market_regime}`\n"
        f"📦 *الصفقات المفتوحة:* `{len(active_monitoring)}` صفقات\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 *إجمالي المحفظة:* `{total_val:.2f} USDT`\n"
        f"💵 *الرصيد المتاح:* `{current_balance - used_balance:.2f} USDT`\n"
        f"📈 *الربح العائم:* `{avg_floating:+.2f}%` (النتيجة الحالية)\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📡 *Adem_trading_bot Active*"
    )
    update.message.reply_text(msg, parse_mode='Markdown')

def run_telegram():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("etat", etat))
    dp.add_handler(CommandHandler("analyse", lambda u, c: c.bot.send_document(chat_id=u.effective_chat.id, document=open(FILE_ANALYSE, 'rb'))))
    dp.add_handler(CommandHandler("resultat", lambda u, c: c.bot.send_document(chat_id=u.effective_chat.id, document=open(FILE_TRADES, 'rb'))))
    updater.start_polling(); updater.idle()

if __name__ == "__main__":
    threading.Thread(target=discovery_engine, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
