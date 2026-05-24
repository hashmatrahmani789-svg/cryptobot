# signal7.py
# Master Combined Signal — fires when Signal 5 + Signal 6 agree
# Scans every 15 minutes

import time
from datetime import datetime, timezone
import requests
import signal5
import signal6

BOT_TOKEN     = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID       = "8118939134"
SCAN_INTERVAL = 15 * 60
COOLDOWN_SEC  = 3600

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

def run():
    send_telegram(
        "7️⃣ *Signal 7 Started*\n"
        "Master Combined Signal | Fires when 5+6 agree | Every 15min"
    )

    # Wait for Signal 5 and 6 to populate results first
    time.sleep(60)

    while True:
        try:
            print(f"\n[Signal7] Checking combined signals...")

            # Get all symbols that appear in both Signal 5 and 6 results
            symbols = set(signal5.signal5_results.keys()) & set(signal6.signal6_results.keys())

            for symbol in symbols:
                try:
                    s5 = signal5.signal5_results.get(symbol)
                    s6 = signal6.signal6_results.get(symbol)

                    if not s5 or not s6:
                        continue
                    if is_on_cooldown(symbol):
                        continue

                    buy_ratio  = s5["buy_ratio"]
                    sell_ratio = s5["sell_ratio"]
                    ls_ratio   = s6["ls_ratio"]
                    top_ls     = s6["top_ls"]
                    funding    = s6["funding"]
                    oi_change  = s6["oi_change"]

                    score      = 0
                    conditions = []

                    # ── SCENARIO 1 — LONG SQUEEZE WARNING ────────────────────
                    if sell_ratio >= 2.0:
                        score += 1
                        conditions.append(f"✅ Sell volume: `{sell_ratio:.1f}x` avg")
                    if ls_ratio >= 1.8:
                        score += 1
                        conditions.append(f"✅ L/S Ratio: `{ls_ratio:.2f}` (too many longs)")
                    if funding >= 0.0008:
                        score += 1
                        conditions.append(f"✅ Funding: `{funding*100:.4f}%` (overheated)")
                    if oi_change < -0.05:
                        score += 1
                        conditions.append(f"✅ OI dropping: `{oi_change*100:+.2f}%`")

                    if score >= 3:
                        confidence = "VERY HIGH" if score == 4 else "HIGH"
                        send_telegram(
                            f"💥 *MASTER SIGNAL — LONG SQUEEZE*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"🎯 Confidence : `{confidence}` ({score}/4 signals agree)\n"
                            f"\n" + "\n".join(conditions) + "\n"
                            f"\n⚠️ Conclusion : LONG SQUEEZE HIGH RISK\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)
                        continue

                    # Reset score for next scenario
                    score      = 0
                    conditions = []

                    # ── SCENARIO 2 — STRONG BUY SETUP ────────────────────────
                    if buy_ratio >= 2.0:
                        score += 1
                        conditions.append(f"✅ Buy volume: `{buy_ratio:.1f}x` avg")
                    if top_ls and top_ls >= 1.5:
                        score += 1
                        conditions.append(f"✅ Top traders: `{top_ls:.2f}` (heavily long)")
                    if funding >= 0 and funding < 0.0005:
                        score += 1
                        conditions.append(f"✅ Funding: `{funding*100:.4f}%` (healthy)")
                    if oi_change > 0.05:
                        score += 1
                        conditions.append(f"✅ OI rising: `{oi_change*100:+.2f}%`")

                    if score >= 3:
                        confidence = "VERY HIGH" if score == 4 else "HIGH"
                        send_telegram(
                            f"🚀 *MASTER SIGNAL — STRONG LONG SETUP*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"🎯 Confidence : `{confidence}` ({score}/4 signals agree)\n"
                            f"\n" + "\n".join(conditions) + "\n"
                            f"\n✅ Conclusion : STRONG LONG SETUP\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)
                        continue

                    # Reset score for next scenario
                    score      = 0
                    conditions = []

                    # ── SCENARIO 3 — SHORT SQUEEZE WARNING ───────────────────
                    if sell_ratio < 0.5:
                        score += 1
                        conditions.append(f"✅ Sell volume low: `{sell_ratio:.1f}x` avg")
                    if ls_ratio <= 0.6:
                        score += 1
                        conditions.append(f"✅ L/S Ratio: `{ls_ratio:.2f}` (too many shorts)")
                    if funding <= -0.0003:
                        score += 1
                        conditions.append(f"✅ Funding negative: `{funding*100:.4f}%`")
                    if oi_change < -0.05:
                        score += 1
                        conditions.append(f"✅ OI dropping: `{oi_change*100:+.2f}%`")

                    if score >= 3:
                        confidence = "VERY HIGH" if score == 4 else "HIGH"
                        send_telegram(
                            f"💥 *MASTER SIGNAL — SHORT SQUEEZE*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"🎯 Confidence : `{confidence}` ({score}/4 signals agree)\n"
                            f"\n" + "\n".join(conditions) + "\n"
                            f"\n⚠️ Conclusion : SHORT SQUEEZE HIGH RISK\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)
                        continue

                    # Reset score for next scenario
                    score      = 0
                    conditions = []

                    # ── SCENARIO 4 — SMART MONEY DISTRIBUTING ────────────────
                    if sell_ratio >= 1.5:
                        score += 1
                        conditions.append(f"✅ Sell volume: `{sell_ratio:.1f}x` avg")
                    if top_ls and top_ls <= 0.8:
                        score += 1
                        conditions.append(f"✅ Top traders reducing longs: `{top_ls:.2f}`")
                    if funding > 0.0005:
                        score += 1
                        conditions.append(f"✅ Funding elevated: `{funding*100:.4f}%`")
                    if oi_change < 0:
                        score += 1
                        conditions.append(f"✅ OI dropping: `{oi_change*100:+.2f}%`")

                    if score >= 3:
                        confidence = "VERY HIGH" if score == 4 else "HIGH"
                        send_telegram(
                            f"🐻 *MASTER SIGNAL — DISTRIBUTION*\n"
                            f"────────────────────\n"
                            f"📌 *{symbol}*\n"
                            f"🎯 Confidence : `{confidence}` ({score}/4 signals agree)\n"
                            f"\n" + "\n".join(conditions) + "\n"
                            f"\n⚠️ Conclusion : SMART MONEY DISTRIBUTING\n"
                            f"⏰ Time (UTC) : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
                        )
                        mark_alerted(symbol)
                        time.sleep(0.5)

                except Exception as e:
                    print(f"[Signal7] {symbol} error: {e}")

        except Exception as e:
            print(f"[Signal7] Scan error: {e}")
            send_telegram(f"⚠️ Signal 7 error: `{e}`")

        time.sleep(SCAN_INTERVAL)