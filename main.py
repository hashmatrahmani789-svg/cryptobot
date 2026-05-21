import ccxt
import telebot
import time

# ===== TELEGRAM =====
BOT_TOKEN = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID = "8118939134"

bot = telebot.TeleBot(BOT_TOKEN)

# ===== EXCHANGE =====
exchange = ccxt.kraken({
    'enableRateLimit': True
})

# ===== COINS TO SCAN =====
symbols = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "DOGE/USD",
    "XRP/USD",
    "ADA/USD"
]

# Prevent repeated alerts
last_alert = {}

# Startup message
bot.send_message(CHAT_ID, "🚀 Crypto Scanner Started (Kraken)")

while True:
    try:
        print("Scanning market...")

        for symbol in symbols:
            try:
                # Get last 20 candles (5 min timeframe)
                candles = exchange.fetch_ohlcv(
                    symbol,
                    timeframe='5m',
                    limit=20
                )

                closes = [candle[4] for candle in candles]
                volumes = [candle[5] for candle in candles]

                current_price = closes[-1]
                current_volume = volumes[-1]

                avg_price = sum(closes[:-1]) / (len(closes) - 1)
                avg_volume = sum(volumes[:-1]) / (len(volumes) - 1)

                price_change = (
                    (current_price - avg_price)
                    / avg_price
                ) * 100

                volume_ratio = (
                    current_volume / avg_volume
                )

                print(
                    f"{symbol} | "
                    f"Move: {round(price_change,2)}% | "
                    f"Volume: {round(volume_ratio,2)}x"
                )

                # Alert conditions
                if (
                    abs(price_change) >= 2
                    and volume_ratio >= 2
                ):

                    signal = (
                        "📈 Bullish"
                        if price_change > 0
                        else "📉 Bearish"
                    )

                    alert_key = (
                        f"{symbol}_{round(price_change)}"
                    )

                    if alert_key not in last_alert:

                        message = f"""
🔥 CRYPTO ALERT

Coin: {symbol}
Signal: {signal}

Price: ${round(current_price,4)}
Move: {round(price_change,2)}%
Volume Spike: {round(volume_ratio,2)}x
"""

                        bot.send_message(
                            CHAT_ID,
                            message
                        )

                        last_alert[alert_key] = True

            except Exception as e:
                print(f"{symbol} error: {e}")

        print("Waiting 300 seconds...")
        time.sleep(300)

    except Exception as e:
        print("Main error:", e)
        time.sleep(60)