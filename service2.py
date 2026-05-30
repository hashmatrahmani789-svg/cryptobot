import requests
import pandas as pd
import time
from datetime import datetime, timezone

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"

SCAN_INTERVAL  = 4 * 60 * 60
CD_4H          = 14400
CD_DAILY       = 86400

EMA_FAST       = 12
EMA_SLOW       = 21
EMA_TREND      = 50

daily_counts = {"4h_cross": 0, "4h_ema50": 0, "daily_cross": 0}
last_summary  = time.time()

cd = {
    "4h_cross":    {},
    "4h_ema50":    {},
    "daily_cross": {},
}

def get_coins():
    coins = [
        # Mega caps
        "BTC","ETH","BNB","SOL","XRP","DOGE","ADA","AVAX","TRX","DOT",
        # Large caps
        "LINK","SHIB","LTC","BCH","UNI","NEAR","APT","ICP","TAO","HYPE",
        "SUI","FIL","ARB","OP","STX","IMX","INJ","MKR","FET","RNDR",
        "ATOM","AAVE","TIA","WIF","PEPE","BONK","FLOKI","JUP","SEI","WLD",
        "GRT","SNX","LDO","CAKE","DYDX","GMX","PENDLE","CRV","VET","HBAR",
        # Mid caps
        "ALGO","EGLD","SAND","MANA","AXS","CHZ","GALA","ENJ","FLOW","ROSE",
        "FTM","KAVA","THETA","OCEAN","CFX","BLUR","ZEC","KSM","MINA","QTUM",
        "1INCH","SUSHI","COMP","BAL","YFI","ZRX","BAND","STORJ","SKL","NMR",
        "JASMY","ACH","ZEN","ONT","ZIL","ICX","WAVES","XTZ","EOS","TRB",
        "API3","UMA","BAT","LRC","ANKR","CELR","COTI","CTSI","OGN","REN",
        # New trending
        "POL","PYTH","JTO","MANTA","ALT","PIXEL","PORTAL","STRK","DYM",
        "METIS","BOME","WEN","TNSR","SAGA","REZ","BB","NOT","IO","ZK",
        "LISTA","ZRO","BLAST","DOGS","HMSTR","CATI","EIGEN","SCR","NEIRO",
        "GOAT","MOODENG","PNUT","ACT","MOVE","ME","PENGU","USUAL","TRUMP",
        "MELANIA","BERA","IP","KAITO","RED","LAYER","PARTI","NIL","INIT",
        "HUMA","TST","VINE","SIGN","SHELL","ANIME","COOKIE","DEXE",
        # DeFi
        "RPL","FXS","RDNT","LQTY","CRO","ALPHA","PERP","RUNE","SPELL",
        "REEF","LOOKS","CVX","BADGER","TOKE",
        # Layer 1 / Layer 2
        "ONE","IOTA","KLAY","CELO","KDA","SCRT","GLMR","MOVR","ASTR",
        "TLOS","EVMOS","TFUEL","SDN",
        # Gaming / Metaverse
        "ILV","MAGIC","ALICE","TLM","SUPER","PYR","GHST","RFOX","SKILL",
        # AI
        "AGIX","NMR","RLC","MASA",
        # Memes
        "TURBO","BRETT","BABYDOGE",
        # Exchange tokens
        "OKB","HT","KCS","GT","MX","LEO",
        # Others
        "XLM","XMR","ETC","DASH","BTG","DCR","DGB","SC","LSK","ARDR",
        "STEEM","XEM","GRS","SNT","CVC","REQ","KNC","BNT","ANT","MTL",
        "POE","BTT","WIN","NFT","BTTC","SUN","JST","ARPA","CTXC","FOR",
        "LOOM","COS","PERL","DREP","TROY","VITE","TCT","IRIS",
    ]
    seen  = set()
    final = []
    for s in coins:
        if s not in seen:
            seen.add(s)
            final.append({"symbol": s, "market_cap": 0})
    print(f"[S2] {len(final)} coins loaded")
    return final

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"[S2] Telegram error: {e}")

def on_cooldown(symbol, store, seconds):
    return symbol in store and time.time() - store[symbol] < seconds

def mark(symbol, store):
    store[symbol] = time.time()

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

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
            df["open"]  = df["open"].astype(float)
            df["high"]  = df["high"].astype(float)
            df["low"]   = df["low"].astype(float)
            df["close"] = df["close"].astype(float)
            if len(df) >= 55:
                return df
        except Exception:
            continue
    return None

