import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA50-REJECTION] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
TELEGRAM_CHAT_ID = "8118939134"
MIN_MARKET_CAP   = 200_000_000

def send_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram failed: {res.status_code} {res.text}")
    except Exception as e:
        log.error(f"Telegram error: {e}")

def get_coins_above_mcap():
    coins = []
    page = 1
    while True:
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": page,
                "sparkline": False
            }
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
    log.info(f"{len(coins)} coins loaded with mcap > $200M")
    return coins

def get_candles(symbol: str, interval: str, limit: int = 60):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < limit:
            return None
        return [
            {
                "open":  float(k[1]),
                "high":  float(k[2]),
                "low":   float(k[3]),
                "close": float(k[4]),
            }
            for k in data[:-1]  # exclude unclosed candle
        ]
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

    candle = candles[-1]
    ema    = ema50[-1]

    # Bullish: wick went below EMA, closed above
    if candle["low"] <= ema and candle["close"] > ema:
        return "BULLISH"
    # Bearish: wick went above EMA, closed below
    if candle["high"] >= ema and candle["close"] < ema:
        return "BEARISH"
    return None

def scan_timeframe(coins: list, interval: str, label: str):
    bullish = []
    bearish = []
    for coin in coins:
        symbol = coin.get("symbol", "").upper() + "USDT"
        candles = get_candles(symbol, interval, limit=60)
        if candles is None or len(candles) < 51:
            time.sleep(0.08)
            continue
        rejection = check_rejection(candles)
        if rejection == "BULLISH":
            bullish.append(coin.get("symbol", "").upper())
        elif rejection == "BEARISH":
            bearish.append(coin.get("symbol", "").upper())
        time.sleep(0.08)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 <b>EMA 50 REJECTION [{label}]</b>\n🕐 {now}"]

    if bullish:
        lines.append(f"\n📈 <b>BULLISH REJECTION:</b>\n{', '.join(bullish)}")
    if bearish:
        lines.append(f"\n📉 <b>BEARISH REJECTION:</b>\n{', '.join(bearish)}")
    if not bullish and not bearish:
        return

    send_alert("\n".join(lines))

def run_scan():
    log.info(f"Scanning... {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    coins = get_coins_above_mcap()
    scan_timeframe(coins, "1h", "1H")
    scan_timeframe(coins, "4h", "4H")
    log.info("Scan complete.")

def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=5, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)

if __name__ == "__main__":
    log.info("EMA 50 Rejection Signal started.")
    send_alert("✅ EMA 50 Rejection bot started and running!")
    while True:
        wait_until_next_scan()
        run_scan()