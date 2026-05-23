"""
Crypto OI / Price Harmony & Divergence Alert Bot
─────────────────────────────────────────────────
- Exchanges    : Binance + Bybit (OI & price, no API key needed)
- Market cap   : only coins with market cap > $1 B  (via CoinGecko free API)
- Notifications: Telegram
- Check every  : 15 minutes

Signal logic (per coin, compared to previous snapshot):
  HARMONY    → Price UP   + OI UP    (longs building, trend confirmed)
  HARMONY    → Price DOWN + OI DOWN  (longs closing, trend confirmed)
  DIVERGENCE → Price UP   + OI DOWN  (shorts closing / no conviction = possible reversal)
  DIVERGENCE → Price DOWN + OI UP    (shorts building against price = bearish pressure)
"""

import time
import logging
import requests
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"   # from @BotFather
TELEGRAM_CHAT_ID   = "8118939134"     # your personal or group chat ID

CHECK_INTERVAL_SEC  = 15 * 60               # 15 minutes
MARKET_CAP_MIN_USD  = 1_000_000_000         # $1 B filter
CHANGE_THRESHOLD_PCT = 0.5                  # minimum % change to count as a move (noise filter)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Telegram send failed: %s", e)

# ── CoinGecko — market cap filter ────────────────────────────────────────────

def get_large_cap_symbols() -> set[str]:
    """
    Return a set of base symbols (e.g. {'BTC','ETH','SOL',...})
    whose market cap exceeds MARKET_CAP_MIN_USD.
    Uses CoinGecko free public API (no key needed).
    """
    symbols = set()
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
                    "sparkline": "false",
                },
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("CoinGecko page %d failed: %s", page, e)
            break

        if not data:
            break

        for coin in data:
            mcap = coin.get("market_cap") or 0
            if mcap < MARKET_CAP_MIN_USD:
                break   # list is sorted desc, so we can stop early
            sym = coin.get("symbol", "").upper()
            if sym:
                symbols.add(sym)

        # if the last item is still above threshold, fetch next page
        if data and (data[-1].get("market_cap") or 0) >= MARKET_CAP_MIN_USD:
            page += 1
            time.sleep(1)   # be polite to free API
        else:
            break

    log.info("Large-cap symbols from CoinGecko: %d coins", len(symbols))
    return symbols


# ── Binance ───────────────────────────────────────────────────────────────────

def binance_get_futures_symbols() -> list[str]:
    """All active USDT-margined perpetual symbols on Binance."""
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=15
        )
        r.raise_for_status()
        symbols = [
            s["symbol"]
            for s in r.json()["symbols"]
            if s["contractType"] == "PERPETUAL"
            and s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
        ]
        return symbols
    except Exception as e:
        log.warning("Binance exchange info failed: %s", e)
        return []


def binance_get_oi(symbol: str) -> float | None:
    """Open interest in USD for a Binance USDT-perp."""
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        return float(d["openInterestValue"])   # already in USDT notional
    except Exception:
        return None


def binance_get_price(symbol: str) -> float | None:
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/price",
            params={"symbol": symbol},
            timeout=10,
        )
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None


# ── Bybit ─────────────────────────────────────────────────────────────────────

def bybit_get_futures_symbols() -> list[str]:
    """All active linear USDT perpetual symbols on Bybit."""
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/instruments-info",
            params={"category": "linear", "limit": 1000},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json()["result"]["list"]
        return [
            i["symbol"]
            for i in items
            if i.get("quoteCoin") == "USDT"
            and i.get("contractType") == "LinearPerpetual"
            and i.get("status") == "Trading"
        ]
    except Exception as e:
        log.warning("Bybit instruments failed: %s", e)
        return []


def bybit_get_oi(symbol: str) -> float | None:
    """Open interest in USD for a Bybit linear perp."""
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/open-interest",
            params={"category": "linear", "symbol": symbol, "intervalTime": "5min", "limit": 1},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()["result"]["list"]
        if not data:
            return None
        return float(data[0]["openInterestValue"])
    except Exception:
        return None


def bybit_get_price(symbol: str) -> float | None:
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json()["result"]["list"]
        if not items:
            return None
        return float(items[0]["lastPrice"])
    except Exception:
        return None


# ── Combined snapshot ─────────────────────────────────────────────────────────

def extract_base(symbol: str) -> str:
    """BTCUSDT → BTC, ETHUSDT → ETH."""
    for quote in ("USDT", "USD", "BUSD"):
        if symbol.endswith(quote):
            return symbol[: -len(quote)]
    return symbol


