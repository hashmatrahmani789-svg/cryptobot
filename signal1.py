import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"
MARKET_CAP_MIN = 500_000_000
EMA_FAST       = 12
EMA_SLOW       = 21

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

def get_binance_pairs():
    try:
        r    = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=15)
        data = r.json()
        return {s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"}
    except Exception:
        return set()

def get_daily_closes(symbol):
    try:
        r    = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": f"{symbol}USDT", "interval": "1d", "limit": 50}, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            return []
        return [float(c[4]) for c in data]
    except Exception:
        return []

def wait_until_daily_close():
    now        = datetime.now(timezone.utc)
    next_close = (now + timedelta(days=1)).replace(hour=0, minute=0, second=30, microsecond=0)
    wait       = (next_close - now).total_seconds()
    return wait

def run():
    send_telegram("4️⃣ *Signal 4 Started*\nDaily EMA 12/21 Cross | MC > $500M | Fires at 00:00 UTC")
    while True:
        try:
            wait       = wait_until_daily_close()
            close_time = (datetime.now(timezone.utc) + timedelta(seconds=wait)).strftime("%Y-%m-%d %H:%M UTC")
            print(f"[Signal4] Next scan at {close_time}")
            time.sleep(wait)

            print(f"[Signal4] Running daily scan...")
            coins         = get_coins()
            binance_pairs = get_binance_pairs()
            alerts_sent   = 0

            for coin in coins:
                symbol = coin["symbol"]
                try:
                    if f"{symbol}USDT" not in binance_pairs:
                        continue
                    closes = get_daily_closes(symbol)
                    if len(closes) < 22:
                        continue
                    ema_fast  = pd.Series(closes).ewm(span=EMA_FAST, adjust=False).mean().tolist()
                    ema_slow  = pd.Series(closes).ewm(span=EMA_SLOW, adjust=False).mean().tolist()
                    bullish   = ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1]
                    bearish   = ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1]
                    if bullish:
                        send_telegram(
                            f"🟢 *DAILY EMA CROSS — BULLISH*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"💰 Price      : `${closes[-1]:,.4f}`\n"
                            f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📈 EMA12 crossed ABOVE EMA21\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}` (Daily Close)"
                        )
                        alerts_sent += 1
                        time.sleep(0.5)
                    elif bearish:
                        send_telegram(
                            f"🔴 *DAILY EMA CROSS — BEARISH*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"💰 Price      : `${closes[-1]:,.4f}`\n"
                            f"📊 Market Cap : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"📉 EMA12 crossed BELOW EMA21\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}` (Daily Close)"
                        )
                        alerts_sent += 1
                        time.sleep(0.5)
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[Signal4] {symbol} error: {e}")

            send_telegram(f"✅ *Signal 4 Daily Scan Done*\nAlerts sent: `{alerts_sent}`")
            print(f"[Signal4] Done. {alerts_sent} alerts sent.")

        except Exception as e:
            print(f"[Signal4] Error: {e}")
            send_telegram(f"⚠️ Signal 4 error: `{e}`")
            time.sleep(60)