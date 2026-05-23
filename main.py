import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timezone

# ── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID   = "8118939134"

MARKET_CAP_MIN           = 1_000_000_000   # $1B
VOLUME_MULTIPLIER        = 2.0
EMA_FAST                 = 12
EMA_SLOW                 = 21
SCAN_INTERVAL            = 15 * 60

CVD_MIN_PRICE_CHANGE_PCT = 1.5
CVD_MIN_DELTA_RATIO      = 0.10

OI_MIN_CHANGE_PCT        = 2.0
OI_MIN_PRICE_CHANGE_PCT  = 1.5

COOLDOWN_SEC             = 3600
# ────────────────────────────────────────────────────────────────────────────

last_alerted = {}


def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"    Telegram error: {e}")


def is_on_cooldown(symbol):
    now = time.time()
    if symbol in last_alerted and now - last_alerted[symbol] < COOLDOWN_SEC:
        return True
    return False


def mark_alerted(symbol):
    last_alerted[symbol] = time.time()


def get_coins_above_market_cap():
    coins = []
    page  = 1
    while True:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order":       "market_cap_desc",
            "per_page":    250,
            "page":        page,
            "sparkline":   False,
        }
        try:
            r    = requests.get(url, params=params, timeout=30)
            data = r.json()
        except Exception as e:
            print(f"  CoinGecko request failed: {e}")
            break

        if not data or not isinstance(data, list):
            print(f"  CoinGecko unexpected response: {data}")
            time.sleep(10)
            break

        for coin in data:
            mc = coin.get("market_cap") or 0
            if mc < MARKET_CAP_MIN:
                break
            coins.append({
                "id":         coin["id"],
                "symbol":     coin["symbol"].upper(),
                "market_cap": mc,
            })

        if (data[-1].get("market_cap") or 0) < MARKET_CAP_MIN:
            break

        page += 1
        time.sleep(2.0)

    print(f"  -> {len(coins)} coins above $1B market cap")
    return coins


# ── DATA FETCHING ────────────────────────────────────────────────────────────

def get_ohlcv_binance_futures(symbol, interval="1h", limit=100):
    url    = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
    r      = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data or isinstance(data, dict):
        return None
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["close"]          = df["close"].astype(float)
    df["volume"]         = df["volume"].astype(float)
    df["taker_buy_base"] = df["taker_buy_base"].astype(float)
    return df


def get_ohlcv_binance_spot(symbol, interval="1h", limit=100):
    url    = "https://api.binance.com/api/v3/klines"
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
    r      = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data or isinstance(data, dict):
        return None
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    df["close"]          = df["close"].astype(float)
    df["volume"]         = df["volume"].astype(float)
    df["taker_buy_base"] = df["taker_buy_base"].astype(float)
    return df


def get_ohlcv_bybit(symbol, interval="60", limit=100):
    url    = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol":   f"{symbol}USDT",
        "interval": interval,
        "limit":    limit,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("retCode") != 0:
        return None
    rows = data.get("result", {}).get("list", [])
    if not rows:
        return None
    rows = rows[::-1]
    df = pd.DataFrame(rows, columns=[
        "time", "open", "high", "low", "close", "volume", "turnover"
    ])
    df["close"]          = df["close"].astype(float)
    df["volume"]         = df["volume"].astype(float)
    df["taker_buy_base"] = df["volume"] * 0.5
    return df


def get_ohlcv_okx(symbol, interval="1H", limit=100):
    url    = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": f"{symbol}-USDT-SWAP", "bar": interval, "limit": limit}
    r      = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("code") != "0" or not data.get("data"):
        return None
    rows = data["data"][::-1]
    df = pd.DataFrame(rows, columns=[
        "time", "open", "high", "low", "close",
        "volume", "quote_vol", "taker_buy_base", "taker_buy_quote",
    ])
    df["close"]          = df["close"].astype(float)
    df["volume"]         = df["volume"].astype(float)
    df["taker_buy_base"] = df["taker_buy_base"].astype(float)
    return df


def get_ohlcv(symbol):
    for fn, name in [
        (get_ohlcv_binance_futures, "binance_futures"),
        (get_ohlcv_binance_spot,    "binance_spot"),
        (get_ohlcv_bybit,           "bybit"),
        (get_ohlcv_okx,             "okx"),
    ]:
        try:
            df = fn(symbol)
            if df is not None and len(df) >= 30:
                return df, name
        except Exception:
            continue
    return None, None


def get_open_interest_binance(symbol):
    url    = "https://fapi.binance.com/futures/data/openInterestHist"
    params = {"symbol": f"{symbol}USDT", "period": "1h", "limit": 5}
    r      = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data or isinstance(data, dict):
        return None
    return [float(d["sumOpenInterest"]) for d in data]


