import json
import logging
import os
import time
import requests
from datetime import datetime, timezone

log = logging.getLogger(__name__)

CACHE_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coins_cache.json")
MIN_MCAP      = 500_000_000
CACHE_TTL     = 86400  # 24 hours

STABLECOINS = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP",
    "GUSD", "FRAX", "LUSD", "USDD", "FDUSD", "PYUSD"
}


def _fmt_mcap(mcap):
    if mcap >= 1_000_000_000_000:
        return f"${mcap/1_000_000_000_000:.2f}T"
    if mcap >= 1_000_000_000:
        return f"${mcap/1_000_000_000:.1f}B"
    return f"${mcap/1_000_000:.0f}M"


def _fetch_coinbase_symbols():
    """Return set of all symbols available as SYMBOL-USD on Coinbase."""
    try:
        r = requests.get(
            "https://api.coinbase.com/api/v3/brokerage/market/products",
            params={"product_type": "SPOT"},
            timeout=15
        )
        symbols = set()
        for p in r.json().get("products", []):
            pid = p.get("product_id", "")
            if pid.endswith("-USD"):
                symbols.add(pid.replace("-USD", ""))
        log.info(f"[coins] {len(symbols)} symbols available on Coinbase")
        return symbols
    except Exception as e:
        log.error(f"[coins] Coinbase fetch error: {e}")
        return set()


def _fetch_from_coingecko(coinbase_symbols):
    """Fetch top coins from CoinGecko filtered by mcap and Coinbase availability."""
    coins = []
    try:
        data = None
        for attempt in range(3):
            try:
                r = requests.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "order":       "market_cap_desc",
                        "per_page":    250,
                        "page":        1,
                        "sparkline":   False
                    },
                    timeout=15
                )
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    break
                log.warning(f"[coins] CoinGecko attempt {attempt+1} returned invalid data, retrying in 5s...")
                time.sleep(5)
            except Exception as e:
                log.warning(f"[coins] CoinGecko attempt {attempt+1} failed: {e}, retrying in 5s...")
                time.sleep(5)

        if not isinstance(data, list) or len(data) == 0:
            log.error("[coins] CoinGecko returned no data after 3 attempts")
            return coins

        for coin in data:
            symbol = coin.get("symbol", "").upper()
            mcap   = coin.get("market_cap") or 0
            if mcap < MIN_MCAP:
                break
            if symbol in STABLECOINS:
                continue
            if symbol not in coinbase_symbols:
                continue
            coins.append((symbol, _fmt_mcap(mcap)))
        log.info(f"[coins] {len(coins)} coins loaded ($500M+, on Coinbase)")
    except Exception as e:
        log.error(f"[coins] CoinGecko fetch error: {e}")
    return coins


def get_coins():
    """
    Return list of (symbol, mcap_str) tuples.
    Uses a 24h file cache — only 1 CoinGecko call per day across all bots.
    """
    # Check cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
            age = datetime.now(timezone.utc).timestamp() - cache["timestamp"]
            if age < CACHE_TTL:
                coins = [tuple(c) for c in cache["coins"]]
                log.info(f"[coins] Loaded {len(coins)} coins from cache ({age/3600:.1f}h old)")
                return coins
        except Exception:
            pass

    # Fetch fresh
    log.info("[coins] Cache expired or missing — fetching fresh coin list...")
    coinbase_symbols = _fetch_coinbase_symbols()
    coins = _fetch_from_coingecko(coinbase_symbols)

    if not coins:
        # If fetch failed and cache exists, use stale cache as fallback
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE) as f:
                    cache = json.load(f)
                coins = [tuple(c) for c in cache["coins"]]
                log.warning(f"[coins] Using stale cache ({len(coins)} coins) — fetch failed")
                return coins
            except Exception:
                pass
        log.error("[coins] No coin data available!")
        return []

    # Save cache
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "coins":     coins
            }, f)
        log.info(f"[coins] Cache saved — {len(coins)} coins")
    except Exception as e:
        log.error(f"[coins] Cache save error: {e}")

    return coins