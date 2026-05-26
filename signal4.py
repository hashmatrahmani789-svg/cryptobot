import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"

MARKET_CAP_MIN = 500_000_000

# EMA Settings
EMA_FAST       = 12
EMA_SLOW       = 21
EMA_TREND      = 50

# ─────────────────────────────────────────
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

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

def get_binance_pairs():
    try:
        r    = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=15)
        data = r.json()
        return {s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"}
    except Exception:
        return set()

def get_daily_closes(symbol, limit=60):
    try:
        r    = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": f"{symbol}USDT", "interval": "1d", "limit": limit},
            timeout=10
        )
        data = r.json()
        if not data or isinstance(data, dict):
            return []
        return [float(c[4]) for c in data]
    except Exception:
        return []

def wait_until_next_daily_close():
    now        = datetime.now(timezone.utc)
    next_close = (now + timedelta(days=1)).replace(hour=0, minute=0, second=30, microsecond=0)
    return (next_close - now).total_seconds()

# ─────────────────────────────────────────
def run_scan():
    print(f"[Signal4] Running daily scan...")
    coins         = get_coins()
    binance_pairs = get_binance_pairs()

    alerts_1221   = 0   # EMA 12/21 cross alerts
    alerts_50     = 0   # EMA 50 trend alerts

    for coin in coins:
        symbol = coin["symbol"]
        try:
            if f"{symbol}USDT" not in binance_pairs:
                continue

            closes = get_daily_closes(symbol, limit=60)
            if len(closes) < 52:
                continue

            series        = pd.Series(closes)
            ema_fast_vals = series.ewm(span=EMA_FAST,  adjust=False).mean().tolist()
            ema_slow_vals = series.ewm(span=EMA_SLOW,  adjust=False).mean().tolist()
            ema_trend_vals= series.ewm(span=EMA_TREND, adjust=False).mean().tolist()

            price_curr    = closes[-1]
            price_prev    = closes[-2]

            # ── Alert 1: EMA 12/21 Cross ───────────────
            cross_bullish = ema_fast_vals[-2] < ema_slow_vals[-2] and ema_fast_vals[-1] > ema_slow_vals[-1]
            cross_bearish = ema_fast_vals[-2] > ema_slow_vals[-2] and ema_fast_vals[-1] < ema_slow_vals[-1]

            if cross_bullish:
                send_telegram(
                    f"🟢 *DAILY EMA CROSS — BULLISH*\n"
                    f"────────────────────\n"
                    f"📌 *{symbol}*\n"
                    f"💰 Price       : `${price_curr:,.4f}`\n"
                    f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
                    f"────────────────────\n"
                    f"📈 EMA12 crossed ABOVE EMA21\n"
                    f"⚡ Early signal — watch for continuation\n"
                    f"📊 EMA12 : `{ema_fast_vals[-1]:,.4f}`\n"
                    f"📊 EMA21 : `{ema_slow_vals[-1]:,.4f}`\n"
                    f"────────────────────\n"
                    f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}` (Daily Close)"
                )
                alerts_1221 += 1
                time.sleep(0.5)

            elif cross_bearish:
                send_telegram(
                    f"🔴 *DAILY EMA CROSS — BEARISH*\n"
                    f"────────────────────\n"
                    f"📌 *{symbol}*\n"
                    f"💰 Price       : `${price_curr:,.4f}`\n"
                    f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
                    f"────────────────────\n"
                    f"📉 EMA12 crossed BELOW EMA21\n"
                    f"⚡ Early signal — watch for reversal\n"
                    f"📊 EMA12 : `{ema_fast_vals[-1]:,.4f}`\n"
                    f"📊 EMA21 : `{ema_slow_vals[-1]:,.4f}`\n"
                    f"────────────────────\n"
                    f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}` (Daily Close)"
                )
                alerts_1221 += 1
                time.sleep(0.5)

            # ── Alert 2: EMA 50 Trend Cross ────────────
            ema50_cross_bullish = price_prev < ema_trend_vals[-2] and price_curr > ema_trend_vals[-1]
            ema50_cross_bearish = price_prev > ema_trend_vals[-2] and price_curr < ema_trend_vals[-1]

            if ema50_cross_bullish:
                send_telegram(
                    f"🔵 *EMA50 TREND SIGNAL — BULLISH*\n"
                    f"────────────────────\n"
                    f"📌 *{symbol}*\n"
                    f"💰 Price       : `${price_curr:,.4f}`\n"
                    f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
                    f"────────────────────\n"
                    f"📈 Price crossed ABOVE EMA50\n"
                    f"✅ Strong bullish trend confirmed\n"
                    f"📊 EMA50 : `{ema_trend_vals[-1]:,.4f}`\n"
                    f"💡 Safer entry — bigger move expected\n"
                    f"────────────────────\n"
                    f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}` (Daily Close)"
                )
                alerts_50 += 1
                time.sleep(0.5)

            elif ema50_cross_bearish:
                send_telegram(
                    f"🟠 *EMA50 TREND SIGNAL — BEARISH*\n"
                    f"────────────────────\n"
                    f"📌 *{symbol}*\n"
                    f"💰 Price       : `${price_curr:,.4f}`\n"
                    f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
                    f"────────────────────\n"
                    f"📉 Price crossed BELOW EMA50\n"
                    f"⚠️ Strong bearish trend confirmed\n"
                    f"📊 EMA50 : `{ema_trend_vals[-1]:,.4f}`\n"
                    f"💡 Safer signal — bigger dump expected\n"
                    f"────────────────────\n"
                    f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}` (Daily Close)"
                )
                alerts_50 += 1
                time.sleep(0.5)

            time.sleep(0.2)

        except Exception as e:
            print(f"[Signal4] {symbol} error: {e}")

    # ── Daily Summary ──────────────────────────
    send_telegram(
        f"✅ *Signal 4 Daily Scan Done*\n"
        f"────────────────────\n"
        f"🔍 Coins scanned   : `{len(coins)}`\n"
        f"🟢 EMA 12/21 alerts: `{alerts_1221}`\n"
        f"🔵 EMA 50 alerts   : `{alerts_50}`\n"
        f"📊 Total alerts    : `{alerts_1221 + alerts_50}`\n"
        f"⏰ Next scan       : `00:00 UTC tomorrow`"
    )
    print(f"[Signal4] Done. {alerts_1221 + alerts_50} alerts sent.")

# ─────────────────────────────────────────
def run():
    send_telegram(
        "4️⃣ *Signal 4 Started* ✅\n"
        "────────────────────\n"
        "🟢 *Alert 1* : Daily EMA 12/21 Cross\n"
        "🔵 *Alert 2* : Price crosses EMA 50\n"
        "💰 *MC Filter*: > $500M\n"
        "⏰ *Fires at* : 00:00 UTC daily close\n"
        "📊 *Candles* : Daily confirmed closes only"
    )

    # Run immediately on startup
    run_scan()

    # Then wait for daily close every day
    while True:
        try:
            wait       = wait_until_next_daily_close()
            close_time = (datetime.now(timezone.utc) + timedelta(seconds=wait)).strftime("%Y-%m-%d %H:%M UTC")
            print(f"[Signal4] Next scan at {close_time}")
            time.sleep(wait)
            run_scan()
        except Exception as e:
            print(f"[Signal4] Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run()