"""
Volume Spike Signal
===================
Scans all 500M+ market cap coins on Coinbase for volume spikes.
Runs on both 15m and 1h timeframes.

Signal tiers (RVOL-based):
  !  Normal spike  : RVOL 2–3×
  !! High spike    : RVOL 3–5×
  !!! Extreme spike: RVOL 5×+

Also detects:
  • CVD (buy vs sell volume split per candle)
  • Divergence warning (price up but sellers dominating)
  • Consecutive spike count

Env vars required:
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import json
import time
import logging
import requests
import numpy as np
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

VOL_WINDOW     = 20       # Rolling window for avg/std calculation
RVOL_THRESH    = 2.0      # Minimum RVOL to trigger
ZSCORE_THRESH  = 2.0      # Minimum Z-Score to trigger
REQUIRE_BOTH   = False    # True = RVOL AND Z-Score must both fire

SIGNAL_MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "signal_memory_vol_spike.json"
)

GRANULARITY_MAP = {
    "15m": "FIFTEEN_MINUTE",
    "1h":  "ONE_HOUR",
}

LOOKBACK_LIMIT = {
    "15m": 100,
    "1h":  100,
}


# ─────────────────────────────────────────
# SIGNAL MEMORY
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
    return memory.get(key) != value


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
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


# ─────────────────────────────────────────
# COINBASE CANDLES (with volume)
# ─────────────────────────────────────────

def get_candles(ticker, interval):
    """Fetch OHLCV candles from Coinbase. Returns list of dicts or None."""
    granularity = GRANULARITY_MAP.get(interval)
    limit       = LOOKBACK_LIMIT.get(interval, 100)
    product_id  = f"{ticker}-USD"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": granularity, "limit": limit},
            timeout=10
        )
        data    = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < VOL_WINDOW + 2:
            return None
        # Coinbase returns newest first — reverse and drop last (incomplete candle)
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
    """
    Returns (rvol, zscore) for the last candle against a rolling window.
    """
    volumes = [c["volume"] for c in candles]
    window  = volumes[-VOL_WINDOW - 1:-1]   # last N candles excluding current
    current = volumes[-1]

    avg = sum(window) / len(window)
    std = (sum((v - avg) ** 2 for v in window) / len(window)) ** 0.5

    rvol   = current / avg if avg > 0 else 0
    zscore = (current - avg) / std if std > 0 else 0
    return round(rvol, 2), round(zscore, 2), round(avg, 2)


def calc_cvd(candle):
    """
    Estimate buy vs sell volume using candle body position.
    buy_vol  = volume × (close - low) / (high - low)
    sell_vol = volume - buy_vol
    """
    high   = candle["high"]
    low    = candle["low"]
    close  = candle["close"]
    volume = candle["volume"]
    rng    = high - low

    if rng == 0:
        buy_vol  = volume * 0.5
        sell_vol = volume * 0.5
    else:
        buy_vol  = volume * ((close - low) / rng)
        sell_vol = volume - buy_vol

    buy_pct  = round(buy_vol / volume * 100, 1) if volume > 0 else 50.0
    sell_pct = round(100 - buy_pct, 1)
    delta    = int(buy_vol - sell_vol)
    return buy_pct, sell_pct, delta


def get_tier(rvol):
    if rvol >= 5.0:
        return "EXTREME"
    elif rvol >= 3.0:
        return "HIGH"
    elif rvol >= 2.0:
        return "NORMAL"
    return "NONE"


def get_close_position(candle):
    rng = candle["high"] - candle["low"]
    if rng == 0:
        return 50.0
    return round((candle["close"] - candle["low"]) / rng * 100, 1)


def is_spike(rvol, zscore):
    rvol_hit   = rvol   >= RVOL_THRESH
    zscore_hit = zscore >= ZSCORE_THRESH
    return (rvol_hit and zscore_hit) if REQUIRE_BOTH else (rvol_hit or zscore_hit)


# ─────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────

def fmt_price(p):
    if not p or p == 0:
        return "N/A"
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"


def fmt_vol(v):
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"{v:.2f}"


def fmt_entry(e, interval):
    tier_emoji = {"EXTREME": "🔥", "HIGH": "⚡", "NORMAL": "📊"}.get(e["tier"], "📊")
    direction_emoji = "🟢" if e["direction"] == "BUY" else "🔴"
    div_line = "\n⚠️ <b>DIVERGENCE</b>: Price up but sellers dominating" if e["divergence"] else ""
    consec_line = f"\n🔁 <b>{e['consecutive']} consecutive spikes</b>" if e["consecutive"] >= 2 else ""

    return (
        f"\n<b>{e['ticker']}</b> — {e['mcap']}\n"
        f"{tier_emoji} {e['tier']} SPIKE  {direction_emoji} {e['direction']}\n"
        f"💰 Price: {fmt_price(e['close'])}  |  Avg vol: {fmt_vol(e['avg_vol'])}\n"
        f"📦 Volume: {fmt_vol(e['volume'])}  (RVOL <b>{e['rvol']}×</b>  Z-Score <b>{e['zscore']}</b>)\n"
        f"📊 CVD: 🟢 Buy {e['buy_pct']}%  🔴 Sell {e['sell_pct']}%  |  Δ {e['delta']:+,}\n"
        f"🕯 Close: {fmt_price(e['close'])}  (top {100 - int(e['close_pos'])}% of range)"
        f"{div_line}"
        f"{consec_line}\n"
        f"<a href='https://www.tradingview.com/chart/?symbol=COINBASE:{e['ticker']}USD'>📈 Chart</a>"
    )


# ─────────────────────────────────────────
# SCAN
# ─────────────────────────────────────────

def run_scan(intervals=None):
    if intervals is None:
        intervals = ["15m", "1h"]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")

    coins  = get_coins()
    if not coins:
        log.error("No coins fetched — aborting.")
        return

    memory  = load_memory()
    results = {interval: {"EXTREME": [], "HIGH": [], "NORMAL": []} for interval in intervals}
    skipped = 0

    for ticker, mcap in coins:
        for interval in intervals:
            candles = get_candles(ticker, interval)
            if not candles:
                skipped += 1
                continue

            rvol, zscore, avg_vol = calc_rvol_zscore(candles)
            if not is_spike(rvol, zscore):
                continue

            tier = get_tier(rvol)
            if tier == "NONE":
                continue

            last = candles[-1]
            buy_pct, sell_pct, delta = calc_cvd(last)
            close_pos  = get_close_position(last)
            direction  = "BUY" if last["close"] >= last["open"] else "SELL"
            divergence = direction == "BUY" and sell_pct > 60

            # Count consecutive spikes
            consecutive = 0
            for c in reversed(candles):
                v = c["volume"]
                if v > avg_vol * RVOL_THRESH:
                    consecutive += 1
                else:
                    break

            sig_key = f"{ticker}_{interval}_spike"
            sig_val = f"{tier}_{direction}"

            if not is_new_signal(memory, sig_key, sig_val):
                continue

            memory[sig_key] = sig_val

            entry = {
                "ticker":      ticker,
                "mcap":        mcap,
                "tier":        tier,
                "direction":   direction,
                "close":       last["close"],
                "volume":      last["volume"],
                "avg_vol":     avg_vol,
                "rvol":        rvol,
                "zscore":      zscore,
                "buy_pct":     buy_pct,
                "sell_pct":    sell_pct,
                "delta":       delta,
                "close_pos":   close_pos,
                "divergence":  divergence,
                "consecutive": consecutive,
            }

            results[interval][tier].append(entry)
            log.info(f"{ticker} [{interval}] {tier} SPIKE — RVOL {rvol}× Z {zscore} {direction}")

        time.sleep(0.2)

    save_memory(memory)
    log.info(f"{skipped} candle fetches skipped")

    # ── Send alerts per timeframe ─────────────────────────
    for interval in intervals:
        tiers = results[interval]
        total = sum(len(v) for v in tiers.values())
        if total == 0:
            log.info(f"No new volume spikes on {interval}.")
            continue

        tf_label = {"15m": "15-Minute", "1h": "1-Hour"}.get(interval, interval)
        lines = [
            f"🔊 <b>VOLUME SPIKE SIGNAL — {tf_label}</b>",
            "╔════════════════════╗",
            f"🕐 {now_str}",
            "╚════════════════════╝",
        ]

        if tiers["EXTREME"]:
            lines.append(f"\n🔥 <b>EXTREME SPIKES (5×+)</b> — {len(tiers['EXTREME'])} coins")
            for e in tiers["EXTREME"]:
                lines.append(fmt_entry(e, interval))

        if tiers["HIGH"]:
            lines.append(f"\n⚡ <b>HIGH SPIKES (3–5×)</b> — {len(tiers['HIGH'])} coins")
            for e in tiers["HIGH"]:
                lines.append(fmt_entry(e, interval))

        if tiers["NORMAL"]:
            lines.append(f"\n📊 <b>NORMAL SPIKES (2–3×)</b> — {len(tiers['NORMAL'])} coins")
            for e in tiers["NORMAL"]:
                lines.append(fmt_entry(e, interval))

        send_alert("\n".join(lines))

    log.info("Scan complete.")


# ─────────────────────────────────────────
# TIMING — synced to candle close
# ─────────────────────────────────────────

def wait_until_next_scan():
    """
    15m candles close at :00, :15, :30, :45
    1h  candles close at :00
    Scan fires 1 minute after close to ensure candle is confirmed.
    Returns which intervals to scan.
    """
    now      = datetime.now(timezone.utc)
    minute   = now.minute
    # Next :01, :16, :31, :46
    targets  = [1, 16, 31, 46]
    upcoming = [t for t in targets if t > minute]
    next_min = upcoming[0] if upcoming else targets[0]

    next_run = now.replace(second=0, microsecond=0)
    if next_min <= minute:
        next_run += timedelta(hours=1)
    next_run = next_run.replace(minute=next_min)

    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(max(sleep_secs, 1))

    # At :01 — scan 1h too; otherwise just 15m
    fired_minute = next_run.minute
    if fired_minute == 1:
        return ["15m", "1h"]
    return ["15m"]


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    log.info("Volume Spike Scanner started.")
    send_alert(
        "🔊 <b>Volume Spike Scanner Online</b>\n"
        "Scanning every 15 minutes at :01 :16 :31 :46\n\n"
        "🔥 Extreme spike  — RVOL 5×+\n"
        "⚡ High spike     — RVOL 3–5×\n"
        "📊 Normal spike   — RVOL 2–3×\n\n"
        "Includes CVD (buy/sell split) + divergence warnings"
    )
    run_scan(["15m", "1h"])
    while True:
        intervals = wait_until_next_scan()
        run_scan(intervals)