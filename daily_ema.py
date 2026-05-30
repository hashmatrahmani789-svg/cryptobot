import os
import time
import logging
import requests
from datetime import datetime, timezone

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EMA-CROSS] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── ENV VARS (set these in Railway) ────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MIN_MARKET_CAP = 50_000_000  # $50M

# ── TELEGRAM ───────────────────────────────────────────────────────────────
def send_alert(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ── COINGECKO: get coins > $50M mcap ──────────────────────────────────────
def get_coins_above_mcap():
    coins = []
    page = 1
    while True:
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": page,
                "sparkline": False
            }
            res = requests.get(url, params=params, timeout=15)
            data = res.json()
            if not data:
                break
            filtered = [c for c in data if c.get("market_cap", 0) >= MIN_MARKET_CAP]
            coins.extend(filtered)
            # If last coin on page is below $50M, no need to go further
            if data[-1].get("market_cap", 0) < MIN_MARKET_CAP:
                break
            page += 1
            time.sleep(2)  # CoinGecko rate limit
        except Exception as e:
            log.error(f"CoinGecko error: {e}")
            break
    log.info(f"{len(coins)} coins loaded with mcap > $50M")
    return coins

# ── BINANCE: get daily closes ──────────────────────────────────────────────
def get_daily_closes(symbol: str, limit: int = 25):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < limit:
            return None
        # index 4 = close price, skip last candle (current open candle)
        closes = [float(k[4]) for k in data[:-1]]
        return closes
    except Exception:
        return None

# ── EMA CALCULATION ────────────────────────────────────────────────────────
def calc_ema(closes: list, period: int) -> list:
    k = 2 / (period + 1)
    ema = [closes[0]]
    for price in closes[1:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

# ── CHECK CROSS ON LAST CLOSED CANDLE ─────────────────────────────────────
def check_cross(closes: list):
    ema12 = calc_ema(closes, 12)
    ema21 = calc_ema(closes, 21)

    # Last two confirmed candles
    prev12, prev21 = ema12[-2], ema21[-2]
    curr12, curr21 = ema12[-1], ema21[-1]

    if prev12 <= prev21 and curr12 > curr21:
        return "BULLISH"
    if prev12 >= prev21 and curr12 < curr21:
        return "BEARISH"
    return None

# ── MAIN SCAN ──────────────────────────────────────────────────────────────
def run_scan():
    log.info(f"Scanning... {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    coins = get_coins_above_mcap()

    bullish_hits = []
    bearish_hits = []

    for coin in coins:
        symbol_raw = coin.get("symbol", "").upper() + "USDT"
        closes = get_daily_closes(symbol_raw)

        if closes is None or len(closes) < 22:
            # Try BTC pair as fallback
            symbol_btc = coin.get("symbol", "").upper() + "BTC"
            closes = get_daily_closes(symbol_btc)
            if closes is None or len(closes) < 22:
                continue

        cross = check_cross(closes)
        if cross == "BULLISH":
            bullish_hits.append(coin.get("symbol", "").upper())
        elif cross == "BEARISH":
            bearish_hits.append(coin.get("symbol", "").upper())

        time.sleep(0.08)  # Binance rate limit safety

    # ── Send Alerts ────────────────────────────────────────────────────────
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if bullish_hits:
        msg = (
            f"📈 <b>EMA 12/21 BULLISH CROSS</b> — Daily Close\n"
            f"🗓 {date_str}\n\n"
            f"<b>Coins:</b> {', '.join(bullish_hits)}\n\n"
            f"✅ EMA 12 crossed <b>above</b> EMA 21 on confirmed daily candle"
        )
        send_alert(msg)
        log.info(f"Bullish crosses: {bullish_hits}")

    if bearish_hits:
        msg = (
            f"📉 <b>EMA 12/21 BEARISH CROSS</b> — Daily Close\n"
            f"🗓 {date_str}\n\n"
            f"<b>Coins:</b> {', '.join(bearish_hits)}\n\n"
            f"❌ EMA 12 crossed <b>below</b> EMA 21 on confirmed daily candle"
        )
        send_alert(msg)
        log.info(f"Bearish crosses: {bearish_hits}")

    if not bullish_hits and not bearish_hits:
        log.info("No crosses found today.")

    log.info("Scan complete.")

# ── SCHEDULER: runs once per day at 00:05 UTC ─────────────────────────────
def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    # Target: 00:05 UTC daily
    target_hour, target_minute = 0, 5
    next_run = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if now >= next_run:
        from datetime import timedelta
        next_run += timedelta(days=1)
    sleep_seconds = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_seconds/3600:.1f}h")
    time.sleep(sleep_seconds)

# ── ENTRY POINT ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("EMA 12/21 Cross Signal started.")
    while True:
        wait_until_next_scan()
        run_scan()