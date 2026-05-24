# signal6.py
# Long/Short Ratio + Funding Rate + OI — MC > $1B — Binance Futures
# Scans every 15 minutes

import requests
import time
from datetime import datetime, timezone

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"
MARKET_CAP_MIN = 1_000_000_000
SCAN_INTERVAL  = 15 * 60
COOLDOWN_SEC   = 3600

# Thresholds
LS_HIGH          = 1.8    # too many longs
LS_LOW           = 0.6    # too many shorts
FUNDING_HIGH     = 0.0008 # 0.08% — longs overheated
FUNDING_LOW      = -0.0003 # negative — shorts overheated
OI_CHANGE_HIGH   = 0.20   # 20% OI change in 4H = big move
TOP_TRADER_HIGH  = 1.5    # top traders heavily long
TOP_TRADER_LOW   = 0.7    # top traders heavily short

last_alerted = {}

# Shared results for Signal 7
signal6_results = {}

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

def get_global_ls_ratio(symbol):
    try:
        r    = requests.get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
            params={"symbol": f"{symbol}USDT", "period": "1h", "limit": 5}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        return [float(d["longShortRatio"]) for d in data]
    except Exception:
        return None

def get_top_trader_ls_ratio(symbol):
    try:
        r    = requests.get("https://fapi.binance.com/futures/data/topLongShortPositionRatio",
            params={"symbol": f"{symbol}USDT", "period": "1h", "limit": 5}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        return [float(d["longShortRatio"]) for d in data]
    except Exception:
        return None

def get_funding_rate(symbol):
    try:
        r    = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": f"{symbol}USDT", "limit": 3}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        return [float(d["fundingRate"]) for d in data]
    except Exception:
        return None

def get_open_interest(symbol):
    try:
        r    = requests.get("https://fapi.binance.com/futures/data/openInterestHist",
            params={"symbol": f"{symbol}USDT", "period": "1h", "limit": 5}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        return [float(d["sumOpenInterestValue"]) for d in data]
    except Exception:
        return None

def run():
    send_telegram(
        "6️⃣ *Signal 6 Started*\n"
        "Long/Short Ratio + Funding + OI | MC > $1B | Every 15min"
    )

    while True:
        try:
            print(f"\n[Signal6] Scanning L/S + Funding + OI...")
            coins         = get_coins()
            futures_pairs = get_futures_pairs()
            valid         = [c for c in coins if f"{c['symbol']}USDT" in futures_pairs]

            for coin in valid:
                symbol = coin["symbol"]
                try:
                    # Get all data
                    global_ls  = get_global_ls_ratio(symbol)
                    top_ls     = get_top_trader_ls_ratio(symbol)
                    funding    = get_funding_rate(symbol)
                    oi         = get_open_interest(symbol)

                    if not global_ls or not funding or not oi:
                        continue

                    curr_ls      = global_ls[-1]
                    curr_top_ls  = top_ls[-1] if top_ls else None
                    curr_funding = funding[-1]
                    curr_oi      = oi[-1]
                    prev_oi      = oi[0]
                    oi_change    = (curr_oi - prev_oi) / prev_oi if prev_oi > 0 else 0

                    # Save for Signal 7
                    signal6_results[symbol] = {
                        "ls_ratio":    curr_ls,
                        "top_ls":      curr_top_ls,
                        "funding":     curr_funding,
                        "oi":          curr_oi,
                        "oi_change":   oi_change,
                    }

                    if is_on_cooldown(symbol):
                        continue

                    top_ls_text = f"`{curr_top_ls:.2f}`" if curr_top_ls else "`N/A`"

                    # ── LONG SQUEEZE RISK ─────────────────────────────────────
                    if curr_ls >= LS_HIGH and curr_funding >= FUNDING_HIGH and oi_change < 0:
                        send_telegram(
                            f"💥 *LONG SQUEEZE RISK*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📊 L/S Ratio    : `{curr_ls:.2f}` (too many longs)\n"
                            f"🏆 Top Traders  : {top_ls_text}\n"
                            f"💸 Funding Rate : `{curr_funding*100:.4f}%` (overheated)\n"
                            f"📉 OI Change    : `{oi_change*100:+.2f}%` (dropping)\n"
                            f"⚠️ Meaning     : Longs overloaded + OI dropping = squeeze risk\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                    # ── SHORT SQUEEZE RISK ────────────────────────────────────
                    elif curr_ls <= LS_LOW and curr_funding <= FUNDING_LOW and oi_change < 0:
                        send_telegram(
                            f"💥 *SHORT SQUEEZE RISK*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📊 L/S Ratio    : `{curr_ls:.2f}` (too many shorts)\n"
                            f"🏆 Top Traders  : {top_ls_text}\n"
                            f"💸 Funding Rate : `{curr_funding*100:.4f}%` (negative)\n"
                            f"📉 OI Change    : `{oi_change*100:+.2f}%` (dropping)\n"
                            f"⚠️ Meaning     : Shorts overloaded + OI dropping = squeeze risk\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                    # ── SMART MONEY LONG ──────────────────────────────────────
                    elif curr_top_ls and curr_top_ls >= TOP_TRADER_HIGH and oi_change > 0:
                        send_telegram(
                            f"🐂 *SMART MONEY GOING LONG*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"🏆 Top Traders  : `{curr_top_ls:.2f}` (heavily long)\n"
                            f"📊 Global L/S   : `{curr_ls:.2f}`\n"
                            f"💸 Funding Rate : `{curr_funding*100:.4f}%`\n"
                            f"📈 OI Change    : `{oi_change*100:+.2f}%` (rising)\n"
                            f"✅ Meaning     : Smart money adding longs + OI rising = bullish\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                    # ── SMART MONEY SHORT ─────────────────────────────────────
                    elif curr_top_ls and curr_top_ls <= TOP_TRADER_LOW and oi_change > 0:
                        send_telegram(
                            f"🐻 *SMART MONEY GOING SHORT*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"🏆 Top Traders  : `{curr_top_ls:.2f}` (heavily short)\n"
                            f"📊 Global L/S   : `{curr_ls:.2f}`\n"
                            f"💸 Funding Rate : `{curr_funding*100:.4f}%`\n"
                            f"📈 OI Change    : `{oi_change*100:+.2f}%` (rising)\n"
                            f"⚠️ Meaning     : Smart money adding shorts + OI rising = bearish\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                    # ── OI EXPLOSION ──────────────────────────────────────────
                    elif abs(oi_change) >= OI_CHANGE_HIGH:
                        direction = "UP" if oi_change > 0 else "DOWN"
                        emoji     = "📈" if oi_change > 0 else "📉"
                        send_telegram(
                            f"{emoji} *OI EXPLOSION — {direction}*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📈 OI Change    : `{oi_change*100:+.2f}%` in 4H\n"
                            f"📊 L/S Ratio    : `{curr_ls:.2f}`\n"
                            f"💸 Funding Rate : `{curr_funding*100:.4f}%`\n"
                            f"⚡ Meaning     : Massive OI move = big price move incoming\n"
                            f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                except Exception as e:
                    print(f"[Signal6] {symbol} error: {e}")
                time.sleep(0.2)

        except Exception as e:
            print(f"[Signal6] Scan error: {e}")
            send_telegram(f"⚠️ Signal 6 error: `{e}`")

        time.sleep(SCAN_INTERVAL)