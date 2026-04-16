import time, requests, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
from flask import Flask
from waitress import serve

# ==========================================
# 1. الإعدادات المحدثة (رصيد 1000$ و 10 صفقات)
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "-1003692815602"
BASE_URL = "https://api.kucoin.com"

initial_balance = 1000.0
available_balance = initial_balance
MAX_TRADES = 10
open_trades = []
daily_loss_limit = 0.10 # إغلاق طوارئ عند خسارة 10% من المحفظة

# ملفات السجلات
TRADE_LOG = 'trading_master_log.csv'
ANALYSE_LOG = 'market_discovery_log.csv'
JOURNAL_LOG = 'bot_journal.txt'

TRADE_HEADERS = ['Symbol', 'Result', 'Quality', 'Entry', 'Exit', 'MAE_Pct', 'MFE_Pct', 'Size_Used', 'Duration', 'RSI', 'BTC', 'Session']
ANALYSE_HEADERS = ['Timestamp', 'Symbol', 'Score', 'RSI', 'Vol_24h', 'BTC_Status', 'Rank']

app = Flask('')
@app.route('/')
def home(): return f"Omega v34.0 Fortress Ready. Active: {len(open_trades)}/10"

# ==========================================
# 2. أنظمة الأمان المتقدمة (Safety Systems)
# ==========================================

def global_kill_switch():
    """إغلاق الطوارئ: إذا انخفضت القيمة الإجمالية 10% عن البداية"""
    global available_balance, open_trades
    current_total = available_balance + sum([t['size'] for t in open_trades])
    if current_total <= (initial_balance * (1 - daily_loss_limit)):
        custom_log("⚠️🚨 KILL SWITCH ACTIVATED: Global loss reached 10%. Closing all trades!")
        send_msg("🚨 **إغلاق الطوارئ!** تم الوصول لحد الخسارة اليومي (10%). تم إغلاق جميع الصفقات حمايةً للمحفظة.")
        # هنا يتم وضع كود إغلاق الصفقات في المنصة برمجياً
        open_trades = [] 
        return True
    return False

def check_liquidity_spread(symbol):
    """فحص الفارق السعري (Spread) لضمان عدم الانزلاق"""
    try:
        res = requests.get(f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={symbol}").json()
        bid = float(res['data']['bid'])
        ask = float(res['data']['ask'])
        spread = (ask - bid) / bid * 100
        return spread <= 0.5 # مقبول إذا كان أقل من 0.5%
    except: return False

# ==========================================
# 3. إدارة السيولة والجودة (Risk Management)
# ==========================================

def evaluate_trade_quality(score, rsi, btc_status):
    # صفقة ذهبية (⭐⭐⭐): 10% من الرصيد (100$)
    if score >= 96 and 40 <= rsi <= 60 and btc_status == "Bullish":
        return 0.10, "High (⭐⭐⭐)"
    # صفقة حذرة (⭐): 5% من الرصيد (50$)
    if rsi > 70 or btc_status == "Bearish":
        return 0.05, "Low (⭐)"
    # صفقة متوسطة (⭐⭐): 7.5% من الرصيد (75$)
    return 0.075, "Medium (⭐⭐)"

# ==========================================
# 4. المحركات الأساسية (Discovery & Management)
# ==========================================

def discovery_engine():
    global available_balance
    while True:
        if global_kill_switch(): time.sleep(3600); continue # توقف لساعة إذا فعل الكيل سويتش

        try:
            res = requests.get(f"{BASE_URL}/api/v1/market/allTickers").json()
            tickers = res['data']['ticker']
            btc_status = get_market_context()
            
            all_scored = sorted([
                {'symbol': t['symbol'], 'price': float(t['last']), 
                 'score': 80 + (float(t['changeRate'])*100*1.5) + (np.log10(float(t['volValue']))*2),
                 'vol': float(t['volValue'])}
                for t in tickers if t['symbol'].endswith("-USDT") and float(t['volValue']) > 80000
            ], key=lambda x: x['score'], reverse=True)[:10]

            for i, opp in enumerate(all_scored):
                rsi_val = calculate_rsi(opp['symbol'])
                
                # توثيق للتحليل
                save_to_csv(ANALYSE_LOG, ANALYSE_HEADERS, {
                    'Timestamp': datetime.now().strftime("%H:%M:%S"), 'Symbol': opp['symbol'],
                    'Score': opp['score'], 'RSI': rsi_val, 'Vol_24h': round(opp['vol'], 0),
                    'BTC_Status': btc_status, 'Rank': i + 1
                })

                # شروط الدخول الصارمة (القناص)
                if i < 3 and len(open_trades) < MAX_TRADES:
                    if opp['symbol'] not in [t['symbol'] for t in open_trades]:
                        # فحص السيولة اللحظي (Spread)
                        if not check_liquidity_spread(opp['symbol']): 
                            custom_log(f"⏩ Skipped {opp['symbol']} due to high spread."); continue
                        
                        risk_pct, q_label = evaluate_trade_quality(opp['score'], rsi_val, btc_status)
                        trade_size = available_balance * risk_pct
                        
                        if available_balance >= trade_size:
                            available_balance -= trade_size
                            open_trades.append({
                                'symbol': opp['symbol'], 'entry': opp['price'], 'size': trade_size,
                                'sl': opp['price'] * 0.95, 'score': opp['score'], 'quality': q_label,
                                'rsi_entry': rsi_val, 'btc_entry': btc_status,
                                'session': "Asian" if 0 <= datetime.now().hour < 8 else "European" if 8 <= datetime.now().hour < 16 else "American",
                                'start_time': datetime.now(), 'max_p': opp['price'], 'min_p': opp['price']
                            })
                            custom_log(f"🎯 Sniper Entered {opp['symbol']} | Quality: {q_label} | Size: ${round(trade_size, 2)}")

        except Exception as e: custom_log(f"⚠️ Discovery Error: {e}")
        time.sleep(30)

# (تكملة الدوال المساعدة manage_trades, calculate_rsi, handle_commands كما في v33.0)
