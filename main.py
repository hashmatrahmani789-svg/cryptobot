from pycoingecko import CoinGeckoAPI
from binance.client import Client
import pandas as pd
import requests
import time

cg = CoinGeckoAPI()
client = Client()

# PUT YOUR REAL VALUES HERE
BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID = "8118939134"


def send_telegram(message):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": message
    }

    requests.post(url, data=data)


# Startup test message
send_telegram("✅ Crypto Scanner Started")


while True:

    print("\nScanning market...\n")

    try:

        coins = cg.get_coins_markets(
            vs_currency="usd",
            order="market_cap_desc",
            per_page=100,
            page=1
        )

        for coin in coins:

            market_cap = coin["market_cap"]

            # Skip coins below 500M market cap
            if market_cap is None or market_cap < 500000000:
                continue

            symbol = coin["symbol"].upper() + "USDT"

            try:

                klines = client.get_klines(
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_1HOUR,
                    limit=50
                )

                df = pd.DataFrame(
                    klines,
                    columns=[
                        "time","open","high","low",
                        "close","volume",
                        "a","b","c","d","e","f"
                    ]
                )

                df["close"] = df["close"].astype(float)
                df["volume"] = df["volume"].astype(float)

                # EMA
                df["ema12"] = df["close"].ewm(span=12).mean()
                df["ema21"] = df["close"].ewm(span=21).mean()

                # Average volume
                avg_volume = df["volume"].rolling(20).mean()

                # Bullish signal
                bullish = (

                    df["ema12"].iloc[-1]
                    >
                    df["ema21"].iloc[-1]

                    and

                    df["ema12"].iloc[-2]
                    <=
                    df["ema21"].iloc[-2]

                    and

                    df["volume"].iloc[-1]
                    >
                    avg_volume.iloc[-1] * 1.5

                )

                # Bearish signal
                bearish = (

                    df["ema12"].iloc[-1]
                    <
                    df["ema21"].iloc[-1]

                    and

                    df["ema12"].iloc[-2]
                    >=
                    df["ema21"].iloc[-2]

                    and

                    df["volume"].iloc[-1]
                    >
                    avg_volume.iloc[-1] * 1.5

                )

                if bullish:

                    msg = (
                        f"🚀 BULLISH SIGNAL\n\n"
                        f"Coin: {symbol}\n"
                        f"Timeframe: 1H\n"
                        f"EMA12 crossed above EMA21\n"
                        f"Volume > 1.5x average"
                    )

                    print(msg)
                    send_telegram(msg)

                if bearish:

                    msg = (
                        f"📉 BEARISH SIGNAL\n\n"
                        f"Coin: {symbol}\n"
                        f"Timeframe: 1H\n"
                        f"EMA12 crossed below EMA21\n"
                        f"Volume > 1.5x average"
                    )

                    print(msg)
                    send_telegram(msg)

            except:
                pass

    except Exception as e:
        print(e)

    print("\nWaiting 300 seconds...\n")

    time.sleep(300)