"""
Open Interest Spike Bot
=======================
Scans all major coins on Coinglass for Open Interest spikes.
Alerts when OI changes 10%+ within the last hour.

Tiers:
  📈 Notable  : 10–20% OI change
  ⚡ Strong   : 20–40% OI change
  🔥 Extreme  : 40%+ OI change

Includes:
  • OI direction (building or unwinding)
  • Price context (OI up + price up = bullish confirmation)
  • Signal interpretation
  • 4-hour cooldown per coin

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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OI_BOT] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "").strip()

PACIFIC = ZoneInfo("America/Los_Angeles")

# ── Thresholds ────────────────────────────────────────────────────────────────
OI_CHANGE_THRESH = 10.0       # Minimum % OI change to trigger
COOLDOWN_HOURS   = 4

MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "signal_memory_oi.json"
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


def is_new_signal(memory, key, direction):
    entry = memory.get(key)
    if entry is None:
        return True
    elapsed_h = (datetime.now(timezone.utc).timestamp() - entry.get("ts", 0)) / 3600
    if elapsed_h >= COOLDOWN_HOURS:
        return True
    return entry.get("direction") != direction   # fire if direction flipped


def update_memory(memory, key, direction):
    memory[key] = {
        "ts":        datetime.now(timezone.utc).timestamp(),
        "direction": direction,
    }


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

def get_oi_list():
    """Fetch current OI snapshot for all coins including % changes."""
    try:
        r = requests.get(
            f"{BASE_URL}/api/futures/openInterest/coin/list",
            headers=HEADERS,
            timeout=15,
        )
        data = r.json()
        log.info(f"OI API response code: {data.get('code')} | msg: {data.get('msg')}")
        if str(data.get("code")) != "0":   # FIX: API returns int 0, not string "0"
            log.error(f"API error: {data.get('msg')} | full response: {data}")
            return []
        return data.get("data", [])
    except Exception as e:
        log.error(f"OI API error: {e}")
        return []


# ─────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────

def fmt_usd(v):
    if v >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:     return f"${v/1_000_000:.1f}M"
    if v >= 1_000:         return f"${v/1_000:.1f}K"
    return f"${v:.0f}"


def fmt_price(p):
    if p >= 1000: return f"${p:,.2f}"
    if p >= 1:    return f"${p:.4f}"
    return f"${p:.6f}"


def get_tier(pct):
    if abs(pct) >= 40: return "EXTREME", "🔥"
    if abs(pct) >= 20: return "STRONG",  "⚡"
    return "NOTABLE", "📈"


def interpret(oi_pct, price_pct):
    """Plain-english interpretation of OI + price combo."""
    oi_up    = oi_pct > 0
    price_up = price_pct > 0

    if oi_up and price_up:
        return "🟢 <b>Bullish</b> — New money entering, price confirming uptrend"
    if oi_up and not price_up:
        return "🔴 <b>Bearish</b> — New money entering short side, price falling"
    if not oi_up and price_up:
        return "⚠️ <b>Short Squeeze</b> — OI dropping (shorts covering), price spiking up"
    return "⚠️ <b>Long Unwind</b> — OI dropping (longs exiting), price falling"


def now_pacific():
    return datetime.now(PACIFIC).strftime("%a %b %d, %I:%M %p %Z")


# ─────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────

def run_scan():
    log.info("Scanning open interest...")
    coins  = get_oi_list()
    memory = load_memory()

    if not coins:
        log.info("No OI data returned.")
        return

    triggered = 0

    for coin in coins:
        symbol = coin.get("symbol", "")
        if not symbol:
            continue

        oi_usd      = float(coin.get("openInterest",     0) or 0)
        oi_pct_1h   = float(coin.get("openInterestChangePercent1h",  0) or 0)
        oi_pct_4h   = float(coin.get("openInterestChangePercent4h",  0) or 0)
        price       = float(coin.get("price",            0) or 0)
        price_pct   = float(coin.get("priceChangePercent1h", 0) or 0)

        if abs(oi_pct_1h) < OI_CHANGE_THRESH:
            continue

        direction  = "UP" if oi_pct_1h > 0 else "DOWN"
        tier_name, tier_emoji = get_tier(oi_pct_1h)
        interp     = interpret(oi_pct_1h, price_pct)
        sig_key    = f"{symbol}_oi"

        if not is_new_signal(memory, sig_key, direction):
            log.debug(f"{symbol} OI suppressed (cooldown)")
            continue

        update_memory(memory, sig_key, direction)
        triggered += 1

        arrow = "📈" if oi_pct_1h > 0 else "📉"

        msg = (
            f"{tier_emoji} <b>OPEN INTEREST SPIKE — {tier_name}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💎 <b>{symbol}</b>\n"
            f"🕐 {now_pacific()}\n\n"
            f"{arrow} <b>OI Change (1H):</b> {oi_pct_1h:+.1f}%\n"
            f"📊 <b>OI Change (4H):</b> {oi_pct_4h:+.1f}%\n"
            f"💰 <b>Total OI:</b> {fmt_usd(oi_usd)}\n"
            f"💵 <b>Price:</b> {fmt_price(price)}  ({price_pct:+.2f}% 1H)\n\n"
            f"{interp}\n"
            f"<a href='https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}USDT'>📈 Chart</a>"
        )

        send_alert(msg)
        log.info(f"{symbol} OI {tier_name} — {oi_pct_1h:+.1f}% | Price {price_pct:+.2f}%")

    save_memory(memory)
    log.info(f"Scan complete. {triggered} alerts fired.")


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    log.info("OI Spike Bot started.")
    send_alert(
        "📊 <b>Open Interest Spike Bot Online</b>\n"
        "Scanning every 15 minutes\n\n"
        "🔥 Extreme  — OI 40%+ change\n"
        "⚡ Strong   — OI 20–40% change\n"
        "📈 Notable  — OI 10–20% change\n\n"
        "Includes price context + signal interpretation\n"
        "4-hour cooldown per coin"
    )
    run_scan()
    while True:
        time.sleep(900)   # every 15 minutes
        run_scan()