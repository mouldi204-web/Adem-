#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت التداول الورقي المتكامل - نسخة واحدة
Integrated Paper Trading Bot - Single File Version
يدعم: Gate.io | Telegram Bot & Channel | Trailing Stop | Explosion Detection | Keep Alive
"""

import ccxt
import pandas as pd
import numpy as np
import time
import threading
import os
import csv
import sqlite3
import json
import requests
import schedule
import logging
import socket
import gc
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict, deque
from http.server import HTTPServer, BaseHTTPRequestHandler
import warnings

warnings.filterwarnings('ignore')

# =========================
# الإعدادات الأساسية
# =========================

# Telegram Settings (يمكن تغييرها حسب رغبتك)
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"
TELEGRAM_CHANNEL_ID = "-1001003692815602"

# Trading Settings
INITIAL_BALANCE = 1000  # $1000
TRADE_AMOUNT = 50  # $50 per trade
MAX_OPEN_TRADES = 20
PROFIT_TARGET = 5  # 5%
STOP_LOSS = -3  # -3%
TRAILING_STOP_ACTIVATION = 2  # Activate after 2% profit
TRAILING_STOP_DISTANCE = 1.5  # Trail by 1.5%

# Scanner Settings
MAX_SYMBOLS = 1500
BATCH_SIZE = 50
BATCH_DELAY = 10  # seconds between batches
API_RATE_LIMIT = 1200  # ms between calls

# Score Thresholds
SCORE_MONITOR = 100  # Monitor if score > 100
SCORE_TRADE = 120  # Trade if score > 120
EXPLOSION_THRESHOLD = 60  # Minimum 60% for explosion alert

# File Names
CSV_HIGH_SCORE = "high_score_signals.csv"
CSV_TRADES = "paper_trading_trades.csv"
CSV_PORTFOLIO = "paper_trading_portfolio.csv"
CSV_EXPLOSIONS = "explosion_signals.csv"
DB_FILE = "trading_database.db"

# =========================
# إعدادات التسجيل (Logging)
# =========================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =========================
# تهيئة المنصة
# =========================

exchange = ccxt.gateio({
    'enableRateLimit': True,
    'rateLimit': API_RATE_LIMIT,
    'options': {'defaultType': 'spot'}
})

# =========================
# Rate Limiter (تجنب الحظر)
# =========================

class RateLimiter:
    """إدارة معدل الطلبات لتجنب حظر المنصة"""
    
    def __init__(self, requests_per_second: int = 3):
        self.requests_per_second = requests_per_second
        self.request_times = deque(maxlen=requests_per_second)
        self.lock = threading.Lock()
    
    def wait(self):
        with self.lock:
            now = time.time()
            if len(self.request_times) == self.request_times.maxlen:
                oldest = self.request_times[0]
                if now - oldest < 1.0:
                    sleep_time = 1.0 - (now - oldest)
                    time.sleep(sleep_time + 0.05)
            self.request_times.append(time.time())

rate_limiter = RateLimiter()

# =========================
# المؤشرات الفنية
# =========================

class TechnicalIndicators:
    """حساب المؤشرات الفنية المتقدمة"""
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
        """حساب RSI"""
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if len(rsi) > 0 else 50
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame):
        """حساب MACD"""
        exp1 = df['c'].ewm(span=12, adjust=False).mean()
        exp2 = df['c'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd.iloc[-1], signal.iloc[-1]
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
        """حساب ADX"""
        df = df.copy()
        df['h-l'] = df['h'] - df['l']
        df['h-pc'] = abs(df['h'] - df['c'].shift(1))
        df['l-pc'] = abs(df['l'] - df['c'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        
        plus_dm = np.where((df['h'] - df['h'].shift(1)) > (df['l'].shift(1) - df['l']), 
                           np.maximum(df['h'] - df['h'].shift(1), 0), 0)
        minus_dm = np.where((df['l'].shift(1) - df['l']) > (df['h'] - df['h'].shift(1)), 
                            np.maximum(df['l'].shift(1) - df['l'], 0), 0)
        
        tr_s = df['tr'].rolling(period).sum()
        plus_di = 100 * (pd.Series(plus_dm).rolling(period).sum() / tr_s)
        minus_di = 100 * (pd.Series(minus_dm).rolling(period).sum() / tr_s)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(period).mean()
        return adx.iloc[-1] if len(adx) > 0 else 20
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20):
        """حساب Bollinger Bands"""
        middle = df['c'].rolling(period).mean()
        std = df['c'].rolling(period).std()
        upper = middle + (std * 2)
        lower = middle - (std * 2)
        return upper.iloc[-1], middle.iloc[-1], lower.iloc[-1]

# =========================
# نظام التسجيل المتقدم (سكور حتى 150)
# =========================

def calculate_score(symbol: str) -> Tuple[int, str, float]:
    """حساب السكور الفني (0-150)"""
    try:
        with rate_limiter:
            # جلب البيانات من 15 دقيقة و 4 ساعات
            df15 = pd.DataFrame(exchange.fetch_ohlcv(symbol, '15m', limit=100), 
                               columns=['t','o','h','l','c','v'])
            df4h = pd.DataFrame(exchange.fetch_ohlcv(symbol, '4h', limit=100), 
                               columns=['t','o','h','l','c','v'])
        
        if len(df15) < 50 or len(df4h) < 50:
            return 0, "", 50
        
        score = 0
        reasons = []
        
        # 1. الترند العام (30 نقطة)
        ma200 = df4h['c'].rolling(200).mean().iloc[-1]
        if df4h['c'].iloc[-1] > ma200:
            score += 30
            reasons.append("📈 TREND_UP")
        
        # 2. الزخم (25 نقطة)
        ma9 = df15['c'].rolling(9).mean().iloc[-1]
        ma21 = df15['c'].rolling(21).mean().iloc[-1]
        if df15['c'].iloc[-1] > ma9 > ma21:
            score += 25
            reasons.append("⚡ MOMENTUM")
        
        # 3. حجم التداول (20 نقطة)
        vol_avg = df15['v'].rolling(20).mean().iloc[-1]
        if df15['v'].iloc[-1] > vol_avg * 1.5:
            score += 20
            reasons.append("📊 HIGH_VOLUME")
        
        # 4. قوة الاتجاه ADX (15 نقطة)
        adx = TechnicalIndicators.calculate_adx(df15)
        if adx > 25:
            score += 15
            reasons.append("🎯 STRONG_TREND")
        
        # 5. RSI (15 نقطة)
        rsi = TechnicalIndicators.calculate_rsi(df15)
        if 30 <= rsi <= 45:
            score += 15
            reasons.append("💪 RSI_OVERSOLD")
        
        # 6. MACD (10 نقطة)
        macd, signal = TechnicalIndicators.calculate_macd(df15)
        if macd > signal:
            score += 10
            reasons.append("🟢 MACD_BULLISH")
        
        # 7. Bollinger Bands (10 نقطة)
        upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df15)
        if df15['c'].iloc[-1] <= lower * 1.02:
            score += 10
            reasons.append("📉 BB_OVERSOLD")
        
        # 8. ATR - تقلب مناسب (5 نقاط)
        atr = TechnicalIndicators.calculate_atr(df15) if hasattr(TechnicalIndicators, 'calculate_atr') else 0
        if atr:
            atr_pct = (atr / df15['c'].iloc[-1]) * 100
            if 2 <= atr_pct <= 5:
                score += 5
                reasons.append("🌊 GOOD_VOLATILITY")
        
        score = min(score, 150)
        return score, '|'.join(reasons), rsi
        
    except Exception as e:
        logger.error(f"Score error {symbol}: {e}")
        return 0, "", 50

# إضافة دالة ATR إذا لم تكن موجودة
def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """حساب Average True Range"""
    high = df['h']
    low = df['l']
    close = df['c']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr.iloc[-1] if len(atr) > 0 else 0

TechnicalIndicators.calculate_atr = staticmethod(calculate_atr)

# =========================
# نظام اكتشاف الانفجارات
# =========================

def detect_explosion(symbol: str) -> Optional[Dict]:
    """كشف الانفجارات الوشيكة"""
    try:
        with rate_limiter:
            df15 = pd.DataFrame(exchange.fetch_ohlcv(symbol, '15m', limit=100), 
                               columns=['t','o','h','l','c','v'])
        
        if len(df15) < 50:
            return None
        
        # 1. كشف انفجار الحجم
        vol_avg = df15['v'].rolling(20).mean().iloc[-1]
        vol_ratio = df15['v'].iloc[-1] / vol_avg if vol_avg > 0 else 1
        
        # 2. كشف انضغاط السعر (Bollinger Squeeze)
        upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df15)
        bb_width = (upper - lower) / middle if middle > 0 else 1
        is_squeeze = bb_width < 0.05
        
        # 3. كشف الاختراق الوشيك
        resistance = df15['h'].rolling(20).max().iloc[-1]
        current_price = df15['c'].iloc[-1]
        distance_to_resistance = ((resistance - current_price) / resistance) * 100
        
        # حساب الاحتمال الإجمالي
        probability = 0
        explosion_type = []
        
        if vol_ratio > 2:
            probability += min(vol_ratio * 20, 50)
            explosion_type.append("VOLUME")
        
        if is_squeeze:
            probability += 30
            explosion_type.append("SQUEEZE")
        
        if distance_to_resistance < 2:
            probability += 20
            explosion_type.append("BREAKOUT")
        
        if probability >= EXPLOSION_THRESHOLD:
            # حساب الصعود المتوقع
            expected_rise = 5 + (probability / 100) * 25
            expected_rise = round(min(expected_rise, 30), 1)
            
            # حساب الوقت المتوقع
            expected_time = int(60 - (probability / 100) * 50)
            expected_time = max(10, min(expected_time, 120))
            
            # مناطق الدخول المقترحة
            entry_zones = [
                {'type': 'ممتاز', 'price': current_price, 'deviation': 0},
                {'type': 'جيد', 'price': current_price * 0.99, 'deviation': -1},
                {'type': 'آمن', 'price': current_price * 0.98, 'deviation': -2}
            ]
            
            return {
                'probability': probability,
                'expected_rise': expected_rise,
                'expected_time': expected_time,
                'expected_time_text': f"{expected_time} دقيقة",
                'type': '+'.join(explosion_type),
                'entry_zones': entry_zones,
                'vol_ratio': round(vol_ratio, 1),
                'is_squeeze': is_squeeze
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Explosion error {symbol}: {e}")
        return None

# =========================
# محفظة التداول الورقي
# =========================

class PaperPortfolio:
    """محفظة التداول الورقي مع Trailing Stop"""
    
    def __init__(self):
        self.balance = INITIAL_BALANCE
        self.initial_balance = INITIAL_BALANCE
        self.open_trades = {}
        self.closed_trades = []
        self.trailing_stops = {}
        
    def can_open_trade(self) -> bool:
        """التحقق من إمكانية فتح صفقة جديدة"""
        return len(self.open_trades) < MAX_OPEN_TRADES and self.balance >= TRADE_AMOUNT
    
    def open_trade(self, symbol: str, price: float, score: int, reasons: str, explosion: Dict = None) -> bool:
        """فتح صفقة جديدة"""
        if not self.can_open_trade():
            return False
        
        trade = {
            'trade_id': f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
            'symbol': symbol,
            'entry_price': price,
            'entry_time': datetime.now(),
            'amount': TRADE_AMOUNT,
            'quantity': TRADE_AMOUNT / price,
            'score': score,
            'reasons': reasons,
            'explosion_prob': explosion['probability'] if explosion else 0,
            'highest': price,
            'lowest': price,
            'max_gain': 0,
            'max_loss': 0,
            'status': 'OPEN',
            'trailing_activated': False
        }
        
        self.open_trades[symbol] = trade
        self.balance -= TRADE_AMOUNT
        return True
    
    def update_trade_prices(self, symbol: str, current_price: float):
        """تحديث أعلى وأدنى سعر للصفقة"""
        if symbol in self.open_trades:
            trade = self.open_trades[symbol]
            current_return = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
            
            if current_price > trade['highest']:
                trade['highest'] = current_price
                trade['max_gain'] = current_return
            
            if current_price < trade['lowest']:
                trade['lowest'] = current_price
                trade['max_loss'] = current_return
    
    def check_trailing_stop(self, symbol: str, current_price: float, current_return: float) -> bool:
        """التحقق من Trailing Stop"""
        trade = self.open_trades[symbol]
        
        # تفعيل Trailing Stop عند تحقيق نسبة معينة
        if current_return >= TRAILING_STOP_ACTIVATION and not trade['trailing_activated']:
            trade['trailing_activated'] = True
            self.trailing_stops[symbol] = trade['highest'] * (1 - TRAILING_STOP_DISTANCE / 100)
            logger.info(f"🔒 تفعيل Trailing Stop لـ {symbol} عند ${self.trailing_stops[symbol]:.6f}")
        
        # التحقق من ضرب Trailing Stop
        if trade['trailing_activated'] and symbol in self.trailing_stops:
            if current_price <= self.trailing_stops[symbol]:
                return True
        
        # تحديث Trailing Stop للأعلى
        elif trade['trailing_activated'] and current_price > trade['highest']:
            self.trailing_stops[symbol] = current_price * (1 - TRAILING_STOP_DISTANCE / 100)
        
        return False
    
    def close_trade(self, symbol: str, price: float, reason: str) -> Optional[Dict]:
        """إغلاق صفقة"""
        if symbol not in self.open_trades:
            return None
        
        trade = self.open_trades[symbol]
        final_return = ((price - trade['entry_price']) / trade['entry_price']) * 100
        profit_loss = (price - trade['entry_price']) * trade['quantity']
        
        trade['exit_price'] = price
        trade['exit_time'] = datetime.now()
        trade['final_return'] = final_return
        trade['profit_loss'] = profit_loss
        trade['exit_reason'] = reason
        trade['status'] = 'CLOSED'
        
        # تحديث الرصيد
        self.balance += trade['amount'] + profit_loss
        
        # نقل إلى الصفقات المغلقة
        self.closed_trades.append(trade)
        del self.open_trades[symbol]
        
        # تنظيف Trailing Stop
        if symbol in self.trailing_stops:
            del self.trailing_stops[symbol]
        
        return trade
    
    def get_summary(self) -> Dict:
        """الحصول على ملخص المحفظة"""
        total_value = self.balance
        unrealized_pnl = 0
        
        for trade in self.open_trades.values():
            total_value += trade['amount']
        
        realized_pnl = sum(t.get('profit_loss', 0) for t in self.closed_trades)
        total_pnl = realized_pnl + unrealized_pnl
        
        winning_trades = len([t for t in self.closed_trades if t.get('final_return', 0) > 0])
        win_rate = (winning_trades / len(self.closed_trades) * 100) if self.closed_trades else 0
        
        return {
            'balance': self.balance,
            'total_value': total_value,
            'realized_pnl': realized_pnl,
            'total_pnl': total_pnl,
            'total_return_pct': (total_pnl / self.initial_balance) * 100,
            'open_trades': len(self.open_trades),
            'closed_trades': len(self.closed_trades),
            'win_rate': win_rate
        }

# تهيئة المحفظة
portfolio = PaperPortfolio()

# =========================
# بوت Telegram المتقدم
# =========================

class TelegramBot:
    """إدارة بوت Telegram والإرسال إلى القناة"""
    
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.channel_id = TELEGRAM_CHANNEL_ID
        self.last_update_id = 0
    
    def send(self, text: str, to_channel: bool = False, parse_mode: str = 'HTML') -> bool:
        """إرسال رسالة إلى البوت أو القناة"""
        chat_id = self.channel_id if to_channel else self.chat_id
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        try:
            response = requests.post(url, data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False
    
    def send_trade_signal(self, symbol: str, score: int, price: float, explosion: Dict = None):
        """إرسال إشارة تداول"""
        symbol_name = symbol.replace('/USDT', '')
        
        if explosion and explosion.get('probability', 0) >= EXPLOSION_THRESHOLD:
            # إشارة انفجار قوية
            message = f"""
