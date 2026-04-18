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

# Telegram Settings
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"
CHANNEL_ID = "1001003692815602"

# Trading Settings
INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 20
PROFIT_TARGET = 5
STOP_LOSS = -3
TRAILING_STOP_ACTIVATION = 2
TRAILING_STOP_DISTANCE = 1.5

# Scanner Settings
MIN_DAILY_VOLATILITY = 4.0  # أقل حركة مقبولة 4%

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

# ملفات CSV
TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
TOP10_FILE = "top10.csv"

# ============================================
# دوال مساعدة
# ============================================

def send_msg(text, chat_id=None, parse_mode='HTML'):
    """إرسال رسالة إلى Telegram"""
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
    """إرسال إلى القناة"""
    return send_msg(text, CHANNEL_ID)

def get_price(symbol='BTC'):
    """الحصول على سعر العملة"""
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
    """الحصول على أسعار جميع العملات"""
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
    """حساب متوسط الحركة اليومية"""
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
    """التحقق من استبعاد العملة"""
    if symbol.upper() in [s.upper() for s in STABLE_COINS]:
        return True, "stable_coin"
    if symbol.upper() in [s.upper() for s in SLOW_LARGE_COINS]:
        return True, "slow_large"
    return False, ""

def calculate_score(symbol, data):
    """حساب السكور"""
    # استبعاد العملات البطيئة
    excluded, reason = is_excluded_symbol(symbol)
    if excluded:
        return 0, [f"🚫 مستبعد: {reason}"]
    
    # التحقق من الحركة
    volatility = calculate_volatility(symbol)
    if volatility < MIN_DAILY_VOLATILITY and volatility > 0:
        return 0, [f"🐢 حركة ضعيفة ({volatility:.1f}%)"]
    
    score = 0
    reasons = []
    
    # التغير السعري
    if data['change'] > 8:
        score += 30
        reasons.append(f"🚀 انفجار +{data['change']:.1f}%")
    elif data['change'] > 5:
        score += 25
        reasons.append(f"📈 قفزة +{data['change']:.1f}%")
    elif data['change'] > 3:
        score += 15
        reasons.append(f"✅ ارتفاع +{data['change']:.1f}%")
    elif data['change'] > 1:
        score += 10
        reasons.append(f"📊 بداية ارتفاع +{data['change']:.1f}%")
    
    # حجم التداول
    if data['volume'] > 5000000:
        score += 30
        reasons.append("📊 حجم كبير جداً")
    elif data['volume'] > 1000000:
        score += 20
        reasons.append("📊 حجم جيد")
    elif data['volume'] > 500000:
        score += 10
        reasons.append("📊 حجم متوسط")
    
    # الحركة
    if volatility > 10:
        score += 15
        reasons.append(f"⚡ تقلب عال {volatility:.0f}%")
    elif volatility > 7:
        score += 10
        reasons.append(f"🌊 تقلب جيد {volatility:.0f}%")
    
    # السعر
    if data['price'] < 0.5:
        score += 10
        reasons.append(f"💰 سعر منخفض ${data['price']:.4f}")
    elif data['price'] < 2:
        score += 5
        reasons.append(f"💵 سعر مناسب ${data['price']:.4f}")
    
    return min(score, 100), reasons

# ============================================
# المسح الضوئي
# ============================================

def scan_top10():
    """مسح السوق وجلب أفضل 10 عملات"""
    global scanning, last_scan_result
    
    scanning = True
    send_msg("🔍 <b>جاري مسح السوق...</b>\n⏱️ يرجى الانتظار 30-60 ثانية")
    
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
        
        # حفظ النتائج
        save_top10_csv(last_scan_result)
        
        # عرض النتائج
        show_top10_results()
        
        scanning = False
        return last_scan_result
        
    except Exception as e:
        send_msg(f"⚠️ خطأ في المسح: {str(e)[:100]}")
        scanning = False
        return []

def show_top10_results():
    """عرض نتائج المسح"""
    if not last_scan_result:
        send_msg("📊 لا توجد نتائج. استخدم /scan أولاً")
        return
    
    message = "🏆 <b>أفضل العملات (مستبعدة العملات البطيئة)</b>\n\n"
    message += f"📊 تم استبعاد العملات التي تتحرك أقل من {MIN_DAILY_VOLATILITY}% يومياً\n"
    message += f"🚫 تم استبعاد العملات المستقرة\n\n"
    
    for i, item in enumerate(last_scan_result[:10], 1):
        change_emoji = "🟢" if item['change'] > 0 else "🔴"
        message += f"{i}. {change_emoji} <b>{item['symbol']}</b>\n"
        message += f"   📊 سكور: {item['score']} | حركة: {item['volatility']:.1f}%\n"
        message += f"   💰 السعر: ${item['price']:.4f} | تغير: {item['change']:+.1f}%\n"
        message += f"   📈 {', '.join(item['reasons'][:2])}\n\n"
    
    message += "\n💡 <b>لفتح صفقة:</b> أرسل /buy [الرمز]\n"
    message += "مثال: /buy SOL"
    
    send_msg(message)

