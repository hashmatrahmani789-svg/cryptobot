import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"

MARKET_CAP_MIN = 1_000_000_000

EMA_FAST       = 12
EMA_SLOW       = 21
EMA_TREND      = 50

COOLDOWN_DAILY = 86400       # 24h
COOLDOWN_4H    = 14400       # 4h
COOLDOWN_1H    = 3600        # 1h

last_alerted = {
    "daily_cross": {},
    "4h_cross":    {},
    "4h_reject":   {},
    "1h_reject":   {},
}

# ─────────────────────────────────────────
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def is_on_cooldown(symbol, store, seconds):
    return symbol in store and time.time() - store[symbol] < seconds

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

def get_ohlcv(symbol, interval, limit=100):
    for url in [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api.binance.com/api/v3/klines",
    ]:
        try:
            r    = requests.get(
                url,
                params={"symbol": f"{symbol}USDT", "interval": interval, "limit": limit},
                timeout=10
            )
            data = r.json()
            if not data or isinstance(data, dict):
                continue
            df = pd.DataFrame(data, columns=[
                "time","open","high","low","close","volume",
                "close_time","quote_vol","trades",
                "taker_buy_base","taker_buy_quote","ignore"
            ])
            df["open"]  = df["open"].astype(float)
            df["high"]  = df["high"].astype(float)
            df["low"]   = df["low"].astype(float)
            df["close"] = df["close"].astype(float)
            if len(df) >= 55:
                return df
        except Exception:
            continue
    return None

# ─────────────────────────────────────────
# ALERT 1 — Daily EMA 12/21 Cross
# ─────────────────────────────────────────
def check_daily_cross(symbol, coin):
    if is_on_cooldown(symbol, last_alerted["daily_cross"], COOLDOWN_DAILY):
        return

    df = get_ohlcv(symbol, "1d", limit=100)
    if df is None:
        return

    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    # Use confirmed closed candles [-3] and [-2], ignore [-1] (live)
    prev = df.iloc[-3]
    curr = df.iloc[-2]

    bullish = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    bearish = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]

    if not bullish and not bearish:
        return

    price   = curr["close"]
    emoji   = "🟢" if bullish else "🔴"
    txt     = "EMA12 crossed ABOVE EMA21 — Bullish" if bullish else "EMA12 crossed BELOW EMA21 — Bearish"
    bias    = "Bullish momentum building ✅" if bullish else "Bearish momentum building ⚠️"

    send_telegram(
        f"{emoji} *DAILY EMA 12/21 CROSS*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price       : `${price:,.4f}`\n"
        f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"📈 {txt}\n"
        f"📊 EMA12 : `{curr['ema_fast']:,.4f}`\n"
        f"📊 EMA21 : `{curr['ema_slow']:,.4f}`\n"
        f"────────────────────\n"
        f"💡 {bias}\n"
        f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
    )
    mark_alerted(symbol, last_alerted["daily_cross"])
    print(f"[Signal4] DAILY CROSS {'BULL' if bullish else 'BEAR'} — {symbol}")
    time.sleep(0.5)

# ─────────────────────────────────────────
# ALERT 2 — 4H EMA 12/21 Cross
# ─────────────────────────────────────────
def check_4h_cross(symbol, coin):
    if is_on_cooldown(symbol, last_alerted["4h_cross"], COOLDOWN_4H):
        return

    df = get_ohlcv(symbol, "4h", limit=100)
    if df is None:
        return

    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    bullish = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    bearish = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]

    if not bullish and not bearish:
        return

    price = curr["close"]
    emoji = "🟢" if bullish else "🔴"
    txt   = "EMA12 crossed ABOVE EMA21 — Bullish" if bullish else "EMA12 crossed BELOW EMA21 — Bearish"
    bias  = "4H momentum shifting UP ✅" if bullish else "4H momentum shifting DOWN ⚠️"

    send_telegram(
        f"{emoji} *4H EMA 12/21 CROSS*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price       : `${price:,.4f}`\n"
        f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"📈 {txt}\n"
        f"📊 EMA12 : `{curr['ema_fast']:,.4f}`\n"
        f"📊 EMA21 : `{curr['ema_slow']:,.4f}`\n"
        f"────────────────────\n"
        f"💡 {bias}\n"
        f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
    )
    mark_alerted(symbol, last_alerted["4h_cross"])
    print(f"[Signal4] 4H CROSS {'BULL' if bullish else 'BEAR'} — {symbol}")
    time.sleep(0.5)

