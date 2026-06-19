"""
Liquidation Alert Bot
=====================
Scans all coins on Coinglass for large liquidation cascades.
Alerts when long or short liquidations exceed $5M in the last hour.

Tiers:
  🟡 Major    : $5M–$15M
  🟠 Massive  : $15M–$50M
  🔴 Extreme  : $50M+

Includes:
  • Long vs short breakdown
  • Dominant side (who got wiped)
  • 4h context (how big vs recent history)
  • 4-hour cooldown per coin to suppress repeats

Env vars required:
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
  COINGLASS_API_KEY
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LIQ_BOT] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "").strip()

PACIFIC = ZoneInfo("America/Los_Angeles")

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_LIQ_USD    = 5_000_000    # $5M minimum to trigger
COOLDOWN_HOURS = 4            # Suppress repeat alerts per coin

MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "signal_memory_liq.json"
)

BASE_URL = "https://open-api-v3.coinglass.com"
HEADERS  = {
    "accept":          "application/json",
    "coinglassSecret": COINGLASS_API_KEY,
}


# ─────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_memory(memory):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        log.error(f"Memory save error: {e}")


def is_new_signal(memory, key):
    entry = memory.get(key)
    if entry is None:
        return True
    elapsed_h = (datetime.now(timezone.utc).timestamp() - entry.get("ts", 0)) / 3600
    return elapsed_h >= COOLDOWN_HOURS


def update_memory(memory, key):
    memory[key] = {"ts": datetime.now(timezone.utc).timestamp()}


# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────

def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     message,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if r.status_code == 200:
            log.info("Alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


# ─────────────────────────────────────────
# COINGLASS API
# ─────────────────────────────────────────

def get_liquidation_list():
    """Fetch liquidation data for all coins (1h window)."""
    try:
        r = requests.get(
            f"{BASE_URL}/api/futures/liquidation/coin/list",
            headers=HEADERS,
            timeout=15,
        )
        data = r.json()
        if data.get("code") != "0":
            log.error(f"API error: {data.get('msg')}")
            return []
        return data.get("data", [])
    except Exception as e:
        log.error(f"Liquidation API error: {e}")
        return []


# ─────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────

def fmt_usd(v):
    if v >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:     return f"${v/1_000_000:.1f}M"
    if v >= 1_000:         return f"${v/1_000:.1f}K"
    return f"${v:.0f}"


def get_tier(total_usd):
    if total_usd >= 50_000_000:  return "EXTREME",  "🔴"
    if total_usd >= 15_000_000:  return "MASSIVE",   "🟠"
    return "MAJOR", "🟡"


def now_pacific():
    return datetime.now(PACIFIC).strftime("%a %b %d, %I:%M %p %Z")


# ─────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────

def run_scan():
    log.info("Scanning liquidations...")
    coins  = get_liquidation_list()
    memory = load_memory()

    if not coins:
        log.info("No liquidation data returned.")
        return

    triggered = 0

    for coin in coins:
        symbol = coin.get("symbol", "")
        if not symbol:
            continue

        # 1h liquidation values
        long_1h  = float(coin.get("longLiquidationUsd1h",  0) or 0)
        short_1h = float(coin.get("shortLiquidationUsd1h", 0) or 0)
        total_1h = long_1h + short_1h

        if total_1h < MIN_LIQ_USD:
            continue

        # 4h context
        long_4h  = float(coin.get("longLiquidationUsd4h",  0) or 0)
        short_4h = float(coin.get("shortLiquidationUsd4h", 0) or 0)
        total_4h = long_4h + short_4h

        # Dominant side
        dominant = "LONGS" if long_1h >= short_1h else "SHORTS"
        dom_emoji = "🟢 Longs" if dominant == "LONGS" else "🔴 Shorts"
        dom_pct   = round((long_1h / total_1h * 100) if dominant == "LONGS" else (short_1h / total_1h * 100), 1)

        tier_name, tier_emoji = get_tier(total_1h)
        sig_key = f"{symbol}_liq"

        if not is_new_signal(memory, sig_key):
            log.debug(f"{symbol} suppressed (cooldown)")
            continue

        update_memory(memory, sig_key)
        triggered += 1

        msg = (
            f"{tier_emoji} <b>LIQUIDATION CASCADE — {tier_name}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💥 <b>{symbol}</b>\n"
            f"🕐 {now_pacific()}\n\n"
            f"📊 <b>Last 1H Total:</b> {fmt_usd(total_1h)}\n"
            f"  🟢 Longs wiped: {fmt_usd(long_1h)}\n"
            f"  🔴 Shorts wiped: {fmt_usd(short_1h)}\n\n"
            f"👊 <b>Dominant:</b> {dom_emoji} ({dom_pct}%)\n"
            f"📈 4H Context: {fmt_usd(total_4h)} total\n\n"
            f"<i>{'⬇️ Longs wiped = price dropped hard' if dominant == 'LONGS' else '⬆️ Shorts wiped = price squeezed up'}</i>\n"
            f"<a href='https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT'>📈 Chart</a>"
        )

        send_alert(msg)
        log.info(f"{symbol} {tier_name} liq — {fmt_usd(total_1h)}")

    save_memory(memory)
    log.info(f"Scan complete. {triggered} alerts fired.")


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    log.info("Liquidation Bot started.")
    send_alert(
        "💥 <b>Liquidation Alert Bot Online</b>\n"
        "Scanning every 15 minutes\n\n"
        "🔴 Extreme  — $50M+\n"
        "🟠 Massive  — $15M–$50M\n"
        "🟡 Major    — $5M–$15M\n\n"
        "4-hour cooldown per coin"
    )
    run_scan()
    while True:
        time.sleep(900)   # every 15 minutes
        run_scan()