def save_top10_csv(results):
    """حفظ النتائج في CSV"""
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
    """فتح صفقة شراء"""
    global balance, open_trades
    
    if len(open_trades) >= MAX_OPEN_TRADES:
        return False, f"الحد الأقصى للصفقات ({MAX_OPEN_TRADES})"
    
    if balance < TRADE_AMOUNT:
        return False, f"الرصيد غير كاف (${balance:.2f})"
    
    # التحقق من وجود الصفقة بالفعل
    if symbol in open_trades:
        return False, f"صفقة {symbol} مفتوحة بالفعل"
    
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
    """إغلاق صفقة"""
    global balance, open_trades, closed_trades
    
    if symbol not in open_trades:
        return False, "الصفقة غير موجودة"
    
    trade = open_trades[symbol]
    current_price = get_price(symbol)
    
    if current_price == 0:
        return False, "لا يمكن الحصول على السعر الحالي"
    
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
    """إغلاق جميع الصفقات"""
    closed = []
    for symbol in list(open_trades.keys()):
        success, trade = close_trade(symbol, "CLOSE_ALL")
        if success:
            closed.append(trade)
    return closed

def get_portfolio_status():
    """الحصول على حالة المحفظة"""
    total_value = balance
    unrealized_pnl = 0
    
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            current_value = trade['quantity'] * current_price
            total_value += current_value
            unrealized_pnl += (current_value - trade['amount'])
            
            # تحديث أعلى وأدنى سعر
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
    """حفظ الصفقات في CSV"""
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
    
    # حفظ المحفظة
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
    """مراقبة الصفقات المفتوحة وإغلاقها تلقائياً"""
    for symbol in list(open_trades.keys()):
        try:
            current_price = get_price(symbol)
            if current_price == 0:
                continue
            
            trade = open_trades[symbol]
            current_return = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            
            # تحديث أعلى سعر (لـ Trailing Stop)
            if current_price > trade['highest']:
                trade['highest'] = current_price
                trade['max_gain'] = current_return
            
            # التحقق من شروط الإغلاق
            should_close = False
            reason = ""
            
            # 1. تحقيق هدف الربح
            if current_return >= PROFIT_TARGET:
                should_close = True
                reason = "TP_HIT"
            
            # 2. وقف الخسارة
            elif current_return <= STOP_LOSS:
                should_close = True
                reason = "SL_HIT"
            
            # 3. Trailing Stop (إذا تم تفعيله)
            elif current_return >= TRAILING_STOP_ACTIVATION:
                trailing_stop = trade['highest'] * (1 - TRAILING_STOP_DISTANCE / 100)
                if current_price <= trailing_stop:
                    should_close = True
                    reason = "TRAILING_STOP"
            
            if should_close:
                success, closed_trade = close_trade(symbol, reason)
                if success:
                    emoji = "✅" if closed_trade['final_return'] >= 0 else "❌"
                    send_msg(f"""
{emoji} <b>إغلاق صفقة {closed_trade['symbol']}</b>

📊 العائد: {closed_trade['final_return']:+.2f}%
💰 الربح: ${closed_trade['profit_loss']:+.2f}
📈 أعلى صعود: +{closed_trade.get('max_gain', 0):.1f}%
🚪 سبب الخروج: {reason}
⏱️ المدة: {((closed_trade['exit_time'] - closed_trade['entry_time']).total_seconds() / 60):.0f} دقيقة
                    """)
                    
                    # إرسال إلى القناة إذا كان ربحاً جيداً
                    if closed_trade['final_return'] >= 3:
                        send_to_channel(f"✅ <b>ربح {closed_trade['symbol']}</b>\n+{closed_trade['final_return']:.1f}% (${closed_trade['profit_loss']:.2f})")
        
        except Exception as e:
            print(f"Monitor error for {symbol}: {e}")

# ============================================
# مراقبة دورية
# ============================================

