import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [1H-4H-CROSS] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

import os

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MIN_MARKET_CAP   = 200_000_000
EMA_FAST         = 12
EMA_SLOW         = 21
VOLUME_MA_PERIOD = 20
CROSS_LOOKBACK   = 12
CHECK_INTERVAL   = 300  # check every 5 minutes


# =========================
# TELEGRAM
# =========================
def send_alert(message):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=15
        )
        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


# =========================
# COINGECKO — GET COINS ABOVE $200M MCAP
# =========================
def get_coins():
    coins = []
    page = 1
    while True:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": False
                },
                timeout=20
            )
            data = r.json()
            if not isinstance(data, list):
                log.error(f"CoinGecko bad response: {data}")
                time.sleep(10)
                break
            if not data:
                break
            filtered = [c for c in data if c.get("market_cap", 0) >= MIN_MARKET_CAP]
            coins.extend(filtered)
            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break
            page += 1
            time.sleep(1.5)
        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break
    log.info(f"{len(coins)} coins loaded with mcap > $200M")
    return coins


# =========================
# BINANCE — GET CANDLES
# =========================
def get_candles(symbol, interval, limit=120):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None, None
        closes  = [float(x[4]) for x in data[:-1]]
        volumes = [float(x[5]) for x in data[:-1]]
        return closes, volumes
    except:
        return None, None


# =========================
# EMA CALCULATION
# =========================
def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


# =========================
# VOLUME ABOVE MA CHECK
# =========================
def volume_above_ma(volumes, period=VOLUME_MA_PERIOD):
    if len(volumes) < period + 1:
        return False
    ma = sum(volumes[-(period + 1):-1]) / period
    return volumes[-1] > ma


# =========================
# CHECK SIGNAL
# =========================
def check_signal(closes, volumes):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    for i in range(1, CROSS_LOOKBACK + 1):
        curr_idx = -i
        prev_idx = -(i + 1)

        prev_fast = ema_fast[prev_idx]
        prev_slow = ema_slow[prev_idx]
        curr_fast = ema_fast[curr_idx]
        curr_slow = ema_slow[curr_idx]

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if volume_above_ma(volumes):
                return "BULLISH", i
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            if volume_above_ma(volumes):
                return "BEARISH", i

    return None, None


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(coins, interval):
    bullish = []
    bearish = []

    for coin in coins:
        ticker = coin.get("symbol", "").upper()
        symbol = ticker + "USDT"

        closes, volumes = get_candles(symbol, interval)

        if closes is None:
            symbol = ticker + "BTC"
            closes, volumes = get_candles(symbol, interval)

        if closes is None:
            continue

        direction, candles_ago = check_signal(closes, volumes)

        if direction is None:
            continue

        log.info(f"{symbol} [{interval}] {direction} ({candles_ago}c ago)")

        if direction == "BULLISH":
            bullish.append(ticker)
        else:
            bearish.append(ticker)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# BUILD MESSAGE
# =========================
def build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str):
    lines = [
        f"📊 <b>EMA 12/21 — Cross Alert</b>",
        f"━━━━━━━━━━━━━━━━",
    ]

    if bullish_1h or bearish_1h:
        lines.append(f"\n⏱ <b>1H Timeframe</b>")
        if bullish_1h:
            coins_str = "  •  ".join(bullish_1h)
            lines.append(f"📈 <b>Bullish</b>\n{coins_str}")
        if bearish_1h:
            coins_str = "  •  ".join(bearish_1h)
            lines.append(f"📉 <b>Bearish</b>\n{coins_str}")

    if bullish_4h or bearish_4h:
        lines.append(f"\n⏱ <b>4H Timeframe</b>")
        if bullish_4h:
            coins_str = "  •  ".join(bullish_4h)
            lines.append(f"📈 <b>Bullish</b>\n{coins_str}")
        if bearish_4h:
            coins_str = "  •  ".join(bearish_4h)
            lines.append(f"📉 <b>Bearish</b>\n{coins_str}")

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# STARTUP SCAN — catches any crosses in last 12 candles immediately
# =========================
def startup_scan(coins):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info("Startup scan — checking last 12 candles...")

    bullish_1h, bearish_1h = scan_timeframe(coins, "1h")
    bullish_4h, bearish_4h = scan_timeframe(coins, "4h")

    if any([bullish_1h, bearish_1h, bullish_4h, bearish_4h]):
        msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
        send_alert(msg)
        log.info("Startup scan complete — signals found.")
    else:
        log.info("Startup scan complete — no signals.")


# =========================
# CHECK IF A CANDLE JUST CLOSED
# =========================
def candle_just_closed(interval):
    now = datetime.now(timezone.utc)
    if interval == "1h":
        return now.minute < 2
    if interval == "4h":
        return now.hour % 4 == 0 and now.minute < 2
    return False


# =========================
# MAIN LOOP
# =========================
def run():
    log.info("1H 4H EMA Cross Scanner started.")
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nScanning at 1H + 4H candle close 24/7.")

    coins = get_coins()
    last_coin_refresh = datetime.now(timezone.utc)

    # scan immediately on startup
    startup_scan(coins)

    while True:
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M UTC")

        if (now - last_coin_refresh).total_seconds() > 3600:
            coins = get_coins()
            last_coin_refresh = now

        bullish_1h, bearish_1h = [], []
        bullish_4h, bearish_4h = [], []

        if candle_just_closed("1h"):
            log.info("1H candle closed — scanning...")
            bullish_1h, bearish_1h = scan_timeframe(coins, "1h")

        if candle_just_closed("4h"):
            log.info("4H candle closed — scanning...")
            bullish_4h, bearish_4h = scan_timeframe(coins, "4h")

        if any([bullish_1h, bearish_1h, bullish_4h, bearish_4h]):
            msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
            send_alert(msg)
            log.info("Signals sent.")
        else:
            if candle_just_closed("1h") or candle_just_closed("4h"):
                log.info("Scan complete — no signals.")

        time.sleep(CHECK_INTERVAL)


# =========================
# START
# =========================
if __name__ == "__main__":
    run()