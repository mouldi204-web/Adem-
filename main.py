#!/usr/bin/env python3
"""
Binance Spot Trading Bot - Fully Automated Paper Trading
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
TELEGRAM_CHANNEL_ID = "1001003692815602"

INITIAL_BALANCE = 1000
BASE_TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 10
MIN_BALANCE_TO_TRADE = 50

PROFIT_TARGET = 5
STOP_LOSS = -3

TRAILING_STOP_ENABLED = True
TRAILING_STOP_ACTIVATION = 2
TRAILING_STOP_DISTANCE = 1.5

MAX_SYMBOLS = 1200
MIN_SCORE_TO_TRADE = 75
COOLDOWN_HOURS = 24

STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD', 'USDP']

# ================== GLOBAL VARIABLES ==================
balance = INITIAL_BALANCE
open_trades = {}
closed_trades = []
last_update_id = 0
scanning = False
is_auto_scan_running = True
detected_coins = {}
auto_traded_recently = {}
start_time = time.time()
trailing_stop_tracker = {}

scan_stats = {
    "last_scan": None,
    "total_scanned": 0,
    "found_candidates": 0,
    "auto_trades_opened": 0
}

CSV_TRADES = "trades.csv"
CSV_PORTFOLIO = "portfolio.csv"
CSV_DETECTED = "detected_coins.csv"

# ================== TELEGRAM FUNCTIONS ==================
def send_telegram(text, chat_id=None, parse_mode='HTML'):
    target = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": target, "text": text, "parse_mode": parse_mode}).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def send_to_channel(text):
    send_telegram(text, TELEGRAM_CHANNEL_ID)

# ================== PRICE FUNCTIONS ==================
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

# ================== SCORE CALCULATION ==================
def calculate_score(symbol, data):
    score = 0
    reasons = []
    price = data['price']
    change = data['change']
    volume = data['volume']
    high = data['high']
    low = data['low']
    
    if change > 8:
        score += 35
        reasons.append(f"Surge +{change:.1f}%")
    elif change > 5:
        score += 30
        reasons.append(f"Jump +{change:.1f}%")
    elif change > 3:
        score += 20
        reasons.append(f"Rise +{change:.1f}%")
    elif change > 1:
        score += 10
        reasons.append(f"Start +{change:.1f}%")
    
    if volume > 100_000_000:
        score += 30
        reasons.append("Very high volume")
    elif volume > 50_000_000:
        score += 25
        reasons.append("High volume")
    elif volume > 20_000_000:
        score += 15
        reasons.append("Good volume")
    elif volume > 10_000_000:
        score += 10
        reasons.append("Medium volume")
    
    if price < 0.1:
        score += 15
        reasons.append(f"Very low price ${price:.4f}")
    elif price < 0.5:
        score += 10
        reasons.append(f"Low price ${price:.4f}")
    elif price < 2:
        score += 5
        reasons.append(f"Good price ${price:.4f}")
    
    if high > 0 and low > 0:
        volatility = ((high - low) / low) * 100
        if volatility > 12:
            score += 20
            reasons.append(f"High volatility {volatility:.0f}%")
        elif volatility > 8:
            score += 15
            reasons.append(f"Good volatility {volatility:.0f}%")
        elif volatility > 5:
            score += 10
            reasons.append(f"Normal volatility {volatility:.0f}%")
    
    return min(score, 100), reasons

# ================== TRADING FUNCTIONS ==================
def can_open_new_trade():
    return len(open_trades) < MAX_OPEN_TRADES and balance >= MIN_BALANCE_TO_TRADE

def is_coin_tradable(symbol):
    if symbol in open_trades:
        return False, "Already open"
    if symbol in auto_traded_recently:
        last_time = auto_traded_recently[symbol]
        hours_passed = (datetime.now() - last_time).total_seconds() / 3600
        if hours_passed < COOLDOWN_HOURS:
            return False, f"Cooldown ({COOLDOWN_HOURS - hours_passed:.1f}h left)"
    return True, "Ready"

def open_trade(symbol, price, score, reasons):
    global balance, open_trades
    if not can_open_new_trade():
        return False, f"Cannot open trade (max: {MAX_OPEN_TRADES}, balance: ${balance:.2f})"
    tradable, msg = is_coin_tradable(symbol)
    if not tradable:
        return False, msg
    trade_amount = BASE_TRADE_AMOUNT
    quantity = trade_amount / price
    trade = {
        "id": f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "symbol": symbol,
        "entry_price": price,
        "entry_time": datetime.now(),
        "amount": trade_amount,
        "quantity": quantity,
        "score": score,
        "reasons": reasons,
        "highest_price": price,
        "lowest_price": price,
        "status": "OPEN"
    }
    open_trades[symbol] = trade
    balance -= trade_amount
    auto_traded_recently[symbol] = datetime.now()
    if symbol in trailing_stop_tracker:
        del trailing_stop_tracker[symbol]
    save_trades_csv()
    save_portfolio_csv()
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
    trade['status'] = "CLOSED"
    closed_trades.append(trade)
    del open_trades[symbol]
    balance += trade['amount'] + profit_loss
    if symbol in trailing_stop_tracker:
        del trailing_stop_tracker[symbol]
    save_trades_csv()
    save_portfolio_csv()
    return True, trade

def update_trade_prices():
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            if current_price > trade['highest_price']:
                trade['highest_price'] = current_price
            if current_price < trade['lowest_price']:
                trade['lowest_price'] = current_price

# ================== TRAILING STOP ==================
def update_trailing_stop(symbol, current_price, entry_price):
    if not TRAILING_STOP_ENABLED:
        return None, False
    current_return = ((current_price - entry_price) / entry_price) * 100
    if symbol not in trailing_stop_tracker:
        trailing_stop_tracker[symbol] = {"highest": entry_price, "stop": None, "activated": False}
    tracker = trailing_stop_tracker[symbol]
    if current_return >= TRAILING_STOP_ACTIVATION and not tracker["activated"]:
        tracker["activated"] = True
        tracker["highest"] = current_price
        tracker["stop"] = current_price * (1 - TRAILING_STOP_DISTANCE / 100)
        send_telegram(f"🔒 Trailing Stop activated for {symbol}\nStop: ${tracker['stop']:.6f}")
    if current_price > tracker["highest"]:
        tracker["highest"] = current_price
        if tracker["activated"]:
            tracker["stop"] = current_price * (1 - TRAILING_STOP_DISTANCE / 100)
    if tracker["activated"] and tracker["stop"]:
        if current_price <= tracker["stop"]:
            return tracker["stop"], True
    return tracker.get("stop"), False

def monitor_trades():
    for symbol in list(open_trades.keys()):
        try:
            current_price = get_price(symbol)
            if current_price == 0:
                continue
            trade = open_trades[symbol]
            current_return = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            if current_price > trade['highest_price']:
                trade['highest_price'] = current_price
            _, should_close = update_trailing_stop(symbol, current_price, trade['entry_price'])
            if should_close:
                close_trade(symbol, "TRAILING_STOP")
                send_telegram(f"📉 Trailing Stop Triggered\n{symbol}\nReturn: {current_return:+.2f}%")
            elif current_return >= PROFIT_TARGET:
                close_trade(symbol, "TP_HIT")
                send_telegram(f"✅ Target Hit\n{symbol}\nReturn: {current_return:+.2f}%")
            elif current_return <= STOP_LOSS:
                close_trade(symbol, "SL_HIT")
                send_telegram(f"❌ Stop Loss Hit\n{symbol}\nReturn: {current_return:+.2f}%")
        except Exception as e:
            print(f"Monitor error for {symbol}: {e}")

# ================== AUTO SCAN & AUTO TRADE ==================
def select_best_coins(candidates, limit=3):
    candidates.sort(key=lambda x: x[3], reverse=True)
    selected = []
    for cand in candidates[:limit]:
        selected.append({"symbol": cand[0], "price": cand[1], "score": cand[3], "reasons": cand[4] if len(cand) > 4 else []})
    return selected

def auto_open_trades(best_coins):
    opened = []
    for coin in best_coins:
        symbol = coin["symbol"]
        price = coin["price"]
        score = coin["score"]
        reasons = coin["reasons"]
        if not can_open_new_trade():
            send_telegram(f"⚠️ Cannot open more trades. Max: {MAX_OPEN_TRADES}, Balance: ${balance:.2f}")
            break
        success, _ = open_trade(symbol, price, score, reasons)
        if success:
            opened.append(symbol)
            scan_stats["auto_trades_opened"] += 1
            send_telegram(f"✅ AUTO TRADE OPENED\n{symbol}\nScore: {score}/100\nEntry: ${price:.6f}\nAmount: ${BASE_TRADE_AMOUNT}")
        else:
            send_telegram(f"⚠️ Auto trade failed for {symbol}")
    return opened

def scan_and_auto_trade():
    global scanning, scan_stats, detected_coins
    scanning = True
    scan_stats["last_scan"] = datetime.now()
    send_telegram(f"🔍 Auto Scan Started\nBalance: ${balance:.2f}\nMax trades: {MAX_OPEN_TRADES - len(open_trades)}")
    try:
        all_prices = get_all_prices()
        candidates = []
        for symbol, data in all_prices.items():
            score, reasons = calculate_score(symbol, data)
            if symbol not in detected_coins:
                detected_coins[symbol] = {"first_seen": datetime.now(), "best_score": score, "best_price": data['price']}
            else:
                if score > detected_coins[symbol]["best_score"]:
                    detected_coins[symbol]["best_score"] = score
            if score >= MIN_SCORE_TO_TRADE:
                candidates.append((symbol, data['price'], data['change'], score, reasons))
        scan_stats["total_scanned"] = len(all_prices)
        scan_stats["found_candidates"] = len(candidates)
        if candidates:
            report = f"📊 Scan Results\nFound {len(candidates)} candidates\n\n"
            for cand in candidates[:5]:
                report += f"• {cand[0]}: Score {cand[3]} | Change {cand[2]:+.1f}%\n"
            send_telegram(report)
            best_coins = select_best_coins(candidates, limit=3)
            if best_coins and can_open_new_trade():
                opened = auto_open_trades(best_coins)
                if opened:
                    send_telegram(f"✅ Auto trades opened: {', '.join(opened)}")
        else:
            send_telegram(f"📊 Scan complete. No candidates with score >= {MIN_SCORE_TO_TRADE}")
        save_detected_csv()
    except Exception as e:
        send_telegram(f"❌ Scan error: {str(e)[:100]}")
    finally:
        scanning = False

def start_auto_scan_scheduler():
    global is_auto_scan_running
    send_telegram("🔄 Auto-scan scheduler started (every 15 minutes)")
    while is_auto_scan_running:
        now = datetime.now()
        minutes_to_next = 15 - (now.minute % 15)
        seconds_to_next = minutes_to_next * 60 - now.second
        if seconds_to_next <= 0:
            seconds_to_next += 900
        time.sleep(seconds_to_next)
        if not scanning:
            scan_and_auto_trade()
            monitor_trades()

def start_monitoring_loop():
    while True:
        try:
            monitor_trades()
            time.sleep(30)
        except Exception as e:
            print(f"Monitor loop error: {e}")
            time.sleep(60)

# ================== CSV SAVING ==================
def save_trades_csv():
    with open(CSV_TRADES, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Type', 'ID', 'Symbol', 'Entry Price', 'Entry Time', 'Amount', 
                        'Quantity', 'Exit Price', 'Exit Time', 'Return%', 'Profit/Loss', 
                        'Exit Reason', 'Score', 'Status'])
        for trade in open_trades.values():
            writer.writerow([
                'OPEN', trade['id'], trade['symbol'], trade['entry_price'],
                trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S'), trade['amount'],
                trade['quantity'], '-', '-', '-', '-', '-', trade['score'], 'OPEN'
            ])
        for trade in closed_trades:
            writer.writerow([
                'CLOSED', trade['id'], trade['symbol'], trade['entry_price'],
                trade['entry_time'].strftime('%Y-%m-%d %H:%M:%S'), trade['amount'],
                trade['quantity'], trade.get('exit_price', '-'),
                trade.get('exit_time', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                f"{trade.get('final_return', 0):.2f}", f"{trade.get('profit_loss', 0):.2f}",
                trade.get('exit_reason', '-'), trade.get('score', 0), 'CLOSED'
            ])

def save_portfolio_csv():
    status = get_portfolio_status()
    with open(CSV_PORTFOLIO, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Time', 'Balance', 'Total Value', 'Total PnL', 'Return%', 
                        'Open Trades', 'Closed Trades', 'Win Rate%'])
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            f"{status['balance']:.2f}", f"{status['total_value']:.2f}",
            f"{status['total_pnl']:.2f}", f"{status['return_pct']:.2f}",
            status['open_trades'], status['closed_trades'], f"{status['win_rate']:.2f}"
        ])

def save_detected_csv():
    with open(CSV_DETECTED, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['First Seen', 'Symbol', 'Best Score', 'Best Price', 'Status'])
        for symbol, data in detected_coins.items():
            writer.writerow([
                data['first_seen'].strftime('%Y-%m-%d %H:%M:%S'),
                symbol, data['best_score'], data['best_price'], 'MONITORED'
            ])

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
        'return_pct': (total_pnl / INITIAL_BALANCE) * 100,
        'open_trades': len(open_trades),
        'closed_trades': len(closed_trades),
        'win_rate': win_rate
    }

# ================== WEB SERVER ==================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        status = get_portfolio_status()
        uptime = (time.time() - start_time) / 3600
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Auto Trading Bot</title><meta http-equiv="refresh" content="30">
        <style>body{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#eee;font-family:Segoe UI,sans-serif;padding:20px}}
        .container{{max-width:1200px;margin:auto}}.header{{text-align:center;margin-bottom:30px;padding:20px;background:rgba(255,255,255,0.1);border-radius:15px}}
        .stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:20px;margin-bottom:30px}}
        .card{{background:rgba(255,255,255,0.1);border-radius:15px;padding:15px;text-align:center}}
        .card-value{{font-size:24px;font-weight:bold}}.profit{{color:#4CAF50}}.loss{{color:#ff6b6b}}
        .section{{background:rgba(255,255,255,0.05);border-radius:15px;padding:20px;margin-bottom:30px}}
        table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.1)}}
        th{{background:rgba(0,0,0,0.4)}}.auto-badge{{background:#4CAF50;color:white;padding:2px 8px;border-radius:10px;font-size:11px}}
        </style>
        </head>
        <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Auto Trading Bot</h1>
                <p>Status: ✅ ONLINE | Uptime: {uptime:.1f}h | <span class="auto-badge">AUTO-TRADING ACTIVE</span></p>
                <p>📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            <div class="stats-grid">
                <div class="card"><div>💰 BALANCE</div><div class="card-value">${status['balance']:.2f}</div></div>
                <div class="card"><div>📈 TOTAL PnL</div><div class="card-value {'profit' if status['total_pnl']>=0 else 'loss'}">${status['total_pnl']:+.2f}</div></div>
                <div class="card"><div>📊 RETURN</div><div class="card-value {'profit' if status['return_pct']>=0 else 'loss'}">{status['return_pct']:+.1f}%</div></div>
                <div class="card"><div>🟢 OPEN</div><div class="card-value">{status['open_trades']}/{MAX_OPEN_TRADES}</div></div>
                <div class="card"><div>🔒 CLOSED</div><div class="card-value">{status['closed_trades']}</div></div>
                <div class="card"><div>📊 WIN RATE</div><div class="card-value">{status['win_rate']:.1f}%</div></div>
            </div>
            <div class="section">
                <h2>📊 Scan Statistics</h2>
                <p>Last Scan: {scan_stats['last_scan'].strftime('%H:%M:%S') if scan_stats['last_scan'] else 'Never'}</p>
                <p>Total Scanned: {scan_stats['total_scanned']} | Candidates: {scan_stats['found_candidates']} | Auto Trades: {scan_stats['auto_trades_opened']}</p>
                <p>Next auto-scan: ~{(15 - (datetime.now().minute % 15)) % 15} minutes</p>
            </div>
            <div class="section">
                <h2>🟢 OPEN TRADES ({len(open_trades)})</h2>
                <table><thead><tr><th>Symbol</th><th>Entry Price</th><th>Entry Time</th><th>Score</th></tr></thead><tbody>
        """
        for trade in open_trades.values():
            html += f"<tr><td>{trade['symbol']}</td><td>${trade['entry_price']:.6f}</td><td>{trade['entry_time'].strftime('%H:%M:%S')}</td><td>{trade['score']}</td></tr>"
        if not open_trades:
            html += "<tr><td colspan='4'>No open trades</td></tr>"
        html += """
                </tbody>
            </table>
            </div>
            <div class="section">
                <h2>🔒 RECENT CLOSED TRADES</h2>
                <table><thead><tr><th>Symbol</th><th>Return%</th><th>Profit/Loss</th><th>Exit Reason</th></tr></thead><tbody>
        """
        for trade in closed_trades[-10:]:
            return_class = "profit" if trade.get('final_return', 0) >= 0 else "loss"
            html += f"<tr><td>{trade['symbol']}</td><td class='{return_class}'>{trade.get('final_return', 0):+.1f}%</td><td class='{return_class}'>${trade.get('profit_loss', 0):+.2f}</td><td>{trade.get('exit_reason', '-')}</td></tr>"
        if not closed_trades:
            html += "<tr><td colspan='4'>No closed trades</td></tr>"
        html += f"""
                </tbody>
            </table>
            </div>
            <div class="section">
                <p style="text-align:center">🤖 Auto-scan every 15 minutes | Auto-trade on score ≥ {MIN_SCORE_TO_TRADE} | Trailing Stop: {TRAILING_STOP_DISTANCE}%</p>
            </div>
        </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode())
    def log_message(self, format, *args):
        pass

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
    global last_update_id, is_auto_scan_running, scanning
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
                    txt = f"""🤖 <b>Auto Trading Bot</b>

