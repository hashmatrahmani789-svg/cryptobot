import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN       = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID         = "8118939134"
COINALYZE_KEY   = "71b88a8f-d87d-4be6-bebe-8bc2c3053073"

MARKET_CAP_MIN  = 1_000_000_000
SCAN_INTERVAL   = 15 * 60

CD_1H           = 3600
CD_15M          = 900
CD_4H           = 14400

EMA_FAST        = 12
EMA_SLOW        = 21
EMA_TREND       = 50

VOL_ROLLING     = 20
VOL_MIN_RATIO   = 1.5

OI_SPIKE_PCT    = 2.0
OI_ACCEL_MIN    = 1.0
OI_ACCEL_STEP   = 0.3
OI_PERIODS      = 3

CVD_LOOKBACK    = 20
CVD_MIN_RATIO   = 0.25

FUNDING_EXTREME = 0.05
LS_EXTREME      = 0.70

cd = {
    "ema_cross_1h": {},
    "ema50_1h":     {},
    "ema50_15m":    {},
    "oi_spike":     {},
    "oi_accel":     {},
    "cvd":          {},
    "vol_1h":       {},
    "vol_15m":      {},
    "funding":      {},
    "longshort":    {},
}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"[S1] Telegram error: {e}")

def on_cooldown(symbol, store, seconds):
    return symbol in store and time.time() - store[symbol] < seconds

def mark(symbol, store):
    store[symbol] = time.time()

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

# ─── DATA FETCHERS ────────────────────────────────────────────────

def get_coins():
    coins = []
    page  = 1
    while True:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": 250, "page": page, "sparkline": False},
                timeout=30
            )
            r.encoding = "utf-8"
            data = r.json()
            if not data or not isinstance(data, list):
                break
            found_below = False
            for coin in data:
                mc = coin.get("market_cap") or 0
                if mc < MARKET_CAP_MIN:
                    found_below = True
                    continue
                sym = coin.get("symbol", "").upper()
                if sym:
                    coins.append({"symbol": sym, "market_cap": mc})
            if found_below:
                break
            page += 1
            time.sleep(2.0)
        except Exception as e:
            print(f"[S1] CoinGecko error: {e}")
            break
    return coins

def get_ohlcv(symbol, interval, limit=100):
    for url in [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api.binance.com/api/v3/klines",
    ]:
        try:
            r = requests.get(
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
            df["open"]           = df["open"].astype(float)
            df["high"]           = df["high"].astype(float)
            df["low"]            = df["low"].astype(float)
            df["close"]          = df["close"].astype(float)
            df["volume"]         = df["volume"].astype(float)
            df["taker_buy_base"] = df["taker_buy_base"].astype(float)
            if len(df) >= 55:
                return df
        except Exception:
            continue
    return None

def get_price(symbol):
    try:
        for url in [
            f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}USDT",
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT",
        ]:
            r = requests.get(url, timeout=10)
            data = r.json()
            if "price" in data:
                return float(data["price"])
    except Exception:
        pass
    return None

def cl_sym(symbol):
    return f"{symbol}USDT_PERP.A"

def get_oi_coinalyze(symbol, periods=6):
    try:
        r = requests.get(
            "https://api.coinalyze.net/v1/open-interest-history",
            params={
                "symbols":  cl_sym(symbol),
                "interval": "1hour",
                "limit":    periods,
                "api_key":  COINALYZE_KEY
            },
            timeout=10
        )
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        history = data[0].get("history", [])
        if len(history) < 4:
            return None
        return [float(h["o"]) for h in history]
    except Exception as e:
        print(f"[S1] Coinalyze OI error {symbol}: {e}")
        return None

def get_funding_coinalyze(symbol):
    try:
        r = requests.get(
            "https://api.coinalyze.net/v1/funding-rate",
            params={
                "symbols": cl_sym(symbol),
                "api_key": COINALYZE_KEY
            },
            timeout=10
        )
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        val = data[0].get("value")
        if val is None:
            return None
        return float(val)
    except Exception as e:
        print(f"[S1] Coinalyze Funding error {symbol}: {e}")
        return None

