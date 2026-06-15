import os
import time
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from coins import get_coins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA50-PULLBACK] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
EMA_PERIOD       = 50

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


def is_new_signal(memory, key, direction):
    return memory.get(key) != direction


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
            "high_24h":   float(data.get("high_52_week", 0)),
            "low_24h":    float(data.get("low_52_week", 0)),
        }
    except:
        return None


def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def check_4h_touch(candles_4h, ema_4h):
    c   = candles_4h[-1]
    e   = ema_4h[-1]
    tol = e * 0.003
    return c["low"] <= e + tol and c["high"] >= e - tol


def check_4h_close(candles_4h, ema_4h):
    c = candles_4h[-1]
    e = ema_4h[-1]
    if c["close"] > e:
        return "BULLISH"
    if c["close"] < e:
        return "BEARISH"
    return None


def check_1h_confirmation(candles_1h, ema_1h):
    c = candles_1h[-1]
    e = ema_1h[-1]
    if c["close"] > e:
        return "BULLISH"
    if c["close"] < e:
        return "BEARISH"
    return None


def fmt_vol(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    return f"${v/1_000:.1f}K"


def fmt_price(p):
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 1:
        return f"${p:.2f}"
    return f"${p:.6f}"


def scan_coins(coins, memory):
    bullish = []
    bearish = []
    skipped = 0
    new_memory = {}

    for ticker, mcap in coins:
        candles_4h = get_candles(ticker, "4h")
        if candles_4h is None:
            log.warning(f"{ticker} — no 4h data")
            skipped += 1
            continue

        candles_1h = get_candles(ticker, "1h")
        if candles_1h is None:
            log.warning(f"{ticker} — no 1h data")
            skipped += 1
            continue

        closes_4h = [c["close"] for c in candles_4h]
        closes_1h = [c["close"] for c in candles_1h]

        ema_4h = calc_ema(closes_4h, EMA_PERIOD)
        ema_1h = calc_ema(closes_1h, EMA_PERIOD)

        # 1) 4H must touch the EMA 50 zone
        if not check_4h_touch(candles_4h, ema_4h):
            continue

        # 2) 4H must CLOSE in a direction relative to EMA 50
        dir_4h = check_4h_close(candles_4h, ema_4h)
        if dir_4h is None:
            continue

        # 3) 1H must confirm the SAME direction
        dir_1h = check_1h_confirmation(candles_1h, ema_1h)
        if dir_1h is None:
            continue

        # 4) both timeframes must agree
        if dir_4h != dir_1h:
            log.info(f"{ticker} EMA50 — 4H/1H mismatch ({dir_4h}/{dir_1h}), skipping")
            continue

        direction = dir_4h
        key = f"{ticker}_ema50_pullback"

        if not is_new_signal(memory, key, direction):
            log.info(f"{ticker} EMA50 {direction} — already fired, skipping")
            new_memory[key] = direction
            continue

        ticker_data = get_ticker(ticker)
        ema_dist     = abs(closes_1h[-1] - ema_1h[-1]) / ema_1h[-1] * 100
        ema_dist_4h  = abs(closes_4h[-1] - ema_4h[-1]) / ema_4h[-1] * 100

        log.info(f"{ticker} EMA50 touch + 4H close + 1H confirm — {direction} — NEW signal")

        entry = {
            "ticker":      ticker,
            "mcap":        mcap,
            "direction":   direction,
            "ema_dist":    ema_dist,
            "ema_dist_4h": ema_dist_4h,
            "price":      ticker_data["price"]      if ticker_data else 0,
            "change_24h": ticker_data["change_24h"] if ticker_data else 0,
            "volume_24h": ticker_data["volume_24h"] if ticker_data else 0,
            "high_24h":   ticker_data["high_24h"]   if ticker_data else 0,
            "low_24h":    ticker_data["low_24h"]    if ticker_data else 0,
            "tv_link":    f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD"
        }

        new_memory[key] = direction

        if direction == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

        time.sleep(0.1)

    log.info(f"{skipped} coins skipped — no data from Coinbase")
    return bullish, bearish, new_memory


def fmt_coin(e):
    change = e["change_24h"]
    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
    close_dir = "above ✅" if e["direction"] == "BULLISH" else "below ✅"
    return (
        f"<b>{e['ticker']}</b> — MCap: {e['mcap']}\n"
        f"💰 {fmt_price(e['price'])} | 24h: {change_str}\n"
        f"🕯 4H: touched EMA50 ✅ | closed {close_dir} ({e['ema_dist_4h']:.1f}%)\n"
        f"📊 Vol: {fmt_vol(e['volume_24h'])} | 1H EMA dist: {e['ema_dist']:.1f}%\n"
        f"📉 Range: {fmt_price(e['low_24h'])} — {fmt_price(e['high_24h'])}\n"
        f"<a href='{e['tv_link']}'>📈 TradingView</a>"
    )


def build_message(bullish, bearish, now_str):
    if not bullish and not bearish:
        return (
            f"🟣 <b>EMA50 PULLBACK Scan</b>\n"
            f"▰▰▰▰▰▰▰▰▰▰▰▰\n"
            f"No 4H touch + close + 1H confirm setups\n\n"
            f"🕐 {now_str}"
        )

    lines = ["🟣 <b>EMA50 PULLBACK — Touch + Close + 1H Confirm</b>", "▰▰▰▰▰▰▰▰▰▰▰▰"]

    if bullish:
        lines.append("\n🟢 <b>Bullish Pullback</b> — 4H touched + closed above, 1H confirms")
        for e in bullish:
            lines.append(fmt_coin(e))

    if bearish:
        lines.append("\n🔴 <b>Bearish Pullback</b> — 4H touched + closed below, 1H confirms")
        for e in bearish:
            lines.append(fmt_coin(e))

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")
    coins = get_coins()
    memory = load_memory()
    bullish, bearish, new_memory = scan_coins(coins, memory)
    memory.update(new_memory)
    save_memory(memory)
    msg = build_message(bullish, bearish, now_str)
    send_alert(msg)
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
    log.info("EMA50 PULLBACK Scanner started.")
    send_alert("🟣 <b>EMA50 PULLBACK Scanner Online</b>\nScanning 4H touch + 4H close + 1H confirmation every hour at :15.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()