#!/usr/bin/env python3
"""
Binance Auto Trading Bot - Paper Trading
"""

import os
import time
import json
import threading
import urllib.request
import csv
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================== SETTINGS ==================
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"

INITIAL_BALANCE = 1000
BASE_TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 10
PROFIT_TARGET = 5
STOP_LOSS = -3
TRAILING_STOP_ACTIVATION = 2
TRAILING_STOP_DISTANCE = 1.5
MIN_SCORE_TO_TRADE = 75
COOLDOWN_HOURS = 24

STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD']

# ================== GLOBALS ==================
balance = INITIAL_BALANCE
open_trades = {}
closed_trades = []
scanning = False
auto_traded_recently = {}
start_time = time.time()
trailing = {}
detected_coins = {}
last_update_id = 0

# ================== TELEGRAM ==================
def send_telegram(text, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": target, "text": text, "parse_mode": "HTML"}).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ================== PRICE ==================
def get_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        with urllib.request.urlopen(url, timeout=10) as r:
            return float(json.loads(r.read().decode())["price"])
    except:
        return 0

def get_all_prices():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
            prices = {}
            for item in data:
                if item['symbol'].endswith('USDT'):
                    sym = item['symbol'].replace('USDT', '')
                    if sym not in STABLE_COINS:
                        prices[sym] = {
                            'price': float(item['lastPrice']),
                            'change': float(item['priceChangePercent']),
                            'volume': float(item['quoteVolume']),
                            'high': float(item['highPrice']),
                            'low': float(item['lowPrice'])
                        }
            return prices
    except:
        return {}

# ================== SCORE ==================
def calculate_score(symbol, data):
    score = 0
    change = data['change']
    volume = data['volume']
    price = data['price']
    high = data['high']
    low = data['low']
    if change > 8: score += 35
    elif change > 5: score += 30
    elif change > 3: score += 20
    elif change > 1: score += 10
    if volume > 100_000_000: score += 30
    elif volume > 50_000_000: score += 25
    elif volume > 20_000_000: score += 15
    elif volume > 10_000_000: score += 10
    if price < 0.1: score += 15
    elif price < 0.5: score += 10
    elif price < 2: score += 5
    if high > 0 and low > 0:
        vol = ((high - low) / low) * 100
        if vol > 12: score += 20
        elif vol > 8: score += 15
        elif vol > 5: score += 10
    return min(score, 100)

# ================== TRADING ==================
def can_open():
    return len(open_trades) < MAX_OPEN_TRADES and balance >= BASE_TRADE_AMOUNT

def is_tradable(symbol):
    if symbol in open_trades: return False
    if symbol in auto_traded_recently:
        last = auto_traded_recently[symbol]
        if (datetime.now() - last).total_seconds() < COOLDOWN_HOURS * 3600:
            return False
    return True

def open_trade(symbol, price, score):
    global balance
    if not can_open(): return False
    if not is_tradable(symbol): return False
    qty = BASE_TRADE_AMOUNT / price
    trade = {
        "symbol": symbol, "entry_price": price, "entry_time": datetime.now(),
        "amount": BASE_TRADE_AMOUNT, "quantity": qty, "score": score,
        "highest": price, "status": "OPEN"
    }
    open_trades[symbol] = trade
    balance -= BASE_TRADE_AMOUNT
    auto_traded_recently[symbol] = datetime.now()
    return True

def close_trade(symbol, reason):
    global balance
    if symbol not in open_trades: return
    trade = open_trades[symbol]
    cur = get_price(symbol)
    if cur == 0: return
    ret = ((cur - trade['entry_price']) / trade['entry_price']) * 100
    pnl = (cur - trade['entry_price']) * trade['quantity']
    trade['exit_price'] = cur
    trade['exit_time'] = datetime.now()
    trade['final_return'] = ret
    trade['profit_loss'] = pnl
    trade['exit_reason'] = reason
    trade['status'] = "CLOSED"
    closed_trades.append(trade)
    del open_trades[symbol]
    balance += trade['amount'] + pnl
    if symbol in trailing:
        del trailing[symbol]

def monitor():
    for sym in list(open_trades.keys()):
        cur = get_price(sym)
        if cur == 0: continue
        trade = open_trades[sym]
        ret = ((cur - trade['entry_price']) / trade['entry_price']) * 100
        if cur > trade['highest']:
            trade['highest'] = cur
        # trailing stop
        if sym not in trailing:
            if ret >= TRAILING_STOP_ACTIVATION:
                trailing[sym] = cur * (1 - TRAILING_STOP_DISTANCE / 100)
                send_telegram(f"🔒 Trailing active {sym} at ${trailing[sym]:.6f}")
        else:
            if cur <= trailing[sym]:
                close_trade(sym, "TRAILING")
                send_telegram(f"📉 Trailing closed {sym} | Return: {ret:+.2f}%")
                continue
            if cur > trade['highest']:
                trailing[sym] = cur * (1 - TRAILING_STOP_DISTANCE / 100)
        # tp / sl
        if ret >= PROFIT_TARGET:
            close_trade(sym, "TP")
            send_telegram(f"✅ TP {sym} | Return: {ret:+.2f}%")
        elif ret <= STOP_LOSS:
            close_trade(sym, "SL")
            send_telegram(f"❌ SL {sym} | Return: {ret:+.2f}%")

# ================== SCAN ==================
def scan_and_trade():
    global scanning
    scanning = True
    send_telegram("🔍 Scanning market...")
    try:
        prices = get_all_prices()
        candidates = []
        for sym, data in prices.items():
            score = calculate_score(sym, data)
            if score >= MIN_SCORE_TO_TRADE:
                candidates.append((sym, data['price'], score))
        candidates.sort(key=lambda x: x[2], reverse=True)
        if candidates:
            msg = "📊 Top candidates:\n"
            for c in candidates[:5]:
                msg += f"{c[0]} | Score {c[2]} | ${c[1]:.6f}\n"
            send_telegram(msg)
            for sym, price, score in candidates[:3]:
                if can_open() and is_tradable(sym):
                    open_trade(sym, price, score)
                    send_telegram(f"✅ AUTO BUY {sym} | Score {score} | ${price:.6f}")
        else:
            send_telegram("No candidates found.")
    except Exception as e:
        send_telegram(f"Scan error: {str(e)[:100]}")
    finally:
        scanning = False

def auto_scan_loop():
    while True:
        now = datetime.now()
        wait = 900 - (now.minute % 15) * 60 - now.second
        if wait <= 0: wait += 900
        time.sleep(wait)
        if not scanning:
            scan_and_trade()

def monitor_loop():
    while True:
        monitor()
        time.sleep(30)

# ================== WEB ==================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        status = {
            'balance': balance,
            'open': len(open_trades),
            'closed': len(closed_trades),
            'win': sum(1 for t in closed_trades if t.get('final_return', 0) > 0),
            'total_pnl': sum(t.get('profit_loss', 0) for t in closed_trades)
        }
        win_rate = (status['win'] / status['closed'] * 100) if status['closed'] else 0
        uptime = (time.time() - start_time) / 3600
        html = f"""
        <html><head><title>Auto Trading Bot</title><meta http-equiv="refresh" content="30"></head>
        <body style="background:#1a1a2e;color:#eee;font-family:Arial;text-align:center;padding:20px">
        <h1>🚀 Auto Trading Bot</h1>
        <p>Status: ✅ ONLINE | Uptime: {uptime:.1f}h</p>
        <p>💰 Balance: ${status['balance']:.2f}</p>
        <p>📈 Total PnL: ${status['total_pnl']:+.2f}</p>
        <p>🟢 Open: {status['open']} | 🔒 Closed: {status['closed']}</p>
        <p>📊 Win Rate: {win_rate:.1f}%</p>
        <p>📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body></html>
        """
        self.wfile.write(html.encode())
    def log_message(self, format, *args): pass

