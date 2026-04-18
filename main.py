#!/usr/bin/env python3
import os
import time
import json
import threading
import csv
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

# ============================================
# الإعدادات
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

MAX_SYMBOLS = 500
SCAN_INTERVAL = 300
EXPLOSION_THRESHOLD = 70
HIGH_EXPLOSION_THRESHOLD = 85

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

TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
TOP10_FILE = "top10.csv"
EXPLOSIONS_FILE = "explosions.csv"

# ============================================
# خادم HTTP لـ Keep-Alive
# ============================================

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
            <h1>🚀 Binance Trading Bot</h1>
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

# ============================================
# دوال التداول
# ============================================

def get_price(symbol):
    """الحصول على السعر من Binance API (بدون CCXT)"""
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            return float(data['price'])
    except Exception as e:
        print(f"Price error for {symbol}: {e}")
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

# ============================================
# المسح الضوئي (بدون CCXT - باستخدام Binance API مباشرة)
# ============================================

def get_all_tickers():
    """جلب جميع الأسعار من Binance"""
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
                            'volume': float(item['quoteVolume'])
                        }
            return prices
    except Exception as e:
        print(f"Ticker error: {e}")
        return {}

def scan_market_sync():
    global scanning, explosions_found, last_scan_result
    scanning = True
    send_msg("💥 <b>جاري مسح الانفجارات...</b>\n⏱️ يرجى الانتظار 20-30 ثانية")
    
    try:
        prices = get_all_tickers()
        explosions = []
        
        for symbol, data in prices.items():
            # حساب سكور بسيط
            score = 0
            if data['change'] > 5:
                score += 40
            elif data['change'] > 3:
                score += 25
            elif data['change'] > 1:
                score += 15
            
            if data['volume'] > 50000000:
                score += 30
            elif data['volume'] > 10000000:
                score += 20
            
            if score >= EXPLOSION_THRESHOLD:
                explosions.append({
                    'symbol': symbol,
                    'price': data['price'],
                    'change': data['change'],
                    'explosion': {
                        'score': score,
                        'expected_rise': round(5 + (score / 100) * 15, 1),
                        'time_to_explode': 30,
                        'explosion_type': "🔥 انفجار حجم + سعر" if score > 80 else "📊 انفجار حجم",
                        'signals': ["🔥 حجم كبير", "🚀 ارتفاع سعري"]
                    }
                })
        
        explosions.sort(key=lambda x: x['explosion']['score'], reverse=True)
        explosions_found = explosions[:10]
        last_scan_result = explosions_found
        
        # حفظ النتائج
        with open(EXPLOSIONS_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Time', 'Symbol', 'Score', 'Expected_Rise%', 'Price', 'Change%'])
            for exp in explosions_found:
                writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exp['symbol'],
                               exp['explosion']['score'], exp['explosion']['expected_rise'],
                               exp['price'], f"{exp['change']:.2f}"])
        
        # إرسال الإشعارات
        for exp in explosions_found[:3]:
            explosion = exp['explosion']
            send_msg(f"""
💥 <b>تنبيه انفجار وشيك!</b>

┌ 📊 <b>{exp['symbol']}</b>
├ 💥 درجة الانفجار: {explosion['score']}/100
├ 📈 الصعود المتوقع: +{explosion['expected_rise']}%
├ ⏰ الوقت المتوقع: {explosion['time_to_explode']} دقيقة
│
└ 🚨 <b>فرصة استثنائية!</b>

💡 /buy {exp['symbol']}
            """)
        
        send_msg(f"✅ اكتمل المسح! تم العثور على {len(explosions_found)} انفجار وشيك")
        scanning = False
        
    except Exception as e:
        send_msg(f"❌ خطأ في المسح: {str(e)[:100]}")
        print(f"Scan error: {e}")
        scanning = False

# ============================================
# عرض الصفقات مع أزرار
# ============================================

def show_open_trades(chat_id, message_id=None):
    if not open_trades:
        msg = "📊 <b>لا توجد صفقات مفتوحة</b>"
        send_msg(msg, chat_id)
        return
    
    keyboard = []
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            keyboard.append([{'text': f"{emoji} {symbol} | {pnl:+.1f}%", 'callback_data': f"CLOSE_{symbol}"}])
    
    keyboard.append([{'text': "🔴 إغلاق الجميع", 'callback_data': "CLOSE_ALL"}])
    keyboard.append([{'text': "🔙 القائمة الرئيسية", 'callback_data': "MAIN_MENU"}])
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
    
    msg = f"📊 <b>الصفقات المفتوحة ({len(open_trades)}/{MAX_OPEN_TRADES})</b>{trades_text}\n\n💰 <b>إجمالي PnL:</b> ${total_pnl:+.2f}\n\n💡 <b>اضغط على صفقة لإغلاقها</b>"
    send_msg(msg, chat_id, reply_markup=reply_markup)

