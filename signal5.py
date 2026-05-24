# signal5.py
# Exchange Inflow/Outflow — MC > $1B — Binance Futures
# Scans every 15 minutes

import requests
import time
from datetime import datetime, timezone

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"
MARKET_CAP_MIN = 1_000_000_000
SCAN_INTERVAL  = 15 * 60
COOLDOWN_SEC   = 3600

# Inflow/Outflow thresholds
INFLOW_SPIKE_MULT  = 2.0   # inflow must be 2x 7d average
OUTFLOW_SPIKE_MULT = 2.0   # outflow must be 2x 7d average
STABLE_SPIKE_MULT  = 2.0   # stablecoin flow must be 2x average

last_alerted = {}

# Shared results for Signal 7
signal5_results = {}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def is_on_cooldown(symbol):
    return symbol in last_alerted and time.time() - last_alerted[symbol] < COOLDOWN_SEC

def mark_alerted(symbol):
    last_alerted[symbol] = time.time()

def get_coins():
    coins = []
    page  = 1
    while True:
        try:
            r    = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": 250, "page": page, "sparkline": False}, timeout=30)
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

def get_futures_pairs():
    try:
        r    = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=15)
        data = r.json()
        return {s["symbol"] for s in data["symbols"] if s["status"] == "TRADING"}
    except Exception:
        return set()

# ── GET TAKER BUY/SELL VOLUME (proxy for inflow/outflow) ─────────────────────
def get_taker_volume(symbol, period="1h", limit=168):
    # 168 hours = 7 days
    try:
        r = requests.get("https://fapi.binance.com/futures/data/takerlongshortRatio",
            params={"symbol": f"{symbol}USDT", "period": period, "limit": limit}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        buy_vols  = [float(d["buyVol"]) for d in data]
        sell_vols = [float(d["sellVol"]) for d in data]
        return buy_vols, sell_vols
    except Exception:
        return None

def get_stablecoin_flow():
    # Check USDT and USDC taker volume as proxy for stablecoin inflow
    try:
        r = requests.get("https://fapi.binance.com/futures/data/takerlongshortRatio",
            params={"symbol": "BTCUSDT", "period": "1h", "limit": 168}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None, None
        buy_vols  = [float(d["buyVol"]) for d in data]
        sell_vols = [float(d["sellVol"]) for d in data]
        return buy_vols, sell_vols
    except Exception:
        return None, None

def run():
    send_telegram(
        "5️⃣ *Signal 5 Started*\n"
        "Exchange Inflow/Outflow | MC > $1B | Every 15min"
    )

    while True:
        try:
            print(f"\n[Signal5] Scanning inflow/outflow...")
            coins        = get_coins()
            futures_pairs = get_futures_pairs()
            valid        = [c for c in coins if f"{c['symbol']}USDT" in futures_pairs]

            for coin in valid:
                symbol = coin["symbol"]
                try:
                    result = get_taker_volume(symbol)
                    if not result:
                        continue

                    buy_vols, sell_vols = result

                    if len(buy_vols) < 24:
                        continue

                    # Current (last 1H)
                    curr_buy  = buy_vols[-1]
                    curr_sell = sell_vols[-1]

                    # 7 day average
                    avg_buy  = sum(buy_vols[:-1]) / len(buy_vols[:-1])
                    avg_sell = sum(sell_vols[:-1]) / len(sell_vols[:-1])

                    # Ratios
                    buy_ratio  = curr_buy  / avg_buy  if avg_buy  > 0 else 0
                    sell_ratio = curr_sell / avg_sell if avg_sell > 0 else 0

                    # Net flow
                    net_flow     = curr_buy - curr_sell
                    net_flow_avg = avg_buy - avg_sell

                    # Save for Signal 7
                    signal5_results[symbol] = {
                        "buy_ratio":  buy_ratio,
                        "sell_ratio": sell_ratio,
                        "net_flow":   net_flow,
                        "curr_buy":   curr_buy,
                        "curr_sell":  curr_sell,
                        "avg_buy":    avg_buy,
                        "avg_sell":   avg_sell,
                    }

                    if is_on_cooldown(symbol):
                        continue

                    # ── SELL PRESSURE ─────────────────────────────────────────
                    if sell_ratio >= INFLOW_SPIKE_MULT and sell_ratio > buy_ratio:
                        send_telegram(
                            f"🔴 *EXCHANGE INFLOW SPIKE*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📥 Sell Volume : `{sell_ratio:.1f}x` vs 7d average\n"
                            f"📈 Buy Volume  : `{buy_ratio:.1f}x` vs 7d average\n"
                            f"⚠️ Meaning    : Large deposits to exchange = Sell pressure\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                    # ── ACCUMULATION ──────────────────────────────────────────
                    elif buy_ratio >= OUTFLOW_SPIKE_MULT and buy_ratio > sell_ratio:
                        send_telegram(
                            f"🟢 *EXCHANGE OUTFLOW SPIKE*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📤 Buy Volume  : `{buy_ratio:.1f}x` vs 7d average\n"
                            f"📥 Sell Volume : `{sell_ratio:.1f}x` vs 7d average\n"
                            f"✅ Meaning    : Large withdrawals = Accumulation signal\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                    # ── UNUSUAL BOTH DIRECTIONS ───────────────────────────────
                    elif buy_ratio >= 1.5 and sell_ratio >= 1.5:
                        send_telegram(
                            f"⚠️ *UNUSUAL FLOW ACTIVITY*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📤 Buy Volume  : `{buy_ratio:.1f}x` vs 7d average\n"
                            f"📥 Sell Volume : `{sell_ratio:.1f}x` vs 7d average\n"
                            f"🔍 Meaning    : Both inflow and outflow spiking = volatility incoming\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                except Exception as e:
                    print(f"[Signal5] {symbol} error: {e}")
                time.sleep(0.2)

        except Exception as e:
            print(f"[Signal5] Scan error: {e}")
            send_telegram(f"⚠️ Signal 5 error: `{e}`")

        time.sleep(SCAN_INTERVAL)