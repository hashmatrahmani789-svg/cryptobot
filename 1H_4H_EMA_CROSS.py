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

COINS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "SHIB",
    "DOT", "LINK", "TON", "MATIC", "UNI", "ICP", "LTC", "APT", "NEAR", "FIL",
    "ARB", "OP", "ATOM", "VET", "ALGO", "HBAR", "MKR", "AAVE", "GRT", "SAND",
    "MANA", "AXS", "CRV", "SNX", "COMP", "LDO", "ENS", "1INCH", "BAL", "YFI",
    "SUSHI", "ZRX", "UMA", "REN", "STORJ", "SKL", "CELO", "FTM", "ROSE", "ZIL",
    "KAVA", "WAVES", "IOTA", "XTZ", "EOS", "NEO", "XLM", "BCH", "ETC", "DASH",
    "ZEC", "XMR", "EGLD", "THETA", "CHZ", "HOT", "ANKR", "ONE", "CELR",
    "DENT", "MTL", "OGN", "BAND", "RLC", "NMR", "BNT", "KNC", "LRC",
    "OMG", "BAT", "ZEN", "ICX", "ONT", "QTUM", "LSK", "SYS", "STMX",
    "FUN", "CVC", "REQ", "POL", "OCEAN", "FET", "RNDR", "INJ",
    "WLD", "SEI", "TIA", "PYTH", "JUP", "BONK", "WIF", "PEPE",
    "FLOKI", "CFX", "STX", "MINA", "SUI", "APE", "GMT", "GAL", "HIGH",
    "HOOK", "MAGIC", "DYDX", "GMX", "BLUR", "RPL", "FXS",
    "SPELL", "PEOPLE", "GLMR", "RUNE", "OSMO", "AKT",
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
# BINANCE — GET CANDLES
# =========================
def get_candles(ticker, interval):
    symbol = ticker + "USDT"
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": 150},
            timeout=10
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None, None
        data = data[:-1]
        closes  = [float(x[4]) for x in data]
        volumes = [float(x[5]) for x in data]
        return closes, volumes
    except:
        return None, None


# =========================
# BINANCE — GET 24H TICKER
# =========================
def get_ticker(ticker):
    symbol = ticker + "USDT"
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": symbol},
            timeout=10
        )
        data = r.json()
        return {
            "price":      float(data.get("lastPrice", 0)),
            "change_24h": float(data.get("priceChangePercent", 0)),
            "volume_24h": float(data.get("quoteVolume", 0)),
            "high_24h":   float(data.get("highPrice", 0)),
            "low_24h":    float(data.get("lowPrice", 0)),
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

    ema_fast = calc_ema(closes, EMA_FAST)
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
# FORMAT VOLUME
# =========================
def fmt_vol(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    return f"${v/1_000:.1f}K"


# =========================
# FORMAT PRICE
# =========================
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

    for ticker in COINS:
        closes, volumes = get_candles(ticker, interval)
        if closes is None:
            continue

        direction, candles_ago, ema_dist = check_signal(closes, volumes)
        if direction is None:
            continue

        ticker_data = get_ticker(ticker)
        if ticker_data is None:
            continue

        signal_label = "S1" if candles_ago == 1 else f"S2({candles_ago})"
        log.info(f"{ticker} [{interval}] {direction} {signal_label}")

        entry = {
            "ticker":      ticker,
            "signal":      signal_label,
            "candles_ago": candles_ago,
            "ema_dist":    ema_dist,
            "price":       ticker_data["price"],
            "change_24h":  ticker_data["change_24h"],
            "volume_24h":  ticker_data["volume_24h"],
            "high_24h":    ticker_data["high_24h"],
            "low_24h":     ticker_data["low_24h"],
            "tv_link":     f"https://www.tradingview.com/chart/?symbol=BINANCE:{ticker}USDT"
        }

        if direction == "BULLISH":
            bullish.append(entry)
        else:
            bearish.append(entry)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# FORMAT COIN LINE
# =========================
def fmt_coin(e):
    change = e["change_24h"]
    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
    return (
        f"<b>{e['ticker']}</b> [{e['signal']}]\n"
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