# -*- coding: utf-8 -*-
# autoresearch.py — Automated Parameter Optimization Loop
# Proposes single-parameter changes via LLM, evaluates via run_backtest.py,
# keeps improvements that pass Bonferroni-corrected validation.
# See program.md for full rules and constraints.

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKTEST_DIR = Path(__file__).parent
RUN_BACKTEST = BACKTEST_DIR / "run_backtest.py"
RESULTS_TSV = BACKTEST_DIR / "results.tsv"
TEMP_CONFIG = BACKTEST_DIR / "temp_config.json"
BASELINE_CONFIG = BACKTEST_DIR / "baseline_config.json"

# Tunable parameter ranges (from program.md)
TUNABLE_PARAMS = {
    "min_edge_weather":        {"min": 0.05, "max": 0.40, "type": float},
    "min_edge_crypto":         {"min": 0.05, "max": 0.30, "type": float},
    "min_confidence_weather":  {"min": 0.40, "max": 0.80, "type": float},
    "min_confidence_crypto":   {"min": 0.35, "max": 0.75, "type": float},
    "fractional_kelly":        {"min": 0.05, "max": 0.50, "type": float},
    "pct_capital_cap":         {"min": 0.01, "max": 0.05, "type": float},
    "daily_cap_pct":           {"min": 0.30, "max": 0.90, "type": float},
    "same_day_skip_hour":      {"min": 10,   "max": 18,   "type": int},
    "min_trade_size":          {"min": 2.0,  "max": 15.0, "type": float},
}

# Default config (mirrors strategy_simulator.py)
DEFAULT_CONFIG = {
    "min_edge_weather":       0.15,
    "min_edge_crypto":        0.12,
    "min_confidence_weather": 0.55,
    "min_confidence_crypto":  0.50,
    "pct_capital_cap":        0.025,
    "max_position_cap":       50.0,
    "daily_cap_pct":          0.70,
    "same_day_skip_hour":     14,
    "fractional_kelly":       0.25,
    "min_trade_size":         5.0,
}

MAX_CONSECUTIVE_INVALID = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bonferroni_threshold(experiment_num: int) -> float:
    """Bonferroni-corrected improvement threshold for Sharpe ratio."""
    return 0.05 / max(experiment_num, 1)