def get_longshort_coinalyze(symbol):
    try:
        r = requests.get(
            "https://api.coinalyze.net/v1/long-short-ratio-history",
            params={
                "symbols":  cl_sym(symbol),
                "interval": "1hour",
                "limit":    1,
                "api_key":  COINALYZE_KEY
            },
            timeout=10
        )
        data = r.json()
        if not data or not isinstance(data, list):
            return None, None
        history = data[0].get("history", [])
        if not history:
            return None, None
        long_pct  = float(history[-1].get("l", 0))
        short_pct = float(history[-1].get("s", 0))
        return long_pct, short_pct
    except Exception as e:
        print(f"[S1] Coinalyze L/S error {symbol}: {e}")
        return None, None

# ─── SIGNAL CHECKS ────────────────────────────────────────────────

def check_ema_cross_1h(symbol, coin, df):
    if on_cooldown(symbol, cd["ema_cross_1h"], CD_1H):
        return
    df = df.copy()
    df["ema12"]   = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema21"]   = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["avg_vol"] = df["volume"].rolling(VOL_ROLLING).mean()
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    bullish = prev["ema12"] <= prev["ema21"] and curr["ema12"] > curr["ema21"]
    bearish = prev["ema12"] >= prev["ema21"] and curr["ema12"] < curr["ema21"]
    if not bullish and not bearish:
        return
    vol_ratio = curr["volume"] / curr["avg_vol"] if curr["avg_vol"] else 0
    if vol_ratio < VOL_MIN_RATIO:
        print(f"[S1] EMA_CROSS_1H {symbol} — cross but low vol {vol_ratio:.2f}x")
        return
    price = curr["close"]
    emoji = "🟢" if bullish else "🔴"
    txt   = "EMA12 crossed ABOVE EMA21" if bullish else "EMA12 crossed BELOW EMA21"
    bias  = "Bullish momentum" if bullish else "Bearish momentum"
    send_telegram(
        f"{emoji} *1H EMA 12/21 CROSS*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"📈 {txt}\n"
        f"🔊 Volume     : `{vol_ratio:.2f}x` avg\n"
        f"💡 {bias}\n"
        f"⏰ `{now_utc()} UTC`"
    )
    mark(symbol, cd["ema_cross_1h"])
    print(f"[S1] EMA CROSS 1H {'BULL' if bullish else 'BEAR'} — {symbol}")

def check_ema50_reject(symbol, coin, df, tf):
    store_key = "ema50_1h" if tf == "1h" else "ema50_15m"
    cooldown  = CD_1H if tf == "1h" else CD_15M
    if on_cooldown(symbol, cd[store_key], cooldown):
        return
    df = df.copy()
    df["ema50"]   = df["close"].ewm(span=EMA_TREND, adjust=False).mean()
    df["avg_vol"] = df["volume"].rolling(VOL_ROLLING).mean()
    c1    = df.iloc[-3]
    c0    = df.iloc[-2]
    ema1  = c1["ema50"]
    ema0  = c0["ema50"]
    vol_ratio = c0["volume"] / c0["avg_vol"] if c0["avg_vol"] else 0
    if vol_ratio < VOL_MIN_RATIO:
        return
    alert_type = None
    direction  = None
    if c0["low"] < ema0 and c0["close"] > ema0:
        alert_type, direction = "Wick Reject", "bullish"
    elif c0["high"] > ema0 and c0["close"] < ema0:
        alert_type, direction = "Wick Reject", "bearish"
    elif c1["close"] < ema1 and c0["close"] > ema0:
        alert_type, direction = "Close Reject", "bullish"
    elif c1["close"] > ema1 and c0["close"] < ema0:
        alert_type, direction = "Close Reject", "bearish"
    if not alert_type:
        return
    price    = c0["close"]
    emoji    = "🔵" if direction == "bullish" else "🟠"
    tf_label = "1H" if tf == "1h" else "15m"
    if direction == "bullish":
        what    = "Wicked BELOW EMA50 — closed ABOVE" if alert_type == "Wick Reject" else "Closed below EMA50 — reclaimed ABOVE"
        meaning = "EMA50 support held ✅"
    else:
        what    = "Wicked ABOVE EMA50 — closed BELOW" if alert_type == "Wick Reject" else "Closed above EMA50 — rejected BELOW"
        meaning = "EMA50 resistance held ⚠️"
    send_telegram(
        f"{emoji} *{tf_label} EMA50 {alert_type.upper()} — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"⚡ {what}\n"
        f"📊 EMA50      : `{ema0:,.4f}`\n"
        f"🔊 Volume     : `{vol_ratio:.2f}x` avg\n"
        f"💡 {meaning}\n"
        f"⏰ `{now_utc()} UTC`"
    )
    mark(symbol, cd[store_key])
    print(f"[S1] EMA50 {tf_label} {alert_type} {'BULL' if direction == 'bullish' else 'BEAR'} — {symbol}")

