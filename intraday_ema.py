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

TELEGRAM_TOKEN   = os.environ.get("8730830984:AAGMpHQqsco1ZCfiADjgRN18zSrwjMpfAS4", "")
TELEGRAM_CHAT_ID = os.environ.get("8118939134", "")
MIN_MARKET_CAP   = 200_000_000
EMA_FAST         = 12
EMA_SLOW         = 21
VOLUME_MA_PERIOD = 20
CROSS_LOOKBACK   = 6  # how many candles back to look for a delayed cross


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
        # exclude the live/current candle (last item)
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
# checks if volume at a specific candle index is above the 20-candle MA
# index -1 = last closed candle, -2 = one before, etc.
# =========================
def volume_above_ma(volumes, candle_index=-1, period=VOLUME_MA_PERIOD):
    # we need enough candles before the target candle to compute MA
    # candle_index is negative (e.g. -1 = last, -6 = 6 from end)
    abs_index = len(volumes) + candle_index  # convert to positive
    if abs_index < period:
        return False
    # MA = average of the 'period' candles BEFORE the target candle
    ma = sum(volumes[abs_index - period : abs_index]) / period
    return volumes[abs_index] > ma


# =========================
# FIND EMA CROSS IN LAST N CANDLES
# returns: (direction, candles_ago)
#   direction = "BULLISH" or "BEARISH"
#   candles_ago = 1 means last closed candle (fresh cross)
#                 2-6 means cross happened that many candles back
# returns (None, None) if no cross found
# =========================
def find_cross(closes, lookback=CROSS_LOOKBACK):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    # check from most recent candle backwards
    # index -1 = last closed candle = 1 candle ago
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
# Signal 1: cross on last candle + volume above MA at that candle
# Signal 2: cross happened 2-6 candles ago (low vol then) + current candle vol now above MA
# =========================
def check_signal(closes, volumes):
    direction, candles_ago = find_cross(closes)

    if direction is None:
        return None, None  # no cross found at all

    if candles_ago == 1:
        # === SIGNAL 1: fresh cross ===
        # volume must be above MA on the cross candle (last closed candle)
        if volume_above_ma(volumes, candle_index=-1):
            return direction, 1
        else:
            return None, None  # cross happened but vol too low — wait for Signal 2

    else:
        # === SIGNAL 2: delayed confirmation ===
        # cross happened 2-6 candles ago
        # volume at cross candle was LOW (below MA)
        cross_vol_was_low = not volume_above_ma(volumes, candle_index=-candles_ago)
        # current candle volume is NOW above MA
        current_vol_high = volume_above_ma(volumes, candle_index=-1)

        if cross_vol_was_low and current_vol_high:
            return direction, candles_ago

    return None, None


# =========================
# SCAN ONE TIMEFRAME
# returns bullish and bearish lists
# =========================
def scan_timeframe(coins, interval):
    bullish = []
    bearish = []

    for coin in coins:
        ticker = coin.get("symbol", "").upper()
        symbol = ticker + "USDT"

        closes, volumes = get_candles(symbol, interval)

        # fallback to BTC pair
        if closes is None:
            symbol = ticker + "BTC"
            closes, volumes = get_candles(symbol, interval)

        if closes is None:
            continue

        direction, candles_ago = check_signal(closes, volumes)

        if direction is None:
            continue

        signal_type = "S1" if candles_ago == 1 else f"S2({candles_ago})"
        log.info(f"{symbol} [{interval}] {direction} {signal_type}")

        if direction == "BULLISH":
            bullish.append(ticker)
        else:
            bearish.append(ticker)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# BUILD ONE BEAUTIFUL MESSAGE PER SCAN
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

    lines = [
        f"📊 <b>EMA 12/21 — Cross Alert</b>",
        f"━━━━━━━━━━━━━━━━",
    ]

    # 1H section
    if bullish_1h or bearish_1h:
        lines.append(f"\n⏱ <b>1H Timeframe</b>")
        if bullish_1h:
            coins_str = "  •  ".join(bullish_1h)
            lines.append(f"📈 <b>Bullish</b>\n{coins_str}")
        if bearish_1h:
            coins_str = "  •  ".join(bearish_1h)
            lines.append(f"📉 <b>Bearish</b>\n{coins_str}")

    # 4H section
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
# MAIN SCAN — ONE MESSAGE TOTAL
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
# HOURLY TIMER — runs at :05 every hour
# =========================
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=5, second=0, microsecond=0)
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
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nScanning 1H + 4H every hour.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()