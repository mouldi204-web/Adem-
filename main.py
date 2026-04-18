#!/usr/bin/env python3
"""
Gate.io Auto Trading Bot - Final Working Version
"""

import os
import time
import json
import threading
import urllib.request
import ccxt
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================== SETTINGS ==================
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"

INITIAL_BALANCE = 1000
MAX_OPEN_TRADES = 10
PROFIT_TARGETS = [3, 6, 10]
PROFIT_TARGET_PARTS = [0.4, 0.3, 0.3]
STOP_LOSS = -3
TRAILING_STOP_ACTIVATION = 2
TRAILING_STOP_DISTANCE = 1.5
BREAKEVEN_ACTIVATION = 2
MIN_SCORE_TO_TRADE = 75
COOLDOWN_HOURS = 24
DAILY_LOSS_LIMIT = 50
MAX_VOLATILITY = 12
ACTIVE_HOURS_START = 12
ACTIVE_HOURS_END = 20
USE_TESTNET = True

STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD']

# ================== SCANNER SETTINGS ==================
MAX_SYMBOLS = 1200
BATCH_SIZE = 100
BATCH_DELAY = 10
SYMBOL_DELAY = 0.2

PRECONDITIONS = {
    'min_price': 0.01,
    'min_volume': 1_000_000,
    'min_change': 1.0,
    'max_change': 30.0,
    'min_liquidity': 0.001,
}

# ================== GLOBALS ==================
balance = INITIAL_BALANCE
open_trades = {}
closed_trades = []
scanning = False
auto_traded_recently = {}
start_time = time.time()
trailing = {}
detected_coins = {}
coin_history = {}
daily_loss = 0
last_reset_date = datetime.now().date()
last_update_id = 0

exchange = ccxt.gateio({'enableRateLimit': True, 'rateLimit': 1200, 'options': {'defaultType': 'spot'}})
if USE_TESTNET:
    exchange.set_sandbox_mode(True)

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

# ================== DATA FETCHING ==================
def get_price(symbol):
    try:
        ticker = exchange.fetch_ticker(f"{symbol}/USDT")
        return ticker['last']
    except:
        return 0

def get_24h_data(symbol):
    try:
        ticker = exchange.fetch_ticker(f"{symbol}/USDT")
        return {
            'price': ticker['last'],
            'change': ticker.get('percentage', 0),
            'volume': ticker.get('quoteVolume', 0),
            'high': ticker.get('high', 0),
            'low': ticker.get('low', 0),
            'bid': ticker.get('bid', 0),
            'ask': ticker.get('ask', 0),
        }
    except:
        return None

def get_all_symbols():
    try:
        markets = exchange.load_markets()
        symbols = [s.replace('/USDT', '') for s in markets if s.endswith('/USDT')]
        return [s for s in symbols if s not in STABLE_COINS][:MAX_SYMBOLS]
    except:
        return []

def fetch_ohlcv(symbol, timeframe='1h', limit=100):
    try:
        return exchange.fetch_ohlcv(f"{symbol}/USDT", timeframe=timeframe, limit=limit)
    except:
        return []

# ================== TECHNICAL INDICATORS ==================
def calculate_rsi(ohlcv, period=14):
    closes = [c[4] for c in ohlcv]
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(ohlcv, fast=12, slow=26):
    closes = [c[4] for c in ohlcv]
    if len(closes) < slow:
        return 0, 0
    ema_fast = sum(closes[-fast:]) / fast
    ema_slow = sum(closes[-slow:]) / slow
    return ema_fast - ema_slow, 0

def calculate_bb_width(ohlcv, period=20):
    closes = [c[4] for c in ohlcv[-period:]]
    if len(closes) < period:
        return 0.1
    mean = sum(closes) / period
    variance = sum((x - mean) ** 2 for x in closes) / period
    std = variance ** 0.5
    return (mean + 2*std - (mean - 2*std)) / mean if mean != 0 else 0.1

def get_trend(ohlcv):
    if not ohlcv or len(ohlcv) < 50:
        return 0
    closes = [c[4] for c in ohlcv]
    ema20 = sum(closes[-20:]) / 20
    ema50 = sum(closes[-50:]) / 50
    if closes[-1] > ema20 > ema50:
        return 1
    elif closes[-1] < ema20 < ema50:
        return -1
    return 0

def get_support_resistance(ohlcv, current_price):
    if not ohlcv or len(ohlcv) < 50:
        return None, None
    highs = [c[2] for c in ohlcv[-50:]]
    lows = [c[3] for c in ohlcv[-50:]]
    supports = sorted([l for l in lows if l < current_price], reverse=True)
    resistances = sorted([h for h in highs if h > current_price])
    return supports[0] if supports else None, resistances[0] if resistances else None

