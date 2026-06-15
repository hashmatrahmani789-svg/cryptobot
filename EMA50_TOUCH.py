import os
import time
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from coins import get_coins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA50] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
EMA_PERIOD       = 50
ZONE_TOLERANCE   = 0.003  # 0.3% zone around EMA50 = "inside"

SIGNAL_MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_memory_ema50.json")


def load_memory():
    if os.path.exists(SIGNAL_MEMORY_FILE):
        try:
            with open(SIGNAL_MEMORY_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_memory(memory):
    try:
        with open(SIGNAL_MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        log.error(f"Memory save error: {e}")


def is_new_signal(memory, key, value):
    return memory.get(key) != value


def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


def get_candles(ticker, interval):
    granularity_map = {"1h": "ONE_HOUR", "4h": "FOUR_HOUR"}
    granularity = granularity_map.get(interval)
    product_id = f"{ticker}-USD"
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
    except:
        return None


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


def fmt_vol(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    return f"${v/1_000:.1f}K"


def fmt_price(p):
    if not p or p == 0:
        return "N/A"
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"


def fmt_entry(e):
    change_str = f"{e['change_24h']:+.2f}%"
    return (
        f"\n<b>{e['ticker']}</b> — {e['mcap']}\n"
        f"💰 {fmt_price(e['price'])}  ({change_str})\n"
        f"📦 Vol: {fmt_vol(e['volume_24h'])}\n"
        f"📊 EMA50: {fmt_price(e['ema'])}  Close: {fmt_price(e['close'])}\n"
        f"<a href='{e['tv_link']}'>📈 Chart</a>"
    )


def build_entry(ticker, mcap, td, ema, close):
    return {
        "ticker": ticker, "mcap": mcap,
        "price": td["price"] if td else 0,
        "change_24h": td["change_24h"] if td else 0,
        "volume_24h": td["volume_24h"] if td else 0,
        "ema": ema, "close": close,
        "tv_link": f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD"
    }


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")

    coins = get_coins()
    if not coins:
        log.error("No coins fetched — aborting.")
        return

    memory = load_memory()

    # Signal 1: 1H EMA50 close
    h1_above = []
    h1_below = []
    # Signal 2: 4H EMA50 close
    close_above  = []
    close_below  = []
    close_inside = []

    skipped = 0

    for ticker, mcap in coins:
        # ── Signal 2: 4H EMA50 CLOSE ─────────────────────
        candles_4h = get_candles(ticker, "4h")
        if candles_4h:
            closes_4h = [c["close"] for c in candles_4h]
            ema_4h    = calc_ema(closes_4h, EMA_PERIOD)
            e4        = ema_4h[-1]
            c4close   = candles_4h[-1]["close"]
            tol       = e4 * ZONE_TOLERANCE

            if c4close > e4 + tol:
                close_val = "ABOVE"
            elif c4close < e4 - tol:
                close_val = "BELOW"
            else:
                close_val = "INSIDE"

            close_key = f"{ticker}_4h_close"
            if is_new_signal(memory, close_key, close_val):
                td = get_ticker(ticker)
                entry = build_entry(ticker, mcap, td, e4, c4close)
                memory[close_key] = close_val
                if close_val == "ABOVE":
                    close_above.append(entry)
                    log.info(f"{ticker} 4H closed ABOVE EMA50 — NEW")
                elif close_val == "BELOW":
                    close_below.append(entry)
                    log.info(f"{ticker} 4H closed BELOW EMA50 — NEW")
                else:
                    close_inside.append(entry)
                    log.info(f"{ticker} 4H closed INSIDE EMA50 — NEW")
                time.sleep(0.1)
        else:
            skipped += 1

        # ── Signal 1: 1H EMA50 CLOSE ─────────────────────
        candles_1h = get_candles(ticker, "1h")
        if candles_1h:
            closes_1h = [c["close"] for c in candles_1h]
            ema_1h    = calc_ema(closes_1h, EMA_PERIOD)
            e1        = ema_1h[-1]
            c1close   = candles_1h[-1]["close"]

            h1_dir = "ABOVE" if c1close > e1 else "BELOW"
            h1_key = f"{ticker}_1h_close"

            if is_new_signal(memory, h1_key, h1_dir):
                td = get_ticker(ticker)
                entry = build_entry(ticker, mcap, td, e1, c1close)
                memory[h1_key] = h1_dir
                if h1_dir == "ABOVE":
                    h1_above.append(entry)
                    log.info(f"{ticker} 1H closed ABOVE EMA50 — NEW")
                else:
                    h1_below.append(entry)
                    log.info(f"{ticker} 1H closed BELOW EMA50 — NEW")
                time.sleep(0.1)
        else:
            skipped += 1

        time.sleep(0.2)

    save_memory(memory)
    log.info(f"{skipped} coins skipped — no Coinbase data")

    # ── Send Signal 1: 1H EMA50 CLOSE ───────────────────
    if h1_above or h1_below:
        lines = [
            "⚡ <b>1H EMA50 CLOSE SIGNAL</b>",
            "╔════════════════════╗",
            f"🕐 {now_str}",
            "╚════════════════════╝",
        ]
        if h1_above:
            lines.append(f"\n🟢 <b>CLOSED ABOVE EMA50</b> — {len(h1_above)} coins")
            for e in h1_above:
                lines.append(fmt_entry(e))
        if h1_below:
            lines.append(f"\n🔴 <b>CLOSED BELOW EMA50</b> — {len(h1_below)} coins")
            for e in h1_below:
                lines.append(fmt_entry(e))
        send_alert("\n".join(lines))

    # ── Send Signal 2: 4H EMA50 CLOSE ───────────────────
    if close_above or close_below or close_inside:
        lines = [
            "🕯 <b>4H EMA50 CLOSE SIGNAL</b>",
            "══════════════════════",
            f"🕐 {now_str}",
            "══════════════════════",
        ]
        if close_above:
            lines.append(f"\n💚 <b>CLOSED ABOVE EMA50</b> — {len(close_above)} coins")
            for e in close_above:
                lines.append(fmt_entry(e))
        if close_below:
            lines.append(f"\n❤️ <b>CLOSED BELOW EMA50</b> — {len(close_below)} coins")
            for e in close_below:
                lines.append(fmt_entry(e))
        if close_inside:
            lines.append(f"\n🔵 <b>CLOSED INSIDE EMA50 ZONE</b> — {len(close_inside)} coins")
            for e in close_inside:
                lines.append(fmt_entry(e))
        send_alert("\n".join(lines))

    total = len(h1_above) + len(h1_below) + len(close_above) + len(close_below) + len(close_inside)
    if total == 0:
        log.info("No new EMA50 signals found.")
    log.info("Scan complete.")


def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=15, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


if __name__ == "__main__":
    log.info("EMA50 Scanner started.")
    send_alert(
        "🟣 <b>EMA50 Scanner Online</b>\n"
        "2 independent signals every hour at :15\n\n"
        "⚡ 1H EMA50 Close (above / below)\n"
        "🕯 4H EMA50 Close (above / below / inside)"
    )
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()