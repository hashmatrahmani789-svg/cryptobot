import os
import time
import json
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MEME-BOT] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# ── Alert thresholds ─────────────────────────────────────────────────────────
MIN_LIQUIDITY_USD   = 100_000    # $100K minimum liquidity
MIN_VOLUME_1H_USD   = 150_000    # $150K minimum 1h volume
VOLUME_SPIKE_MULT   = 5.0        # 5x above average
MIN_PRICE_CHANGE_1H = 20.0       # 20% price increase in 1h
MIN_AGE_HOURS       = 2          # ignore brand new coins under 2h
MIN_TXNS_1H         = 50         # minimum transactions in 1h (filter bots)

# ── Chains to monitor ────────────────────────────────────────────────────────
CHAINS = ["solana", "ethereum", "base"]

# ── Signal memory ────────────────────────────────────────────────────────────
SIGNAL_MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_memory_meme.json")


def load_memory():
    if os.path.exists(SIGNAL_MEMORY_FILE):
        try:
            with open(SIGNAL_MEMORY_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_memory(memory):
    try:
        with open(SIGNAL_MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        log.error(f"Memory save error: {e}")


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


def get_trending_tokens(chain):
    """Get trending tokens from DexScreener for a chain."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/token-profiles/latest/v1",
            timeout=15
        )
        data = r.json()
        if isinstance(data, list):
            return [t for t in data if t.get("chainId", "").lower() == chain.lower()]
        return []
    except Exception as e:
        log.error(f"DexScreener trending error ({chain}): {e}")
        return []


def get_boosted_tokens():
    """Get boosted/promoted tokens from DexScreener — these often pump."""
    try:
        r = requests.get(
            "https://api.dexscreener.com/token-boosts/top/v1",
            timeout=15
        )
        data = r.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        log.error(f"DexScreener boosted error: {e}")
        return []


def get_token_pairs(chain, token_address):
    """Get pair data for a token."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
            timeout=15
        )
        data = r.json()
        pairs = data.get("pairs", [])
        # Filter by chain and sort by liquidity
        chain_pairs = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
        chain_pairs.sort(key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)
        return chain_pairs[0] if chain_pairs else None
    except Exception as e:
        log.error(f"DexScreener pair error ({token_address}): {e}")
        return None


def search_pairs(chain):
    """Search for active pairs on a chain sorted by volume."""
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/search?q=pump",
            timeout=15
        )
        data = r.json()
        pairs = data.get("pairs", [])
        return [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
    except:
        return []


def fmt_price(p):
    if p is None:
        return "N/A"
    p = float(p)
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    if p >= 0.0001:
        return f"${p:.6f}"
    return f"${p:.10f}"


def fmt_usd(v):
    if v is None:
        return "N/A"
    v = float(v)
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:.0f}"


def get_chain_emoji(chain):
    emojis = {
        "solana": "◎",
        "ethereum": "Ξ",
        "base": "🔵"
    }
    return emojis.get(chain.lower(), "🔗")


def analyze_pair(pair, memory):
    """Check if a pair meets all alert criteria."""
    try:
        chain        = pair.get("chainId", "").lower()
        token        = pair.get("baseToken", {})
        symbol       = token.get("symbol", "???")
        name         = token.get("name", "???")
        address      = token.get("address", "")
        dex          = pair.get("dexId", "")
        pair_address = pair.get("pairAddress", "")

        # Price data
        price_usd    = float(pair.get("priceUsd") or 0)
        price_change = pair.get("priceChange", {})
        change_1h    = float(price_change.get("h1") or 0)
        change_24h   = float(price_change.get("h24") or 0)

        # Volume
        volume       = pair.get("volume", {})
        vol_1h       = float(volume.get("h1") or 0)
        vol_6h       = float(volume.get("h6") or 0)
        vol_24h      = float(volume.get("h24") or 0)

        # Liquidity
        liquidity    = pair.get("liquidity", {})
        liq_usd      = float(liquidity.get("usd") or 0)

        # Transactions
        txns         = pair.get("txns", {})
        txns_1h      = txns.get("h1", {})
        buys_1h      = int(txns_1h.get("buys") or 0)
        sells_1h     = int(txns_1h.get("sells") or 0)
        total_txns_1h = buys_1h + sells_1h

        # Market cap
        mcap         = float(pair.get("marketCap") or pair.get("fdv") or 0)

        # Token age
        created_at   = pair.get("pairCreatedAt")
        age_hours    = 999
        if created_at:
            age_hours = (datetime.now(timezone.utc).timestamp() - created_at / 1000) / 3600

        # Volume spike — compare 1h vs average hourly from 24h
        avg_hourly_vol = vol_24h / 24 if vol_24h > 0 else 0
        vol_spike      = vol_1h / avg_hourly_vol if avg_hourly_vol > 0 else 0

        # ── Apply filters ────────────────────────────────────────────────────
        if liq_usd < MIN_LIQUIDITY_USD:
            return None
        if vol_1h < MIN_VOLUME_1H_USD:
            return None
        if change_1h < MIN_PRICE_CHANGE_1H:
            return None
        if age_hours < MIN_AGE_HOURS:
            return None
        if total_txns_1h < MIN_TXNS_1H:
            return None
        if vol_spike < VOLUME_SPIKE_MULT:
            return None

        # ── Signal memory — don't repeat ────────────────────────────────────
        mem_key = f"{chain}_{address}"
        last_alert = memory.get(mem_key, 0)
        now_ts = datetime.now(timezone.utc).timestamp()

        # Only re-alert if 6 hours have passed (price may have pumped further)
        if now_ts - last_alert < 21600:
            return None

        # Buy pressure
        buy_ratio = buys_1h / total_txns_1h * 100 if total_txns_1h > 0 else 0

        return {
            "chain":       chain,
            "symbol":      symbol,
            "name":        name,
            "address":     address,
            "pair_address": pair_address,
            "dex":         dex,
            "price":       price_usd,
            "change_1h":   change_1h,
            "change_24h":  change_24h,
            "vol_1h":      vol_1h,
            "vol_24h":     vol_24h,
            "liq_usd":     liq_usd,
            "mcap":        mcap,
            "vol_spike":   vol_spike,
            "buys_1h":     buys_1h,
            "sells_1h":    sells_1h,
            "buy_ratio":   buy_ratio,
            "age_hours":   age_hours,
            "mem_key":     mem_key,
        }

    except Exception as e:
        log.error(f"Pair analysis error: {e}")
        return None


