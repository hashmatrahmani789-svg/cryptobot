import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAILY-EMA] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
TELEGRAM_CHAT_ID = "8118939134"
MIN_MARKET_CAP   = 50_000_000
CROSS_LOOKBACK   = 3

STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "GUSD", "FRAX", "LUSD", "USDD"}

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
            filtered = [
                c for c in data
                if c.get("market_cap", 0) >= MIN_MARKET_CAP
                and c.get("symbol", "").upper() not in STABLECOINS
            ]
            coins.extend(filtered)
            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break
            page += 1
            time.sleep(2)
        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break
    log.info(f"{len(coins)} coins loaded with mcap > $50M")
    return coins

def get_candles(symbol: str, limit: int = 60):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < limit:
            return None
        closes = [float(k[4]) for k in data[:-1]]
        return closes
    except Exception:
        return None

def calc_ema(values: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def check_cross_lookback(closes: list):
    ema12 = calc_ema(closes, 12)
    ema21 = calc_ema(closes, 21)
    for i in range(-CROSS_LOOKBACK, 0):
        prev12, prev21 = ema12[i-1], ema21[i-1]
        curr12, curr21 = ema12[i], ema21[i]
        if prev12 <= prev21 and curr12 > curr21:
            return "BULLISH"
        if prev12 >= prev21 and curr12 < curr21:
            return "BEARISH"
    return None

def run_scan():
    log.info(f"Daily scan running... {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    coins = get_coins_above_mcap()
    bullish = []
    bearish = []

    for coin in coins:
        symbol = coin.get("symbol", "").upper() + "USDT"
        closes = get_candles(symbol, limit=60)
        if closes is None or len(closes) < 22:
            time.sleep(0.08)
            continue
        cross = check_cross_lookback(closes)
        if cross == "BULLISH":
            bullish.append(coin.get("symbol", "").upper())
        elif cross == "BEARISH":
            bearish.append(coin.get("symbol", "").upper())
        time.sleep(0.08)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 <b>DAILY EMA 12/21 CROSS</b>\n🕐 {now}"]

    if bullish:
        lines.append(f"\n📈 <b>BULLISH</b> (within 3 days):\n{', '.join(bullish)}")
    if bearish:
        lines.append(f"\n📉 <b>BEARISH</b> (within 3 days):\n{', '.join(bearish)}")
    if not bullish and not bearish:
        log.info("No crosses found.")
        return

    send_alert("\n".join(lines))
    log.info("Scan complete.")

def wait_until_daily_close():
    now = datetime.now(timezone.utc)
    # Daily candle closes at 00:00 UTC, scan at 00:05 UTC
    next_run = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(days=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)

if __name__ == "__main__":
    log.info("Daily EMA 12/21 Cross Signal started.")
    send_alert("✅ Daily EMA Cross bot started and running!")
    while True:
        wait_until_daily_close()
        run_scan()