✅ Status: ACTIVE
💰 Balance: ${balance:.2f}
🟢 Max Trades: {MAX_OPEN_TRADES}
🎯 Min Score: {MIN_SCORE_TO_TRADE}
🔒 Trailing Stop: {TRAILING_STOP_DISTANCE}%

<b>Commands:</b>
/status - Bot status
/scan - Manual scan
/portfolio - Portfolio details
/closeall - Close all trades
/help - Help

<b>Auto Features:</b>
• Auto-scan every 15 minutes
• Auto-open trades on high score
• Auto-close with TP/SL/Trailing"""
                    send_telegram(txt, chat)

                elif text == '/status':
                    st = get_portfolio_status()
                    upt = (time.time() - start_time) / 3600
                    txt = f"""📊 <b>Bot Status</b>
✅ Auto-Trading: ACTIVE
⏰ Uptime: {upt:.1f}h
💰 Balance: ${st['balance']:.2f}
📈 Total PnL: ${st['total_pnl']:+.2f}
🟢 Open: {st['open_trades']}/{MAX_OPEN_TRADES}
📊 Win Rate: {st['win_rate']:.1f}%
🎯 Min Score: {MIN_SCORE_TO_TRADE}
🔒 Trailing Stop: {TRAILING_STOP_DISTANCE}%
🔄 Next auto-scan: ~{(15 - (datetime.now().minute % 15)) % 15} min"""
                    send_telegram(txt, chat)

                elif text == '/scan':
                    if scanning:
                        send_telegram("Scan already in progress", chat)
                    else:
                        send_telegram("🔍 Manual scan started...", chat)
                        threading.Thread(target=scan_and_auto_trade, daemon=True).start()

                elif text == '/portfolio':
                    st = get_portfolio_status()
                    txt = f"""💰 <b>Portfolio</b>
Balance: ${st['balance']:.2f}
Total Value: ${st['total_value']:.2f}
Total Pn