# ─────────────────────────────────────────
# ALERT 3 — 4H EMA50 Cross & Reject
# ─────────────────────────────────────────
def check_4h_ema50_reject(symbol, coin):
    if is_on_cooldown(symbol, last_alerted["4h_reject"], COOLDOWN_4H):
        return

    df = get_ohlcv(symbol, "4h", limit=100)
    if df is None:
        return

    df["ema50"] = df["close"].ewm(span=EMA_TREND, adjust=False).mean()

    # Confirmed candles: [-4], [-3], [-2] — ignore [-1] live
    c2 = df.iloc[-4]   # two candles ago
    c1 = df.iloc[-3]   # previous candle
    c0 = df.iloc[-2]   # last confirmed candle

    ema2 = c2["ema50"]
    ema1 = c1["ema50"]
    ema0 = c0["ema50"]

    alert_type = None
    direction  = None

    # ── Wick Reject ──────────────────────────
    # Bullish wick reject: low wicks below EMA50 but close stays above
    if c0["low"] < ema0 and c0["close"] > ema0:
        alert_type = "wick"
        direction  = "bullish"

    # Bearish wick reject: high wicks above EMA50 but close stays below
    elif c0["high"] > ema0 and c0["close"] < ema0:
        alert_type = "wick"
        direction  = "bearish"

    # ── Close Reject ─────────────────────────
    # Bullish close reject: c1 closed below EMA50, c0 closed back above
    elif c1["close"] < ema1 and c0["close"] > ema0:
        alert_type = "close"
        direction  = "bullish"

    # Bearish close reject: c1 closed above EMA50, c0 closed back below
    elif c1["close"] > ema1 and c0["close"] < ema0:
        alert_type = "close"
        direction  = "bearish"

    if not alert_type:
        return

    price      = c0["close"]
    emoji      = "🔵" if direction == "bullish" else "🟠"
    reject_txt = "Wick Reject" if alert_type == "wick" else "Close Reject"

    if direction == "bullish":
        what   = "Price wicked BELOW EMA50 but closed ABOVE" if alert_type == "wick" \
                 else "Price closed below EMA50 then reclaimed ABOVE"
        meaning = "EMA50 held as support — bounce likely ✅"
    else:
        what   = "Price wicked ABOVE EMA50 but closed BELOW" if alert_type == "wick" \
                 else "Price closed above EMA50 then rejected BELOW"
        meaning = "EMA50 acted as resistance — drop likely ⚠️"

    send_telegram(
        f"{emoji} *4H EMA50 {reject_txt.upper()} — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price       : `${price:,.4f}`\n"
        f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"📊 Type        : `{reject_txt}`\n"
        f"⚡ {what}\n"
        f"📊 EMA50       : `{ema0:,.4f}`\n"
        f"────────────────────\n"
        f"💡 {meaning}\n"
        f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
    )
    mark_alerted(symbol, last_alerted["4h_reject"])
    print(f"[Signal4] 4H EMA50 {reject_txt.upper()} {'BULL' if direction == 'bullish' else 'BEAR'} — {symbol}")
    time.sleep(0.5)

