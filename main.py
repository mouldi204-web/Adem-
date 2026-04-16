import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات (تأكد من صحة البيانات)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID ="5067771509"
CHANNEL_ID = "-1003692815602"  # معرف القناة للإشارات (مثال: @omega_signals)

BASE_URL = "https://api.kucoin.com"
initial_balance = 1000.0
available_balance = initial_balance
MAX_TRADES = 10
open_trades = []

# ملفات السجلات
TRADE_LOG = 'trading_master_log.csv'
ANALYSE_LOG = 'market_discovery_log.csv'
JOURNAL_LOG = 'bot_journal.txt'

app = Flask('')
@app.route('/')
def home(): return f"Omega v35.1 Channel Mode Active."

# ==========================================
# 2. نظام الإرسال المزدوج (قناة + خاص)
# ==========================================

def send_msg(text, destination=CHAT_ID):
    """إرسال رسالة لوجهة محددة (القناة أو الخاص)"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": destination, "text": text, "parse_mode": "Markdown"})
    except: pass

def send_signal_to_channel(msg):
    """وظيفة مخصصة لإرسال الإشارة للقناة والخاص معاً"""
    send_msg(msg, destination=CHANNEL_ID) # إرسال للقناة
    send_msg(msg, destination=CHAT_ID)    # إرسال نسخة لك للتوثيق

# ==========================================
# 3. محرك الرصد المحدث للإرسال للقناة
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
                if not sym.endswith("-USDT") or any(x in sym for x in ["3L", "3S"]): continue
                vol = float(t['volValue'])
                if vol < 80000: continue
                score = 80 + (float(t['changeRate'])*150) + (np.log10(vol)*2)
                scored.append({'symbol': sym, 'price': float(t['last']), 'score': round(score, 1)})

            top_10 = sorted(scored, key=lambda x: x['score'], reverse=True)[:10]
            
            for i, opp in enumerate(top_10):
                rsi_val = calculate_rsi(opp['symbol'])
                
                if i < 3 and len(open_trades) < MAX_TRADES and opp['symbol'] not in [t['symbol'] for t in open_trades]:
                    if rsi_val < 65:
                        quality = "⭐⭐⭐ ذهبية" if opp['score'] > 95 else "⭐⭐ متوسطة"
                        trade_size = available_balance * (0.10 if opp['score'] > 95 else 0.075)
                        
                        available_balance -= trade_size
                        open_trades.append({
                            'symbol': opp['symbol'], 'entry': opp['price'], 'size': trade_size,
                            'sl': opp['price'] * 0.96, 'tp': opp['price'] * 1.05,
                            'score': opp['score'], 'quality': quality, 'start_time': datetime.now()
                        })
                        
                        # تنسيق الرسالة الاحترافي للقناة
                        msg = (f"📢 **إشارة تداول جديدة**\n"
                               f"━━━━━━━━━━━━━━\n"
                               f"💎 **العملة:** #{opp['symbol'].replace('-USDT', '')}\n"
                               f"📊 **الجودة:** {quality}\n"
                               f"💰 **سعر الدخول:** `{opp['price']}`\n"
                               f"🎯 **الهدف المستهدف:** `{round(opp['price']*1.05, 6)}` (+5%)\n"
                               f"🚫 **وقف الخسارة:** `{round(opp['price']*0.96, 6)}` (-4%)\n"
                               f"━━━━━━━━━━━━━━\n"
                               f"📈 **حالة السوق:** {btc_status} | **RSI:** {rsi_val}")
                        
                        send_signal_to_channel(msg)

        except: pass
        time.sleep(40)

# (بقية الدوال manage_trades و handle_commands تبقى كما هي مع التأكد من استدعائها في الأسفل)

def handle_commands():
    last_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_id + 1}&timeout=20"
            res = requests.get(url, timeout=25).json()
            for update in res.get("result", []):
                last_id = update["update_id"]
                msg = update.get("message", {})
                # التحقق أن الأمر قادم من صاحب البوت فقط (CHAT_ID)
                if str(msg.get("chat", {}).get("id")) == str(CHAT_ID):
                    text = msg.get("text", "")
                    if text == "/balance":
                        total = available_balance + sum([t['size'] for t in open_trades])
                        send_msg(f"💰 **الوضع الحالي للمحفظة:**\nمتاح: `${round(available_balance, 2)}`\nإجمالي: `${round(total, 2)}`", CHAT_ID)
                    elif text == "/csv": send_doc(TRADE_LOG)
        except: time.sleep(10)

def send_doc(path):
    if os.path.exists(path):
        with open(path, 'rb') as f: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data={'chat_id': CHAT_ID}, files={'document': f})

if __name__ == "__main__":
    send_msg("🚀 **Omega v35.1** بدأ العمل الآن ويرسل الإشارات للقناة!", CHAT_ID)
    threading.Thread(target=handle_commands, daemon
