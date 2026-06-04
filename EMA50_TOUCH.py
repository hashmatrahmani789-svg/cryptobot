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

import os

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
MIN_MARKET_CAP    = 100_000_000
EMA_PERIOD        = 50
CHECK_INTERVAL    = 300

STABLECOINS = {
    "USDT","USDC","BUSD","DAI","TUSD","USDP","GUSD","FRAX","LUSD","USDD",
    "FDUSD","USDG","RLUSD","PYUSD","USDY","PAXG","USTB","USDAI","RUSD",
    "USDA","USDM","CRVUSD","EURS","AUSD","NUSD","FRXUSD","DUSD","SATUSD",
    "USDTB","EUTBL","EURC","EURCV","APXUSD","EURSAFO","USDS","USDE",
    "SUSD","TUSD","MUSD","CUSD","ZUSD","HUSD","OUSD","USDX","USDJ",
    "USDN","USDQ","USDW","USDFL","USDH","USDL","USDV","USDZ"
}


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
# COINGECKO — refreshes at :30 every hour (offset from EMA cross bot)
# =========================
def get_coins():
    coins = []
    page = 1
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

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
                headers=headers,
                timeout=20
            )
            data = r.json()
            if not isinstance(data, list):
                log.error(f"CoinGecko bad response: {data}")
                break
            if not data:
                break
            filtered = [
                c["symbol"].upper() for c in data
                if c.get("market_cap", 0) >= MIN_MARKET_CAP
                and c["symbol"].upper() not in STABLECOINS
                and not c["symbol"].upper().startswith("USD")
            ]
            coins.extend(filtered)
            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break
            page += 1
            time.sleep(2)
        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break

    log.info(f"{len(coins)} coins loaded from CoinGecko")
    return coins


# =========================
# COINBASE — GET CANDLES
# =========================
def get_candles_coinbase(ticker, granularity_seconds):
    product_id = f"{ticker}-USD"
    try:
        closes = []
        end = datetime.now(timezone.utc)

        for _ in range(2):
            start = end - timedelta(seconds=granularity_seconds * 300)
            r = requests.get(
                f"https://api.exchange.coinbase.com/products/{product_id}/candles",
                params={
                    "granularity": granularity_seconds,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
                timeout=10
            )
            data = r.json()
            if not isinstance(data, list) or not data:
                break
            page_closes = [float(c[4]) for c in reversed(data)]
            closes = page_closes + closes
            end = start
            time.sleep(0.1)

        if len(closes) < 60:
            return None
        return closes[:-1]  # exclude live candle
    except:
        return None


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
# SIGNAL — wick touched EMA 50
# low <= EMA <= high
# =========================
def check_touch(closes):
    ema = calc_ema(closes, EMA_PERIOD)
    e = ema[-1]

    # need high and low — fetch full candle data
    return e, closes[-1]


def check_touch_full(candles):
    closes = [c["close"] for c in candles]
    ema = calc_ema(closes, EMA_PERIOD)
    e = ema[-1]
    c = candles[-1]

    if c["low"] <= e <= c["high"]:
        if c["close"] >= e:
            return "BULLISH"
        else:
            return "BEARISH"
    return None


# =========================
# COINBASE — GET FULL CANDLES (with high/low)
# =========================
def get_full_candles_coinbase(ticker, granularity_seconds):
    product_id = f"{ticker}-USD"
    try:
        candles = []
        end = datetime.now(timezone.utc)

        for _ in range(2):
            start = end - timedelta(seconds=granularity_seconds * 300)
            r = requests.get(
                f"https://api.exchange.coinbase.com/products/{product_id}/candles",
                params={
                    "granularity": granularity_seconds,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
                timeout=10
            )
            data = r.json()
            if not isinstance(data, list) or not data:
                break
            # [time, low, high, open, close, volume]
            page = [{"low": float(c[1]), "high": float(c[2]), "close": float(c[4])} for c in reversed(data)]
            candles = page + candles
            end = start
            time.sleep(0.1)

        if len(candles) < 60:
            return None
        return candles[:-1]  # exclude live candle
    except:
        return None


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(coins, interval_label):
    granularity = 3600 if interval_label == "1h" else 14400
    bullish = []
    bearish = []

    for ticker in coins:
        candles = get_full_candles_coinbase(ticker, granularity)
        if candles is None:
            continue

        direction = check_touch_full(candles)
        if direction is None:
            continue

        log.info(f"{ticker} [{interval_label}] {direction} (touch)")

        if direction == "BULLISH":
            bullish.append(ticker)
        else:
            bearish.append(ticker)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# BUILD MESSAGE
# =========================
def build_message(results_by_tf, now_str):
    has_signals = any(bull or bear for bull, bear in results_by_tf.values())

    if not has_signals:
        return (
            f"🔍 <b>EMA 50 Scan</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"No touches found on 1H or 4H\n\n"
            f"🕐 {now_str}"
        )

    lines = [
        "🎯 <b>EMA 50 — Touch Alert</b>",
        "━━━━━━━━━━━━━━━━",
    ]

    for interval, (bullish, bearish) in results_by_tf.items():
        if not bullish and not bearish:
            continue
        label = "1H" if interval == "1h" else "4H"
        lines.append(f"\n⏱ <b>{label} Timeframe</b>")
        if bullish:
            lines.append(f"📈 <b>Bullish</b>\n{'  •  '.join(bullish)}")
        if bearish:
            lines.append(f"📉 <b>Bearish</b>\n{'  •  '.join(bearish)}")

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# SCAN
# =========================
def do_scan(coins, label=""):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if label:
        log.info(f"{label} scanning...")

    results = {}
    for interval in ["1h", "4h"]:
        bullish, bearish = scan_timeframe(coins, interval)
        results[interval] = (bullish, bearish)

    msg = build_message(results, now_str)
    send_alert(msg)
    log.info("Scan complete.")


# =========================
# CANDLE JUST CLOSED
# =========================
def candle_just_closed(interval):
    now = datetime.now(timezone.utc)
    if interval == "1h":
        return now.minute < 2
    if interval == "4h":
        return now.hour % 4 == 0 and now.minute < 2
    return False


# =========================
# COIN REFRESH — at :30 every hour (offset from EMA cross bot at :00)
# =========================
def coins_need_refresh(last_refresh):
    now = datetime.now(timezone.utc)
    if (now - last_refresh).total_seconds() < 3600:
        return False
    return True


# =========================
# MAIN LOOP
# =========================
def run():
    log.info("EMA 50 Touch Scanner started.")
    send_alert("✅ <b>EMA 50 Scanner Online</b>\nCoinGecko + Coinbase. Scanning 1H + 4H at candle close.")

    # wait until :30 to load coins (offset from EMA cross bot)
    now = datetime.now(timezone.utc)
    if now.minute < 30:
        wait = now.replace(minute=30, second=0, microsecond=0)
    else:
        wait = (now + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
    sleep_secs = (wait - now).total_seconds()
    if sleep_secs > 60:
        log.info(f"Waiting until :30 to load coins — sleeping {sleep_secs/60:.1f}m")
        time.sleep(sleep_secs)

    coins = get_coins()
    last_coin_refresh = datetime.now(timezone.utc)

    do_scan(coins, label="Startup")

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now(timezone.utc)

        if coins_need_refresh(last_coin_refresh):
            coins = get_coins()
            last_coin_refresh = now

        if candle_just_closed("1h") or candle_just_closed("4h"):
            do_scan(coins, label="Candle close")


if __name__ == "__main__":
    run()