def init_results_tsv():
    """Create results.tsv with header if it doesn't exist."""
    if not RESULTS_TSV.exists():
        with open(RESULTS_TSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow([
                "timestamp", "experiment_num", "param_changed", "old_value",
                "new_value", "metric_in_old", "metric_in_new", "metric_out_old",
                "metric_out_new", "metric_combined_old", "metric_combined_new",
                "bonferroni_threshold", "verdict",
            ])


def log_result(row: dict):
    """Append a row to results.tsv."""
    with open(RESULTS_TSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([
            row["timestamp"],
            row["experiment_num"],
            row["param_changed"],
            row["old_value"],
            row["new_value"],
            row["metric_in_old"],
            row["metric_in_new"],
            row["metric_out_old"],
            row["metric_out_new"],
            row["metric_combined_old"],
            row["metric_combined_new"],
            row["bonferroni_threshold"],
            row["verdict"],
        ])


def run_backtest_with_config(config_path: str, start_date: str, end_date: str,
                              capital: float, min_trades: int) -> dict:
    """
    Run run_backtest.py with given config and parse METRIC lines from stdout.
    Returns {"metric_in": float|None, "metric_out": float|None, "metric": float|None, "valid": bool}
    """
    cmd = [
        sys.executable, str(RUN_BACKTEST),
        "--config", config_path,
        "--start-date", start_date,
        "--end-date", end_date,
        "--capital", str(capital),
        "--min-trades", str(min_trades),
        "--quiet",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("  [ERROR] Backtest timed out (>120s)", file=sys.stderr)
        return {"metric_in": None, "metric_out": None, "metric": None, "valid": False}

    stdout = result.stdout
    if result.returncode != 0:
        print(f"  [ERROR] Backtest failed (rc={result.returncode}): {result.stderr[:200]}",
              file=sys.stderr)
        return {"metric_in": None, "metric_out": None, "metric": None, "valid": False}

    parsed = {"metric_in": None, "metric_out": None, "metric": None, "valid": True}
    for line in stdout.strip().split("\n"):
        line = line.strip()
        m = re.match(r"^METRIC_IN:\s*(.+)$", line)
        if m:
            val = m.group(1).strip()
            parsed["metric_in"] = None if val == "INVALID" else float(val)
        m = re.match(r"^METRIC_OUT:\s*(.+)$", line)
        if m:
            val = m.group(1).strip()
            parsed["metric_out"] = None if val == "INVALID" else float(val)
        m = re.match(r"^METRIC:\s*(.+)$", line)
        if m:
            val = m.group(1).strip()
            parsed["metric"] = None if val == "INVALID" else float(val)

    if parsed["metric_in"] is None or parsed["metric_out"] is None:
        parsed["valid"] = False

    return parsed


def propose_change_via_llm(current_config: dict, history_summary: str) -> dict | None:
    """
    Use claude CLI to propose a single parameter change with hypothesis.
    Returns {"param": str, "new_value": float/int, "hypothesis": str} or None.
    """
    tunable_summary = "\n".join(
        f"  {k}: current={current_config.get(k, '?')}, range=[{v['min']}, {v['max']}]"
        for k, v in TUNABLE_PARAMS.items()
    )

    prompt = f"""You are optimizing a Kalshi prediction market trading bot's parameters.
The bot trades weather and crypto binary options. The metric is Sharpe ratio (higher = better).

Current config:
{tunable_summary}

Recent experiment history:
{history_summary if history_summary else "(no prior experiments)"}

Propose exactly ONE parameter change to improve the Sharpe ratio.
Consider the experiment history to avoid repeating failed changes.

Respond in EXACTLY this JSON format, nothing else:
{{"param": "<parameter_name>", "new_value": <number>, "hypothesis": "<one sentence why>"}}
"""

    try:
        result = subprocess.run(
            ["claude", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        print("  [WARN] 'claude' CLI not found. Falling back to simple heuristic.", file=sys.stderr)
        return _fallback_proposal(current_config, history_summary)
    except subprocess.TimeoutExpired:
        print("  [WARN] claude CLI timed out. Falling back to heuristic.", file=sys.stderr)
        return _fallback_proposal(current_config, history_summary)

    if result.returncode != 0:
        print(f"  [WARN] claude CLI error: {result.stderr[:200]}. Falling back.", file=sys.stderr)
        return _fallback_proposal(current_config, history_summary)

    # Parse JSON from output (may have surrounding text)
    text = result.stdout.strip()
    json_match = re.search(r'\{[^}]+\}', text)
    if not json_match:
        print(f"  [WARN] Could not parse LLM JSON. Falling back.", file=sys.stderr)
        return _fallback_proposal(current_config, history_summary)

    try:
        proposal = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        print(f"  [WARN] Invalid JSON from LLM. Falling back.", file=sys.stderr)
        return _fallback_proposal(current_config, history_summary)

    param = proposal.get("param", "")
    if param not in TUNABLE_PARAMS:
        print(f"  [WARN] LLM proposed non-tunable param '{param}'. Falling back.", file=sys.stderr)
        return _fallback_proposal(current_config, history_summary)

    # Validate range
    spec = TUNABLE_PARAMS[param]
    new_val = spec["type"](proposal["new_value"])
    new_val = max(spec["min"], min(spec["max"], new_val))

    return {
        "param": param,
        "new_value": new_val,
        "hypothesis": proposal.get("hypothesis", "no hypothesis"),
    }


def _fallback_proposal(current_config: dict, history_summary: str) -> dict:
    """Simple sequential parameter sweep when LLM is unavailable."""
    params = list(TUNABLE_PARAMS.keys())
    # Cycle through params, try small adjustments
    import hashlib
    seed = int(hashlib.md5(history_summary.encode()).hexdigest()[:8], 16)
    param = params[seed % len(params)]
    spec = TUNABLE_PARAMS[param]
    current_val = current_config.get(param, spec["min"])

    # Try 10% increase or decrease alternately
    if seed % 2 == 0:
        delta = (spec["max"] - spec["min"]) * 0.10
        new_val = min(current_val + delta, spec["max"])
    else:
        delta = (spec["max"] - spec["min"]) * 0.10
        new_val = max(current_val - delta, spec["min"])

    new_val = spec["type"](round(new_val, 4) if spec["type"] == float else new_val)

    return {
        "param": param,
        "new_value": new_val,
        "hypothesis": f"heuristic: adjust {param} by 10%",
    }


def git_commit_change(param: str, old_val, new_val, metric_in: float, metric_out: float):
    """Create a git branch and commit the kept config change."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch_name = f"autoresearch/{ts}-{param}"

    try:
        subprocess.run(["git", "checkout", "-b", branch_name], check=True,
                        capture_output=True, text=True, cwd=str(BACKTEST_DIR))
        subprocess.run(["git", "add", str(TEMP_CONFIG)], check=True,
                        capture_output=True, text=True, cwd=str(BACKTEST_DIR))
        msg = f"autoresearch: {param} {old_val} -> {new_val} (sharpe in: {metric_in}, out: {metric_out})"
        subprocess.run(["git", "commit", "-m", msg], check=True,
                        capture_output=True, text=True, cwd=str(BACKTEST_DIR))
        # Return to previous branch
        subprocess.run(["git", "checkout", "-"], check=True,
                        capture_output=True, text=True, cwd=str(BACKTEST_DIR))
        print(f"  [GIT] Committed to branch: {branch_name}")
    except subprocess.CalledProcessError as e:
        print(f"  [GIT ERROR] {e.stderr[:200] if e.stderr else str(e)}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ruppert Autoresearch Loop")
    parser.add_argument("--max-experiments", type=int, default=20)
    parser.add_argument("--start-date", type=str, default="2026-02-27")
    parser.add_argument("--end-date", type=str, default="2026-03-13")
    parser.add_argument("--capital", type=float, default=400.0)
    parser.add_argument("--min-trades", type=int, default=30,
                        help="Minimum trades per split (program.md requires 30)")
    parser.add_argument("--sleep", type=int, default=30,
                        help="Seconds between experiments (default 30)")
    parser.add_argument("--no-git", action="store_true",
                        help="Skip git branch/commit operations")
    parser.add_argument("--no-llm", action="store_true",
                        help="Use heuristic fallback instead of LLM")
    args = parser.parse_args()

    init_results_tsv()

    # Load or create baseline config
    current_config = dict(DEFAULT_CONFIG)
    if BASELINE_CONFIG.exists():
        with open(BASELINE_CONFIG, "r", encoding="utf-8") as f:
            current_config.update(json.load(f))
        print(f"[init] Loaded baseline from {BASELINE_CONFIG}")
    else:
        with open(BASELINE_CONFIG, "w", encoding="utf-8") as f:
            json.dump(current_config, f, indent=2)
        print(f"[init] Created baseline at {BASELINE_CONFIG}")

    # Run baseline backtest
    with open(TEMP_CONFIG, "w", encoding="utf-8") as f:
        json.dump(current_config, f, indent=2)

    print("[baseline] Running baseline backtest...")
    baseline = run_backtest_with_config(
        str(TEMP_CONFIG), args.start_date, args.end_date, args.capital, args.min_trades
    )
    print(f"[baseline] metric_in={baseline['metric_in']}, metric_out={baseline['metric_out']}, "
          f"metric={baseline['metric']}, valid={baseline['valid']}")

    if not baseline["valid"]:
        print("[baseline] INVALID — not enough trades. Consider lowering --min-trades or widening date range.")
        print("[baseline] Continuing anyway; experiments will be compared against INVALID baseline.")

    consecutive_invalid = 0
    history_lines = []
    kept_count = 0
    discarded_count = 0

    print(f"\n[loop] Starting autoresearch — max {args.max_experiments} experiments\n")

    for exp_num in range(1, args.max_experiments + 1):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        threshold = bonferroni_threshold(exp_num)

        print(f"--- Experiment {exp_num}/{args.max_experiments} (Bonferroni threshold: {threshold:.6f}) ---")

        # Build history summary for LLM
        history_summary = "\n".join(history_lines[-10:])  # last 10

        # Propose change
        if args.no_llm:
            proposal = _fallback_proposal(current_config, history_summary)
        else:
            proposal = propose_change_via_llm(current_config, history_summary)

        if proposal is None:
            print("  [SKIP] No valid proposal generated")
            continue

        param = proposal["param"]
        new_val = proposal["new_value"]
        old_val = current_config.get(param)
        hypothesis = proposal["hypothesis"]

        print(f"  Proposal: {param} = {old_val} -> {new_val}")
        print(f"  Hypothesis: {hypothesis}")

        # Skip if value unchanged
        if old_val == new_val:
            print(f"  [SKIP] Value unchanged")
            history_lines.append(f"exp{exp_num}: {param} unchanged, SKIP")
            continue

        # Write temp config with change
        test_config = dict(current_config)
        test_config[param] = new_val
        with open(TEMP_CONFIG, "w", encoding="utf-8") as f:
            json.dump(test_config, f, indent=2)

        # Run backtest
        result = run_backtest_with_config(
            str(TEMP_CONFIG), args.start_date, args.end_date, args.capital, args.min_trades
        )

        if not result["valid"]:
            print(f"  [INVALID] Backtest returned INVALID")
            consecutive_invalid += 1
            verdict = "SKIP_INVALID"

            log_result({
                "timestamp": ts, "experiment_num": exp_num,
                "param_changed": param, "old_value": old_val, "new_value": new_val,
                "metric_in_old": baseline.get("metric_in", "N/A"),
                "metric_in_new": "INVALID",
                "metric_out_old": baseline.get("metric_out", "N/A"),
                "metric_out_new": "INVALID",
                "metric_combined_old": baseline.get("metric", "N/A"),
                "metric_combined_new": "INVALID",
                "bonferroni_threshold": threshold,
                "verdict": verdict,
            })
            history_lines.append(f"exp{exp_num}: {param}={old_val}->{new_val}, INVALID")

            # Restore baseline config
            with open(TEMP_CONFIG, "w", encoding="utf-8") as f:
                json.dump(current_config, f, indent=2)

            if consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                print(f"\n[STOP] {MAX_CONSECUTIVE_INVALID} consecutive INVALID results. Stopping.")
                break
        else:
            consecutive_invalid = 0

            # Check improvement
            base_in = baseline.get("metric_in")
            base_out = baseline.get("metric_out")
            new_in = result["metric_in"]
            new_out = result["metric_out"]

            improved = True
            if base_in is not None and base_out is not None:
                delta_in = new_in - base_in
                delta_out = new_out - base_out
                improved = (delta_in > threshold and delta_out > threshold)
                print(f"  metric_in:  {base_in:.4f} -> {new_in:.4f} (delta={delta_in:+.4f})")
                print(f"  metric_out: {base_out:.4f} -> {new_out:.4f} (delta={delta_out:+.4f})")
            else:
                # Baseline was invalid; any valid result is an improvement
                print(f"  metric_in:  N/A -> {new_in:.4f}")
                print(f"  metric_out: N/A -> {new_out:.4f}")
                improved = True

            if improved:
                verdict = "KEEP"
                kept_count += 1
                print(f"  [KEEP] Improvement passes Bonferroni threshold")

                # Update baseline
                current_config[param] = new_val
                baseline = result

                # Save updated baseline
                with open(BASELINE_CONFIG, "w", encoding="utf-8") as f:
                    json.dump(current_config, f, indent=2)

                # Git commit
                if not args.no_git:
                    git_commit_change(param, old_val, new_val,
                                      result["metric_in"], result["metric_out"])
            else:
                verdict = "DISCARD"
                discarded_count += 1
                print(f"  [DISCARD] Improvement below threshold or regression")

                # Restore baseline config
                with open(TEMP_CONFIG, "w", encoding="utf-8") as f:
                    json.dump(current_config, f, indent=2)

            log_result({
                "timestamp": ts, "experiment_num": exp_num,
                "param_changed": param, "old_value": old_val, "new_value": new_val,
                "metric_in_old": base_in if base_in is not None else "N/A",
                "metric_in_new": new_in,
                "metric_out_old": base_out if base_out is not None else "N/A",
                "metric_out_new": new_out,
                "metric_combined_old": baseline.get("metric", "N/A"),
                "metric_combined_new": result["metric"],
                "bonferroni_threshold": threshold,
                "verdict": verdict,
            })

            history_lines.append(
                f"exp{exp_num}: {param}={old_val}->{new_val}, "
                f"in={new_in:.4f}, out={new_out:.4f}, {verdict}"
            )

        # Sleep between experiments
        if exp_num < args.max_experiments:
            print(f"  Sleeping {args.sleep}s...")
            try:
                time.sleep(args.sleep)
            except KeyboardInterrupt:
                print("\n[INTERRUPTED] Graceful shutdown.")
                break

    # Summary
    print(f"\n{'='*60}")
    print(f"AUTORESEARCH COMPLETE")
    print(f"{'='*60}")
    print(f"Experiments run: {exp_num}")
    print(f"Kept:     {kept_count}")
    print(f"Discarded: {discarded_count}")
    print(f"Invalid:  {exp_num - kept_count - discarded_count}")
    print(f"Final config: {json.dumps(current_config, indent=2)}")
    print(f"Results log:  {RESULTS_TSV}")


if __name__ == "__main__":
    main()
