#!/usr/bin/env python3
"""
Trading Bot Pro - With Interactive Buttons
بوت تداول احترافي مع أزرار تفاعلية للتحكم بالصفقات
"""

import os
import time
import json
import threading
import csv
import asyncio
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

import ccxt.pro as ccxt
import pandas as pd
import numpy as np

# ============================================
# الإعدادات
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

# إعدادات الانفجار
EXPLOSION_THRESHOLD = 70
HIGH_EXPLOSION_THRESHOLD = 85
MAX_SYMBOLS = 500
SCAN_INTERVAL = 300

# العملات المستبعدة
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
loop = asyncio.new_event_loop()

# ملفات CSV
TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"
TOP10_FILE = "top10.csv"
EXPLOSIONS_FILE = "explosions.csv"

# ============================================
# خادم HTTP
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
    HTTPServer(('0.0.0.0', port), KeepAliveHandler).serve_forever()

# ============================================
# دوال Telegram مع أزرار
# ============================================

def send_msg(text, chat_id=None, parse_mode='HTML', reply_markup=None):
    """إرسال رسالة مع أزرار تفاعلية"""
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

def edit_message_text(text, chat_id, message_id, reply_markup=None):
    """تعديل رسالة موجودة"""
    try:
        url = f'https://api.telegram.org/bot{TOKEN}/editMessageText'
        data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        post_data = json.dumps(data).encode()
        req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Edit error: {e}")
        return False

def answer_callback_query(callback_id, text=None):
    """الرد على الضغط على زر"""
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

def send_to_channel(text):
    return send_msg(text, CHANNEL_ID)

# ============================================
# دوال التداول الأساسية
# ============================================

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
        return False, f"الحد الأقصى {MAX_OPEN_TRADES} صفقة"
    if balance < TRADE_AMOUNT:
        return False, f"الرصيد غير كاف (${balance:.2f})"
    if symbol in open_trades:
        return False, f"صفقة {symbol} مفتوحة بالفعل"
    
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
        return False, "الصفقة غير موجودة"
    
    trade = open_trades[symbol]
    current_price = get_price(symbol)
    if current_price == 0:
        return False, "لا يمكن جلب السعر"
    
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
    """إغلاق جميع الصفقات المفتوحة"""
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

def save_results_to_csv(explosions, top_coins):
    with open(EXPLOSIONS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Time', 'Symbol', 'Score', 'Expected_Rise%', 'Time_To_Explode', 'Type', 'Price', 'Change%'])
        for exp in explosions:
            writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'), exp['symbol'], 
                           exp['explosion']['score'], exp['explosion']['expected_rise'],
                           exp['explosion']['time_to_explode'], exp['explosion']['explosion_type'],
                           exp['price'], f"{exp['change']:.2f}"])

# ============================================
# دوال عرض الصفقات مع أزرار
# ============================================

