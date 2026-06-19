import os
import time
import json
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHLIST] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_KEY   = os.environ.get("TWELVE_DATA_KEY", "").strip()

EMA_FAST          = 12
EMA_SLOW          = 21
EMA_50            = 50
VOLUME_MA_PERIOD  = 20
CROSS_LOOKBACK    = 3
ZONE_TOLERANCE    = 0.003

CRYPTO = [
    ("BTC",  "Bitcoin"),
    ("ETH",  "Ethereum"),
    ("HYPE", "Hyperliquid"),
    ("SOL",  "Solana"),
]

MACRO = [
    ("XAU/USD", "Gold"),
    ("XAG/USD", "Silver"),
    ("IXIC",    "NASDAQ"),
    ("SPX",     "S&P 500"),
    ("DXY",     "Dollar Index"),
]

CRYPTO_TFS = ["15m", "1h", "4h"]
MACRO_TFS  = ["1h", "4h", "1day"]

SIGNAL_MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_memory_watchlist.json")


def load_memory():
    if os.path.exists(SIGNAL_MEMORY_FILE):
        try:
            with open(SIGNAL_MEMORY_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_memory(memory):
    try:
        with open(SIGNAL_MEMORY_FILE, "w") as f:
            json.dump(memory, f)
    except Exception as e:
        log.error(f"Memory save error: {e}")


def is_new_signal(memory, key, value):
    return memory.get(key) != value


def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=15
        )
        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


def get_crypto_candles(ticker, interval):
    granularity_map = {"15m": "FIFTEEN_MINUTE", "1h": "ONE_HOUR", "4h": "FOUR_HOUR"}
    granularity = granularity_map.get(interval)
    product_id = f"{ticker}-USD"
    try:
        r = requests.get(
            f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
            params={"granularity": granularity, "limit": 150},
            timeout=10
        )
        data = r.json()
        candles = data.get("candles", [])
        if not candles or len(candles) < 60:
            return None
        candles = list(reversed(candles))[:-1]
        return [
            {
                "high":   float(c["high"]),
                "low":    float(c["low"]),
                "close":  float(c["close"]),
                "volume": float(c["volume"]),
            }
            for c in candles
        ]
    except Exception as e:
        log.error(f"Coinbase error {ticker} {interval}: {e}")
        return None


def get_macro_candles(symbol, interval):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol":     symbol,
                "interval":   interval,
                "outputsize": 150,
                "apikey":     TWELVE_DATA_KEY,
            },
            timeout=15
        )
        data = r.json()
        if data.get("status") == "error":
            log.error(f"TwelveData error {symbol} {interval}: {data.get('message')}")
            return None
        values = data.get("values", [])
        if not values or len(values) < 60:
            return None
        values = list(reversed(values))
        return [
            {
                "high":   float(v["high"]),
                "low":    float(v["low"]),
                "close":  float(v["close"]),
                "volume": float(v.get("volume", 0) or 0),
            }
            for v in values
        ]
    except Exception as e:
        log.error(f"TwelveData exception {symbol} {interval}: {e}")
        return None


def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def volume_above_ma(volumes, period=VOLUME_MA_PERIOD):
    if len(volumes) < period + 1:
        return False
    ma = sum(volumes[-period - 1:-1]) / period
    return volumes[-1] > ma


def find_cross(closes, lookback=CROSS_LOOKBACK):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)
    for i in range(1, lookback + 1):
        curr_idx = -i
        prev_idx = -(i + 1)
        if ema_fast[prev_idx] <= ema_slow[prev_idx] and ema_fast[curr_idx] > ema_slow[curr_idx]:
            return "BULLISH", i, ema_fast[-1], ema_slow[-1]
        if ema_fast[prev_idx] >= ema_slow[prev_idx] and ema_fast[curr_idx] < ema_slow[curr_idx]:
            return "BEARISH", i, ema_fast[-1], ema_slow[-1]
    return None, None, None, None


def ema50_state(candles):
    closes = [c["close"] for c in candles]
    ema50  = calc_ema(closes, EMA_50)
    e      = ema50[-1]
    c      = candles[-1]
    tol    = e * ZONE_TOLERANCE
    touched = c["low"] <= e + tol and c["high"] >= e - tol
    if c["close"] > e + tol:
        state = "ABOVE"
    elif c["close"] < e - tol:
        state = "BELOW"
    else:
        state = "INSIDE"
    return touched, state, e, c["close"]


def fmt_price(p):
    if p is None or p == 0:
        return "N/A"
    if p >= 1000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"


def tv_link_crypto(ticker):
    return f"https://www.tradingview.com/chart/?symbol=COINBASE:{ticker}USD"


