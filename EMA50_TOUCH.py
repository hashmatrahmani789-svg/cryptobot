import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA50-TOUCH] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
MIN_MARKET_CAP    = 200_000_000
EMA_PERIOD        = 50
SCAN_INTERVAL_M   = 15


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
                headers={"x-cg-demo-api-key": COINGECKO_API_KEY},
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
                log.warning(f"CoinGecko bad response: {data}")
                time.sleep(10)
                continue
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
    log.info(f"{len(coins)} coins loaded from CoinGecko")
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
        if not isinstance(data, list) or len(data) < 60:
            return None
        candles = [
            {
                "open":  float(x[1]),
                "high":  float(x[2]),
                "low":   float(x[3]),
                "close": float(x[4]),
            }
            for x in data[:-1]
        ]
        return candles
    except:
        return None


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
# SIGNAL 1 — WICK TOUCH
# Bullish: low wicked into/below EMA but closed above
# Bearish: high wicked into/above EMA but closed below
# =========================
def check_wick_touch(candles, ema):
    c   = candles[-1]
    e   = ema[-1]
    tol = e * 0.002

    if c["low"] <= e + tol and c["close"] > e:
        return "BULLISH"
    if c["high"] >= e - tol and c["close"] < e:
        return "BEARISH"
    return None


# =========================
# SIGNAL 2 — PRICE HELD
# Bullish: candle body sitting on EMA from above (within 0.5%)
# Bearish: candle body sitting under EMA from below (within 0.5%)
# =========================
def check_held(candles, ema):
    c   = candles[-1]
    e   = ema[-1]
    tol = e * 0.005

    if c["close"] >= e and c["close"] <= e + tol and c["open"] >= e:
        return "BULLISH"
    if c["close"] <= e and c["close"] >= e - tol and c["open"] <= e:
        return "BEARISH"
    return None


# =========================
# SIGNAL 3 — RECLAIM
# Bullish: previous candle closed below EMA, current closed above
# Bearish: previous candle closed above EMA, current closed below
# =========================
def check_reclaim(candles, ema):
    prev   = candles[-2]
    curr   = candles[-1]
    e_prev = ema[-2]
    e_curr = ema[-1]

    if prev["close"] < e_prev and curr["close"] > e_curr:
        return "BULLISH"
    if prev["close"] > e_prev and curr["close"] < e_curr:
        return "BEARISH"
    return None


# =========================
# CHECK ALL 3 SIGNALS FOR ONE COIN
# =========================
def check_coin(candles):
    closes = [c["close"] for c in candles]
    ema    = calc_ema(closes, EMA_PERIOD)

    results = []
    wick    = check_wick_touch(candles, ema)
    held    = check_held(candles, ema)
    reclaim = check_reclaim(candles, ema)

    if wick:
        results.append((wick, "wick"))
    if held:
        results.append((held, "held"))
    if reclaim:
        results.append((reclaim, "reclaim"))

    return results


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(coins, interval):
    bullish = []
    bearish = []

    for coin in coins:
        ticker = coin.get("symbol", "").upper()
        symbol = ticker + "USDT"

        candles = get_candles(symbol, interval)
        if candles is None:
            symbol = ticker + "BTC"
            candles = get_candles(symbol, interval)
        if candles is None:
            continue

        signals = check_coin(candles)
        for direction, label in signals:
            log.info(f"{symbol} [{interval}] {direction} ({label})")
            if direction == "BULLISH":
                bullish.append((ticker, label))
            else:
                bearish.append((ticker, label))

        time.sleep(0.05)

    return bullish, bearish


# =========================
# BUILD MESSAGE
# =========================
def build_message(results_by_tf, now_str):
    has_signals = any(bull or bear for bull, bear in results_by_tf.values())

    if not has_signals:
        return (
            f"🔍 <b>EMA 50 Scan</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"No interactions found on 15M, 1H or 4H\n\n"
            f"🕐 {now_str}"
        )

    lines = ["🎯 <b>EMA 50 — Interaction Alert</b>", "━━━━━━━━━━━━━━━━"]
    tf_labels = {"15m": "15M", "1h": "1H", "4h": "4H"}

    for interval, (bullish, bearish) in results_by_tf.items():
        if not bullish and not bearish:
            continue
        label = tf_labels.get(interval, interval.upper())
        lines.append(f"\n⏱ <b>{label} Timeframe</b>")
        if bullish:
            coins_str = "  •  ".join(f"{t} <i>({s})</i>" for t, s in bullish)
            lines.append(f"📈 <b>Bullish</b>\n{coins_str}")
        if bearish:
            coins_str = "  •  ".join(f"{t} <i>({s})</i>" for t, s in bearish)
            lines.append(f"📉 <b>Bearish</b>\n{coins_str}")

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# MAIN SCAN
# =========================
def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")
    coins = get_coins()
    results = {}
    for interval in ["15m", "1h", "4h"]:
        bullish, bearish = scan_timeframe(coins, interval)
        results[interval] = (bullish, bearish)
    msg = build_message(results, now_str)
    send_alert(msg)
    log.info("Scan complete.")


# =========================
# 15 MINUTE TIMER
# =========================
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    minutes = now.minute
    next_minute = (minutes // SCAN_INTERVAL_M + 1) * SCAN_INTERVAL_M
    if next_minute >= 60:
        next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_run = now.replace(minute=next_minute, second=0, microsecond=0)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


# =========================
# START
# =========================
if __name__ == "__main__":
    log.info("EMA 50 Interaction Scanner started.")
    send_alert("✅ <b>EMA 50 Scanner Online</b>\nScanning 15M + 1H + 4H every 15 minutes.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()