def build_alert(e):
    chain_emoji = get_chain_emoji(e["chain"])
    chain_name  = e["chain"].capitalize()
    age_str     = f"{e['age_hours']:.0f}h old" if e["age_hours"] < 48 else f"{e['age_hours']/24:.0f}d old"
    spike_str   = f"{e['vol_spike']:.1f}x" if e["vol_spike"] < 100 else "100x+"
    dex_link    = f"https://dexscreener.com/{e['chain']}/{e['pair_address']}"

    return (
        f"🚀 <b>MEME COIN ALERT</b> {chain_emoji} {chain_name}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"<b>{e['symbol']}</b> — {e['name']}\n"
        f"💰 Price: {fmt_price(e['price'])}\n"
        f"📈 1h Change: +{e['change_1h']:.1f}%\n"
        f"📊 24h Change: {e['change_24h']:+.1f}%\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💧 Liquidity: {fmt_usd(e['liq_usd'])}\n"
        f"📦 Vol 1h: {fmt_usd(e['vol_1h'])} 🔥 {spike_str} spike\n"
        f"📦 Vol 24h: {fmt_usd(e['vol_24h'])}\n"
        f"💎 MCap: {fmt_usd(e['mcap'])}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🟢 Buys: {e['buys_1h']} | 🔴 Sells: {e['sells_1h']} ({e['buy_ratio']:.0f}% buys)\n"
        f"⏱ Age: {age_str} | DEX: {e['dex']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>DYOR — verify contract before entry</i>\n"
        f"<a href='{dex_link}'>📈 DexScreener</a>"
    )


def scan_chain(chain, memory):
    log.info(f"Scanning {chain}...")
    alerts = []

    try:
        # Search for active pairs on this chain
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/search?q={chain}",
            timeout=15
        )
        data = r.json()
        pairs = [p for p in data.get("pairs", []) if p.get("chainId", "").lower() == chain.lower()]

        # Also get top gainers by searching common meme terms
        for term in ["pepe", "doge", "cat", "inu", "moon", "sol", "based"]:
            try:
                r2 = requests.get(
                    f"https://api.dexscreener.com/latest/dex/search?q={term}",
                    timeout=10
                )
                extra = [p for p in r2.json().get("pairs", []) if p.get("chainId", "").lower() == chain.lower()]
                pairs.extend(extra)
                time.sleep(0.2)
            except:
                pass

        # Deduplicate by pair address
        seen = set()
        unique_pairs = []
        for p in pairs:
            pa = p.get("pairAddress", "")
            if pa and pa not in seen:
                seen.add(pa)
                unique_pairs.append(p)

        log.info(f"{chain}: {len(unique_pairs)} pairs to analyze")

        for pair in unique_pairs:
            result = analyze_pair(pair, memory)
            if result:
                alerts.append(result)

    except Exception as e:
        log.error(f"Scan error ({chain}): {e}")

    return alerts


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Meme coin scan started... {now_str}")

    memory = load_memory()
    all_alerts = []

    for chain in CHAINS:
        alerts = scan_chain(chain, memory)
        all_alerts.extend(alerts)
        time.sleep(1)

    if not all_alerts:
        log.info("No meme coin signals found.")
        return

    # Sort by volume spike (biggest spike first)
    all_alerts.sort(key=lambda x: x["vol_spike"], reverse=True)

    # Send alerts and update memory
    now_ts = datetime.now(timezone.utc).timestamp()
    for e in all_alerts:
        msg = build_alert(e)
        send_alert(msg)
        memory[e["mem_key"]] = now_ts
        time.sleep(1)

    save_memory(memory)
    log.info(f"Scan complete. {len(all_alerts)} alerts sent.")


if __name__ == "__main__":
    log.info("Meme Coin Bot started.")
    send_alert("✅ <b>Meme Coin Bot Online</b>\nMonitoring Solana, Ethereum, Base\nAlerts: $150K+ volume, 5x spike, 20%+ price move, $100K+ liquidity")

    while True:
        run_scan()
        log.info("Sleeping 15 minutes...")
        time.sleep(900)  # scan every 15 minutes