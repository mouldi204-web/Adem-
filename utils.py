import requests
import time

# =========================
# SAFE REQUEST
# =========================
def safe_get(url):
    try:
        return requests.get(url).json()
    except:
        return None

# =========================
# BATCH SPLIT
# =========================
def chunk(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i+size]

# =========================
# SLEEP SAFE
# =========================
def safe_sleep(sec):
    time.sleep(sec)