💥 <b>إشارة انفجار وشيكة!</b> 💥

┌ 📊 <b>{symbol_name}</b>
├ 🎯 السكور: <code>{score}/150</code>
├ 💰 السعر: <code>${price:.6f}</code>
├ 💣 احتمال الانفجار: <code>{explosion['probability']:.0f}%</code>
├ 📈 الصعود المتوقع: <code>+{explosion['expected_rise']}%</code>
├ ⏰ الوقت المتوقع: <code>{explosion['expected_time_text']}</code>
├ 📊 نوع الإشارة: <code>{explosion['type']}</code>
│
├ 📍 مناطق الدخول:
├  ├ ممتاز: <code>${explosion['entry_zones'][0]['price']:.6f}</code>
├  ├ جيد: <code>${explosion['entry_zones'][1]['price']:.6f}</code>
├  └ آمن: <code>${explosion['entry_zones'][2]['price']:.6f}</code>
│
└ 🔥 <b>فرصة استثنائية - تحرك فوراً!</b>
            """
        else:
            # إشارة عادية
            message = f"""
📊 <b>إشارة تداول جديدة</b>

┌ 📊 <b>{symbol_name}</b>
├ 🎯 السكور: <code>{score}/150</code>
├ 💰 السعر: <code>${price:.6f}</code>
│
└ ✅ <b>فرصة تداول واعدة</b>
            """
        
        # إرسال إلى البوت
        self.send(message)
        
        # إرسال إلى القناة إذا كانت الإشارة قوية
        if score >= SCORE_TRADE or (explosion and explosion['probability'] >= 75):
            self.send(message, to_channel=True)
    
    def send_trade_update(self, trade: Dict, is_close: bool = False):
        """إرسال تحديث صفقة (فتح أو إغلاق)"""
        symbol_name = trade['symbol'].replace('/USDT', '')
        
        if is_close:
            # رسالة إغلاق صفقة
            if trade['final_return'] >= 0:
                emoji = "✅"
                status = "ربح"
            else:
                emoji = "❌"
                status = "خسارة"
            
            message = f"""
{emoji} <b>إغلاق صفقة - {status}</b> {emoji}

