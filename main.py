#!/usr/bin/env python3
"""
Adem Trading Bot - Advanced Version with Price Tracking
بوت متقدم مع تتبع الأسعار وتحليل الانفجارات
"""

import os
import time
import json
import threading
import csv
import urllib.request
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================
# الإعدادات الأساسية
# ============================================

TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "1001003692815602"

# إعدادات التداول
INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 20
PROFIT_TARGET = 5
STOP_LOSS = -3
TRAILING_STOP_ACTIVATION = 2
TRAILING_STOP_DISTANCE = 1.5

# إعدادات المسح
MAX_SYMBOLS = 500
SCAN_INTERVAL = 300
EXPLOSION_THRESHOLD = 65
HIGH_EXPLOSION_THRESHOLD = 80

# العملات المستبعدة
STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD']

# ============================================
# متغيرات البوت
# ============================================

last_update_id = 0
bot_running = True
scanning = False
open_trades = {}
closed_trades = []
balance = INITIAL_BALANCE
start_time = time.time()

# تخزين العملات المكتشفة (الانفجارات)
detected_coins = {}  # {symbol: {detection_time, detection_price, score, expected_rise, time_to_explode, highest_price, lowest_price, current_rise}}

# ملفات CSV
TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
DETECTED_COINS_FILE = "detected_coins.csv"

# ============================================
# دوال التداول الأساسية
# ============================================

def get_price(symbol):
    """الحصول على السعر من Binance"""
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            return float(data['price'])
    except:
        return 0

def get_market_data():
    """جلب بيانات السوق من Binance"""
    try:
        url = 'https://api.binance.com/api/v3/ticker/24hr'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            top_coins = []
            for item in data:
                if item['symbol'].endswith('USDT') and float(item.get('quoteVolume', 0)) > 5000000:
                    symbol = item['symbol'].replace('USDT', '')
                    if symbol not in STABLE_COINS:
                        top_coins.append({
                            'symbol': symbol,
                            'price': float(item['lastPrice']),
                            'change': float(item['priceChangePercent']),
                            'volume': float(item['quoteVolume'])
                        })
            top_coins.sort(key=lambda x: abs(x['change']), reverse=True)
            return top_coins[:10]
    except:
        return []

def update_detected_coins_price(symbol, current_price):
    """تحديث أعلى وأدنى سعر للعملة المكتشفة"""
    if symbol in detected_coins:
        coin = detected_coins[symbol]
        if current_price > coin['highest_price']:
            coin['highest_price'] = current_price
            coin['highest_rise'] = ((current_price - coin['detection_price']) / coin['detection_price']) * 100
        if current_price < coin['lowest_price']:
            coin['lowest_price'] = current_price
            coin['lowest_drop'] = ((current_price - coin['detection_price']) / coin['detection_price']) * 100
        coin['current_price'] = current_price
        coin['current_rise'] = ((current_price - coin['detection_price']) / coin['detection_price']) * 100
        coin['last_update'] = datetime.now()

def save_detected_coins_csv():
    """حفظ العملات المكتشفة في CSV"""
    with open(DETECTED_COINS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Detection Time', 'Symbol', 'Detection Price', 'Current Price', 
                        'Current Rise%', 'Highest Price', 'Highest Rise%', 'Lowest Price', 
                        'Lowest Drop%', 'Score', 'Expected Rise%', 'Time To Explode(min)', 
                        'Status', 'Last Update'])
        
        for symbol, coin in detected_coins.items():
            writer.writerow([
                coin['detection_time'].strftime('%Y-%m-%d %H:%M:%S'),
                symbol,
                f"{coin['detection_price']:.6f}",
                f"{coin['current_price']:.6f}",
                f"{coin['current_rise']:.2f}",
                f"{coin['highest_price']:.6f}",
                f"{coin['highest_rise']:.2f}",
                f"{coin['lowest_price']:.6f}",
                f"{coin['lowest_drop']:.2f}",
                coin['score'],
                coin['expected_rise'],
                coin['time_to_explode'],
                coin['status'],
                coin['last_update'].strftime('%Y-%m-%d %H:%M:%S')
            ])

