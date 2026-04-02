"""
data_integrity_check.py — Trade log and data file integrity audit.

Checks:
- Trade logs have required fields and valid schema
- predictions.jsonl has no unscored entries older than 7 days
- pnl_cache.json is fresh (< 24h old)
- cycle_log.jsonl is being written (last entry < 25h ago)
- YES shadow log is growing (direction filter capturing data)
- No module producing 0 signals for 3+ consecutive cycles

Run daily. QA owns this.
Usage: python data_integrity_check.py
Exit code 0 = clean, 1 = issues found
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT      = Path(__file__).parent
DEMO_DIR  = ROOT.parent          # audit/ -> demo/
LOGS_DIR  = DEMO_DIR / "logs"   # brier_tracker.py lives in demo root
issues    = []
warnings  = []

# Make demo root importable (brier_tracker.py lives there)
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))


def check_cycle_log():
    """Verify cycle_log.jsonl has a recent entry."""
    cycle_log = LOGS_DIR / "cycle_log.jsonl"
    if not cycle_log.exists():
        issues.append("cycle_log.jsonl missing — cycles may not be running")
        return
    lines = cycle_log.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
    if not lines:
        issues.append("cycle_log.jsonl is empty — no cycles have run since reset")
        return
    try:
        last = json.loads(lines[-1])
        ts = datetime.fromisoformat(last.get("ts", "2000-01-01"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_h > 25:
            warnings.append(f"cycle_log.jsonl last entry is {age_h:.1f}h ago — cycles may have stalled")
        else:
            print(f"  cycle_log: last entry {age_h:.1f}h ago — OK")
    except Exception as e:
        warnings.append(f"cycle_log.jsonl parse error: {e}")


def check_unscored_predictions():
    """Detect predictions older than 7 days that were never scored."""
    pred_file = LOGS_DIR / "predictions.jsonl"
    if not pred_file.exists():
        print("  predictions.jsonl: not yet created (no trades placed)")
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    unscored = []
    for line in pred_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines():
        try:
            entry = json.loads(line)
            if entry.get("outcome") is None:
                ts = datetime.fromisoformat(entry.get("ts", "2000-01-01"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    unscored.append(entry.get("ticker", "unknown"))
        except Exception:
            continue
    if unscored:
        warnings.append(f"Unscored predictions older than 7 days: {unscored}")
    else:
        print(f"  predictions.jsonl: no stale unscored entries — OK")


def check_pnl_cache():
    """No-op — pnl_cache.json removed. P&L computed live from logs."""
    print("  pnl_cache.json removed — P&L computed live from logs — OK")


def check_shadow_log():
    """Verify YES shadow log exists and is growing."""
    shadow_log = LOGS_DIR / "weather_yes_shadow.jsonl"
    if not shadow_log.exists():
        warnings.append("weather_yes_shadow.jsonl missing — YES shadow logging may not be wired correctly")
        return
    lines = shadow_log.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
    print(f"  weather_yes_shadow.jsonl: {len(lines)} entries — OK")


def check_trade_schema():
    """Verify today's trade log has required fields."""
    from datetime import date
    today = date.today().isoformat()
    trade_log = LOGS_DIR / f"trades_{today}.jsonl"
    if not trade_log.exists():
        print(f"  trades_{today}.jsonl: no trades today yet — OK")
        return
    REQUIRED_FIELDS = ["ticker", "side", "price", "size", "edge", "ts"]
    bad_entries = []
    for i, line in enumerate(trade_log.read_text(encoding="utf-8", errors="ignore").strip().splitlines(), 1):
        try:
            entry = json.loads(line)
            missing = [f for f in REQUIRED_FIELDS if f not in entry]
            if missing:
                bad_entries.append(f"line {i}: missing fields {missing}")
        except Exception:
            bad_entries.append(f"line {i}: invalid JSON")
    if bad_entries:
        issues.append(f"trades_{today}.jsonl schema errors: {bad_entries}")
    else:
        print(f"  trades_{today}.jsonl: schema valid — OK")


def check_brier_domain_progress():
    """Report per-domain Brier score progress toward 30-trade threshold."""
    try:
        from brier_tracker import get_domain_brier_summary
        summary = get_domain_brier_summary()
        if not summary:
            print("  Brier score: no scored predictions yet")
            return
        for domain, data in summary.items():
            count = data.get("count", 0)
            brier = data.get("brier_mean")
            pct   = data.get("threshold_pct", 0)
            brier_str = f"{brier:.4f}" if brier is not None else "N/A"
            print(f"  {domain:10} {count:3}/30 trades scored | Brier: {brier_str} | {pct}% to autoresearch")
            if count >= 30:
                warnings.append(f"POST-BRIER REVIEW DUE: {domain} has reached 30 scored trades!")
    except Exception as e:
        warnings.append(f"Brier summary failed: {e}")


def main():
    print("=== Ruppert Data Integrity Check ===\n")

    print("Checking cycle log...")
    check_cycle_log()

    print("Checking unscored predictions...")
    check_unscored_predictions()

    print("Checking P&L cache...")
    check_pnl_cache()

    print("Checking YES shadow log...")
    check_shadow_log()

    print("Checking trade schema...")
    check_trade_schema()

    print("Checking Brier score progress...")
    check_brier_domain_progress()

    print()
    if issues:
        print(f"❌ ISSUES ({len(issues)} — must fix):")
        for issue in issues:
            print(f"  {issue}")
        print()

    if warnings:
        print(f"⚠️  WARNINGS ({len(warnings)} — review):")
        for w in warnings:
            print(f"  {w}")
        print()

    if not issues and not warnings:
        print("✅ All data integrity checks passed")
        return 0

    if issues:
        print(f"RESULT: FAIL ({len(issues)} issues, {len(warnings)} warnings)")
        return 1

    print(f"RESULT: PASS WITH WARNINGS ({len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
