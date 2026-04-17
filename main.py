import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# [1] الإعدادات المالية والتقنية
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"] 
exchange = ccxt.gateio({'enableRateLimit': True})

FILE_RESULTS = 'trading_journal.csv'
MAX_VIRTUAL_TRADES = 50    # رفعنا عدد الصفقات المراقبة لأن السكور 60 أسهل في التحقق
TRADE_AMOUNT = 50          # مبلغ افتراضي للحساب
SCORE_MIN_RECORD = 60      # الحد الأدنى للتسجيل في الجدول

active_scans = {}

# تهيئة الجدول
if not os.path.exists(FILE_RESULTS):
    pd.DataFrame(columns=[
        'Time', 'Symbol', 'Entry_Price', 'Score', 
        'Max_Rise%', 'Max_Drop%', 'Final_Result'
    ]).to_csv(FILE_RESULTS, index=False, encoding='utf-8-sig')

# ==========================================
# [2] نظام المراقبة والحسم (Logic)
# ==========================================
def track_and_log_trade(sym, entry_p, score):
    global active_scans
    max_p, min_p = entry_p, entry_p
    
    while True:
        try:
            time.sleep(15) # فحص السعر كل 15 ثانية
            ticker = exchange.fetch_ticker(sym)
            curr_p = ticker['last']
            
            # تحديث أقصى ارتفاع وانخفاض وصل له السعر منذ الدخول
            max_p = max(max_p, curr_p)
            min_p = min(min_p, curr_p)
            
            pnl_pct = ((curr_p - entry_p) / entry_p) * 100
            
            # حساب أقصى نسب مئوية مسجلة حتى اللحظة
            max_rise_pct = ((max_p - entry_p) / entry_p) * 100
            max_drop_pct = ((min_p - entry_p) / entry_p) * 100

            # شرط الحسم: 5% نجاح أو -3% فشل
            if pnl_pct >= 5.0 or pnl_pct <= -3.0:
                status = "نجاح ✅" if pnl_pct >= 5.0 else "فشل ❌"
                
                # كتابة السطر النهائي في ملف CSV
                with open(FILE_RESULTS, 'a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerow([
                        datetime.now().strftime('%Y-%m-%d %H:%M'),
                        sym, entry_p, score,
                        f"{max_rise_pct:.2f}%", 
                        f"{max_drop_pct:.2f}%", 
                        status
                    ])
                
                # إشعار التليجرام عند الحسم
                exit_msg = (f"🏁 **حسم صفقة**\nالعملة: #{sym}\nالنتيجة: {status}\n"
                            f"أعلى صعود: `{max_rise_pct:.2f}%`\nأدنى هبوط: `{max_drop_pct:.2f}%`")
                send_alert(exit_msg, "EXIT")
                
                if sym in active_scans: del active_scans[sym]
                break
        except Exception as e:
            print(f"Error tracking {sym}: {e}")
            break

# ==========================================
# [3] معالجة العملات المكتشفة
# ==========================================
def process_coin(sym):
    if sym in active_scans or len(active_scans) >= MAX_VIRTUAL_TRADES: return
    
    # حساب السكور باستخدام المحرك (الذي يدمج ADX, RVOL, RS_BTC, Squeeze)
    score, details = calculate_master_score(sym)
    
    # تنفيذ طلبك: تسجيل أي عملة سكورها > 60
    if score >= SCORE_MIN_RECORD:
        active_scans[sym] = True
        p = exchange.fetch_ticker(sym)['last']
        
        # إشعار دخول (فقط إذا كان السكور عالياً جداً 85+ لتجنب الإزعاج، أو للكل حسب رغبتك)
        # هنا سأجعل الإشعار لكل ما هو فوق 60 كما طلبت في التسجيل
        send_alert(f"📝 تم تسجيل عملة (Score {score})\nالعملة: #{sym}\nالسعر: `{p}`", "ENTRY")
        
        # بدء خيط المراقبة والتدوين
        threading.Thread(target=track_and_log_trade, args=(sym, p, score), daemon=True).start()

# دالة main والأوامر تظل كما هي في الكود السابق...