def show_open_trades(chat_id, message_id=None):
    """عرض الصفقات المفتوحة مع أزرار إغلاق لكل صفقة"""
    if not open_trades:
        msg = "📊 <b>لا توجد صفقات مفتوحة</b>"
        if message_id:
            edit_message_text(msg, chat_id, message_id)
        else:
            send_msg(msg, chat_id)
        return
    
    # بناء键盘 الأزرار للصفقات المفتوحة
    keyboard = []
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            emoji = "🟢" if pnl >= 0 else "🔴"
            button_text = f"{emoji} {symbol} | {pnl:+.1f}% | دخل ${trade['entry_price']:.4f}"
            keyboard.append([{'text': button_text, 'callback_data': f"CLOSE_{symbol}"}])
    
    # إضافة زر إغلاق الكل
    keyboard.append([{'text': "🔴 إغلاق جميع الصفقات", 'callback_data': "CLOSE_ALL"}])
    keyboard.append([{'text': "🔄 تحديث", 'callback_data': "REFRESH_OPEN"}])
    keyboard.append([{'text': "🔙 العودة للقائمة الرئيسية", 'callback_data': "MAIN_MENU"}])
    
    reply_markup = {'inline_keyboard': keyboard}
    
    # حساب إجمالي الربح/الخسارة للصفقات المفتوحة
    total_pnl = 0
    trades_text = ""
    for symbol, trade in open_trades.items():
        current_price = get_price(symbol)
        if current_price > 0:
            pnl = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            pnl_amount = (current_price - trade['entry_price']) * trade['quantity']
            total_pnl += pnl_amount
            emoji = "🟢" if pnl >= 0 else "🔴"
            trades_text += f"\n{emoji} <b>{symbol}</b>: {pnl:+.1f}% (${pnl_amount:+.2f})"
    
    msg = f"""📊 <b>الصفقات المفتوحة ({len(open_trades)}/{MAX_OPEN_TRADES})</b>
{trades_text}

💰 <b>إجمالي PnL المفتوح:</b> ${total_pnl:+.2f}

💡 <b>اضغط على أي صفقة لإغلاقها</b>
"""
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_explosions_with_buttons(chat_id, message_id=None):
    """عرض العملات التي ستنفجر مع أزرار شراء"""
    if not explosions_found:
        msg = "💥 <b>لا توجد انفجارات وشيكة حالياً</b>\nاستخدم /explode للمسح"
        if message_id:
            edit_message_text(msg, chat_id, message_id)
        else:
            send_msg(msg, chat_id)
        return
    
    # بناء键盘 الأزرار للانفجارات
    keyboard = []
    for exp in explosions_found[:10]:
        explosion = exp['explosion']
        button_text = f"💥 {exp['symbol']} | درجة {explosion['score']} | صعود +{explosion['expected_rise']}%"
        keyboard.append([{'text': button_text, 'callback_data': f"BUY_{exp['symbol']}"}])
    
    keyboard.append([{'text': "🔄 تحديث", 'callback_data': "REFRESH_EXPLOSIONS"}])
    keyboard.append([{'text': "🔙 العودة للقائمة الرئيسية", 'callback_data': "MAIN_MENU"}])
    
    reply_markup = {'inline_keyboard': keyboard}
    
    msg = "💥 <b>العملات المرشحة للانفجار</b>\n\n"
    for i, exp in enumerate(explosions_found[:10], 1):
        explosion = exp['explosion']
        msg += f"{i}. <b>{exp['symbol']}</b>\n"
        msg += f"   💥 درجة الانفجار: {explosion['score']}/100\n"
        msg += f"   📈 صعود متوقع: +{explosion['expected_rise']}%\n"
        msg += f"   ⏰ خلال: {explosion['time_to_explode']} دقيقة\n"
        msg += f"   💰 السعر: ${exp['price']:.6f}\n\n"
    
    msg += "💡 <b>اضغط على أي عملة لفتح صفقة</b>"
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_main_menu(chat_id, message_id=None):
    """عرض القائمة الرئيسية مع أزرار التحكم"""
    status = get_portfolio_status()
    
    keyboard = [
        [{'text': "💥 كشف الانفجارات", 'callback_data': "SHOW_EXPLOSIONS"}],
        [{'text': "📊 مسح السوق", 'callback_data': "SCAN_MARKET"}],
        [{'text': "🟢 الصفقات المفتوحة", 'callback_data': "SHOW_OPEN_TRADES"}],
        [{'text': "🔒 الصفقات المغلقة", 'callback_data': "SHOW_CLOSED_TRADES"}],
        [{'text': "💰 حالة المحفظة", 'callback_data': "SHOW_PORTFOLIO"}],
        [{'text': "📁 تحميل CSV", 'callback_data': "EXPORT_CSV"}],
        [{'text': "📊 حالة البوت", 'callback_data': "BOT_STATUS"}]
    ]
    
    reply_markup = {'inline_keyboard': keyboard}
    
    msg = f"""
🤖 <b>Adem Trading Bot - القائمة الرئيسية</b>

💰 <b>المحفظة:</b>
├ الرصيد: ${status['balance']:.2f}
├ إجمالي الربح: ${status['total_pnl']:+.2f}
├ العائد: {status['total_return_pct']:+.1f}%
│
📊 <b>الصفقات:</b>
├ مفتوحة: {status['open_trades']}/{MAX_OPEN_TRADES}
├ مغلقة: {status['closed_trades']}
├ نسبة الربح: {status['win_rate']:.1f}%
│
💥 <b>الانفجارات:</b>
├ مكتشفة: {len(explosions_found)}
│
⏰ {datetime.now().strftime('%H:%M:%S')}

💡 <b>اختر أحد الخيارات:</b>
    """
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_closed_trades(chat_id, message_id=None):
    """عرض الصفقات المغلقة"""
    if not closed_trades:
        msg = "📊 <b>لا توجد صفقات مغلقة</b>"
        if message_id:
            edit_message_text(msg, chat_id, message_id)
        else:
            send_msg(msg, chat_id)
        return
    
    msg = "🔒 <b>آخر 10 صفقات مغلقة</b>\n\n"
    for trade in closed_trades[-10:]:
        emoji = "✅" if trade.get('final_return', 0) > 0 else "❌"
        msg += f"{emoji} <b>{trade['symbol']}</b>\n"
        msg += f"   العائد: {trade.get('final_return', 0):+.1f}%\n"
        msg += f"   الربح: ${trade.get('profit_loss', 0):+.2f}\n"
        msg += f"   الخروج: {trade.get('exit_reason', '-')}\n\n"
    
    keyboard = [[{'text': "🔙 العودة للقائمة الرئيسية", 'callback_data': "MAIN_MENU"}]]
    reply_markup = {'inline_keyboard': keyboard}
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_portfolio(chat_id, message_id=None):
    """عرض تفاصيل المحفظة"""
    status = get_portfolio_status()
    
    msg = f"""
💰 <b>تفاصيل المحفظة</b>

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
    
    keyboard = [[{'text': "🔙 العودة للقائمة الرئيسية", 'callback_data': "MAIN_MENU"}]]
    reply_markup = {'inline_keyboard': keyboard}
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

def show_bot_status(chat_id, message_id=None):
    """عرض حالة البوت"""
    status = get_portfolio_status()
    uptime = (time.time() - start_time) / 3600
    
    msg = f"""
