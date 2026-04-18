#!/usr/bin/env python3
"""
Trading Bot - Telegram Only Version
نسخة خفيفة للنسخة المجانية من Railway
"""

import os
import time
import json
import urllib.request
from datetime import datetime
import threading
import csv

# ============================================
# الإعدادات الأساسية
# ============================================

TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "1001003692815602"

INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 20
PROFIT_TARGET = 5
STOP_LOSS = -3
TRAILING_STOP_ACTIVATION = 2
TRAILING_STOP_DISTANCE = 1.5
MIN_DAILY_VOLATILITY = 4.0

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

# ============================================
# دوال مساعدة
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

def get_price(symbol='BTC'):
    try:
        url = 'https://api.gateio.ws/api/v4/spot/tickers'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            for item in data:
                if item['currency_pair'] == f'{symbol}_USDT':
                    return float(item['last'])
        return 0
    except:
        return 0

def get_all_prices():
    try:
        url = 'https://api.gateio.ws/api/v4/spot/tickers'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            prices = {}
            for item in data:
                if item['currency_pair'].endswith('_USDT'):
                    symbol = item['currency_pair'].replace('_USDT', '')
                    prices[symbol] = {
                        'price': float(item['last']),
                        'change': float(item.get('change_percentage', 0)),
                        'volume': float(item.get('quote_volume', 0))
                    }
            return prices
    except:
        return {}

def calculate_volatility(symbol):
    global volatility_cache
    if symbol in volatility_cache:
        cache_time, volatility = volatility_cache[symbol]
        if (datetime.now() - cache_time).seconds < 3600:
            return volatility
    try:
        url = f"https://api.gateio.ws/api/v4/spot/tickers"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            for item in data:
                if item['currency_pair'] == f"{symbol}_USDT":
                    high = float(item.get('high_24h', 0))
                    low = float(item.get('low_24h', 0))
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
    
    if data['change'] > 8:
        score += 30
        reasons.append(f"Surge +{data['change']:.1f}%")
    elif data['change'] > 5:
        score += 25
        reasons.append(f"Jump +{data['change']:.1f}%")
    elif data['change'] > 3:
        score += 15
        reasons.append(f"Rise +{data['change']:.1f}%")
    elif data['change'] > 1:
        score += 10
        reasons.append(f"Start +{data['change']:.1f}%")
    
    if data['volume'] > 5000000:
        score += 30
        reasons.append("Very high volume")
    elif data['volume'] > 1000000:
        score += 20
        reasons.append("Good volume")
    elif data['volume'] > 500000:
        score += 10
        reasons.append("Medium volume")
    
    if volatility > 10:
        score += 15
        reasons.append(f"High volatility {volatility:.0f}%")
    elif volatility > 7:
        score += 10
        reasons.append(f"Good volatility {volatility:.0f}%")
    
    if data['price'] < 0.5:
        score += 10
        reasons.append(f"Low price ${data['price']:.4f}")
    elif data['price'] < 2:
        score += 5
        reasons.append(f"Good price ${data['price']:.4f}")
    
    return min(score, 100), reasons

# ============================================
# المسح الضوئي
# ============================================

def scan_top10():
    global scanning, last_scan_result
    scanning = True
    send_msg("Scanning market... Please wait 30-60 seconds")
    
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
        send_msg(f"Scan error: {str(e)[:100]}")
        scanning = False
        return []

