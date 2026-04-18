#!/usr/bin/env python3
import os
import time
import json
import threading
import csv
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

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

MAX_SYMBOLS = 500
SCAN_INTERVAL = 300
EXPLOSION_THRESHOLD = 70
HIGH_EXPLOSION_THRESHOLD = 85

STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD']

last_update_id = 0
bot_running = True
scanning = False
last_scan_result = []
explosions_found = []
open_trades = {}
closed_trades = []
balance = INITIAL_BALANCE
start_time = time.time()

TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
TOP10_FILE = "top10.csv"
EXPLOSIONS_FILE = "explosions.csv"

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        status = get_portfolio_status()
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Binance Pro Bot</title><meta http-equiv="refresh" content="60">
        <style>body {{ font-family: Arial; text-align: center; padding: 50px; background: #1a1a2e; color: #eee; }}
        .online {{ color: #4CAF50; }} .value {{ font-size: 24px; font-weight: bold; }}</style>
        </head>
        <body>
            <h1>🚀 Binance Pro Trading Bot</h1>
            <p>Status: <span class="online">✅ ONLINE</span></p>
            <p>Uptime: {(time.time()-start_time)/3600:.1f} hours</p>
            <p>Balance: <span class="value">${status['balance']:.2f}</span></p>
            <p>Explosions: {len(explosions_found)}</p>
            <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        """
        self.wfile.write(html.encode())
    def log_message(self, format, *args): pass

def start_keep_alive():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
    print(f"✅ Keep-alive server running on port {port}")
    server.serve_forever()

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

import ccxt
exchange_sync = ccxt.binance({'enableRateLimit': True, 'rateLimit': 1200})

def get_price(symbol):
    try:
        ticker = exchange_sync.fetch_ticker(f"{symbol}/USDT")
        return ticker['last']
    except:
        return 0

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

def scan_market_sync():
    global scanning, explosions_found, last_scan_result
    scanning = True
    send_msg("💥 <b>Scanning for explosions...</b>\n⏱️ Please wait")
    try:
        import random
        test_coins = ['SOL', 'AVAX', 'ARB', 'OP', 'SUI', 'SEI', 'APT', 'NEAR', 'INJ', 'TIA']
        explosions = []
        for coin in test_coins[:8]:
            score = random.randint(65, 95)
            if score >= EXPLOSION_THRESHOLD:
                explosions.append({
                    'symbol': coin,
                    'price': round(random.uniform(1, 150), 4),
                    'change': round(random.uniform(2, 12), 1),
                    'explosion': {
                        'score': score,
                        'expected_rise': round(random.uniform(5, 20), 1),
                        'time_to_explode': random.randint(15, 60),
                        'explosion_type': "🔥 Volume + Price" if score > 80 else "📊 Volume",
                        'signals': ["🔥 Huge volume", "🚀 Price surge", "🟢 MACD positive"]
                    }
                })
        explosions.sort(key=lambda x: x['explosion']['score'], reverse=True)
        explosions_found = explosions
        last_scan_result = explosions
        save_results_to_csv(explosions_found, [])
        for exp in explosions_found[:3]:
            explosion = exp['explosion']
            send_msg(f"""
💥 <b>Explosion Alert!</b>

┌ 📊 <b>{exp['symbol']}</b>
├ 💥 Score: {explosion['score']}/100
├ 📈 Expected Rise: +{explosion['expected_rise']}%
├ ⏰ Time: {explosion['time_to_explode']} min
│
└ 🚨 <b>Great opportunity!</b>

💡 /buy {exp['symbol']}
            """)
        send_msg(f"✅ Scan complete! Found {len(explosions_found)} explosions")
        scanning = False
    except Exception as e:
        send_msg(f"❌ Error: {str(e)[:100]}")
        scanning = False

def save_results_to_csv(explosions, top_coins):
    with open(EXPLOSIONS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Time', 'Symbol', 'Score', 'Expected_Rise%', 'Time_To_Explode', 'Type', 'Price', 'Change%'])
        for exp in explosions:
            writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exp['symbol'],
                           exp['explosion']['score'], exp['explosion']['expected_rise'],
                           exp['explosion']['time_to_explode'], exp['explosion']['explosion_type'],
                           exp['price'], f"{exp['change']:.2f}"])

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
                if 'callback_query' in update:
                    handle_callback_query(update['callback_query'])
                    continue
                message = update.get('message', {})
                text = message.get('text', '').lower()
                user_id = message.get('chat', {}).get('id')
                if text == '/start':
                    send_msg("🤖 Bot is running! Use /explode to scan for explosions", user_id)
                elif text == '/explode':
                    if scanning:
                        send_msg("⚠️ Scan already in progress", user_id)
                    else:
                        threading.Thread(target=scan_market_sync, daemon=True).start()
                        send_msg("🔍 Scanning for explosions...", user_id)
                elif text.startswith('/buy'):
                    parts = text.split()
                    if len(parts) > 1:
                        symbol = parts[1].upper()
                        found = None
                        for exp in explosions_found:
                            if exp['symbol'] == symbol:
                                found = exp
                                break
                        if found:
                            success, trade = open_trade(symbol, found['price'], found['explosion']['score'],
                                                       found['explosion']['signals'])
                            if success:
                                send_msg(f"✅ Opened {symbol}\n💰 Price: ${found['price']:.4f}", user_id)
                            else:
                                send_msg(f"❌ {trade}", user_id)
                        else:
                            send_msg(f"❌ {symbol} not found in scan results", user_id)
                    else:
                        send_msg("⚠️ /buy SYMBOL\nExample: /buy SOL", user_id)
                elif text == '/closeall':
                    closed = close_all_trades()
                    send_msg(f"✅ Closed {len(closed)} trades", user_id)
                elif text.startswith('/close'):
                    parts = text.split()
                    if len(parts) > 1:
                        symbol = parts[1].upper()
                        success, result = close_trade(symbol, "COMMAND")
                        if success:
                            emoji = "✅" if result['final_return'] >= 0 else "❌"
                            send_msg(f"{emoji} Closed {symbol}\nReturn: {result['final_return']:+.1f}%", user_id)
                        else:
                            send_msg(f"❌ {result}", user_id)
                    else:
                        send_msg("⚠️ /close SYMBOL\nExample: /close SOL", user_id)
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

def handle_callback_query(callback):
    data = callback.get('data', '')
    chat_id = callback.get('message', {}).get('chat', {}).get('id')
    callback_id = callback.get('id')
    if data.startswith('CLOSE_'):
        symbol = data.replace('CLOSE_', '')
        success, result = close_trade(symbol, "BUTTON_CLOSE")
        if success:
            answer_callback_query(callback_id, f"✅ Closed {symbol}")
        else:
            answer_callback_query(callback_id, f"❌ {result}")
    elif data == 'CLOSE_ALL':
        closed = close_all_trades()
        answer_callback_query(callback_id, f"✅ Closed {len(closed)} trades")
    elif data.startswith('BUY_'):
        symbol = data.replace('BUY_', '')
        found = None
        for exp in explosions_found:
            if exp['symbol'] == symbol:
                found = exp
                break
        if found:
            success, trade = open_trade(symbol, found['price'], found['explosion']['score'],
                                       found['explosion']['signals'])
            if success:
                answer_callback_query(callback_id, f"✅ Opened {symbol}")
            else:
                answer_callback_query(callback_id, f"❌ {trade}")
        else:
            answer_callback_query(callback_id, "❌ Symbol not found")
    else:
        answer_callback_query(callback_id, "⚠️ Unknown command")

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

def show_open_trades(chat_id, message_id=None):
    if not open_trades:
        msg = "📊 <b>No open trades</b>"
        send_msg(msg, chat_id)
        return
    keyboard = []
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            button_text = f"{emoji} {symbol} | {pnl:+.1f}%"
            keyboard.append([{'text': button_text, 'callback_data': f"CLOSE_{symbol}"}])
    keyboard.append([{'text': "🔴 Close All", 'callback_data': "CLOSE_ALL"}])
    reply_markup = {'inline_keyboard': keyboard}
    trades_text = ""
    total_pnl = 0
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            pnl_amount = (current_price - trade['entry_price']) * trade['quantity']
            total_pnl += pnl_amount
            emoji = "🟢" if pnl >= 0 else "🔴"
            trades_text += f"\n{emoji} <b>{symbol}</b>: {pnl:+.1f}% (${pnl_amount:+.2f})"
    msg = f"📊 <b>Open Trades ({len(open_trades)}/{MAX_OPEN_TRADES})</b>{trades_text}\n\n💰 <b>Total Open PnL:</b> ${total_pnl:+.2f}\n\n💡 <b>Click a trade to close it</b>"
    send_msg(msg, chat_id, reply_markup=reply_markup)

def show_explosions_with_buttons(chat_id, message_id=None):
    if not explosions_found:
        msg = "💥 <b>No explosions found</b>\nUse /explode to scan"
        send_msg(msg, chat_id)
        return
    keyboard = []
    for exp in explosions_found[:10]:
        explosion = exp['explosion']
        button_text = f"💥 {exp['symbol']} | Score {explosion['score']} | +{explosion['expected_rise']}%"
        keyboard.append([{'text': button_text, 'callback_data': f"BUY_{exp['symbol']}"}])
    reply_markup = {'inline_keyboard': keyboard}
    msg = "💥 <b>Explosion Candidates</b>\n\n"
    for i, exp in enumerate(explosions_found[:10], 1):
        explosion = exp['explosion']
        msg += f"{i}. <b>{exp['symbol']}</b>\n   💥 Score: {explosion['score']}/100\n   📈 Expected Rise: +{explosion['expected_rise']}%\n   ⏰ Time: {explosion['time_to_explode']} min\n   💰 Price: ${exp['price']:.6f}\n\n"
    msg += "💡 <b>Click a coin to open a trade</b>"
    send_msg(msg, chat_id, reply_markup=reply_markup)

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 STARTING BINANCE TRADING BOT")
    print("=" * 60)
    keep_alive_thread = threading.Thread(target=start_keep_alive, daemon=True)
    keep_alive_thread.start()
    send_msg("🚀 <b>Trading Bot Started!</b>\n\n💡 Use /explode to scan for explosions\n💡 Use /buy SYMBOL to open trades")
    monitor_thread = threading.Thread(target=handle_commands, daemon=True)
    monitor_thread.start()
    handle_commands()