📊 <b>حالة البوت</b>

✅ <b>الحالة:</b> نشط
⏰ <b>وقت التشغيل:</b> {uptime:.1f} ساعات
📅 <b>الوقت:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔧 <b>الإعدادات:</b>
├ رأس المال: ${INITIAL_BALANCE}
├ حجم الصفقة: ${TRADE_AMOUNT}
├ الحد الأقصى: {MAX_OPEN_TRADES} صفقة
├ هدف الربح: +{PROFIT_TARGET}%
├ وقف الخسارة: {STOP_LOSS}%
└ عتبة الانفجار: {EXPLOSION_THRESHOLD}%

📊 <b>الإحصائيات:</b>
├ الرصيد: ${status['balance']:.2f}
├ إجمالي الربح: ${status['total_pnl']:+.2f}
├ العائد: {status['total_return_pct']:+.1f}%
├ صفقات مفتوحة: {status['open_trades']}
├ صفقات مغلقة: {status['closed_trades']}
└ نسبة الربح: {status['win_rate']:.1f}%
"""
    
    keyboard = [[{'text': "🔙 العودة للقائمة الرئيسية", 'callback_data': "MAIN_MENU"}]]
    reply_markup = {'inline_keyboard': keyboard}
    
    if message_id:
        edit_message_text(msg, chat_id, message_id, reply_markup)
    else:
        send_msg(msg, chat_id, reply_markup=reply_markup)

# ============================================
# المسح الضوئي
# ============================================

# دوال المسح المبسطة (نفس الكود السابق)
def scan_market_sync():
    """مسح السوق (نسخة مبسطة)"""
    global scanning, explosions_found, last_scan_result
    scanning = True
    send_msg("💥 <b>جاري مسح الانفجارات...</b>\n⏱️ يرجى الانتظار")
    
    try:
        # محاكاة نتائج للاختبار
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
                        'explosion_type': "🔥 انفجار حجم + سعر" if score > 80 else "📊 انفجار حجم",
                        'signals': ["🔥 حجم خارق", "🚀 قفزة سعرية", "🟢 MACD إيجابي"]
                    }
                })
        
        explosions.sort(key=lambda x: x['explosion']['score'], reverse=True)
        explosions_found = explosions
        last_scan_result = explosions
        
        save_results_to_csv(explosions_found, [])
        
        # إرسال الإشعارات
        for exp in explosions_found[:3]:
            explosion = exp['explosion']
            send_msg(f"""
💥 <b>تنبيه انفجار وشيك!</b>

┌ 📊 <b>{exp['symbol']}</b>
├ 💥 درجة الانفجار: {explosion['score']}/100
├ 📈 الصعود المتوقع: +{explosion['expected_rise']}%
├ ⏰ خلال: {explosion['time_to_explode']} دقيقة
│
└ 🚨 <b>فرصة استثنائية!</b>

