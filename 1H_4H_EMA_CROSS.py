import os
import time
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from coins import get_coins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [1H-4H-CROSS] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
EMA_FAST         = 12
EMA_SLOW         = 21
VOLUME_MA_PERIOD = 20
CROSS_LOOKBACK   = 12

SIGNAL_MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_memory_1h4h.json")


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
    """Returns True if this is a new signal (not already fired)."""
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
            params={"granularity": granularity, "limit": 150},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 50:
            return None, None, None, None
        candles = list(reversed(candles))[:-1]
        closes  = [float(c["close"])  for c in candles]
        volumes = [float(c["volume"]) for c in candles]
        highs   = [float(c["high"])   for c in candles]
        lows    = [float(c["low"])    for c in candles]
        return closes, volumes, highs, lows
    except:
        return None, None, None, None


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


def volume_above_ma(volumes, candle_index=-1, period=VOLUME_MA_PERIOD):
    abs_index = len(volumes) + candle_index
    if abs_index < period:
        return False
    ma = sum(volumes[abs_index - period: abs_index]) / period
    return volumes[abs_index] > ma


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


def check_signal_1h(closes, volumes):
    direction, candles_ago = find_cross(closes)
    if direction is None:
        return None, None, None
    ema_slow = calc_ema(closes, EMA_SLOW)
    ema_dist = abs(closes[-1] - ema_slow[-1]) / ema_slow[-1] * 100
    if candles_ago == 1:
        if volume_above_ma(volumes, candle_index=-1):
            return direction, 1, ema_dist
        else:
            return None, None, None
    else:
        cross_vol_was_low = not volume_above_ma(volumes, candle_index=-candles_ago)
        current_vol_high  = volume_above_ma(volumes, candle_index=-1)
        if cross_vol_was_low and current_vol_high:
            return direction, candles_ago, ema_dist
    return None, None, None


def check_signal_4h(closes):
    direction, candles_ago = find_cross(closes)
    if direction is None:
        return None, None, None
    ema_slow = calc_ema(closes, EMA_SLOW)
    ema_dist = abs(closes[-1] - ema_slow[-1]) / ema_slow[-1] * 100
    return direction, candles_ago, ema_dist


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


def scan_timeframe(interval, coins, memory):
    bullish = []
    bearish = []
    skipped = 0
    new_memory = {}

    for ticker, mcap in coins:
        closes, volumes, highs, lows = get_candles(ticker, interval)
        if closes is None:
            log.warning(f"{ticker} [{interval}] — no data")
            skipped += 1
            continue

        if interval == "1h":
            direction, candles_ago, ema_dist = check_signal_1h(closes, volumes)
        else:
            direction, candles_ago, ema_dist = check_signal_4h(closes)

        if direction is None:
            continue

        key = f"{ticker}_{interval}"

        # Only fire if this is a new signal
        if not is_new_signal(memory, key, direction):
            log.info(f"{ticker} [{interval}] {direction} — already fired, skipping")
            new_memory[key] = direction
            continue

        ticker_data = get_ticker(ticker)
        signal_label = "S1" if candles_ago == 1 else f"S2({candles_ago})"
        log.info(f"{ticker} [{interval}] {direction} {signal_label} — NEW signal")

        cross_idx  = -candles_ago
        cross_high = highs[cross_idx] if highs else 0
        cross_low  = lows[cross_idx]  if lows  else 0

        entry = {
            "ticker":     ticker,
            "mcap":       mcap,
            "signal":     signal_label,
            "ema_dist":   ema_dist,
            "price":      ticker_data["price"]      if ticker_data else 0,
            "change_24h": ticker_data["change_24h"] if ticker_data else 0,
            "volume_24h": ticker_data["volume_24h"] if ticker_data else 0,
            "cross_high": cross_high,
            "cross_low":  cross_low,
            "tv_link":    f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD"
        }

        new_memory[key] = direction

        if direction == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

        time.sleep(0.1)

    log.info(f"[{interval}] {skipped} coins skipped — no data from Coinbase")
    return bullish, bearish, new_memory


def fmt_coin(e):
    change = e["change_24h"]
    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
    return (
        f"<b>{e['ticker']}</b> [{e['signal']}] — MCap: {e['mcap']}\n"
        f"💰 {fmt_price(e['price'])} | 24h: {change_str}\n"
        f"📊 Vol: {fmt_vol(e['volume_24h'])} | EMA dist: {e['ema_dist']:.1f}%\n"
        f"📉 Cross candle: {fmt_price(e['cross_low'])} — {fmt_price(e['cross_high'])}\n"
        f"<a href='{e['tv_link']}'>📈 TradingView</a>"
    )


def build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str):
    has_signals = any([bullish_1h, bearish_1h, bullish_4h, bearish_4h])

    if not has_signals:
        return (
            f"🔍 <b>EMA 12/21 Scan</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"No new crosses found on 1H or 4H\n\n"
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


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")
    coins = get_coins()
    memory = load_memory()

    bullish_1h, bearish_1h, new_mem_1h = scan_timeframe("1h", coins, memory)
    bullish_4h, bearish_4h, new_mem_4h = scan_timeframe("4h", coins, memory)

    # Merge and save updated memory
    memory.update(new_mem_1h)
    memory.update(new_mem_4h)
    save_memory(memory)

    msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
    send_alert(msg)
    log.info("Scan complete.")


def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=0, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


if __name__ == "__main__":
    log.info("Intraday EMA Scanner started.")
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nScanning 1H + 4H every hour at :00.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()