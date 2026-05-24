import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN           = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID             = "8118939134"
MARKET_CAP_MIN      = 1_000_000_000
OI_MIN_CHANGE_PCT   = 2.0
OI_MIN_PRICE_PCT    = 1.5
SCAN_INTERVAL       = 15 * 60
COOLDOWN_SEC        = 3600

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

def get_oi(symbol):
    try:
        r    = requests.get("https://fapi.binance.com/futures/data/openInterestHist", params={"symbol": f"{symbol}USDT", "period": "1h", "limit": 5}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return None
        return [float(d["sumOpenInterest"]) for d in data]
    except Exception:
        return None

def run():
    send_telegram("2️⃣ *Signal 2 Started*\nOI + Price Momentum | MC > $1B | Every 15min")
    while True:
        try:
            print(f"\n[Signal2] Scanning...")
            coins = get_coins()
            for coin in coins:
                symbol = coin["symbol"]
                try:
                    df, market = get_ohlcv(symbol)
                    if df is None:
                        continue
                    if "binance" not in market:
                        continue
                    curr_price   = float(df.iloc[-2]["close"])
                    prev_price   = float(df.iloc[-3]["close"])
                    price_change = (curr_price - prev_price) / prev_price * 100
                    oi_list      = get_oi(symbol)
                    if not oi_list or len(oi_list) < 2:
                        continue
                    oi_change = (oi_list[-1] - oi_list[-2]) / oi_list[-2] * 100
                    if abs(oi_change) < OI_MIN_CHANGE_PCT or abs(price_change) < OI_MIN_PRICE_PCT:
                        continue
                    if is_on_cooldown(symbol):
                        continue
                    if oi_change > 0 and price_change > 0:
                        direction = "bullish"
                        emoji     = "📈"
                        detail    = "Price UP + OI UP = Real buying pressure"
                    elif oi_change > 0 and price_change < 0:
                        direction = "bearish"
                        emoji     = "📉"
                        detail    = "Price DOWN + OI UP = Real selling pressure"
                    else:
                        continue
                    send_telegram(
                        f"{emoji} *OI MOMENTUM SIGNAL*\n"
                        f"────────────────────\n"
                        f"📌 *{symbol}*\n"
                        f"💰 Price      : `${curr_price:,.4f}`\n"
                        f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                        f"💹 {detail}\n"
                        f"📊 OI Change  : `{oi_change:+.2f}%`\n"
                        f"📉 Price Change: `{price_change:+.2f}%`\n"
                        f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                    )
                    mark_alerted(symbol)
                    time.sleep(0.5)
                except Exception as e:
                    print(f"[Signal2] {symbol} error: {e}")
                time.sleep(0.15)
        except Exception as e:
            print(f"[Signal2] Scan error: {e}")
        time.sleep(SCAN_INTERVAL)