"""
Backtesting Engine — EMA 12/21 Cross Strategy
Tests your existing signal on historical data.
Shows: win rate, profit factor, max drawdown, best/worst coins.

Usage: python backtest.py
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timezone, timedelta

# ── Settings ──────────────────────────────────────────────
EMA_FAST = 12
EMA_SLOW = 21
STOP_LOSS_PCT = 3.0       # stop loss %
TAKE_PROFIT_PCT = 6.0     # take profit %
TIMEFRAME = "1h"          # "1h" or "4h"
LOOKBACK_DAYS = 180       # 6 months

# Top coins to backtest
COINS = [
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX",
    "DOT", "LINK", "UNI", "LTC", "APT", "NEAR", "ARB", "OP",
    "ATOM", "AAVE", "PEPE", "INJ", "SUI", "FET", "RNDR", "SEI",
]

GRANULARITY_MAP = {
    "1h": {"api": "ONE_HOUR", "seconds": 3600},
    "4h": {"api": "FOUR_HOUR", "seconds": 14400},
}


def calc_ema(values, period):
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def fetch_candles(ticker, timeframe, days):
    """Fetch historical candles from Coinbase with pagination."""
    product_id = f"{ticker}-USD"
    granularity = GRANULARITY_MAP[timeframe]["api"]
    candle_secs = GRANULARITY_MAP[timeframe]["seconds"]

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    all_candles = []
    current_end = end

    while current_end > start:
        current_start = max(current_end - timedelta(hours=300 if timeframe == "1h" else 1200), start)

        params = {
            "granularity": granularity,
            "start": int(current_start.timestamp()),
            "end": int(current_end.timestamp()),
        }

        try:
            r = requests.get(
                f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles",
                params=params,
                timeout=15,
            )
            data = r.json()
            candles = data.get("candles", [])
            if not candles:
                break

            all_candles.extend(candles)
            # Move window back
            oldest = min(int(c["start"]) for c in candles)
            current_end = datetime.fromtimestamp(oldest, tz=timezone.utc)

        except Exception as e:
            print(f"    Error: {e}")
            break

        time.sleep(0.15)

    # Deduplicate by timestamp and sort
    seen = set()
    unique = []
    for c in all_candles:
        ts = c["start"]
        if ts not in seen:
            seen.add(ts)
            unique.append(c)

    unique.sort(key=lambda c: int(c["start"]))

    # Parse into lists
    closes = [float(c["close"]) for c in unique]
    highs = [float(c["high"]) for c in unique]
    lows = [float(c["low"]) for c in unique]
    timestamps = [int(c["start"]) for c in unique]

    return closes, highs, lows, timestamps


def find_signals(closes):
    """Find all EMA cross points."""
    ema_fast = calc_ema(closes, EMA_FAST)
    ema_slow = calc_ema(closes, EMA_SLOW)

    signals = []
    for i in range(1, len(closes)):
        prev_fast = ema_fast[i - 1]
        prev_slow = ema_slow[i - 1]
        curr_fast = ema_fast[i]
        curr_slow = ema_slow[i]

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            signals.append({"index": i, "direction": "LONG", "price": closes[i]})
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            signals.append({"index": i, "direction": "SHORT", "price": closes[i]})

    return signals


def simulate_trades(closes, highs, lows, timestamps, signals):
    """Simulate trades with stop loss and take profit."""
    trades = []
    i = 0

    while i < len(signals):
        signal = signals[i]
        entry_idx = signal["index"]
        direction = signal["direction"]
        entry_price = signal["price"]

        if direction != "LONG":
            i += 1
            continue

        sl_price = entry_price * (1 - STOP_LOSS_PCT / 100)
        tp_price = entry_price * (1 + TAKE_PROFIT_PCT / 100)

        exit_price = None
        exit_reason = None
        exit_idx = None

        # Walk forward from entry
        for j in range(entry_idx + 1, len(closes)):
            # Check stop loss (hit low)
            if lows[j] <= sl_price:
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
                exit_idx = j
                break

            # Check take profit (hit high)
            if highs[j] >= tp_price:
                exit_price = tp_price
                exit_reason = "TAKE_PROFIT"
                exit_idx = j
                break

            # Check for opposite signal (bearish cross)
            for s in signals:
                if s["index"] == j and s["direction"] == "SHORT":
                    exit_price = closes[j]
                    exit_reason = "SIGNAL_EXIT"
                    exit_idx = j
                    break

            if exit_price:
                break

        if exit_price is None:
            # Still in trade, use last close
            exit_price = closes[-1]
            exit_reason = "OPEN"
            exit_idx = len(closes) - 1

        pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        entry_time = datetime.fromtimestamp(timestamps[entry_idx], tz=timezone.utc)
        exit_time = datetime.fromtimestamp(timestamps[exit_idx], tz=timezone.utc)
        hold_hours = (exit_time - entry_time).total_seconds() / 3600

        trades.append({
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "entry_time": entry_time.strftime("%Y-%m-%d %H:%M"),
            "exit_time": exit_time.strftime("%Y-%m-%d %H:%M"),
            "hold_hours": hold_hours,
        })

        # Skip to after exit
        i += 1
        while i < len(signals) and signals[i]["index"] <= exit_idx:
            i += 1

    return trades


def calc_metrics(trades):
    """Calculate performance metrics."""
    if not trades:
        return None

    closed = [t for t in trades if t["exit_reason"] != "OPEN"]
    if not closed:
        return None

    wins = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] <= 0]

    total_trades = len(closed)
    win_rate = len(wins) / total_trades * 100 if total_trades else 0

    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    total_return = sum(t["pnl_pct"] for t in closed)
    avg_hold = sum(t["hold_hours"] for t in closed) / len(closed) if closed else 0

    # Max drawdown
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in closed:
        cumulative += t["pnl_pct"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Exit reason breakdown
    tp_count = len([t for t in closed if t["exit_reason"] == "TAKE_PROFIT"])
    sl_count = len([t for t in closed if t["exit_reason"] == "STOP_LOSS"])
    sig_count = len([t for t in closed if t["exit_reason"] == "SIGNAL_EXIT"])

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "avg_hold_hours": avg_hold,
        "tp_exits": tp_count,
        "sl_exits": sl_count,
        "signal_exits": sig_count,
    }


def print_results(coin_results):
    """Print formatted backtest results."""
    print(f"\n{'═' * 65}")
    print(f"  BACKTEST RESULTS — EMA {EMA_FAST}/{EMA_SLOW} Cross")
    print(f"  Timeframe: {TIMEFRAME} | Lookback: {LOOKBACK_DAYS} days")
    print(f"  Stop Loss: {STOP_LOSS_PCT}% | Take Profit: {TAKE_PROFIT_PCT}%")
    print(f"{'═' * 65}\n")

    # Per-coin results
    print(f"  {'Coin':<8} {'Trades':<8} {'Win%':<8} {'Avg Win':<10} {'Avg Loss':<10} {'PF':<8} {'Return':<10} {'MaxDD':<8}")
    print(f"  {'─' * 62}")

    all_trades = []
    for coin, data in sorted(coin_results.items(), key=lambda x: x[1]["metrics"]["total_return"] if x[1]["metrics"] else -999, reverse=True):
        m = data["metrics"]
        if not m:
            print(f"  {coin:<8} {'—':<8} no trades")
            continue

        all_trades.extend(data["trades"])

        pf_str = f"{m['profit_factor']:.1f}" if m['profit_factor'] != float('inf') else "∞"
        print(
            f"  {coin:<8} "
            f"{m['total_trades']:<8} "
            f"{m['win_rate']:.0f}%{'':>4} "
            f"+{m['avg_win']:.1f}%{'':>4} "
            f"{m['avg_loss']:.1f}%{'':>4} "
            f"{pf_str:<8} "
            f"{m['total_return']:>+.1f}%{'':>3} "
            f"{m['max_drawdown']:.1f}%"
        )

    # Overall metrics
    overall = calc_metrics(all_trades)
    if overall:
        print(f"\n  {'─' * 62}")
        pf_str = f"{overall['profit_factor']:.1f}" if overall['profit_factor'] != float('inf') else "∞"
        print(
            f"  {'TOTAL':<8} "
            f"{overall['total_trades']:<8} "
            f"{overall['win_rate']:.0f}%{'':>4} "
            f"+{overall['avg_win']:.1f}%{'':>4} "
            f"{overall['avg_loss']:.1f}%{'':>4} "
            f"{pf_str:<8} "
            f"{overall['total_return']:>+.1f}%{'':>3} "
            f"{overall['max_drawdown']:.1f}%"
        )

        print(f"\n  {'─' * 62}")
        print(f"  Exit Breakdown:")
        print(f"    Take Profit: {overall['tp_exits']} ({overall['tp_exits']/overall['total_trades']*100:.0f}%)")
        print(f"    Stop Loss:   {overall['sl_exits']} ({overall['sl_exits']/overall['total_trades']*100:.0f}%)")
        print(f"    Signal Exit: {overall['signal_exits']} ({overall['signal_exits']/overall['total_trades']*100:.0f}%)")
        print(f"    Avg Hold:    {overall['avg_hold_hours']:.0f} hours")

    # Top 3 and Bottom 3
    ranked = [(coin, data["metrics"]["total_return"]) for coin, data in coin_results.items() if data["metrics"]]
    ranked.sort(key=lambda x: x[1], reverse=True)

    if len(ranked) >= 3:
        print(f"\n  Top 3:    {ranked[0][0]} ({ranked[0][1]:+.1f}%), {ranked[1][0]} ({ranked[1][1]:+.1f}%), {ranked[2][0]} ({ranked[2][1]:+.1f}%)")
        print(f"  Bottom 3: {ranked[-1][0]} ({ranked[-1][1]:+.1f}%), {ranked[-2][0]} ({ranked[-2][1]:+.1f}%), {ranked[-3][0]} ({ranked[-3][1]:+.1f}%)")

    print(f"\n{'═' * 65}")


def save_results(coin_results, overall_trades):
    """Save detailed results to JSON."""
    output = {
        "settings": {
            "ema_fast": EMA_FAST,
            "ema_slow": EMA_SLOW,
            "timeframe": TIMEFRAME,
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "lookback_days": LOOKBACK_DAYS,
        },
        "coins": {},
        "overall": calc_metrics(overall_trades),
    }

    for coin, data in coin_results.items():
        output["coins"][coin] = {
            "metrics": data["metrics"],
            "trades": data["trades"],
        }

    filepath = f"backtest_EMA{EMA_FAST}_{EMA_SLOW}_{TIMEFRAME}_{LOOKBACK_DAYS}d.json"
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Detailed results saved → {filepath}")


def run():
    print("=" * 40)
    print("  BACKTESTING ENGINE")
    print("=" * 40)
    print(f"\n  Strategy:  EMA {EMA_FAST}/{EMA_SLOW} Cross (Long only)")
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Period:    Last {LOOKBACK_DAYS} days")
    print(f"  SL/TP:     {STOP_LOSS_PCT}% / {TAKE_PROFIT_PCT}%")
    print(f"  Coins:     {len(COINS)}")
    print(f"\n  Fetching data...\n")

    coin_results = {}
    all_trades = []

    for i, coin in enumerate(COINS, 1):
        print(f"  [{i}/{len(COINS)}] {coin}...", end=" ")

        closes, highs, lows, timestamps = fetch_candles(coin, TIMEFRAME, LOOKBACK_DAYS)

        if not closes or len(closes) < 50:
            print(f"insufficient data ({len(closes) if closes else 0} candles)")
            coin_results[coin] = {"metrics": None, "trades": []}
            continue

        signals = find_signals(closes)
        trades = simulate_trades(closes, highs, lows, timestamps, signals)
        metrics = calc_metrics(trades)

        coin_results[coin] = {"metrics": metrics, "trades": trades}
        all_trades.extend(trades)

        trade_count = metrics["total_trades"] if metrics else 0
        ret = f"{metrics['total_return']:+.1f}%" if metrics else "—"
        print(f"{len(closes)} candles, {trade_count} trades, return: {ret}")

        time.sleep(0.2)

    print_results(coin_results)
    save_results(coin_results, all_trades)


if __name__ == "__main__":
    run()