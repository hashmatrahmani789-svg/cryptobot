import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID   = "8118939134"

MARKET_CAP_MIN    = 1_000_000_000

# 15m settings
EMA_FAST_15       = 9
EMA_SLOW_15       = 21
VOL_MULTIPLIER_15 = 1.5      # Type 1: 1.5x rolling average
VOL_SPIKE_15      = 1.8      # Type 2: 1.8x previous candle

# 1H settings
EMA_FAST_1H       = 12
EMA_SLOW_1H       = 21
VOL_MULTIPLIER_1H = 1.5      # lowered from 2.0
VOL_ROLLING_1H    = 20

SCAN_INTERVAL     = 15 * 60
COOLDOWN_SEC      = 3600

last_alerted = {}

# ─────────────────────────────────────────
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
def get_ohlcv(symbol, interval, limit=100):
    for url in [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api.binance.com/api/v3/klines",
    ]:
        try:
            r    = requests.get(url, params={"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}, timeout=10)
            data = r.json()
            if not data or isinstance(data, dict):
                continue
            df = pd.DataFrame(data, columns=["time","open","high","low","close","volume",
                                              "close_time","quote_vol","trades",
                                              "taker_buy_base","taker_buy_quote","ignore"])
            df["close"]  = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            if len(df) >= 30:
                return df
        except Exception:
            continue
    return None

# ─────────────────────────────────────────
def check_15m(df):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST_15, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW_15, adjust=False).mean()
    df["avg_vol"]  = df["volume"].rolling(20).mean()

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    bullish = (prev["ema_fast"] <= prev["ema_slow"]) and (curr["ema_fast"] > curr["ema_slow"])
    bearish = (prev["ema_fast"] >= prev["ema_slow"]) and (curr["ema_fast"] < curr["ema_slow"])

    # Type 1 — above rolling average
    vol_type1 = curr["volume"] >= VOL_MULTIPLIER_15 * curr["avg_vol"]

    # Type 2 — spike vs previous candle
    prev_vol  = df["volume"].iloc[-3]
    vol_type2 = (curr["volume"] / prev_vol >= VOL_SPIKE_15) if prev_vol > 0 else False

    # OR instead of AND — either condition passes
    vol_ok    = vol_type1 or vol_type2
    vol_ratio = curr["volume"] / curr["avg_vol"] if curr["avg_vol"] else 0

    if bullish and vol_ok:
        return "bullish", vol_ratio, curr["close"]
    if bearish and vol_ok:
        return "bearish", vol_ratio, curr["close"]
    return None, vol_ratio, curr["close"]

# ─────────────────────────────────────────
def check_1h_confirmation(df_1h, direction):
    df = df_1h.copy()
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST_1H, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW_1H, adjust=False).mean()
    df["avg_vol"]  = df["volume"].rolling(VOL_ROLLING_1H).mean()

    curr = df.iloc[-2]

    # 1H EMA trend must match 15m signal direction
    trend_ok     = (curr["ema_fast"] > curr["ema_slow"]) if direction == "bullish" \
                   else (curr["ema_fast"] < curr["ema_slow"])

    # 1H volume — lowered to 1.5x
    vol_1h_ok    = curr["volume"] >= VOL_MULTIPLIER_1H * curr["avg_vol"]
    vol_1h_ratio = curr["volume"] / curr["avg_vol"] if curr["avg_vol"] else 0

    return trend_ok, vol_1h_ok, vol_1h_ratio

# ─────────────────────────────────────────
def run():
    send_telegram(
        "1️⃣ *1H EMA & VOL Started* ✅\n"
        "────────────────────\n"
        "⏱ *Entry* : 15m EMA 9/21 Cross\n"
        "✅ *Filter* : 1H EMA 12/21 Trend + Volume\n"
        "🔊 *Volume*: Type1 (1.5x avg) OR Type2 (1.8x prev candle) on 15m\n"
        "📊 *1H Vol* : 1.5x rolling 20 average\n"
        "💰 *MC Filter* : > $1B\n"
        "🔄 *Scan every* : 15 min"
    )

    while True:
        try:
            print(f"\n[1H_EMA_VOL] Scanning...")
            coins = get_coins()

            for coin in coins:
                symbol = coin["symbol"]
                try:
                    df_15m = get_ohlcv(symbol, "15m", limit=100)
                    if df_15m is None:
                        continue

                    df_1h = get_ohlcv(symbol, "1h", limit=100)
                    if df_1h is None:
                        continue

                    direction, vol_ratio_15m, price = check_15m(df_15m)
                    if not direction:
                        continue

                    if is_on_cooldown(symbol):
                        continue

                    trend_ok, vol_1h_ok, vol_1h_ratio = check_1h_confirmation(df_1h, direction)

                    print(f"[1H_EMA_VOL] {symbol} | 15m={direction} vol={vol_ratio_15m:.2f}x | 1H trend={trend_ok} vol={vol_1h_ok} ({vol_1h_ratio:.2f}x)")

                    if not trend_ok:
                        print(f"[1H_EMA_VOL] {symbol} SKIPPED — 1H trend not aligned")
                        continue

                    if not vol_1h_ok:
                        print(f"[1H_EMA_VOL] {symbol} SKIPPED — 1H volume not confirmed")
                        continue

                    emoji     = "🚀" if direction == "bullish" else "🔻"
                    cross_txt = "EMA9 crossed ABOVE EMA21 (15m)" if direction == "bullish" \
                                else "EMA9 crossed BELOW EMA21 (15m)"
                    trend_txt = "1H EMA12 > EMA21 ✅ Bullish" if direction == "bullish" \
                                else "1H EMA12 < EMA21 ✅ Bearish"

                    send_telegram(
                        f"{emoji} *EMA CROSS SIGNAL — CONFIRMED*\n"
                        f"────────────────────\n"
                        f"📌 *{symbol}*\n"
                        f"💰 Price        : `${price:,.4f}`\n"
                        f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                        f"────────────────────\n"
                        f"⏱ *15m Signal*\n"
                        f"📈 {cross_txt}\n"
                        f"🔊 Volume       : `{vol_ratio_15m:.2f}x` avg (15m)\n"
                        f"────────────────────\n"
                        f"🕐 *1H Confirmation*\n"
                        f"📉 Trend        : {trend_txt}\n"
                        f"🔊 1H Volume    : `{vol_1h_ratio:.2f}x` avg (1H)\n"
                        f"────────────────────\n"
                        f"⏰ Time (UTC)   : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                    )
                    mark_alerted(symbol)
                    time.sleep(0.5)

                except Exception as e:
                    print(f"[1H_EMA_VOL] {symbol} error: {e}")
                time.sleep(0.15)

        except Exception as e:
            print(f"[1H_EMA_VOL] Scan error: {e}")

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()