#!/usr/bin/env python3
"""
Adem Trading Bot - Complete Version
بوت تداول متكامل + Telegram + صفحة ويب متقدمة
"""

import os
import time
import json
import threading
import csv
import urllib.request
from datetime import datetime
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
EXPLOSION_THRESHOLD = 70
HIGH_EXPLOSION_THRESHOLD = 85

# العملات المستبعدة
STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD']

# ============================================
# متغيرات البوت
# ============================================

last_update_id = 0
bot_running = True
scanning = False
last_scan_result = []
explosions_found = []
open_trades = {}
closed_trades = []
balance = INITIAL_BALANCE
start_time = time.time()

# ملفات CSV
TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
TOP10_FILE = "top10.csv"
EXPLOSIONS_FILE = "explosions.csv"

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

def open_trade(symbol, price, score, reasons):
    global balance, open_trades
    if len(open_trades) >= MAX_OPEN_TRADES:
        return False, f"Max trades ({MAX_OPEN_TRADES})"
    if balance < TRADE_AMOUNT:
        return False, f"Insufficient balance (${balance:.2f})"
    if symbol in open_trades:
        return False, f"Trade {symbol} already open"
    
    trade = {
        'trade_id': f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        'symbol': symbol,
        'entry_price': price,
        'entry_time': datetime.now().isoformat(),
        'amount': TRADE_AMOUNT,
        'quantity': TRADE_AMOUNT / price,
        'score': score,
        'reasons': reasons,
        'highest_price': price,
        'lowest_price': price,
        'max_gain': 0,
        'max_loss': 0,
        'status': 'OPEN'
    }
    open_trades[symbol] = trade
    balance -= TRADE_AMOUNT
    save_trades_csv()
    return True, trade

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
    trade['exit_time'] = datetime.now().isoformat()
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
                        'Quantity', 'Exit Price', 'Exit Time', 'Return%', 'Profit/Loss', 'Exit Reason'])
        for trade in open_trades.values():
            writer.writerow(['OPEN', trade['trade_id'], trade['symbol'], trade['entry_price'],
                           trade['entry_time'], trade['amount'], trade['quantity'], '-', '-', '-', '-', '-'])
        for trade in closed_trades:
            writer.writerow(['CLOSED', trade['trade_id'], trade['symbol'], trade['entry_price'],
                           trade['entry_time'], trade['amount'], trade['quantity'], trade.get('exit_price', '-'),
                           trade.get('exit_time', '-'), f"{trade.get('final_return', 0):.2f}",
                           f"{trade.get('profit_loss', 0):.2f}", trade.get('exit_reason', '-')])

# ============================================
# المسح الضوئي
# ============================================

def scan_market():
    global scanning, explosions_found, last_scan_result
    scanning = True
    
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
                    
                    score = 0
                    if change > 5:
                        score += 40
                    elif change > 3:
                        score += 25
                    elif change > 1:
                        score += 15
                    
                    if volume > 50000000:
                        score += 30
                    elif volume > 10000000:
                        score += 20
                    
                    if score >= EXPLOSION_THRESHOLD:
                        explosions.append({
                            'symbol': symbol,
                            'price': price,
                            'change': change,
                            'explosion': {
                                'score': score,
                                'expected_rise': round(5 + (score / 100) * 15, 1),
                                'time_to_explode': 30,
                                'explosion_type': "🔥 Volume + Price" if score > 80 else "📊 Volume",
                                'signals': ["High volume", "Price surge"]
                            }
                        })
            
            explosions.sort(key=lambda x: x['explosion']['score'], reverse=True)
            explosions_found = explosions[:10]
            last_scan_result = explosions_found
            
            # حفظ النتائج
            with open(EXPLOSIONS_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Time', 'Symbol', 'Score', 'Expected Rise%', 'Price', 'Change%'])
                for exp in explosions_found:
                    writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exp['symbol'],
                                   exp['explosion']['score'], exp['explosion']['expected_rise'],
                                   exp['price'], f"{exp['change']:.2f}"])
            
            # إرسال إشعارات Telegram
            for exp in explosions_found[:3]:
                send_msg(f"""
💥 <b>Explosion Alert!</b>

┌ 📊 <b>{exp['symbol']}</b>
├ 💥 Score: {exp['explosion']['score']}/100
├ 📈 Expected Rise: +{exp['explosion']['expected_rise']}%
├ ⏰ Time: {exp['explosion']['time_to_explode']} min
│
└ 🚨 <b>Great opportunity!</b>

💡 /buy {exp['symbol']}
""")
            
            send_msg(f"✅ Scan complete! Found {len(explosions_found)} explosions")
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