def show_explosions_with_buttons(chat_id, message_id=None):
    if not explosions_found:
        msg = "💥 <b>لا توجد انفجارات حالياً</b>\nاستخدم /explode للمسح"
        send_msg(msg, chat_id)
        return
    
    keyboard = []
    for exp in explosions_found[:10]:
        explosion = exp['explosion']
        keyboard.append([{'text': f"💥 {exp['symbol']} | درجة {explosion['score']} | +{explosion['expected_rise']}%", 
                         'callback_data': f"BUY_{exp['symbol']}"}])
    
    keyboard.append([{'text': "🔄 تحديث", 'callback_data': "REFRESH_EXPLOSIONS"}])
    keyboard.append([{'text': "🔙 القائمة الرئيسية", 'callback_data': "MAIN_MENU"}])
    reply_markup = {'inline_keyboard': keyboard}
    
    msg = "💥 <b>العملات المرشحة للانفجار</b>\n\n"
    for i, exp in enumerate(explosions_found[:10], 1):
        explosion = exp['explosion']
        msg += f"{i}. <b>{exp['symbol']}</b>\n"
        msg += f"   💥 درجة: {explosion['score']}/100\n"
        msg += f"   📈 صعود متوقع: +{explosion['expected_rise']}%\n"
        msg += f"   💰 السعر: ${exp['price']:.6f}\n\n"
    
    msg += "💡 <b>اضغط على عملة لفتح صفقة</b>"
    send_msg(msg, chat_id, reply_markup=reply_markup)

def show_main_menu(chat_id, message_id=None):
    status = get_portfolio_status()
    
    keyboard = [
        [{'text': "💥 كشف الانفجارات", 'callback_data': "SHOW_EXPLOSIONS"}],
        [{'text': "📊 مسح السوق", 'callback_data': "SCAN_MARKET"}],
        [{'text': "🟢 الصفقات المفتوحة", 'callback_data': "SHOW_OPEN_TRADES"}],
        [{'text': "💰 حالة المحفظة", 'callback_data': "SHOW_PORTFOLIO"}],
        [{'text': "📁 تحميل CSV", 'callback_data': "EXPORT_CSV"}]
    ]
    reply_markup = {'inline_keyboard': keyboard}
    
    msg = f"""
🤖 <b>Adem Trading Bot</b>

💰 <b>المحفظة:</b>
├ الرصيد: ${status['balance']:.2f}
├ إجمالي الربح: ${status['total_pnl']:+.2f}
├ العائد: {status['total_return_pct']:+.1f}%

📊 <b>الصفقات:</b>
├ مفتوحة: {status['open_trades']}/{MAX_OPEN_TRADES}
├ مغلقة: {status['closed_trades']}
├ نسبة الربح: {status['win_rate']:.1f}%

💥 <b>الانفجارات:</b>
├ مكتشفة: {len(explosions_found)}

⏰ {datetime.now().strftime('%H:%M:%S')}

💡 <b>اختر أحد الخيارات:</b>
"""
    send_msg(msg, chat_id, reply_markup=reply_markup)

def show_portfolio(chat_id, message_id=None):
    status = get_portfolio_status()
    msg = f"""
💰 <b>تفاصيل المحفظة</b>

💵 الرصيد: ${status['balance']:.2f}
📈 القيمة الإجمالية: ${status['total_value']:.2f}
💰 إجمالي الربح: ${status['total_pnl']:+.2f}
📊 العائد: {status['total_return_pct']:+.1f}%

🟢 <b>الصفقات المفتوحة ({status['open_trades']}):</b>
"""
    if open_trades:
        for symbol, trade in open_trades.items():
            current_price = get_price(symbol)
            if current_price > 0:
                pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
                msg += f"\n• {symbol}: {pnl:+.1f}% (دخل ${trade['entry_price']:.4f})"
    else:
        msg += "\nلا توجد صفقات مفتوحة"
    
    msg += f"\n\n✅ الصفقات المغلقة: {status['closed_trades']}"
    msg += f"\n📊 نسبة الربح: {status['win_rate']:.1f}%"
    
    keyboard = [[{'text': "🔙 القائمة الرئيسية", 'callback_data': "MAIN_MENU"}]]
    send_msg(msg, chat_id, reply_markup={'inline_keyboard': keyboard})

def export_csv_files(chat_id):
    files = [EXPLOSIONS_FILE, TRADES_FILE, PORTFOLIO_FILE, TOP10_FILE]
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
        send_msg("📁 تم إرسال ملفات CSV", chat_id)
    else:
        send_msg("⚠️ لا توجد ملفات CSV للإرسال", chat_id)

# ============================================
# معالجة الأزرار والأوامر
# ============================================

