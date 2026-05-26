import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN        = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID          = "8118939134"

MARKET_CAP_MIN   = 1_000_000_000

# Alert 1 — OI Spike
OI_SPIKE_PCT     = 2.0        # OI must change by 2%

# Alert 2 — OI Acceleration
OI_ACCEL_MIN_PCT = 1.0        # each period minimum 1% change
OI_ACCEL_PERIODS = 3          # 3 consecutive rising periods
OI_ACCEL_STEP    = 0.3        # each period must be 0.3% bigger than last

SCAN_INTERVAL    = 15 * 60
COOLDOWN_SEC     = 3600

last_alerted_spike = {}
last_alerted_accel = {}

# ─────────────────────────────────────────
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def is_on_cooldown(symbol, store):
    return symbol in store and time.time() - store[symbol] < COOLDOWN_SEC

def mark_alerted(symbol, store):
    store[symbol] = time.time()

# ─────────────────────────────────────────
def get_coins():
    coins = []
    page  = 1
    while True:
        try:
            r    = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": 250, "page": page, "sparkline": False},
                timeout=30
            )
            data = r.json()
            if not data or not isinstance(data, list):
                break
            for coin in data:
                mc = coin.get("market_cap") or 0
                if mc < MARKET_CAP_MIN:
                    return coins
                coins.append({"symbol": coin["symbol"].upper(), "market_cap": mc})
            if (data[-1].get("market_cap") or 0) < MARKET_CAP_MIN:
                break
            page += 1
            time.sleep(2.0)
        except Exception as e:
            print(f"CoinGecko error: {e}")
            break
    return coins

# ─────────────────────────────────────────
def get_oi(symbol, periods=6):
    """Fetch OI history from Binance futures"""
    try:
        r    = requests.get(
            "https://fapi.binance.com/futures/data/openInterestHist",
            params={"symbol": f"{symbol}USDT", "period": "1h", "limit": periods},
            timeout=10
        )
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        return [float(d["sumOpenInterest"]) for d in data]
    except Exception:
        return None

def get_price(symbol):
    """Get latest price from Binance"""
    try:
        r    = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/price",
            params={"symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        return float(data["price"]) if "price" in data else None
    except Exception:
        return None

# ─────────────────────────────────────────
def check_oi_spike(oi_list):
    """Alert 1 — OI changed by 2%+ in latest period"""
    if len(oi_list) < 2:
        return None, 0
    prev = oi_list[-2]
    curr = oi_list[-1]
    if prev == 0:
        return None, 0
    change_pct = (curr - prev) / prev * 100
    if abs(change_pct) >= OI_SPIKE_PCT:
        direction = "bullish" if change_pct > 0 else "bearish"
        return direction, change_pct
    return None, change_pct

# ─────────────────────────────────────────
def check_oi_acceleration(oi_list):
    """Alert 2 — OI accelerating: each period bigger than last"""
    if len(oi_list) < OI_ACCEL_PERIODS + 1:
        return False, []

    # Calculate % change for each consecutive period
    changes = []
    for i in range(1, len(oi_list)):
        prev = oi_list[i - 1]
        curr = oi_list[i]
        if prev == 0:
            return False, []
        changes.append((curr - prev) / prev * 100)

    # Take last N periods
    recent = changes[-(OI_ACCEL_PERIODS):]

    # All must be positive (OI rising)
    if not all(c > 0 for c in recent):
        return False, recent

    # Each must be above minimum
    if not all(c >= OI_ACCEL_MIN_PCT for c in recent):
        return False, recent

    # Each period must be bigger than the last (acceleration)
    for i in range(1, len(recent)):
        if recent[i] < recent[i - 1] + OI_ACCEL_STEP:
            return False, recent

    return True, recent

# ─────────────────────────────────────────
def run():
    send_telegram(
        "2️⃣ *Signal 2 Started* ✅\n"
        "────────────────────\n"
        "🔥 *Alert 1* : OI Spike > 2%\n"
        "🚀 *Alert 2* : OI Acceleration (3 periods, +0.3% each)\n"
        "📊 *No price filter — pure OI*\n"
        "💰 *MC Filter* : > $1B\n"
        "🔄 *Scan every* : 15 min"
    )

    while True:
        try:
            print(f"\n[Signal2] Scanning...")
            coins = get_coins()

            for coin in coins:
                symbol = coin["symbol"]
                try:
                    oi_list = get_oi(symbol, periods=6)
                    if not oi_list or len(oi_list) < 4:
                        continue

                    price = get_price(symbol)
                    if price is None:
                        continue

                    # ── Alert 1: OI Spike ──────────────────
                    direction, oi_change = check_oi_spike(oi_list)
                    if direction and not is_on_cooldown(symbol, last_alerted_spike):
                        emoji     = "🔥📈" if direction == "bullish" else "🔥📉"
                        move_txt  = "OI SURGING UP — Longs being built 🟢" if direction == "bullish" \
                                    else "OI DROPPING — Positions closing/shorts 🔴"
                        send_telegram(
                            f"{emoji} *OI SPIKE SIGNAL*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"💰 Price       : `${price:,.4f}`\n"
                            f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"────────────────────\n"
                            f"📊 OI Change   : `{oi_change:+.2f}%`\n"
                            f"💡 {move_txt}\n"
                            f"⚠️ Price move expected soon\n"
                            f"────────────────────\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol, last_alerted_spike)
                        print(f"[Signal2] OI SPIKE — {symbol} | {oi_change:+.2f}%")
                        time.sleep(0.5)

                    # ── Alert 2: OI Acceleration ───────────
                    accel_ok, recent_changes = check_oi_acceleration(oi_list)
                    if accel_ok and not is_on_cooldown(symbol, last_alerted_accel):
                        periods_txt = "\n".join([
                            f"📊 Period {i+1}     : `{c:+.2f}%`"
                            for i, c in enumerate(recent_changes)
                        ])
                        send_telegram(
                            f"🚀 *OI ACCELERATION SIGNAL*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"💰 Price       : `${price:,.4f}`\n"
                            f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"────────────────────\n"
                            f"📈 OI growing faster each period:\n"
                            f"{periods_txt}\n"
                            f"────────────────────\n"
                            f"💡 Strong momentum building — big move coming\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol, last_alerted_accel)
                        print(f"[Signal2] OI ACCEL — {symbol} | {recent_changes}")
                        time.sleep(0.5)

                except Exception as e:
                    print(f"[Signal2] {symbol} error: {e}")
                time.sleep(0.15)

        except Exception as e:
            print(f"[Signal2] Scan error: {e}")

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()