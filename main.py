#!/usr/bin/env python3
"""
Adem Trading Bot - Full Version with Interactive Buttons & Web Dashboard
"""

import os
import json
import time
import threading
import urllib.request
import csv
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================== SETTINGS ==================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "1001003692815602"  # optional

INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 20

# Global variables
balance = INITIAL_BALANCE
open_trades = {}
closed_trades = []
last_update_id = 0
scanning = False
detected_coins = {}
start_time = time.time()

CSV_DETECTED = "detected_coins.csv"
CSV_TRADES = "trades.csv"
CSV_PORTFOLIO = "portfolio.csv"

# ================== TELEGRAM HELPERS ==================
def send_telegram(text, chat_id=None, reply_markup=None):
    target = chat_id or CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": target, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

def edit_message_text(text, chat_id, message_id, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("Edit error:", e)

def answer_callback(callback_id, text=None):
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    data = {"callback_query_id": callback_id}
    if text:
        data["text"] = text
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("Callback answer error:", e)

# ================== PRICE & PORTFOLIO ==================
def get_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
        with urllib.request.urlopen(url, timeout=10) as r:
            return float(json.loads(r.read().decode())["price"])
    except:
        return 0

def get_portfolio_status():
    total_value = balance
    for t in open_trades.values():
        price = get_price(t["symbol"])
        if price > 0:
            total_value += t["quantity"] * price
    realized = sum(t.get("profit_loss", 0) for t in closed_trades)
    total_pnl = realized
    wins = sum(1 for t in closed_trades if t.get("final_return", 0) > 0)
    win_rate = (wins / len(closed_trades) * 100) if closed_trades else 0
    return {
        "balance": balance,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "return_pct": (total_pnl / INITIAL_BALANCE) * 100,
        "open_trades": len(open_trades),
        "closed_trades": len(closed_trades),
        "win_rate": win_rate
    }

# ================== UPDATE PRICES ==================
def update_detected_prices():
    for symbol, coin in detected_coins.items():
        price = get_price(symbol)
        if price > 0:
            if price > coin.get("highest_price", coin["detection_price"]):
                coin["highest_price"] = price
                coin["highest_rise"] = ((price - coin["detection_price"]) / coin["detection_price"]) * 100
            if price < coin.get("lowest_price", coin["detection_price"]):
                coin["lowest_price"] = price
                coin["lowest_drop"] = ((price - coin["detection_price"]) / coin["detection_price"]) * 100
            coin["current_price"] = price
            coin["current_rise"] = ((price - coin["detection_price"]) / coin["detection_price"]) * 100
            coin["last_update"] = datetime.now()

def update_trade_prices():
    for symbol, trade in open_trades.items():
        price = get_price(symbol)
        if price > 0:
            if price > trade["highest_price"]:
                trade["highest_price"] = price
                trade["highest_rise"] = ((price - trade["entry_price"]) / trade["entry_price"]) * 100
            if price < trade["lowest_price"]:
                trade["lowest_price"] = price
                trade["lowest_drop"] = ((price - trade["entry_price"]) / trade["entry_price"]) * 100
            trade["current_price"] = price
            trade["current_return"] = ((price - trade["entry_price"]) / trade["entry_price"]) * 100

# ================== EXPLOSION SCAN ==================
def scan_for_explosions():
    global scanning, detected_coins
    scanning = True
    send_telegram("🔍 Scanning for explosions... (30 sec)")
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
            explosions = []
            for item in data:
                if not item["symbol"].endswith("USDT"):
                    continue
                symbol = item["symbol"][:-4]
                change = float(item["priceChangePercent"])
                volume = float(item["quoteVolume"])
                price = float(item["lastPrice"])
                score = 0
                if change > 5: score += 35
                elif change > 3: score += 20
                elif change > 1: score += 10
                if volume > 50_000_000: score += 30
                elif volume > 10_000_000: score += 20
                if price < 0.5: score += 15
                elif price < 2: score += 10
                if score >= 65:
                    explosions.append((symbol, price, change, score))
                    if symbol not in detected_coins:
                        detected_coins[symbol] = {
                            "detection_time": datetime.now(),
                            "detection_price": price,
                            "current_price": price,
                            "highest_price": price,
                            "lowest_price": price,
                            "highest_rise": 0,
                            "lowest_drop": 0,
                            "current_rise": 0,
                            "score": score,
                            "expected_rise": 5 + (score / 100) * 15,
                            "time_to_explode": 30,
                            "status": "ACTIVE"
                        }
            explosions.sort(key=lambda x: x[3], reverse=True)
            # Send alerts for top 5
            for sym, price, ch, sc in explosions[:5]:
                keyboard = {"inline_keyboard": [[{"text": f"BUY {sym}", "callback_data": f"BUY_{sym}"}]]}
                send_telegram(f"💥 <b>{sym}</b>\nScore: {sc}/100 | Change: {ch:+.1f}%\nPrice: ${price:.6f}", reply_markup=keyboard)
            send_telegram(f"✅ Scan done. Found {len(explosions)} explosions.")
            save_detected_csv()
    except Exception as e:
        send_telegram(f"❌ Scan error: {str(e)[:100]}")
    finally:
        scanning = False

# ================== CSV SAVING ==================
def save_detected_csv():
    with open(CSV_DETECTED, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Time", "Symbol", "Detection Price", "Current Price", "Current Rise%", "Highest Price", "Highest Rise%", "Lowest Price", "Lowest Drop%", "Score", "Expected Rise%", "Status"])
        for sym, coin in detected_coins.items():
            writer.writerow([
                coin["detection_time"].strftime("%Y-%m-%d %H:%M:%S"), sym,
                coin["detection_price"], coin.get("current_price", coin["detection_price"]),
                f"{coin.get('current_rise', 0):.2f}", coin.get("highest_price", coin["detection_price"]),
                f"{coin.get('highest_rise', 0):.2f}", coin.get("lowest_price", coin["detection_price"]),
                f"{coin.get('lowest_drop', 0):.2f}", coin["score"], coin.get("expected_rise", 0), coin["status"]
            ])

def save_trades_csv():
    with open(CSV_TRADES, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Type", "Symbol", "Entry Price", "Entry Time", "Exit Price", "Exit Time", "Return%", "Profit/Loss", "Exit Reason"])
        for trade in open_trades.values():
            writer.writerow(["OPEN", trade["symbol"], trade["entry_price"], trade["entry_time"].strftime("%Y-%m-%d %H:%M:%S"), "-", "-", "-", "-", "-"])
        for trade in closed_trades:
            writer.writerow(["CLOSED", trade["symbol"], trade["entry_price"], trade["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
                             trade.get("exit_price", "-"), trade.get("exit_time", datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
                             f"{trade.get('final_return', 0):.2f}", f"{trade.get('profit_loss', 0):.2f}", trade.get("exit_reason", "-")])

def save_portfolio_csv():
    status = get_portfolio_status()
    with open(CSV_PORTFOLIO, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Time", "Balance", "Total Value", "Total PnL", "Return%", "Open Trades", "Closed Trades", "Win Rate%"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status["balance"], status["total_value"], status["total_pnl"], status["return_pct"], status["open_trades"], status["closed_trades"], status["win_rate"]])

# ================== TRADING ==================
def open_trade(symbol, price, score):
    global balance, open_trades
    if len(open_trades) >= MAX_OPEN_TRADES:
        return False, "Max trades reached"
    if balance < TRADE_AMOUNT:
        return False, f"Insufficient balance ${balance:.2f}"
    if symbol in open_trades:
        return False, "Trade already open"
    trade = {
        "symbol": symbol,
        "entry_price": price,
        "entry_time": datetime.now(),
        "amount": TRADE_AMOUNT,
        "quantity": TRADE_AMOUNT / price,
        "score": score,
        "highest_price": price,
        "lowest_price": price,
        "highest_rise": 0,
        "lowest_drop": 0,
        "status": "OPEN"
    }
    open_trades[symbol] = trade
    balance -= TRADE_AMOUNT
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
        return False, "Cannot get price"
    ret = ((current_price - trade["entry_price"]) / trade["entry_price"]) * 100
    pnl = (current_price - trade["entry_price"]) * trade["quantity"]
    trade["exit_price"] = current_price
    trade["exit_time"] = datetime.now()
    trade["final_return"] = ret
    trade["profit_loss"] = pnl
    trade["exit_reason"] = reason
    trade["status"] = "CLOSED"
    closed_trades.append(trade)
    del open_trades[symbol]
    balance += trade["amount"] + pnl
    save_trades_csv()
    save_portfolio_csv()
    return True, trade

def close_all_trades():
    for s in list(open_trades.keys()):
        close_trade(s, "CLOSE_ALL")

# ================== WEB DASHBOARD ==================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        update_detected_prices()
        update_trade_prices()
        status = get_portfolio_status()
        uptime = (time.time() - start_time) / 3600
        
        # Detected coins table
        detected_rows = ""
        for sym, coin in sorted(detected_coins.items(), key=lambda x: x[1]["detection_time"], reverse=True)[:20]:
            detected_rows += f"""
            <tr>
                <td>{coin['detection_time'].strftime('%H:%M:%S')}</td>
                <td><b>{sym}</b></td>
                <td>${coin['detection_price']:.6f}</td>
                <td>${coin.get('current_price', coin['detection_price']):.6f}</td>
                <td class="{'profit' if coin.get('current_rise',0)>=0 else 'loss'}">{coin.get('current_rise',0):+.2f}%</td>
                <td class="profit">${coin.get('highest_price', coin['detection_price']):.6f}</td>
                <td class="profit">+{coin.get('highest_rise',0):.2f}%</td>
                <td class="loss">${coin.get('lowest_price', coin['detection_price']):.6f}</td>
                <td class="loss">{coin.get('lowest_drop',0):.2f}%</td>
                <td><span class="badge badge-high">{coin['score']}</span></td>
                <td class="profit">+{coin.get('expected_rise',5):.1f}%</td>
                <td>{coin.get('time_to_explode',30)} min</td>
                <td>{coin['status']}</td>
            </tr>
            """
        if not detected_rows:
            detected_rows = '<tr><td colspan="13">No detected coins. Run /explode.</td></tr>'
        
        # Open trades table
        open_rows = ""
        for sym, trade in open_trades.items():
            open_rows += f"""
            <tr>
                <td><b>{sym}</b></td>
                <td>{trade['entry_time'].strftime('%H:%M:%S')}</td>
                <td>${trade['entry_price']:.6f}</td>
                <td>${trade.get('current_price', trade['entry_price']):.6f}</td>
                <td class="{'profit' if trade.get('current_return',0)>=0 else 'loss'}">{trade.get('current_return',0):+.2f}%</td>
                <td class="profit">${trade['highest_price']:.6f}</td>
                <td class="profit">+{trade['highest_rise']:.2f}%</td>
                <td class="loss">${trade['lowest_price']:.6f}</td>
                <td class="loss">{trade['lowest_drop']:.2f}%</td>
                <td>${trade['amount']:.2f}</td>
            </tr>
            """
        if not open_rows:
            open_rows = '<tr><td colspan="10">No open trades</td></tr>'
        
        # Closed trades table
        closed_rows = ""
        for trade in closed_trades[-15:]:
            closed_rows += f"""
            <tr>
                <td><b>{trade['symbol']}</b></td>
                <td>{trade['entry_time'].strftime('%H:%M:%S')}</td>
                <td>{trade.get('exit_time', datetime.now()).strftime('%H:%M:%S')}</td>
                <td>${trade['entry_price']:.6f}</td>
                <td>${trade.get('exit_price',0):.6f}</td>
                <td class="{'profit' if trade.get('final_return',0)>=0 else 'loss'}">{trade.get('final_return',0):+.2f}%</td>
                <td class="{'profit' if trade.get('profit_loss',0)>=0 else 'loss'}">${trade.get('profit_loss',0):+.2f}</td>
                <td class="profit">+{trade.get('highest_rise',0):.2f}%</td>
                <td class="loss">{trade.get('lowest_drop',0):.2f}%</td>
                <td>{'✅' if trade.get('final_return',0)>=0 else '❌'} {trade.get('exit_reason','-')}</td>
            </tr>
            """
        if not closed_rows:
            closed_rows = '<tr><td colspan="10">No closed trades</td></tr>'
        
        html = f"""
        <!DOCTYPE html>
        <html lang="ar" dir="rtl">
        <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">
        <title>Adem Trading Bot</title>
        <style>
            body {{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#eee;font-family:Segoe UI,sans-serif;padding:20px}}
            .container {{max-width:1400px;margin:auto}}
            .header {{text-align:center;margin-bottom:30px;padding:20px;background:rgba(255,255,255,0.1);border-radius:15px}}
            .stats-grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:20px;margin-bottom:30px}}
            .card {{background:rgba(255,255,255,0.1);border-radius:15px;padding:15px;text-align:center}}
            .card-value {{font-size:24px;font-weight:bold}}
            .profit {{color:#4CAF50}} .loss {{color:#ff6b6b}}
            .section {{background:rgba(255,255,255,0.05);border-radius:15px;padding:20px;margin-bottom:30px;overflow-x:auto}}
            h2 {{border-bottom:2px solid #4CAF50;display:inline-block;margin-bottom:20px}}
            table {{width:100%;border-collapse:collapse;font-size:13px}}
            th,td {{padding:10px 8px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.1)}}
            th {{background:rgba(0,0,0,0.4)}}
            .badge {{display:inline-block;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:bold;background:#ff6b6b;color:white}}
            .footer {{text-align:center;margin-top:30px;font-size:12px;opacity:0.6}}
        </style>
        </head>
        <body>
        <div class="container">
            <div class="header"><h1>🚀 Adem Trading Bot</h1><p>Status: ✅ ONLINE | Uptime: {uptime:.1f}h</p><p>📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p></div>
            <div class="stats-grid">
                <div class="card"><div>💰 BALANCE</div><div class="card-value">${status['balance']:.2f}</div></div>
                <div class="card"><div>📈 TOTAL PnL</div><div class="card-value {'profit' if status['total_pnl']>=0 else 'loss'}">${status['total_pnl']:+.2f}</div></div>
                <div class="card"><div>📊 RETURN</div><div class="card-value {'profit' if status['return_pct']>=0 else 'loss'}">{status['return_pct']:+.1f}%</div></div>
                <div class="card"><div>🟢 OPEN</div><div class="card-value">{status['open_trades']}/{MAX_OPEN_TRADES}</div></div>
                <div class="card"><div>🔒 CLOSED</div><div class="card-value">{status['closed_trades']}</div></div>
                <div class="card"><div>📊 WIN RATE</div><div class="card-value">{status['win_rate']:.1f}%</div></div>
                <div class="card"><div>💥 DETECTED</div><div class="card-value">{len(detected_coins)}</div></div>
            </div>
            <div class="section"><h2>💥 DETECTED COINS</h2>
            <table><thead><tr><th>Time</th><th>Symbol</th><th>Detect Price</th><th>Current Price</th><th>Current Rise%</th><th>Highest Price</th><th>Highest Rise%</th><th>Lowest Price</th><th>Lowest Drop%</th><th>Score</th><th>Expected Rise%</th><th>Time</th><th>Status</th></tr></thead><tbody>{detected_rows}</tbody></table></div>
            <div class="section"><h2>🟢 OPEN TRADES</h2>
            <table><thead><tr><th>Symbol</th><th>Entry Time</th><th>Entry Price</th><th>Current Price</th><th>Return%</th><th>Highest Price</th><th>Highest Rise%</th><th>Lowest Price</th><th>Lowest Drop%</th><th>Amount</th></tr></thead><tbody>{open_rows}</tbody></table></div>
            <div class="section"><h2>🔒 CLOSED TRADES (Last 15)</h2>
            <table><thead><tr><th>Symbol</th><th>Entry Time</th><th>Exit Time</th><th>Entry Price</th><th>Exit Price</th><th>Return%</th><th>Profit/Loss</th><th>Highest Rise%</th><th>Lowest Drop%</th><th>Exit Reason</th></tr></thead><tbody>{closed_rows}</tbody></table></div>
            <div class="footer">🔄 Auto-refresh every 30s | Telegram: /menu</div>
        </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode())
    def log_message(self, format, *args): pass

def start_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), WebHandler).serve_forever()

# ================== TELEGRAM COMMANDS & BUTTONS ==================
def send_main_menu(chat_id, message_id=None):
    keyboard = {
        "inline_keyboard": [
            [{"text": "💥 Scan Explosions", "callback_data": "SCAN"}],
            [{"text": "🟢 Open Trade", "callback_data": "OPEN_MENU"}],
            [{"text": "🔴 Close Trade", "callback_data": "CLOSE_MENU"}],
            [{"text": "💰 Portfolio", "callback_data": "PORTFOLIO"}],
            [{"text": "📊 Bot Status", "callback_data": "STATUS"}],
            [{"text": "📁 Export CSV", "callback_data": "EXPORT"}]
        ]
    }
    text = "🤖 <b>Adem Trading Bot</b>\nChoose an action:"
    if message_id:
        edit_message_text(text, chat_id, message_id, keyboard)
    else:
        send_telegram(text, chat_id, keyboard)

def send_open_menu(chat_id, message_id=None):
    if not detected_coins:
        send_telegram("No detected coins yet. Run /explode first.", chat_id)
        return
    keyboard = {"inline_keyboard": []}
    for sym, coin in list(detected_coins.items())[:10]:
        keyboard["inline_keyboard"].append([{"text": f"💥 {sym} (Score: {coin['score']})", "callback_data": f"BUY_{sym}"}])
    keyboard["inline_keyboard"].append([{"text": "🔙 Back", "callback_data": "MAIN"}])
    text = "🟢 <b>Select coin to BUY:</b>"
    if message_id:
        edit_message_text(text, chat_id, message_id, keyboard)
    else:
        send_telegram(text, chat_id, keyboard)

def send_close_menu(chat_id, message_id=None):
    if not open_trades:
        send_telegram("No open trades.", chat_id)
        return
    keyboard = {"inline_keyboard": []}
    for sym, trade in open_trades.items():
        keyboard["inline_keyboard"].append([{"text": f"🔴 {sym} (Entry: ${trade['entry_price']:.4f})", "callback_data": f"CLOSE_{sym}"}])
    keyboard["inline_keyboard"].append([{"text": "🔴 Close ALL", "callback_data": "CLOSE_ALL"}])
    keyboard["inline_keyboard"].append([{"text": "🔙 Back", "callback_data": "MAIN"}])
    text = "🔴 <b>Select trade to CLOSE:</b>"
    if message_id:
        edit_message_text(text, chat_id, message_id, keyboard)
    else:
        send_telegram(text, chat_id, keyboard)

def send_confirmation(chat_id, action, symbol, message_id=None):
    if action == "BUY":
        coin = detected_coins.get(symbol)
        if not coin:
            send_telegram(f"❌ {symbol} not found.", chat_id)
            return
        keyboard = {"inline_keyboard": [
            [{"text": "✅ Confirm BUY", "callback_data": f"CONFIRM_BUY_{symbol}"}],
            [{"text": "❌ Cancel", "callback_data": "OPEN_MENU"}]
        ]}
        text = f"📊 <b>Confirm BUY {symbol}</b>\nPrice: ${coin['detection_price']:.6f}\nScore: {coin['score']}/100\nAmount: ${TRADE_AMOUNT}"
        if message_id:
            edit_message_text(text, chat_id, message_id, keyboard)
        else:
            send_telegram(text, chat_id, keyboard)
    elif action == "CLOSE":
        trade = open_trades.get(symbol)
        if not trade:
            send_telegram(f"❌ {symbol} not in open trades.", chat_id)
            return
        current_price = get_price(symbol)
        ret = ((current_price - trade["entry_price"]) / trade["entry_price"]) * 100 if current_price else 0
        keyboard = {"inline_keyboard": [
            [{"text": "✅ Confirm CLOSE", "callback_data": f"CONFIRM_CLOSE_{symbol}"}],
            [{"text": "❌ Cancel", "callback_data": "CLOSE_MENU"}]
        ]}
        text = f"📊 <b>Confirm CLOSE {symbol}</b>\nEntry: ${trade['entry_price']:.6f}\nCurrent: ${current_price:.6f}\nReturn: {ret:+.2f}%"
        if message_id:
            edit_message_text(text, chat_id, message_id, keyboard)
        else:
            send_telegram(text, chat_id, keyboard)

def send_portfolio(chat_id, message_id=None):
    st = get_portfolio_status()
    text = f"💰 <b>Portfolio</b>\nBalance: ${st['balance']:.2f}\nTotal PnL: ${st['total_pnl']:+.2f}\nReturn: {st['return_pct']:+.1f}%\nOpen: {st['open_trades']} | Closed: {st['closed_trades']}\nWin Rate: {st['win_rate']:.1f}%"
    keyboard = {"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "MAIN"}]]}
    if message_id:
        edit_message_text(text, chat_id, message_id, keyboard)
    else:
        send_telegram(text, chat_id, keyboard)

def send_status(chat_id, message_id=None):
    st = get_portfolio_status()
    uptime = (time.time() - start_time) / 3600
    text = f"📊 <b>Bot Status</b>\nUptime: {uptime:.1f}h\nBalance: ${st['balance']:.2f}\nTotal PnL: ${st['total_pnl']:+.2f}\nOpen Trades: {st['open_trades']}\nClosed Trades: {st['closed_trades']}\nWin Rate: {st['win_rate']:.1f}%\nDetected Coins: {len(detected_coins)}"
    keyboard = {"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "MAIN"}]]}
    if message_id:
        edit_message_text(text, chat_id, message_id, keyboard)
    else:
        send_telegram(text, chat_id, keyboard)

def export_csv(chat_id):
    save_detected_csv()
    save_trades_csv()
    save_portfolio_csv()
    files = [CSV_DETECTED, CSV_TRADES, CSV_PORTFOLIO]
    for file in files:
        if os.path.exists(file):
            with open(file, "rb") as f:
                data = f.read()
            boundary = "----WebKitFormBoundary" + str(time.time())
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{file}\"\r\n"
                    f"Content-Type: text/csv\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
            try:
                req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
                urllib.request.urlopen(req, timeout=30)
                time.sleep(1)
            except Exception as e:
                print(f"Error sending {file}: {e}")
    send_telegram("📁 CSV files sent.", chat_id)

# ================== CALLBACK HANDLER ==================
def handle_callback(callback):
    data = callback.get("data", "")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    msg_id = callback.get("message", {}).get("message_id")
    cb_id = callback.get("id")
    
    if data == "MAIN":
        send_main_menu(chat_id, msg_id)
    elif data == "SCAN":
        answer_callback(cb_id, "Scanning...")
        threading.Thread(target=scan_for_explosions, daemon=True).start()
        send_telegram("🔍 Scan started.", chat_id)
    elif data == "OPEN_MENU":
        send_open_menu(chat_id, msg_id)
    elif data == "CLOSE_MENU":
        send_close_menu(chat_id, msg_id)
    elif data == "PORTFOLIO":
        send_portfolio(chat_id, msg_id)
    elif data == "STATUS":
        send_status(chat_id, msg_id)
    elif data == "EXPORT":
        answer_callback(cb_id, "Exporting...")
        export_csv(chat_id)
    elif data.startswith("BUY_"):
        symbol = data[4:]
        send_confirmation(chat_id, "BUY", symbol, msg_id)
    elif data.startswith("CLOSE_"):
        symbol = data[6:]
        send_confirmation(chat_id, "CLOSE", symbol, msg_id)
    elif data == "CLOSE_ALL":
        close_all_trades()
        answer_callback(cb_id, "Closed all trades")
        send_close_menu(chat_id, msg_id)
    elif data.startswith("CONFIRM_BUY_"):
        symbol = data[12:]
        price = get_price(symbol)
        score = detected_coins.get(symbol, {}).get("score", 0)
        ok, res = open_trade(symbol, price, score)
        if ok:
            answer_callback(cb_id, f"Bought {symbol}")
            send_telegram(f"✅ Opened {symbol} at ${price:.6f}", chat_id)
        else:
            answer_callback(cb_id, f"Failed: {res}")
        send_open_menu(chat_id, msg_id)
    elif data.startswith("CONFIRM_CLOSE_"):
        symbol = data[14:]
        ok, res = close_trade(symbol, "BUTTON")
        if ok:
            answer_callback(cb_id, f"Closed {symbol}")
            send_telegram(f"✅ Closed {symbol} | Return: {res['final_return']:+.1f}% | Profit: ${res['profit_loss']:+.2f}", chat_id)
        else:
            answer_callback(cb_id, f"Failed: {res}")
        send_close_menu(chat_id, msg_id)
    else:
        answer_callback(cb_id, "Unknown command")

# ================== GET UPDATES ==================
def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    if offset:
        url += f"?offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except:
        return {"result": []}

def handle_telegram():
    global last_update_id
    while True:
        try:
            updates = get_updates(last_update_id + 1)
            for upd in updates.get("result", []):
                last_update_id = upd["update_id"]
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"])
                    continue
                msg = upd.get("message", {})
                text = msg.get("text", "").lower()
                chat = msg.get("chat", {}).get("id")
                if not chat:
                    continue
                if text == "/start" or text == "/menu":
                    send_main_menu(chat)
                elif text == "/explode":
                    if scanning:
                        send_telegram("Scan already in progress.", chat)
                    else:
                        threading.Thread(target=scan_for_explosions, daemon=True).start()
                        send_telegram("🔍 Scanning...", chat)
                elif text == "/portfolio":
                    send_portfolio(chat)
                elif text == "/status":
                    send_status(chat)
                elif text == "/export":
                    export_csv(chat)
                elif text.startswith("/buy"):
                    parts = text.split()
                    if len(parts) < 2:
                        send_telegram("Usage: /buy SYMBOL", chat)
                    else:
                        sym = parts[1].upper()
                        price = get_price(sym)
                        if price == 0:
                            send_telegram(f"❌ Cannot get price for {sym}", chat)
                        else:
                            score = detected_coins.get(sym, {}).get("score", 0)
                            ok, res = open_trade(sym, price, score)
                            if ok:
                                send_telegram(f"✅ Opened {sym} at ${price:.6f}", chat)
                            else:
                                send_telegram(f"❌ {res}", chat)
                elif text.startswith("/close"):
                    parts = text.split()
                    if len(parts) < 2:
                        send_telegram("Usage: /close SYMBOL", chat)
                    else:
                        sym = parts[1].upper()
                        ok, res = close_trade(sym, "USER")
                        if ok:
                            send_telegram(f"✅ Closed {sym} | Return: {res['final_return']:+.1f}% | Profit: ${res['profit_loss']:+.2f}", chat)
                        else:
                            send_telegram(f"❌ {res}", chat)
                elif text == "/closeall":
                    close_all_trades()
                    send_telegram("✅ Closed all trades.", chat)
                else:
                    if text:
                        send_telegram("Unknown command. Use /menu", chat)
            time.sleep(1)
        except Exception as e:
            print("Telegram loop error:", e)
            time.sleep(5)

# ================== MAIN ==================
if __name__ == "__main__":
    print("Starting bot...")
    web_thread = threading.Thread(target=start_web, daemon=True)
    web_thread.start()
    handle_telegram()