def open_trade(symbol, price, score, reasons, expected_rise=None):
    global balance, open_trades
    if len(open_trades) >= MAX_OPEN_TRADES:
        return False, f"Max trades ({MAX_OPEN_TRADES})"
    if balance < TRADE_AMOUNT:
        return False, f"Insufficient balance (${balance:.2f})"
    if symbol in open_trades:
        return False, f"Trade {symbol} already open"
    
    # تحديث حالة العملة المكتشفة
    if symbol in detected_coins:
        detected_coins[symbol]['status'] = 'TRADED'
    
    trade = {
        'trade_id': f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        'symbol': symbol,
        'entry_price': price,
        'entry_time': datetime.now(),
        'amount': TRADE_AMOUNT,
        'quantity': TRADE_AMOUNT / price,
        'score': score,
        'reasons': reasons,
        'expected_rise': expected_rise,
        'highest_price': price,
        'lowest_price': price,
        'highest_rise': 0,
        'lowest_drop': 0,
        'max_gain': 0,
        'max_loss': 0,
        'status': 'OPEN'
    }
    open_trades[symbol] = trade
    balance -= TRADE_AMOUNT
    save_trades_csv()
    return True, trade

def update_trade_prices(symbol, current_price):
    """تحديث أعلى وأدنى سعر للصفقة"""
    if symbol in open_trades:
        trade = open_trades[symbol]
        current_return = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
        
        if current_price > trade['highest_price']:
            trade['highest_price'] = current_price
            trade['highest_rise'] = current_return
        
        if current_price < trade['lowest_price']:
            trade['lowest_price'] = current_price
            trade['lowest_drop'] = current_return
        
        trade['current_price'] = current_price
        trade['current_return'] = current_return

def close_trade(symbol, reason="MANUAL"):
    global balance, open_trades, closed_trades
    if symbol not in open_trades:
        return False, "Trade not found"
    
    trade = open_trades[symbol]
    current_price = get_price(symbol)
    if current_price == 0:
        return False, "Cannot get price"
    
    final_return = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
    profit_loss = (current_price - trade['entry_price']) * trade['quantity']
    
    trade['exit_price'] = current_price
    trade['exit_time'] = datetime.now()
    trade['final_return'] = final_return
    trade['profit_loss'] = profit_loss
    trade['exit_reason'] = reason
    trade['status'] = 'CLOSED'
    
    closed_trades.append(trade)
    del open_trades[symbol]
    balance += trade['amount'] + profit_loss
    save_trades_csv()
    return True, trade

def close_all_trades():
    closed = []
    for symbol in list(open_trades.keys()):
        success, trade = close_trade(symbol, "CLOSE_ALL")
        if success:
            closed.append(trade)
    return closed

def get_portfolio_status():
    total_value = balance
    for trade in open_trades.values():
        current_price = get_price(trade['symbol'])
        if current_price > 0:
            total_value += trade['quantity'] * current_price
            update_trade_prices(trade['symbol'], current_price)
    
    realized_pnl = sum(t.get('profit_loss', 0) for t in closed_trades)
    total_pnl = realized_pnl
    winning_trades = len([t for t in closed_trades if t.get('final_return', 0) > 0])
    win_rate = (winning_trades / len(closed_trades) * 100) if closed_trades else 0
    
    return {
        'balance': balance,
        'total_value': total_value,
        'total_pnl': total_pnl,
        'total_return_pct': (total_pnl / INITIAL_BALANCE) * 100,
        'open_trades': len(open_trades),
        'closed_trades': len(closed_trades),
        'win_rate': win_rate
    }

