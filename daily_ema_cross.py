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


def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
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


def send_long_alert(lines):
    """Split into multiple messages if over Telegram 4096 char limit."""
    message = "\n".join(lines)
    if len(message) <= 4096:
        send_alert(message)
        return
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > 4096:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    for i, chunk in enumerate(chunks):
        send_alert(chunk)
        if i < len(chunks) - 1:
            time.sleep(1)


def get_daily_candles(ticker, limit=60):
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
            return None, None
        candles = list(reversed(candles))[:-1]
        closes  = [float(c["close"])  for c in candles]
        volumes = [float(c["volume"]) for c in candles]
        return closes, volumes
    except:
        return None, None


def get_ticker(ticker):
    product_id = f"{ticker}-USD"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}",
            timeout=10
        )
        data = r.json()
        return {
            "price":      float(data.get("price", 0)),
            "change_24h": float(data.get("price_percentage_change_24h", 0)),
            "volume_24h": float(data.get("volume_24h", 0)),
        }
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
    prev12, prev21 = ema12[-2], ema21[-2]
    curr12, curr21 = ema12[-1], ema21[-1]
    if prev12 <= prev21 and curr12 > curr21:
        return "BULLISH", ema12[-1], ema21[-1]
    if prev12 >= prev21 and curr12 < curr21:
        return "BEARISH", ema12[-1], ema21[-1]
    return None, None, None


def fmt_price(p):
    if p is None or p == 0:
        return "N/A"
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"


def fmt_vol(v):
    if not v:
        return "N/A"
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    return f"${v/1_000:.1f}K"


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Daily scan running... {now_str}")

    coins = get_coins()
    if not coins:
        log.error("No coins fetched — aborting scan.")
        return

    bullish = []
    bearish = []
    skipped = 0

    for ticker, mcap in coins:
        closes, volumes = get_daily_candles(ticker)
        if closes is None or len(closes) < 22:
            skipped += 1
            time.sleep(0.2)
            continue

        direction, ema12_val, ema21_val = check_cross(closes)
        if direction is None:
            time.sleep(0.2)
            continue

        ticker_data = get_ticker(ticker)
        time.sleep(0.3)

        entry = {
            "ticker":     ticker,
            "mcap":       mcap,
            "price":      ticker_data["price"]      if ticker_data else 0,
            "change_24h": ticker_data["change_24h"] if ticker_data else None,
            "vol_24h":    ticker_data["volume_24h"] if ticker_data else None,
            "ema12":      ema12_val,
            "ema21":      ema21_val,
        }

        if direction == "BULLISH":
            bullish.append(entry)
            log.info(f"{ticker} DAILY BULLISH cross")
        else:
            bearish.append(entry)
            log.info(f"{ticker} DAILY BEARISH cross")

    log.info(f"{skipped} coins skipped — no Coinbase data")

    if not bullish and not bearish:
        log.info("No daily crosses found.")
        return

    lines = [
        "📅 <b>DAILY EMA 12/21 CROSS</b>",
        f"🕐 {now_str}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if bullish:
        lines.append(f"\n📈 <b>BULLISH</b> — {len(bullish)} coins")
        lines.append("─────────────────────")
        for e in bullish:
            change_str = f"{e['change_24h']:+.2f}%" if e["change_24h"] is not None else "N/A"
            lines.append(
                f"\n🟢 <b>{e['ticker']}</b> — {e['mcap']}\n"
                f"💰 {fmt_price(e['price'])}  ({change_str})\n"
                f"📦 Vol: {fmt_vol(e['vol_24h'])}\n"
                f"📊 EMA12: {fmt_price(e['ema12'])}  EMA21: {fmt_price(e['ema21'])}\n"
                f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>View Chart</a>"
            )

    if bearish:
        lines.append(f"\n📉 <b>BEARISH</b> — {len(bearish)} coins")
        lines.append("─────────────────────")
        for e in bearish:
            change_str = f"{e['change_24h']:+.2f}%" if e["change_24h"] is not None else "N/A"
            lines.append(
                f"\n🔴 <b>{e['ticker']}</b> — {e['mcap']}\n"
                f"💰 {fmt_price(e['price'])}  ({change_str})\n"
                f"📦 Vol: {fmt_vol(e['vol_24h'])}\n"
                f"📊 EMA12: {fmt_price(e['ema12'])}  EMA21: {fmt_price(e['ema21'])}\n"
                f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>View Chart</a>"
            )

    send_long_alert(lines)
    log.info("Daily scan complete.")


def wait_until_daily_close():
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(days=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/3600:.1f}h")
    time.sleep(sleep_secs)


if __name__ == "__main__":
    log.info("Daily EMA 12/21 Cross Scanner started.")
    send_alert("✅ <b>Daily EMA Scanner Online</b>\nScanning all coins $500M+ market cap every day at 00:05 UTC.")
    while True:
        wait_until_daily_close()
        run_scan()