# ─────────────────────────────────────────
# ALERT 4 — 1H EMA50 Cross & Reject
# ─────────────────────────────────────────
def check_1h_ema50_reject(symbol, coin):
    if is_on_cooldown(symbol, last_alerted["1h_reject"], COOLDOWN_1H):
        return

    df = get_ohlcv(symbol, "1h", limit=100)
    if df is None:
        return

    df["ema50"] = df["close"].ewm(span=EMA_TREND, adjust=False).mean()

    c2 = df.iloc[-4]
    c1 = df.iloc[-3]
    c0 = df.iloc[-2]

    ema2 = c2["ema50"]
    ema1 = c1["ema50"]
    ema0 = c0["ema50"]

    alert_type = None
    direction  = None

    # ── Wick Reject ──────────────────────────
    if c0["low"] < ema0 and c0["close"] > ema0:
        alert_type = "wick"
        direction  = "bullish"

    elif c0["high"] > ema0 and c0["close"] < ema0:
        alert_type = "wick"
        direction  = "bearish"

    # ── Close Reject ─────────────────────────
    elif c1["close"] < ema1 and c0["close"] > ema0:
        alert_type = "close"
        direction  = "bullish"

    elif c1["close"] > ema1 and c0["close"] < ema0:
        alert_type = "close"
        direction  = "bearish"

    if not alert_type:
        return

    price      = c0["close"]
    emoji      = "🔵" if direction == "bullish" else "🟠"
    reject_txt = "Wick Reject" if alert_type == "wick" else "Close Reject"

    if direction == "bullish":
        what    = "Price wicked BELOW EMA50 but closed ABOVE" if alert_type == "wick" \
                  else "Price closed below EMA50 then reclaimed ABOVE"
        meaning = "EMA50 held as support — bounce likely ✅"
    else:
        what    = "Price wicked ABOVE EMA50 but closed BELOW" if alert_type == "wick" \
                  else "Price closed above EMA50 then rejected BELOW"
        meaning = "EMA50 acted as resistance — drop likely ⚠️"

    send_telegram(
        f"{emoji} *1H EMA50 {reject_txt.upper()} — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price       : `${price:,.4f}`\n"
        f"📊 Market Cap  : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"📊 Type        : `{reject_txt}`\n"
        f"⚡ {what}\n"
        f"📊 EMA50       : `{ema0:,.4f}`\n"
        f"────────────────────\n"
        f"💡 {meaning}\n"
        f"⏰ Time (UTC)  : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
    )
    mark_alerted(symbol, last_alerted["1h_reject"])
    print(f"[Signal4] 1H EMA50 {reject_txt.upper()} {'BULL' if direction == 'bullish' else 'BEAR'} — {symbol}")
    time.sleep(0.5)

# ─────────────────────────────────────────
def run_scan():
    print(f"\n[Signal4] Scanning... {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    coins = get_coins()
    print(f"[Signal4] {len(coins)} coins loaded")

    for coin in coins:
        symbol = coin["symbol"]
        try:
            check_daily_cross(symbol, coin)
            check_4h_cross(symbol, coin)
            check_4h_ema50_reject(symbol, coin)
            check_1h_ema50_reject(symbol, coin)
        except Exception as e:
            print(f"[Signal4] {symbol} error: {e}")
        time.sleep(0.3)

    print(f"[Signal4] Scan complete.")

# ─────────────────────────────────────────
def run():
    send_telegram(
        "4️⃣ *Signal 4 Started* ✅\n"
        "────────────────────\n"
        "🟢 *Alert 1* : Daily EMA 12/21 Cross\n"
        "🟢 *Alert 2* : 4H EMA 12/21 Cross\n"
        "🔵 *Alert 3* : 4H EMA50 Wick & Close Reject\n"
        "🔵 *Alert 4* : 1H EMA50 Wick & Close Reject\n"
        "💰 *MC Filter* : > $1B\n"
        "🔄 *Scan every* : 15 min"
    )

    # Startup delay — let other signals stabilize first
    print("[Signal4] Waiting 10 min before first scan...")
    time.sleep(600)

    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"[Signal4] Scan error: {e}")
        time.sleep(15 * 60)

if __name__ == "__main__":
    run()