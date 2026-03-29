# -*- coding: utf-8 -*-
# run_backtest.py — Immutable Eval Harness for Ruppert Backtest
# NEVER modify this file from the autoresearch loop.
# Deterministic: same params = same output every time.

import argparse
import json
import math
import sys
from pathlib import Path

from backtest_engine import run_backtest
from strategy_simulator import DEFAULT_CONFIG


def load_config(config_path: str | None) -> dict:
    """
    Load strategy config from a JSON file, or fall back to DEFAULT_CONFIG.
    The JSON file may contain a subset of keys — missing keys inherit from DEFAULT_CONFIG.
    """
    cfg = dict(DEFAULT_CONFIG)
    if config_path:
        p = Path(config_path)
        if not p.exists():
            print(f"ERROR: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        with open(p, "r", encoding="utf-8") as f:
            overrides = json.load(f)
        cfg.update(overrides)
    return cfg


def split_trades_by_date(trades: list, split_pct: float = 0.70) -> tuple:
    """
    Split trades into in-sample (first split_pct by date) and out-of-sample (rest).
    Returns (in_sample_trades, out_of_sample_trades, split_date).
    """
    if not trades:
        return [], [], ""

    # Get unique sorted dates
    dates = sorted(set(t["settle_date"] for t in trades if t.get("settle_date")))
    if not dates:
        return trades, [], ""

    split_idx = max(1, int(len(dates) * split_pct))
    split_date = dates[min(split_idx, len(dates) - 1)]

    in_dates = set(dates[:split_idx])
    out_dates = set(dates[split_idx:])

    in_sample = [t for t in trades if t.get("settle_date") in in_dates]
    out_sample = [t for t in trades if t.get("settle_date") in out_dates]

    return in_sample, out_sample, split_date


def compute_metrics(trades: list, starting_capital: float) -> dict:
    """Compute Sharpe ratio, win rate, P&L, trade count from a list of trade records."""
    if not trades:
        return {
            "sharpe": 0.0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "trade_count": 0,
            "avg_pnl": 0.0,
            "max_drawdown": 0.0,
        }

    pnls = [t["pnl"] for t in trades]
    total_pnl = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / len(pnls) if pnls else 0.0
    avg_pnl = total_pnl / len(pnls) if pnls else 0.0

    # Sharpe ratio: mean(daily_pnl) / std(daily_pnl) * sqrt(252)
    # Group PnL by date for daily returns
    daily = {}
    for t in trades:
        d = t.get("settle_date", "unknown")
        daily[d] = daily.get(d, 0.0) + t["pnl"]

    daily_pnls = list(daily.values())
    if len(daily_pnls) >= 2:
        mean_d = sum(daily_pnls) / len(daily_pnls)
        var_d = sum((x - mean_d) ** 2 for x in daily_pnls) / (len(daily_pnls) - 1)
        std_d = math.sqrt(var_d) if var_d > 0 else 0.0
        sharpe = (mean_d / std_d) * math.sqrt(252) if std_d > 0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown
    capital = starting_capital
    peak = capital
    max_dd = 0.0
    for d in sorted(daily.keys()):
        capital += daily[d]
        peak = max(peak, capital)
        dd = (peak - capital) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    return {
        "sharpe": round(sharpe, 4),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 4),
        "trade_count": len(trades),
        "avg_pnl": round(avg_pnl, 4),
        "max_drawdown": round(max_dd, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Ruppert Backtest Eval Harness")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to JSON config override file")
    parser.add_argument("--start-date", type=str, default="2026-02-27")
    parser.add_argument("--end-date", type=str, default="2026-03-13")
    parser.add_argument("--capital", type=float, default=400.0)
    parser.add_argument("--split-pct", type=float, default=0.70,
                        help="In-sample fraction (default 0.70)")
    parser.add_argument("--min-trades", type=int, default=30,
                        help="Minimum trades per split for validity (default 30)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only output METRIC lines (for autoresearch parsing)")
    args = parser.parse_args()

    config = load_config(args.config)

    # Run full backtest
    results = run_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        config=config,
        starting_capital=args.capital,
    )

    trades = results["trades"]

    # Split into in-sample / out-of-sample
    in_trades, out_trades, split_date = split_trades_by_date(trades, args.split_pct)

    m_all = compute_metrics(trades, args.capital)
    m_in = compute_metrics(in_trades, args.capital)
    m_out = compute_metrics(out_trades, args.capital)

    # Validity check
    valid = True
    invalid_reasons = []
    if m_in["trade_count"] < args.min_trades:
        valid = False
        invalid_reasons.append(f"in-sample trades {m_in['trade_count']} < {args.min_trades}")
    if m_out["trade_count"] < args.min_trades:
        valid = False
        invalid_reasons.append(f"out-of-sample trades {m_out['trade_count']} < {args.min_trades}")

    # Output METRIC lines (parsed by autoresearch.py)
    if not valid:
        print(f"METRIC_IN: INVALID")
        print(f"METRIC_OUT: INVALID")
        print(f"METRIC: INVALID")
        if not args.quiet:
            print(f"INVALID_REASON: {'; '.join(invalid_reasons)}")
    else:
        print(f"METRIC_IN: {m_in['sharpe']}")
        print(f"METRIC_OUT: {m_out['sharpe']}")
        # Combined metric: average of in-sample and out-of-sample Sharpe
        combined = round((m_in["sharpe"] + m_out["sharpe"]) / 2, 4)
        print(f"METRIC: {combined}")

    # Summary output
    if not args.quiet:
        print()
        print("=" * 60)
        print("BACKTEST SUMMARY")
        print("=" * 60)
        print(f"Date range:       {args.start_date} to {args.end_date}")
        print(f"Starting capital: ${args.capital:.2f}")
        print(f"Ending capital:   ${results['ending_capital']:.2f}")
        print(f"Split date:       {split_date} (in-sample < | >= out-of-sample)")
        print()

        print(f"{'':20s} {'ALL':>10s} {'IN-SAMPLE':>12s} {'OUT-OF-SAMPLE':>14s}")
        print("-" * 60)
        print(f"{'Trade count':20s} {m_all['trade_count']:10d} {m_in['trade_count']:12d} {m_out['trade_count']:14d}")
        print(f"{'Win rate':20s} {m_all['win_rate']:10.1%} {m_in['win_rate']:12.1%} {m_out['win_rate']:14.1%}")
        print(f"{'Total P&L':20s} ${m_all['total_pnl']:9.2f} ${m_in['total_pnl']:11.2f} ${m_out['total_pnl']:13.2f}")
        print(f"{'Avg P&L/trade':20s} ${m_all['avg_pnl']:9.2f} ${m_in['avg_pnl']:11.2f} ${m_out['avg_pnl']:13.2f}")
        print(f"{'Sharpe ratio':20s} {m_all['sharpe']:10.4f} {m_in['sharpe']:12.4f} {m_out['sharpe']:14.4f}")
        print(f"{'Max drawdown':20s} {m_all['max_drawdown']:10.1%} {m_in['max_drawdown']:12.1%} {m_out['max_drawdown']:14.1%}")

        # Module breakdown
        print()
        print("BY MODULE:")
        for mod_name, mod in results["by_module"].items():
            if mod["trades"] > 0:
                wr = f"{mod['win_rate']:.1%}" if mod['trades'] > 0 else "N/A"
                print(f"  {mod_name:10s}: {mod['trades']:3d} trades, "
                      f"P&L ${mod['pnl']:8.2f}, WR {wr}")

        # Config used
        print()
        print("CONFIG:")
        for k, v in sorted(config.items()):
            print(f"  {k}: {v}")

        print()
        print(f"Valid: {'YES' if valid else 'NO — ' + '; '.join(invalid_reasons)}")


if __name__ == "__main__":
    main()