def check_oi(symbol, coin):
    oi_list = get_oi_coinalyze(symbol, periods=6)
    if not oi_list or len(oi_list) < 4:
        return
    price = get_price(symbol)
    if price is None:
        return
    if not on_cooldown(symbol, cd["oi_spike"], CD_1H):
        prev   = oi_list[-2]
        curr   = oi_list[-1]
        if prev > 0:
            change = (curr - prev) / prev * 100
            if abs(change) >= OI_SPIKE_PCT:
                direction = "bullish" if change > 0 else "bearish"
                emoji     = "🔥📈" if direction == "bullish" else "🔥📉"
                move_txt  = "OI SURGING — Longs being built 🟢" if direction == "bullish" else "OI DROPPING — Shorts or closing 🔴"
                send_telegram(
                    f"{emoji} *OI SPIKE — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
                    f"────────────────────\n"
                    f"📌 *{symbol}*\n"
                    f"💰 Price      : `${price:,.4f}`\n"
                    f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
                    f"────────────────────\n"
                    f"📊 OI Change  : `{change:+.2f}%` (all exchanges)\n"
                    f"💡 {move_txt}\n"
                    f"⏰ `{now_utc()} UTC`"
                )
                mark(symbol, cd["oi_spike"])
                print(f"[S1] OI SPIKE — {symbol} {change:+.2f}%")
    if not on_cooldown(symbol, cd["oi_accel"], CD_1H):
        changes = []
        for i in range(1, len(oi_list)):
            p = oi_list[i-1]
            c = oi_list[i]
            if p == 0:
                break
            changes.append((c - p) / p * 100)
        recent = changes[-OI_PERIODS:]
        if (len(recent) == OI_PERIODS and
            all(c > 0 for c in recent) and
            all(c >= OI_ACCEL_MIN for c in recent) and
            all(recent[i] >= recent[i-1] + OI_ACCEL_STEP for i in range(1, len(recent)))):
            periods_txt = "\n".join([f"📊 Period {i+1}     : `{c:+.2f}%`" for i, c in enumerate(recent)])
            send_telegram(
                f"🚀 *OI ACCELERATION*\n"
                f"────────────────────\n"
                f"📌 *{symbol}*\n"
                f"💰 Price      : `${price:,.4f}`\n"
                f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
                f"────────────────────\n"
                f"📈 OI growing faster each period:\n"
                f"{periods_txt}\n"
                f"💡 Big move loading\n"
                f"⏰ `{now_utc()} UTC`"
            )
            mark(symbol, cd["oi_accel"])
            print(f"[S1] OI ACCEL — {symbol}")