def check_4h_cross(symbol, df):
    if on_cooldown(symbol, cd["4h_cross"], CD_4H):
        return
    df = df.copy()
    df["ema12"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    bullish = prev["ema12"] <= prev["ema21"] and curr["ema12"] > curr["ema21"]
    bearish = prev["ema12"] >= prev["ema21"] and curr["ema12"] < curr["ema21"]
    if not bullish and not bearish:
        return
    price = curr["close"]
    emoji = "🟢" if bullish else "🔴"
    txt   = "EMA12 crossed ABOVE EMA21" if bullish else "EMA12 crossed BELOW EMA21"
    bias  = "4H bullish momentum ✅" if bullish else "4H bearish momentum ⚠️"
    send_telegram(
        f"{emoji} *4H EMA 12/21 CROSS — {'BULLISH' if bullish else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"────────────────────\n"
        f"📈 {txt}\n"
        f"📊 EMA12      : `{curr['ema12']:,.4f}`\n"
        f"📊 EMA21      : `{curr['ema21']:,.4f}`\n"
        f"💡 {bias}\n"
        f"⏰ `{now_utc()} UTC`"
    )
    mark(symbol, cd["4h_cross"])
    daily_counts["4h_cross"] += 1
    print(f"[S2] 4H CROSS {'BULL' if bullish else 'BEAR'} — {symbol}")

def check_4h_ema50(symbol, df):
    if on_cooldown(symbol, cd["4h_ema50"], CD_4H):
        return
    df = df.copy()
    df["ema50"] = df["close"].ewm(span=EMA_TREND, adjust=False).mean()
    c1   = df.iloc[-3]
    c0   = df.iloc[-2]
    ema1 = c1["ema50"]
    ema0 = c0["ema50"]
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
    price = c0["close"]
    emoji = "🔵" if direction == "bullish" else "🟠"
    if direction == "bullish":
        what    = "Wicked BELOW EMA50 — closed ABOVE" if alert_type == "Wick Reject" else "Closed below EMA50 — reclaimed ABOVE"
        meaning = "EMA50 support held ✅ Swing long setup"
    else:
        what    = "Wicked ABOVE EMA50 — closed BELOW" if alert_type == "Wick Reject" else "Closed above EMA50 — rejected BELOW"
        meaning = "EMA50 resistance held ⚠️ Swing short setup"
    send_telegram(
        f"{emoji} *4H EMA50 {alert_type.upper()} — {'BULLISH' if direction == 'bullish' else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"────────────────────\n"
        f"📊 Type       : `{alert_type}`\n"
        f"⚡ {what}\n"
        f"📊 EMA50      : `{ema0:,.4f}`\n"
        f"💡 {meaning}\n"
        f"⏰ `{now_utc()} UTC`"
    )
    mark(symbol, cd["4h_ema50"])
    daily_counts["4h_ema50"] += 1
    print(f"[S2] 4H EMA50 {alert_type} {'BULL' if direction == 'bullish' else 'BEAR'} — {symbol}")

def check_daily_cross(symbol, df):
    if on_cooldown(symbol, cd["daily_cross"], CD_DAILY):
        return
    df = df.copy()
    df["ema12"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    bullish = prev["ema12"] <= prev["ema21"] and curr["ema12"] > curr["ema21"]
    bearish = prev["ema12"] >= prev["ema21"] and curr["ema12"] < curr["ema21"]
    if not bullish and not bearish:
        return
    price = curr["close"]
    emoji = "🌙" if bullish else "🌑"
    txt   = "EMA12 crossed ABOVE EMA21" if bullish else "EMA12 crossed BELOW EMA21"
    bias  = "Daily bullish trend ✅" if bullish else "Daily bearish trend ⚠️"
    send_telegram(
        f"{emoji} *DAILY EMA 12/21 CROSS — {'BULLISH' if bullish else 'BEARISH'}*\n"
        f"────────────────────\n"
        f"📌 *{symbol}*\n"
        f"💰 Price      : `${price:,.4f}`\n"
        f"────────────────────\n"
        f"📈 {txt}\n"
        f"📊 EMA12      : `{curr['ema12']:,.4f}`\n"
        f"📊 EMA21      : `{curr['ema21']:,.4f}`\n"
        f"💡 {bias}\n"
        f"⏰ `{now_utc()} UTC` (Daily Close)"
    )
    mark(symbol, cd["daily_cross"])
    daily_counts["daily_cross"] += 1
    print(f"[S2] DAILY CROSS {'BULL' if bullish else 'BEAR'} — {symbol}")

def send_daily_summary():
    global last_summary
    send_telegram(
        f"📊 *Service 2 Daily Summary*\n"
        f"────────────────────\n"
        f"🟢 4H EMA 12/21     : `{daily_counts['4h_cross']} alerts`\n"
        f"🔵 4H EMA50 Reject  : `{daily_counts['4h_ema50']} alerts`\n"
        f"🌙 Daily EMA 12/21  : `{daily_counts['daily_cross']} alerts`\n"
        f"📊 Total            : `{sum(daily_counts.values())} alerts`\n"
        f"⏰ `{now_utc()} UTC`"
    )
    for k in daily_counts:
        daily_counts[k] = 0
    last_summary = time.time()

def run():
    global last_summary
    send_telegram(
        "2️⃣ *Service 2 Started* ✅\n"
        "────────────────────\n"
        "1. 4H EMA 12/21 Cross\n"
        "2. 4H EMA50 Wick + Close Reject\n"
        "3. Daily EMA 12/21 Cross\n"
        "────────────────────\n"
        f"📊 {len(get_coins())} coins | Scan every 4H"
    )
    while True:
        try:
            print(f"\n[S2] Scanning... {now_utc()} UTC")
            coins = get_coins()
            for coin in coins:
                symbol = coin["symbol"]
                try:
                    df_4h    = get_ohlcv(symbol, "4h", limit=100)
                    df_daily = get_ohlcv(symbol, "1d", limit=100)
                    if df_4h is not None:
                        check_4h_cross(symbol, df_4h)
                        check_4h_ema50(symbol, df_4h)
                    if df_daily is not None:
                        check_daily_cross(symbol, df_daily)
                except Exception as e:
                    print(f"[S2] {symbol} error: {e}")
                time.sleep(0.3)
            print(f"[S2] Scan complete.")
            if time.time() - last_summary >= 86400:
                send_daily_summary()
        except Exception as e:
            print(f"[S2] Scan error: {e}")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()