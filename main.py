#!/usr/bin/env python3
"""
Gate.io Breakout Scanner - Real-time Market Mover Detection
يكتشف العملات التي تظهر إشارات اختراق قوية على منصة Gate.io
"""

import time
import json
import urllib.request
import threading
from datetime import datetime

# ============================================
# الإعدادات
# ============================================

TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"
TELEGRAM_CHANNEL_ID = "1001003692815602"

# إعدادات المسح
MAX_SYMBOLS = 500
MIN_SCORE = 60
SCAN_INTERVAL = 300  # 5 دقائق بين كل مسح

# إعدادات المؤشرات
EMA_PERIOD = 20
VOLUME_PERIOD = 20
RSI_PERIOD = 14
BREAKOUT_PERIOD = 20

# العملات المستبعدة (العملات المستقرة)
STABLE_COINS = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'USDD', 'USDP', 'GUSD', 'PAX']

# العملات الكبيرة البطيئة (يمكن تفعيلها حسب الرغبة)
# SLOW_LARGE_COINS = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'DOGE', 'MATIC', 'DOT', 'LTC', 'TRX', 'TON', 'LINK', 'AVAX', 'SHIB']

# ============================================
# دوال المساعدة
# ============================================

def send_telegram(text, parse_mode='HTML'):
    """إرسال رسالة إلى Telegram"""
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        data = json.dumps({
            'chat_id': TELEGRAM_CHAT_ID,
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

def send_to_channel(text):
    """إرسال إلى القناة"""
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        data = json.dumps({
            'chat_id': TELEGRAM_CHANNEL_ID,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Channel error: {e}")
        return False

def fetch_klines_gateio(symbol, interval='1h', limit=100):
    """جلب بيانات الشموع من Gate.io"""
    try:
        # Gate.io API endpoint للشموع
        # صيغة السعر: BTC_USDT (بينها شرطة سفلية)
        formatted_symbol = symbol.replace('USDT', '_USDT')
        
        # تحويل الفاصل الزمني
        interval_map = {
            '1m': '1m',
            '5m': '5m', 
            '15m': '15m',
            '1h': '1h',
            '4h': '4h',
            '1d': '1d'
        }
        gate_interval = interval_map.get(interval, '1h')
        
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={formatted_symbol}&interval={gate_interval}&limit={limit}"
        
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
            
            klines = []
            for k in data:
                klines.append({
                    'time': int(k[0]),
                    'open': float(k[5]),   # Gate.io تنسيق مختلف
                    'high': float(k[3]),
                    'low': float(k[4]),
                    'close': float(k[2]),
                    'volume': float(k[6])
                })
            return klines
    except Exception as e:
        print(f"Error fetching {symbol} from Gate.io: {e}")
        return None

def fetch_ticker_gateio(symbol):
    """جلب بيانات التيكر الحالية من Gate.io"""
    try:
        formatted_symbol = symbol.replace('USDT', '_USDT')
        url = f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={formatted_symbol}"
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data:
                return {
                    'price': float(data[0]['last']),
                    'change': float(data[0].get('change_percentage', 0)),
                    'volume': float(data[0].get('quote_volume', 0))
                }
        return None
    except Exception as e:
        print(f"Ticker error for {symbol}: {e}")
        return None

def get_all_symbols_gateio():
    """جلب جميع العملات المتاحة على Gate.io"""
    try:
        url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
            symbols = []
            for pair in data:
                if pair['quote'] == 'USDT' and pair['trade_status'] == 'tradable':
                    symbol = pair['base'] + 'USDT'
                    base = pair['base']
                    # استبعاد العملات المستقرة
                    if base not in STABLE_COINS:
                        symbols.append(symbol)
            return symbols[:MAX_SYMBOLS]
    except Exception as e:
        print(f"Error fetching symbols from Gate.io: {e}")
        return []

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
    """حساب MACD (تقاطع بسيط)"""
    if len(prices) < 26:
        return False
    
    # EMA 12
    ema12 = calculate_ema(prices, 12)
    # EMA 26
    ema26 = calculate_ema(prices, 26)
    # MACD
    macd = ema12 - ema26
    
    # حساب مؤشر MACD البسيط
    macd_history = []
    for i in range(26, len(prices)):
        e12 = calculate_ema(prices[:i+1], 12)
        e26 = calculate_ema(prices[:i+1], 26)
        macd_history.append(e12 - e26)
    
    if len(macd_history) >= 9:
        signal = calculate_ema(macd_history, 9)
        return macd > signal
    return False

def calculate_score(symbol, klines, ticker):
    """حساب السكور بناءً على المؤشرات"""
    if not klines or len(klines) < 50:
        return 0, []
    
    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    volumes = [k['volume'] for k in klines]
    
    score = 0
    reasons = []
    
    # 1. اختراق سعري (30 نقطة)
    recent_highs = highs[-BREAKOUT_PERIOD-1:-1]
    highest_recent = max(recent_highs) if recent_highs else 0
    current_price = closes[-1]
    
    if current_price > highest_recent and highest_recent > 0:
        breakout_pct = ((current_price - highest_recent) / highest_recent) * 100
        score += 30
        reasons.append(f"Breakout +{breakout_pct:.1f}%")
    
    # 2. انفجار حجم (25 نقطة)
    avg_volume = sum(volumes[-VOLUME_PERIOD-1:-1]) / VOLUME_PERIOD if len(volumes) > VOLUME_PERIOD else 0
    current_volume = volumes[-1]
    
    if avg_volume > 0:
        volume_ratio = current_volume / avg_volume
        if volume_ratio > 2:
            score += 25
            reasons.append(f"Volume x{volume_ratio:.1f}")
        elif volume_ratio > 1.5:
            score += 15
            reasons.append(f"Volume x{volume_ratio:.1f}")
        elif volume_ratio > 1.2:
            score += 8
            reasons.append(f"Volume x{volume_ratio:.1f}")
    
    # 3. الاتجاه (15 نقطة)
    ema = calculate_ema(closes, EMA_PERIOD)
    if current_price > ema:
        score += 15
        reasons.append("Uptrend")
    
    # 4. MACD (15 نقطة)
    if calculate_macd(closes):
        score += 15
        reasons.append("MACD Bullish")
    
    # 5. RSI (10 نقاط)
    rsi = calculate_rsi(closes, RSI_PERIOD)
    if 40 <= rsi <= 60:
        score += 10
        reasons.append(f"RSI {rsi:.0f}")
    elif 60 < rsi <= 75:
        score += 5
        reasons.append(f"RSI {rsi:.0f}")
    
    # 6. التغير السعري (5 نقاط من التيكر)
    if ticker and ticker['change'] > 3:
        score += 5
        reasons.append(f"Change +{ticker['change']:.1f}%")
    
    return min(score, 100), reasons

def scan_market():
    """المسح الضوئي للسوق على Gate.io"""
    print(f"\n{'='*50}")
    print(f"🔄 Scanning Gate.io Market - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")
    
    symbols = get_all_symbols_gateio()
    print(f"📊 Found {len(symbols)} pairs on Gate.io")
    
    results = []
    total_scanned = 0
    
    for i, symbol in enumerate(symbols):
        try:
            # جلب بيانات الشموع
            klines = fetch_klines_gateio(symbol, '1h', 60)
            ticker = fetch_ticker_gateio(symbol)
            
            if klines and ticker:
                score, reasons = calculate_score(symbol, klines, ticker)
                
                if score >= MIN_SCORE:
                    current_price = ticker['price']
                    change = ticker['change']
                    
                    results.append({
                        'symbol': symbol,
                        'score': score,
                        'price': current_price,
                        'change': change,
                        'reasons': reasons
                    })
                    print(f"  ✅ {symbol}: Score {score} | Change {change:+.1f}%")
                    total_scanned += 1
            
            # تأخير لتجنب حظر API
            time.sleep(0.3)
            
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")
            continue
    
    # ترتيب حسب السكور
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n📈 Found {len(results)} signals with score >= {MIN_SCORE}")
    
    # إرسال النتائج إلى Telegram
    send_results_to_telegram(results[:15])
    
    return results

def send_results_to_telegram(results):
    """إرسال النتائج إلى Telegram"""
    if not results:
        send_telegram("🔍 No strong signals found on Gate.io in this scan.")
        return
    
    message = f"🚀 <b>Gate.io Breakout Scanner</b> 🚀\n\n"
    message += f"📊 Time: {datetime.now().strftime('%H:%M:%S')}\n"
    message += f"🎯 Min Score: {MIN_SCORE}\n"
    message += f"📈 Top {min(len(results), 10)} Signals\n\n"
    
    for i, r in enumerate(results[:10], 1):
        change_emoji = "🟢" if r['change'] > 0 else "🔴"
        message += f"{i}. {change_emoji} <b>{r['symbol']}</b>\n"
        message += f"   Score: <code>{r['score']}</code> | Change: {r['change']:+.1f}%\n"
        message += f"   Price: ${r['price']:.6f}\n"
        message += f"   📊 {', '.join(r['reasons'][:3])}\n\n"
    
    message += f"\n💡 Use /buy SYMBOL to open a trade\n"
    message += f"🔄 Auto-scan every {SCAN_INTERVAL//60} minutes"
    
    send_telegram(message)
    
    # إرسال أفضل إشارة إلى القناة
    if results:
        best = results[0]
        channel_msg = f"🏆 <b>Best Signal on Gate.io</b>\n\n{best['symbol']}\nScore: {best['score']}\nChange: {best['change']:+.1f}%\nPrice: ${best['price']:.6f}"
        send_to_channel(channel_msg)

def start_auto_scanner():
    """تشغيل الماسح التلقائي"""
    print("🤖 Starting Gate.io Breakout Scanner...")
    send_telegram("🤖 <b>Gate.io Breakout Scanner Started!</b>\n\n✅ Auto-scan every 5 minutes\n✅ 6 technical indicators\n✅ Real-time alerts")
    
    while True:
        try:
            scan_market()
            print(f"⏳ Waiting {SCAN_INTERVAL//60} minutes until next scan...")
            time.sleep(SCAN_INTERVAL)
        except Exception as e:
            print(f"Scanner error: {e}")
            time.sleep(60)

def handle_telegram_commands():
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

<b>Features:</b>
✅ Scans 500+ pairs on Gate.io
✅ 6 technical indicators
✅ Breakout + Volume confirmation
✅ MACD + RSI + EMA filters
✅ Real-time alerts via Telegram

<b>Commands:</b>
/scan - Run manual scan
/status - Scanner status
/help - Help

<b>Auto-scan:</b>
Every 5 minutes automatically"""
                    send_telegram(msg)
                
                elif text == '/scan':
                    send_telegram("🔄 Manual scan started on Gate.io...")
                    threading.Thread(target=scan_market, daemon=True).start()
                
                elif text == '/status':
                    msg = f"""📊 <b>Gate.io Scanner Status</b>

✅ Status: Active
📈 Max pairs: {MAX_SYMBOLS}
🎯 Min score: {MIN_SCORE}
⏱️ Interval: {SCAN_INTERVAL//60} min
🔧 Indicators: 6 active
🏦 Exchange: Gate.io

📅 Last update: {datetime.now().strftime('%H:%M:%S')}"""
                    send_telegram(msg)
                
                elif text == '/help':
                    msg = """📚 <b>Gate.io Scanner Help</b>

<b>How it works:</b>
1. Scans all USDT pairs on Gate.io
2. Analyzes 6 technical indicators
3. Calculates confidence score (0-100)
4. Sends top signals to Telegram

<b>Indicators used:</b>
- Price Breakout (30 pts)
- Volume Explosion (25 pts)
- Trend (EMA) (15 pts)
- MACD (15 pts)
- RSI (10 pts)
- Price Change (5 pts)

<b>Score interpretation:</b>
80-100: Excellent signal
65-79: Good signal
60-64: Weak signal"""
                    send_telegram(msg)
                
                elif text == '/ping':
                    send_telegram("🏓 Pong! Gate.io scanner is running")
                
                else:
                    if text and not text.startswith('/'):
                        send_telegram(f"❓ Unknown command: {text}\nUse /help", user_id)
            
            time.sleep(1)
        except Exception as e:
            print(f"Commands error: {e}")
            time.sleep(5)

# ============================================
# التشغيل الرئيسي
# ============================================

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 STARTING GATE.IO BREAKOUT SCANNER")
    print("=" * 50)
    print(f"Time: {datetime.now()}")
    print(f"Exchange: Gate.io")
    print(f"Max pairs: {MAX_SYMBOLS}")
    print(f"Min score: {MIN_SCORE}")
    print(f"Scan interval: {SCAN_INTERVAL//60} minutes")
    print("=" * 50)
    
    # إرسال رسالة بدء التشغيل
    send_telegram("🚀 <b>Gate.io Breakout Scanner Started!</b>\n\n✅ Connected to Gate.io API\n✅ Auto-scan every 5 minutes\n✅ Sending signals to this chat")
    
    # تشغيل الماسح في thread منفصل
    scanner_thread = threading.Thread(target=start_auto_scanner, daemon=True)
    scanner_thread.start()
    
    # تشغيل معالجة الأوامر
    handle_telegram_commands()
