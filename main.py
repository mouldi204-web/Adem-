import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
BASE_URL = "https://api.kucoin.com"

monitoring_list = {} 
ANALYSE_LOG = 'market_discovery_log.csv'
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Score', 'Entry_Price', 'Max_Up_%', 'Max_Down_%', 'Result', 'Duration_Min']

app = Flask('')
@app.route('/')
def home(): return "Omega v37.1 Smart Notifications Active."

# ==========================================
# 2. نظام الإشعارات الذكية (Smart Notifications)
# ==========================================

def send_smart_entry_msg(sym, score, entry_p):
    """إشعار ذكي عند رصد وتسجيل العملة"""
    msg = (f"🚀 **إشعار دخول ذكي**\n"
           f"━━━━━━━━━━━━━━\n"
           f"💎 **العملة:** #{sym.replace('-USDT', '')}\n"
           f"📈 **السكور:** `{score}`\n"
           f"🎯 **نقطة الدخول:** `{entry_p}`\n"
           f"🏁 **الأهداف:** `+4%` | `-2%`\n"
           f"━━━━━━━━━━━━━━\n"
           f"⏰ الوقت: {datetime.now().strftime('%H:%M:%S')}")
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def send_smart_exit_msg(sym, result, data):
    """إشعار ذكي عند حسم النتيجة (نجاح/فشل)"""
    duration = round((datetime.now() - data['start_time']).total_seconds() / 60, 1)
    color = "🟢" if "نجاح" in result else "🔴"
    
    msg = (f"{color} **إشعار خروج وحسم**\n"
           f"━━━━━━━━━━━━━━\n"
           f"💎 **العملة:** #{sym.replace('-USDT', '')}\n"
           f"📊 **النتيجة النهائية:** `{result}`\n"
           f"📈 **أقصى صعود وصل له:** `+{round(data['max_up'], 2)}%`\n"
           f"📉 **أقصى هبوط وصل له:** `{round(data['max_down'], 2)}%`\n"
           f"⏱️ **المدة المستغرقة:** `{duration}` دقيقة\n"
           f"━━━━━━━━━━━━━━")
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

# ==========================================
# 3. محرك الحكم والتسجيل
# ==========================================

def performance_judger():
    while True:
        for sym, data in list(monitoring_list.items()):
            try:
                res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={sym}").json()
                curr_p = float(res['data']['price'])
                
                change = (curr_p - data['entry_price']) / data['entry_price'] * 100
                data['max_up'] = max(data['max_up'],
