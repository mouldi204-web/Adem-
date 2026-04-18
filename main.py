#!/usr/bin/env python3
"""
Gate.io Breakout Scanner - Final Version
أفضل إعدادات للتجربة - يعمل فوراً
"""

import os
import time
import json
import urllib.request
import threading
from datetime import datetime

# ============================================
# الإعدادات - تم تحسينها للتجربة
# ============================================

# Telegram Settings (استبدلها بتوكنك)
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"

# إعدادات المسح - محسنة لنتائج أسرع
MAX_SYMBOLS = 300        # 300 عملة لسرعة أفضل
MIN_SCORE = 55           # سكور أقل للحصول على نتائج
SCAN_INTERVAL = 300      # 5 دقائق بين كل مسح

# إعدادات المؤشرات - متوازنة
BB_PERIOD = 20
BB_STD = 2
EMA_PERIOD = 20
VOLUME_PERIOD = 20
RSI_PERIOD = 14
BREAKOUT_PERIOD = 20

# العملات المستبعدة
STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD', 'USDP']

# ملفات CSV
TOP10_FILE = "top10.csv"
TRADES_FILE = "trades.csv"
PORTFOLIO_FILE = "portfolio.csv"

# ============================================
# دوال Telegram
# ============================================

def send_telegram(text, chat_id=None, parse_mode='HTML'):
    """إرسال رسالة إلى Telegram"""
    try:
        target = chat_id or TELEGRAM_CHAT_ID
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
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
        print(f"Telegram error: {e}")
        return False

def send_csv_files(chat_id):
    """إرسال جميع ملفات CSV"""
    files = [TOP10_FILE, TRADES_FILE, PORTFOLIO_FILE]
    sent = False
    
    for file in files:
        if os.path.exists(file) and os.path.getsize(file) > 0:
            try:
                url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument'
                with open(file, 'rb') as f:
                    data = f.read()
                
                boundary = '----WebKitFormBoundary' + str(time.time())
                body = (
                    f'--{boundary}\r\n'
                    f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
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
        send_telegram("📁 <b>CSV files sent!</b>\n\n- top10.csv\n- trades.csv\n- portfolio.csv", chat_id)
    else:
        send_telegram("⚠️ No CSV files yet. Use /scan first.", chat_id)

# ============================================
# دوال API - Gate.io
# ============================================

def fetch_klines_gateio(symbol, interval='1h', limit=100):
    """جلب بيانات الشموع من Gate.io"""
    try:
        formatted_symbol = symbol.replace('USDT', '_USDT')
        
        interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m',
            '1h': '1h', '4h': '4h', '1d': '1d'
        }
        gate_interval = interval_map.get(interval, '1h')
        
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={formatted_symbol}&interval={gate_interval}&limit={limit}"
        
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
            
            klines = []
            for k in data:
                klines.append({
                    'time': int(k[0]),
                    'open': float(k[5]),
                    'high': float(k[3]),
                    'low': float(k[4]),
                    'close': float(k[2]),
                    'volume': float(k[6])
                })
            return klines
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def get_all_symbols_gateio():
    """جلب جميع العملات المتاحة"""
    try:
        url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
            symbols = []
            for pair in data:
                if pair['quote'] == 'USDT' and pair['trade_status'] == 'tradable':
                    symbol = pair['base'] + 'USDT'
                    base = pair['base']
                    if base not in STABLE_COINS:
                        symbols.append(symbol)
            return symbols[:MAX_SYMBOLS]
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return []

# ============================================
# المؤشرات الفنية
# ============================================

