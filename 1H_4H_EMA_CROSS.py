import os
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

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
EMA_FAST         = 12
EMA_SLOW         = 21
VOLUME_MA_PERIOD = 20
CROSS_LOOKBACK   = 12

# =========================
# HARDCODED COIN LIST
# Format: (ticker, market_cap_string)
# Update market caps manually once a week
# Only coins with $200M+ mcap listed on Coinbase
# =========================
COINS = [
    ("BTC",   "$1.3T"),
    ("ETH",   "$320B"),
    ("SOL",   "$85B"),
    ("XRP",   "$130B"),
    ("BNB",   "$90B"),
    ("DOGE",  "$26B"),
    ("ADA",   "$22B"),
    ("TRX",   "$20B"),
    ("AVAX",  "$15B"),
    ("SHIB",  "$12B"),
    ("DOT",   "$10B"),
    ("LINK",  "$9B"),
    ("TON",   "$8B"),
    ("UNI",   "$7B"),
    ("LTC",   "$7B"),
    ("APT",   "$6B"),
    ("NEAR",  "$6B"),
    ("ICP",   "$5B"),
    ("FIL",   "$4B"),
    ("ARB",   "$4B"),
    ("OP",    "$3B"),
    ("ATOM",  "$3B"),
    ("HBAR",  "$3B"),
    ("MKR",   "$3B"),
    ("AAVE",  "$3B"),
    ("VET",   "$2.5B"),
    ("ALGO",  "$2B"),
    ("GRT",   "$2B"),
    ("LDO",   "$2B"),
    ("RNDR",  "$2B"),
    ("INJ",   "$2B"),
    ("IMX",   "$2B"),
    ("FET",   "$2B"),
    ("STX",   "$2B"),
    ("SAND",  "$1.5B"),
    ("MANA",  "$1.5B"),
    ("AXS",   "$1.5B"),
    ("CRV",   "$1.5B"),
    ("SNX",   "$1.2B"),
    ("COMP",  "$1.2B"),
    ("ENS",   "$1B"),
    ("1INCH", "$900M"),
    ("YFI",   "$900M"),
    ("SUSHI", "$800M"),
    ("ZRX",   "$700M"),
    ("BAL",   "$700M"),
    ("OCEAN", "$700M"),
    ("WLD",   "$700M"),
    ("SEI",   "$700M"),
    ("TIA",   "$700M"),
    ("SUI",   "$700M"),
    ("PEPE",  "$650B"),
    ("FLOKI", "$600M"),
    ("BONK",  "$600M"),
    ("WIF",   "$600M"),
    ("PYTH",  "$600M"),
    ("JUP",   "$600M"),
    ("DYDX",  "$600M"),
    ("GMX",   "$600M"),
    ("RPL",   "$600M"),
    ("FXS",   "$500M"),
    ("BLUR",  "$500M"),
    ("CFX",   "$500M"),
    ("MINA",  "$500M"),
    ("APE",   "$500M"),
    ("GMT",   "$500M"),
    ("GAL",   "$500M"),
    ("MAGIC", "$500M"),
    ("HOOK",  "$400M"),
    ("PERP",  "$400M"),
    ("SPELL", "$400M"),
    ("PEOPLE","$400M"),
    ("GLMR",  "$400M"),
    ("RUNE",  "$400M"),
    ("OSMO",  "$400M"),
    ("AKT",   "$400M"),
    ("XLM",   "$4B"),
    ("BCH",   "$7B"),
    ("ETC",   "$4B"),
    ("XTZ",   "$800M"),
    ("EOS",   "$1B"),
    ("EGLD",  "$1.5B"),
    ("THETA", "$1B"),
    ("CHZ",   "$700M"),
    ("ANKR",  "$500M"),
    ("FTM",   "$1B"),
    ("ROSE",  "$500M"),
    ("KAVA",  "$600M"),
    ("WAVES", "$400M"),
    ("ZIL",   "$400M"),
    ("ONE",   "$300M"),
    ("CELR",  "$300M"),
    ("BAND",  "$300M"),
    ("NMR",   "$300M"),
    ("KNC",   "$300M"),
    ("LRC",   "$300M"),
    ("BAT",   "$400M"),
    ("ICX",   "$300M"),
    ("QTUM",  "$400M"),
    ("ZEN",   "$300M"),
    ("ONT",   "$300M"),
    ("STORJ", "$300M"),
    ("SKL",   "$300M"),
    ("CELO",  "$400M"),
    ("RLC",   "$300M"),
    ("UMA",   "$300M"),
    ("OGN",   "$200M"),
    ("MTL",   "$200M"),
    ("FUN",   "$200M"),
    ("REQ",   "$200M"),
    ("POL",   "$200M"),
]


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
# COINBASE — GET CANDLES
# =========================
def get_candles(ticker, interval):
    granularity_map = {
        "1h": "ONE_HOUR",
        "4h": "FOUR_HOUR"
    }
    granularity = granularity_map.get(interval)
    product_id = f"{ticker}-USDT"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": granularity, "limit": 150},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 50:
            return None, None
        candles = list(reversed(candles))[:-1]
        closes  = [float(c["close"]) for c in candles]
        volumes = [float(c["volume"]) for c in candles]
        return closes, volumes
    except:
        return None, None


