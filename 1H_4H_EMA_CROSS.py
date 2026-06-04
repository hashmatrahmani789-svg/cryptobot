import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [1H-4H-CROSS] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

import os

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
MIN_MARKET_CAP   = 100_000_000
EMA_FAST         = 12
EMA_SLOW         = 21
CROSS_LOOKBACK   = 12
CHECK_INTERVAL   = 300

STABLECOINS = {
    "USDT","USDC","BUSD","DAI","TUSD","USDP","GUSD","FRAX","LUSD","USDD",
    "FDUSD","USDG","RLUSD","PYUSD","USDY","PAXG","USTB","USDAI","RUSD",
    "USDA","USDM","CRVUSD","EURS","AUSD","NUSD","FRXUSD","DUSD","SATUSD",
    "USDTB","EUTBL","EURC","EURCV","APXUSD","EURSAFO"
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
# COINGECKO — GET COINS ABOVE $100M MCAP
# called once per hour only
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
# granularity: 3600=1h, 14400=4h
# max 300 per request — fetch 2 pages = 600 candles
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
            # coinbase returns newest first: [time, low, high, open, close, volume]
            page_closes = [float(c[4]) for c in reversed(data)]
            closes = page_closes + closes
            end = start
            time.sleep(0.1)

        if len(closes) < 50:
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
# SIGNAL
# =========================
def check_signal(closes):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    for i in range(1, CROSS_LOOKBACK + 1):
        curr_idx = -i
        prev_idx = -(i + 1)

        if ema_fast[prev_idx] <= ema_slow[prev_idx] and ema_fast[curr_idx] > ema_slow[curr_idx]:
            return "BULLISH", i
        if ema_fast[prev_idx] >= ema_slow[prev_idx] and ema_fast[curr_idx] < ema_slow[curr_idx]:
            return "BEARISH", i

    return None, None


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(coins, interval_label):
    granularity = 3600 if interval_label == "1h" else 14400
    bullish = []
    bearish = []

    for ticker in coins:
        closes = get_candles_coinbase(ticker, granularity)
        if closes is None:
            continue

        direction, candles_ago = check_signal(closes)
        if direction is None:
            continue

        log.info(f"{ticker} [{interval_label}] {direction} ({candles_ago}c ago)")

        if direction == "BULLISH":
            bullish.append(ticker)
        else:
            bearish.append(ticker)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# BUILD MESSAGE
# =========================
def build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str):
    lines = [
        f"📊 <b>EMA 12/21 — Cross Alert</b>",
        f"━━━━━━━━━━━━━━━━",
    ]

    if bullish_1h or bearish_1h:
        lines.append(f"\n⏱ <b>1H Timeframe</b>")
        if bullish_1h:
            lines.append(f"📈 <b>Bullish</b>\n{'  •  '.join(bullish_1h)}")
        if bearish_1h:
            lines.append(f"📉 <b>Bearish</b>\n{'  •  '.join(bearish_1h)}")

    if bullish_4h or bearish_4h:
        lines.append(f"\n⏱ <b>4H Timeframe</b>")
        if bullish_4h:
            lines.append(f"📈 <b>Bullish</b>\n{'  •  '.join(bullish_4h)}")
        if bearish_4h:
            lines.append(f"📉 <b>Bearish</b>\n{'  •  '.join(bearish_4h)}")

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# SCAN
# =========================
def do_scan(coins, label=""):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if label:
        log.info(f"{label} scanning...")

    bullish_1h, bearish_1h = scan_timeframe(coins, "1h")
    bullish_4h, bearish_4h = scan_timeframe(coins, "4h")

    if any([bullish_1h, bearish_1h, bullish_4h, bearish_4h]):
        msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
        send_alert(msg)
        log.info("Signals sent.")
    else:
        log.info("No signals.")


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
# MAIN LOOP
# =========================
def run():
    log.info("1H 4H EMA Cross Scanner started.")
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nCoinGecko filter + Coinbase candles. Scanning at candle close.")

    coins = get_coins()
    last_coin_refresh = datetime.now(timezone.utc)

    do_scan(coins, label="Startup")

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now(timezone.utc)

        # refresh coins once per hour
        if (now - last_coin_refresh).total_seconds() > 3600:
            coins = get_coins()
            last_coin_refresh = now

        intervals = []
        if candle_just_closed("1h"):
            intervals.append("1h")
        if candle_just_closed("4h"):
            intervals.append("4h")

        if intervals:
            do_scan(coins, label="+".join(i.upper() for i in intervals))


if __name__ == "__main__":
    run()