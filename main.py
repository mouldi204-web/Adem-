import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask

# ==========================================
# 1. إعدادات الاتصال والأمان
# ==========================================
# يفضل ضبط هذه القيم كـ Environment Variables في Railway
TOKEN = os.environ.get('8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68', 'ضع_التوكن_هنا')
CHAT_ID = os.environ.get('5067771509', 'ضع_الايدي_هنا')
BASE_URL = "https://api.kucoin.com"

# إعدادات المحفظة الذكية
INITIAL_BALANCE = 1000.0
current_balance = INITIAL_BALANCE
open_trades_list = []
MAX_CONCURRENT_TRADES = 15

# ==========================================
# 2. خادم ويب مصغر (Keep-Alive & Health Check)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return f"Omega Institutional v14.5 is Active. Current Balance: ${round(current_balance, 2)}"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 3. نظام سجل الأحداث الزمني (Master CSV Log)
# ==========================================
def log_master_timeline(trade, action, price, pnl_usd=0):
    file = 'trading_master_log.csv'
    headers = [
        'Symbol', 'Action', 'Time', 'Price', 'PNL_$', 
        'Total_Balance', 'Entry_Time', 'BE_Time', 'Partial_Time', 'Final_Time'
    ]
    
    file_exists = os.path.isfile(file)
    with open(file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists: writer.writeheader()
        
        writer.writerow({
            'Symbol': trade['symbol'],
            'Action': action,
            'Time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'Price': price,
            'PNL_$': round(pnl_usd, 2),
            'Total_Balance': round(current_balance, 2),
            'Entry_Time': trade.get('entry_time', 'N/A'),
            'BE_Time': trade.get('be_time', 'N/A'),
            'Partial_Time': trade.get('pc_time', 'N/A'),
            'Final_Time': trade.get('fc_time', 'N/A')
        })

# ==========================================
# 4. أوامر التيليجرام الذكية (/csv, /status)
# ==========================================
def handle_telegram_commands():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}"
            res = requests.get(url, timeout=10).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                
                if text == "/csv":
                    send_csv_to_user()
                elif text == "/status":
                    send_smart_msg(
                        f"📊 *تقرير الحالة اللحظي*\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"💰 *الرصيد:* `${round(current_balance, 2)}` \n"
                        f"🕒 *الصفقات النشطة:* `{len(open_trades_list)}` \n"
                        f"📈 *صافي الربح:* `${round(current_balance - INITIAL_BALANCE, 2)}`"
                    )
        except: pass
        time.sleep(3)

def send_csv_to_user():
    file = 'trading_master_log.csv'
    if os.path.exists(file):
        url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
        with open(file, 'rb') as f:
            requests.post(url, data={'chat_id': CHAT_ID}, files={'document': f})
    else:
        send_smart_msg("❌ لم يتم تسجيل أي صفقات بعد.")

def send_smart_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
    except: pass

# ==========================================
# 5. محرك إدارة الصفقات الهجين (Hybrid Management)
# ==========================================
def manage_portfolio():
    global current_balance
    for trade in open_trades_list[:]:
        try:
            # جلب السعر الحالي
            res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={trade['symbol']}").json()
            curr_p = float(res["data"]["price"])
            
            # تحديث MFE (أقصى ربح وصل له السعر)
            pnl_pct = ((curr_p - trade['entry']) / trade['entry']) * 100
            if pnl_pct > trade['mfe']: trade['mfe'] = pnl_pct

            # حالة 1: جني الربح الجزئي (50%) وتأمين الصفقة
            if not trade["partial_done"] and curr_p >= trade["tp1"]:
                trade["partial_done"] = True
                trade["be_time"] = datetime.now().strftime("%H:%M:%S")
                trade["pc_time"] = datetime.now().strftime("%H:%M:%S")
                trade["sl"] = trade["entry"] # تأمين عند الدخول
                
                pnl_usd = (trade['size'] * 0.5) * (pnl_pct / 100)
                current_balance += pnl_usd
                
                log_master_timeline(trade, "PARTIAL_TP_50%", curr_p, pnl_usd)
                send_smart_msg(f"✅ *غلق جزئي 50%* | {trade['symbol']}\nالربح: `${round(pnl_usd, 2)}` \nتأمين الوقف عند الدخول 🛡️")

            # حالة 2: تتبع الربح (Trailing Stop) بعد الهدف الأول
            elif trade["partial_done"]:
                trailing_sl = curr_p - (trade['atr'] * 1.5)
                if trailing_sl > trade["sl"]:
                    trade["sl"] = trailing_sl # رفع الوقف مع السعر
                
                if curr_p <= trade["sl"]:
                    finalize_trade_exit(trade, curr_p, "Trailing SL Hit")

            # حالة 3: ضرب وقف الخسارة الابتدائي
            elif curr_p <= trade["sl"]:
                finalize_trade_exit(trade, curr_p, "Stop Loss Hit")
                
        except Exception as e:
            print(f"Error managing {trade['symbol']}: {e}")

def finalize_trade_exit(trade, price, reason):
    global current_balance
    trade["fc_time"] = datetime.now().strftime("%H:%M:%S")
    
    # حساب الكمية المتبقية (إما 100% أو 50%)
    mult = 0.5 if trade["partial_done"] else 1.0
    pnl_pct = ((price - trade['entry']) / trade['entry']) * 100
    pnl_usd = (trade['size'] * mult) * (pnl_pct / 100)
    current_balance += pnl_usd
    
    log_master_timeline(trade, f"FINAL_EXIT ({reason})", price, pnl_usd)
    
    status_icon = "🏁" if pnl_usd >= 0 else "❌"
    send_smart_msg(
        f"{status_icon} *إغلاق نهائي* | {trade['symbol']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔹 السبب: `{reason}`\n"
        f"💵 ربح الجزء الأخير: `${round(pnl_usd, 2)}`\n"
        f"💰 الرصيد الجديد: `${round(current_balance, 2)}`"
    )
    open_trades_list.remove(trade)

# ==========================================
# 6. التشغيل النهائي (Railway & Docker Ready)
# ==========================================
def main_loop():
    # إشعار بداية التشغيل
    send_smart_msg(
        "🚀 *OMEGA INSTITUTIONAL v14.5 ONLINE*\n"
        "━━━━━━━━━━━━━━━\n"
        "🛰️ النظام جاهز للعمل 24/7 على Railway\n"
        "📊 الفائدة المركبة والوقف المتحرك مفعلة\n"
        "📂 أرسل `/csv` في أي وقت لتحميل السجل"
    )

    # تشغيل الخيوط الفرعية (Threads)
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=handle_telegram_commands, daemon=True).start()

    while True:
        # هنا يتم استدعاء وظيفة المسح (Scanner) للبحث عن فرص
        # وإضافة أي صفقة جديدة لـ open_trades_list
        manage_portfolio()
        time.sleep(10)

if __name__ == "__main__":
    main_loop()
