import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID   = "8118939134"

MARKET_CAP_MIN    = 500_000_000
VOLUME_MULTIPLIER = 1.5
EMA_FAST          = 12
EMA_SLOW          = 21
SCAN_INTERVAL     = 15 * 60
# ────────────────────────────────────────────────────────────────────────────


def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})


def get_coins_above_market_cap():
    coins = []
    page  = 1
    while True:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page, "sparkline": False}
        r    = requests.get(url, params=params, timeout=30)
        data = r.json()
        if not data:
            break
        for coin in data:
            mc = coin.get("market_cap") or 0
            if mc < MARKET_CAP_MIN:
                break
            coins.append({"id": coin["id"], "symbol": coin["symbol"].upper(), "market_cap": mc})
        if (data[-1].get("market_cap") or 0) < MARKET_CAP_MIN:
            break
        page += 1
        time.sleep(1.2)
    print(f"  -> {len(coins)} coins above $500M market cap")
    return coins


def get_ohlcv_binance_futures(symbol, interval="1h", limit=100):
    """Try Binance Futures first (covers more coins like HYPE)"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": f"{symbol}USDT",
        "interval": interval,
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data or isinstance(data, dict):
        return None
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_vol","trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df["close"]  = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df


def get_ohlcv_binance_spot(symbol, interval="1h", limit=100):
    """Fallback to Binance Spot"""
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": f"{symbol}USDT",
        "interval": interval,
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data or isinstance(data, dict):
        return None
    df = pd.DataFrame(data, columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_vol","trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df["close"]  = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df


def get_ohlcv(symbol):
    """Try futures first, fall back to spot"""
    df = get_ohlcv_binance_futures(symbol)
    if df is not None and len(df) >= 30:
        return df, "futures"
    df = get_ohlcv_binance_spot(symbol)
    if df is not None and len(df) >= 30:
        return df, "spot"
    return None, None


def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def check_signal(df, symbol, market):
    df = df.copy()
    df["ema_fast"] = calc_ema(df["close"], EMA_FAST)
    df["ema_slow"] = calc_ema(df["close"], EMA_SLOW)
    df["avg_vol"]  = df["volume"].rolling(20).mean()

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    ema_cross   = (prev["ema_fast"] <= prev["ema_slow"]) and (curr["ema_fast"] > curr["ema_slow"])
    vol_confirm = curr["volume"] >= VOLUME_MULTIPLIER * curr["avg_vol"]

    vol_ratio = curr["volume"] / curr["avg_vol"] if curr["avg_vol"] else 0
    print(f"    {symbol} [{market}] | EMA cross={ema_cross} | Vol={vol_ratio:.2f}x | {'✅ SIGNAL' if ema_cross and vol_confirm else '❌'}")

    return ema_cross and vol_confirm, curr


def scan():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scanning market...")
    coins   = get_coins_above_market_cap()
    signals = []

    for i, coin in enumerate(coins):
        symbol = coin["symbol"]
        try:
            df, market = get_ohlcv(symbol)
            if df is None:
                print(f"    {symbol} | Skipped — not on Binance futures or spot")
                continue
            triggered, last_candle = check_signal(df, symbol, market)
            if triggered:
                signals.append({
                    "symbol": symbol,
                    "market": market,
                    "market_cap": coin["market_cap"],
                    "close": last_candle["close"],
                    "volume": last_candle["volume"],
                    "avg_vol": last_candle["avg_vol"],
                })
        except Exception as e:
            print(f"    {symbol} | Error: {e}")
        time.sleep(0.1)

    print(f"\n  -> Found {len(signals)} signal(s)")

    if signals:
        for s in signals:
            vol_ratio = s["volume"] / s["avg_vol"]
            mc_b      = s["market_cap"] / 1e9
            msg = (
                f"🚀 *EMA CROSS ALERT*\n"
                f"────────────────────\n"
                f"📌 *{s['symbol']}* ({s['market']})\n"
                f"💰 Price       : `${s['close']:,.4f}`\n"
                f"📊 Market Cap  : `${mc_b:.2f}B`\n"
                f"📈 EMA 12 crossed above EMA 21 (1H)\n"
                f"🔊 Volume      : `{vol_ratio:.2f}x` average\n"
                f"⏰ Time (UTC)  : `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}`"
            )
            send_telegram(msg)
            time.sleep(0.5)
    else:
        print("  No signals this scan.")


# ── MAIN LOOP ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    send_telegram("🤖 *Scanner started!*\nWatching for EMA 12/21 cross + 1.5× volume on 1H")

    while True:
        try:
            scan()
        except Exception as e:
            send_telegram(f"⚠️ Scanner error: {e}")
            print(f"Error: {e}")

        print(f"  Sleeping {SCAN_INTERVAL//60} min until next scan...")
        time.sleep(SCAN_INTERVAL)
