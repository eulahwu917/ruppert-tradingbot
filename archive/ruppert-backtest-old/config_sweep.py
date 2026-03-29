# config_sweep.py — Ruppert Backtest Framework
# Parameter grid for optimization sweeps.
# Optimizer (SA-1) owns all thresholds; this grid is seeded from their recommendations.

import itertools
from strategy_simulator import DEFAULT_CONFIG

# ---------------------------------------------------------------------------
# Sweep grid — values to try for each parameter
# ---------------------------------------------------------------------------
SWEEP_GRID = {
    "min_edge_weather":       [0.10, 0.12, 0.15, 0.18, 0.20],
    "min_edge_crypto":        [0.08, 0.10, 0.12, 0.15],
    "min_confidence_weather": [0.45, 0.50, 0.55, 0.60],
    "same_day_skip_hour":     [12, 13, 14, 15],
}

# Total combinations: 5 × 4 × 4 × 4 = 320


def _build_config(overrides: dict) -> dict:
    """Build a full config dict from DEFAULT_CONFIG + sweep overrides."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(overrides)
    return cfg


def _generate_configs() -> list:
    """Generate all parameter combinations from SWEEP_GRID."""
    keys = list(SWEEP_GRID.keys())
    value_lists = [SWEEP_GRID[k] for k in keys]
    configs = []
    for combo in itertools.product(*value_lists):
        overrides = dict(zip(keys, combo))
        configs.append(_build_config(overrides))
    return configs


def run_sweep(
    start_date: str,
    end_date: str,
    starting_capital: float = 400.0,
    verbose: bool = True,
) -> list:
    """
    Run backtest for every combination in SWEEP_GRID.

    Args:
        start_date:       ISO date string, e.g. '2026-02-27'
        end_date:         ISO date string, e.g. '2026-03-13'
        starting_capital: starting capital per run
        verbose:          print progress every 20 configs

    Returns:
        list of (config_dict, results_dict) sorted by total_pnl descending
    """
    # Import here to avoid circular import at module level
    from backtest_engine import run_backtest

    configs = _generate_configs()
    total = len(configs)
    if verbose:
        print(f"[sweep] Running {total} parameter combinations...")

    results = []
    for i, cfg in enumerate(configs):
        if verbose and i > 0 and i % 20 == 0:
            best_so_far = max(results, key=lambda x: x[1]["total_pnl"])
            print(
                f"[sweep] {i}/{total} done | "
                f"best so far: ${best_so_far[1]['total_pnl']:.2f} "
                f"({best_so_far[1]['total_trades']} trades)"
            )
        res = run_backtest(
            start_date=start_date,
            end_date=end_date,
            config=cfg,
            starting_capital=starting_capital,
        )
        results.append((cfg, res))

    # Sort by total_pnl descending
    results.sort(key=lambda x: x[1]["total_pnl"], reverse=True)

    if verbose:
        best_cfg, best_res = results[0]
        print(f"\n[sweep] Complete. Best config:")
        print(f"  Total P&L : ${best_res['total_pnl']:.2f}")
        print(f"  Win rate  : {best_res['win_rate']*100:.1f}%")
        print(f"  Trades    : {best_res['total_trades']}")
        print(f"  Config    : {best_cfg}")

    return results