┌ 📊 <b>{symbol_name}</b>
├ 📈 العائد: <code>{trade['final_return']:+.2f}%</code>
├ 💰 الربح/الخسارة: <code>${trade['profit_loss']:+.2f}</code>
├ 📊 أعلى صعود: <code>+{trade['max_gain']:.1f}%</code>
├ 🚪 سبب الخروج: <code>{trade['exit_reason']}</code>
├ ⏱️ المدة: <code>{((trade['exit_time'] - trade['entry_time']).total_seconds() / 60):.0f} دقيقة</code>
│
└ ⏰ <code>{trade['exit_time'].strftime('%H:%M:%S')}</code>
            """
        else:
            # رسالة فتح صفقة
            message = f"""
🚀 <b>فتح صفقة جديدة</b> 🚀

┌ 📊 <b>{symbol_name}</b>
├ 💰 سعر الدخول: <code>${trade['entry_price']:.6f}</code>
├ 🎯 السكور: <code>{trade['score']}/150</code>
├ 💵 المبلغ: <code>${trade['amount']}</code>
├ 🎯 الهدف: <code>+{PROFIT_TARGET}%</code>
├ 🛑 وقف الخسارة: <code>{STOP_LOSS}%</code>
│
└ ⏰ <code>{trade['entry_time'].strftime('%H:%M:%S')}</code>
            """
        
        self.send(message)
    
    def send_portfolio_summary(self):
        """إرسال ملخص المحفظة"""
        summary = portfolio.get_summary()
        
        # تفاصيل الصفقات المفتوحة
        open_trades_text = ""
        for sym, trade in list(portfolio.open_trades.items())[:5]:
            open_trades_text += f"\n├ {sym.replace('/USDT', '')}: دخل ${trade['entry_price']:.4f}"
        
        message = f"""