def calculate_rsi(prices, period=14):
    """حساب RSI"""
    if len(prices) < period + 1:
        return 50
    
    deltas = []
    for i in range(1, len(prices)):
        deltas.append(prices[i] - prices[i-1])
    
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        return 100
    
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_ema(prices, period=20):
    """حساب EMA"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_macd(prices):
    """حساب MACD"""
    if len(prices) < 26:
        return False
    
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    macd = ema12 - ema26
    
    macd_history = []
    for i in range(26, len(prices)):
        e12 = calculate_ema(prices[:i+1], 12)
        e26 = calculate_ema(prices[:i+1], 26)
        macd_history.append(e12 - e26)
    
    if len(macd_history) >= 9:
        signal = calculate_ema(macd_history, 9)
        return macd > signal
    return False

def calculate_bollinger_bandwidth(prices, period=20, std=2):
    """حساب عرض Bollinger Bands"""
    if len(prices) < period:
        return 100
    
    recent = prices[-period:]
    mean = sum(recent) / period
    variance = sum((p - mean) ** 2 for p in recent) / period
    std_dev = variance ** 0.5
    
    upper = mean + (std_dev * std)
    lower = mean - (std_dev * std)
    bandwidth = (upper - lower) / mean if mean > 0 else 100
    
    return bandwidth

def is_bullish_engulfing(klines):
    """كشف نمط Bullish Engulfing"""
    if len(klines) < 2:
        return False
    
    prev = klines[-2]
    curr = klines[-1]
    
    prev_bearish = prev['close'] < prev['open']
    curr_bullish = curr['close'] > curr['open']
    engulfing = curr['open'] < prev['close'] and curr['close'] > prev['open']
    
    return prev_bearish and curr_bullish and engulfing

def calculate_score(symbol, klines):
    """حساب السكور (0-100)"""
    if not klines or len(klines) < 50:
        return 0, []
    
    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    volumes = [k['volume'] for k in klines]
    
    score = 0
    reasons = []
    
    # 1. اختراق سعري (25 نقطة)
    recent_highs = highs[-BREAKOUT_PERIOD-1:-1]
    highest_recent = max(recent_highs) if recent_highs else 0
    current_price = closes[-1]
    
    if current_price > highest_recent and highest_recent > 0:
        breakout_pct = ((current_price - highest_recent) / highest_recent) * 100
        score += 25
        reasons.append(f"🚀 Breakout +{breakout_pct:.1f}%")
    
    # 2. انفجار حجم (25 نقطة)
    avg_volume = sum(volumes[-VOLUME_PERIOD-1:-1]) / VOLUME_PERIOD if len(volumes) > VOLUME_PERIOD else 0
    current_volume = volumes[-1]
    
    if avg_volume > 0:
        volume_ratio = current_volume / avg_volume
        if volume_ratio > 2:
            score += 25
            reasons.append(f"📊 Volume x{volume_ratio:.1f}")
        elif volume_ratio > 1.5:
            score += 15
            reasons.append(f"📈 Volume x{volume_ratio:.1f}")
        elif volume_ratio > 1.2:
            score += 8
            reasons.append(f"📉 Volume x{volume_ratio:.1f}")
    
    # 3. الاتجاه (15 نقطة)
    ema = calculate_ema(closes, EMA_PERIOD)
    if current_price > ema:
        score += 15
        reasons.append("📈 Uptrend")
    
    # 4. MACD (15 نقطة)
    if calculate_macd(closes):
        score += 15
        reasons.append("🟢 MACD Bullish")
    
    # 5. RSI (10 نقطة)
    rsi = calculate_rsi(closes, RSI_PERIOD)
    if 50 <= rsi <= 70:
        score += 10
        reasons.append(f"💪 RSI {rsi:.0f}")
    elif 40 <= rsi < 50:
        score += 5
        reasons.append(f"📊 RSI {rsi:.0f}")
    
    # 6. Bollinger Squeeze (10 نقطة)
    bb_width = calculate_bollinger_bandwidth(closes, BB_PERIOD, BB_STD)
    if bb_width < 0.05:
        score += 10
        reasons.append("🔄 BB Squeeze")
    
    return min(score, 100), reasons

# ============================================
# المسح الضوئي
# ============================================

def save_top10_csv(results):
    """حفظ النتائج في CSV"""
    with open(TOP10_FILE, 'w', newline='', encoding='utf-8') as f:
        import csv
        writer = csv.writer(f)
        writer.writerow(['Rank', 'Symbol', 'Score', 'Price', 'Change%', 'Reasons', 'Time'])
        for i, item in enumerate(results[:20], 1):
            writer.writerow([
                i, item['symbol'], item['score'], item['price'],
                f"{item['change']:.2f}", '|'.join(item['reasons']),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ])

def scan_market():
    """المسح الضوئي للسوق"""
    print(f"\n{'='*50}")
    print(f"🔄 Scanning Gate.io - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")
    
    symbols = get_all_symbols_gateio()
    print(f"📊 Found {len(symbols)} pairs")
    
    results = []
    
    for i, symbol in enumerate(symbols):
        klines = fetch_klines_gateio(symbol, '1h', 60)
        
        if klines:
            score, reasons = calculate_score(symbol, klines)
            
            if score >= MIN_SCORE:
                current_price = klines[-1]['close']
                change = ((current_price - klines[-2]['close']) / klines[-2]['close']) * 100 if len(klines) > 1 else 0
                
                results.append({
                    'symbol': symbol,
                    'score': score,
                    'price': current_price,
                    'change': change,
                    'reasons': reasons
                })
                print(f"  ✅ {symbol}: Score {score} | +{change:.1f}%")
        
        # تأخير لتجنب الحظر
        if (i + 1) % 20 == 0:
            time.sleep(1)
    
    results.sort(key=lambda x: x['score'], reverse=True)
    save_top10_csv(results)
    send_results(results[:10])
    
    return results

def send_results(results):
    """إرسال النتائج إلى Telegram"""
    if not results:
        send_telegram("🔍 No signals found in this scan.")
        return
    
    message = f"🚀 <b>Gate.io Scanner Results</b> 🚀\n\n"
    message += f"⏰ {datetime.now().strftime('%H:%M:%S')} | 🎯 Min Score: {MIN_SCORE}\n\n"
    
    for i, r in enumerate(results[:10], 1):
        emoji = "🟢" if r['change'] > 0 else "🔴"
        message += f"{i}. {emoji} <b>{r['symbol']}</b>\n"
        message += f"   📊 Score: <code>{r['score']}</code> | Change: {r['change']:+.1f}%\n"
        message += f"   💰 Price: ${r['price']:.6f}\n"
        message += f"   📈 {', '.join(r['reasons'][:2])}\n\n"
    
    message += f"💡 /scan - New scan | /export - CSV files"
    send_telegram(message)

def start_auto_scanner():
    """الماسح التلقائي"""
    send_telegram("✅ <b>Gate.io Scanner Started!</b>\n\n🔄 Auto-scan every 5 minutes\n📊 Min score: 55\n💡 Use /scan for manual scan")
    
    while True:
        try:
            scan_market()
            time.sleep(SCAN_INTERVAL)
        except Exception as e:
            print(f"Scanner error: {e}")
            time.sleep(60)

# ============================================
# أوامر Telegram
# ============================================

def handle_commands():
    """معالجة أوامر Telegram"""
    last_id = 0
    
    while True:
        try:
            url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates'
            if last_id:
                url += f'?offset={last_id + 1}'
            
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read().decode())
            
            for update in data.get('result', []):
                last_id = update['update_id']
                message = update.get('message', {})
                text = message.get('text', '').lower()
                user_id = message.get('chat', {}).get('id')
                
                if text == '/start':
                    msg = """🤖 <b>Gate.io Breakout Scanner</b>

