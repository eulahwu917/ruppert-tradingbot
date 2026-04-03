"""
optimizer.py - Ruppert Trading Bot Parameter Optimizer
Analyzes trade history and proposes parameter improvements.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths
_env_paths = _get_paths()
LOGS_DIR = _env_paths['logs']
BASE_DIR = _env_paths['root']
ARCHIVE_DIR = LOGS_DIR / "archive-pre-2026-03-26"

BONFERRONI_N = 6
BONFERRONI_THRESHOLD = 0.05 / BONFERRONI_N  # ~0.0083

import config as _config
from agents.ruppert.data_scientist.capital import get_capital as _get_capital
_capital = _get_capital()
DAILY_CAP = _capital * (
    getattr(_config, 'WEATHER_DAILY_CAP_PCT', 0.07) +
    getattr(_config, 'CRYPTO_DAILY_CAP_PCT', 0.07) +
    getattr(_config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04) +
    getattr(_config, 'GEO_DAILY_CAP_PCT', 0.04) +
    getattr(_config, 'ECON_DAILY_CAP_PCT', 0.04) +
    getattr(_config, 'FED_DAILY_CAP_PCT', 0.03)
)
MIN_TRADES             = getattr(_config, 'OPTIMIZER_MIN_TRADES', 30)
DOMAIN_THRESHOLD       = 10  # Fine-grained domains (e.g. crypto_dir_15m_btc) — lowered from 30
LOW_WIN_RATE_THRESHOLD = getattr(_config, 'OPTIMIZER_LOW_WIN_RATE', 0.60)
BRIER_FLAG_THRESHOLD   = getattr(_config, 'OPTIMIZER_BRIER_FLAG', 0.25)
HOLD_TIME_FLAG_HOURS   = getattr(_config, 'OPTIMIZER_HOLD_TIME_FLAG_HRS', 12)
CAP_UTIL_FLAG          = getattr(_config, 'OPTIMIZER_CAP_UTIL_FLAG', 0.30)
MAX_MODULE_AVG_SIZE    = getattr(_config, 'OPTIMIZER_MAX_AVG_SIZE', 40.0)

CONFIDENCE_TIERS = [
    (0.25, 0.40, "25-40%"),
    (0.40, 0.50, "40-50%"),
    (0.50, 0.60, "50-60%"),
    (0.60, 0.70, "60-70%"),
    (0.70, 0.80, "70-80%"),
    (0.80, 1.01, "80%+"),
]


def detect_module(ticker: str) -> str:
    t = ticker.upper()
    if t.startswith("KXHIGH"):
        return "weather"
    for kw in ("BTC", "ETH", "SOL"):
        if kw in t:
            return "crypto"
    for kw in ("FED", "FOMC"):
        if kw in t:
            return "fed"
    for kw in ("GDP", "CPI", "PCE", "NFP", "UNEMP"):
        if kw in t:
            return "econ"
    return "geo"


def load_trades() -> list:
    trades = []
    patterns = [
        LOGS_DIR.glob("trades_*.jsonl"),
        ARCHIVE_DIR.glob("trades_*.jsonl") if ARCHIVE_DIR.exists() else iter([]),
    ]
    for pattern in patterns:
        for fpath in pattern:
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            trades.append(rec)
                        except json.JSONDecodeError:
                            pass
            except OSError:
                pass
    return trades


def load_scored_predictions() -> dict:
    """Returns dict keyed by ticker -> list of outcome records."""
    outcomes = defaultdict(list)
    scored_path = LOGS_DIR / "scored_predictions.jsonl"
    if not scored_path.exists():
        return outcomes
    try:
        with open(scored_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ticker = rec.get("ticker", "")
                    if ticker:
                        outcomes[ticker].append(rec)
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return outcomes


def get_domain_trade_counts() -> dict[str, int]:
    """
    Reads scored_predictions.jsonl and returns count of scored trades per domain.
    Domain is read from the stored 'domain' field (fine-grained classify_module name).
    Falls back to detect_module(ticker) for legacy records without a domain field.
    """
    counts = defaultdict(int)
    scored_path = LOGS_DIR / "scored_predictions.jsonl"
    if not scored_path.exists():
        return dict(counts)
    with open(scored_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ticker = rec.get("ticker", "")
                # Use stored domain (fine-grained classify_module name) if present;
                # fall back to detect_module for legacy records without domain field.
                domain = rec.get("domain") or detect_module(ticker)
                if domain:
                    counts[domain] += 1
            except json.JSONDecodeError:
                pass
    return dict(counts)


def get_eligible_domains(threshold: int = DOMAIN_THRESHOLD) -> list[str]:
    """
    Returns list of domains with >= threshold scored trades.
    """
    counts = get_domain_trade_counts()
    return [domain for domain, count in counts.items() if count >= threshold]


def run_domain_experiments(domains: list[str]) -> dict:
    """
    Placeholder for running per-domain optimization experiments.
    Currently a no-op. Future: grid search, bayesian optimization, etc.
    """
    results = {}
    for domain in domains:
        results[domain] = {"status": "placeholder", "experiments_run": 0}
    return results


def enrich_trades(trades: list, outcomes: dict) -> list:
    """Add derived fields: module, confidence, outcome (if available)."""
    from agents.ruppert.data_scientist.logger import classify_module as _classify_module
    enriched = []
    for t in trades:
        rec = dict(t)
        # Module: use stored module if present; derive via classify_module (not detect_module)
        # so win-rate-by-module reports use fine-grained names (crypto_dir_15m_btc, not crypto)
        if "module" not in rec or not rec["module"]:
            rec["module"] = _classify_module(rec.get("source", ""), rec.get("ticker", ""))
        # Confidence
        if "confidence" not in rec or rec["confidence"] is None:
            edge = rec.get("edge", 0.0)
            rec["confidence"] = abs(edge) if edge is not None else 0.0
        # Win prob (noaa_prob or win_prob)
        if "win_prob" not in rec:
            rec["win_prob"] = rec.get("noaa_prob", None)
        # Outcome from scored_predictions
        ticker = rec.get("ticker", "")
        outcome_records = outcomes.get(ticker, [])
        if outcome_records:
            # Use the most recent outcome record
            rec["outcome"] = outcome_records[-1].get("outcome", None)
        else:
            rec["outcome"] = None
        enriched.append(rec)
    return enriched


def get_confidence_tier(confidence: float) -> str:
    for lo, hi, label in CONFIDENCE_TIERS:
        if lo <= confidence < hi:
            return label
    return "other"


def analyze_win_rate_by_module(trades: list):
    """Returns dict: module -> {trades, wins, win_rate}"""
    module_data = defaultdict(lambda: {"trades": 0, "wins": 0})
    for t in trades:
        mod = t.get("module", "geo")
        outcome = t.get("outcome")
        module_data[mod]["trades"] += 1
        if outcome == 1:
            module_data[mod]["wins"] += 1
    results = {}
    for mod, data in module_data.items():
        n = data["trades"]
        w = data["wins"]
        win_rate = w / n if n > 0 else None
        results[mod] = {"trades": n, "wins": w, "win_rate": win_rate}
    return results


def analyze_confidence_tiers(trades: list):
    """Returns dict: tier_label -> {trades, wins, win_rate}"""
    tier_data = defaultdict(lambda: {"trades": 0, "wins": 0})
    for t in trades:
        conf = t.get("confidence", 0.0)
        tier = get_confidence_tier(conf)
        outcome = t.get("outcome")
        tier_data[tier]["trades"] += 1
        if outcome == 1:
            tier_data[tier]["wins"] += 1
    results = {}
    for tier, data in tier_data.items():
        n = data["trades"]
        w = data["wins"]
        win_rate = w / n if n > 0 else None
        results[tier] = {"trades": n, "wins": w, "win_rate": win_rate}
    return results


def analyze_exit_timing(trades: list):
    """Returns {avg_hold_hours, avg_pnl, count} for trades with exit_price."""
    hold_times = []
    pnls = []
    for t in trades:
        if "exit_price" not in t or t["exit_price"] is None:
            continue
        # Try to compute hold time from entry/exit timestamps
        entry_ts = t.get("timestamp")
        exit_ts = t.get("exit_timestamp")
        if entry_ts and exit_ts:
            try:
                entry_dt = datetime.fromisoformat(str(entry_ts)[:19])
                exit_dt = datetime.fromisoformat(str(exit_ts)[:19])
                hold_hours = (exit_dt - entry_dt).total_seconds() / 3600
                hold_times.append(hold_hours)
            except (ValueError, TypeError):
                pass
        # P&L
        pnl = t.get("pnl") if t.get("pnl") is not None else t.get("realized_pnl")
        if pnl is not None:
            try:
                pnls.append(float(pnl))
            except (ValueError, TypeError):
                pass
    return {
        "count": len(hold_times),
        "avg_hold_hours": statistics.mean(hold_times) if hold_times else None,
        "avg_pnl": statistics.mean(pnls) if pnls else None,
    }


def analyze_brier_score(trades: list):
    """Returns {brier_score, count} for trades with win_prob and outcome.

    IMPORTANT: This function requires ENRICHED trades as input (output of enrich_trades()).
    Calling it on raw trade log records will silently exclude all pre-2026-03-26 records
    that only have 'noaa_prob' (not 'win_prob') as a direct field.
    """
    squared_errors = []
    for t in trades:
        wp = t.get("win_prob")
        if wp is None:
            # Fallback: accept noaa_prob for records that weren't enriched
            wp = t.get("noaa_prob")
        outcome = t.get("outcome")
        if wp is None or outcome is None:
            continue
        try:
            wp = float(wp)
            outcome = float(outcome)
            squared_errors.append((wp - outcome) ** 2)
        except (ValueError, TypeError):
            pass
    return {
        "count": len(squared_errors),
        "brier_score": statistics.mean(squared_errors) if squared_errors else None,
    }


def analyze_daily_cap_utilization(trades: list):
    """Returns {avg_daily_dollars, avg_utilization, days_tracked}."""
    daily = defaultdict(float)
    for t in trades:
        ts = t.get("timestamp", "")
        size = t.get("size_dollars", 0.0)
        if not ts:
            continue
        try:
            date_str = str(ts)[:10]
            daily[date_str] += float(size) if size else 0.0
        except (ValueError, TypeError):
            pass
    if not daily:
        return {"avg_daily_dollars": 0.0, "avg_utilization": 0.0, "days_tracked": 0}
    daily_totals = list(daily.values())
    avg_daily = statistics.mean(daily_totals)
    avg_util = avg_daily / DAILY_CAP
    return {
        "avg_daily_dollars": avg_daily,
        "avg_utilization": avg_util,
        "days_tracked": len(daily),
    }


def analyze_sizing_review(trades: list):
    """Returns dict: module -> {count, avg_size}."""
    module_sizes = defaultdict(list)
    for t in trades:
        mod = t.get("module", "geo")
        size = t.get("size_dollars")
        if size is not None:
            try:
                module_sizes[mod].append(float(size))
            except (ValueError, TypeError):
                pass
    results = {}
    for mod, sizes in module_sizes.items():
        results[mod] = {
            "count": len(sizes),
            "avg_size": statistics.mean(sizes) if sizes else 0.0,
        }
    return results


def format_pct(val, decimals=1):
    if val is None:
        return "N/A"
    return f"{val*100:.{decimals}f}%"


def status_tag(condition: bool) -> str:
    return "FLAG" if condition else "OK"


def build_report(
    trades,
    module_wr,
    tier_wr,
    exit_timing,
    brier,
    cap_util,
    sizing,
    today_str,
    has_outcome_data=True,
):
    proposals = []
    lines = []

    lines.append(f"# Optimizer Proposals -- {today_str}")
    lines.append("_Generated by optimizer.py. CEO reviews -> David approves -> Dev builds._")
    lines.append("")
    lines.append("## Summary")

    modules_with_data = [m for m, d in module_wr.items() if d["trades"] >= 5]
    lines.append(f"- Trades analyzed: {len(trades)}")
    lines.append(f"- Modules with sufficient data (>=5 trades): {modules_with_data}")
    lines.append(f"- Dimensions checked: {BONFERRONI_N}")
    lines.append(f"- Bonferroni threshold: {BONFERRONI_THRESHOLD:.4f}")
    lines.append("")

    # --- Win Rate by Module ---
    lines.append("## Findings")
    lines.append("")
    lines.append("### Win Rate by Module")
    lines.append("")

    if not has_outcome_data:
        lines.append("_Skipped: no outcome data available yet._")
    else:
        lines.append("| Module | Trades | Wins | Win Rate | Status |")
        lines.append("|--------|--------|------|----------|--------|")

        for mod in sorted(module_wr.keys()):
            d = module_wr[mod]
            n = d["trades"]
            wr = d["win_rate"]
            if wr is None:
                status = "No outcomes"
            elif n < 5:
                status = "Low data"
            elif wr < LOW_WIN_RATE_THRESHOLD:
                status = "FLAG - Low win rate"
                # Propose only if we have enough data
                if n >= 5:
                    improvement = LOW_WIN_RATE_THRESHOLD - wr
                    if improvement > BONFERRONI_THRESHOLD:
                        proposals.append(
                            f"**[{mod.upper()}] MIN_EDGE threshold**: "
                            f"Current win rate {format_pct(wr)} is below 60% target. "
                            f"Propose raising min_edge filter for {mod} module from current "
                            f"value to reduce low-confidence trades. "
                            f"Expected impact: +{format_pct(improvement)} win rate."
                        )
            else:
                status = "OK"
            lines.append(f"| {mod} | {n} | {d['wins']} | {format_pct(wr)} | {status} |")

    lines.append("")

    # --- Confidence Tier Analysis ---
    lines.append("### Confidence Tier Analysis")
    lines.append("")

    if not has_outcome_data:
        lines.append("_Skipped: no outcome data available yet._")
    else:
        lines.append("| Tier | Trades | Wins | Win Rate | Status |")
        lines.append("|------|--------|------|----------|--------|")

        tier_order = [t[2] for t in CONFIDENCE_TIERS] + ["other"]
        for tier_label in tier_order:
            if tier_label not in tier_wr:
                continue
            d = tier_wr[tier_label]
            n = d["trades"]
            wr = d["win_rate"]
            if wr is None:
                status = "No outcomes"
            elif n < 5:
                status = "Low data"
            elif wr < LOW_WIN_RATE_THRESHOLD:
                status = "FLAG - Below 60%"
                improvement = LOW_WIN_RATE_THRESHOLD - wr
                if n >= 5 and improvement > BONFERRONI_THRESHOLD:
                    proposals.append(
                        f"**[GLOBAL] Confidence tier {tier_label}**: "
                        f"Win rate {format_pct(wr)} below 60% threshold. "
                        f"Propose adding minimum confidence filter to exclude this tier. "
                        f"Expected impact: +{format_pct(improvement)} win rate for this tier."
                    )
            else:
                status = "OK"
            lines.append(f"| {tier_label} | {n} | {d['wins']} | {format_pct(wr)} | {status} |")

    lines.append("")

    # --- Brier Score ---
    lines.append("### Brier Score (Calibration)")
    lines.append("")
    bs = brier["brier_score"]
    bc = brier["count"]
    if bs is None:
        lines.append(f"- No calibration data available (0 trades with both win_prob and outcome).")
    else:
        flag = bs > BRIER_FLAG_THRESHOLD
        status = f"FLAG - Overconfident (>{BRIER_FLAG_THRESHOLD})" if flag else "OK - Well calibrated"
        lines.append(f"- Trades with calibration data: {bc}")
        lines.append(f"- Brier score: {bs:.4f} (lower=better; flag threshold={BRIER_FLAG_THRESHOLD})")
        lines.append(f"- Status: {status}")
        if flag:
            improvement = bs - BRIER_FLAG_THRESHOLD
            if improvement > BONFERRONI_THRESHOLD:
                proposals.append(
                    f"**[CALIBRATION] Probability estimation**: "
                    f"Brier score {bs:.4f} exceeds threshold {BRIER_FLAG_THRESHOLD}. "
                    f"Model is over/under-confident. Propose recalibrating win_prob estimates "
                    f"using Platt scaling or isotonic regression on recent outcomes. "
                    f"Expected impact: Brier score reduction of ~{improvement:.4f}."
                )

    lines.append("")

    # --- Exit Timing ---
    lines.append("### Exit Timing")
    lines.append("")
    et_count = exit_timing["count"]
    avg_hold = exit_timing["avg_hold_hours"]
    avg_pnl = exit_timing["avg_pnl"]
    if et_count == 0:
        lines.append("- No trades with exit data found (exit_price field absent).")
        lines.append("- Note: This is expected for dry-run/simulated trades.")
    else:
        flag_hold = avg_hold is not None and avg_hold > HOLD_TIME_FLAG_HOURS
        lines.append(f"- Trades with exit data: {et_count}")
        if avg_hold is not None:
            lines.append(
                f"- Avg hold time: {avg_hold:.1f}h "
                f"({'FLAG - Exceeds 12h' if flag_hold else 'OK'})"
            )
        if avg_pnl is not None:
            lines.append(f"- Avg P&L per trade: ${avg_pnl:.2f}")
        if flag_hold and avg_hold is not None:
            excess_hours = avg_hold - HOLD_TIME_FLAG_HOURS
            if (excess_hours / HOLD_TIME_FLAG_HOURS) > BONFERRONI_THRESHOLD:
                proposals.append(
                    f"**[EXIT] Hold time limit**: "
                    f"Avg hold {avg_hold:.1f}h exceeds 12h flag threshold. "
                    f"Propose implementing time-based exit rule at 12h max. "
                    f"Expected impact: Reduced overnight exposure."
                )

    lines.append("")

    # --- Daily Cap Utilization ---
    lines.append("### Daily Cap Utilization")
    lines.append("")
    avg_daily = cap_util["avg_daily_dollars"]
    avg_util = cap_util["avg_utilization"]
    days = cap_util["days_tracked"]
    flag_util = avg_util < CAP_UTIL_FLAG
    lines.append(f"- Days tracked: {days}")
    lines.append(f"- Daily cap (sum of module caps): ${DAILY_CAP:.0f}")
    lines.append(f"- Avg daily deployment: ${avg_daily:.2f}")
    lines.append(
        f"- Avg utilization: {format_pct(avg_util)} "
        f"({'FLAG - Below 30%' if flag_util else 'OK'})"
    )
    if flag_util and days >= 3:
        underutil = CAP_UTIL_FLAG - avg_util
        if underutil > BONFERRONI_THRESHOLD:
            proposals.append(
                f"**[SIZING] Daily cap utilization**: "
                f"Avg utilization {format_pct(avg_util)} is below 30% of ${DAILY_CAP:.0f} cap. "
                f"Propose relaxing MIN_EDGE or expanding market scan to find more opportunities. "
                f"Expected impact: +{format_pct(underutil)} daily capital deployment."
            )

    lines.append("")

    # --- Sizing Review ---
    lines.append("### Sizing Review")
    lines.append("")
    lines.append("| Module | Trades | Avg Size ($) | Status |")
    lines.append("|--------|--------|--------------|--------|")

    for mod in sorted(sizing.keys()):
        d = sizing[mod]
        avg_sz = d["avg_size"]
        flag_sz = avg_sz > MAX_MODULE_AVG_SIZE
        status = f"FLAG - Avg >${MAX_MODULE_AVG_SIZE:.0f}" if flag_sz else "OK"
        lines.append(f"| {mod} | {d['count']} | {avg_sz:.2f} | {status} |")
        if flag_sz:
            excess = avg_sz - MAX_MODULE_AVG_SIZE
            pct_excess = excess / MAX_MODULE_AVG_SIZE
            if pct_excess > BONFERRONI_THRESHOLD:
                proposals.append(
                    f"**[{mod.upper()}] Max position size**: "
                    f"Current avg ${avg_sz:.2f} exceeds ${MAX_MODULE_AVG_SIZE:.0f} limit. "
                    f"Propose capping {mod} module max_position_size at ${MAX_MODULE_AVG_SIZE:.0f}. "
                    f"Expected impact: Reduced single-module concentration risk."
                )

    lines.append("")

    # --- Actionable Proposals ---
    lines.append("## Actionable Proposals")
    if proposals:
        lines.append("_(Only items meeting Bonferroni threshold listed here)_")
        lines.append("")
        for i, p in enumerate(proposals, 1):
            lines.append(f"{i}. {p}")
    else:
        lines.append("")
        lines.append("## No Proposals")
        lines.append("_(Nothing meets Bonferroni threshold)_")
        lines.append("")
        lines.append("No parameter changes recommended. Data looks healthy.")

    return "\n".join(lines), proposals


def main():
    today_str = datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print("RUPPERT OPTIMIZER")
    print(f"Run date: {today_str}")
    print("=" * 60)
    print()

    # Load data
    print("Loading trade logs...")
    trades_raw = load_trades()
    print(f"  Found {len(trades_raw)} raw trade records.")

    if len(trades_raw) < MIN_TRADES:
        print(
            f"OPTIMIZER: Insufficient data ({len(trades_raw)} trades). "
            f"Minimum {MIN_TRADES} required. Aborting."
        )
        sys.exit(0)

    print("Loading scored predictions...")
    outcomes = load_scored_predictions()
    print(f"  Found outcome data for {len(outcomes)} tickers.")

    # Per-domain scored trade counts
    domain_counts = get_domain_trade_counts()
    eligible_domains = get_eligible_domains()

    print(f"Per-domain scored trade counts (threshold={DOMAIN_THRESHOLD}):")
    for domain, count in sorted(domain_counts.items()):
        status = "ELIGIBLE" if count >= DOMAIN_THRESHOLD else f"NEEDS {DOMAIN_THRESHOLD - count} more"
        print(f"  {domain:12s}: {count:3d} trades  [{status}]")
    print(f"Eligible domains: {eligible_domains}")
    print()

    print("Enriching trade records...")
    trades = enrich_trades(trades_raw, outcomes)
    print(f"  Enriched {len(trades)} trades.")
    print()

    # Count trades with actual outcome data
    scored_outcome_count = sum(1 for t in trades if t.get("outcome") is not None)
    has_outcome_data = scored_outcome_count > 0

    # Run analyses
    print("Running analysis (6 dimensions)...")
    print()

    # 1. Win rate by module
    module_wr = analyze_win_rate_by_module(trades)
    print("[1/6] Win rate by module:")
    if not has_outcome_data:
        print("      Win rate analysis skipped: no scored outcomes available yet.")
    else:
        for mod in sorted(module_wr.keys()):
            d = module_wr[mod]
            wr_str = format_pct(d["win_rate"]) if d["win_rate"] is not None else "N/A (no outcomes)"
            print(f"      {mod:12s}: {d['trades']:3d} trades, win rate={wr_str}")

    print()

    # 2. Confidence tiers
    tier_wr = analyze_confidence_tiers(trades)
    print("[2/6] Win rate by confidence tier:")
    if not has_outcome_data:
        print("      Confidence tier analysis skipped: no scored outcomes available yet.")
    else:
        tier_order = [t[2] for t in CONFIDENCE_TIERS] + ["other"]
        for tier_label in tier_order:
            if tier_label not in tier_wr:
                continue
            d = tier_wr[tier_label]
            wr_str = format_pct(d["win_rate"]) if d["win_rate"] is not None else "N/A (no outcomes)"
            print(f"      {tier_label:10s}: {d['trades']:3d} trades, win rate={wr_str}")

    print()

    # 3. Exit timing
    exit_timing = analyze_exit_timing(trades)
    print("[3/6] Exit timing:")
    if exit_timing["count"] == 0:
        print("      No trades with exit data (dry-run mode expected).")
    else:
        avg_hold = exit_timing["avg_hold_hours"]
        avg_pnl = exit_timing["avg_pnl"]
        print(f"      {exit_timing['count']} trades with exit data.")
        if avg_hold is not None:
            flag = " [FLAG >12h]" if avg_hold > HOLD_TIME_FLAG_HOURS else ""
            print(f"      Avg hold time: {avg_hold:.1f}h{flag}")
        if avg_pnl is not None:
            print(f"      Avg P&L: ${avg_pnl:.2f}")

    print()

    # 4. Brier score
    brier = analyze_brier_score(trades)
    print("[4/6] Brier score (calibration):")
    if brier["brier_score"] is None:
        print("      No calibration data (win_prob + outcome pairs needed).")
    else:
        flag = " [FLAG >0.25]" if brier["brier_score"] > BRIER_FLAG_THRESHOLD else ""
        print(f"      {brier['count']} trades, Brier={brier['brier_score']:.4f}{flag}")

    print()

    # 5. Daily cap utilization
    cap_util = analyze_daily_cap_utilization(trades)
    print("[5/6] Daily cap utilization:")
    print(f"      {cap_util['days_tracked']} days tracked.")
    flag = " [FLAG <30%]" if cap_util["avg_utilization"] < CAP_UTIL_FLAG else ""
    print(
        f"      Avg deployment: ${cap_util['avg_daily_dollars']:.2f} / "
        f"${DAILY_CAP:.0f} (sum of module caps) = {format_pct(cap_util['avg_utilization'])}{flag}"
    )

    print()

    # 6. Sizing review
    sizing = analyze_sizing_review(trades)
    print("[6/6] Sizing review by module:")
    for mod in sorted(sizing.keys()):
        d = sizing[mod]
        flag = f" [FLAG >${MAX_MODULE_AVG_SIZE:.0f}]" if d["avg_size"] > MAX_MODULE_AVG_SIZE else ""
        print(f"      {mod:12s}: avg ${d['avg_size']:.2f}{flag}")

    print()

    if eligible_domains:
        experiment_results = run_domain_experiments(eligible_domains)
        all_placeholder = all(r.get("experiments_run", 0) == 0 for r in experiment_results.values())
        if all_placeholder:
            print("[Placeholder] Domain experiments not yet implemented — skipping.")
            print(f"  Eligible domains: {eligible_domains} (need implementation in run_domain_experiments)")
        else:
            print("Running experiments for eligible domains...")
            for domain, result in experiment_results.items():
                print(f"  {domain}: {result}")
    else:
        print(f"No domains eligible for experiments yet (need {DOMAIN_THRESHOLD} scored trades each).")

    print()
    print("-" * 60)

    # Build and write report
    report_text, proposals = build_report(
        trades, module_wr, tier_wr, exit_timing, brier, cap_util, sizing, today_str,
        has_outcome_data=has_outcome_data,
    )

    output_path = LOGS_DIR / f"optimizer_proposals_{today_str}.md"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"Proposals written to: {output_path}")
    except OSError as e:
        print(f"WARNING: Could not write proposals file: {e}")

    print()
    if proposals:
        print(f"ACTIONABLE PROPOSALS: {len(proposals)} item(s) flagged (Bonferroni threshold={BONFERRONI_THRESHOLD:.4f})")
        for i, p in enumerate(proposals, 1):
            # Strip markdown for console
            clean = p.replace("**", "").replace("_", "")
            print(f"  {i}. {clean}")
    else:
        print("RESULT: No actionable proposals. Data looks healthy.")

    print()
    print("Optimizer complete. Exiting.")


if __name__ == "__main__":
    main()
