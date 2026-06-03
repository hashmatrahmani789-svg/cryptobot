import os
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

TELEGRAM_TOKEN = os.getenv("8730830984:AAGMpHQqsco1ZCfiADjgRN18zSrwjMpfAS4")
TELEGRAM_CHAT_ID = os.getenv("8118939134")

MIN_MARKET_CAP = 200_000_000
CROSS_LOOKBACK = 6
USE_VOLUME_FILTER = False


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
                "parse_mode": "HTML"
            },
            timeout=15
        )

        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram failed: {r.status_code}")

    except Exception as e:
        log.error(f"Telegram error: {e}")


def get_binance_pairs():
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/exchangeInfo",
            timeout=20
        )

        data = r.json()

        pairs = {
            s["symbol"]
            for s in data["symbols"]
            if s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
        }

        log.info(f"{len(pairs)} Binance pairs loaded")
        return pairs

    except Exception as e:
        log.error(f"Binance pair load error: {e}")
        return set()


def get_coins_above_mcap(valid_pairs):
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

            for coin in data:

                if coin.get("market_cap", 0) < MIN_MARKET_CAP:
                    continue

                symbol = coin["symbol"].upper() + "USDT"

                if symbol in valid_pairs:
                    coins.append(symbol)

            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break

            page += 1
            time.sleep(1)

        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break

    log.info(f"{len(coins)} valid Binance pairs above $200M mcap")

    return list(set(coins))


def get_candles(symbol, interval, limit=100):

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

        closes = [float(x[4]) for x in data[:-1]]
        volumes = [float(x[5]) for x in data[:-1]]

        return closes, volumes

    except:
        return None, None


def calc_ema(values, period):

    k = 2 / (period + 1)

    ema = [values[0]]

    for price in values[1:]:
        ema.append(price * k + ema[-1] * (1 - k))

    return ema


def volume_above_ma(volumes, period=20):

    if len(volumes) < period + 1:
        return False

    avg = sum(volumes[-period-1:-1]) / period

    return volumes[-1] > avg


def check_cross(closes):

    ema12 = calc_ema(closes, 12)
    ema21 = calc_ema(closes, 21)

    for i in range(-CROSS_LOOKBACK, 0):

        prev12 = ema12[i - 1]
        prev21 = ema21[i - 1]

        curr12 = ema12[i]
        curr21 = ema21[i]

        if prev12 <= prev21 and curr12 > curr21:
            return "BULLISH"

        if prev12 >= prev21 and curr12 < curr21:
            return "BEARISH"

    return None


def scan_timeframe(symbols, interval, label):

    bullish = []
    bearish = []

    for symbol in symbols:

        closes, volumes = get_candles(symbol, interval)

        if closes is None or len(closes) < 30:
            continue

        cross = check_cross(closes)

        if not cross:
            continue

        volume_ok = volume_above_ma(volumes)

        log.info(
            f"{symbol} {cross} detected "
            f"(volume_ok={volume_ok})"
        )

        if USE_VOLUME_FILTER and not volume_ok:
            continue

        if cross == "BULLISH":
            bullish.append(symbol.replace("USDT", ""))
        else:
            bearish.append(symbol.replace("USDT", ""))

        time.sleep(0.05)

    if not bullish and not bearish:
        log.info(f"No signals found on {label}")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = [
        f"📊 <b>EMA 12/21 [{label}]</b>",
        f"🕐 {now}"
    ]

    if bullish:
        message.append(
            "\n📈 <b>BULLISH</b>\n" +
            ", ".join(bullish)
        )

    if bearish:
        message.append(
            "\n📉 <b>BEARISH</b>\n" +
            ", ".join(bearish)
        )

    send_alert("\n".join(message))


def run_scan():

    log.info(
        f"Scanning... "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    valid_pairs = get_binance_pairs()

    symbols = get_coins_above_mcap(valid_pairs)

    scan_timeframe(symbols, "1h", "1H")
    scan_timeframe(symbols, "4h", "4H")

    log.info("Scan complete.")


def wait_until_next_scan():

    now = datetime.now(timezone.utc)

    next_run = now.replace(
        minute=5,
        second=0,
        microsecond=0
    )

    if now >= next_run:
        next_run += timedelta(hours=1)

    sleep_seconds = (next_run - now).total_seconds()

    log.info(
        f"Next scan at "
        f"{next_run.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    time.sleep(sleep_seconds)


if __name__ == "__main__":
    log.info("Intraday EMA Scanner started.")
    send_alert("✅ EMA bot online")

    run_scan()  # run immediately after startup

    while True:
        wait_until_next_scan()
        run_scan()