def show_top10_results():
    if not last_scan_result:
        send_msg("No results. Use /scan first")
        return
    
    message = "TOP COINS (Slow coins excluded)\n\n"
    message += f"Excluded: coins with <{MIN_DAILY_VOLATILITY}% daily movement\n"
    message += f"Excluded: stable coins\n\n"
    
    for i, item in enumerate(last_scan_result[:10], 1):
        change_emoji = "🟢" if item['change'] > 0 else "🔴"
        message += f"{i}. {change_emoji} {item['symbol']}\n"
        message += f"   Score: {item['score']} | Volatility: {item['volatility']:.1f}%\n"
        message += f"   Price: ${item['price']:.4f} | Change: {item['change']:+.1f}%\n"
        message += f"   {', '.join(item['reasons'][:2])}\n\n"
    
    message += "To open trade: /buy SYMBOL\nExample: /buy SOL"
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
# إدارة الصفقات
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
                send_msg(f"""Daily Report

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
                    msg = """🤖 Trading Bot - Light Version

Features:
- Excludes stable and slow coins
- Score system (0-100)
- Virtual portfolio $1000
- Trailing Stop Loss
- Full Telegram control

Commands:
/scan - Scan market
/portfolio - Show portfolio
/trades - Trade history
/buy SYMBOL - Open trade
/close SYMBOL - Close trade
/closeall - Close all trades
/status - Bot status
/export - Download CSV files
/help - Help

Example: /buy SOL"""
                    send_msg(msg, user_id)
                
                elif text == '/help':
                    msg = """Commands Guide

Scan:
/scan - Scan market for top coins

Trading:
/buy SOL - Open buy trade
/close SOL - Close trade
/closeall - Close all trades

Portfolio:
/portfolio - Portfolio details
/trades - Trade history
/status - Bot status

Files:
/export - Download CSV files

Score system:
80-100: Excellent
60-80: Very good
50-60: Good"""
                    send_msg(msg, user_id)
                
                elif text == '/scan':
                    if scanning:
                        send_msg("Scan already in progress, please wait", user_id)
                    else:
                        threading.Thread(target=scan_top10, daemon=True).start()
                
                elif text == '/status':
                    btc = get_price('BTC')
                    eth = get_price('ETH')
                    status = get_portfolio_status()
                    msg = f"""Bot Status

Time: {datetime.now().strftime('%H:%M:%S')}

Prices:
BTC: ${btc:,.0f}
ETH: ${eth:,.0f}

Portfolio:
Balance: ${status['balance']:.2f}
Total PnL: ${status['total_pnl']:+.2f}
Return: {status['total_return_pct']:+.1f}%

Trades:
Open: {status['open_trades']}/{MAX_OPEN_TRADES}
Closed: {status['closed_trades']}
Win rate: {status['win_rate']:.1f}%"""
                    send_msg(msg, user_id)
                
                elif text == '/portfolio':
                    status = get_portfolio_status()
                    msg = f"""Portfolio Details

Balance: ${status['balance']:.2f}
Total Value: ${status['total_value']:.2f}
Total PnL: ${status['total_pnl']:+.2f}
Return: {status['total_return_pct']:+.1f}%

Open Trades ({status['open_trades']}):"""
                    
                    if open_trades:
                        for symbol, trade in open_trades.items():
                            current_price = get_price(symbol)
                            if current_price > 0:
                                pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
                                msg += f"\n• {symbol}: {pnl:+.1f}% (Entry ${trade['entry_price']:.4f})"
                    else:
                        msg += "\nNo open trades"
                    
                    msg += f"\n\nClosed Trades: {status['closed_trades']}"
                    msg += f"\nWin Rate: {status['win_rate']:.1f}%"
                    send_msg(msg, user_id)
                
                elif text == '/trades':
                    if not closed_trades:
                        send_msg("No closed trades yet", user_id)
                    else:
                        msg = "Last 10 Closed Trades\n\n"
                        for trade in closed_trades[-10:]:
                            emoji = "✅" if trade.get('final_return', 0) > 0 else "❌"
                            msg += f"{emoji} {trade['symbol']}\n"
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
                            send_msg(f"Symbol {symbol} not found in scan results\nUse /scan first", user_id)
                        else:
                            success, result = open_trade(symbol, found['price'], found['score'], found['reasons'])
                            if success:
                                msg = f"""Trade opened!

{symbol}
Price: ${found['price']:.4f}
Score: {found['score']}
Amount: ${TRADE_AMOUNT}

Target: +{PROFIT_TARGET}%
Stop Loss: {STOP_LOSS}%
Trailing: after +{TRAILING_STOP_ACTIVATION}% (distance {TRAILING_STOP_DISTANCE}%)"""
                                send_msg(msg, user_id)
                                send_to_channel(f"New trade\n{symbol}\nPrice: ${found['price']:.4f}\nScore: {found['score']}")
                            else:
                                send_msg(f"Failed: {result}", user_id)
                
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
                            send_msg(f"Failed: {result}", user_id)
                
                elif text == '/closeall':
                    closed = close_all_trades()
                    if closed:
                        total_pnl = sum(t.get('profit_loss', 0) for t in closed)
                        send_msg(f"Closed all trades ({len(closed)})\nTotal PnL: ${total_pnl:+.2f}", user_id)
                    else:
                        send_msg("No open trades to close", user_id)
                
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
                        send_msg("CSV files sent:\n- top10.csv\n- trades.csv\n- portfolio.csv", user_id)
                    else:
                        send_msg("No CSV files to send", user_id)
                
                elif text == '/ping':
                    send_msg("Pong! Bot is running", user_id)
                
                else:
                    if text and not text.startswith('/'):
                        send_msg(f"Unknown command: {text}\nUse /help", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 50)
    print("STARTING TRADING BOT (TELEGRAM ONLY)")
    print("=" * 50)
    print(f"Time: {datetime.now()}")
    print(f"Balance: ${INITIAL_BALANCE}")
    print(f"Max trades: {MAX_OPEN_TRADES}")
    print("=" * 50)
    
    send_msg("Bot is running!\n\nUse /scan to start scanning\nUse /help for commands")
    
    monitor_thread = threading.Thread(target=start_monitoring, daemon=True)
    monitor_thread.start()
    
    handle_commands()