# ── INDICATORS ───────────────────────────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_cvd(df):
    df = df.copy()
    df["delta"] = df["taker_buy_base"] - (df["volume"] - df["taker_buy_base"])
    df["cvd"]   = df["delta"].cumsum()
    return df


# ── SIGNAL 1: EMA CROSS + VOLUME ─────────────────────────────────────────────

def check_ema_signal(df):
    df = df.copy()
    df["ema_fast"] = calc_ema(df["close"], EMA_FAST)
    df["ema_slow"] = calc_ema(df["close"], EMA_SLOW)
    df["avg_vol"]  = df["volume"].rolling(20).mean()

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    bullish_cross = (prev["ema_fast"] <= prev["ema_slow"]) and (curr["ema_fast"] > curr["ema_slow"])
    bearish_cross = (prev["ema_fast"] >= prev["ema_slow"]) and (curr["ema_fast"] < curr["ema_slow"])
    vol_confirm   = curr["volume"] >= VOLUME_MULTIPLIER * curr["avg_vol"]
    vol_ratio     = curr["volume"] / curr["avg_vol"] if curr["avg_vol"] else 0

    if bullish_cross and vol_confirm:
        return "bullish", vol_ratio, curr["close"]
    if bearish_cross and vol_confirm:
        return "bearish", vol_ratio, curr["close"]
    return None, vol_ratio, curr["close"]


# ── SIGNAL 2: OI + PRICE ─────────────────────────────────────────────────────

def check_oi_signal(symbol, current_price, prev_price):
    oi_list = get_open_interest_binance(symbol)
    if not oi_list or len(oi_list) < 2:
        return None, None

    oi_change    = (oi_list[-1] - oi_list[-2]) / oi_list[-2] * 100
    price_change = (current_price - prev_price) / prev_price * 100

    if abs(oi_change) < OI_MIN_CHANGE_PCT:
        return None, None
    if abs(price_change) < OI_MIN_PRICE_CHANGE_PCT:
        return None, None

    if oi_change > 0 and price_change > 0:
        return "bullish", oi_change
    if oi_change > 0 and price_change < 0:
        return "bearish", oi_change
    return None, None


# ── SIGNAL 3: CVD DIVERGENCE ─────────────────────────────────────────────────

def check_cvd_signal(df):
    df     = calc_cvd(df)
    recent = df.iloc[-11:-1]

    start_price      = recent["close"].iloc[0]
    end_price        = recent["close"].iloc[-1]
    avg_vol          = recent["volume"].mean()
    price_change_pct = (end_price - start_price) / start_price * 100
    cvd_change       = recent["cvd"].iloc[-1] - recent["cvd"].iloc[0]
    cvd_ratio        = abs(cvd_change) / avg_vol if avg_vol else 0

    if abs(price_change_pct) < CVD_MIN_PRICE_CHANGE_PCT:
        return None, price_change_pct, cvd_change
    if cvd_ratio < CVD_MIN_DELTA_RATIO:
        return None, price_change_pct, cvd_change

    bullish_div = price_change_pct < 0 and cvd_change > 0
    bearish_div = price_change_pct > 0 and cvd_change < 0

    if bullish_div:
        return "bullish", price_change_pct, cvd_change
    if bearish_div:
        return "bearish", price_change_pct, cvd_change
    return None, price_change_pct, cvd_change


# ── SCAN ─────────────────────────────────────────────────────────────────────

