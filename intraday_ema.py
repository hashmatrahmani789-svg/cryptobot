import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [INTRADAY-EMA] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv("8611090872:AAH5ztW9MMovKNAXZ2RyCzbJANysvrSefHk")
TELEGRAM_CHAT_ID = os.getenv("8118939134")
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

def get_candles(symbol: str, interval: str, limit: int = 30):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < limit:
            return None, None
        # Exclude last candle (unclosed)
        closes  = [float(k[4]) for k in data[:-1]]
        volumes = [float(k[5]) for k in data[:-1]]
        return closes, volumes
    except Exception:
        return None, None

def calc_ema(values: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def volume_above_ma(volumes: list, period: int = 20) -> bool:
    if len(volumes) < period + 1:
        return False
    vol_ma = sum(volumes[-period-1:-1]) / period
    return volumes[-1] > vol_ma

def check_cross(closes: list):
    ema12 = calc_ema(closes, 12)
    ema21 = calc_ema(closes, 21)
    prev12, prev21 = ema12[-2], ema21[-2]
    curr12, curr21 = ema12[-1], ema21[-1]
    if prev12 <= prev21 and curr12 > curr21:
        return "BULLISH"
    if prev12 >= prev21 and curr12 < curr21:
        return "BEARISH"
    return None

def scan_timeframe(coins: list, interval: str, label: str):
    bullish = []
    bearish = []
    for coin in coins:
        symbol = coin.get("symbol", "").upper() + "USDT"
        closes, volumes = get_candles(symbol, interval, limit=30)
        if closes is None or len(closes) < 22:
            time.sleep(0.08)
            continue
        cross = check_cross(closes)
        if cross and volume_above_ma(volumes):
            name = coin.get("symbol", "").upper()
            if cross == "BULLISH":
                bullish.append(name)
            else:
                bearish.append(name)
        time.sleep(0.08)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if bullish:
        send_alert(f"📈 <b>EMA 12/21 BULLISH CROSS [{label}]</b>\n🕐 {now}\n\n<b>Coins:</b> {', '.join(bullish)}\n\n✅ EMA 12 crossed <b>above</b> EMA 21\n📊 Volume confirmed above 20-period MA")
        log.info(f"[{label}] Bullish: {bullish}")
    if bearish:
        send_alert(f"📉 <b>EMA 12/21 BEARISH CROSS [{label}]</b>\n🕐 {now}\n\n<b>Coins:</b> {', '.join(bearish)}\n\n❌ EMA 12 crossed <b>below</b> EMA 21\n📊 Volume confirmed above 20-period MA")
        log.info(f"[{label}] Bearish: {bearish}")
    if not bullish and not bearish:
        log.info(f"[{label}] No crosses found.")
        send_alert(f"🔍 INTRADAY EMA [{label}] — no crosses found at {now}")

def run_scan():
    log.info(f"TOKEN: {TELEGRAM_TOKEN[:15] if TELEGRAM_TOKEN else 'IS NONE ⚠️'}")
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
    log.info("Intraday EMA 12/21 Cross Signal started.")
    send_alert("✅ Intraday EMA bot started and running!")
    while True:
        wait_until_next_scan()
        run_scan()