#!/usr/bin/env python3
import os
import time
import json
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import threading

TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
CHAT_ID = "5067771509"

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        html = '<html><body><h1>Trading Bot</h1><p>Status: ONLINE</p><p>Time: ' + now + '</p></body></html>'
        self.wfile.write(html.encode('utf-8'))
    def log_message(self, format, *args):
        pass

def start_server():
    port = int(os.environ.get('PORT', 8080))
    HTTPServer(('0.0.0.0', port), SimpleHandler).serve_forever()

def send_msg(text):
    try:
        url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
        data = json.dumps({'chat_id': CHAT_ID, 'text': text}).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print('Error:', e)

def get_btc():
    try:
        url = 'https://api.gateio.ws/api/v4/spot/tickers'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
            for item in data:
                if item['currency_pair'] == 'BTC_USDT':
                    return float(item['last'])
        return 0
    except:
        return 0

if __name__ == '__main__':
    threading.Thread(target=start_server, daemon=True).start()
    time.sleep(2)
    send_msg('✅ Bot Started!')
    while True:
        btc = get_btc()
        if btc:
            print(f'BTC: ${btc:,.0f}')
        time.sleep(60)