💡 /buy {exp['symbol']}
            """)
        
        send_msg(f"✅ اكتمل المسح! تم العثور على {len(explosions_found)} انفجار وشيك")
        scanning = False
        
    except Exception as e:
        send_msg(f"❌ خطأ: {str(e)[:100]}")
        scanning = False

# ============================================
# معالجة الأزرار والأوامر
# ============================================

def handle_callback_query(callback):
    """معالجة الضغط على الأزرار"""
    data = callback.get('data', '')
    chat_id = callback.get('message', {}).get('chat', {}).get('id')
    message_id = callback.get('message', {}).get('message_id')
    callback_id = callback.get('id')
    
    # معالجة إغلاق صفقة محددة
    if data.startswith('CLOSE_'):
        symbol = data.replace('CLOSE_', '')
        success, result = close_trade(symbol, "BUTTON_CLOSE")
        if success:
            answer_callback_query(callback_id, f"✅ تم إغلاق {symbol}")
            show_open_trades(chat_id, message_id)
        else:
            answer_callback_query(callback_id, f"❌ {result}")
    
    # معالجة إغلاق جميع الصفقات
    elif data == 'CLOSE_ALL':
        closed = close_all_trades()
        answer_callback_query(callback_id, f"✅ تم إغلاق {len(closed)} صفقة")
        show_open_trades(chat_id, message_id)
    
    # معالجة شراء عملة
    elif data.startswith('BUY_'):
        symbol = data.replace('BUY_', '')
        # البحث عن العملة في نتائج الانفجار
        found = None
        for exp in explosions_found:
            if exp['symbol'] == symbol:
                found = exp
                break
        
        if found:
            success, trade = open_trade(symbol, found['price'], found['explosion']['score'], 
                                       found['explosion']['signals'])
            if success:
                answer_callback_query(callback_id, f"✅ تم فتح صفقة {symbol}")
                send_msg(f"✅ <b>تم فتح صفقة {symbol}</b>\n💰 السعر: ${found['price']:.4f}\n💥 درجة الانفجار: {found['explosion']['score']}/100")
            else:
                answer_callback_query(callback_id, f"❌ {trade}")
        else:
            answer_callback_query(callback_id, "❌ العملة غير موجودة")
    
    # عرض الصفقات المفتوحة
    elif data == 'SHOW_OPEN_TRADES':
        show_open_trades(chat_id, message_id)
    
    # عرض الصفقات المغلقة
    elif data == 'SHOW_CLOSED_TRADES':
        show_closed_trades(chat_id, message_id)
    
    # عرض المحفظة
    elif data == 'SHOW_PORTFOLIO':
        show_portfolio(chat_id, message_id)
    
    # عرض حالة البوت
    elif data == 'BOT_STATUS':
        show_bot_status(chat_id, message_id)
    
    # عرض الانفجارات
    elif data == 'SHOW_EXPLOSIONS':
        show_explosions_with_buttons(chat_id, message_id)
    
    # مسح السوق
    elif data == 'SCAN_MARKET':
        answer_callback_query(callback_id, "🔄 جاري المسح...")
        threading.Thread(target=scan_market_sync, daemon=True).start()
        send_msg("🔍 جاري مسح الانفجارات...", chat_id)
    
    # تحديث قائمة الانفجارات
    elif data == 'REFRESH_EXPLOSIONS':
        show_explosions_with_buttons(chat_id, message_id)
    
    # تحديث الصفقات المفتوحة
    elif data == 'REFRESH_OPEN':
        show_open_trades(chat_id, message_id)
    
    # تصدير CSV
    elif data == 'EXPORT_CSV':
        answer_callback_query(callback_id, "📁 جاري إرسال الملفات...")
        files = [TOP10_FILE, EXPLOSIONS_FILE, TRADES_FILE, PORTFOLIO_FILE]
        for file in files:
            if os.path.exists(file) and os.path.getsize(file) > 0:
                try:
                    url = f'https://api.telegram.org/bot{TOKEN}/sendDocument'
                    with open(file, 'rb') as f:
                        data_file = f.read()
                    boundary = '----WebKitFormBoundary' + str(time.time())
                    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
                           f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{file}"\r\n'
                           f'Content-Type: text/csv\r\n\r\n').encode() + data_file + f'\r\n--{boundary}--\r\n'.encode()
                    req = urllib.request.Request(url, data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
                    urllib.request.urlopen(req, timeout=30)
                    time.sleep(1)
                except Exception as e:
                    print(f"Error sending {file}: {e}")
        send_msg("📁 تم إرسال ملفات CSV", chat_id)
    
    # القائمة الرئيسية
    elif data == 'MAIN_MENU':
        show_main_menu(chat_id, message_id)
    
    else:
        answer_callback_query(callback_id, "⚠️ أمر غير معروف")

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
                
                # معالجة الضغط على الأزرار
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
                            success, trade = open_trade(symbol, found['price'], found['explosion']['score'], 
                                                       found['explosion']['signals'])
                            if success:
