import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CALENDAR] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# ── High impact economic events ──────────────────────────────────────────────
# Format: (month, day, hour_utc, minute_utc, name, description)
EVENTS_2026 = [
    # ── FOMC Meetings (Fed interest rate decisions) ──
    (1,  29, 19, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (3,  19, 18, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (5,  7,  18, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (6,  18, 18, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (7,  30, 18, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (9,  17, 18, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (11, 5,  19, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),
    (12, 17, 19, 0,  "🏦 FOMC Rate Decision",        "Federal Reserve interest rate decision — major market mover"),

    # ── CPI (Consumer Price Index — inflation) ──
    (1,  15, 13, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (2,  12, 13, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (3,  12, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (4,  10, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (5,  13, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (6,  11, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (7,  15, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (8,  12, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (9,  11, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (10, 14, 12, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (11, 12, 13, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),
    (12, 10, 13, 30, "📊 US CPI Report",             "Inflation data — directly impacts Fed policy and crypto"),

    # ── NFP (Non-Farm Payrolls — jobs report) ──
    (1,  10, 13, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (2,  7,  13, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (3,  7,  13, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (4,  4,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (5,  2,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (6,  6,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (7,  3,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (8,  7,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (9,  5,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (10, 3,  12, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (11, 6,  13, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),
    (12, 4,  13, 30, "💼 Non-Farm Payrolls",         "US jobs report — risk on/off signal"),

    # ── PPI (Producer Price Index) ──
    (1,  16, 13, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (2,  13, 13, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (3,  13, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (4,  11, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (5,  14, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (6,  12, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (7,  16, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (8,  13, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (9,  12, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (10, 15, 12, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (11, 13, 13, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),
    (12, 11, 13, 30, "🏭 US PPI Report",             "Producer inflation — leads CPI trends"),

    # ── GDP ──
    (1,  30, 13, 30, "📈 US GDP (Advance)",          "Quarterly GDP estimate — economic growth signal"),
    (4,  30, 12, 30, "📈 US GDP (Advance)",          "Quarterly GDP estimate — economic growth signal"),
    (7,  30, 12, 30, "📈 US GDP (Advance)",          "Quarterly GDP estimate — economic growth signal"),
    (10, 30, 12, 30, "📈 US GDP (Advance)",          "Quarterly GDP estimate — economic growth signal"),

    # ── Jackson Hole (Fed annual symposium) ──
    (8,  27, 14, 0,  "🏔️ Jackson Hole Symposium",   "Fed annual speech — major policy hints, big market mover"),

    # ── Bitcoin specific ──
    (4,  17, 0,  0,  "₿ Bitcoin Halving Anniversary","1 year since last halving — historically bullish period"),
]


def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
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


def get_upcoming_events(now, hours_ahead=25):
    """Get events happening within the next X hours."""
    upcoming = []
    for month, day, hour, minute, name, desc in EVENTS_2026:
        try:
            event_time = datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        diff = (event_time - now).total_seconds() / 3600
        if 0 <= diff <= hours_ahead:
            upcoming.append((event_time, diff, name, desc))
    return upcoming


def check_and_alert(sent_log):
    now = datetime.now(timezone.utc)
    events = get_upcoming_events(now, hours_ahead=25)

    for event_time, hours_away, name, desc in events:
        time_str = event_time.strftime("%Y-%m-%d %H:%M UTC")

        # Day before alert (18-26 hours away)
        day_key = f"day_{time_str}"
        if 18 <= hours_away <= 26 and day_key not in sent_log:
            msg = (
                f"📅 <b>TOMORROW — Economic Event</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{name}\n"
                f"🕐 {time_str}\n\n"
                f"ℹ️ {desc}\n\n"
                f"⚠️ <b>Consider reducing risk or waiting for the release before entering new trades.</b>"
            )
            send_alert(msg)
            sent_log.add(day_key)
            log.info(f"Day-before alert sent: {name}")

        # 1 hour before alert
        hour_key = f"1h_{time_str}"
        if 0.5 <= hours_away <= 1.5 and hour_key not in sent_log:
            msg = (
                f"⚠️ <b>1 HOUR WARNING</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{name}\n"
                f"🕐 {time_str}\n\n"
                f"ℹ️ {desc}\n\n"
                f"🚨 <b>High volatility expected. Avoid new entries until after release.</b>"
            )
            send_alert(msg)
            sent_log.add(hour_key)
            log.info(f"1h alert sent: {name}")

        # 15 min before alert
        min_key = f"15m_{time_str}"
        if 0 <= hours_away <= 0.35 and min_key not in sent_log:
            msg = (
                f"🚨 <b>15 MINUTES — EVENT IMMINENT</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{name}\n"
                f"🕐 {time_str}\n\n"
                f"⛔ <b>DO NOT enter new trades. Close risky positions if needed.</b>"
            )
            send_alert(msg)
            sent_log.add(min_key)
            log.info(f"15min alert sent: {name}")

    return sent_log


def send_weekly_preview():
    """Send a weekly summary of upcoming events every Monday."""
    now = datetime.now(timezone.utc)
    upcoming = []
    for month, day, hour, minute, name, desc in EVENTS_2026:
        try:
            event_time = datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        diff_days = (event_time - now).total_seconds() / 86400
        if 0 <= diff_days <= 7:
            upcoming.append((event_time, name))

    if not upcoming:
        return

    lines = [
        "📅 <b>THIS WEEK — Economic Events</b>",
        "━━━━━━━━━━━━━━━━",
    ]
    for event_time, name in sorted(upcoming):
        lines.append(f"• {name} — {event_time.strftime('%a %b %d, %H:%M UTC')}")

    lines.append("\n⚠️ <i>Plan your trades around these dates.</i>")
    send_alert("\n".join(lines))
    log.info("Weekly preview sent.")


if __name__ == "__main__":
    log.info("Economic Calendar Bot started.")
    send_alert("✅ <b>Economic Calendar Bot Online</b>\nMonitoring high impact events for 2026.\nAlerts: Day before + 1 hour before + 15 min before.")

    sent_log = set()
    weekly_sent_date = None

    # Send weekly preview on startup if it's Monday
    now = datetime.now(timezone.utc)
    if now.weekday() == 0:
        send_weekly_preview()
        weekly_sent_date = now.date()

    while True:
        now = datetime.now(timezone.utc)

        # Weekly preview every Monday
        if now.weekday() == 0 and now.date() != weekly_sent_date:
            send_weekly_preview()
            weekly_sent_date = now.date()

        sent_log = check_and_alert(sent_log)
        log.info(f"Calendar check done. {len(sent_log)} alerts sent so far.")
        time.sleep(900)  # check every 15 minutes