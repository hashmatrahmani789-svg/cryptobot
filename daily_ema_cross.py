import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAILY-EMA] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
CROSS_LOOKBACK   = 3

# ── Stablecoins to exclude ──────────────────────────────────────────────────
STABLECOINS = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USDD", "GUSD",
    "FRAX", "LUSD", "SUSD", "CUSD", "EURC", "PYUSD", "FDUSD", "USDE",
    "USDS", "USDX", "ALUSD", "CRVUSD", "GHO", "MKUSD", "DOLA", "EURS",
    "EURT", "XAUT", "PAXG"
}

# ── Coin list with market cap tiers ─────────────────────────────────────────
# Format: (ticker, market_cap_usd)
# Only coins >= $200M market cap for spot trading
COINS = [
    # Mega cap > $10B
    ("BTC",   2_000_000_000_000),
    ("ETH",   400_000_000_000),
    ("BNB",   90_000_000_000),
    ("SOL",   80_000_000_000),
    ("XRP",   70_000_000_000),
    ("ADA",   20_000_000_000),
    ("AVAX",  15_000_000_000),
    ("DOT",   10_000_000_000),
    ("LINK",  10_000_000_000),
    ("TON",   10_000_000_000),
    # Large cap $1B–$10B
    ("MATIC", 8_000_000_000),
    ("UNI",   6_000_000_000),
    ("ATOM",  4_000_000_000),
    ("LTC",   4_000_000_000),
    ("BCH",   4_000_000_000),
    ("NEAR",  4_000_000_000),
    ("FIL",   3_000_000_000),
    ("ICP",   3_000_000_000),
    ("APT",   3_000_000_000),
    ("ARB",   2_500_000_000),
    ("OP",    2_000_000_000),
    ("INJ",   2_000_000_000),
    ("SUI",   2_000_000_000),
    ("TIA",   1_500_000_000),
    ("TAO",   1_500_000_000),
    ("ONDO",  1_200_000_000),
    ("ENA",   1_200_000_000),
    ("PENDLE",1_000_000_000),
    ("AERO",  1_000_000_000),
    ("DOGE",  20_000_000_000),
    ("SHIB",  8_000_000_000),
    ("TRX",   10_000_000_000),
    ("HBAR",  3_000_000_000),
    ("STX",   2_000_000_000),
    ("MKR",   2_000_000_000),
    ("AAVE",  2_000_000_000),
    ("GRT",   1_000_000_000),
    ("SNX",   800_000_000),
    ("CRV",   600_000_000),
    ("ZEC",   500_000_000),
    # Mid cap $200M–$1B
    ("ALGO",  900_000_000),
    ("SAND",  700_000_000),
    ("MANA",  600_000_000),
    ("1INCH", 400_000_000),
    ("ENS",   400_000_000),
    ("COMP",  300_000_000),
    ("SUSHI", 250_000_000),
    ("BAL",   200_000_000),
]


def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
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


def get_daily_candles(ticker, limit=60):
    """Fetch daily candles from Coinbase."""
    product_id = f"{ticker}-USD"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": "ONE_DAY", "limit": limit},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 25:
            return None, None
        candles = list(reversed(candles))[:-1]
        closes  = [float(c["close"])  for c in candles]
        volumes = [float(c["volume"]) for c in candles]
        return closes, volumes
    except:
        return None, None


def get_coin_stats(ticker):
    """Fetch 24h change, volume, and market cap from CoinGecko."""
    try:
        # Map ticker to CoinGecko id for common coins
        id_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
            "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
            "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
            "TON": "the-open-network", "MATIC": "matic-network",
            "UNI": "uniswap", "ATOM": "cosmos", "LTC": "litecoin",
            "BCH": "bitcoin-cash", "NEAR": "near", "FIL": "filecoin",
            "ICP": "internet-computer", "APT": "aptos", "ARB": "arbitrum",
            "OP": "optimism", "INJ": "injective-protocol", "SUI": "sui",
            "TIA": "celestia", "TAO": "bittensor", "ONDO": "ondo-finance",
            "ENA": "ethena", "PENDLE": "pendle", "AERO": "aerodrome-finance",
            "DOGE": "dogecoin", "SHIB": "shiba-inu", "TRX": "tron",
            "HBAR": "hedera-hashgraph", "STX": "blockstack",
            "MKR": "maker", "AAVE": "aave", "GRT": "the-graph",
            "SNX": "havven", "CRV": "curve-dao-token", "ZEC": "zcash",
            "ALGO": "algorand", "SAND": "the-sandbox", "MANA": "decentraland",
            "1INCH": "1inch", "ENS": "ethereum-name-service",
            "COMP": "compound-governance-token", "SUSHI": "sushi", "BAL": "balancer",
        }
        cg_id = id_map.get(ticker)
        if not cg_id:
            return None, None, None
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": cg_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true"
            },
            timeout=10
        )
        d = r.json().get(cg_id, {})
        change = d.get("usd_24h_change")
        volume = d.get("usd_24h_vol")
        mcap   = d.get("usd_market_cap")
        return change, volume, mcap
    except:
        return None, None, None


