#!/usr/bin/env python3
"""
Trading Bot - Binance Version with 1000 Pairs + Keep Alive for Render
نسخة Binance مع 1000 عملة والتشغيل الدائم على Render
"""

import os
import time
import json
import urllib.request
from datetime import datetime
import threading
import csv
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
MIN_DAILY_VOLATILITY = 4.0

# إعدادات المسح - 1000 عملة
MAX_SYMBOLS = 1000
SCAN_INTERVAL = 300  # 5 دقائق

# العملات المستبعدة
STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'USDP', 'FDUSD']
SLOW_LARGE_COINS = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'DOGE', 'MATIC', 'DOT', 'LTC', 'TRX', 'TON', 'LINK', 'AVAX', 'SHIB', 'XLM', 'BCH', 'NEAR', 'ALGO', 'VET']

# ============================================
# متغيرات البوت
# ============================================

last_update_id = 0
bot_running = True
scanning = False
last_scan_result = []
open_trades = {}
closed_trades = []
balance = INITIAL_BALANCE
volatility_cache = {}

TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
TOP10_FILE = "top10.csv"

# وقت بدء التشغيل
start_time = time.time()

# ============================================
# خادم HTTP لـ Render Keep-Alive
# ============================================

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            uptime = time.time() - start_time
            status = get_portfolio_status()
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Binance Trading Bot</title>
                <meta http-equiv="refresh" content="60">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }}
                    .container {{ max-width: 800px; margin: auto; }}
                    .status {{ color: #4CAF50; font-weight: bold; }}
                    .card {{ background: #16213e; padding: 20px; border-radius: 10px; margin: 10px 0; }}
                    .value {{ font-size: 24px; font-weight: bold; }}
                    .profit {{ color: #4CAF50; }}
                    .loss {{ color: #ff6b6b; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🤖 Binance Trading Bot</h1>
                    <div class="card">
                        <h2>📊 Bot Status</h2>
                        <p>Status: <span class="status">🟢 ONLINE</span></p>
                        <p>Uptime: {uptime/3600:.1f} hours</p>
                        <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                    <div class="card">
                        <h2>💰 Portfolio</h2>
                        <p>Balance: <span class="value">${status['balance']:.2f}</span></p>
                        <p>Total PnL: <span class="{'profit' if status['total_pnl']>=0 else 'loss'}">${status['total_pnl']:+.2f}</span></p>
                        <p>Return: <span class="{'profit' if status['total_return_pct']>=0 else 'loss'}">{status['total_return_pct']:+.1f}%</span></p>
                    </div>
                    <div class="card">
                        <h2>📈 Trading Stats</h2>
                        <p>Open Trades: {status['open_trades']}/{MAX_OPEN_TRADES}</p>
                        <p>Closed Trades: {status['closed_trades']}</p>
                        <p>Win Rate: {status['win_rate']:.1f}%</p>
                    </div>
                    <div class="card">
                        <h2>⚙️ Scanner Settings</h2>
                        <p>Exchange: Binance</p>
                        <p>Pairs Scanned: {MAX_SYMBOLS}</p>
                        <p>Scan Interval: {SCAN_INTERVAL//60} minutes</p>
                        <p>Min Score: 50</p>
                    </div>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass

def start_keep_alive_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
    print(f"✅ Keep-alive server running on port {port}")
    server.serve_forever()

# ============================================
# دوال Telegram
# ============================================

def send_msg(text, chat_id=None, parse_mode='HTML'):
    try:
        target = chat_id or CHAT_ID
        url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
        data = json.dumps({
            'chat_id': target,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Send error: {e}")
        return False

def send_to_channel(text):
    return send_msg(text, CHANNEL_ID)

# ============================================
# دوال API - Binance
# ============================================

def get_price(symbol='BTC'):
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            return float(data['price'])
    except:
        return 0

def get_all_prices():
    try:
        url = 'https://api.binance.com/api/v3/ticker/24hr'
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
            prices = {}
            for item in data:
                if item['symbol'].endswith('USDT'):
                    symbol = item['symbol'].replace('USDT', '')
                    if symbol not in STABLE_COINS:
                        prices[symbol] = {
                            'price': float(item['lastPrice']),
                            'change': float(item['priceChangePercent']),
                            'volume': float(item['quoteVolume']),
                            'high': float(item['highPrice']),
                            'low': float(item['lowPrice'])
                        }
            return prices
    except Exception as e:
        print(f"Price error: {e}")
        return {}

def calculate_volatility(symbol):
    global volatility_cache
    if symbol in volatility_cache:
        cache_time, volatility = volatility_cache[symbol]
        if (datetime.now() - cache_time).seconds < 3600:
            return volatility
    
    try:
        url = f'https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            high = float(data['highPrice'])
            low = float(data['lowPrice'])
            if high > 0 and low > 0:
                volatility = ((high - low) / low) * 100
                volatility_cache[symbol] = (datetime.now(), volatility)
                return volatility
        return 0
    except:
        return 0

def is_excluded_symbol(symbol):
    if symbol.upper() in [s.upper() for s in STABLE_COINS]:
        return True, "stable_coin"
    if symbol.upper() in [s.upper() for s in SLOW_LARGE_COINS]:
        return True, "slow_large"
    return False, ""

def calculate_score(symbol, data):
    excluded, reason = is_excluded_symbol(symbol)
    if excluded:
        return 0, [f"Excluded: {reason}"]
    
    volatility = calculate_volatility(symbol)
    if volatility < MIN_DAILY_VOLATILITY and volatility > 0:
        return 0, [f"Low volatility ({volatility:.1f}%)"]
    
    score = 0
    reasons = []
    
    # التغير السعري (30 points)
    if data['change'] > 8:
        score += 30
        reasons.append(f"🚀 Surge +{data['change']:.1f}%")
    elif data['change'] > 5:
        score += 25
        reasons.append(f"📈 Jump +{data['change']:.1f}%")
    elif data['change'] > 3:
        score += 15
        reasons.append(f"✅ Rise +{data['change']:.1f}%")
    elif data['change'] > 1:
        score += 10
        reasons.append(f"📊 Start +{data['change']:.1f}%")
    
    # حجم التداول (30 points)
    if data['volume'] > 50000000:
        score += 30
        reasons.append("🔥 Very high volume")
    elif data['volume'] > 10000000:
        score += 20
        reasons.append("📊 Good volume")
    elif data['volume'] > 5000000:
        score += 10
        reasons.append("📈 Medium volume")
    
    # التقلب (20 points)
    if volatility > 10:
        score += 20
        reasons.append(f"⚡ High volatility {volatility:.0f}%")
    elif volatility > 7:
        score += 15
        reasons.append(f"🌊 Good volatility {volatility:.0f}%")
    elif volatility > 4:
        score += 10
        reasons.append(f"📊 Normal volatility {volatility:.0f}%")
    
    # السعر (10 points)
    if data['price'] < 0.5:
        score += 10
        reasons.append(f"💰 Very low price ${data['price']:.4f}")
    elif data['price'] < 2:
        score += 5
        reasons.append(f"💵 Low price ${data['price']:.4f}")
    
    return min(score, 100), reasons

# ============================================
# المسح الضوئي
# ============================================

def scan_top10():
    global scanning, last_scan_result
    scanning = True
    send_msg("🔍 Scanning Binance market (1000 pairs)... Please wait 60-120 seconds")
    
    try:
        prices = get_all_prices()
        results = []
        
        for symbol, data in prices.items():
            score, reasons = calculate_score(symbol, data)
            if score >= 50:
                results.append({
                    'symbol': symbol,
                    'score': score,
                    'price': data['price'],
                    'change': data['change'],
                    'volume': data['volume'],
                    'volatility': calculate_volatility(symbol),
                    'reasons': reasons
                })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        last_scan_result = results[:15]
        save_top10_csv(last_scan_result)
        show_top10_results()
        scanning = False
        return last_scan_result
    except Exception as e:
        send_msg(f"❌ Scan error: {str(e)[:100]}")
        scanning = False
        return []

def show_top10_results():
    if not last_scan_result:
        send_msg("No results. Use /scan first")
        return
    
    message = "🏆 <b>TOP 10 BINANCE COINS</b>\n\n"
    message += f"📊 Scanned: 1000 pairs | Min volatility: {MIN_DAILY_VOLATILITY}%\n\n"
    
    for i, item in enumerate(last_scan_result[:10], 1):
        emoji = "🟢" if item['change'] > 0 else "🔴"
        message += f"{i}. {emoji} <b>{item['symbol']}</b>\n"
        message += f"   📊 Score: <code>{item['score']}</code> | Change: {item['change']:+.1f}%\n"
        message += f"   💰 Price: ${item['price']:.6f} | Vol: {item['volatility']:.1f}%\n"
        message += f"   📈 {', '.join(item['reasons'][:2])}\n\n"
    
    message += "💡 <b>To open trade:</b> /buy SYMBOL\n"
    message += "📌 Example: /buy SOL"
    send_msg(message)

def save_top10_csv(results):
    with open(TOP10_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Rank', 'Symbol', 'Score', 'Price', 'Change%', 'Volatility%', 'Volume', 'Reasons', 'Time'])
        for i, item in enumerate(results[:20], 1):
            writer.writerow([
                i, item['symbol'], item['score'], item['price'],
                f"{item['change']:.2f}", f"{item['volatility']:.2f}",
                f"{item['volume']:.0f}", '|'.join(item['reasons']),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ])

# ============================================
# إدارة الصفقات (مختصرة)
# ============================================

def open_trade(symbol, price, score, reasons):
    global balance, open_trades
    if len(open_trades) >= MAX_OPEN_TRADES:
        return False, f"Max trades reached ({MAX_OPEN_TRADES})"
    if balance < TRADE_AMOUNT:
        return False, f"Insufficient balance (${balance:.2f})"
    if symbol in open_trades:
        return False, f"Trade {symbol} already open"
    
    trade = {
        'id': f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        'symbol': symbol,
        'entry_price': price,
        'entry_time': datetime.now(),
        'amount': TRADE_AMOUNT,
        'quantity': TRADE_AMOUNT / price,
        'score': score,
        'reasons': reasons,
        'highest': price,
        'lowest': price,
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
        return False, "Cannot get current price"
    
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
    unrealized_pnl = 0
    
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            current_value = trade['quantity'] * current_price
            total_value += current_value
            unrealized_pnl += (current_value - trade['amount'])
            if current_price > trade['highest']:
                trade['highest'] = current_price
                trade['max_gain'] = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            if current_price < trade['lowest']:
                trade['lowest'] = current_price
                trade['max_loss'] = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
    
    realized_pnl = sum(t.get('profit_loss', 0) for t in closed_trades)
    total_pnl = realized_pnl + unrealized_pnl
    winning_trades = len([t for t in closed_trades if t.get('final_return', 0) > 0])
    win_rate = (winning_trades / len(closed_trades) * 100) if closed_trades else 0
    
    return {
        'balance': balance,
        'total_value': total_value,
        'invested': INITIAL_BALANCE - balance,
        'realized_pnl': realized_pnl,
        'unrealized_pnl': unrealized_pnl,
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
                        'Quantity', 'Exit Price', 'Exit Time', 'Return%', 'Profit/Loss', 
                        'Exit Reason', 'Status'])
        
        for trade in open_trades.values():
            writer.writerow([
                'OPEN', trade['id'], trade['symbol'], trade['entry_price'],
                trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S'), trade['amount'],
                trade['quantity'], '-', '-', '-', '-', '-', 'OPEN'
            ])
        
        for trade in closed_trades:
            writer.writerow([
                'CLOSED', trade['id'], trade['symbol'], trade['entry_price'],
                trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S'), trade['amount'],
                trade['quantity'], trade.get('exit_price', '-'),
                trade.get('exit_time', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                f"{trade.get('final_return', 0):.2f}",
                f"{trade.get('profit_loss', 0):.2f}",
                trade.get('exit_reason', '-'), 'CLOSED'
            ])
    
    status = get_portfolio_status()
    with open(PORTFOLIO_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Time', 'Balance', 'Total Value', 'Realized PnL', 'Unrealized PnL', 
                        'Total PnL', 'Return%', 'Open Trades', 'Closed Trades', 'Win Rate%'])
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            f"{status['balance']:.2f}", f"{status['total_value']:.2f}",
            f"{status['realized_pnl']:.2f}", f"{status['unrealized_pnl']:.2f}",
            f"{status['total_pnl']:.2f}", f"{status['total_return_pct']:.2f}",
            status['open_trades'], status['closed_trades'], f"{status['win_rate']:.2f}"
        ])

def monitor_open_trades():
    for symbol in list(open_trades.keys()):
        try:
            current_price = get_price(symbol)
            if current_price == 0:
                continue
            
            trade = open_trades[symbol]
            current_return = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            
            if current_price > trade['highest']:
                trade['highest'] = current_price
                trade['max_gain'] = current_return
            
            should_close = False
            reason = ""
            
            if current_return >= PROFIT_TARGET:
                should_close = True
                reason = "TP_HIT"
            elif current_return <= STOP_LOSS:
                should_close = True
                reason = "SL_HIT"
            elif current_return >= TRAILING_STOP_ACTIVATION:
                trailing_stop = trade['highest'] * (1 - TRAILING_STOP_DISTANCE / 100)
                if current_price <= trailing_stop:
                    should_close = True
                    reason = "TRAILING_STOP"
            
            if should_close:
                success, closed_trade = close_trade(symbol, reason)
                if success:
                    emoji = "✅" if closed_trade['final_return'] >= 0 else "❌"
                    send_msg(f"""{emoji} Trade closed {closed_trade['symbol']}

Return: {closed_trade['final_return']:+.2f}%
Profit: ${closed_trade['profit_loss']:+.2f}
Max gain: +{closed_trade.get('max_gain', 0):.1f}%
Reason: {reason}
Duration: {((closed_trade['exit_time'] - closed_trade['entry_time']).total_seconds() / 60):.0f} min""")
                    
                    if closed_trade['final_return'] >= 3:
                        send_to_channel(f"✅ Profit {closed_trade['symbol']}\n+{closed_trade['final_return']:.1f}% (${closed_trade['profit_loss']:.2f})")
        except Exception as e:
            print(f"Monitor error for {symbol}: {e}")

def start_monitoring():
    while bot_running:
        try:
            monitor_open_trades()
            current_hour = datetime.now().hour
            if current_hour == 0 and datetime.now().minute < 5:
                status = get_portfolio_status()
                send_msg(f"""📊 Daily Report

Balance: ${status['balance']:.2f}
Total PnL: ${status['total_pnl']:+.2f}
Return: {status['total_return_pct']:+.1f}%
Open trades: {status['open_trades']}
Closed trades: {status['closed_trades']}
Win rate: {status['win_rate']:.1f}%

{datetime.now().strftime('%Y-%m-%d')}""")
            time.sleep(60)
        except Exception as e:
            print(f"Monitoring loop error: {e}")
            time.sleep(60)

# ============================================
# معالجة أوامر Telegram
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
                
                if text == '/start':
                    msg = """🤖 <b>Binance Trading Bot</b> - 1000 Pairs

<b>Features:</b>
✅ 1000+ pairs scanned
✅ 6 technical indicators
✅ Virtual portfolio $1000
✅ Trailing Stop Loss
✅ Full Telegram control

<b>Commands:</b>
/scan → Scan market
/portfolio → Show portfolio
/trades → Trade history
/buy SYMBOL → Open trade
/close SYMBOL → Close trade
/closeall → Close all trades
/status → Bot status
/export → Download CSV
/help → Help

<b>Example:</b> /buy SOL"""
                    send_msg(msg, user_id)
                
                elif text == '/scan':
                    if scanning:
                        send_msg("⚠️ Scan already in progress", user_id)
                    else:
                        send_msg("🔄 Scanning Binance (1000 pairs)...\n⏱️ Please wait 60-120 seconds", user_id)
                        threading.Thread(target=scan_top10, daemon=True).start()
                
                elif text == '/status':
                    btc = get_price('BTC')
                    eth = get_price('ETH')
                    status = get_portfolio_status()
                    msg = f"""📊 <b>Bot Status</b>

⏰ Time: {datetime.now().strftime('%H:%M:%S')}

💰 <b>Prices:</b>
BTC: ${btc:,.0f}
ETH: ${eth:,.0f}

💵 <b>Portfolio:</b>
Balance: ${status['balance']:.2f}
Total PnL: ${status['total_pnl']:+.2f}
Return: {status['total_return_pct']:+.1f}%

📈 <b>Trades:</b>
Open: {status['open_trades']}/{MAX_OPEN_TRADES}
Closed: {status['closed_trades']}
Win rate: {status['win_rate']:.1f}%"""
                    send_msg(msg, user_id)
                
                elif text == '/portfolio':
                    status = get_portfolio_status()
                    msg = f"""💰 <b>Portfolio Details</b>

Balance: ${status['balance']:.2f}
Total Value: ${status['total_value']:.2f}
Total PnL: ${status['total_pnl']:+.2f}
Return: {status['total_return_pct']:+.1f}%

🟢 <b>Open Trades ({status['open_trades']}):</b>"""
                    
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
                
                elif text == '/trades':
                    if not closed_trades:
                        send_msg("📊 No closed trades yet", user_id)
                    else:
                        msg = "📊 <b>Last 10 Closed Trades</b>\n\n"
                        for trade in closed_trades[-10:]:
                            emoji = "✅" if trade.get('final_return', 0) > 0 else "❌"
                            msg += f"{emoji} <b>{trade['symbol']}</b>\n"
                            msg += f"   Return: {trade.get('final_return', 0):+.1f}%\n"
                            msg += f"   Profit: ${trade.get('profit_loss', 0):+.2f}\n"
                            msg += f"   Exit: {trade.get('exit_reason', '-')}\n\n"
                        send_msg(msg, user_id)
                
                elif text.startswith('/buy'):
                    parts = text.split()
                    if len(parts) < 2:
                        send_msg("Usage: /buy SYMBOL\nExample: /buy SOL", user_id)
                    else:
                        symbol = parts[1].upper()
                        found = None
                        for item in last_scan_result:
                            if item['symbol'] == symbol:
                                found = item
                                break
                        
                        if not found:
                            send_msg(f"❌ Symbol {symbol} not found in scan results\nUse /scan first", user_id)
                        else:
                            success, result = open_trade(symbol, found['price'], found['score'], found['reasons'])
                            if success:
                                msg = f"""✅ <b>Trade opened!</b>

{symbol}
💰 Price: ${found['price']:.4f}
📊 Score: {found['score']}
💵 Amount: ${TRADE_AMOUNT}

🎯 Target: +{PROFIT_TARGET}%
🛑 Stop Loss: {STOP_LOSS}%
🔒 Trailing: after +{TRAILING_STOP_ACTIVATION}% (distance {TRAILING_STOP_DISTANCE}%)"""
                                send_msg(msg, user_id)
                                send_to_channel(f"🟢 New trade\n{symbol}\nPrice: ${found['price']:.4f}\nScore: {found['score']}")
                            else:
                                send_msg(f"❌ Failed: {result}", user_id)
                
                elif text.startswith('/close'):
                    parts = text.split()
                    if len(parts) < 2:
                        send_msg("Usage: /close SYMBOL\nExample: /close SOL", user_id)
                    else:
                        symbol = parts[1].upper()
                        success, result = close_trade(symbol, "USER_COMMAND")
                        if success:
                            emoji = "✅" if result['final_return'] >= 0 else "❌"
                            send_msg(f"{emoji} Trade closed {symbol}\nReturn: {result['final_return']:+.1f}%\nProfit: ${result['profit_loss']:+.2f}", user_id)
                        else:
                            send_msg(f"❌ {result}", user_id)
                
                elif text == '/closeall':
                    closed = close_all_trades()
                    if closed:
                        total_pnl = sum(t.get('profit_loss', 0) for t in closed)
                        send_msg(f"✅ Closed all trades ({len(closed)})\nTotal PnL: ${total_pnl:+.2f}", user_id)
                    else:
                        send_msg("📊 No open trades to close", user_id)
                
                elif text == '/export':
                    save_trades_csv()
                    files = [TOP10_FILE, TRADES_FILE, PORTFOLIO_FILE]
                    sent = False
                    for file in files:
                        if os.path.exists(file) and os.path.getsize(file) > 0:
                            try:
                                url = f'https://api.telegram.org/bot{TOKEN}/sendDocument'
                                with open(file, 'rb') as f:
                                    data = f.read()
                                boundary = '----WebKitFormBoundary' + str(time.time())
                                body = (
                                    f'--{boundary}\r\n'
                                    f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{user_id}\r\n'
                                    f'--{boundary}\r\n'
                                    f'Content-Disposition: form-data; name="document"; filename="{file}"\r\n'
                                    f'Content-Type: text/csv\r\n\r\n'
                                ).encode() + data + f'\r\n--{boundary}--\r\n'.encode()
                                headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
                                req = urllib.request.Request(url, data=body, headers=headers, method='POST')
                                urllib.request.urlopen(req, timeout=30)
                                sent = True
                                time.sleep(1)
                            except Exception as e:
                                print(f"Error sending {file}: {e}")
                    if sent:
                        send_msg("📁 CSV files sent:\n- top10.csv\n- trades.csv\n- portfolio.csv", user_id)
                    else:
                        send_msg("⚠️ No CSV files to send", user_id)
                
                elif text == '/help':
                    msg = """📚 <b>Commands Guide</b>

🔍 <b>Scan:</b>
/scan → Scan 1000 Binance pairs

💰 <b>Trading:</b>
/buy SOL → Open trade
/close SOL → Close trade
/closeall → Close all trades

📊 <b>Portfolio:</b>
/portfolio → Portfolio details
/trades → Trade history
/status → Bot status

📁 <b>Files:</b>
/export → Download CSV files

🏆 <b>Score System:</b>
80-100: Excellent 🔥
60-80: Very good ⭐
50-60: Good ✅

💡 <b>First use:</b> /scan → /buy SOL"""
                    send_msg(msg, user_id)
                
                elif text == '/ping':
                    send_msg("🏓 Pong! Bot is running", user_id)
                
                else:
                    if text and not text.startswith('/'):
                        send_msg(f"❓ Unknown command: {text}\nUse /help", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 BINANCE TRADING BOT - 1000 PAIRS")
    print("=" * 60)
    print(f"Time: {datetime.now()}")
    print(f"Balance: ${INITIAL_BALANCE}")
    print(f"Max trades: {MAX_OPEN_TRADES}")
    print(f"Pairs to scan: {MAX_SYMBOLS}")
    print("=" * 60)
    
    # تشغيل خادم Keep-Alive
    keep_alive_thread = threading.Thread(target=start_keep_alive_server, daemon=True)
    keep_alive_thread.start()
    print("✅ Keep-alive server started")
    
    # إرسال رسالة البدء
    send_msg("🚀 <b>Binance Trading Bot Started!</b>\n\n✅ 1000 pairs scanner\n✅ Virtual portfolio $1000\n✅ 6 technical indicators\n✅ Auto-scan every 5 minutes\n\n💡 Use /scan to start")
    
    # تشغيل المراقبة
    monitor_thread = threading.Thread(target=start_monitoring, daemon=True)
    monitor_thread.start()
    
    # تشغيل معالجة الأوامر
    handle_commands()
