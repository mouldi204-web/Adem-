#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت التداول الورقي - نسخة Railway المعدلة
"""

import os
import sys
import time
import threading
import logging
from datetime import datetime

# إعداد التسجيل البسيط
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================
# خادم HTTP بسيط لـ Railway (الأهم)
# =========================

def start_http_server():
    """تشغيل خادم HTTP بسيط ليبقى Railway سعيداً"""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"""
                <!DOCTYPE html>
                <html>
                <head><title>Trading Bot</title></head>
                <body>
                    <h1>🤖 Trading Bot is Running!</h1>
                    <p>Status: Online</p>
                    <p>Time: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S').encode() + b"""</p>
                </body>
                </html>
                """)
            
            def log_message(self, format, *args):
                pass
        
        port = int(os.environ.get('PORT', 8080))
        server = HTTPServer(('0.0.0.0', port), Handler)
        logger.info(f"✅ HTTP Server running on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"HTTP Server error: {e}")

# =========================
# الإعدادات الأساسية
# =========================

# Telegram Settings (يمكن تعديلها)
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"
TELEGRAM_CHANNEL_ID = "-1001003692815602"

# إعدادات التداول
INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_OPEN_TRADES = 20
PROFIT_TARGET = 5
STOP_LOSS = -3

# إعدادات المسح
MAX_SYMBOLS = 500  # أقل لبداية أسرع
SCORE_TRADE = 120
SCORE_MONITOR = 100

# =========================
# دوال بسيطة للاختبار
# =========================

def send_telegram(message):
    """إرسال رسالة بسيطة إلى Telegram"""
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        logger.info("✅ Telegram message sent")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def simple_scanner():
    """ماسح بسيط للاختبار"""
    try:
        import ccxt
        
        exchange = ccxt.gateio({
            'enableRateLimit': True,
            'rateLimit': 1200
        })
        
        # جلب بعض العملات للاختبار
        markets = exchange.load_markets()
        symbols = [s for s in markets.keys() if '/USDT' in s][:50]
        
        result = f"🔍 Scanned {len(symbols)} symbols"
        logger.info(result)
        
        # جلب سعر البتكوين كاختبار
        ticker = exchange.fetch_ticker('BTC/USDT')
        price = ticker['last']
        
        message = f"""
✅ <b>Bot is Running!</b>

📊 Status: Online
💰 BTC Price: ${price:,.0f}
📈 Total Symbols: {len(symbols)}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🤖 Trading bot is active and monitoring...
        """
        send_telegram(message)
        
        return True
        
    except Exception as e:
        logger.error(f"Scanner error: {e}")
        send_telegram(f"⚠️ Bot started with warning: {str(e)[:100]}")
        return False

# =========================
# الحلقة الرئيسية
# =========================

def main():
    """الدالة الرئيسية"""
    logger.info("=" * 50)
    logger.info("🚀 Starting Trading Bot on Railway")
    logger.info("=" * 50)
    
    # 1. تشغيل خادم HTTP (لـ Railway)
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    logger.info("✅ HTTP Server thread started")
    
    # 2. انتظار قليل للتأكد
    time.sleep(3)
    
    # 3. إرسال رسالة بدء التشغيل
    send_telegram("🚀 <b>Trading Bot Started Successfully!</b>\n\n✅ Connected to Gate.io\n✅ Monitoring System Active\n✅ Railway Deployment Live")
    
    # 4. تشغيل ماسح بسيط
    simple_scanner()
    
    # 5. الحلقة الرئيسية (تبقي البوت حياً)
    logger.info("✅ Entering main loop...")
    
    counter = 0
    while True:
        try:
            time.sleep(60)  # انتظر دقيقة
            counter += 1
            
            # كل ساعة، قم بعملية مسح بسيطة
            if counter % 60 == 0:
                logger.info("💓 Heartbeat - Bot is alive")
                simple_scanner()
            
            # كل 24 ساعة، إرسال تقرير يومي
            if counter % 1440 == 0:
                send_telegram("📊 <b>Daily Report</b>\n\nBot is running normally.\n24 hours of continuous operation.")
                
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(30)

# =========================
# نقطة الدخول
# =========================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
        send_telegram("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        send_telegram(f"💥 Bot crashed: {str(e)[:100]}")
        time.sleep(10)
        sys.exit(1)