def check_cvd(symbol, coin, df):
    if on_cooldown(symbol, cd["cvd"], CD_1H):
        return
    df = df.copy()
    df["delta"] = df["taker_buy_base"] - (df["volume"] - df["taker_buy_base"])
    df["cvd"]   = df["delta"].cumsum()
    recent      = df.iloc[-(CVD_LOOKBACK + 1):-1]
    start_price = recent["close"].iloc[0]
    end_price   = recent["close"].iloc[-1]
    avg_vol     = recent["volume"].mean()
    cvd_start   = recent["cvd"].iloc[0]
    cvd_end     = recent["cvd"].iloc[-1]
    cvd_change  = cvd_end - cvd_start
    cvd_ratio   = abs(cvd_change) / avg_vol if avg_vol else 0
    if cvd_ratio < CVD_MIN_RATIO:
        return
    mid        = len(recent) // 2
    cvd_first  = recent["cvd"].iloc[:mid].mean()
    cvd_second = recent["cvd"].iloc[mid:].mean()
    price_down = end_price < start_price
    price_up   = end_price > start_price
    price_chg  = (end_price - start_price) / start_price * 100
    direction  = None
    if price_down and cvd_change > 0 and cvd_second > cvd_first:
        direction = "bullish"
    elif price_up and cvd_change < 0 and cvd_second < cvd_first:
        direction = "bearish"
    if not direction:
        return
    price   = float(df.iloc[-2]["close"])
    emoji   = "🔍" if direction == "bullish" else "⚠️"
    detail  = "Price DOWN but CVD UP" if direction == "bullish" else "Price UP but CVD DOWN"
    meaning = "Smart money accumulating 🟢" if direction == "bullish" else "Smart money distributing 🔴"
    send_telegram(
        f"{emoji} *CVD DIVERGENCE — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"⚡ {detail}\n"
        f"🌊 CVD Change : `{cvd_change:+.0f}`\n"
        f"⚖️ CVD Ratio  : `{cvd_ratio:.2f}`\n"
        f"📈 Price Chg  : `{price_chg:+.2f}%`\n"
        f"💡 {meaning}\n"
        f"⏰ `{now_utc()} UTC`"
    )
    mark(symbol, cd["cvd"])
    print(f"[S1] CVD {'BULL' if direction == 'bullish' else 'BEAR'} — {symbol}")

def check_volume(symbol, coin, df_1h, df_15m):
    for df, store_key, cd_time, label in [
        (df_1h,  "vol_1h",  CD_1H,  "1H"),
        (df_15m, "vol_15m", CD_15M, "15m"),
    ]:
        if df is None or on_cooldown(symbol, cd[store_key], cd_time):
            continue
        d         = df.copy()
        d["avg"]  = d["volume"].rolling(VOL_ROLLING).mean()
        curr      = d.iloc[-2]
        vol_ratio = curr["volume"] / curr["avg"] if curr["avg"] else 0
        if vol_ratio >= VOL_MIN_RATIO * 1.5:
            price = curr["close"]
            send_telegram(
                f"🔊 *VOLUME SPIKE {label}*\n"
                f"────────────────────\n"
                f"📌 *{symbol}*\n"
                f"💰 Price      : `${price:,.4f}`\n"
                f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
                f"────────────────────\n"
                f"📊 Volume     : `{vol_ratio:.2f}x` avg\n"
                f"💡 Unusual volume — watch for breakout\n"
                f"⏰ `{now_utc()} UTC`"
            )
            mark(symbol, cd[store_key])
            print(f"[S1] VOL SPIKE {label} — {symbol} {vol_ratio:.2f}x")

def check_funding(symbol, coin):
    if on_cooldown(symbol, cd["funding"], CD_4H):
        return
    funding = get_funding_coinalyze(symbol)
    if funding is None or abs(funding) < FUNDING_EXTREME:
        return
    price = get_price(symbol)
    if price is None:
        return
    if funding > 0:
        emoji, meaning, direction = "⚠️", "Funding HIGH — long squeeze risk 🔴", "bearish"
    else:
        emoji, meaning, direction = "💡", "Funding NEGATIVE — short squeeze likely 🟢", "bullish"
    send_telegram(
        f"{emoji} *FUNDING EXTREME — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
        f"────────────────────\n"
        f"📊 Funding    : `{funding*100:+.4f}%` (all exchanges)\n"
        f"💡 {meaning}\n"
        f"⏰ `{now_utc()} UTC`"
    )
    mark(symbol, cd["funding"])
    print(f"[S1] FUNDING — {symbol} {funding*100:+.4f}%")