💰 <b>ملخص المحفظة</b>

📊 <b>الإحصائيات:</b>
├ الرصيد: <code>${summary['balance']:.2f}</code>
├ القيمة الإجمالية: <code>${summary['total_value']:.2f}</code>
├ الربح المحقق: <code>${summary['realized_pnl']:+.2f}</code>
├ إجمالي الربح: <code>${summary['total_pnl']:+.2f}</code>
├ العائد الإجمالي: <code>{summary['total_return_pct']:+.1f}%</code>
│
├ صفقات مفتوحة: <code>{summary['open_trades']}/{MAX_OPEN_TRADES}</code>
├ صفقات مغلقة: <code>{summary['closed_trades']}</code>
└ نسبة الربح: <code>{summary['win_rate']:.1f}%</code>
{open_trades_text}
📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
        """
        self.send(message)

telegram_bot = TelegramBot()

# =========================
# الماسح الضوئي المتقدم (1500 عملة)
# =========================

class AdvancedScanner:
    """الماسح الضوئي لـ 1500 عملة مع تقسيم ذكي"""
    
    def __init__(self):
        self.results = []
        self.processed = 0
        self.scan_count = 0
    
    def get_symbols(self) -> List[str]:
        """الحصول على قائمة العملات (حتى 1500)"""
        try:
            markets = exchange.load_markets()
            symbols = [s for s in markets.keys() if '/USDT' in s]
            
            # تصفية العملات المستقرة
            stable_coins = ['USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'FDUSD', 'USDD']
            symbols = [s for s in symbols if not any(stable in s for stable in stable_coins)]
            
            # تصفية العملات الجديدة (أقل من 30 يوم) إذا أمكن
            symbols = symbols[:MAX_SYMBOLS]
            
            logger.info(f"✅ تم تحميل {len(symbols)} عملة للمسح")
            return symbols
            
        except Exception as e:
            logger.error(f"Error getting symbols: {e}")
            return []
    
    def scan_batch(self, symbols: List[str], batch_num: int, total_batches: int) -> List[Dict]:
        """مسح مجموعة من العملات"""
        batch_results = []
        
        for i, symbol in enumerate(symbols):
            try:
                # حساب السكور
                score, reasons, rsi = calculate_score(symbol)
                
                # كشف الانفجار
                explosion = detect_explosion(symbol)
                
                # إذا كان السكور مرتفع أو انفجار محتمل
                if score >= SCORE_MONITOR or (explosion and explosion['probability'] >= EXPLOSION_THRESHOLD):
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    
                    result = {
                        'symbol': symbol,
                        'score': score,
                        'price': price,
                        'explosion': explosion,
                        'timestamp': datetime.now()
                    }
                    batch_results.append(result)
                    
                    logger.info(f"[{batch_num}/{total_batches}] {symbol}: Score={score}, Explosion={explosion['probability'] if explosion else 0}%")
                    
                    # حفظ في CSV
                    self.save_to_csv(result)
                    
                    # إرسال إشارة إذا كانت قوية جداً
                    if score >= SCORE_TRADE:
                        telegram_bot.send_trade_signal(symbol, score, price, explosion)
                        
                        # فتح صفقة تداول ورقي
                        if portfolio.can_open_trade():
                            if portfolio.open_trade(symbol, price, score, reasons, explosion):
                                trade = portfolio.open_trades[symbol]
                                telegram_bot.send_trade_update(trade, is_close=False)
                                logger.info(f"✅ تم فتح صفقة: {symbol}")
                    
                    elif explosion and explosion['probability'] >= 75:
                        telegram_bot.send_trade_signal(symbol, score, price, explosion)
                
                # تأخير بين الطلبات
                time.sleep(API_RATE_LIMIT / 1000)
                self.processed += 1
                
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
                continue
        
        return batch_results
    
    def save_to_csv(self, result: Dict):
        """حفظ النتيجة في ملف CSV"""
        file_exists = os.path.exists(CSV_HIGH_SCORE)
        
        with open(CSV_HIGH_SCORE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            if not file_exists or os.path.getsize(CSV_HIGH_SCORE) == 0:
                writer.writerow(['Time', 'Symbol', 'Score', 'Price', 'Explosion_Prob', 'Explosion_Rise', 'Explosion_Type', 'Status'])
            
            explosion = result.get('explosion')
            writer.writerow([
                result['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                result['symbol'],
                result['score'],
                result['price'],
                explosion['probability'] if explosion else 0,
                explosion['expected_rise'] if explosion else 0,
                explosion['type'] if explosion else '',
                'ACTIVE'
            ])
    
    def scan_all(self):
        """مسح جميع العملات"""
        self.scan_count += 1
        symbols = self.get_symbols()
        total = len(symbols)
        
        logger.info(f"🔍 بدء المسح #{self.scan_count} لـ {total} عملة...")
        telegram_bot.send(f"🔍 <b>بدء المسح الشامل #{self.scan_count}</b>\n📊 عدد العملات: {total}\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        
        # تقسيم إلى مجموعات
        batches = [symbols[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
        
        all_results = []
        
        for batch_num, batch in enumerate(batches, 1):
            logger.info(f"📦 معالجة المجموعة {batch_num}/{len(batches)} ({len(batch)} عملة)")
            
            results = self.scan_batch(batch, batch_num, len(batches))
            all_results.extend(results)
            
            # تأخير بين المجموعات
            if batch_num < len(batches):
                logger.info(f"⏳ انتظار {BATCH_DELAY} ثانية...")
                time.sleep(BATCH_DELAY)
        
        # إرسال التقرير النهائي
        self.send_final_report(all_results)
        
        return all_results
    
    def send_final_report(self, results: List[Dict]):
        """إرسال التقرير النهائي"""
        high_score = [r for r in results if r['score'] >= SCORE_TRADE]
        explosions = [r for r in results if r.get('explosion') and r['explosion']['probability'] >= 75]
        
        summary = portfolio.get_summary()
        
        report = f"""
