import os
import time
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA50-REJECT] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MIN_MARKET_CAP   = 500_000_000

def send_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            log.error(f"Telegram failed: {res.status_code} {res.text}")
    except Exception as e:
        log.error(f"Telegram error: {e}")

def get_coins_above_mcap():
    coins = []
    page = 1
    while True:
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page, "sparkline": False}
            res = requests.get(url, params=params, timeout=15)
            data = res.json()
            if not data:
                break
            filtered = [c for c in data if c.get("market_cap", 0) >= MIN_MARKET_CAP]
            coins.extend(filtered)
            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break
            page += 1
            time.sleep(2)
        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break
    log.info(f"{len(coins)} coins loaded with mcap > $500M")
    return coins

def get_candles(symbol: str, interval: str, limit: int = 60):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < limit:
            return None
        candles = [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in data[:-1]]
        return candles
    except Exception:
        return None

def calc_ema(values: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def check_rejection(candles: list):
    closes = [c["close"] for c in candles]
    ema50  = calc_ema(closes, 50)
    last         = candles[-1]
    last_ema     = ema50[-1]
    prev_close   = candles[-2]["close"]
    prev_ema     = ema50[-2]
    candle_low   = last["low"]
    candle_high  = last["high"]
    candle_close = last["close"]
    touch_threshold = last_ema * 0.005
    bullish = (candle_low <= last_ema + touch_threshold and candle_close > last_ema and prev_close <= prev_ema * 1.01)
    bearish = (candle_high >= last_ema - touch_threshold and candle_close < last_ema and prev_close >= prev_ema * 0.99)
    if bullish:
        return "BULLISH", last_ema, candle_close
    if bearish:
        return "BEARISH", last_ema, candle_close
    return None, None, None

def scan_timeframe(coins: list, interval: str, label: str):
    bullish = []
    bearish = []
    for coin in coins:
        symbol = coin.get("symbol", "").upper() + "USDT"
        candles = get_candles(symbol, interval, limit=60)
        if candles is None or len(candles) < 52:
            time.sleep(0.08)
            continue
        signal, ema_val, close_val = check_rejection(candles)
        name = coin.get("symbol", "").upper()
        if signal == "BULLISH":
            bullish.append((name, ema_val, close_val))
        elif signal == "BEARISH":
            bearish.append((name, ema_val, close_val))
        time.sleep(0.08)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if bullish:
        lines = "\n".join(f"• <b>{n}</b> | EMA50: {e:.4f} | Close: {c:.4f}" for n, e, c in bullish)
        send_alert(f"📈 <b>50 EMA BULLISH REJECTION [{label}]</b>\n🕐 {now}\n\n{lines}\n\n✅ Wick touched 50 EMA, candle closed <b>above</b>")
        log.info(f"[{label}] Bullish rejections: {[x[0] for x in bullish]}")
    if bearish:
        lines = "\n".join(f"• <b>{n}</b> | EMA50: {e:.4f} | Close: {c:.4f}" for n, e, c in bearish)
        send_alert(f"📉 <b>50 EMA BEARISH REJECTION [{label}]</b>\n🕐 {now}\n\n{lines}\n\n❌ Wick touched 50 EMA, candle closed <b>below</b>")
        log.info(f"[{label}] Bearish rejections: {[x[0] for x in bearish]}")
    if not bullish and not bearish:
        log.info(f"[{label}] No rejections found.")

def run_scan():
    log.info(f"Scanning... {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    coins = get_coins_above_mcap()
    scan_timeframe(coins, "1h", "1H")
    scan_timeframe(coins, "4h", "4H")
    log.info("Scan complete.")

def wait_until_next_hour():
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=5, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)

if __name__ == "__main__":
    log.info("50 EMA Rejection Signal started.")
    send_alert("✅ <b>EMA50-REJECT Signal is live!</b>\nBot started and connected to Telegram successfully.")
    while True:
        wait_until_next_hour()
        run_scan()