def save_trades_csv():
    with open(TRADES_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Type', 'ID', 'Symbol', 'Entry Price', 'Entry Time', 'Amount', 
                        'Quantity', 'Highest Price', 'Highest Rise%', 'Lowest Price', 
                        'Lowest Drop%', 'Exit Price', 'Exit Time', 'Return%', 'Profit/Loss', 
                        'Exit Reason', 'Expected Rise%', 'Status'])
        
        for trade in open_trades.values():
            writer.writerow([
                'OPEN', trade['trade_id'], trade['symbol'], trade['entry_price'],
                trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S'), trade['amount'],
                trade['quantity'], trade['highest_price'], f"{trade['highest_rise']:.2f}",
                trade['lowest_price'], f"{trade['lowest_drop']:.2f}",
                '-', '-', '-', '-', '-', trade.get('expected_rise', '-'), 'OPEN'
            ])
        
        for trade in closed_trades:
            writer.writerow([
                'CLOSED', trade['trade_id'], trade['symbol'], trade['entry_price'],
                trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S'), trade['amount'],
                trade['quantity'], trade.get('highest_price', '-'), f"{trade.get('highest_rise', 0):.2f}",
                trade.get('lowest_price', '-'), f"{trade.get('lowest_drop', 0):.2f}",
                trade.get('exit_price', '-'), trade.get('exit_time', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                f"{trade.get('final_return', 0):.2f}", f"{trade.get('profit_loss', 0):.2f}",
                trade.get('exit_reason', '-'), trade.get('expected_rise', '-'), 'CLOSED'
            ])

# ============================================
# المسح الضوئي - نظام اكتشاف الانفجارات
# ============================================

def scan_market():
    global scanning
    
    scanning = True
    send_msg("🔍 <b>جاري مسح الانفجارات...</b>\n⏱️ يرجى الانتظار 20-30 ثانية")
    
    try:
        url = 'https://api.binance.com/api/v3/ticker/24hr'
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
            explosions = []
            
            for item in data:
                if item['symbol'].endswith('USDT'):
                    symbol = item['symbol'].replace('USDT', '')
                    if symbol in STABLE_COINS:
                        continue
                    
                    change = float(item['priceChangePercent'])
                    volume = float(item['quoteVolume'])
                    price = float(item['lastPrice'])
                    
                    # حساب سكور الانفجار المحسن
                    score = 0
                    signals = []
                    expected_rise = 5
                    time_to_explode = 60
                    
                    # عامل التغير السعري
                    if change > 8:
                        score += 35
                        signals.append("🚀 Strong surge")
                        expected_rise += 10
                        time_to_explode -= 20
                    elif change > 5:
                        score += 25
                        signals.append("📈 Good surge")
                        expected_rise += 7
                        time_to_explode -= 15
                    elif change > 3:
                        score += 15
                        signals.append("✅ Positive move")
                        expected_rise += 4
                        time_to_explode -= 10
                    elif change > 1:
                        score += 8
                        signals.append("📊 Starting move")
                        expected_rise += 2
                    
                    # عامل حجم التداول
                    if volume > 50000000:
                        score += 30
                        signals.append("🔥 Very high volume")
                        expected_rise += 8
                        time_to_explode -= 15
                    elif volume > 10000000:
                        score += 20
                        signals.append("📊 High volume")
                        expected_rise += 4
                        time_to_explode -= 10
                    elif volume > 5000000:
                        score += 10
                        signals.append("📈 Good volume")
                        expected_rise += 2
                    
                    # عامل السعر المنخفض
                    if price < 0.5:
                        score += 15
                        signals.append("💰 Very low price")
                        expected_rise += 5
                    elif price < 2:
                        score += 10
                        signals.append("💵 Low price")
                        expected_rise += 3
                    elif price < 5:
                        score += 5
                        signals.append("💲 Good price")
                        expected_rise += 1
                    
                    # تحديد الوقت النهائي
                    time_to_explode = max(15, min(time_to_explode, 120))
                    expected_rise = min(expected_rise, 30)
                    
                    if score >= EXPLOSION_THRESHOLD:
                        # تسجيل العملة في detected_coins إذا كانت جديدة
                        current_time = datetime.now()
                        if symbol not in detected_coins:
                            detected_coins[symbol] = {
                                'detection_time': current_time,
                                'detection_price': price,
                                'current_price': price,
                                'highest_price': price,
                                'lowest_price': price,
                                'highest_rise': 0,
                                'lowest_drop': 0,
                                'current_rise': 0,
                                'score': score,
                                'expected_rise': expected_rise,
                                'time_to_explode': time_to_explode,
                                'status': 'ACTIVE',
                                'last_update': current_time
                            }
                        else:
                            # تحديث العملة الموجودة
                            detected_coins[symbol]['score'] = score
                            detected_coins[symbol]['expected_rise'] = expected_rise
                            detected_coins[symbol]['time_to_explode'] = time_to_explode
                            detected_coins[symbol]['last_update'] = current_time
                        
                        explosions.append({
                            'symbol': symbol,
                            'price': price,
                            'change': change,
                            'score': score,
                            'expected_rise': expected_rise,
                            'time_to_explode': time_to_explode,
                            'signals': signals
                        })
            
            # تحديث أسعار العملات المكتشفة
            for symbol in detected_coins:
                current_price = get_price(symbol)
                if current_price > 0:
                    update_detected_coins_price(symbol, current_price)
            
            # حفظ العملات المكتشفة
            save_detected_coins_csv()
            
            # ترتيب الانفجارات
            explosions.sort(key=lambda x: x['score'], reverse=True)
            
            # إرسال إشعارات للانفجارات الجديدة فقط
            new_explosions = [e for e in explosions[:3] if e['score'] >= EXPLOSION_THRESHOLD]
            for exp in new_explosions:
                send_msg(f"""
💥 <b>New Explosion Detected!</b>

┌ 📊 <b>{exp['symbol']}</b>
├ 💥 Score: <code>{exp['score']}/100</code>
├ 📈 Expected Rise: <code>+{exp['expected_rise']}%</code>
├ ⏰ Time to explode: <code>{exp['time_to_explode']} min</code>
├ 💰 Current Price: <code>${exp['price']:.6f}</code>
├ 📈 24h Change: <code>{exp['change']:+.1f}%</code>
│
├ 📊 <b>Signals:</b>
""")
                for signal in exp['signals'][:3]:
                    send_msg(f"├  {signal}")
                send_msg(f"""
│
└ 🚨 <b>Great opportunity!</b>

💡 /buy {exp['symbol']}
""")
            
            send_msg(f"✅ Scan complete! Found {len(explosions)} potential explosions")
            scanning = False
            
    except Exception as e:
        print(f"Scan error: {e}")
        scanning = False

# ============================================
# دوال Telegram
# ============================================

def send_msg(text, chat_id=None, parse_mode='HTML', reply_markup=None):
    try:
        target = chat_id or CHAT_ID
        url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
        data = {'chat_id': target, 'text': text, 'parse_mode': parse_mode}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        post_data = json.dumps(data).encode()
        req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Send error: {e}")
        return False

def edit_message_text(text, chat_id, message_id, reply_markup=None):
    try:
        url = f'https://api.telegram.org/bot{TOKEN}/editMessageText'
        data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        post_data = json.dumps(data).encode()
        req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Edit error: {e}")
        return False

def answer_callback_query(callback_id, text=None):
    try:
        url = f'https://api.telegram.org/bot{TOKEN}/answerCallbackQuery'
        data = {'callback_query_id': callback_id}
        if text:
            data['text'] = text
        post_data = json.dumps(data).encode()
        req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Callback error: {e}")
        return False

def export_csv_files(chat_id):
    files = [DETECTED_COINS_FILE, TRADES_FILE, PORTFOLIO_FILE]
    sent = False
    for file in files:
        if os.path.exists(file) and os.path.getsize(file) > 0:
            try:
                url = f'https://api.telegram.org/bot{TOKEN}/sendDocument'
                with open(file, 'rb') as f:
                    data = f.read()
                boundary = '----WebKitFormBoundary' + str(time.time())
                body = (f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
                       f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{file}"\r\n'
                       f'Content-Type: text/csv\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
                req = urllib.request.Request(url, data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
                urllib.request.urlopen(req, timeout=30)
                sent = True
                time.sleep(1)
            except Exception as e:
                print(f"Error sending {file}: {e}")
    if sent:
        send_msg("📁 CSV files sent!\n\n- detected_coins.csv (Tracked coins)\n- trades.csv (Trade history)\n- portfolio.csv (Portfolio)", chat_id)

# ============================================
# صفحة الويب المتقدمة
# ============================================

def get_html_dashboard():
    """إنشاء صفحة HTML متقدمة مع جداول الانفجارات والصفقات"""
    status = get_portfolio_status()
    market_data = get_market_data()
    uptime_hours = (time.time() - start_time) / 3600
    
    # تحديث أسعار العملات المكتشفة
    for symbol in list(detected_coins.keys()):
        current_price = get_price(symbol)
        if current_price > 0:
            update_detected_coins_price(symbol, current_price)
    
    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="30">
        <title>🤖 Adem Trading Bot - Explosion Detector</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                padding: 20px;
                color: #eee;
            }}
            .container {{ max-width: 1400px; margin: 0 auto; }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background: rgba(255,255,255,0.1);
                border-radius: 15px;
                backdrop-filter: blur(10px);
            }}
            .status-online {{ color: #4CAF50; font-weight: bold; }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}
            .card {{
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 15px;
                padding: 20px;
                text-align: center;
            }}
            .card-value {{ font-size: 28px; font-weight: bold; }}
            .profit {{ color: #4CAF50; }}
            .loss {{ color: #ff6b6b; }}
            .section {{
                background: rgba(255,255,255,0.05);
                border-radius: 15px;
                padding: 20px;
                margin-bottom: 30px;
                overflow-x: auto;
            }}
            .section h2 {{
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #4CAF50;
                display: inline-block;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 13px;
            }}
            th, td {{
                padding: 10px 8px;
                text-align: center;
                border-bottom: 1px solid rgba(255,255,255,0.1);
            }}
            th {{
                background: rgba(0,0,0,0.4);
                font-weight: bold;
                position: sticky;
                top: 0;
            }}
            tr:hover {{ background: rgba(255,255,255,0.05); }}
            .badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 11px;
                font-weight: bold;
            }}
            .badge-high {{ background: #ff6b6b; color: white; }}
            .badge-medium {{ background: #ffd93d; color: #333; }}
            .badge-low {{ background: #6bcb77; color: white; }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                padding: 20px;
                font-size: 12px;
                opacity: 0.6;
            }}
            @media (max-width: 768px) {{
                .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
                th, td {{ padding: 6px 4px; font-size: 10px; }}
                .section {{ padding: 10px; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Adem Trading Bot - Explosion Detector</h1>
                <p>Status: <span class="status-online">✅ ONLINE</span> | Uptime: {uptime_hours:.1f} hours</p>
                <p>📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="stats-grid">
                <div class="card"><div class="card-title">💰 BALANCE</div><div class="card-value">${status['balance']:.2f}</div></div>
                <div class="card"><div class="card-title">📈 TOTAL PnL</div><div class="card-value {'profit' if status['total_pnl']>=0 else 'loss'}">${status['total_pnl']:+.2f}</div></div>
                <div class="card"><div class="card-title">📊 RETURN</div><div class="card-value {'profit' if status['total_return_pct']>=0 else 'loss'}">{status['total_return_pct']:+.1f}%</div></div>
                <div class="card"><div class="card-title">🟢 OPEN</div><div class="card-value">{status['open_trades']}/{MAX_OPEN_TRADES}</div></div>
                <div class="card"><div class="card-title">🔒 CLOSED</div><div class="card-value">{status['closed_trades']}</div></div>
                <div class="card"><div class="card-title">📊 WIN RATE</div><div class="card-value">{status['win_rate']:.1f}%</div></div>
                <div class="card"><div class="card-title">💥 DETECTED</div><div class="card-value">{len(detected_coins)}</div></div>
            </div>
            
            <!-- جدول العملات المكتشفة (الانفجارات) -->
            <div class="section">
                <h2>💥 DETECTED COINS (Explosion Candidates)</h2>
                <div style="font-size: 12px; margin-bottom: 10px;">🟢 = Price Up | 🔴 = Price Down | 📊 Tracking since detection</div>
                <table>
                    <thead>
                        <tr><th>Detection Time</th><th>Symbol</th><th>Detection Price</th><th>Current Price</th><th>Current Rise%</th><th>Highest Price</th><th>Highest Rise%</th><th>Lowest Price</th><th>Lowest Drop%</th><th>Score</th><th>Expected Rise%</th><th>Time To Explode</th><th>Status</th></tr>
                    </thead>
                    <tbody>
    """
    
    for symbol, coin in sorted(detected_coins.items(), key=lambda x: x[1]['detection_time'], reverse=True)[:20]:
        rise_class = "profit" if coin['current_rise'] >= 0 else "loss"
        badge_class = "badge-high" if coin['score'] >= 80 else ("badge-medium" if coin['score'] >= 65 else "badge-low")
        status_emoji = "🟢" if coin['status'] == 'ACTIVE' else "✅"
        
        html += f"""
                        <tr>
                            <td>{coin['detection_time'].strftime('%H:%M:%S')}</td>
                            <td><b>{symbol}</b></td>
                            <td>${coin['detection_price']:.6f}</td>
                            <td>${coin['current_price']:.6f}</td>
                            <td class="{rise_class}">{coin['current_rise']:+.2f}%</td>
                            <td class="profit">${coin['highest_price']:.6f}</td>
                            <td class="profit">+{coin['highest_rise']:.2f}%</td>
                            <td class="loss">${coin['lowest_price']:.6f}</td>
                            <td class="loss">{coin['lowest_drop']:.2f}%</td>
                            <td><span class="badge {badge_class}">{coin['score']}</span></td>
                            <td class="profit">+{coin['expected_rise']}%</td>
                            <td>{coin['time_to_explode']} min</td>
                            <td>{status_emoji} {coin['status']}</td>
                        </tr>
        """
    
    html += """
                    </tbody>
                </table>
            </div>
            
            <!-- جدول الصفقات المفتوحة -->
            <div class="section">
                <h2>🟢 OPEN TRADES</h2>
                <table>
                    <thead>
                        <tr><th>Symbol</th><th>Entry Time</th><th>Entry Price</th><th>Current Price</th><th>Current Return%</th><th>Highest Price</th><th>Highest Rise%</th><th>Lowest Price</th><th>Lowest Drop%</th><th>Amount</th><th>Expected Rise%</th></tr>
                    </thead>
                    <tbody>
    """
    
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            update_trade_prices(symbol, current_price)
            return_class = "profit" if trade.get('current_return', 0) >= 0 else "loss"
            html += f"""
                        <tr>
                            <td><b>{symbol}</b></td>
                            <td>{trade['entry_time'].strftime('%H:%M:%S')}</td>
                            <td>${trade['entry_price']:.6f}</td>
                            <td>${current_price:.6f}</td>
                            <td class="{return_class}">{trade.get('current_return', 0):+.2f}%</td>
                            <td class="profit">${trade['highest_price']:.6f}</td>
                            <td class="profit">+{trade['highest_rise']:.2f}%</td>
                            <td class="loss">${trade['lowest_price']:.6f}</td>
                            <td class="loss">{trade['lowest_drop']:.2f}%</td>
                            <td>${trade['amount']:.2f}</td>
                            <td class="profit">+{trade.get('expected_rise', '-')}%</td>
                        </tr>
            """
    
    if not open_trades:
        html += '<tr><td colspan="11" style="text-align:center">No open trades</td></tr>'
    
    html += """
                    </tbody>
                </table>
            </div>
            
            <!-- جدول الصفقات المغلقة -->
            <div class="section">
                <h2>🔒 CLOSED TRADES (Last 15)</h2>
                <table>
                    <thead>
                        <tr><th>Symbol</th><th>Entry Time</th><th>Exit Time</th><th>Entry Price</th><th>Exit Price</th><th>Final Return%</th><th>Profit/Loss</th><th>Highest Rise%</th><th>Lowest Drop%</th><th>Exit Reason</th><th>Expected Rise%</th></tr>
                    </thead>
                    <tbody>
    """
    
    for trade in closed_trades[-15:]:
        return_class = "profit" if trade.get('final_return', 0) >= 0 else "loss"
        emoji = "✅" if trade.get('final_return', 0) >= 0 else "❌"
        html += f"""
                        <tr>
                            <td><b>{trade['symbol']}</b></td>
                            <td>{trade['entry_time'].strftime('%H:%M:%S')}</td>
                            <td>{trade.get('exit_time', datetime.now()).strftime('%H:%M:%S')}</td>
                            <td>${trade['entry_price']:.6f}</td>
                            <td>${trade.get('exit_price', 0):.6f}</td>
                            <td class="{return_class}">{trade.get('final_return', 0):+.2f}%</td>
                            <td class="{return_class}">${trade.get('profit_loss', 0):+.2f}</td>
                            <td class="profit">+{trade.get('highest_rise', 0):.2f}%</td>
                            <td class="loss">{trade.get('lowest_drop', 0):.2f}%</td>
                            <td>{emoji} {trade.get('exit_reason', '-')}</td>
                            <td class="profit">+{trade.get('expected_rise', '-')}%</td>
                        </tr>
        """
    
    if not closed_trades:
        html += '<tr><td colspan="11" style="text-align:center">No closed trades</td></tr>'
    
    html += f"""
