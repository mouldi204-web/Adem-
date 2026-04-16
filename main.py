import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات (بياناتك الشخصية)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

# قائمة لمتابعة أداء العملات المسجلة
monitoring_list = {} 

# ملف السجلات للتحليل اللاحق
ANALYSE_LOG = 'market_discovery_log.csv'
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Score', 'Entry_Price', 'Max_Up_%', 'Max_Down_%', 'Result', 'Duration_Min']

app = Flask('')
@app.route('/')
def home(): return "Omega v37.4 Stable - Smart Signals Active."

# ==========================================
# 2. نظام الإشعارات الذكية (Smart Notifications)
# ==========================================

def send_msg(text):
    """دالة مركزية لإرسال الرسائل لتجنب أخطاء التعريف"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def send_smart_entry_msg(sym, score, entry_p):
    """إشعار منسق عند دخول العملة منطقة الرصد"""
    msg = (f"🚀 **إشعار دخول ذكي**\n"
           f"━━━━━━━━━━━━━━\n"
           f"💎 **العملة:** #{sym.replace('-USDT', '')}\n"
           f"📈 **السكور:** `{score}`\n"
           f"🎯 **نقطة الدخول:** `{entry_p}`\n"
           f"🏁 **الأهداف:** `+4%` | `-2%`\n"
           f"━━━━━━━━━━━━━━\n"
           f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    send_msg(msg)

def send_smart_exit_msg(sym, result, data):
    """إشعار منسق عند حسم النتيجة (نجاح/فشل)"""
    duration = round((datetime.now() - data['start_time']).total_seconds() / 60, 1)
    status_icon = "🟢" if "نجاح" in result else "🔴"
    
    msg = (f"{status_icon} **إشعار حسم النتيجة**\n"
           f"━━━━━━━━━━━━━━\n"
           f"💎 **العملة:** #{sym.replace('-USDT', '')}\n"
           f"📊 **النتيجة:** `{result}`\n"
           f"📈 **أقصى صعود:** `+{round(data['max_up'], 2)}%`\n"
           f"📉 **أقصى هبوط:** `{round(data['max_down'], 2)}%`\n"
           f"⏱️ **المدة:** `{duration}` دقيقة\n"
           f"━━━━━━━━━━━━━━")
    send_msg(msg)

# ==========================================
# 3. محرك الحكم والتسجيل (Judging Engine)
# ==========================================

def performance_judger():
    """يراقب العملات المحفوظة ويحدد النجاح أو الفشل"""
    while True:
        for sym, data in list(monitoring_list.items()):
            try:
                # جلب السعر اللحظي
                res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                if 'data' not in res or res['data'] is None: continue
                
                curr_p = float(res['data']['price'])
                
                # حساب النسبة المئوية للتغير من نقطة الدخول
                change = (curr_p - data['entry_price']) / data['entry_price'] * 100
                data['max_up'] = max(data['max_up'], change)
                data['max_down'] = min(data['max_down'], change)

                # الحكم: نجاح (+4%) أو فشل (-2%)
                if change >= 4.0:
                    data['result'] = "نجاح ✅"
                    save_to_csv(sym, data)
                    send_smart_exit_msg(sym, data['result'], data)
                    del monitoring_list[sym]
                
                elif change <= -2.0:
                    data['result'] = "فشل ❌"
                    save_to_csv(sym, data)
                    send_smart_exit_msg(sym, data['result'], data)
                    del monitoring_list[sym]
            except Exception as e:
                print(f"Error judging {sym}: {e}")
                continue
        time.sleep(15)

def save_to_csv(sym, data):
    """تصدير البيانات النهائية للملف"""
    duration = round((datetime.now() - data['start_time']).total_seconds() / 60, 1)
    file_exists = os.path.isfile(ANALYSE_LOG)
    with open(ANALYSE_LOG, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=ANALYSE_HEADERS)
        if not file_exists: writer.writeheader()
        writer.writerow({
            'Timestamp': data['start_time'].strftime("%H:%M:%S"),
            'Symbol': sym, 'Score': data['score'], 'Entry_Price': data['entry_price'],
            'Max_Up_%': round(data['max_up'], 2), 'Max_Down_%': round(data['max_down'], 2),
            'Result': data['result'], 'Duration_Min': duration
        })

# ==========================================
# 4. محرك الرصد (Elite Scanner Score > 90)
# ==========================================

def discovery_engine():
    """يبحث عن العملات التي تحقق سكور أعلى من 90"""
    while True:
        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers", timeout=15).json()
            tickers = res['data']['ticker']
            
            for t in tickers:
                sym = t['symbol']
                # تصفية العملات المطلوبة
                if not sym.endswith("-USDT") or any(x in sym for x in ["3L", "3S", "UP", "DOWN"]): continue
                
                vol = float(t['volValue'])
                if vol < 100000: continue
                
                # حساب السكور الخوارزمي
                score = 80 + (float(t['changeRate'])*150) + (np.log10(vol)*2)
                
                if score >= 90 and sym not in monitoring_list:
                    # احتساب نقطة الدخول الواقعية (سعر Ask)
                    res_book = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}", timeout=10).json()
                    entry_p = float(res_book['data']['ask'])
                    
                    monitoring_list[sym] = {
                        'entry_price': entry_p, 'score': round(score, 1),
                        'start_time': datetime.now(), 'max_up': 0.0, 'max_down': 0.0, 'result': "Pending"
                    }
                    send_smart_entry_msg(sym, round(score, 1), entry_p)
        except Exception as e:
            print(f"Scanner Error: {e}")
        time.sleep(40)

# ==========================================
# 5. نظام الأوامر (Command System)
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
                if str(msg.get("chat", {}).get("id")) == str(CHAT_ID):
                    text = msg.get("text", "")
                    if text == "/balance":
                        send_msg(f"📊 **حالة النظام:**\nمراقبة نشطة: {len(monitoring_list)} عملات.")
                    elif text == "/csv":
                        if os.path.exists(ANALYSE_LOG):
                            with open(ANALYSE_LOG, 'rb') as f:
                                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", 
                                              data={'chat_id': CHAT_ID}, files={'document': f})
        except: time.sleep(10)

if __name__ == "__main__":
    send_msg("⚙️ **نظام Omega v37.4 قيد التشغيل**\nيتم رصد السكور > 90 وتحليل الأهداف.")
    
    # تشغيل العمليات في الخلفية
    threading.Thread(target=handle_commands, daemon=True).start()
    threading.Thread(target=performance_judger, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    
    # تشغيل سيرفر الويب للبقاء حياً على الاستضافة
    serve(app, host='0.0.0.0', port=8080)
