import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN           = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID             = "8118939134"

MARKET_CAP_MIN      = 1_000_000_000

# CVD Settings
CVD_LOOKBACK        = 20     # 20 x 1H candles = 20 hours
CVD_MIN_DELTA_RATIO = 0.25   # CVD must be 25% of avg volume

SCAN_INTERVAL       = 15 * 60
COOLDOWN_SEC        = 3600

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
def get_ohlcv(symbol):
    for url in [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api.binance.com/api/v3/klines",
    ]:
        try:
            r    = requests.get(
                url,
                params={"symbol": f"{symbol}USDT", "interval": "1h", "limit": 100},
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
            df["close"]          = df["close"].astype(float)
            df["volume"]         = df["volume"].astype(float)
            df["taker_buy_base"] = df["taker_buy_base"].astype(float)
            if len(df) >= 30:
                return df
        except Exception:
            continue
    return None

# ─────────────────────────────────────────
def check_signal(df):
    df         = df.copy()

    # Calculate CVD
    df["delta"] = df["taker_buy_base"] - (df["volume"] - df["taker_buy_base"])
    df["cvd"]   = df["delta"].cumsum()

    # Get last 20 candles (excluding current incomplete candle)
    recent      = df.iloc[-(CVD_LOOKBACK + 1):-1]

    start_price = recent["close"].iloc[0]
    end_price   = recent["close"].iloc[-1]
    avg_vol     = recent["volume"].mean()

    cvd_start   = recent["cvd"].iloc[0]
    cvd_end     = recent["cvd"].iloc[-1]
    cvd_change  = cvd_end - cvd_start
    cvd_ratio   = abs(cvd_change) / avg_vol if avg_vol else 0

    # Price direction — just up or down, no % required
    price_going_down = end_price < start_price
    price_going_up   = end_price > start_price
    price_chg_pct    = (end_price - start_price) / start_price * 100

    # CVD must be strong enough
    if cvd_ratio < CVD_MIN_DELTA_RATIO:
        return None, price_chg_pct, cvd_change, cvd_ratio

    # CVD trend confirmation — second half stronger than first
    mid        = len(recent) // 2
    cvd_first  = recent["cvd"].iloc[:mid].mean()
    cvd_second = recent["cvd"].iloc[mid:].mean()

    # Bullish divergence — price down but CVD up
    if price_going_down and cvd_change > 0 and cvd_second > cvd_first:
        return "bullish", price_chg_pct, cvd_change, cvd_ratio

    # Bearish divergence — price up but CVD down
    if price_going_up and cvd_change < 0 and cvd_second < cvd_first:
        return "bearish", price_chg_pct, cvd_change, cvd_ratio

    return None, price_chg_pct, cvd_change, cvd_ratio

# ─────────────────────────────────────────
def run():
    send_telegram(
        "3️⃣ *Signal 3 Started* ✅\n"
        "────────────────────\n"
        "🔍 *Type*     : CVD Divergence\n"
        "⏱ *Timeframe*: 1H candles\n"
        "📊 *Lookback* : 20 candles (20 hours)\n"
        "⚖️ *CVD Ratio*: 0.25 minimum\n"
        "📉 *Filter*   : Price direction only (no % required)\n"
        "💰 *MC Filter*: > $1B\n"
        "🔄 *Scan every*: 15 min"
    )

    while True:
        try:
            print(f"\n[Signal3] Scanning...")
            coins = get_coins()

            for coin in coins:
                symbol = coin["symbol"]
                try:
                    df = get_ohlcv(symbol)
                    if df is None:
                        continue

                    if is_on_cooldown(symbol):
                        continue

                    direction, price_chg, cvd_chg, cvd_ratio = check_signal(df)

                    if direction:
                        price   = float(df.iloc[-2]["close"])
                        emoji   = "🔍" if direction == "bullish" else "⚠️"

                        if direction == "bullish":
                            detail    = "Price going DOWN but CVD going UP"
                            meaning   = "Hidden buying — smart money accumulating 🟢"
                            expectation = "Potential price reversal UP incoming"
                        else:
                            detail    = "Price going UP but CVD going DOWN"
                            meaning   = "Hidden selling — smart money distributing 🔴"
                            expectation = "Potential price reversal DOWN incoming"

                        print(f"[Signal3] {direction.upper()} — {symbol} | price={price_chg:+.2f}% | cvd_ratio={cvd_ratio:.2f}")

                        send_telegram(
                            f"{emoji} *CVD DIVERGENCE SIGNAL*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"💰 Price        : `${price:,.4f}`\n"
                            f"📊 Market Cap   : `${coin['market_cap']/1e9:.2f}B`\n"
                            f"────────────────────\n"
                            f"📉 *What happened:*\n"
                            f"⚡ {detail}\n"
                            f"🌊 CVD Change   : `{cvd_chg:+.0f}`\n"
                            f"⚖️ CVD Ratio    : `{cvd_ratio:.2f}`\n"
                            f"📈 Price Change : `{price_chg:+.2f}%`\n"
                            f"────────────────────\n"
                            f"💡 *Meaning:*\n"
                            f"{meaning}\n"
                            f"🎯 {expectation}\n"
                            f"────────────────────\n"
                            f"⏰ Time (UTC)   : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                except Exception as e:
                    print(f"[Signal3] {symbol} error: {e}")
                time.sleep(0.15)

        except Exception as e:
            print(f"[Signal3] Scan error: {e}")

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()