def check_longshort(symbol, coin):
    if on_cooldown(symbol, cd["longshort"], CD_1H):
        return
    long_pct, short_pct = get_longshort_coinalyze(symbol)
    if long_pct is None:
        return
    price = get_price(symbol)
    if price is None:
        return
    if long_pct >= LS_EXTREME:
        send_telegram(
            f"🐂 *CROWDED LONGS — SQUEEZE RISK*\n"
            f"────────────────────\n"
            f"📌 *{symbol}*\n"
            f"💰 Price      : `${price:,.4f}`\n"
            f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
            f"────────────────────\n"
            f"📊 Longs      : `{long_pct*100:.1f}%`\n"
            f"📊 Shorts     : `{short_pct*100:.1f}%`\n"
            f"💡 Retail heavily long — squeeze risk ⚠️\n"
            f"⏰ `{now_utc()} UTC`"
        )
        mark(symbol, cd["longshort"])
        print(f"[S1] CROWDED LONGS — {symbol}")
    elif short_pct >= LS_EXTREME:
        send_telegram(
            f"🐻 *CROWDED SHORTS — SQUEEZE INCOMING*\n"
            f"────────────────────\n"
            f"📌 *{symbol}*\n"
            f"💰 Price      : `${price:,.4f}`\n"
            f"📊 MC         : `${coin['market_cap']/1e9:.2f}B`\n"
            f"────────────────────\n"
            f"📊 Longs      : `{long_pct*100:.1f}%`\n"
            f"📊 Shorts     : `{short_pct*100:.1f}%`\n"
            f"💡 Retail heavily short — squeeze likely 🟢\n"
            f"⏰ `{now_utc()} UTC`"
        )
        mark(symbol, cd["longshort"])
        print(f"[S1] CROWDED SHORTS — {symbol}")

# ─── MAIN ─────────────────────────────────────────────────────────

def run():
    send_telegram(
        "1️⃣ *Service 1 Started* ✅\n"
        "────────────────────\n"
        "1. 1H EMA 12/21 Cross + Volume\n"
        "2. 1H EMA50 Wick/Close Reject + Volume\n"
        "3. 15m EMA50 Wick/Close Reject + Volume\n"
        "4. 1H OI Spike + Acceleration (Coinalyze)\n"
        "5. 1H CVD Divergence\n"
        "6. 1H + 15m Volume Spike\n"
        "7. Funding Rate Extreme (Coinalyze)\n"
        "8. Long/Short Ratio Extreme (Coinalyze)\n"
        "────────────────────\n"
        "💰 MC > $1B | Scan every 15 min"
    )
    while True:
        try:
            print(f"\n[S1] Scanning... {now_utc()} UTC")
            coins = get_coins()
            print(f"[S1] {len(coins)} coins loaded")
            for coin in coins:
                symbol = coin["symbol"]
                try:
                    df_1h  = get_ohlcv(symbol, "1h",  limit=100)
                    df_15m = get_ohlcv(symbol, "15m", limit=100)
                    if df_1h is not None:
                        check_ema_cross_1h(symbol, coin, df_1h)
                        check_ema50_reject(symbol, coin, df_1h, "1h")
                        check_cvd(symbol, coin, df_1h)
                    check_volume(symbol, coin, df_1h, df_15m)
                    if df_15m is not None:
                        check_ema50_reject(symbol, coin, df_15m, "15m")
                    check_oi(symbol, coin)
                    check_funding(symbol, coin)
                    check_longshort(symbol, coin)
                except Exception as e:
                    print(f"[S1] {symbol} error: {e}")
                time.sleep(0.5)
            print(f"[S1] Scan complete.")
        except Exception as e:
            print(f"[S1] Scan error: {e}")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()