def scan():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scanning market...")
    coins = get_coins_above_market_cap()

    ema_signals = []
    oi_signals  = []
    cvd_signals = []

    for coin in coins:
        symbol = coin["symbol"]
        try:
            df, market = get_ohlcv(symbol)
            if df is None:
                print(f"    {symbol} | Skipped — not found on any exchange")
                continue

            curr_price = float(df.iloc[-2]["close"])
            prev_price = float(df.iloc[-3]["close"])

            # Signal 1: EMA Cross
            ema_dir, vol_ratio, _ = check_ema_signal(df)
            print(f"    {symbol} [{market}] | EMA={ema_dir or 'none'} | Vol={vol_ratio:.2f}x")
            if ema_dir and not is_on_cooldown(symbol):
                ema_signals.append({
                    "symbol":     symbol,
                    "direction":  ema_dir,
                    "vol_ratio":  vol_ratio,
                    "price":      curr_price,
                    "market_cap": coin["market_cap"],
                    "market":     market,
                })
                mark_alerted(symbol)

            # Signal 2: OI + Price
            if "binance" in market or market == "bybit":
                if not is_on_cooldown(symbol):
                    oi_dir, oi_change = check_oi_signal(symbol, curr_price, prev_price)
                    if oi_dir:
                        oi_signals.append({
                            "symbol":     symbol,
                            "direction":  oi_dir,
                            "oi_change":  oi_change,
                            "price":      curr_price,
                            "market_cap": coin["market_cap"],
                        })
                        mark_alerted(symbol)

            # Signal 3: CVD Divergence
            if not is_on_cooldown(symbol):
                cvd_dir, price_chg, cvd_chg = check_cvd_signal(df)
                if cvd_dir:
                    cvd_signals.append({
                        "symbol":       symbol,
                        "direction":    cvd_dir,
                        "price_change": price_chg,
                        "cvd_change":   cvd_chg,
                        "price":        curr_price,
                        "market_cap":   coin["market_cap"],
                    })
                    mark_alerted(symbol)

        except Exception as e:
            print(f"    {symbol} | Error: {e}")

        time.sleep(0.15)

    print(f"\n  -> EMA: {len(ema_signals)} | OI: {len(oi_signals)} | CVD: {len(cvd_signals)}")

    # ── Send EMA Alerts ───────────────────────────────────────────────────────
    for s in ema_signals:
        emoji          = "🚀" if s["direction"] == "bullish" else "🔻"
        direction_text = (
            "EMA 12 crossed ABOVE EMA 21 (Bullish)"
            if s["direction"] == "bullish"
            else "EMA 12 crossed BELOW EMA 21 (Bearish)"
        )
        msg = (
            f"{emoji} *EMA CROSS SIGNAL*\n"
            f"────────────────────\n"
            f"📌 *{s['symbol']}*\n"
            f"💰 Price      : `${s['price']:,.4f}`\n"
            f"📊 Market Cap : `${s['market_cap']/1e9:.2f}B`\n"
            f"📈 {direction_text}\n"
            f"🔊 Volume     : `{s['vol_ratio']:.2f}x` average\n"
            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
        )
        send_telegram(msg)
        time.sleep(0.5)

    # ── Send OI Alerts ────────────────────────────────────────────────────────
    for s in oi_signals:
        emoji  = "📈" if s["direction"] == "bullish" else "📉"
        detail = (
            "Price UP + OI UP = Real buying pressure"
            if s["direction"] == "bullish"
            else "Price DOWN + OI UP = Real selling pressure"
        )
        msg = (
            f"{emoji} *OI MOMENTUM SIGNAL*\n"
            f"────────────────────\n"
            f"📌 *{s['symbol']}*\n"
            f"💰 Price      : `${s['price']:,.4f}`\n"
            f"📊 Market Cap : `${s['market_cap']/1e9:.2f}B`\n"
            f"💹 {detail}\n"
            f"📊 OI Change  : `{s['oi_change']:+.2f}%`\n"
            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
        )
        send_telegram(msg)
        time.sleep(0.5)

    # ── Send CVD Alerts ───────────────────────────────────────────────────────
    for s in cvd_signals:
        emoji  = "🔍" if s["direction"] == "bullish" else "⚠️"
        detail = (
            "CVD rising while price dipping = Hidden buying"
            if s["direction"] == "bullish"
            else "CVD falling while price rising = Hidden selling"
        )
        msg = (
            f"{emoji} *CVD DIVERGENCE SIGNAL*\n"
            f"────────────────────\n"
            f"📌 *{s['symbol']}*\n"
            f"💰 Price      : `${s['price']:,.4f}`\n"
            f"📊 Market Cap : `${s['market_cap']/1e9:.2f}B`\n"
            f"⚡ {detail}\n"
            f"📉 Price Change: `{s['price_change']:+.2f}%`\n"
            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
        )
        send_telegram(msg)
        time.sleep(0.5)

    if not ema_signals and not oi_signals and not cvd_signals:
        print("  No signals this scan.")


# ── MAIN LOOP ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    send_telegram(
        "🤖 *Scanner started!*\n"
        "────────────────────\n"
        "Running 3 signals:\n"
        "1️⃣ EMA 12/21 Cross + 2.0x Volume\n"
        "2️⃣ OI + Price Momentum (2% OI / 1.5% Price min)\n"
        "3️⃣ CVD Divergence (1.5% price / 10% delta min)\n"
        "🔕 1 hour cooldown per coin\n"
        "📊 Only coins above $1B market cap\n"
        "Scanning every 15 min 24/7"
    )

    while True:
        try:
            scan()
        except Exception as e:
            send_telegram(f"⚠️ Scanner error: `{e}`")
            print(f"Error: {e}")

        print(f"  Sleeping {SCAN_INTERVAL//60} min until next scan...")
        time.sleep(SCAN_INTERVAL)
