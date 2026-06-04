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
        return None

    product_id = f"{ticker}-USDT"

    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": granularity, "limit": 120},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 60:
            return None

        candles = list(reversed(candles))[:-1]

        return [
            {
                "open":  float(c["open"]),
                "high":  float(c["high"]),
                "low":   float(c["low"]),
                "close": float(c["close"]),
            }
            for c in candles
        ]

    except Exception as e:
        log.error(f"Coinbase error {product_id}: {e}")
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
# SIGNAL LOGIC
# Step 1 — 4H candle touches the 50 EMA (wick or body)
# Step 2 — 1H candle closes above (bullish) or below (bearish) the 50 EMA
# =========================
def check_4h_touch(candles_4h, ema_4h):
    c   = candles_4h[-1]
    e   = ema_4h[-1]
    tol = e * 0.003
    return c["low"] <= e + tol and c["high"] >= e - tol


def check_1h_confirmation(candles_1h, ema_1h):
    c = candles_1h[-1]
    e = ema_1h[-1]
    if c["close"] > e:
        return "BULLISH"
    if c["close"] < e:
        return "BEARISH"
    return None


# =========================
# FORMAT MARKET CAP
# =========================
def fmt_mcap(mcap):
    if mcap >= 1_000_000_000:
        return f"${mcap/1_000_000_000:.1f}B"
    return f"${mcap/1_000_000:.0f}M"


# =========================
# SCAN ALL COINS
# =========================
def scan_coins(coins):
    bullish = []
    bearish = []

    for ticker, info in coins.items():
        candles_4h = get_candles(ticker, "4h")
        if candles_4h is None:
            continue

        candles_1h = get_candles(ticker, "1h")
        if candles_1h is None:
            continue

        closes_4h = [c["close"] for c in candles_4h]
        closes_1h = [c["close"] for c in candles_1h]

        ema_4h = calc_ema(closes_4h, EMA_PERIOD)
        ema_1h = calc_ema(closes_1h, EMA_PERIOD)

        if not check_4h_touch(candles_4h, ema_4h):
            continue

        direction = check_1h_confirmation(candles_1h, ema_1h)
        if direction is None:
            continue

        log.info(f"{ticker} EMA50 touch — {direction}")

        entry = {
            "ticker":     ticker,
            "mcap":       fmt_mcap(info["market_cap"]),
            "change_24h": info["price_change_24h"],
            "price":      info["current_price"],
            "tv_link":    f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USDT"
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
        f"<b>{e['ticker']}</b> — {e['mcap']} | 24h: {change_str}\n"
        f"<a href='{e['tv_link']}'>📈 TradingView</a>"
    )


# =========================
# BUILD MESSAGE
# =========================
def build_message(bullish, bearish, now_str):
    if not bullish and not bearish:
        return (
            f"🔍 <b>EMA 50 Scan</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"No 4H touches confirmed on 1H\n\n"
            f"🕐 {now_str}"
        )

    lines = ["🎯 <b>EMA 50 — Touch Alert</b>", "━━━━━━━━━━━━━━━━"]

    if bullish:
        lines.append("\n📈 <b>Bullish</b> — 4H touched + 1H closed above")
        for e in bullish:
            lines.append(fmt_coin(e))

    if bearish:
        lines.append("\n📉 <b>Bearish</b> — 4H touched + 1H closed below")
        for e in bearish:
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
    bullish, bearish = scan_coins(coins)
    msg = build_message(bullish, bearish, now_str)
    send_alert(msg)
    log.info("Scan complete.")


# =========================
# HOURLY TIMER — runs at :10
# =========================
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=15, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


# =========================
# START
# =========================
if __name__ == "__main__":
    log.info("EMA 50 Touch Scanner started.")
    send_alert("✅ <b>EMA 50 Scanner Online</b>\nScanning 4H touch + 1H confirmation every hour at :15.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()