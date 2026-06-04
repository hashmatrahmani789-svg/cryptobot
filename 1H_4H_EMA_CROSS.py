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

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
MIN_MARKET_CAP    = 100_000_000
EMA_FAST          = 12
EMA_SLOW          = 21
VOLUME_MA_PERIOD  = 20
CROSS_LOOKBACK    = 12
CHECK_INTERVAL    = 300

STABLECOINS = {
    "USDT","USDC","BUSD","DAI","TUSD","USDP","GUSD","FRAX","LUSD","USDD",
    "FDUSD","USDG","RLUSD","PYUSD","USDY","PAXG","USTB","USDAI","RUSD",
    "USDA","USDM","CRVUSD","EURS","AUSD","NUSD","FRXUSD","DUSD","SATUSD",
    "USDTB","EUTBL","EURC","EURCV","APXUSD","EURSAFO","USDS","USDE",
    "SUSD","MUSD","CUSD","ZUSD","HUSD","OUSD","USDX","USDJ",
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
# FORMAT HELPERS
# =========================
def fmt_price(p):
    if p >= 1000:
        return f"${p:,.0f}"
    elif p >= 1:
        return f"${p:.2f}"
    elif p >= 0.01:
        return f"${p:.4f}"
    else:
        return f"${p:.6f}"

def fmt_mcap(m):
    if m >= 1_000_000_000:
        return f"${m/1_000_000_000:.1f}B"
    else:
        return f"${m/1_000_000:.0f}M"

def fmt_vol(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.1f}B"
    else:
        return f"${v/1_000_000:.0f}M"

def fmt_change(c):
    if c is None:
        return "N/A"
    sign = "+" if c >= 0 else ""
    return f"{sign}{c:.1f}%"

def tradingview_link(ticker):
    return f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD"


# =========================
# COINGECKO — GET COINS WITH DETAILS
# =========================
def get_coins():
    coins = {}
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
            for c in data:
                ticker = c["symbol"].upper()
                mcap = c.get("market_cap", 0)
                if mcap < MIN_MARKET_CAP:
                    continue
                if ticker in STABLECOINS or ticker.startswith("USD"):
                    continue
                coins[ticker] = {
                    "price":      c.get("current_price"),
                    "mcap":       mcap,
                    "change_24h": c.get("price_change_percentage_24h"),
                    "volume_24h": c.get("total_volume"),
                }
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
# COINBASE — GET CANDLES WITH VOLUME
# =========================
def get_candles_coinbase(ticker, granularity_seconds):
    product_id = f"{ticker}-USD"
    try:
        closes = []
        volumes = []
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
            page_closes  = [float(c[4]) for c in reversed(data)]
            page_volumes = [float(c[5]) for c in reversed(data)]
            closes  = page_closes  + closes
            volumes = page_volumes + volumes
            end = start
            time.sleep(0.1)

        if len(closes) < 50:
            return None, None
        return closes[:-1], volumes[:-1]
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
# VOLUME ABOVE MA
# =========================
def volume_above_ma(volumes, period=VOLUME_MA_PERIOD):
    if len(volumes) < period + 1:
        return False
    ma = sum(volumes[-(period + 1):-1]) / period
    return volumes[-1] > ma


# =========================
# SIGNAL
# =========================
def check_signal(closes, volumes):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    for i in range(1, CROSS_LOOKBACK + 1):
        curr_idx = -i
        prev_idx = -(i + 1)

        if ema_fast[prev_idx] <= ema_slow[prev_idx] and ema_fast[curr_idx] > ema_slow[curr_idx]:
            if volume_above_ma(volumes):
                return "BULLISH", i
        if ema_fast[prev_idx] >= ema_slow[prev_idx] and ema_fast[curr_idx] < ema_slow[curr_idx]:
            if volume_above_ma(volumes):
                return "BEARISH", i

    return None, None


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(coins, interval_label):
    granularity = 3600 if interval_label == "1h" else 14400
    bullish = []
    bearish = []

    for ticker, info in coins.items():
        closes, volumes = get_candles_coinbase(ticker, granularity)
        if closes is None:
            continue

        direction, candles_ago = check_signal(closes, volumes)
        if direction is None:
            continue

        log.info(f"{ticker} [{interval_label}] {direction} ({candles_ago}c ago)")

        entry = {
            "ticker":      ticker,
            "candles_ago": candles_ago,
            "price":       info.get("price"),
            "mcap":        info.get("mcap"),
            "change_24h":  info.get("change_24h"),
            "volume_24h":  info.get("volume_24h"),
        }

        if direction == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# FORMAT COIN ENTRY
# =========================
def fmt_coin(entry, direction):
    ticker = entry["ticker"]
    price  = fmt_price(entry["price"]) if entry["price"] else "N/A"
    mcap   = fmt_mcap(entry["mcap"]) if entry["mcap"] else "N/A"
    change = fmt_change(entry["change_24h"])
    vol    = fmt_vol(entry["volume_24h"]) if entry["volume_24h"] else "N/A"
    cago   = entry["candles_ago"]
    link   = tradingview_link(ticker)
    emoji  = "📈" if direction == "BULLISH" else "📉"
    label  = "🟢 BULLISH" if direction == "BULLISH" else "🔴 BEARISH"

    return (
        f"{emoji} <b>{ticker}</b> — {price}  {label}\n"
        f"MCap: {mcap}  |  24h: {change}  |  Vol: {vol}\n"
        f"Cross: {cago}c ago  |  <a href='{link}'>TradingView</a>"
    )


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
        for entry in bullish_1h:
            lines.append(fmt_coin(entry, "BULLISH"))
        for entry in bearish_1h:
            lines.append(fmt_coin(entry, "BEARISH"))

    if bullish_4h or bearish_4h:
        lines.append(f"\n⏱ <b>4H Timeframe</b>")
        for entry in bullish_4h:
            lines.append(fmt_coin(entry, "BULLISH"))
        for entry in bearish_4h:
            lines.append(fmt_coin(entry, "BEARISH"))

    lines.append(f"\n🕐 {now_str}")
    return "\n\n".join(lines)


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
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nCoinGecko + Coinbase. Volume filter ON. Scanning at candle close.")

    coins = get_coins()
    last_coin_refresh = datetime.now(timezone.utc)

    do_scan(coins, label="Startup")

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now(timezone.utc)

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