def scan_asset(name, label, candles_by_tf, tfs, is_crypto, memory,
               sig1, sig2, sig3):
    # ── Signal 1: 1H EMA 12/21 cross WITH volume ─────────────────────────────
    c_1h = candles_by_tf.get("1h")
    if c_1h:
        closes = [c["close"] for c in c_1h]
        vols   = [c["volume"] for c in c_1h]
        direction, ago, ef, es = find_cross(closes)
        if direction:
            has_vol = volume_above_ma(vols) if is_crypto else True
            if has_vol:
                key = f"{name}_1h_cross"
                if is_new_signal(memory, key, direction):
                    memory[key] = direction
                    sig1.append({
                        "name": name, "label": label, "dir": direction,
                        "ago": ago, "ef": ef, "es": es,
                        "price": closes[-1], "is_crypto": is_crypto,
                    })
        # ← memory.pop() removed: signal won't re-fire until direction flips

    # ── Signal 2: 4H EMA 12/21 cross WITHOUT volume ──────────────────────────
    c_4h = candles_by_tf.get("4h")
    if c_4h:
        closes = [c["close"] for c in c_4h]
        direction, ago, ef, es = find_cross(closes)
        if direction:
            key = f"{name}_4h_cross"
            if is_new_signal(memory, key, direction):
                memory[key] = direction
                sig2.append({
                    "name": name, "label": label, "dir": direction,
                    "ago": ago, "ef": ef, "es": es,
                    "price": closes[-1], "is_crypto": is_crypto,
                })
        # ← memory.pop() removed: signal won't re-fire until direction flips

    # ── Signal 3: lowest-TF EMA50 touch + close ──────────────────────────────
    low_tf = tfs[0]
    c_low = candles_by_tf.get(low_tf)
    if c_low:
        touched, state, ema, close = ema50_state(c_low)
        key = f"{name}_{low_tf}_ema50"
        if is_new_signal(memory, key, state):
            memory[key] = state
            sig3.append({
                "name": name, "label": label, "tf": low_tf,
                "state": state, "touched": touched,
                "ema": ema, "close": close, "is_crypto": is_crypto,
            })


def fmt_cross_entry(e):
    arrow = "🟢" if e["dir"] == "BULLISH" else "🔴"
    when  = "this candle" if e["ago"] == 1 else f"{e['ago']} candles ago"
    link  = tv_link_crypto(e["name"]) if e["is_crypto"] else ""
    chart = f"\n<a href='{link}'>📈 Chart</a>" if link else ""
    return (
        f"\n{arrow} <b>{e['name']}</b> ({e['label']}) — {e['dir']}\n"
        f"💰 {fmt_price(e['price'])}  |  cross {when}\n"
        f"📊 EMA12: {fmt_price(e['ef'])}  EMA21: {fmt_price(e['es'])}{chart}"
    )


def fmt_ema50_entry(e):
    icon = {"ABOVE": "💚", "BELOW": "❤️", "INSIDE": "🔵"}[e["state"]]
    touch_str = " 🎯 touched" if e["touched"] else ""
    link  = tv_link_crypto(e["name"]) if e["is_crypto"] else ""
    chart = f"\n<a href='{link}'>📈 Chart</a>" if link else ""
    return (
        f"\n{icon} <b>{e['name']}</b> ({e['label']}) — closed {e['state']}{touch_str}\n"
        f"💰 {fmt_price(e['close'])}  |  EMA50: {fmt_price(e['ema'])}{chart}"
    )


def send_signals(sig1, sig2, sig3, now_str):
    if sig1:
        lines = [
            "⚡ <b>1H EMA 12/21 CROSS + VOLUME</b>",
            "╔════════════════════╗",
            f"🕐 {now_str}",
            "╚════════════════════╝",
        ]
        for e in sig1:
            lines.append(fmt_cross_entry(e))
        send_alert("\n".join(lines))

    if sig2:
        lines = [
            "🌊 <b>4H EMA 12/21 CROSS</b>",
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
            f"🕐 {now_str}",
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        ]
        for e in sig2:
            lines.append(fmt_cross_entry(e))
        send_alert("\n".join(lines))

    if sig3:
        lines = [
            "🕯 <b>EMA50 TOUCH + CLOSE</b>",
            "══════════════════════",
            f"🕐 {now_str}",
            "══════════════════════",
        ]
        for e in sig3:
            lines.append(fmt_ema50_entry(e))
        send_alert("\n".join(lines))


def run_scan():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"Watchlist scan running... {now_str}")

    memory = load_memory()
    sig1, sig2, sig3 = [], [], []

    for ticker, label in CRYPTO:
        candles_by_tf = {}
        for tf in CRYPTO_TFS:
            candles_by_tf[tf] = get_crypto_candles(ticker, tf)
            time.sleep(0.2)
        scan_asset(ticker, label, candles_by_tf, CRYPTO_TFS, True, memory, sig1, sig2, sig3)

    if TWELVE_DATA_KEY:
        for symbol, label in MACRO:
            candles_by_tf = {}
            for tf in MACRO_TFS:
                candles_by_tf[tf] = get_macro_candles(symbol, tf)
                time.sleep(1.0)
            scan_asset(symbol.replace("/", ""), label, candles_by_tf, MACRO_TFS, False, memory, sig1, sig2, sig3)
    else:
        log.warning("TWELVE_DATA_KEY not set — skipping macro assets.")

    save_memory(memory)

    total = len(sig1) + len(sig2) + len(sig3)
    if total == 0:
        log.info("No new signals.")
        return

    send_signals(sig1, sig2, sig3, now_str)
    log.info(f"Scan complete. {total} signals sent.")


def wait_until_next_scan():
    now = datetime.now(timezone.utc)
    minute = (now.minute // 15 + 1) * 15
    if minute >= 60:
        next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_run = now.replace(minute=minute, second=0, microsecond=0)
    sleep_secs = (next_run - now).total_seconds()
    log.info(f"Next scan at {next_run.strftime('%H:%M UTC')} — sleeping {sleep_secs/60:.1f}m")
    time.sleep(sleep_secs)


if __name__ == "__main__":
    log.info("Watchlist Scanner started.")
    send_alert(
        "✅ <b>Watchlist Scanner Online</b>\n"
        "Crypto: BTC, ETH, HYPE, SOL (15m/1H/4H)\n"
        "Macro: Gold, Silver, NASDAQ, S&P 500, DXY (1H/4H/1D)\n\n"
        "Signals:\n"
        "⚡ 1H EMA 12/21 cross + volume\n"
        "🌊 4H EMA 12/21 cross\n"
        "🕯 EMA50 touch + close (in/out)"
    )
    run_scan()
    while True:
        wait_until_next_scan()
        run_scan()