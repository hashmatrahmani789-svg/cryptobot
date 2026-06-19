"""
Economic Calendar Bot
=====================
Monitors high-impact macro events and sends Telegram alerts:
  • Day before   — full explainer
  • 1 hour before
  • 15 min before

All alert times displayed in Pacific Time (Seattle, WA).
Handles PST (UTC-8) and PDT (UTC-7) automatically via zoneinfo.

Env vars required:
  TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CALENDAR] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

PACIFIC = ZoneInfo("America/Los_Angeles")


def fmt_local(dt_utc):
    """Convert a UTC datetime to Pacific Time and return a readable string."""
    dt_pt  = dt_utc.astimezone(PACIFIC)
    tz_abbr = dt_pt.strftime("%Z")   # PDT or PST automatically
    return dt_pt.strftime(f"%a %b %d, %I:%M %p {tz_abbr}")


# ── Event types ───────────────────────────────────────────────────────────────
EVENT_TYPES = {
    "FOMC": {
        "name": "🏦 FOMC Rate Decision",
        "impact": "Federal Reserve interest rate decision — biggest scheduled market mover",
        "explain": (
            "<b>What it is:</b> The Fed sets the US benchmark interest rate 8x/year. "
            "They raise rates to fight inflation, cut them to boost the economy.\n"
            "<b>How it moves crypto:</b> High rates = money is 'expensive', investors flee "
            "risky assets like crypto into safe bonds → bearish. Rate cuts = cheap money "
            "flows into risk assets → bullish. The press conference 30 min after can move "
            "markets even more than the decision itself."
        ),
    },
    "FOMC_MINUTES": {
        "name": "📝 FOMC Minutes",
        "impact": "Detailed notes from the last Fed meeting — reveals their thinking",
        "explain": (
            "<b>What it is:</b> The full written record of the last FOMC meeting, released "
            "3 weeks later.\n"
            "<b>How it moves crypto:</b> Traders dig through it for hints on future rate "
            "moves. Hawkish tone (worried about inflation) → bearish. Dovish tone (ready to "
            "cut) → bullish. Less impactful than the decision but can still cause spikes."
        ),
    },
    "CPI": {
        "name": "📊 US CPI Report",
        "impact": "Headline inflation data — directly drives Fed policy",
        "explain": (
            "<b>What it is:</b> Consumer Price Index — measures how much prices for everyday "
            "goods (food, gas, rent) rose vs last year. This is THE inflation number.\n"
            "<b>How it moves crypto:</b> Hot CPI (inflation higher than expected) → Fed likely "
            "keeps rates high → bearish for crypto. Cool CPI (inflation falling) → rate cuts "
            "more likely → bullish. One of the most volatile releases of the month."
        ),
    },
    "CORE_PCE": {
        "name": "🎯 Core PCE",
        "impact": "The Fed's preferred inflation gauge",
        "explain": (
            "<b>What it is:</b> Personal Consumption Expenditures, excluding food & energy. "
            "This is the inflation metric the Fed actually targets (2% goal).\n"
            "<b>How it moves crypto:</b> Because the Fed watches this more than CPI, a "
            "surprise here strongly shifts rate expectations. Higher = bearish, lower = bullish."
        ),
    },
    "PPI": {
        "name": "🏭 US PPI Report",
        "impact": "Producer inflation — leads CPI trends",
        "explain": (
            "<b>What it is:</b> Producer Price Index — measures inflation at the wholesale "
            "level (what businesses pay before passing costs to consumers).\n"
            "<b>How it moves crypto:</b> Often seen as an early warning for CPI. Rising PPI "
            "hints future consumer inflation → can pressure crypto. Milder reaction than CPI."
        ),
    },
    "NFP": {
        "name": "💼 Non-Farm Payrolls",
        "impact": "US jobs report — risk on/off signal",
        "explain": (
            "<b>What it is:</b> How many jobs the US added last month (excluding farm work). "
            "Released first Friday of the month with the unemployment rate.\n"
            "<b>How it moves crypto:</b> Strong jobs = hot economy = Fed can keep rates high "
            "→ often bearish for crypto. Weak jobs = economy cooling = rate cuts likely → "
            "bullish. Counterintuitive: 'bad news' for jobs is often 'good news' for crypto."
        ),
    },
    "UNEMPLOYMENT": {
        "name": "📉 Unemployment Rate",
        "impact": "Share of people jobless — health of the labor market",
        "explain": (
            "<b>What it is:</b> The % of the workforce without a job. Released with NFP.\n"
            "<b>How it moves crypto:</b> Rising unemployment signals a weakening economy → "
            "pushes the Fed toward rate cuts → bullish for risk assets. Low unemployment → "
            "Fed stays tight → bearish."
        ),
    },
    "JOBLESS": {
        "name": "🗂️ Initial Jobless Claims",
        "impact": "Weekly layoffs data — real-time labor pulse",
        "explain": (
            "<b>What it is:</b> Number of people who filed for unemployment for the first "
            "time last week. Released every Thursday.\n"
            "<b>How it moves crypto:</b> A high-frequency read on the job market. Sudden jumps "
            "can hint at recession (bullish for rate-cut bets). Usually a minor mover unless "
            "the number is a big surprise."
        ),
    },
    "RETAIL": {
        "name": "🛍️ US Retail Sales",
        "impact": "Consumer spending strength",
        "explain": (
            "<b>What it is:</b> Total spending at retail stores — shows how confident and "
            "flush US consumers are.\n"
            "<b>How it moves crypto:</b> Strong spending = robust economy = Fed stays tight "
            "→ can pressure crypto. Weak spending = slowdown = rate-cut hopes → supportive."
        ),
    },
    "GDP": {
        "name": "📈 US GDP",
        "impact": "Quarterly economic growth scorecard",
        "explain": (
            "<b>What it is:</b> Gross Domestic Product — the total value of everything the US "
            "economy produced last quarter. The headline measure of growth.\n"
            "<b>How it moves crypto:</b> Strong growth = healthy economy but also less reason "
            "to cut rates. A contraction (negative GDP) raises recession fears, which can "
            "boost rate-cut bets and risk appetite. Reaction depends on the broader narrative."
        ),
    },
    "ISM_MFG": {
        "name": "🏗️ ISM Manufacturing PMI",
        "impact": "Factory activity gauge",
        "explain": (
            "<b>What it is:</b> A survey of manufacturers. Above 50 = expansion, below 50 = "
            "contraction.\n"
            "<b>How it moves crypto:</b> A leading indicator of economic health. Weak readings "
            "signal a slowing economy → rate-cut hopes → can support crypto. Moderate mover."
        ),
    },
    "ISM_SVC": {
        "name": "🛎️ ISM Services PMI",
        "impact": "Services sector activity gauge",
        "explain": (
            "<b>What it is:</b> Same as manufacturing PMI but for the services sector, which "
            "is the bulk of the US economy. Above 50 = expansion.\n"
            "<b>How it moves crypto:</b> A strong services economy keeps the Fed cautious on "
            "cuts. Weakness fuels easing bets. Generally a moderate mover."
        ),
    },
    "CONSUMER_CONF": {
        "name": "🙂 Consumer Confidence",
        "impact": "How optimistic consumers feel",
        "explain": (
            "<b>What it is:</b> A survey measuring how confident people feel about the economy "
            "and their finances.\n"
            "<b>How it moves crypto:</b> Confident consumers spend more → economic strength. "
            "Falling confidence can signal a coming slowdown. Usually a minor mover."
        ),
    },
    "JACKSON_HOLE": {
        "name": "🏔️ Jackson Hole Symposium",
        "impact": "Fed annual policy speech — major mover",
        "explain": (
            "<b>What it is:</b> An annual gathering where the Fed Chair often signals big "
            "shifts in monetary policy direction.\n"
            "<b>How it moves crypto:</b> Powell's speech here has historically caused sharp "
            "moves. Hawkish surprises crush risk assets; dovish hints rally them. Watch closely."
        ),
    },
    "POWELL_SPEECH": {
        "name": "🎤 Fed Chair Speech",
        "impact": "Powell remarks — can move markets on a sentence",
        "explain": (
            "<b>What it is:</b> A scheduled public speech by the Fed Chair.\n"
            "<b>How it moves crypto:</b> A single sentence about rates or inflation can swing "
            "markets. Tone matters more than content. Volatility risk during the speech window."
        ),
    },
    "BTC_HALVING": {
        "name": "₿ Bitcoin Halving Anniversary",
        "impact": "Historically bullish period for BTC",
        "explain": (
            "<b>What it is:</b> Marks years since the last Bitcoin halving (when mining "
            "rewards get cut in half, reducing new BTC supply).\n"
            "<b>How it moves crypto:</b> Historically, the 12-18 months after a halving have "
            "been strong for BTC due to the supply squeeze. Not a guarantee — sentiment marker."
        ),
    },
}

# ── Scheduled events for 2026 (all times in UTC) ──────────────────────────────
# Format: (month, day, hour_utc, minute_utc, type_key)
EVENTS_2026 = [
    # FOMC Rate Decisions
    (1, 29, 19, 0, "FOMC"), (3, 19, 18, 0, "FOMC"), (5, 7, 18, 0, "FOMC"),
    (6, 18, 18, 0, "FOMC"), (7, 30, 18, 0, "FOMC"), (9, 17, 18, 0, "FOMC"),
    (11, 5, 19, 0, "FOMC"), (12, 17, 19, 0, "FOMC"),

    # FOMC Minutes
    (2, 18, 19, 0, "FOMC_MINUTES"), (4, 8, 18, 0, "FOMC_MINUTES"),
    (5, 28, 18, 0, "FOMC_MINUTES"), (7, 8, 18, 0, "FOMC_MINUTES"),
    (8, 19, 18, 0, "FOMC_MINUTES"), (10, 7, 18, 0, "FOMC_MINUTES"),
    (11, 25, 19, 0, "FOMC_MINUTES"),

    # CPI
    (1, 15, 13, 30, "CPI"), (2, 12, 13, 30, "CPI"), (3, 12, 12, 30, "CPI"),
    (4, 10, 12, 30, "CPI"), (5, 13, 12, 30, "CPI"), (6, 11, 12, 30, "CPI"),
    (7, 15, 12, 30, "CPI"), (8, 12, 12, 30, "CPI"), (9, 11, 12, 30, "CPI"),
    (10, 14, 12, 30, "CPI"), (11, 12, 13, 30, "CPI"), (12, 10, 13, 30, "CPI"),

    # Core PCE
    (1, 30, 13, 30, "CORE_PCE"), (2, 27, 13, 30, "CORE_PCE"), (3, 27, 12, 30, "CORE_PCE"),
    (4, 30, 12, 30, "CORE_PCE"), (5, 29, 12, 30, "CORE_PCE"), (6, 26, 12, 30, "CORE_PCE"),
    (7, 31, 12, 30, "CORE_PCE"), (8, 28, 12, 30, "CORE_PCE"), (9, 25, 12, 30, "CORE_PCE"),
    (10, 30, 12, 30, "CORE_PCE"), (11, 25, 13, 30, "CORE_PCE"), (12, 23, 13, 30, "CORE_PCE"),

    # PPI
    (1, 16, 13, 30, "PPI"), (2, 13, 13, 30, "PPI"), (3, 13, 12, 30, "PPI"),
    (4, 11, 12, 30, "PPI"), (5, 14, 12, 30, "PPI"), (6, 12, 12, 30, "PPI"),
    (7, 16, 12, 30, "PPI"), (8, 13, 12, 30, "PPI"), (9, 12, 12, 30, "PPI"),
    (10, 15, 12, 30, "PPI"), (11, 13, 13, 30, "PPI"), (12, 11, 13, 30, "PPI"),

    # NFP + Unemployment (first Friday)
    (1, 10, 13, 30, "NFP"), (2, 7, 13, 30, "NFP"), (3, 7, 13, 30, "NFP"),
    (4, 4, 12, 30, "NFP"), (5, 2, 12, 30, "NFP"), (6, 6, 12, 30, "NFP"),
    (7, 3, 12, 30, "NFP"), (8, 7, 12, 30, "NFP"), (9, 5, 12, 30, "NFP"),
    (10, 3, 12, 30, "NFP"), (11, 6, 13, 30, "NFP"), (12, 4, 13, 30, "NFP"),

    # Retail Sales
    (1, 16, 13, 30, "RETAIL"), (2, 17, 13, 30, "RETAIL"), (3, 16, 12, 30, "RETAIL"),
    (4, 15, 12, 30, "RETAIL"), (5, 15, 12, 30, "RETAIL"), (6, 16, 12, 30, "RETAIL"),
    (7, 16, 12, 30, "RETAIL"), (8, 14, 12, 30, "RETAIL"), (9, 16, 12, 30, "RETAIL"),
    (10, 15, 12, 30, "RETAIL"), (11, 17, 13, 30, "RETAIL"), (12, 16, 13, 30, "RETAIL"),

    # GDP (Advance, quarterly)
    (1, 29, 13, 30, "GDP"), (4, 29, 12, 30, "GDP"),
    (7, 30, 12, 30, "GDP"), (10, 29, 12, 30, "GDP"),

    # ISM Manufacturing
    (1, 2, 15, 0, "ISM_MFG"), (2, 2, 15, 0, "ISM_MFG"), (3, 2, 15, 0, "ISM_MFG"),
    (4, 1, 14, 0, "ISM_MFG"), (5, 1, 14, 0, "ISM_MFG"), (6, 1, 14, 0, "ISM_MFG"),
    (7, 1, 14, 0, "ISM_MFG"), (8, 3, 14, 0, "ISM_MFG"), (9, 1, 14, 0, "ISM_MFG"),
    (10, 1, 14, 0, "ISM_MFG"), (11, 2, 15, 0, "ISM_MFG"), (12, 1, 15, 0, "ISM_MFG"),

    # ISM Services
    (1, 6, 15, 0, "ISM_SVC"), (2, 4, 15, 0, "ISM_SVC"), (3, 4, 15, 0, "ISM_SVC"),
    (4, 3, 14, 0, "ISM_SVC"), (5, 5, 14, 0, "ISM_SVC"), (6, 3, 14, 0, "ISM_SVC"),
    (7, 6, 14, 0, "ISM_SVC"), (8, 5, 14, 0, "ISM_SVC"), (9, 3, 14, 0, "ISM_SVC"),
    (10, 5, 14, 0, "ISM_SVC"), (11, 4, 15, 0, "ISM_SVC"), (12, 3, 15, 0, "ISM_SVC"),

    # Consumer Confidence
    (1, 27, 15, 0, "CONSUMER_CONF"), (2, 24, 15, 0, "CONSUMER_CONF"),
    (3, 31, 14, 0, "CONSUMER_CONF"), (4, 28, 14, 0, "CONSUMER_CONF"),
    (5, 26, 14, 0, "CONSUMER_CONF"), (6, 30, 14, 0, "CONSUMER_CONF"),
    (7, 28, 14, 0, "CONSUMER_CONF"), (8, 25, 14, 0, "CONSUMER_CONF"),
    (9, 29, 14, 0, "CONSUMER_CONF"), (10, 27, 14, 0, "CONSUMER_CONF"),
    (11, 24, 15, 0, "CONSUMER_CONF"), (12, 22, 15, 0, "CONSUMER_CONF"),

    # Jackson Hole
    (8, 27, 14, 0, "JACKSON_HOLE"),

    # Bitcoin halving anniversary
    (4, 17, 0, 0, "BTC_HALVING"),
]


def send_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials missing.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     message,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if r.status_code == 200:
            log.info("Telegram alert sent.")
        else:
            log.error(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")


def get_upcoming_events(now, hours_ahead=26):
    upcoming = []
    for month, day, hour, minute, type_key in EVENTS_2026:
        try:
            event_time = datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        diff = (event_time - now).total_seconds() / 3600
        if 0 <= diff <= hours_ahead:
            upcoming.append((event_time, diff, type_key))
    return upcoming


def check_and_alert(sent_log):
    now    = datetime.now(timezone.utc)
    events = get_upcoming_events(now, hours_ahead=26)

    for event_time, hours_away, type_key in events:
        et      = EVENT_TYPES[type_key]
        name    = et["name"]
        impact  = et["impact"]
        explain = et["explain"]
        local   = fmt_local(event_time)        # ← Pacific Time display

        # Day-before alert (includes full explainer)
        day_key = f"day_{event_time.isoformat()}_{type_key}"
        if 18 <= hours_away <= 26 and day_key not in sent_log:
            msg = (
                f"📅 <b>TOMORROW — Economic Event</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{name}\n"
                f"🕐 {local}\n\n"
                f"ℹ️ {impact}\n\n"
                f"{explain}\n\n"
                f"⚠️ <b>Consider reducing risk or waiting for the release before new trades.</b>"
            )
            send_alert(msg)
            sent_log.add(day_key)
            log.info(f"Day-before alert sent: {name} @ {local}")

        # 1 hour before
        hour_key = f"1h_{event_time.isoformat()}_{type_key}"
        if 0.5 <= hours_away <= 1.5 and hour_key not in sent_log:
            msg = (
                f"⚠️ <b>1 HOUR WARNING</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{name}\n"
                f"🕐 {local}\n\n"
                f"ℹ️ {impact}\n\n"
                f"🚨 <b>High volatility expected. Avoid new entries until after release.</b>"
            )
            send_alert(msg)
            sent_log.add(hour_key)
            log.info(f"1h alert sent: {name} @ {local}")

        # 15 min before
        min_key = f"15m_{event_time.isoformat()}_{type_key}"
        if 0 <= hours_away <= 0.35 and min_key not in sent_log:
            msg = (
                f"🚨 <b>15 MINUTES — EVENT IMMINENT</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{name}\n"
                f"🕐 {local}\n\n"
                f"⛔ <b>DO NOT enter new trades. Close risky positions if needed.</b>"
            )
            send_alert(msg)
            sent_log.add(min_key)
            log.info(f"15min alert sent: {name} @ {local}")

    return sent_log


def send_weekly_preview():
    now      = datetime.now(timezone.utc)
    upcoming = []
    for month, day, hour, minute, type_key in EVENTS_2026:
        try:
            event_time = datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            continue
        diff_days = (event_time - now).total_seconds() / 86400
        if 0 <= diff_days <= 7:
            upcoming.append((event_time, EVENT_TYPES[type_key]["name"]))

    if not upcoming:
        return

    lines = [
        "📅 <b>THIS WEEK — Economic Events (Pacific Time)</b>",
        "━━━━━━━━━━━━━━━━",
    ]
    for event_time, name in sorted(upcoming):
        lines.append(f"• {name} — {fmt_local(event_time)}")

    lines.append("\n⚠️ <i>Plan your trades around these dates.</i>")
    send_alert("\n".join(lines))
    log.info("Weekly preview sent.")


if __name__ == "__main__":
    log.info("Economic Calendar Bot started.")

    # Show current Pacific offset on startup
    now_pt   = datetime.now(PACIFIC)
    tz_abbr  = now_pt.strftime("%Z")
    utc_off  = now_pt.strftime("%z")
    utc_disp = f"UTC{utc_off[:3]}:{utc_off[3:]}"

    send_alert(
        f"✅ <b>Economic Calendar Bot Online</b>\n"
        f"📍 All times shown in Pacific Time ({tz_abbr} / {utc_disp})\n"
        f"Alerts: Day before (with full explainer) + 1 hour + 15 min.\n\n"
        f"Tracking: FOMC, CPI, Core PCE, PPI, NFP, Unemployment, Retail Sales, "
        f"GDP, ISM PMIs, Consumer Confidence, Jackson Hole & more."
    )

    sent_log         = set()
    weekly_sent_date = None

    now = datetime.now(timezone.utc)
    if now.weekday() == 0:
        send_weekly_preview()
        weekly_sent_date = now.date()

    while True:
        now = datetime.now(timezone.utc)
        if now.weekday() == 0 and now.date() != weekly_sent_date:
            send_weekly_preview()
            weekly_sent_date = now.date()

        sent_log = check_and_alert(sent_log)
        log.info(f"Calendar check done. {len(sent_log)} alerts sent so far.")
        time.sleep(900)