def handle_callback_query(callback):
    data = callback.get('data', '')
    chat_id = callback.get('message', {}).get('chat', {}).get('id')
    message_id = callback.get('message', {}).get('message_id')
    callback_id = callback.get('id')
    
    if data.startswith('CLOSE_'):
        symbol = data.replace('CLOSE_', '')
        success, result = close_trade(symbol, "BUTTON")
        answer_callback_query(callback_id, f"✅ تم إغلاق {symbol}" if success else f"❌ {result}")
        show_open_trades(chat_id, message_id)
    
    elif data == 'CLOSE_ALL':
        closed = close_all_trades()
        answer_callback_query(callback_id, f"✅ تم إغلاق {len(closed)} صفقة")
        show_open_trades(chat_id, message_id)
    
    elif data.startswith('BUY_'):
        symbol = data.replace('BUY_', '')
        found = None
        for exp in explosions_found:
            if exp['symbol'] == symbol:
                found = exp
                break
        if found:
            success, trade = open_trade(symbol, found['price'], found['explosion']['score'], found['explosion']['signals'])
            answer_callback_query(callback_id, f"✅ تم فتح {symbol}" if success else f"❌ {trade}")
        else:
            answer_callback_query(callback_id, "❌ العملة غير موجودة")
    
    elif data == 'SHOW_EXPLOSIONS':
        show_explosions_with_buttons(chat_id, message_id)
    
    elif data == 'REFRESH_EXPLOSIONS':
        show_explosions_with_buttons(chat_id, message_id)
    
    elif data == 'SCAN_MARKET':
        answer_callback_query(callback_id, "🔄 جاري المسح...")
        threading.Thread(target=scan_market_sync, daemon=True).start()
    
    elif data == 'SHOW_OPEN_TRADES':
        show_open_trades(chat_id, message_id)
    
    elif data == 'SHOW_PORTFOLIO':
        show_portfolio(chat_id, message_id)
    
    elif data == 'EXPORT_CSV':
        answer_callback_query(callback_id, "📁 جاري الإرسال...")
        export_csv_files(chat_id)
    
    elif data == 'MAIN_MENU':
        show_main_menu(chat_id, message_id)

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
                    show_main_menu(user_id)
                
                elif text == '/menu':
                    show_main_menu(user_id)
                
                elif text == '/explode':
                    if scanning:
                        send_msg("⚠️ جاري المسح حالياً", user_id)
                    else:
                        threading.Thread(target=scan_market_sync, daemon=True).start()
                        send_msg("🔍 جاري مسح الانفجارات...", user_id)
                
                elif text == '/trades':
                    show_open_trades(user_id)
                
                elif text == '/portfolio':
                    show_portfolio(user_id)
                
                elif text == '/closeall':
                    closed = close_all_trades()
                    send_msg(f"✅ تم إغلاق {len(closed)} صفقة", user_id)
                
                elif text.startswith('/close'):
                    parts = text.split()
                    if len(parts) > 1:
                        symbol = parts[1].upper()
                        success, result = close_trade(symbol, "COMMAND")
                        if success:
                            emoji = "✅" if result['final_return'] >= 0 else "❌"
                            send_msg(f"{emoji} تم إغلاق {symbol}\nالعائد: {result['final_return']:+.1f}%", user_id)
                        else:
                            send_msg(f"❌ {result}", user_id)
                    else:
                        send_msg("⚠️ /close SYMBOL\nمثال: /close SOL", user_id)
                
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
                            success, trade = open_trade(symbol, found['price'], found['explosion']['score'], found['explosion']['signals'])
                            if success:
                                send_msg(f"✅ تم فتح {symbol}\n💰 السعر: ${found['price']:.4f}\n💥 درجة الانفجار: {found['explosion']['score']}/100", user_id)
                            else:
                                send_msg(f"❌ {trade}", user_id)
                        else:
                            send_msg(f"❌ {symbol} غير موجود\nاستخدم /explode أولاً", user_id)
                    else:
                        send_msg("⚠️ /buy SYMBOL\nمثال: /buy SOL", user_id)
                
                elif text == '/export':
                    export_csv_files(user_id)
                
                elif text == '/status':
                    status = get_portfolio_status()
                    send_msg(f"""
📊 <b>حالة البوت</b>

💰 الرصيد: ${status['balance']:.2f}
📈 إجمالي الربح: ${status['total_pnl']:+.2f}
📊 العائد: {status['total_return_pct']:+.1f}%
🟢 صفقات مفتوحة: {status['open_trades']}
✅ صفقات مغلقة: {status['closed_trades']}
📈 نسبة الربح: {status['win_rate']:.1f}%
💥 انفجارات مكتشفة: {len(explosions_found)}

⏰ {datetime.now().strftime('%H:%M:%S')}
                    """, user_id)
                
                elif text == '/ping':
                    send_msg("🏓 Pong! البوت يعمل", user_id)
                
                else:
                    if text and not text.startswith('/'):
                        send_msg(f"❓ أمر غير معروف: {text}\nاستخدم /start", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 STARTING BINANCE TRADING BOT")
    print("=" * 60)
    print(f"Time: {datetime.now()}")
    print(f"Balance: ${INITIAL_BALANCE}")
    print(f"Max trades: {MAX_OPEN_TRADES}")
    print("=" * 60)
    
    # تشغيل خادم Keep-Alive
    keep_alive_thread = threading.Thread(target=start_keep_alive, daemon=True)
    keep_alive_thread.start()
    print("✅ Keep-alive server started")
    
    # إرسال رسالة البدء
    send_msg("🚀 <b>Trading Bot Started!</b>\n\n✅ 24/7 operation\n✅ Auto-scan every 5 minutes\n✅ Explosion detection active\n\n💡 Use /menu to start")
    
    # تشغيل معالجة الأوامر
    handle_commands()