✅ <b>اكتمل المسح #{self.scan_count}!</b>

📊 <b>النتائج:</b>
├ عملات تم فحصها: <code>{self.processed}</code>
├ عملات بسكور عالي: <code>{len(high_score)}</code>
├ انفجارات محتملة: <code>{len(explosions)}</code>
│
💰 <b>المحفظة:</b>
├ الرصيد: <code>${summary['balance']:.2f}</code>
├ صفقات مفتوحة: <code>{summary['open_trades']}/{MAX_OPEN_TRADES}</code>
├ صفقات مغلقة: <code>{summary['closed_trades']}</code>
├ نسبة الربح: <code>{summary['win_rate']:.1f}%</code>
│
└ ⏰ <code>{datetime.now().strftime('%H:%M:%S')}</code>
        """
        
        telegram_bot.send(report)
        
        # إرسال أفضل نتيجة إلى القناة
        if high_score:
            best = high_score[0]
            channel_msg = f"""
🏆 <b>أفضل إشارة في المسح #{self.scan_count}</b>

┌ 📊 <b>{best['symbol'].replace('/USDT', '')}</b>
├ 🎯 السكور: <code>{best['score']}/150</code>
├ 💰 السعر: <code>${best['price']:.6f}</code>
│
└ 🔥 <b>فرصة تداول ممتازة</b>
            """
            telegram_bot.send(channel_msg, to_channel=True)

# =========================
# مراقبة الصفقات المفت
