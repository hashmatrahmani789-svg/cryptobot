"""
Volume Spike Signal — Early Long / Short
=========================================
Scans all 500M+ market cap coins on Coinbase for real volume spikes.
Filters out fake pumps and fake dumps using CVD + close position.

Signal tiers (RVOL-based):
  ⚡ High spike    : RVOL 3–5×
  🔥 Extreme spike : RVOL 5×+

Rules — ALL must pass to fire:
  1. RVOL   ≥ 3.0×
  2. Z-Score ≥ 2.5
  3. Price moved ≥ 1% on the spike candle
  4. LONG  → close in top 60% of candle range + buyers > 55% CVD
  5. SHORT → close in bottom 40% of candle range + sellers > 55% CVD

Fake pump filter : volume spike + price up but sellers dominate → DROPPED
Fake dump filter : volume spike + price down but buyers dominate → DROPPED

Sends two separate Telegram messages (LONG / SHORT) for instant recognition.
4-hour cooldown per coin.

Env vars required:
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from coins import get_coins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VOL_SPIKE] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# ── Thresholds ─────────────────────────────────────────────────────────────────
VOL_WINDOW       = 50      # Candles used for baseline average
RVOL_THRESH      = 3.0     # Minimum RVOL to qualify
ZSCORE_THRESH    = 2.5     # Minimum Z-Score to qualify
MIN_PRICE_CHANGE = 1.0     # Minimum % candle move to qualify
CVD_THRESH       = 55.0    # Minimum buy% (long) or sell% (short) to confirm
CLOSE_POS_LONG   = 60.0    # Close must be in top X% of range for LONG
CLOSE_POS_SHORT  = 40.0    # Close must be in bottom X% of range for SHORT
COOLDOWN_HOURS   = 4       # Suppress repeat alerts per coin

SIGNAL_MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "signal_memory_vol_spike.json"
)

GRANULARITY_MAP = {"1h": "ONE_HOUR"}
LOOKBACK_LIMIT  = {"1h": 150}


# ─────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────

def load_memory():
    if os.path.exists(SIGNAL_MEMORY_FILE):
        try:
            with open(SIGNAL_MEMORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_memory(memory):
    try:
        with open(SIGNAL_MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        log.error(f"Memory save error: {e}")


def is_new_signal(memory, key, value):
    entry = memory.get(key)
    if entry is None:
        return True
    if isinstance(entry, str):
        return entry != value
    last_val  = entry.get("value")
    last_ts   = entry.get("ts", 0)
    elapsed_h = (datetime.now(timezone.utc).timestamp() - last_ts) / 3600
    if last_val != value:
        return True
    if elapsed_h >= COOLDOWN_HOURS:
        return True
    return False


def update_memory(memory, key, value):
    memory[key] = {
        "value": value,
        "ts":    datetime.now(timezone.utc).timestamp(),
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
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


# ─────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────

def get_candles(ticker, interval):
    granularity = GRANULARITY_MAP[interval]
    limit       = LOOKBACK_LIMIT[interval]
    product_id  = f"{ticker}-USD"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": granularity, "limit": limit},
            timeout=10,
        )
        data    = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < VOL_WINDOW + 2:
            return None
        candles = list(reversed(candles))[:-1]
        return [
            {
                "open":   float(c["open"]),
                "high":   float(c["high"]),
                "low":    float(c["low"]),
                "close":  float(c["close"]),
                "volume": float(c.get("volume", 0)),
            }
            for c in candles
        ]
    except Exception as e:
        log.debug(f"{ticker} candle error ({interval}): {e}")
        return None


# ─────────────────────────────────────────
# SIGNAL LOGIC
# ─────────────────────────────────────────

def calc_rvol_zscore(candles):
    volumes = [c["volume"] for c in candles]
    window  = volumes[-VOL_WINDOW - 1:-1]
    current = volumes[-1]
    avg     = sum(window) / len(window)
    std     = (sum((v - avg) ** 2 for v in window) / len(window)) ** 0.5
    rvol    = current / avg if avg > 0 else 0
    zscore  = (current - avg) / std if std > 0 else 0
    return round(rvol, 2), round(zscore, 2), round(avg, 2)


def calc_cvd(candle):
    high, low, close, volume = (
        candle["high"], candle["low"], candle["close"], candle["volume"]
    )
    rng = high - low
    if rng == 0:
        buy_vol = sell_vol = volume * 0.5
    else:
        buy_vol  = volume * ((close - low) / rng)
        sell_vol = volume - buy_vol
    buy_pct  = round(buy_vol  / volume * 100, 1) if volume > 0 else 50.0
    sell_pct = round(100 - buy_pct, 1)
    return buy_pct, sell_pct


def get_close_position(candle):
    rng = candle["high"] - candle["low"]
    if rng == 0:
        return 50.0
    return round((candle["close"] - candle["low"]) / rng * 100, 1)


def get_price_change_pct(candle):
    if candle["open"] == 0:
        return 0.0
    return round(abs(candle["close"] - candle["open"]) / candle["open"] * 100, 2)


def get_tier(rvol):
    if rvol >= 5.0:
        return "EXTREME"
    if rvol >= 3.0:
        return "HIGH"
    return "NONE"


def classify_signal(candle, buy_pct, sell_pct, close_pos, price_change):
    """
    Returns 'LONG', 'SHORT', or None (fake / no signal).

    LONG  = price up + closes top 60%+ + buyers > 55%
    SHORT = price down + closes bottom 40%- + sellers > 55%
    Anything else = fake pump/dump → dropped
    """
    is_up = candle["close"] >= candle["open"]

    if is_up:
        if close_pos >= CLOSE_POS_LONG and buy_pct >= CVD_THRESH:
            return "LONG"
        else:
            log.debug("Fake pump detected — dropped")
            return None
    else:
        if close_pos <= CLOSE_POS_SHORT and sell_pct >= CVD_THRESH:
            return "SHORT"
        else:
            log.debug("Fake dump detected — dropped")
            return None


# ─────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────

def fmt_price(p):
    if not p:
        return "N/A"
    if p >= 1000: return f"${p:,.2f}"
    if p >= 1:    return f"${p:.4f}"
    return f"${p:.6f}"


def fmt_vol(v):
    if v >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:     return f"${v/1_000_000:.1f}M"
    if v >= 1_000:         return f"${v/1_000:.1f}K"
    return f"{v:.2f}"


def fmt_long(e):
    tier_emoji = "🔥" if e["tier"] == "EXTREME" else "⚡"
    return (
        f"🟢 <b>{e['ticker']}</b> [{e['tier']}] — {e['mcap']}\n"
        f"💰 {fmt_price(e['close'])} | Move: +{e['price_change']}%\n"
        f"📊 Vol: {fmt_vol(e['volume'])} | RVOL: {tier_emoji}<b>{e['rvol']}×</b> | Z: <b>{e['zscore']}</b>\n"
        f"🎯 Close pos: top {100 - int(e['close_pos'])}% | Buyers: {e['buy_pct']}%\n"
        f"<a href='{e['tv_link']}'>📈 Chart</a>"
    )


def fmt_short(e):
    tier_emoji = "🔥" if e["tier"] == "EXTREME" else "⚡"
    return (
        f"🔴 <b>{e['ticker']}</b> [{e['tier']}] — {e['mcap']}\n"
        f"💸 {fmt_price(e['close'])} | Move: -{e['price_change']}%\n"
        f"📊 Vol: {fmt_vol(e['volume'])} | RVOL: {tier_emoji}<b>{e['rvol']}×</b> | Z: <b>{e['zscore']}</b>\n"
        f"🎯 Close pos: bottom {int(e['close_pos'])}% | Sellers: {e['sell_pct']}%\n"
        f"<a href='{e['tv_link']}'>📉 Chart</a>"
    )


# ─────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────

def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")

    coins = get_coins()
    if not coins:
        log.error("No coins fetched — aborting.")
        return

    memory  = load_memory()
    longs   = {"EXTREME": [], "HIGH": []}
    shorts  = {"EXTREME": [], "HIGH": []}
    skipped = 0
    dropped = 0

    for ticker, mcap in coins:
        candles = get_candles(ticker, "1h")
        if not candles:
            skipped += 1
            time.sleep(0.2)
            continue

        rvol, zscore, avg_vol = calc_rvol_zscore(candles)

        if rvol < RVOL_THRESH or zscore < ZSCORE_THRESH:
            time.sleep(0.2)
            continue

        tier = get_tier(rvol)
        if tier == "NONE":
            time.sleep(0.2)
            continue

        last         = candles[-1]
        price_change = get_price_change_pct(last)
        buy_pct, sell_pct = calc_cvd(last)
        close_pos    = get_close_position(last)

        # Filter: price must have actually moved
        if price_change < MIN_PRICE_CHANGE:
            log.debug(f"{ticker} dropped — price change {price_change}% < {MIN_PRICE_CHANGE}%")
            dropped += 1
            time.sleep(0.2)
            continue

        # Classify: LONG, SHORT, or fake → None
        direction = classify_signal(last, buy_pct, sell_pct, close_pos, price_change)
        if direction is None:
            log.info(f"{ticker} — fake pump/dump detected, dropped")
            dropped += 1
            time.sleep(0.2)
            continue

        sig_key = f"{ticker}_1h_spike"
        sig_val = f"{tier}_{direction}"

        if not is_new_signal(memory, sig_key, sig_val):
            log.debug(f"{ticker} suppressed (cooldown)")
            time.sleep(0.2)
            continue

        update_memory(memory, sig_key, sig_val)

        entry = {
            "ticker":       ticker,
            "mcap":         mcap,
            "tier":         tier,
            "direction":    direction,
            "close":        last["close"],
            "volume":       last["volume"],
            "avg_vol":      avg_vol,
            "rvol":         rvol,
            "zscore":       zscore,
            "buy_pct":      buy_pct,
            "sell_pct":     sell_pct,
            "close_pos":    close_pos,
            "price_change": price_change,
            "tv_link":      f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD"
        }

        if direction == "LONG":
            longs[tier].append(entry)
            log.info(f"{ticker} LONG {tier} — RVOL {rvol}× Z {zscore} | Close top {100-int(close_pos)}% | Buy {buy_pct}%")
        else:
            shorts[tier].append(entry)
            log.info(f"{ticker} SHORT {tier} — RVOL {rvol}× Z {zscore} | Close bot {int(close_pos)}% | Sell {sell_pct}%")

        time.sleep(0.2)

    save_memory(memory)
    log.info(f"{skipped} skipped (no data) | {dropped} dropped (fake/no move)")

    total_longs  = sum(len(v) for v in longs.values())
    total_shorts = sum(len(v) for v in shorts.values())

    if total_longs == 0 and total_shorts == 0:
        log.info("No real volume spikes found.")
        return

    # ── LONG message ─────────────────────────────────────────────────────────
    if total_longs > 0:
        lines = [
            "🟢 <b>VOLUME SPIKE — LONG SETUP</b> 🟢",
            "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─",
        ]
        if longs["EXTREME"]:
            lines.append("🔥 <b>EXTREME (5×+)</b>\n")
            for e in longs["EXTREME"]:
                lines.append(fmt_long(e))
                lines.append("")
        if longs["HIGH"]:
            lines.append("⚡ <b>HIGH (3–5×)</b>\n")
            for e in longs["HIGH"]:
                lines.append(fmt_long(e))
                lines.append("")
        lines.append(f"🕐 {now_str}")
        send_alert("\n".join(lines))

    # ── SHORT message ─────────────────────────────────────────────────────────
    if total_shorts > 0:
        lines = [
            "🔴 <b>VOLUME SPIKE — SHORT SETUP</b> 🔴",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        if shorts["EXTREME"]:
            lines.append("🔥 <b>EXTREME (5×+)</b>\n")
            for e in shorts["EXTREME"]:
                lines.append(fmt_short(e))
                lines.append("")
        if shorts["HIGH"]:
            lines.append("⚡ <b>HIGH (3–5×)</b>\n")
            for e in shorts["HIGH"]:
                lines.append(fmt_short(e))
                lines.append("")
        lines.append(f"🕐 {now_str}")
        send_alert("\n".join(lines))

    log.info("Scan complete.")


# ─────────────────────────────────────────
# TIMING
# ─────────────────────────────────────────

def wait_until_next_scan():
    now      = datetime.now(timezone.utc)
    next_run = now.replace(minute=1, second=0, microsecond=0)
    if now.minute >= 1:
        next_run += timedelta(hours=1)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(max(sleep_secs, 1))


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    log.info("Volume Spike Scanner started.")
    send_alert(
        "🔊 <b>Volume Spike Scanner Online</b>\n"
        "Scanning every hour at :01\n\n"
        "🟢 LONG SETUP  — spike up + close top 60% + buyers >55%\n"
        "🔴 SHORT SETUP — spike down + close bot 40% + sellers >55%\n\n"
        "🔥 Extreme: RVOL 5×+  |  ⚡ High: RVOL 3–5×\n"
        "❌ Fake pumps/dumps filtered out automatically\n"
        "⏱ 4-hour cooldown per coin"
    )
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()