def calculate_atr(ohlcv, period=14):
    if not ohlcv or len(ohlcv) < period+1:
        return 0
    tr_values = []
    for i in range(1, len(ohlcv)):
        high = ohlcv[i][2]
        low = ohlcv[i][3]
        prev_close = ohlcv[i-1][4]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
    return sum(tr_values[-period:]) / period

# ================== PRECISE ENTRY & TP/SL ==================
def calculate_precise_entry(current_price, ohlcv_1h, ohlcv_4h):
    support_1h, _ = get_support_resistance(ohlcv_1h, current_price)
    support_4h, _ = get_support_resistance(ohlcv_4h, current_price)
    supports = [s for s in [support_1h, support_4h] if s is not None and s < current_price]
    if supports:
        best_support = max(supports)
        if (current_price - best_support) / current_price < 0.01:
            entry = current_price
        else:
            entry = best_support
    else:
        entry = current_price
    return entry

def calculate_dynamic_tp_sl(entry_price, atr, support, resistance):
    sl_distance = min(1.5 * (atr / entry_price), 0.03)
    sl_price = entry_price * (1 - sl_distance)
    if support and support > sl_price:
        sl_price = support * 0.99
    if resistance and resistance > entry_price:
        tp1 = min(resistance, entry_price * 1.03)
    else:
        tp1 = entry_price * 1.03
    tp2 = entry_price * 1.06
    tp3 = entry_price * 1.10
    return [tp1, tp2, tp3], sl_price

# ================== SCORING (MULTI-TIMEFRAME) ==================
def calculate_score_mtf(ticker_data, ohlcv_15m, ohlcv_1h, ohlcv_4h, btc_change, coin_win_rate):
    score = 0
    price = ticker_data['price']
    change = ticker_data['change']
    volume = ticker_data['volume']
    high = ticker_data['high']
    low = ticker_data['low']

    if change > 10: score += 15
    elif change > 8: score += 12
    elif change > 6: score += 9
    elif change > 4: score += 6
    elif change > 2: score += 3
    elif change > 1: score += 1

    if volume > 200_000_000: score += 10
    elif volume > 100_000_000: score += 8
    elif volume > 50_000_000: score += 6
    elif volume > 20_000_000: score += 4
    elif volume > 10_000_000: score += 2

    if price < 0.05: score += 8
    elif price < 0.1: score += 6
    elif price < 0.5: score += 4
    elif price < 1: score += 2
    elif price < 2: score += 1

    if high > 0 and low > 0:
        volatility = ((high - low) / low) * 100
        if 5 <= volatility <= MAX_VOLATILITY:
            score += 5
        elif volatility > MAX_VOLATILITY:
            score -= 5

    if ohlcv_1h and len(ohlcv_1h) >= 20:
        volumes = [c[5] for c in ohlcv_1h[-21:-1]]
        avg_vol = sum(volumes) / len(volumes) if volumes else 1
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1
        if vol_ratio > 2: score += 5
        elif vol_ratio > 1.5: score += 3
        elif vol_ratio > 1.2: score += 1

    trend_15m = get_trend(ohlcv_15m)
    trend_1h = get_trend(ohlcv_1h)
    trend_4h = get_trend(ohlcv_4h)
    bullish_count = sum([1 for t in [trend_15m, trend_1h, trend_4h] if t == 1])
    if bullish_count >= 2: score += 10
    elif bullish_count == 1: score += 5

    if ohlcv_1h and len(ohlcv_1h) >= 15:
        rsi = calculate_rsi(ohlcv_1h)
        if 30 <= rsi <= 50: score += 5
        elif rsi > 70: score -= 5

    if ohlcv_1h and len(ohlcv_1h) >= 26:
        macd, _ = calculate_macd(ohlcv_1h)
        if macd > 0: score += 5

    if ohlcv_1h and len(ohlcv_1h) >= 20:
        if calculate_bb_width(ohlcv_1h) < 0.05: score += 3

    if coin_win_rate is not None:
        if coin_win_rate > 70: score += 4
        elif coin_win_rate > 60: score += 2
        elif coin_win_rate > 50: score += 1

    if btc_change is not None:
        if btc_change < -2: score = score * 0.7
        elif btc_change > 2: score = score * 1.1

    hour = datetime.now().hour
    if hour < ACTIVE_HOURS_START or hour > ACTIVE_HOURS_END:
        score = score * 0.8

    return max(0, min(100, int(score)))

