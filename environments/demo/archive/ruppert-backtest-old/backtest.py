# -*- coding: utf-8 -*-
"""
Ruppert Backtest Framework -- Entry Point

Usage:
  python backtest.py                                  # default config, accuracy mode
  python backtest.py --sweep                          # parameter sweep (320 combos)
  python backtest.py --start 2026-02-27 --end 2026-03-13
  python backtest.py --capital 500 --sweep
  python backtest.py --output results/my_run         # custom output path (no extension)

Output:
  results/<timestamp>_accuracy_report.txt   -- human-readable accuracy report
  results/<timestamp>_accuracy_report.json  -- full machine-readable results
"""

import argparse
import sys
from pathlib import Path

# Ensure this directory is on the path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_engine import run_accuracy_backtest
from config_sweep import run_sweep, SWEEP_GRID
from strategy_simulator import DEFAULT_CONFIG
from report import generate_accuracy_report, print_sweep_summary


# Default date range -- matches Researcher's data collection window
DEFAULT_START = "2026-02-27"
DEFAULT_END   = "2026-03-13"
DEFAULT_CAPITAL = 400.0


def main():
    parser = argparse.ArgumentParser(
        description="Ruppert Backtesting Framework -- Accuracy Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--start", default=DEFAULT_START,
        help=f"Start date (YYYY-MM-DD). Default: {DEFAULT_START}"
    )
    parser.add_argument(
        "--end", default=DEFAULT_END,
        help=f"End date (YYYY-MM-DD). Default: {DEFAULT_END}"
    )
    parser.add_argument(
        "--capital", type=float, default=DEFAULT_CAPITAL,
        help=f"Starting capital in dollars (unused in accuracy mode). Default: {DEFAULT_CAPITAL}"
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Run a full parameter sweep over SWEEP_GRID"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path base (without extension). Default: auto-timestamped in results/"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of top sweep results to print. Default: 10"
    )
    parser.add_argument(
        "--no-report", action="store_true",
        help="Skip writing report files (print summary only)"
    )

    args = parser.parse_args()

    print(f"[backtest] Period    : {args.start} -> {args.end}")
    print(f"[backtest] Capital   : ${args.capital:.2f}")
    print(f"[backtest] Mode      : {'SWEEP' if args.sweep else 'ACCURACY'}")
    print()

    if args.sweep:
        # ---- Parameter sweep (uses legacy run_backtest internally via config_sweep) ----
        print(f"[backtest] Sweep grid: {len(SWEEP_GRID)} params, "
              f"{sum(len(v) for v in SWEEP_GRID.values())} total values")
        sweep_results = run_sweep(
            start_date=args.start,
            end_date=args.end,
            starting_capital=args.capital,
            verbose=True,
        )

        print_sweep_summary(sweep_results, top_n=args.top)

        if not args.no_report:
            for rank, (cfg, res) in enumerate(sweep_results[:3], 1):
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out = args.output or f"results/{ts}_sweep_rank{rank}"
                from report import generate_report
                path = generate_report(res, cfg, output_path=out)
                print(f"[backtest] Rank {rank} report -> {path}")

    else:
        # ---- Accuracy backtest (default) ----
        print("[backtest] Running accuracy backtest with default config...")
        results = run_accuracy_backtest(
            start_date=args.start,
            end_date=args.end,
            scan_hours_utc=[7, 12, 15, 22],
            config=dict(DEFAULT_CONFIG),
            starting_capital=args.capital,
        )

        # Print quick summary
        print()
        print(f"  Markets evaluated : {results['total_markets_evaluated']}")
        print(f"  Triggered         : {results['total_triggered']} "
              f"({results['trigger_rate']:.1%})")
        print(f"  Correct           : {results['total_correct']} "
              f"({results['win_rate']:.1%} win rate)")
        print()

        if not args.no_report:
            path = generate_accuracy_report(
                results, dict(DEFAULT_CONFIG), output_path=args.output
            )
            print(f"[backtest] Report written -> {path}")
        else:
            # Print per-market rows to stdout
            for r in results.get("all_results", []):
                status = "HIT " if r.get('triggered') else "skip"
                correct_s = ""
                if r.get('triggered'):
                    correct_s = "CORRECT" if r.get('correct') else "WRONG  "
                print(
                    f"  {r.get('settle_date','?')}  {r.get('ticker','?'):<34}  "
                    f"{status}  {correct_s}  "
                    f"prob={r.get('prob',0):.3f}  edge={r.get('edge',0):.3f}  "
                    f"conf={r.get('confidence',0):.3f}  dir={r.get('direction','?')}"
                )


if __name__ == "__main__":
    main()
