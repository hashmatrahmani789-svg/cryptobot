import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID   = "8118939134"

MARKET_CAP_MIN    = 1_000_000_000
VOLUME_MULTIPLIER = 1.2          # was 2.0 — loosened
EMA_FAST          = 12
EMA_SLOW          = 21
SCAN_INTERVAL     = 15 * 60
COOLDOWN_SEC      = 3600

last_alerted = {}

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
            r    = requests.get("https://api.coingecko.com/api/v3/coins/markets", params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page, "sparkline": False}, timeout=30)
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

def get_ohlcv(symbol):
    for url, name in [
        ("https://fapi.binance.com/fapi/v1/klines", "binance_futures"),
        ("https://api.binance.com/api/v3/klines",   "binance_spot"),
    ]:
        try:
            r    = requests.get(url, params={"symbol": f"{symbol}USDT", "interval": "1h", "limit": 100}, timeout=10)
            data = r.json()
            if not data or isinstance(data, dict):
                continue
            df = pd.DataFrame(data, columns=["time","open","high","low","close","volume","close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"])
            df["close"]  = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            if len(df) >= 30:
                return df, name
        except Exception:
            continue
    return None, None

def check_signal(df):
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["avg_vol"]  = df["volume"].rolling(20).mean()
    prev      = df.iloc[-3]
    curr      = df.iloc[-2]
    bullish   = (prev["ema_fast"] <= prev["ema_slow"]) and (curr["ema_fast"] > curr["ema_slow"])
    bearish   = (prev["ema_fast"] >= prev["ema_slow"]) and (curr["ema_fast"] < curr["ema_slow"])
    vol_ok    = curr["volume"] >= VOLUME_MULTIPLIER * curr["avg_vol"]
    vol_ratio = curr["volume"] / curr["avg_vol"] if curr["avg_vol"] else 0
    if bullish and vol_ok:
        return "bullish", vol_ratio, curr["close"]
    if bearish and vol_ok:
        return "bearish", vol_ratio, curr["close"]
    return None, vol_ratio, curr["close"]

def run():
    send_telegram("1️⃣ *Signal 1 Started*\nEMA 12/21 Cross + 1.2x Volume | MC > $1B | Every 15min")
    while True:
        try:
            print(f"\n[Signal1] Scanning...")
            coins = get_coins()
            for coin in coins:
                symbol = coin["symbol"]
                try:
                    df, market = get_ohlcv(symbol)
                    if df is None:
                        continue
                    direction, vol_ratio, price = check_signal(df)
                    if direction and not is_on_cooldown(symbol):
                        emoji = "🚀" if direction == "bullish" else "🔻"
                        text  = "EMA12 crossed ABOVE EMA21" if direction == "bullish" else "EMA12 crossed BELOW EMA21"
                        send_telegram(
                            f"{emoji} *EMA CROSS SIGNAL*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"💰 Price      : `${price:,.4f}`\n"
                            f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📈 {text}\n"
                            f"🔊 Volume     : `{vol_ratio:.2f}x` average\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)
                except Exception as e:
                    print(f"[Signal1] {symbol} error: {e}")
                time.sleep(0.15)
        except Exception as e:
            print(f"[Signal1] Scan error: {e}")
        time.sleep(SCAN_INTERVAL)