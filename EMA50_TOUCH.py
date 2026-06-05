import os
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

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
EMA_PERIOD       = 50

# =========================
# HARDCODED COIN LIST
# Format: (ticker, market_cap_string)
# Update market caps manually once a week
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
    ("PEPE",  "$6.5B"),
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
        return {
            "price":      float(data.get("price", 0)),
            "change_24h": float(data.get("price_percentage_change_24h", 0)),
            "volume_24h": float(data.get("volume_24h", 0)),
            "high_24h":   float(data.get("high_52_week", 0)),
            "low_24h":    float(data.get("low_52_week", 0)),
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
# SIGNAL LOGIC
# Step 1 — 4H candle touches the 50 EMA
# Step 2 — 1H candle closes above/below the 50 EMA
# =========================
def check_4h_touch(candles_4h, ema_4h):
    c   = candles_4h[-1]
    e   = ema_4h[-1]
    tol = e * 0.003
    return c["low"] <= e + tol and c["high"] >= e - tol


def check_1h_confirmation(candles_1h, ema_1h):
    c = candles_1h[-1]
    e = ema_1h[-1]
    if c["close"] > e:
        return "BULLISH"
    if c["close"] < e:
        return "BEARISH"
    return None


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
# SCAN ALL COINS
# =========================
def scan_coins():
    bullish = []
    bearish = []

    for ticker, mcap in COINS:
        candles_4h = get_candles(ticker, "4h")
        if candles_4h is None:
            continue

        candles_1h = get_candles(ticker, "1h")
        if candles_1h is None:
            continue

        closes_4h = [c["close"] for c in candles_4h]
        closes_1h = [c["close"] for c in candles_1h]

        ema_4h = calc_ema(closes_4h, EMA_PERIOD)
        ema_1h = calc_ema(closes_1h, EMA_PERIOD)

        if not check_4h_touch(candles_4h, ema_4h):
            continue

        direction = check_1h_confirmation(candles_1h, ema_1h)
        if direction is None:
            continue

        ticker_data = get_ticker(ticker)
        ema_dist = abs(closes_1h[-1] - ema_1h[-1]) / ema_1h[-1] * 100

        log.info(f"{ticker} EMA50 touch — {direction}")

        entry = {
            "ticker":     ticker,
            "mcap":       mcap,
            "ema_dist":   ema_dist,
            "price":      ticker_data["price"] if ticker_data else 0,
            "change_24h": ticker_data["change_24h"] if ticker_data else 0,
            "volume_24h": ticker_data["volume_24h"] if ticker_data else 0,
            "high_24h":   ticker_data["high_24h"] if ticker_data else 0,
            "low_24h":    ticker_data["low_24h"] if ticker_data else 0,
            "tv_link":    f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USDT"
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
        f"<b>{e['ticker']}</b> — MCap: {e['mcap']}\n"
        f"💰 {fmt_price(e['price'])} | 24h: {change_str}\n"
        f"📊 Vol: {fmt_vol(e['volume_24h'])} | EMA dist: {e['ema_dist']:.1f}%\n"
        f"📉 Range: {fmt_price(e['low_24h'])} — {fmt_price(e['high_24h'])}\n"
        f"<a href='{e['tv_link']}'>📈 TradingView</a>"
    )


# =========================
# BUILD MESSAGE
# =========================
def build_message(bullish, bearish, now_str):
    if not bullish and not bearish:
        return (
            f"🔍 <b>EMA 50 Scan</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"No 4H touches confirmed on 1H\n\n"
            f"🕐 {now_str}"
        )

    lines = ["🎯 <b>EMA 50 — Touch Alert</b>", "━━━━━━━━━━━━━━━━"]

    if bullish:
        lines.append("\n📈 <b>Bullish</b> — 4H touched + 1H closed above")
        for e in bullish:
            lines.append(fmt_coin(e))

    if bearish:
        lines.append("\n📉 <b>Bearish</b> — 4H touched + 1H closed below")
        for e in bearish:
            lines.append(fmt_coin(e))

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# MAIN SCAN
# =========================
def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")
    bullish, bearish = scan_coins()
    msg = build_message(bullish, bearish, now_str)
    send_alert(msg)
    log.info("Scan complete.")


# =========================
# HOURLY TIMER — runs at :15
# =========================
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    next_run = now.replace(minute=15, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


# =========================
# START
# =========================
if __name__ == "__main__":
    log.info("EMA 50 Touch Scanner started.")
    send_alert("✅ <b>EMA 50 Scanner Online</b>\nScanning 4H touch + 1H confirmation every hour at :15.")
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()
