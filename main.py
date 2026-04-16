import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات الأساسية
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "-1003692815602" 

BASE_URL = "https://api.kucoin.com"
initial_balance = 1000.0
available_balance = initial_balance
MAX_TRADES = 10
open_trades = []

# قائمة مراقبة ممتدة للعملات (حتى بعد الخروج) لجمع الإحصائيات
extended_watchlist = {} 

# ملفات السجلات
TRADE_LOG = 'trading_master_log.csv'
ANALYSE_LOG = 'market_discovery_log.csv'

# أعمدة سجل التحليل المطور
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Score', 'Initial_Price', 'Current_Result', 'Max_Gain_%', 'Max_Drawdown_%', 'Status', 'Duration_to_Target_Min']

app = Flask('')
@app.route('/')
def home(): return f"Omega v36.0 Strategy Validator Active."

# ==========================================
# 2. محرك المراقبة والتحليل (The Validator)
# ==========================================

def track_extended_performance():
    """يراقب أداء كل عملة ظهرت بسكور > 90 لقياس مدى نجاح الاستراتيجية"""
    while True:
        for sym, data in list(extended_watchlist.items()):
            try:
                # جلب السعر الحالي
                res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}").json()
                curr_p = float(res['data']['price'])
                
                # حساب النسبة من سعر الرصد الأول
                change_pct = (curr_p - data['start_price']) / data['start_price'] * 100
                
                # تحديث أقصى صعود وأقصى هبوط
                data['max_up'] = max(data['max_up'], change_pct)
                data['max_down'] = min(data['max_down'], change_pct)
                
                # فحص الأهداف (4% نجاح، -2% فشل)
                if data['final_status'] == "Monitoring":
                    duration = round((datetime.now() - data['start_time']).total_seconds() / 60, 1)
                    
                    if change_pct >= 4.0:
                        data['final_status'] = "SUCCESS ✅"
                        data['time_to_reach'] = duration
                        send_msg(f"🎯 تحليل: العملة `{sym}` حققت هدف 4%+ بنجاح خلال {duration} دقيقة.")
                    
                    elif change_pct <= -2.0:
                        data['final_status'] = "FAILED ❌"
                        data['time_to_reach'] = duration
                        send_msg(f"📉 تحليل: العملة `{sym}` لمست -2% (فشل الاستراتيجية) خلال {duration} دقيقة.")

                # حفظ وتحديث البيانات في ملف التحليل بشكل دوري
                save_analysis_data(sym, data)
                
            except: continue
        time.sleep(20)

def save_analysis_data(sym, data):
    # وظيفة لتحديث السجل مع كل تغير
    file_exists = os.path.isfile(ANALYSE_LOG)
    with open(ANALYSE_LOG, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ANALYSE_HEADERS)
        if not file_exists: writer.writeheader()
        writer.writerow({
            'Timestamp': data['start_time'].strftime("%H:%M:%S"),
            'Symbol': sym,
            'Score': data['score'],
            'Initial_Price': data['start_price'],
            'Current_Result': f"{round((data['max_up']), 2)}%",
            'Max_Gain_%': round(data['max_up'], 2),
            'Max_Drawdown_%': round(data['max_down'], 2),
            'Status': data['final_status'],
            'Duration_to_Target_Min': data.get('time_to_reach', 'N/A')
        })

# ==========================================
# 3. محرك الرصد (تعديل سكور 90+)
# ==========================================

def discovery_engine():
    global available_balance
    while True:
        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers").json()
            tickers = res['data']['ticker']
            
            for t in tickers:
                sym = t['symbol']
                if not sym.endswith("-USDT") or any(x in sym for x in ["3L", "3S"]): continue
                
                vol = float(t['volValue'])
                if vol < 80000: continue
                
                score = 80 + (float(t['changeRate'])*150) + (np.log10(vol)*2)
                
                # إذا السكور > 90 أضفها للمراقبة فوراً
                if score >= 90 and sym not in extended_watchlist:
                    price = float(t['last'])
                    extended_watchlist[sym] = {
                        'start_price': price,
                        'score': round(score, 1),
                        'start_time': datetime.now(),
                        'max_up': 0.0,
                        'max_down': 0.0,
                        'final_status': "Monitoring"
                    }
                    custom_log(f"🔍 Added {sym} to extended monitoring (Score: {score})")

                    # منطق الدخول التلقائي في الصفقات المفتوحة
                    if len(open_trades) < MAX_TRADES:
                        # (نفس منطق الدخول السابق مع إرسال الإشارات)
                        pass 

        except: pass
        time.sleep(40)

# ==========================================
# 4. التشغيل
# ==========================================

if __name__ == "__main__":
    send_msg("🧪 **Omega v36.0 Validator**\nبدأ نظام المراقبة الممتدة للأهداف (+4% / -2%).", CHAT_ID)
    
    # تشغيل خيط المراقبة الممتدة
    threading.Thread(target=track_extended_performance, daemon=True).start()
    threading.Thread(target=discovery_engine, daemon=True).start()
    # (بقية الخيوط handle_commands و manage_trades)
    
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