def start_web():
    port = int(os.environ.get('PORT', 8080))
    HTTPServer(('0.0.0.0', port), WebHandler).serve_forever()

# ================== TELEGRAM COMMANDS ==================
def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    if offset:
        url += f"?offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except:
        return {"result": []}

def handle_commands():
    global last_update_id
    while True:
        try:
            updates = get_updates(last_update_id + 1)
            for upd in updates.get('result', []):
                last_update_id = upd['update_id']
                msg = upd.get('message', {})
                text = msg.get('text', '').lower()
                chat = msg.get('chat', {}).get('id')
                if not chat:
                    continue
                if text == '/start':
                    send_telegram("🤖 Auto Trading Bot started.\n/status - Info\n/scan - Manual scan\n/portfolio - Details\n/closeall - Close all\n/help", chat)
                elif text == '/status':
                    st = {'balance': balance, 'open': len(open_trades), 'closed': len(closed_trades)}
                    win = sum(1 for t in closed_trades if t.get('final_return', 0) > 0)
                    wr = (win / st['closed'] * 100) if st['closed'] else 0
                    send_telegram(f"💰 Balance: ${st['balance']:.2f}\n🟢 Open: {st['open']}\n🔒 Closed: {st['closed']}\n📊 Win rate: {wr:.1f}%", chat)
                elif text == '/scan':
                    if scanning:
                        send_telegram("Scan already running.", chat)
                    else:
                        send_telegram("Manual scan started.", chat)
                        threading.Thread(target=scan_and_trade, daemon=True).start()
                elif text == '/portfolio':
                    msg = f"💰 Balance: ${balance:.2f}\n\n🟢 Open trades:\n"
                    for sym, trade in open_trades.items():
                        cur = get_price(sym)
                        ret = ((cur - trade['entry_price']) / trade['entry_price']) * 100 if cur else 0
                        msg += f"{sym}: {ret:+.1f}% (${trade['entry_price']:.4f})\n"
                    if not open_trades:
                        msg += "No open trades.\n"
                    send_telegram(msg, chat)
                elif text == '/closeall':
                    count = len(open_trades)
                    for sym in list(open_trades.keys()):
                        close_trade(sym, "MANUAL")
                    send_telegram(f"Closed {count} trades.", chat)
                elif text == '/help':
                    send_telegram("Commands: /start, /status, /scan, /portfolio, /closeall, /help", chat)
                else:
                    send_telegram("Unknown command. /help", chat)
            time.sleep(1)
        except Exception as e:
            print("Cmd error:", e)
            time.sleep(5)

# ================== MAIN ==================
if __name__ == "__main__":
    print("Starting Auto Trading Bot...")
    threading.Thread(target=start_web, daemon=True).start()
    threading.Thread(target=auto_scan_loop, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    handle_commands()
