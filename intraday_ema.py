import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA-SCANNER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

log = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = "8730830984:AAGMpHQqsco1ZCfiADjgRN18zSrwjMpfAS4"
TELEGRAM_CHAT_ID = "8118939134"
MIN_DAILY_VOLUME = 10_000_000  # $10M
CROSS_LOOKBACK = 6
EMA_FAST = 12
EMA_SLOW = 21
VOLUME_MA_PERIOD = 20

# =========================
# TELEGRAM
# =========================

def send_alert(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing")
        return

    try:

        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=15
        )

        if r.status_code == 200:
            log.info("Telegram alert sent")
        else:
            log.error(
                f"Telegram error {r.status_code}: {r.text}"
            )

    except Exception as e:
        log.error(f"Telegram exception: {e}")

# =========================
# BINANCE PAIRS
# =========================
def get_active_pairs():
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            timeout=20
        )

        data = r.json()

        if not isinstance(data, list):
            log.error(f"Binance response: {data}")
            return []

        pairs = []

        for coin in data:

            symbol = coin.get("symbol")

            if not symbol or not symbol.endswith("USDT"):
                continue

            try:
                quote_volume = float(
                    coin.get("quoteVolume", 0)
                )
            except:
                continue

            if quote_volume >= MIN_DAILY_VOLUME:
                pairs.append(symbol)

        log.info(f"{len(pairs)} active pairs found")

        return pairs

    except Exception as e:
        log.error(f"Failed loading Binance pairs: {e}")
        return []
    symbol,
    interval,
    limit=100
):

    try:

        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            },
            timeout=10
        )

        data = r.json()

        if not isinstance(data, list):
            return None, None

        closes = [
            float(x[4])
            for x in data[:-1]
        ]

        volumes = [
            float(x[5])
            for x in data[:-1]
        ]

        return closes, volumes

    except:
        return None, None

# =========================
# EMA
# =========================

def calc_ema(values, period):

    k = 2 / (period + 1)

    ema = [values[0]]

    for value in values[1:]:

        ema.append(
            value * k +
            ema[-1] * (1 - k)
        )

    return ema

# =========================
# VOLUME FILTER
# =========================

def volume_above_ma(
    volumes,
    period=VOLUME_MA_PERIOD
):

    if len(volumes) < period + 1:
        return False

    current_volume = volumes[-1]

    volume_ma = (
        sum(volumes[-period-1:-1])
        / period
    )

    return current_volume > volume_ma

# =========================
# EMA CROSS
# =========================

def check_cross(closes):

    ema_fast = calc_ema(
        closes,
        EMA_FAST
    )

    ema_slow = calc_ema(
        closes,
        EMA_SLOW
    )

    for i in range(
        -CROSS_LOOKBACK,
        0
    ):

        prev_fast = ema_fast[i - 1]
        prev_slow = ema_slow[i - 1]

        curr_fast = ema_fast[i]
        curr_slow = ema_slow[i]

        if (
            prev_fast <= prev_slow
            and
            curr_fast > curr_slow
        ):
            return "BULLISH"

        if (
            prev_fast >= prev_slow
            and
            curr_fast < curr_slow
        ):
            return "BEARISH"

    return None

# =========================
# SCANNER
# =========================

def scan_timeframe(
    symbols,
    interval,
    label
):

    bullish = []
    bearish = []

    for symbol in symbols:

        closes, volumes = get_candles(
            symbol,
            interval
        )

        if closes is None:
            continue

        cross = check_cross(closes)

        if not cross:
            continue

        if not volume_above_ma(volumes):
            continue

        log.info(
            f"{symbol} "
            f"{cross} "
            f"volume confirmed"
        )

        if cross == "BULLISH":
            bullish.append(symbol)

        else:
            bearish.append(symbol)

        time.sleep(0.05)

    if not bullish and not bearish:

        log.info(
            f"No signals found on {label}"
        )

        return

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = [
        f"📊 <b>EMA 12/21 [{label}]</b>",
        f"🕐 {now}"
    ]

    if bullish:

        message.append(
            "\n📈 <b>BULLISH</b>\n" +
            "\n".join(bullish)
        )

    if bearish:

        message.append(
            "\n📉 <b>BEARISH</b>\n" +
            "\n".join(bearish)
        )

    send_alert(
        "\n".join(message)
    )

# =========================
# MAIN SCAN
# =========================

def run_scan():

    log.info(
        f"Scanning "
        f"{datetime.now(timezone.utc)}"
    )

    symbols = get_active_pairs()

    scan_timeframe(
        symbols,
        "1h",
        "1H"
    )

    scan_timeframe(
        symbols,
        "4h",
        "4H"
    )

    log.info(
        "Scan complete"
    )

# =========================
# HOURLY TIMER
# =========================

def wait_until_next_scan():

    now = datetime.now(
        timezone.utc
    )

    next_run = now.replace(
        minute=5,
        second=0,
        microsecond=0
    )

    if now >= next_run:
        next_run += timedelta(
            hours=1
        )

    sleep_seconds = (
        next_run - now
    ).total_seconds()

    log.info(
        f"Next scan at "
        f"{next_run.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    time.sleep(
        sleep_seconds
    )

# =========================
# START
# =========================

if __name__ == "__main__":

    log.info(
        "EMA Scanner Started"
    )

    send_alert(
        "✅ EMA Scanner Online"
    )

    # Run immediately after deploy
    run_scan()

    while True:

        wait_until_next_scan()

        run_scan()