# ================== TRADING LOGIC ==================
def get_position_size(score, volatility=None):
    base = 50
    if score >= 90: size = base * 1.5
    elif score >= 75: size = base
    else: size = base * 0.5
    if volatility and volatility > 8: size *= 0.7
    return max(20, min(100, size))

def check_daily_loss():
    global daily_loss, last_reset_date
    today = datetime.now().date()
    if today != last_reset_date:
        daily_loss = 0
        last_reset_date = today
    return daily_loss < DAILY_LOSS_LIMIT

def can_open():
    return len(open_trades) < MAX_OPEN_TRADES and balance >= 20 and check_daily_loss()

def is_tradable(symbol):
    if symbol in open_trades: return False
    if symbol in auto_traded_recently:
        last = auto_traded_recently[symbol]
        if (datetime.now() - last).total_seconds() < COOLDOWN_HOURS * 3600:
            return False
    return True

def open_trade(symbol, price, score, volatility, tp_levels, sl_price):
    global balance
    if not can_open(): return False
    if not is_tradable(symbol): return False
    size = get_position_size(score, volatility)
    qty = size / price
    trade = {
        "symbol": symbol,
        "entry_price": price,
        "entry_time": datetime.now(),
        "amount": size,
        "quantity": qty,
        "score": score,
        "highest": price,
        "status": "OPEN",
        "targets_hit": 0,
        "breakeven_activated": False,
        "tp_levels": tp_levels,
        "sl_price": sl_price
    }
    open_trades[symbol] = trade
    balance -= size
    auto_traded_recently[symbol] = datetime.now()
    send_telegram(f"✅ AUTO BUY {symbol} | Score {score} | Entry ${price:.6f} | Size ${size:.0f} | TP: {tp_levels[0]:.6f}, {tp_levels[1]:.6f}, {tp_levels[2]:.6f} | SL: ${sl_price:.6f}")
    return True

def close_trade(symbol, reason, close_percent=1.0):
    global balance, daily_loss
    if symbol not in open_trades: return
    trade = open_trades[symbol]
    cur = get_price(symbol)
    if cur == 0: return
    ret = ((cur - trade['entry_price']) / trade['entry_price']) * 100
    closed_amount = trade['amount'] * close_percent
    closed_qty = trade['quantity'] * close_percent
    pnl = (cur - trade['entry_price']) * closed_qty
    trade['amount'] -= closed_amount
    trade['quantity'] -= closed_qty
    closed_trades.append({
        "symbol": symbol, "entry_price": trade['entry_price'], "entry_time": trade['entry_time'],
        "exit_price": cur, "exit_time": datetime.now(), "final_return": ret, "profit_loss": pnl,
        "exit_reason": reason, "amount": closed_amount, "score": trade['score']
    })
    balance += closed_amount + pnl
    if pnl < 0: daily_loss += abs(pnl)
    if trade['amount'] <= 0:
        del open_trades[symbol]
        if symbol in trailing: del trailing[symbol]
    return True

def monitor_trades():
    for sym in list(open_trades.keys()):
        cur = get_price(sym)
        if cur == 0: continue
        trade = open_trades[sym]
        ret = ((cur - trade['entry_price']) / trade['entry_price']) * 100
        if cur > trade['highest']: trade['highest'] = cur

        if cur <= trade['sl_price']:
            close_trade(sym, "SL", 1.0)
            send_telegram(f"❌ SL {sym} | Return: {ret:+.2f}%")
            continue

        if not trade.get('breakeven_activated') and ret >= BREAKEVEN_ACTIVATION:
            trade['breakeven_activated'] = True
            send_telegram(f"🔒 Breakeven activated for {sym}")

        for i, tp in enumerate(trade['tp_levels']):
            if trade.get('targets_hit', 0) <= i and cur >= tp:
                close_percent = PROFIT_TARGET_PARTS[i]
                close_trade(sym, f"TP_{PROFIT_TARGETS[i]}%", close_percent)
                trade['targets_hit'] = i+1
                send_telegram(f"✅ TP {PROFIT_TARGETS[i]}% hit for {sym} | Closed {close_percent*100:.0f}%")
                break

        if sym in open_trades:
            trade = open_trades[sym]
            if sym not in trailing:
                if ret >= TRAILING_STOP_ACTIVATION:
                    trailing[sym] = cur * (1 - TRAILING_STOP_DISTANCE / 100)
                    send_telegram(f"🔒 Trailing active {sym} at ${trailing[sym]:.6f}")
            else:
                if cur <= trailing[sym]:
                    close_trade(sym, "TRAILING", 1.0)
                    send_telegram(f"📉 Trailing closed {sym} | Return: {ret:+.2f}%")
                elif cur > trade['highest']:
                    trailing[sym] = cur * (1 - TRAILING_STOP_DISTANCE / 100)