def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def check_cross(closes):
    ema12 = calc_ema(closes, 12)
    ema21 = calc_ema(closes, 21)
    for i in range(1, CROSS_LOOKBACK + 1):
        curr_idx = -i
        prev_idx = -(i + 1)
        prev12, prev21 = ema12[prev_idx], ema21[prev_idx]
        curr12, curr21 = ema12[curr_idx], ema21[curr_idx]
        if prev12 <= prev21 and curr12 > curr21:
            return "BULLISH", i, ema12[-1], ema21[-1]
        if prev12 >= prev21 and curr12 < curr21:
            return "BEARISH", i, ema12[-1], ema21[-1]
    return None, None, None, None


def fmt_price(p):
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"


def fmt_mcap(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    return f"${v/1_000_000:.0f}M"


def fmt_vol(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    return f"${v/1_000_000:.0f}M"


def get_mcap_tier(mcap_usd):
    if mcap_usd >= 10_000_000_000:
        return "MEGA"   # > $10B
    if mcap_usd >= 1_000_000_000:
        return "LARGE"  # $1B–$10B
    return "MID"        # $200M–$1B


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Daily scan running... {now_str}")

    # Separate buckets: mega+large (>$1B) vs mid ($200M-$1B)
    mega_large_bullish = []
    mega_large_bearish = []
    mid_bullish = []
    mid_bearish = []
    skipped = 0

    for ticker, static_mcap in COINS:
        # Skip stablecoins
        if ticker in STABLECOINS:
            continue

        closes, volumes = get_daily_candles(ticker)
        if closes is None or len(closes) < 22:
            skipped += 1
            time.sleep(0.2)
            continue

        direction, candles_ago, ema12_val, ema21_val = check_cross(closes)

        if direction is None:
            time.sleep(0.2)
            continue

        # Get live stats from CoinGecko
        change_24h, vol_24h, live_mcap = get_coin_stats(ticker)
        time.sleep(0.5)  # respect CoinGecko rate limit

        mcap_usd  = live_mcap if live_mcap else static_mcap
        tier      = get_mcap_tier(mcap_usd)
        price     = closes[-1]
        avg_vol   = sum(volumes[-10:]) / 10 if volumes else 0
        cur_vol   = volumes[-1] if volumes else 0
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0

        entry = {
            "ticker":     ticker,
            "price":      price,
            "mcap":       mcap_usd,
            "change_24h": change_24h,
            "vol_24h":    vol_24h,
            "ema12":      ema12_val,
            "ema21":      ema21_val,
            "days_ago":   candles_ago,
            "vol_ratio":  vol_ratio,
            "tier":       tier,
        }

        if tier in ("MEGA", "LARGE"):
            if direction == "BULLISH":
                mega_large_bullish.append(entry)
                log.info(f"{ticker} [{tier}] DAILY BULLISH cross ({candles_ago}d ago)")
            else:
                mega_large_bearish.append(entry)
                log.info(f"{ticker} [{tier}] DAILY BEARISH cross ({candles_ago}d ago)")
        else:
            if direction == "BULLISH":
                mid_bullish.append(entry)
                log.info(f"{ticker} [MID] DAILY BULLISH cross ({candles_ago}d ago)")
            else:
                mid_bearish.append(entry)
                log.info(f"{ticker} [MID] DAILY BEARISH cross ({candles_ago}d ago)")

    log.info(f"{skipped} coins skipped — no data")

    total = len(mega_large_bullish) + len(mega_large_bearish) + len(mid_bullish) + len(mid_bearish)
    if total == 0:
        log.info("No daily crosses found.")
        return

    # ── Send alert for Large/Mega cap (> $1B) ───────────────────────────────
    if mega_large_bullish or mega_large_bearish:
        lines = [
            "🏆 <b>DAILY EMA 12/21 — LARGE CAP SIGNAL</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🕐 {now_str}",
        ]

        if mega_large_bullish:
            lines.append("\n📈 <b>BULLISH CROSSES — Large/Mega Cap</b>")
            for e in mega_large_bullish:
                days_str   = "today" if e["days_ago"] == 1 else f"{e['days_ago']}d ago"
                change_str = f"{e['change_24h']:+.2f}%" if e["change_24h"] is not None else "N/A"
                vol_str    = fmt_vol(e["vol_24h"]) if e["vol_24h"] else "N/A"
                mcap_str   = fmt_mcap(e["mcap"])
                vol_surge  = f" 🔥 Vol x{e['vol_ratio']:.1f}" if e["vol_ratio"] > 1.5 else ""
                lines.append(
                    f"\n<b>{e['ticker']}</b> [{e['tier']}]{vol_surge}\n"
                    f"💰 Price: {fmt_price(e['price'])}\n"
                    f"📊 24h Change: {change_str}\n"
                    f"💎 Market Cap: {mcap_str}\n"
                    f"📦 24h Volume: {vol_str}\n"
                    f"📅 Cross: {days_str}\n"
                    f"📉 EMA12: {fmt_price(e['ema12'])} | EMA21: {fmt_price(e['ema21'])}\n"
                    f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>📈 Chart</a>"
                )

        if mega_large_bearish:
            lines.append("\n📉 <b>BEARISH CROSSES — Large/Mega Cap</b>")
            for e in mega_large_bearish:
                days_str   = "today" if e["days_ago"] == 1 else f"{e['days_ago']}d ago"
                change_str = f"{e['change_24h']:+.2f}%" if e["change_24h"] is not None else "N/A"
                vol_str    = fmt_vol(e["vol_24h"]) if e["vol_24h"] else "N/A"
                mcap_str   = fmt_mcap(e["mcap"])
                vol_surge  = f" 🔥 Vol x{e['vol_ratio']:.1f}" if e["vol_ratio"] > 1.5 else ""
                lines.append(
                    f"\n<b>{e['ticker']}</b> [{e['tier']}]{vol_surge}\n"
                    f"💰 Price: {fmt_price(e['price'])}\n"
                    f"📊 24h Change: {change_str}\n"
                    f"💎 Market Cap: {mcap_str}\n"
                    f"📦 24h Volume: {vol_str}\n"
                    f"📅 Cross: {days_str}\n"
                    f"📉 EMA12: {fmt_price(e['ema12'])} | EMA21: {fmt_price(e['ema21'])}\n"
                    f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>📈 Chart</a>"
                )

        send_alert("\n".join(lines))

    # ── Send alert for Mid cap ($200M–$1B) ──────────────────────────────────
    if mid_bullish or mid_bearish:
        lines = [
            "📡 <b>DAILY EMA 12/21 — MID CAP SIGNAL</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🕐 {now_str}",
            "⚠️ <i>Mid cap $200M–$1B — higher risk, verify before entry</i>",
        ]

        if mid_bullish:
            lines.append("\n📈 <b>BULLISH CROSSES — Mid Cap</b>")
            for e in mid_bullish:
                days_str   = "today" if e["days_ago"] == 1 else f"{e['days_ago']}d ago"
                change_str = f"{e['change_24h']:+.2f}%" if e["change_24h"] is not None else "N/A"
                vol_str    = fmt_vol(e["vol_24h"]) if e["vol_24h"] else "N/A"
                mcap_str   = fmt_mcap(e["mcap"])
                lines.append(
                    f"\n<b>{e['ticker']}</b> [MID]\n"
                    f"💰 Price: {fmt_price(e['price'])}\n"
                    f"📊 24h Change: {change_str}\n"
                    f"💎 Market Cap: {mcap_str}\n"
                    f"📦 24h Volume: {vol_str}\n"
                    f"📅 Cross: {days_str}\n"
                    f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>📈 Chart</a>"
                )

        if mid_bearish:
            lines.append("\n📉 <b>BEARISH CROSSES — Mid Cap</b>")
            for e in mid_bearish:
                days_str   = "today" if e["days_ago"] == 1 else f"{e['days_ago']}d ago"
                change_str = f"{e['change_24h']:+.2f}%" if e["change_24h"] is not None else "N/A"
                vol_str    = fmt_vol(e["vol_24h"]) if e["vol_24h"] else "N/A"
                mcap_str   = fmt_mcap(e["mcap"])
                lines.append(
                    f"\n<b>{e['ticker']}</b> [MID]\n"
                    f"💰 Price: {fmt_price(e['price'])}\n"
                    f"📊 24h Change: {change_str}\n"
                    f"💎 Market Cap: {mcap_str}\n"
                    f"📦 24h Volume: {vol_str}\n"
                    f"📅 Cross: {days_str}\n"
                    f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>📈 Chart</a>"
                )

        send_alert("\n".join(lines))

    log.info("Daily scan complete.")


def wait_until_daily_close():
    """Wait until 00:05 UTC (5 min after daily candle close)."""
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(days=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M UTC')} — sleeping {sleep_secs/3600:.1f}h")
    time.sleep(sleep_secs)


if __name__ == "__main__":
    log.info("Daily EMA 12/21 Cross Scanner started.")
    send_alert("✅ <b>Daily EMA Scanner Online</b>\nScanning daily candles every day at 00:05 UTC.")
    while True:
        wait_until_daily_close()
        run_scan()