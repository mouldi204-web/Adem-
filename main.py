#!/usr/bin/env python3
"""
Adem Trading Bot - Stable Version for Render
No external dependencies, only standard library.
"""

import os
import json
import time
import threading
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================== الإعدادات ==================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"

INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 20

# متغيرات البوت
balance = INITIAL_BALANCE
open_trades = {}
closed_trades = []
last_update_id = 0
scanning = False
detected_coins = {}   # تخزين العملات المكتشفة
start_time = time.time()

# ================== دوال مساعدة ==================
def send_telegram(text, chat_id=None):
    target = chat_id or CHAT_ID
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = json.dumps({"chat_id": target, "text": text, "parse_mode": "HTML"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}), timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

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

# ================== كشف الانفجارات ==================
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
                if not item["symbol"].endswith("USDT"): continue
                symbol = item["symbol"][:-4]
                change = float(item["priceChangePercent"])
                volume = float(item["quoteVolume"])
                price = float(item["lastPrice"])
                # حساب السكور
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
                            "score": score,
                            "status": "ACTIVE"
                        }
            # ترتيب وإرسال إشعارات
            explosions.sort(key=lambda x: x[3], reverse=True)
            for sym, price, ch, sc in explosions[:5]:
                send_telegram(f"💥 <b>{sym}</b>\nScore: {sc}/100 | Change: {ch:+.1f}%\nPrice: ${price:.6f}\n/buy {sym}")
            send_telegram(f"✅ Scan done. Found {len(explosions)} explosions.")
    except Exception as e:
        send_telegram(f"❌ Scan error: {str(e)[:100]}")
    finally:
        scanning = False

# ================== فتح وإغلاق الصفقات ==================
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
        "highest": price,
        "lowest": price,
        "status": "OPEN"
    }
    open_trades[symbol] = trade
    balance -= TRADE_AMOUNT
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
    return True, trade

def close_all_trades():
    for s in list(open_trades.keys()):
        close_trade(s, "CLOSE_ALL")

# ================== صفحة الويب ==================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        status = get_portfolio_status()
        uptime = (time.time() - start_time) / 3600
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Adem Trading Bot</title><meta http-equiv="refresh" content="30">
        <style>body{{background:#1a1a2e;color:#eee;font-family:Arial;text-align:center;padding:20px}}</style>
        </head>
        <body>
            <h1>🚀 Adem Trading Bot</h1>
            <p>Status: <span style="color:#4CAF50">✅ ONLINE</span> | Uptime: {uptime:.1f}h</p>
            <p>💰 Balance: ${status['balance']:.2f}</p>
            <p>📈 Total PnL: <span style="color:{'#4CAF50' if status['total_pnl']>=0 else '#ff6b6b'}">${status['total_pnl']:+.2f}</span></p>
            <p>🟢 Open Trades: {status['open_trades']} | 🔒 Closed: {status['closed_trades']}</p>
            <p>📊 Win Rate: {status['win_rate']:.1f}%</p>
            <hr>
            <p>💥 Detected coins: {len(detected_coins)}</p>
            <p>📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><small>Use Telegram commands: /explode, /buy SYMBOL, /close SYMBOL, /portfolio</small></p>
        </body>
        </html>
        """
        self.wfile.write(html.encode())
    def log_message(self, format, *args): pass

def start_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), WebHandler).serve_forever()

# ================== أوامر Telegram ==================
def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    if offset:
        url += f"?offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except:
        return {"result": []}

def handle_commands():
    global last_update_id, scanning
    while True:
        try:
            updates = get_updates(last_update_id + 1)
            for upd in updates.get("result", []):
                last_update_id = upd["update_id"]
                msg = upd.get("message", {})
                text = msg.get("text", "").lower()
                chat = msg.get("chat", {}).get("id")
                if not chat:
                    continue
                if text == "/start":
                    send_telegram("🤖 Bot started. Use /explode to scan, /buy SYMBOL to trade.", chat)
                elif text == "/explode":
                    if scanning:
                        send_telegram("Scan already in progress...", chat)
                    else:
                        threading.Thread(target=scan_for_explosions, daemon=True).start()
                        send_telegram("🔍 Scanning started...", chat)
                elif text.startswith("/buy"):
                    parts = text.split()
                    if len(parts) < 2:
                        send_telegram("Usage: /buy SYMBOL (e.g., /buy SOL)", chat)
                    else:
                        sym = parts[1].upper()
                        # البحث في آخر اكتشافات
                        price = get_price(sym)
                        if price == 0:
                            send_telegram(f"❌ Cannot get price for {sym}", chat)
                        else:
                            score = 0
                            for s, data in detected_coins.items():
                                if s == sym:
                                    score = data["score"]
                                    break
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
                elif text == "/portfolio":
                    st = get_portfolio_status()
                    msg = f"💰 Balance: ${st['balance']:.2f}\n📈 Total PnL: ${st['total_pnl']:+.2f}\n📊 Return: {st['return_pct']:+.1f}%\n🟢 Open: {st['open_trades']} | 🔒 Closed: {st['closed_trades']}\n✅ Win Rate: {st['win_rate']:.1f}%"
                    send_telegram(msg, chat)
                else:
                    if text:
                        send_telegram("Unknown command. Use /start", chat)
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ================== التشغيل الرئيسي ==================
if __name__ == "__main__":
    print("Starting bot...")
    # تشغيل خادم الويب في خيط منفصل