# =========================
# COINBASE — GET 24H TICKER
# =========================
def get_ticker(ticker):
    product_id = f"{ticker}-USDT"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}",
            timeout=10
        )
        data = r.json()
        price      = float(data.get("price", 0))
        change_24h = float(data.get("price_percentage_change_24h", 0))
        volume_24h = float(data.get("volume_24h", 0))
        high_24h   = float(data.get("high_52_week", 0))
        low_24h    = float(data.get("low_52_week", 0))
        return {
            "price":      price,
            "change_24h": change_24h,
            "volume_24h": volume_24h,
            "high_24h":   high_24h,
            "low_24h":    low_24h,
        }
    except:
        return None


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
# =========================
def volume_above_ma(volumes, candle_index=-1, period=VOLUME_MA_PERIOD):
    abs_index = len(volumes) + candle_index
    if abs_index < period:
        return False
    ma = sum(volumes[abs_index - period : abs_index]) / period
    return volumes[abs_index] > ma


# =========================
# FIND EMA CROSS
# =========================
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


# =========================
# SIGNAL LOGIC
# =========================
def check_signal(closes, volumes):
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


# =========================
# FORMAT HELPERS
# =========================
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


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(interval):
    bullish = []
    bearish = []

    for ticker, mcap in COINS:
        closes, volumes = get_candles(ticker, interval)
        if closes is None:
            continue

        direction, candles_ago, ema_dist = check_signal(closes, volumes)
        if direction is None:
            continue

        ticker_data = get_ticker(ticker)
        signal_label = "S1" if candles_ago == 1 else f"S2({candles_ago})"
        log.info(f"{ticker} [{interval}] {direction} {signal_label}")

        entry = {
            "ticker":      ticker,
            "mcap":        mcap,
            "signal":      signal_label,
            "ema_dist":    ema_dist,
            "price":       ticker_data["price"] if ticker_data else 0,
            "change_24h":  ticker_data["change_24h"] if ticker_data else 0,
            "volume_24h":  ticker_data["volume_24h"] if ticker_data else 0,
            "high_24h":    ticker_data["high_24h"] if ticker_data else 0,
            "low_24h":     ticker_data["low_24h"] if ticker_data else 0,
            "tv_link":     f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USDT"
        }

        if direction == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

        time.sleep(0.1)

    return bullish, bearish


# =========================
# FORMAT COIN LINE
# =========================
def fmt_coin(e):
    change = e["change_24h"]
    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
    return (
        f"<b>{e['ticker']}</b> [{e['signal']}] — MCap: {e['mcap']}\n"
        f"💰 {fmt_price(e['price'])} | 24h: {change_str}\n"
        f"📊 Vol: {fmt_vol(e['volume_24h'])} | EMA dist: {e['ema_dist']:.1f}%\n"
        f"📉 Range: {fmt_price(e['low_24h'])} — {fmt_price(e['high_24h'])}\n"
        f"<a href='{e['tv_link']}'>📈 TradingView</a>"
    )


# =========================
# BUILD MESSAGE
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


# =========================
# MAIN SCAN
# =========================
def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")
    bullish_1h, bearish_1h = scan_timeframe("1h")
    bullish_4h, bearish_4h = scan_timeframe("4h")
    msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
    send_alert(msg)
    log.info("Scan complete.")


# =========================
# HOURLY TIMER — runs at :00
# =========================
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=0, second=0, microsecond=0)
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
    send_alert("✅ <b>EMA 12/21 Scanner Online</b>\nScanning 1H + 4H every hour at :00.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()