def start_monitoring():
    """بدء المراقبة الدورية"""
    while bot_running:
        try:
            monitor_open_trades()
            
            # كل ساعة، تحديث الأسعار وإرسال تقرير
            current_hour = datetime.now().hour
            if current_hour == 0 and datetime.now().minute < 5:
                status = get_portfolio_status()
                send_msg(f"""
📊 <b>تقرير يومي</b>

💰 الرصيد: ${status['balance']:.2f}
📈 إجمالي الربح: ${status['total_pnl']:+.2f}
📊 العائد: {status['total_return_pct']:+.1f}%
🟢 صفقات مفتوحة: {status['open_trades']}
✅ صفقات مغلقة: {status['closed_trades']}
📈 نسبة الربح: {status['win_rate']:.1f}%

📅 {datetime.now().strftime('%Y-%m-%d')}
                """)
            
            time.sleep(60)  # كل دقيقة
            
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
                
                # أمر /start
                if text == '/start':
                    msg = """
🤖 <b>بوت التداول الورقي - النسخة الخفيفة</b>

✅ <b>المميزات:</b>
🚫 استبعاد العملات المستقرة والبطيئة
📊 نظام سكور متقدم (0-100)
💰 محفظة افتراضية $1000
📈 Trailing Stop Loss
💬 تحكم كامل عبر Telegram

📋 <b>الأوامر:</b>
/scan - مسح السوق وجلب أفضل العملات
/portfolio - عرض المحفظة
/trades - سجل الصفقات
/buy [الرمز] - فتح صفقة (مثال: /buy SOL)
/close [الرمز] - إغلاق صفقة
/closeall - إغلاق جميع الصفقات
/status - حالة البوت
/export - تحميل ملفات CSV
/help - المساعدة

💡 <b>نصيحة:</b>
1. استخدم /scan لمعرفة أفضل العملات
2. استخدم /buy [الرمز] لفتح صفقة
3. البوت يراقب الصفقات ويغلقها تلقائياً
                    """
                    send_msg(msg, user_id)
                
                # أمر /help
                elif text == '/help':
                    msg = """
📚 <b>دليل الأوامر</b>

🔍 <b>البحث والمسح:</b>
/scan - مسح السوق (أفضل العملات)

💰 <b>التداول:</b>
/buy SOL - فتح صفقة شراء
/close SOL - إغلاق صفقة
/closeall - إغلاق الكل

📊 <b>المحفظة:</b>
/portfolio - تفاصيل المحفظة
/trades - سجل الصفقات
/status - حالة البوت

📁 <b>الملفات:</b>
/export - تحميل CSV

📊 <b>نظام السكور:</b>
80-100: ممتاز 🔥
60-80: جيد جداً ⭐
50-60: جيد ✅
                    """
                    send_msg(msg, user_id)
                
                # أمر /scan
                elif text == '/scan':
                    if scanning:
                        send_msg("⚠️ المسح جاري بالفعل، انتظر قليلاً", user_id)
                    else:
                        threading.Thread(target=scan_top10, daemon=True).start()
                
                # أمر /status
                elif text == '/status':
                    btc = get_price('BTC')
                    eth = get_price('ETH')
                    status = get_portfolio_status()
                    
                    msg = f"""
🤖 <b>حالة البوت</b>

✅ <b>البوت:</b> يعمل
⏰ <b>الوقت:</b> {datetime.now().strftime('%H:%M:%S')}

💰 <b>الأسعار:</b>
BTC: ${btc:,.0f}
ETH: ${eth:,.0f}

📊 <b>المحفظة:</b>
💵 الرصيد: ${status['balance']:.2f}
💰 إجمالي الربح: ${status['total_pnl']:+.2f}
📈 العائد: {status['total_return_pct']:+.1f}%

📊 <b>الصفقات:</b>
🟢 مفتوحة: {status['open_trades']}/{MAX_OPEN_TRADES}
✅ مغلقة: {status['closed_trades']}
📈 نسبة الربح: {status['win_rate']:.1f}%
                    """
                    send_msg(msg, user_id)
                
                # أمر /portfolio
                elif text == '/portfolio':
                    status = get_portfolio_status()
                    
                    msg = f"""
💰 <b>المحفظة التفصيلية</b>

💵 <b>الرصيد:</b> ${status['balance']:.2f}
📈 <b>القيمة الإجمالية:</b> ${status['total_value']:.2f}
💰 <b>إجمالي الربح:</b> ${status['total_pnl']:+.2f}
📊 <b>العائد:</b> {status['total_return_pct']:+.1f}%

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
                    
                    msg += f"\n\n✅ <b>الصفقات المغلقة:</b> {status['closed_trades']}"
                    msg += f"\n📊 <b>نسبة الربح:</b> {status['win_rate']:.1f}%"
                    
                    send_msg(msg, user_id)
                
                # أمر /trades
                elif text == '/trades':
                    if not closed_trades:
                        send_msg("📊 لا توجد صفقات مغلقة حتى الآن", user_id)
                    else:
                        msg = "📊 <b>آخر 10 صفقات مغلقة</b>\n\n"
                        for trade in closed_trades[-10:]:
                            emoji = "🟢" if trade.get('final_return', 0) > 0 else "🔴"
                            msg += f"{emoji} <b>{trade['symbol']}</b>\n"
                            msg += f"   العائد: {trade.get('final_return', 0):+.1f}%\n"
                            msg += f"   الربح: ${trade.get('profit_loss', 0):+.2f}\n"
                            msg += f"   الخروج: {trade.get('exit_reason', '-')}\n\n"
                        send_msg(msg, user_id)
                
                # أمر /buy
                elif text.startswith('/buy'):
                    parts = text.split()
                    if len(parts) < 2:
                        send_msg("⚠️ استخدم: /buy [الرمز]\nمثال: /buy SOL", user_id)
                    else:
                        symbol = parts[1].upper()
                        
                        # البحث عن العملة في آخر مسح
                        found = None
                        for item in last_scan_result:
                            if item['symbol'] == symbol:
                                found = item
                                break
                        
                        if not found:
                            send_msg(f"⚠️ العملة {symbol} غير موجودة في نتائج المسح\nاستخدم /scan أولاً", user_id)
                        else:
                            success, result = open_trade(symbol, found['price'], found['score'], found['reasons'])
                            if success:
                                msg = f"""