<b>⚙️ Settings:</b>
• 300+ pairs scanned
• 6 technical indicators
• Min score: 55
• Auto-scan: 5 min

<b>📋 Commands:</b>
/scan → Manual scan
/status → Bot status
/export → Download CSV
/help → Help

<b>🚀 Ready! Use /scan to start</b>"""
                    send_telegram(msg, user_id)
                
                elif text == '/scan':
                    send_telegram("🔄 Scanning market... (30-60 sec)", user_id)
                    threading.Thread(target=lambda: scan_market(), daemon=True).start()
                
                elif text == '/status':
                    msg = f"""📊 <b>Scanner Status</b>

✅ Status: Active
📈 Pairs: {MAX_SYMBOLS}
🎯 Min score: {MIN_SCORE}
⏱️ Interval: {SCAN_INTERVAL//60} min
🔧 Indicators: 6
🏦 Exchange: Gate.io

📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                    send_telegram(msg, user_id)
                
                elif text == '/export':
                    send_csv_files(user_id)
                
                elif text == '/help':
                    msg = """📚 <b>Help & Commands</b>

<b>Commands:</b>
/start - Welcome message
/scan - Manual market scan
/status - Bot status
/export - Download CSV files
/help - This help

<b>Score System (0-100):</b>
80-100: 🔥 Excellent
65-79: ✅ Good
55-64: 📊 Weak

<b>Indicators:</b>
• Price Breakout (25pts)
• Volume Explosion (25pts)
• Trend EMA (15pts)
• MACD (15pts)
• RSI (10pts)
• BB Squeeze (10pts)"""
                    send_telegram(msg, user_id)
                
                elif text == '/ping':
                    send_telegram("🏓 Pong! Bot is running", user_id)
                
                else:
                    if text and not text.startswith('/'):
                        send_telegram(f"❓ Unknown: {text}\nUse /help", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 GATE.IO BREAKOUT SCANNER")
    print("=" * 50)
    print(f"Time: {datetime.now()}")
    print(f"Pairs: {MAX_SYMBOLS}")
    print(f"Min Score: {MIN_SCORE}")
    print(f"Interval: {SCAN_INTERVAL//60} min")
    print("=" * 50)
    
    # إرسال رسالة البدء
    send_telegram("🚀 <b>Gate.io Scanner Started!</b>\n\n✅ 300+ pairs\n✅ 6 indicators\n✅ Auto-scan every 5 min\n\n💡 Use /scan to test now!")
    
    # تشغيل الماسح التلقائي
    scanner_thread = threading.Thread(target=start_auto_scanner, daemon=True)
    scanner_thread.start()
    
    # تشغيل معالجة الأوامر
    handle_commands()
