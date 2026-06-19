"""
Volume Spike Signal
===================
Scans all 500M+ market cap coins on Coinbase for volume spikes.
Runs on the 1h timeframe only (15m removed to reduce noise).

Signal tiers (RVOL-based):
  !! High spike    : RVOL 3–5×
  !!! Extreme spike: RVOL 5×+

  Normal spikes (2–3×) are intentionally suppressed.

Rules (BOTH must fire):
  • RVOL   ≥ 3.0×
  • Z-Score ≥ 2.5

Also detects:
  • CVD (buy vs sell volume split per candle)
  • Divergence warning (price up but sellers dominating)
  • Consecutive spike count
  • 4-hour cooldown per coin to suppress repeat alerts

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

# ── Thresholds (tightened) ─────────────────────────────────────────────────────
VOL_WINDOW     = 50       # Wider baseline → more stable average
RVOL_THRESH    = 3.0      # Raised from 2.0 — skips NORMAL tier entirely
ZSCORE_THRESH  = 2.5      # Raised from 2.0
REQUIRE_BOTH   = True     # BOTH RVOL and Z-Score must fire (was False)
COOLDOWN_HOURS = 4        # Suppress repeat alerts per coin per timeframe

# ── Timeframes (1h only) ───────────────────────────────────────────────────────
INTERVALS = ["1h"]

GRANULARITY_MAP = {
    "1h": "ONE_HOUR",
}

LOOKBACK_LIMIT = {
    "1h": 150,   # Extra candles so VOL_WINDOW=50 has a solid history
}

SIGNAL_MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "signal_memory_vol_spike.json"
)


# ─────────────────────────────────────────
# SIGNAL MEMORY  (with timestamp cooldown)
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
    """
    Returns True only if:
      1. The stored tier/direction changed, OR
      2. The cooldown window has elapsed since the last alert.
    """
    entry = memory.get(key)
    if entry is None:
        return True

    # Support old flat-string format gracefully
    if isinstance(entry, str):
        return entry != value

    last_val  = entry.get("value")
    last_ts   = entry.get("ts", 0)
    now_ts    = datetime.now(timezone.utc).timestamp()
    elapsed_h = (now_ts - last_ts) / 3600

    if last_val != value:
        return True                         # Signal changed — always fire
    if elapsed_h >= COOLDOWN_HOURS:
        return True                         # Cooldown expired — fire again
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
# COINBASE CANDLES
# ─────────────────────────────────────────

def get_candles(ticker, interval):
    """Fetch OHLCV candles from Coinbase. Returns list of dicts or None."""
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
    """Returns (rvol, zscore, avg_vol) vs last N candles."""
    volumes = [c["volume"] for c in candles]
    window  = volumes[-VOL_WINDOW - 1:-1]
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
      sell_vol = volume − buy_vol
    """
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
    delta    = int(buy_vol - sell_vol)
    return buy_pct, sell_pct, delta


def get_tier(rvol):
    if rvol >= 5.0:
        return "EXTREME"
    elif rvol >= 3.0:
        return "HIGH"
    return "NONE"   # NORMAL (2–3×) is intentionally excluded


def get_close_position(candle):
    rng = candle["high"] - candle["low"]
    if rng == 0:
        return 50.0
    return round((candle["close"] - candle["low"]) / rng * 100, 1)


def is_spike(rvol, zscore):
    """Both RVOL and Z-Score must exceed their thresholds."""
    return rvol >= RVOL_THRESH and zscore >= ZSCORE_THRESH


# ─────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────

def fmt_price(p):
    if not p:
        return "N/A"
    if p >= 1000:  return f"${p:,.2f}"
    if p >= 1:     return f"${p:.4f}"
    return f"${p:.6f}"


def fmt_vol(v):
    if v >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:     return f"${v/1_000_000:.1f}M"
    if v >= 1_000:         return f"${v/1_000:.1f}K"
    return f"{v:.2f}"


def fmt_entry(e):
    tier_emoji      = {"EXTREME": "🔥", "HIGH": "⚡"}.get(e["tier"], "⚡")
    direction_emoji = "🟢" if e["direction"] == "BUY" else "🔴"
    div_line        = "\n⚠️ <b>DIVERGENCE</b>: Price up but sellers dominating" if e["divergence"] else ""
    consec_line     = f"\n🔁 <b>{e['consecutive']} consecutive spikes</b>" if e["consecutive"] >= 2 else ""

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

def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Scanning... {now_str}")

    coins = get_coins()
    if not coins:
        log.error("No coins fetched — aborting.")
        return

    memory  = load_memory()
    results = {interval: {"EXTREME": [], "HIGH": []} for interval in INTERVALS}
    skipped = 0

    for ticker, mcap in coins:
        for interval in INTERVALS:
            candles = get_candles(ticker, interval)
            if not candles:
                skipped += 1
                continue

            rvol, zscore, avg_vol = calc_rvol_zscore(candles)

            if not is_spike(rvol, zscore):
                continue

            tier = get_tier(rvol)
            if tier == "NONE":
                continue  # NORMAL tier suppressed

            last       = candles[-1]
            buy_pct, sell_pct, delta = calc_cvd(last)
            close_pos  = get_close_position(last)
            direction  = "BUY" if last["close"] >= last["open"] else "SELL"
            divergence = direction == "BUY" and sell_pct > 60

            # Count consecutive candles above RVOL threshold
            consecutive = 0
            for c in reversed(candles):
                if c["volume"] > avg_vol * RVOL_THRESH:
                    consecutive += 1
                else:
                    break

            sig_key = f"{ticker}_{interval}_spike"
            sig_val = f"{tier}_{direction}"

            if not is_new_signal(memory, sig_key, sig_val):
                log.debug(f"{ticker} [{interval}] suppressed (cooldown or same signal)")
                continue

            update_memory(memory, sig_key, sig_val)

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

    # ── Send alerts per timeframe ──────────────────────────────────────────────
    for interval in INTERVALS:
        tiers = results[interval]
        total = sum(len(v) for v in tiers.values())
        if total == 0:
            log.info(f"No new volume spikes on {interval}.")
            continue

        tf_label = {"1h": "1-Hour"}.get(interval, interval)
        lines = [
            f"🔊 <b>VOLUME SPIKE SIGNAL — {tf_label}</b>",
            "╔════════════════════╗",
            f"🕐 {now_str}",
            "╚════════════════════╝",
        ]

        if tiers["EXTREME"]:
            lines.append(f"\n🔥 <b>EXTREME SPIKES (5×+)</b> — {len(tiers['EXTREME'])} coins")
            for e in tiers["EXTREME"]:
                lines.append(fmt_entry(e))

        if tiers["HIGH"]:
            lines.append(f"\n⚡ <b>HIGH SPIKES (3–5×)</b> — {len(tiers['HIGH'])} coins")
            for e in tiers["HIGH"]:
                lines.append(fmt_entry(e))

        send_alert("\n".join(lines))

    log.info("Scan complete.")


# ─────────────────────────────────────────
# TIMING — synced to 1h candle close
# ─────────────────────────────────────────

def wait_until_next_scan():
    """
    1h candles close at :00 each hour.
    Scan fires at :01 to ensure the candle is confirmed.
    """
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
        "🔥 Extreme spike  — RVOL 5×+  (Z ≥ 2.5, both required)\n"
        "⚡ High spike     — RVOL 3–5× (Z ≥ 2.5, both required)\n\n"
        "📵 Normal spikes suppressed\n"
        "⏱ 4-hour cooldown per coin\n"
        "Includes CVD (buy/sell split) + divergence warnings"
    )
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()