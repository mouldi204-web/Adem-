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

FILE_TRADES = 'trades_history.csv'    # سجل الأرباح والخسائر
FILE_ANALYSE = 'market_analysis.csv'  # سجل مراقبة السكور 80+

INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
used_balance = 0.0
active_monitoring = {}
current_market_regime = "Unknown"

app = Flask('')
@app.route('/')
def home(): return f"Omega v65.0 Active. Market: {current_market_regime}"

# --- [2] محرك الإشعارات المطور ---

def send_msg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                     data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def log_to_csv(file_name, data):
    file_exists = os.path.isfile(file_name)
    headers = list(data.keys())
    with open(file_name, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
            if file_name == FILE_ANALYSE:
                send_msg(f"📂 *تنبيه:* تم إنشاء قاعدة بيانات التحليل `{FILE_ANALYSE}`")
        writer.writerow(data)

def get_technical_data(symbol):
    try:
        url = f"{BASE_URL}/api/v1/market/candles?symbol={symbol}&type=5min"
        res = requests.get(url, timeout=10).json()
        if 'data' not in res or len(res['data']) < 20: return 50, 0, 0, 1.0
        candles = res['data'][::-1]
        closes = [float(c[2]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        
        diffs = np.diff(closes)
        gains = [d if d > 0 else 0 for d in diffs]; losses = [-d if d < 0 else 0 for d in diffs]
        avg_gain = sum(gains[-14:])/14; avg_loss = sum(losses[-14:])/14
        rsi = 100 - (100 / (1 + (avg_gain/avg_loss))) if avg_loss != 0 else 100
        ema_20 = pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1]
        
        avg_vol = sum(volumes[-11:-1]) / 10
        vol_spike = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
        return rsi, ema_20, closes[-1], vol_spike
    except: return 50, 0, 0, 1.0

# --- [3] محرك الرصد والتحليل (التعديل المطلوب) ---

def discovery_engine():
    global used_balance
    while True:
        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers", timeout=15).json()
            for t in res['data']['ticker']:
                sym, last_p = t['symbol'], float(t['last'])
                vol_24h = float(t['volValue'])
                if not sym.endswith("-USDT") or vol_24h < 200000: continue
                
                score = round((float(t['changeRate']) * 100) + (np.log10(vol_24h) * 2), 1)
                
                if score >= 80:
                    rsi, ema, _, spike = get_technical_data(sym)
                    
                    analysis_data = {
                        'Time': datetime.now().strftime('%H:%M:%S'),
                        'Symbol': sym, 'Score': score, 'RSI': round(rsi,1),
                        'Vol_Spike': f"{spike:.2f}x", 'Price': last_p,
                        'Market': current_market_regime, 'Action': 'SKIPPED', 'Reason': 'N/A'
                    }

                    if sym in active_monitoring:
                        analysis_data['Action'] = 'MONITORING'
                    elif rsi >= 70:
                        analysis_data['Reason'] = 'Overbought (RSI)'
                    elif last_p <= ema:
                        analysis_data['Reason'] = 'Below EMA20'
                    elif spike < 1.5:
                        analysis_data['Reason'] = 'Low Momentum'
                    else:
                        alloc = 150.0 if score >= 95 else 50.0
                        if (current_balance - used_balance) >= alloc:
                            used_balance += alloc
                            active_monitoring[sym] = {
                                'sym': sym, 'score': score, 'rsi': rsi, 'spike': spike,
                                'entry_p': last_p, 'alloc': alloc, 'max_h': last_p, 
                                'sl': last_p * 0.97, 'start_time': datetime.now()
                            }
                            analysis_data['Action'] = 'ENTERED'
                            
                            # إشعار الدخول المطور
                            expected_roi = 5.0 + (spike * 0.5) + ((score - 80) / 10)
                            msg = (
                                f"🚀 *دخول فرصة جديدة: #{sym}*\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"📝 *السبب:* `سكور عالٍ + انفجار سيولة`\n"
                                f"🎯 *الهدف المتوقع:* `+{expected_roi:.1f}%` 🔥\n"
                                f"📊 *المعطيات:* سكور `{score}` | RSI `{round(rsi,1)}`\n"
                                f"🔥 *الزخم:* `{spike:.2f}x` | السوق `{current_market_regime}`\n"
                                f"💰 *الدخول:* `{last_p:.8f}` | الكمية `{alloc}$`"
                            )
                            send_msg(msg)
                        else:
                            analysis_data['Reason'] = 'InSufficient Balance'
                    
                    log_to_csv(FILE_ANALYSE, analysis_data)
        except: pass
        time.sleep(30)

def performance_judger():
    global current_balance, used_balance
    while True:
        for sym, data in list(active_monitoring.items()):
            try:
                p = float(requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()['data']['price'])
                chg = (p - data['entry_p']) / data['entry_p'] * 100
                data['max_h'] = max(data['max_h'], p)
                
                # Trailing Stop & Break Even
                if chg >= 5.0:
                    new_sl = data['max_h'] * 0.985
                    if new_sl > data['sl']: data['sl'] = new_sl
                elif chg >= 2.0 and not data.get('be'):
                    data['sl'] = data['entry_p']; data['be'] = True

                if p <= data['sl']:
                    prof = data['alloc'] * (chg / 100)
                    current_balance += prof; used_balance -= data['alloc']
                    duration = str(datetime.now() - data['start_time']).split('.')[0]
                    max_reach = ((data['max_h']-data['entry_p'])/data['entry_p']*100)
                    
                    # إشعار الإغلاق المطور
                    msg = (
                        f"🏁 *إغلاق صفقة: #{sym}*\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"💵 *النتيجة النهائية:* `{chg:+.2f}%` (`{prof:+.2f}$`)\n"
                        f"🔝 *أعلى قمة وصل لها:* `{max_reach:+.2f}%` 📈\n"
                        f"🕒 *مدة البقاء:* `{duration}`\n"
                        f"💰 *الرصيد المحقق:* `{current_balance:.2f} USDT`"
                    )
                    send_msg(msg)
                    
                    log_to_csv(FILE_TRADES, {
                        'Close_Time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'Symbol': sym, 'Profit_%': f"{chg:+.2f}%", 'Profit_$': f"{prof:+.2f}$",
                        'Duration': duration, 'Max_Peak': f"{max_reach:+.2f}%", 'Score_At_Entry': data['score']
                    })
                    del active_monitoring[sym]
            except: continue
        time.sleep(15)

# --- [4] أوامر تليجرام المحدثة (etat, analyse, resultat) ---

def etat(update: Update, context: CallbackContext):
    total_val = current_balance
    avail = current_balance - used_balance
    msg = (
        f"📊 *الحالة اللحظية للمحفظة:*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🌍 *حالة السوق:* `{current_market_regime}`\n"
        f"💰 *المحفظة الإجمالية:* `{total_val:.2f} USDT`\n"
        f"💵 *الرصيد المتاح:* `{avail:.2f} USDT`\n"
        f"🔒 *القيمة في الصفقات:* `{used_balance:.2f} USDT`\n"
        f"📦 *عدد الصفقات النشطة:* `{len(active_monitoring)}`"
    )
    update.message.reply_text(msg, parse_mode='Markdown')

def analyse(update: Update, context: CallbackContext):
    if os.path.exists(FILE_ANALYSE):
        with open(FILE_ANALYSE, 'rb') as f:
            context.bot.send_document(chat_id=update.effective_chat.id, document=f, filename="market_analysis.csv", caption="🔍 تحليل جميع فرص السكور 80+")
    else: update.message.reply_text("⏳ لم يتم رصد أي سكور 80+ بعد.")

def resultat(update: Update, context: CallbackContext):
    if os.path.exists(FILE_TRADES):
        with open(FILE_TRADES, 'rb') as f:
            context.bot.send_document(chat_id=update.effective_chat.id, document=f, filename="trades_history.csv", caption="✅ سجل الصفقات المغلقة فقط")
    else: update.message.reply_text("⏳ لا توجد صفقات مغلقة في السجل.")

def run_telegram():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("etat", etat))
    dp.add_handler(CommandHandler("resultat", resultat))
    dp.add_handler(CommandHandler("analyse", analyse))
    updater.start_polling()
    send_msg("✅ *تم التشغيل بنجاح!*\nاستخدم /analyse لمراجعة السكور و /resultat للأرباح.")
    updater.idle()

if __name__ == "__main__":
    threading.Thread(target=update_market_regime, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=run_telegram, daemon=True).start()
    serve(app, host='0.0.0.0', port=8080)
