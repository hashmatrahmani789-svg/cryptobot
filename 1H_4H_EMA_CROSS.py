import time
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [1H-4H-CROSS] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

import os

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
EMA_FAST         = 12
EMA_SLOW         = 21
CROSS_LOOKBACK   = 12
CHECK_INTERVAL   = 300

COINS = [
    'BTC','ETH','BNB','XRP','SOL','TRX','HYPE','DOGE','LEO','ZEC','RAIN','ADA','XLM','XMR',
    'CC','LINK','LAB','WBT','BCH','TON','HBAR','LTC','AVAX','SUI','NEAR','SHI','XAUT','CRO',
    'TAO','WLFI','MNT','ONDO','DOT','ASTER','WLD','UNI','OKB','ICP','PI','BGB','PEPE','ETC',
    'AAVE','QNT','BCAP','RENDER','POL','ALGO','ATOM','ENA','FIL','APT','INJ','FLR','XDC',
    'PUMP','JUP','ARB','FET','HASH','VET','DASH','TRUMP','VIRTUAL','PENGU','KITE','BONK',
    'CAKE','PRIME','LIT','LUNC','STX','SEI','KAU','SUN','AERO','TIA','XTZ','CRV','ZRO',
    'ETHFI','SPX','JTO','CHZ','OHM','PYTH','BSV','GNO','CFX','TEL','DCR','KAIA','FLOKI',
    'JASMY','LDO','GRT','OP','PENDLE','MON','XPL','IOTA','GWEI','ENS','ULTIMA','BILL',
    'AKT','KOGE','ONYC','TWT','TRAC','SKYAI','AXS','REAL','WFI','NEX','USAT','COMP','NEO',
    'RAY','THETA','SYRUP','MX','BTSE','GENIUS','XCN','BORG','SAND','AR','BAT','HOME',
    'DYDX','MANA','ZANO','RAIL','EIGEN','STRCX','CFG','APE','VSN','GALA','SHFL','OZO',
    'GLM','RUNE','WEMIX','HNT','SFP','FT','XEC','CVX','IMX','ZK','KAITO','1INCH','AWE',
    'STAC','RIVER','TKX'
]

# remove known stables and junk
EXCLUDE = {'USDS','USDC','USDT','BUSD','DAI','TUSD','USDP','GUSD','FRAX','LUSD','USDD',
           'FDUSD','USDG','RLUSD','PYUSD','USYC','USDG','BUIDL','USDY','PAXG','USTB',
           'USDAI','RUSD','USDA','USDM','APYUSD','CRVUSD','EURS','AUSD','NUSD','FRXUSD',
           'THBILL','DUSD','SATUSD','USDAT','EURSAFO','APXUSD','EURC','EURCV','USDTB',
           'EUTBL','STABLE','JTRSY','FIGR_HELOC','PC0000031','PC0000033','PC0000097',
           'PC0000023','PC0000015','PC0000085','PC0000077','M','U','B','S','A','H',
           'USDF','SKY','BFUSD','MORPHO','VVV','币安人生','FARTCOIN','BANANAS31','GOMINING',
           'CHEEMS','CRCLON','TIBBIR','ACRED','SAHARA','FORM','BMX','STAC'}

COINS = [c for c in COINS if c not in EXCLUDE]


# =========================
# TELEGRAM
# =========================
def send_alert(message):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=15
        )
        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


# =========================
# BINANCE
# =========================
def get_candles(symbol, interval, limit=500):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None
        return [float(x[4]) for x in data[:-1]]
    except:
        return None


# =========================
# EMA
# =========================
def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


# =========================
# SIGNAL
# =========================
def check_signal(closes):
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    for i in range(1, CROSS_LOOKBACK + 1):
        curr_idx = -i
        prev_idx = -(i + 1)

        if ema_fast[prev_idx] <= ema_slow[prev_idx] and ema_fast[curr_idx] > ema_slow[curr_idx]:
            return "BULLISH", i
        if ema_fast[prev_idx] >= ema_slow[prev_idx] and ema_fast[curr_idx] < ema_slow[curr_idx]:
            return "BEARISH", i

    return None, None


# =========================
# SCAN ONE TIMEFRAME
# =========================
def scan_timeframe(interval):
    bullish = []
    bearish = []

    for ticker in COINS:
        symbol = ticker + "USDT"
        closes = get_candles(symbol, interval)
        if closes is None:
            closes = get_candles(ticker + "BTC", interval)
        if closes is None:
            continue

        direction, candles_ago = check_signal(closes)
        if direction is None:
            continue

        log.info(f"{symbol} [{interval}] {direction} ({candles_ago}c ago)")

        if direction == "BULLISH":
            bullish.append(ticker)
        else:
            bearish.append(ticker)

        time.sleep(0.05)

    return bullish, bearish


# =========================
# BUILD MESSAGE
# =========================
def build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str):
    lines = [
        f"📊 <b>EMA 12/21 — Cross Alert</b>",
        f"━━━━━━━━━━━━━━━━",
    ]

    if bullish_1h or bearish_1h:
        lines.append(f"\n⏱ <b>1H Timeframe</b>")
        if bullish_1h:
            lines.append(f"📈 <b>Bullish</b>\n{'  •  '.join(bullish_1h)}")
        if bearish_1h:
            lines.append(f"📉 <b>Bearish</b>\n{'  •  '.join(bearish_1h)}")

    if bullish_4h or bearish_4h:
        lines.append(f"\n⏱ <b>4H Timeframe</b>")
        if bullish_4h:
            lines.append(f"📈 <b>Bullish</b>\n{'  •  '.join(bullish_4h)}")
        if bearish_4h:
            lines.append(f"📉 <b>Bearish</b>\n{'  •  '.join(bearish_4h)}")

    lines.append(f"\n🕐 {now_str}")
    return "\n".join(lines)


# =========================
# SCAN
# =========================
def do_scan(label=""):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if label:
        log.info(f"{label} scanning...")

    bullish_1h, bearish_1h = scan_timeframe("1h")
    bullish_4h, bearish_4h = scan_timeframe("4h")

    if any([bullish_1h, bearish_1h, bullish_4h, bearish_4h]):
        msg = build_message(bullish_1h, bearish_1h, bullish_4h, bearish_4h, now_str)
        send_alert(msg)
        log.info("Signals sent.")
    else:
        log.info("No signals.")


# =========================
# MAIN LOOP
# =========================
def run():
    log.info(f"1H 4H EMA Cross Scanner started. {len(COINS)} coins loaded.")
    send_alert(f"✅ <b>EMA 12/21 Scanner Online</b>\n{len(COINS)} coins loaded. Scanning every 5 min.")

    do_scan(label="Startup")

    while True:
        time.sleep(CHECK_INTERVAL)
        do_scan()


if __name__ == "__main__":
    run()