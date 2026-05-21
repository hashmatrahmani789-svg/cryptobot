import ccxt
import telebot
import time

# ===== TELEGRAM =====
BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID = "8118939134"

bot = telebot.TeleBot(BOT_TOKEN)

# ===== EXCHANGE =====
exchange = ccxt.binance({
    'enableRateLimit': True
})

# Coins to scan
symbols = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "DOGE/USDT",
    "XRP/USDT",
    "ADA/USDT"
]

# Prevent spam
last_alert = {}

bot.send_message(CHAT_ID, "🚀 Crypto Scanner Started")

while True:
    try:
        print("Scanning market...")

        for symbol in symbols:
            try:
                candles = exchange.fetch_ohlcv(
                    symbol,
                    timeframe='5m',
                    limit=20
                )

                closes = [candle[4] for candle in candles]

                current_price = closes[-1]
                average_price = sum(closes[:-1]) / (len(closes)-1)

                percent_change = (
                    (current_price - average_price)
                    / average_price
                ) * 100

                print(f"{symbol}: {round(percent_change,2)}%")

                # Alert if move > 2%
                if abs(percent_change) >= 2:

                    alert_text = (
                        f"🔥 ALERT\n\n"
                        f"Coin: {symbol}\n"
                        f"Price: ${round(current_price,4)}\n"
                        f"Move: {round(percent_change,2)}%"
                    )

                    # stop repeat alerts
                    if last_alert.get(symbol) != round(percent_change):

                        bot.send_message(
                            CHAT_ID,
                            alert_text
                        )

                        last_alert[symbol] = round(percent_change)

            except Exception as e:
                print(f"{symbol} error: {e}")

        print("Waiting 300 seconds...")
        time.sleep(300)

    except Exception as e:
        print("Main loop error:", e)
        time.sleep(60)