✅ <b>تم فتح صفقة شراء</b>

📊 <b>{symbol}</b>
💰 السعر: ${found['price']:.4f}
📈 السكور: {found['score']}
💵 المبلغ: ${TRADE_AMOUNT}

🎯 الهدف: +{PROFIT_TARGET}%
🛑 وقف الخسارة: {STOP_LOSS}%
🔒 Trailing Stop: بعد +{TRAILING_STOP_ACTIVATION}% (مسافة {TRAILING_STOP_DISTANCE}%)
                                """
                                send_msg(msg, user_id)
                                send_to_channel(f"🟢 <b>صفقة جديدة</b>\n{symbol}\nالسعر: ${found['price']:.4f}\nالسكور: {found['score']}")
                            else:
                                send_msg(f"❌ فشل فتح الصفقة: {result}", user_id)
                
                # أمر /close
                elif text.startswith('/close'):
                    parts = text.split()
                    if len(parts) < 2:
                        send_msg("⚠️ استخدم: /close [الرمز]\nمثال: /close SOL", user_id)
                    else:
                        symbol = parts[1].upper()
                        success, result = close_trade(symbol, "USER_COMMAND")
                        if success:
                            emoji = "✅" if result['final_return'] >= 0 else "❌"
                            send_msg(f"{emoji} <b>تم إغلاق صفقة {symbol}</b>\nالعائد: {result['final_return']:+.1f}%\nالربح: ${result['profit_loss']:+.2f}", user_id)
                        else:
                            send_msg(f"❌ {result}", user_id)
                
                # أمر /closeall
                elif text == '/closeall':
                    closed = close_all_trades()
                    if closed:
                        total_pnl = sum(t.get('profit_loss', 0) for t in closed)
                        send_msg(f"✅ <b>تم إغلاق جميع الصفقات ({len(closed)})</b>\nإجمالي الربح: ${total_pnl:+.2f}", user_id)
                    else:
                        send_msg("📊 لا توجد صفقات مفتوحة للإغلاق", user_id)
                
                # أمر /export
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
                        send_msg("📁 <b>تم إرسال ملفات CSV</b>\n- top10.csv (أفضل العملات)\n- trades.csv (سجل الصفقات)\n- portfolio.csv (المحفظة)", user_id)
                    else:
                        send_msg("⚠️ لا توجد ملفات CSV للإرسال", user_id)
                
                # أمر /ping
                elif text == '/ping':
                    send_msg("🏓 Pong! البوت يعمل", user_id)
                
                # أوامر غير معروفة
                else:
                    if text and not text.startswith('/'):
                        send_msg(f"❓ أمر غير معروف: {text}\nاستخدم /help للمساعدة", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 STARTING TRADING BOT (TELEGRAM ONLY)")
    print("=" * 50)
    print(f"Time: {datetime.now()}")
    print(f"Balance: ${INITIAL_BALANCE}")
    print(f"Max trades: {MAX_OPEN_TRADES}")
    print("=" * 50)
    
    # إرسال رسالة بدء التشغيل
    send_msg("""
🚀 <b>البوت يعمل الآن!</b>

✅ نسخة خفيفة (بدون صفحة ويب)
✅ مناسب للنسخة المجانية من Railway
✅ استهلاك منخفض للموارد

📋 <b>الأوامر المتاحة:</b>
/scan - مسح السوق