# ================== SCAN PIPELINE ==================
def passes_prefilter(symbol, ticker_data):
    price = ticker_data['price']
    change = ticker_data['change']
    volume = ticker_data['volume']
    bid = ticker_data.get('bid', price)
    ask = ticker_data.get('ask', price)

    if price < PRECONDITIONS['min_price']:
        return False, f"price {price:.4f} < {PRECONDITIONS['min_price']}"
    if volume < PRECONDITIONS['min_volume']:
        return False, f"volume {volume/1e6:.1f}M < {PRECONDITIONS['min_volume']/1e6}M"
    if change < PRECONDITIONS['min_change']:
        return False, f"change {change:.1f}% < {PRECONDITIONS['min_change']}%"
    if change > PRECONDITIONS['max_change']:
        return False, f"change {change:.1f}% > {PRECONDITIONS['max_change']}%"
    if bid > 0 and ask > 0:
        spread = (ask - bid) / bid
        if spread > PRECONDITIONS['min_liquidity']:
            return False, f"spread {spread:.2%} > {PRECONDITIONS['min_liquidity']:.1%}"
    return True, "OK"

def scan_and_trade():
    global scanning, detected_coins
    if not check_daily_loss():
        send_telegram("Daily loss limit reached. Auto-trading paused.")
        return
    scanning = True
    send_telegram("🔍 Scanning 1200 symbols with filtering pipeline...")
    try:
        all_symbols = get_all_symbols()
        if not all_symbols:
            send_telegram("Failed to fetch symbols.")
            scanning = False
            return
        btc_data = get_24h_data('BTC')
        btc_change = btc_data['change'] if btc_data else 0
        candidates = []
        total_batches = (len(all_symbols) + BATCH_SIZE - 1) // BATCH_SIZE
        processed = 0

        for batch_start in range(0, len(all_symbols), BATCH_SIZE):
            batch = all_symbols[batch_start:batch_start+BATCH_SIZE]
            for symbol in batch:
                try:
                    ticker_data = get_24h_data(symbol)
                    if not ticker_data: continue
                    passed, _ = passes_prefilter(symbol, ticker_data)
                    if not passed: continue
                    ohlcv_15m = fetch_ohlcv(symbol, '15m', 100)
                    ohlcv_1h = fetch_ohlcv(symbol, '1h', 100)
                    ohlcv_4h = fetch_ohlcv(symbol, '4h', 100)
                    if not ohlcv_1h or len(ohlcv_1h) < 50: continue
                    win_rate = coin_history.get(symbol, {}).get('win_rate', 50)
                    score = calculate_score_mtf(ticker_data, ohlcv_15m, ohlcv_1h, ohlcv_4h, btc_change, win_rate)
                    if score >= MIN_SCORE_TO_TRADE:
                        entry_price = calculate_precise_entry(ticker_data['price'], ohlcv_1h, ohlcv_4h)
                        atr = calculate_atr(ohlcv_1h)
                        support, resistance = get_support_resistance(ohlcv_1h, entry_price)
                        tp_levels, sl_price = calculate_dynamic_tp_sl(entry_price, atr, support, resistance)
                        volatility = ((ticker_data['high'] - ticker_data['low']) / ticker_data['low']) * 100 if ticker_data['low']>0 else 0
                        candidates.append((symbol, entry_price, score, volatility, tp_levels, sl_price))
                        if symbol not in detected_coins or score > detected_coins[symbol].get('best_score',0):
                            detected_coins[symbol] = {"best_score": score, "best_price": entry_price}
                    processed += 1
                    time.sleep(SYMBOL_DELAY)
                except Exception as e:
                    print(f"Error scanning {symbol}: {e}")
                    continue
            if batch_start + BATCH_SIZE < len(all_symbols):
                time.sleep(BATCH_DELAY)
            send_telegram(f"📊 Batch {batch_start//BATCH_SIZE +1}/{total_batches} | Processed {processed}/{len(all_symbols)} | Candidates: {len(candidates)}")

        candidates.sort(key=lambda x: x[2], reverse=True)
        if candidates:
            msg = "📊 Top candidates:\n"
            for c in candidates[:5]:
                msg += f"{c[0]} | Score {c[2]} | Entry ${c[1]:.6f}\n"
            send_telegram(msg)
            for sym, entry, score, vol, tp_lev, sl in candidates[:3]:
                if can_open() and is_tradable(sym):
                    open_trade(sym, entry, score, vol, tp_lev, sl)
        else:
            send_telegram("No candidates passed all filters.")
    except Exception as e:
        send_telegram(f"Scan error: {str(e)[:200]}")
    finally:
        scanning = False

