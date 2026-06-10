import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from coins import get_coins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAILY-EMA] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
CROSS_LOOKBACK   = 3


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


def get_daily_candles(ticker, limit=60):
    """Fetch daily candles from Coinbase."""
    product_id = f"{ticker}-USD"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": "ONE_DAY", "limit": limit},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 25:
            return None
        candles = list(reversed(candles))[:-1]
        return [float(c["close"]) for c in candles]
    except:
        return None


def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def check_cross(closes):
    ema12 = calc_ema(closes, 12)
    ema21 = calc_ema(closes, 21)
    for i in range(1, CROSS_LOOKBACK + 1):
        curr_idx = -i
        prev_idx = -(i + 1)
        prev12, prev21 = ema12[prev_idx], ema21[prev_idx]
        curr12, curr21 = ema12[curr_idx], ema21[curr_idx]
        if prev12 <= prev21 and curr12 > curr21:
            return "BULLISH", i
        if prev12 >= prev21 and curr12 < curr21:
            return "BEARISH", i
    return None, None


def fmt_price(p):
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:.2f}"
    return f"${p:.6f}"


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Daily scan running... {now_str}")

    coins = get_coins()
    bullish = []
    bearish = []
    skipped = 0

    for ticker, mcap in coins:
        closes = get_daily_candles(ticker)
        if closes is None or len(closes) < 22:
            skipped += 1
            time.sleep(0.1)
            continue

        direction, candles_ago = check_cross(closes)

        if direction == "BULLISH":
            bullish.append((ticker, mcap, closes[-1], candles_ago))
            log.info(f"{ticker} DAILY BULLISH cross ({candles_ago}d ago)")
        elif direction == "BEARISH":
            bearish.append((ticker, mcap, closes[-1], candles_ago))
            log.info(f"{ticker} DAILY BEARISH cross ({candles_ago}d ago)")

        time.sleep(0.1)

    log.info(f"{skipped} coins skipped — no data")

    if not bullish and not bearish:
        log.info("No daily crosses found.")
        return

    lines = [
        "📅 <b>DAILY EMA 12/21 — Cross Alert</b>",
        "━━━━━━━━━━━━━━━━",
        f"🕐 {now_str}"
    ]

    if bullish:
        lines.append("\n📈 <b>Bullish Crosses</b>")
        for ticker, mcap, price, days_ago in bullish:
            days_str = "today" if days_ago == 1 else f"{days_ago}d ago"
            lines.append(
                f"<b>{ticker}</b> — MCap: {mcap}\n"
                f"💰 {fmt_price(price)} | Cross: {days_str}\n"
                f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD'>📈 TradingView</a>"
            )

    if bearish:
        lines.append("\n📉 <b>Bearish Crosses</b>")
        for ticker, mcap, price, days_ago in bearish:
            days_str = "today" if days_ago == 1 else f"{days_ago}d ago"
            lines.append(
                f"<b>{ticker}</b> — MCap: {mcap}\n"
                f"💰 {fmt_price(price)} | Cross: {days_str}\n"
                f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD'>📈 TradingView</a>"
            )

    send_alert("\n".join(lines))
    log.info("Daily scan complete.")


def wait_until_daily_close():
    """Wait until 00:05 UTC (5 min after daily candle close)."""
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(days=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/3600:.1f}h")
    time.sleep(sleep_secs)


if __name__ == "__main__":
    log.info("Daily EMA 12/21 Cross Scanner started.")
    send_alert("✅ <b>Daily EMA Scanner Online</b>\nScanning daily candles every day at 00:05 UTC.")
    while True:
        wait_until_daily_close()
        run_scan()