def send_to_channel(text):
    return send_msg(text, CHANNEL_ID)

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
    files = [EXPLOSIONS_FILE, TRADES_FILE, PORTFOLIO_FILE]
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
        send_msg("📁 CSV files sent!", chat_id)

# ============================================
# صفحة الويب المتقدمة
# ============================================

def get_html_dashboard():
    """إنشاء صفحة HTML متقدمة"""
    status = get_portfolio_status()
    market_data = get_market_data()
    uptime_hours = (time.time() - start_time) / 3600
    
    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="30">
        <title>🤖 Adem Trading Bot</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                padding: 20px;
                color: #eee;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background: rgba(255,255,255,0.1);
                border-radius: 15px;
                backdrop-filter: blur(10px);
            }}
            .header h1 {{ font-size: 2em; margin-bottom: 10px; }}
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
                transition: transform 0.3s;
            }}
            .card:hover {{ transform: translateY(-5px); }}
            .card-title {{ font-size: 14px; opacity: 0.7; margin-bottom: 10px; }}
            .card-value {{ font-size: 28px; font-weight: bold; }}
            .profit {{ color: #4CAF50; }}
            .loss {{ color: #ff6b6b; }}
            .section {{
                background: rgba(255,255,255,0.05);
                border-radius: 15px;
                padding: 20px;
                margin-bottom: 30px;
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
            }}
            th, td {{
                padding: 12px;
                text-align: center;
                border-bottom: 1px solid rgba(255,255,255,0.1);
            }}
            th {{
                background: rgba(0,0,0,0.3);
                font-weight: bold;
            }}
            tr:hover {{ background: rgba(255,255,255,0.05); }}
            .badge {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
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
                th, td {{ padding: 8px; font-size: 12px; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Adem Trading Bot</h1>
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
                <div class="card"><div class="card-title">💥 EXPLOSIONS</div><div class="card-value">{len(explosions_found)}</div></div>
            </div>
            
            <div class="section">
                <h2>📊 TOP 10 MARKET MOVERS</h2>
                <table>
                    <thead><tr><th>#</th><th>Symbol</th><th>Price</th><th>24h Change</th><th>Volume</th></tr></thead>
                    <tbody>
    """
    
    for i, coin in enumerate(market_data[:10], 1):
        change_class = "profit" if coin['change'] >= 0 else "loss"
        change_symbol = "+" if coin['change'] >= 0 else ""
        html += f"<tr><td>{i}</td><td><b>{coin['symbol']}</b></td><td>${coin['price']:.4f}</td><td class='{change_class}'>{change_symbol}{coin['change']:.1f}%</td><td>${coin['volume']/1000000:.1f}M</td></tr>"
    
    html += """
                    </tbody>
                </table>
            </div>
    """
    
    if explosions_found:
        html += """
            <div class="section">
                <h2>💥 EXPLOSION ALERTS</h2>
                <table>
                    <thead><tr><th>Symbol</th><th>Score</th><th>Expected Rise</th><th>Time</th><th>Type</th></tr></thead>
                    <tbody>
        """
        for exp in explosions_found[:5]:
            badge_class = "badge-high" if exp['explosion']['score'] >= 85 else "badge-medium"
            html += f"<tr><td><b>{exp['symbol']}</b></td><td><span class='badge {badge_class}'>{exp['explosion']['score']}</span></td><td class='profit'>+{exp['explosion']['expected_rise']}%</td><td>{exp['explosion']['time_to_explode']} min</td><td>{exp['explosion']['explosion_type']}</td></tr>"
        html += "</tbody><table></div>"
    
    if open_trades:
        html += """
            <div class="section">
                <h2>🟢 OPEN TRADES</h2>
                etable
                    <thead><tr><th>Symbol</th><th>Entry Price</th><th>Current Price</th><th>PnL</th><th>Amount</th></tr></thead>
                    <tbody>
        """
        for symbol, trade in open_trades.items():
            current_price = get_price(symbol)
            if current_price > 0:
                pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
                pnl_class = "profit" if pnl >= 0 else "loss"
                html += f"<tr><td><b>{symbol}</b></td><td>${trade['entry_price']:.4f}</td><td>${current_price:.4f}</td><td class='{pnl_class}'>{pnl:+.1f}%</td><td>${trade['amount']:.2f}</td></tr>"
        html += "</tbody></table></div>"
    
    if closed_trades:
        html += """
            <div class="section">
                <h2>🔒 LAST 10 CLOSED TRADES</h2>
                <table>
                    <thead><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>Return</th><th>Profit</th><th>Reason</th></tr></thead>
                    <tbody>
        """
        for trade in closed_trades[-10:]:
            return_class = "profit" if trade.get('final_return', 0) >= 0 else "loss"
            emoji = "✅" if trade.get('final_return', 0) >= 0 else "❌"
            html += f"<tr><td><b>{trade['symbol']}</b></td><td>${trade['entry_price']:.4f}</td><td>${trade.get('exit_price', 0):.4f}</td><td class='{return_class}'>{trade.get('final_return', 0):+.1f}%</td><td class='{return_class}'>${trade.get('profit_loss', 0):+.2f}</td><td>{emoji} {trade.get('exit_reason', '-')}</td></tr>"
        html += "</tbody></table></div>"
    
    html += f"""
            <div class="footer">
                🔄 Auto-refresh every 30 seconds | 💡 Telegram Commands: /buy SOL, /close SOL, /explode, /portfolio, /closeall<br>
                📊 Exchange: Binance | 🤖 Adem Trading Bot | 🚀 24/7 Operation | 📁 /export to download CSV
            </div>
        </div>
    </body>
    </html>
    """
    return html

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        html = get_html_dashboard()
        self.wfile.write(html.encode())
    def log_message(self, format, *args): pass

def start_web_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), WebHandler)
    print(f"✅ Web server running on port {port}")
    server.serve_forever()

# ============================================
# أوامر Telegram
# ============================================

def get_updates(offset=None):
    try:
        url = f'https://api.telegram.org/bot{TOKEN}/getUpdates'
        if offset:
            url += f'?offset={offset}'
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except:
        return {'result': []}

def show_main_menu(chat_id):
    status = get_portfolio_status()
    msg = f"""
🤖 <b>Adem Trading Bot</b>

💰 <b>Portfolio:</b>
├ Balance: ${status['balance']:.2f}
├ Total PnL: ${status['total_pnl']:+.2f}
├ Return: {status['total_return_pct']:+.1f}%

📊 <b>Trades:</b>
├ Open: {status['open_trades']}/{MAX_OPEN_TRADES}
├ Closed: {status['closed_trades']}
├ Win Rate: {status['win_rate']:.1f}%

💥 <b>Explosions:</b> {len(explosions_found)}

📋 <b>Commands:</b>
/explode - Scan for explosions
/buy SOL - Open trade
/close SOL - Close trade
/closeall - Close all trades
/portfolio - Show portfolio
/status - Bot status
/export - Download CSV
/help - Help

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
    send_msg(msg, chat_id)

def handle_commands():
    global last_update_id, bot_running
    
    while bot_running:
        try:
            updates = get_updates(last_update_id + 1)
            
            for update in updates.get('result', []):
                last_update_id = update['update_id']
                message = update.get('message', {})
                text = message.get('text', '').lower()
                user_id = message.get('chat', {}).get('id')
                
                if text == '/start' or text == '/menu':
                    show_main_menu(user_id)
                
                elif text == '/explode':
                    if scanning:
                        send_msg("⚠️ Scan already in progress", user_id)
                    else:
                        send_msg("🔍 Scanning for explosions...", user_id)
                        threading.Thread(target=scan_market, daemon=True).start()
                
                elif text == '/portfolio':
                    status = get_portfolio_status()
                    msg = f"""
💰 <b>Portfolio Details</b>

Balance: ${status['balance']:.2f}
Total Value: ${status['total_value']:.2f}
Total PnL: ${status['total_pnl']:+.2f}
Return: {status['total_return_pct']:+.1f}%

🟢 <b>Open Trades ({status['open_trades']}):</b>
"""
                    if open_trades:
                        for symbol, trade in open_trades.items():
                            current_price = get_price(symbol)
                            if current_price > 0:
                                pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
                                msg += f"\n• {symbol}: {pnl:+.1f}% (Entry ${trade['entry_price']:.4f})"
                    else:
                        msg += "\nNo open trades"
                    
                    msg += f"\n\n✅ Closed Trades: {status['closed_trades']}"
                    msg += f"\n📊 Win Rate: {status['win_rate']:.1f}%"
                    send_msg(msg, user_id)
                
                elif text == '/status':
                    status = get_portfolio_status()
                    uptime = (time.time() - start_time) / 3600
                    msg = f"""
📊 <b>Bot Status</b>

✅ Status: Active
⏰ Uptime: {uptime:.1f} hours
📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

💰 Balance: ${status['balance']:.2f}
📈 Total PnL: ${status['total_pnl']:+.2f}
📊 Return: {status['total_return_pct']:+.1f}%

🟢 Open Trades: {status['open_trades']}
✅ Closed Trades: {status['closed_trades']}
📈 Win Rate: {status['win_rate']:.1f}%
💥 Explosions: {len(explosions_found)}
"""
                    send_msg(msg, user_id)
                
                elif text.startswith('/buy'):
                    parts = text.split()
                    if len(parts) < 2:
                        send_msg("⚠️ Usage: /buy SYMBOL\nExample: /buy SOL", user_id)
                    else:
                        symbol = parts[1].upper()
                        found = None
                        for exp in explosions_found:
                            if exp['symbol'] == symbol:
                                found = exp
                                break
                        if found:
                            success, trade = open_trade(symbol, found['price'], found['explosion']['score'], found['explosion']['signals'])
                            if success:
                                send_msg(f"✅ Opened {symbol}\n💰 Price: ${found['price']:.4f}\n💥 Explosion Score: {found['explosion']['score']}/100", user_id)
                            else:
                                send_msg(f"❌ {trade}", user_id)
                        else:
                            send_msg(f"❌ {symbol} not found\nUse /explode first", user_id)
                
                elif text.startswith('/close'):
                    parts = text.split()
                    if len(parts) < 2:
                        send_msg("⚠️ Usage: /close SYMBOL\nExample: /close SOL", user_id)
                    else:
                        symbol = parts[1].upper()
                        success, result = close_trade(symbol, "COMMAND")
                        if success:
                            emoji = "✅" if result['final_return'] >= 0 else "❌"
                            send_msg(f"{emoji} Closed {symbol}\nReturn: {result['final_return']:+.1f}%\nProfit: ${result['profit_loss']:+.2f}", user_id)
                        else:
                            send_msg(f"❌ {result}", user_id)
                
                elif text == '/closeall':
                    closed = close_all_trades()
                    send_msg(f"✅ Closed {len(closed)} trades", user_id)
                
                elif text == '/export':
                    export_csv_files(user_id)
                
                elif text == '/help':
                    msg = """
📚 <b>Commands Guide</b>

🔍 <b>Scan:</b>
/explode - Scan for explosions

💰 <b>Trading:</b>
/buy SOL - Open trade
/close SOL - Close trade
/closeall - Close all trades

📊 <b>Portfolio:</b>
/portfolio - Portfolio details
/status - Bot status

📁 <b>Files:</b>
/export - Download CSV files

💡 <b>First use:</b> /explode → /buy SOL
"""
                    send_msg(msg, user_id)
                
                elif text == '/ping':
                    send_msg("🏓 Pong! Bot is running", user_id)
                
                else:
                    if text and not text.startswith('/'):
                        send_msg(f"❓ Unknown: {text}\nUse /help", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 ADEM TRADING BOT - COMPLETE VERSION")
    print("=" * 60)
    print(f"Time: {datetime.now()}")
    print(f"Balance: ${INITIAL_BALANCE}")
    print(f"Max trades: {MAX_OPEN_TRADES}")
    print(f"Web port: 8080")
    print("=" * 60)
    
    # تشغيل خادم الويب
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    print("✅ Web server started")
    
    # إرسال رسالة بدء التشغيل
    send_msg("🚀 <b>Adem Trading Bot Started!</b>\n\n✅ Web dashboard active\n✅ 24/7 operation\n✅ Explosion detection\n\n💡 Use /menu to start")
    
    # تشغيل معالجة الأوامر
    handle_commands()
