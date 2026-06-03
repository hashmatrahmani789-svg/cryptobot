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

# =========================
# CONFIG
# =========================
TELEGRAM_TOKEN   = "8730830984:AAGMpHQqsco1ZCfiADjgRN18zSrwjMpfAS4"
TELEGRAM_CHAT_ID = "8118939134"
MIN_VOLUME_24H   = 10_000_000
EMA_FAST         = 12
EMA_SLOW         = 21
VOLUME_MA_PERIOD = 20
CROSS_LOOKBACK   = 6

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
# GET ACTIVE BINANCE PAIRS
# =========================
def get_active_pairs():
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            timeout=30
        )
        data = r.json()
        if not isinstance(data, list):
            log.error(f"Binance ticker failed: {data}")
            return []
        pairs = []
        for coin in data:
            symbol = coin.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            try:
                volume = float(coin.get("quoteVolume", 0))
            except:
                continue
            if volume >= MIN_VOLUME_24H:
                pairs.append(symbol)
        log.info(f"{len(pairs)} active pairs with >$10M volume")
        return pairs
    except Exception as e:
        log.error(f"Failed loading Binance pairs: {e}")
        return []

# =========================
# GET CANDLES
# =========================
def get_candles(symbol, interval, limit=100):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 30:
            return None, None
        closes  = [float(x[4]) for x in data[:-1]]
        volumes = [float(x[5]) for x in data[:-1]]
        return closes, volumes
    except:
        return None, None

# =========================
# EMA
# =========================
def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

# =========================
# VOLUME FILTER
# =========================
def volume_above_ma(volumes, period=VOLUME_MA_PERIOD):
    if len(volumes) < period + 1:
        return False
    vol_ma = sum(volumes[-period-1:-1]) / period
    return volumes[-1] > vol_ma

# =========================
# EMA CROSS CHECK
# =========================
def check_cross(closes, lookback=CROSS_LOOKBACK):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)
    for i in range(-lookback, 0):
        prev_fast, prev_slow = ema_fast[i-1], ema_slow[i-1]
        curr_fast, curr_slow = ema_fast[i], ema_slow[i]
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return "BULLISH"
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return "BEARISH"
    return None

# =========================
# SCAN TIMEFRAME
# =========================
def scan_timeframe(symbols, interval, label):
    bullish = []
    bearish = []
    for symbol in symbols:
        closes, volumes = get_candles(symbol, interval)
        if closes is None:
            continue
        cross = check_cross(closes)
        if not cross:
            continue
        if not volume_above_ma(volumes):
            continue
        log.info(f"{symbol} {cross} — volume confirmed")
        if cross == "BULLISH":
            bullish.append(symbol)
        else:
            bearish.append(symbol)
        time.sleep(0.05)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not bullish and not bearish:
        log.info(f"[{label}] No signals found.")
        send_alert(f"🔍 EMA scan [{label}] complete — no crosses found\n🕐 {now}")
        return

    msg = [f"📊 <b>EMA 12/21 [{label}]</b>", f"🕐 {now}"]
    if bullish:
        msg.append("\n📈 <b>BULLISH</b>\n" + "\n".join(bullish))
    if bearish:
        msg.append("\n📉 <b>BEARISH</b>\n" + "\n".join(bearish))
    send_alert("\n".join(msg))

# =========================
# MAIN SCAN
# =========================
def run_scan():
    log.info(f"Scanning... {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    symbols = get_active_pairs()
    if not symbols:
        send_alert("⚠️ Failed to load Binance pairs — retrying next hour")
        return
    scan_timeframe(symbols, "1h", "1H")
    scan_timeframe(symbols, "4h", "4H")
    log.info("Scan complete.")

# =========================
# HOURLY TIMER
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
    send_alert("✅ EMA Scanner Online")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()