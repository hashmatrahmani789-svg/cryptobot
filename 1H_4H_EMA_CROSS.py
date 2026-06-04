import os
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

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
MIN_MARKET_CAP    = 200_000_000
EMA_FAST          = 12
EMA_SLOW          = 21
VOLUME_MA_PERIOD  = 20
CROSS_LOOKBACK    = 12
COIN_CACHE_HOURS  = 24

_coin_cache      = {}
_coin_cache_time = None


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
# COINGECKO — CACHED COIN LIST
# refreshes once every 24 hours
# =========================
def get_coins():
    global _coin_cache, _coin_cache_time
    now = datetime.now(timezone.utc)

    if _coin_cache and _coin_cache_time:
        age_hours = (now - _coin_cache_time).total_seconds() / 3600
        if age_hours < COIN_CACHE_HOURS:
            log.info(f"{len(_coin_cache)} coins from cache")
            return _coin_cache

    coins = {}
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
            for c in data:
                mcap = c.get("market_cap", 0)
                if mcap >= MIN_MARKET_CAP:
                    ticker = c.get("symbol", "").upper()
                    coins[ticker] = {
                        "market_cap": mcap,
                        "price_change_24h": c.get("price_change_percentage_24h", 0),
                        "current_price": c.get("current_price", 0)
                    }
            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break
            page += 1
            time.sleep(2)
        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break

    _coin_cache = coins
    _coin_cache_time = now
    log.info(f"{len(coins)} coins fetched from CoinGecko")
    return coins


# =========================
# COINBASE — GET CANDLES
# =========================
def get_candles(ticker, interval):
    granularity_map = {
        "1h": "ONE_HOUR",
        "4h": "FOUR_HOUR"
    }
    granularity = granularity_map.get(interval)
    if not granularity:
        return None, None

    product_id = f"{ticker}-USDT"

    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": granularity, "limit": 150},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 50:
            return None, None

        candles = list(reversed(candles))[:-1]
        closes  = [float(c["close"]) for c in candles]
        volumes = [float(c["volume"]) for c in candles]
        return closes, volumes

    except Exception as e:
        log.error(f"Coinbase error {product_id}: {e}")
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
def volume_above_ma(volumes, candle_index=-1, period=VOLUME_MA_PERIOD):
    abs_index = len(volumes) + candle_index
    if abs_index < period:
        return False
    ma = sum(volumes[abs_index - period : abs_index]) / period
    return volumes[abs_index] > ma


# =========================
# FIND EMA CROSS
# =========================
def find_cross(closes, lookback=CROSS_LOOKBACK):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    for i in range(1, lookback + 1):
        curr_idx = -i
        prev_idx = -(i + 1)
        prev_fast = ema_fast[prev_idx]
        prev_slow = ema_slow[prev_idx]
        curr_fast = ema_fast[curr_idx]
        curr_slow = ema_slow[curr_idx]

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return "BULLISH", i
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return "BEARISH", i

    return None, None


# =========================
# SIGNAL LOGIC
# =========================
def check_signal(closes, volumes):
    direction, candles_ago = find_cross(closes)

    if direction is None:
        return None, None

    if candles_ago == 1:
        if volume_above_ma(volumes, candle_index=-1):
            return direction, 1
        else:
            return None, None
    else:
        cross_vol_was_low = not volume_above_ma(volumes, candle_index=-candles_ago)
        current_vol_high  = volume_above_ma(volumes, candle_index=-1)
        if cross_vol_was_low and current_vol_high:
            return direction, candles_ago

    return None, None


# =========================
# FORMAT MARKET CAP
# =========================
def fmt_mcap(mcap):
    if mcap >= 1_000_000_000:
        return f"${mcap/1_000_000_000:.1f}B"
    return f"${mcap/1_000_000:.0f}M"


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(coins, interval):
    bullish = []
    bearish = []

    for ticker, info in coins.items():
        closes, volumes = get_candles(ticker, interval)
        if closes is None:
            continue

        direction, candles_ago = check_signal(closes, volumes)
        if direction is None:
            continue

        signal_type = "fresh" if candles_ago == 1 else f"{candles_ago} candles ago"
        log.info(f"{ticker} [{interval}] {direction} ({signal_type})")

        entry = {
            "ticker":      ticker,
            "candles_ago": signal_type,
            "mcap":        fmt_mcap(info["market_cap"]),
            "change_24h":  info["price_change_24h"],
            "price":       info["current_price"],
            "tv_link":     f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USDT"
        }

        if direction == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

        time.sleep(0.1)

    return bullish, bearish


# =========================
# FORMAT COIN LINE
# =========================
def fmt_coin(e):
    change = e["change_24h"]
    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
    return (
        f"<b>{e['ticker']}</b> — {e['mcap']} | 24h: {change_str} | cross: {e['candles_ago']}\n"
        f"<a href='{e['tv_link']}'>📈 TradingView</a>"
    )


# =========================
# BUILD MESSAGE
# =========================
def build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str):
    has_signals = any([bullish_1h, bearish_1h, bullish_4h, bearish_4h])

    if not has_signals:
        return (
            f"🔍 <b>EMA 12/21 Scan</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"No crosses found on 1H or 4H\n\n"
            f"🕐 {now_str}"
        )

    lines = ["📊 <b>EMA 12/21 — Cross Alert</b>", "━━━━━━━━━━━━━━━━"]

    if bullish_1h or bearish_1h:
        lines.append("\n⏱ <b>1H Timeframe</b>")
        if bullish_1h:
            lines.append("📈 <b>Bullish</b>")
            for e in bullish_1h:
                lines.append(fmt_coin(e))
        if bearish_1h:
            lines.append("📉 <b>Bearish</b>")
            for e in bearish_1h:
                lines.append(fmt_coin(e))

    if bullish_4h or bearish_4h:
        lines.append("\n⏱ <b>4H Timeframe</b>")
        if bullish_4h:
            lines.append("📈 <b>Bullish</b>")
            for e in bullish_4h:
                lines.append(fmt_coin(e))
        if bearish_4h:
            lines.append("📉 <b>Bearish</b>")
            for e in bearish_4h:
                lines.append(fmt_coin(e))

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# MAIN SCAN
# =========================
def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")
    coins = get_coins()
    bullish_1h, bearish_1h = scan_timeframe(coins, "1h")
    bullish_4h, bearish_4h = scan_timeframe(coins, "4h")
    msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
    send_alert(msg)
    log.info("Scan complete.")


# =========================
# HOURLY TIMER — runs at :05
# =========================
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=0, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


# =========================
# START
# =========================
if __name__ == "__main__":
    log.info("Intraday EMA Scanner started.")
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nScanning 1H + 4H every hour at :00.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()