# ================== AUTO LOOPS ==================
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
        monitor_trades()
        time.sleep(30)

# ================== WEB DASHBOARD ==================
def get_portfolio_status():
    total_value = balance
    for trade in open_trades.values():
        price = get_price(trade['symbol'])
        if price > 0:
            total_value += trade['quantity'] * price
    realized_pnl = sum(t.get('profit_loss', 0) for t in closed_trades)
    total_pnl = realized_pnl
    winning = sum(1 for t in closed_trades if t.get('final_return', 0) > 0)
    win_rate = (winning / len(closed_trades) * 100) if closed_trades else 0
    return {
        'balance': balance, 'total_value': total_value, 'total_pnl': total_pnl,
        'return_pct': (total_pnl / INITIAL_BALANCE) * 100, 'open_trades': len(open_trades),
        'closed_trades': len(closed_trades), 'win_rate': win_rate,
        'daily_loss': daily_loss, 'daily_limit': DAILY_LOSS_LIMIT
    }

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        status = get_portfolio_status()
        uptime = (time.time() - start_time) / 3600
        html = f"""
        <html><head><title>Gate.io Pro Bot</title><meta http-equiv="refresh" content="30"></head>
        <body style="background:#1a1a2e;color:#eee;font-family:Segoe UI;text-align:center;padding:20px">
        <h1>🚀 Gate.io Pro Bot</h1>
        <p>Status: ✅ ONLINE | Uptime: {uptime:.1f}h</p>
        <p>💰 Balance: ${status['balance']:.2f} | 📈 Total PnL: ${status['total_pnl']:+.2f}</p>
        <p>🟢 Open: {status['open_trades']} | 🔒 Closed: {status['closed_trades']} | 📊 Win Rate: {status['win_rate']:.1f}%</p>
        <p>⚠️ Daily Loss: ${status['daily_loss']:.2f} / ${DAILY_LOSS_LIMIT}</p>
        <p>📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <hr><p>🤖 Auto-scan every 15 min | Multi-TF | Dynamic entry & TP/SL</p>
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
    if offset: url += f"?offset={offset}"
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
            for upd in updates.get('result', []):
                last_update_id = upd['update_id']
                msg = upd.get('message', {})
                text = msg.get('text', '').lower()
                chat = msg.get('chat', {}).get('id')
                if not chat: continue
                if text == '/start':
                    send_telegram("🤖 Gate.io Pro Bot started.\n/status - Info\n/scan - Manual scan\n/portfolio - Details\n/closeall - Close all\n/help", chat)
                elif text == '/status':
                    st = get_portfolio_status()
                    send_telegram(f"💰 Balance: ${st['balance']:.2f}\n📈 Total PnL: ${st['total_pnl']:+.2f}\n🟢 Open: {st['open_trades']}\n🔒 Closed: {st['closed_trades']}\n📊 Win rate: {st['win_rate']:.1f}%\n⚠️ Daily loss: ${st['daily_loss']:.2f}", chat)
                elif text == '/scan':
                    if scanning: send_telegram("Scan already running.", chat)
                    else:
                        send_telegram("Manual scan started.", chat)
                        threading.Thread(target=scan_and_trade, daemon=True).start()
                elif text == '/portfolio':
                    st = get_portfolio_status()
                    msg = f"💰 Balance: ${st['balance']:.2f}\n\n🟢 Open trades:\n"
                    for sym, trade in open_trades.items():
                        cur = get_price(sym)
                        ret = ((cur - trade['entry_price']) / trade['entry_price']) * 100 if cur else 0
                        msg += f"{sym}: {ret:+.1f}% (${trade['entry_price']:.4f})\n"
                    if not open_trades: msg += "No open trades.\n"
                    send_telegram(msg, chat)
                elif text == '/closeall':
                    count = len(open_trades)
                    for sym in list(open_trades.keys()):
                        close_trade(sym, "MANUAL", 1.0)
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
    print("=" * 60)
    print("🚀 GATE.IO PRO BOT STARTED")
    print(f"Mode: {'TESTNET' if USE_TESTNET else 'LIVE'}")
    print(f"Initial balance: ${INITIAL_BALANCE}")
    print("=" * 60)

    threading.Thread(target=start_web, daemon=True).start()
    threading.Thread(target=auto_scan_loop, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    handle_commands()
