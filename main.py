import ccxt
import time, pandas as pd, numpy as np, os, csv, threading
from datetime import datetime
import requests

# ==========================================
# CONFIG
# ==========================================
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TARGET_CHATS = ["5067771509", "-1002446777595"]

exchange = ccxt.gateio({'enableRateLimit': True})

FILE_SIGNALS = 'signals_log.csv'
FILE_ACTIVE = 'active_trades.csv'
FILE_HISTORY = 'trade_history.csv'

for f, h in [
    (FILE_SIGNALS, ['Time', 'Symbol', 'Score', 'Price', 'RSI', 'Body_Ratio']),
    (FILE_ACTIVE, ['Entry_Time', 'Symbol', 'Entry_Price', 'Current_SL', 'Highest_Price']),
    (FILE_HISTORY, ['Exit_Time', 'Symbol', 'Entry_Price', 'Exit_Price', 'PNL%', 'Max_Rise%'])
]:
    if not os.path.exists(f):
        with open(f, 'w', newline='') as file:
            csv.writer(file).writerow(h)

active_virtual_trades = {}
MAX_VIRTUAL_TRADES = 150
BOOT_TIME = datetime.now()

# ==========================================
# INDICATORS
# ==========================================
def calculate_metrics(df):
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_u'] = df['sma20'] + (df['std20'] * 2)

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss.replace(0, 0.001))))

    candle_range = df['high'] - df['low']
    body_range = abs(df['close'] - df['open'])
    df['body_ratio'] = (body_range / candle_range.replace(0, 0.001)) * 100

    tr = pd.concat([
        df['high'] - df['low'],
        abs(df['high'] - df['close'].shift()),
        abs(df['low'] - df['close'].shift())
    ], axis=1).max(axis=1)

    df['atr'] = tr.rolling(14).mean()

    return df


# ==========================================
# V3 AI SCORING ENGINE
# ==========================================
def get_final_score(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0

    # Breakout early
    if last['close'] > last['bb_u'] * 0.965:
        score += 20

    # Momentum acceleration
    if last['close'] > prev['close']:
        score += 10

    if (last['close'] - prev