def build_snapshot(large_cap: set[str]) -> dict[str, dict]:
    """
    Returns {base_symbol: {price, oi}} aggregated from Binance + Bybit.
    Only includes coins in large_cap set.
    """
    snapshot: dict[str, dict] = {}

    # ── Binance ───────────────────────────────────────────────────────────────
    log.info("Fetching Binance data…")
    for sym in binance_get_futures_symbols():
        base = extract_base(sym)
        if base not in large_cap:
            continue
        price = binance_get_price(sym)
        oi    = binance_get_oi(sym)
        if price and oi:
            if base not in snapshot:
                snapshot[base] = {"price": price, "oi": 0.0, "sources": []}
            snapshot[base]["oi"] += oi
            snapshot[base]["sources"].append("Binance")
        time.sleep(0.05)   # gentle rate limiting

    # ── Bybit ─────────────────────────────────────────────────────────────────
    log.info("Fetching Bybit data…")
    for sym in bybit_get_futures_symbols():
        base = extract_base(sym)
        if base not in large_cap:
            continue
        price = bybit_get_price(sym)
        oi    = bybit_get_oi(sym)
        if price and oi:
            if base not in snapshot:
                snapshot[base] = {"price": price, "oi": 0.0, "sources": []}
            else:
                # average the price across exchanges
                snapshot[base]["price"] = (snapshot[base]["price"] + price) / 2
            snapshot[base]["oi"] += oi
            snapshot[base]["sources"].append("Bybit")
        time.sleep(0.05)

    log.info("Snapshot ready: %d coins", len(snapshot))
    return snapshot


# ── Signal detection ──────────────────────────────────────────────────────────

def pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100


def detect_signals(prev: dict, curr: dict) -> list[dict]:
    signals = []
    for base, now in curr.items():
        if base not in prev:
            continue
        before = prev[base]

        dp = pct_change(before["price"], now["price"])
        doi = pct_change(before["oi"],   now["oi"])

        # ignore noise
        if abs(dp) < CHANGE_THRESHOLD_PCT and abs(doi) < CHANGE_THRESHOLD_PCT:
            continue

        price_up = dp > 0
        oi_up    = doi > 0

        if price_up == oi_up:
            signal_type = "HARMONY"
            if price_up:
                emoji = "✅"
                desc  = "Price ↑ & OI ↑ — bullish conviction, trend confirmed"
            else:
                emoji = "✅"
                desc  = "Price ↓ & OI ↓ — longs closing, trend confirmed"
        else:
            signal_type = "DIVERGENCE"
            if price_up and not oi_up:
                emoji = "⚠️"
                desc  = "Price ↑ but OI ↓ — shorts closing, weak conviction, possible reversal"
            else:
                emoji = "🚨"
                desc  = "Price ↓ but OI ↑ — shorts building, bearish pressure"

        signals.append({
            "base":   base,
            "type":   signal_type,
            "emoji":  emoji,
            "desc":   desc,
            "dp":     dp,
            "doi":    doi,
            "price":  now["price"],
            "oi":     now["oi"],
        })

    return signals


def format_message(signals: list[dict]) -> str:
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    harmony    = [s for s in signals if s["type"] == "HARMONY"]
    divergence = [s for s in signals if s["type"] == "DIVERGENCE"]

    lines = [f"📊 *OI/Price Signal Report* — {now_str}\n"]

    if divergence:
        lines.append("─── 🚨 DIVERGENCES ───")
        for s in sorted(divergence, key=lambda x: abs(x["dp"]), reverse=True):
            lines.append(
                f"{s['emoji']} *{s['base']}*\n"
                f"   Price: ${s['price']:,.4f}  ({s['dp']:+.2f}%)\n"
                f"   OI:    ${s['oi']/1e6:,.1f}M  ({s['doi']:+.2f}%)\n"
                f"   _{s['desc']}_"
            )

    if harmony:
        lines.append("\n─── ✅ HARMONIES ───")
        for s in sorted(harmony, key=lambda x: abs(x["dp"]), reverse=True):
            lines.append(
                f"{s['emoji']} *{s['base']}*\n"
                f"   Price: ${s['price']:,.4f}  ({s['dp']:+.2f}%)\n"
                f"   OI:    ${s['oi']/1e6:,.1f}M  ({s['doi']:+.2f}%)\n"
                f"   _{s['desc']}_"
            )

    if not harmony and not divergence:
        lines.append("No significant signals this cycle (all moves below threshold).")

    return "\n".join(lines)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Bot starting…")
    send_telegram("🤖 *Crypto OI/Price Alert Bot* started!\nMonitoring coins with market cap > $1B every 15 min.")

    prev_snapshot: dict = {}

    while True:
        try:
            log.info("=== New cycle ===")

            large_cap = get_large_cap_symbols()
            curr_snapshot = build_snapshot(large_cap)

            if prev_snapshot:
                signals = detect_signals(prev_snapshot, curr_snapshot)
                msg = format_message(signals)
                log.info("Sending report: %d signals", len(signals))
                send_telegram(msg)
            else:
                log.info("First run — collecting baseline snapshot, no signals yet.")
                send_telegram("📡 Baseline snapshot collected. Signals will appear next cycle.")

            prev_snapshot = curr_snapshot

        except Exception as e:
            log.exception("Unexpected error in main loop: %s", e)
            send_telegram(f"⚠️ Bot error: `{e}`")

        log.info("Sleeping %d seconds…", CHECK_INTERVAL_SEC)
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    main()