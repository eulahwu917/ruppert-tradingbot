# Data Agent Architecture Specification

**Author:** Architect  
**Date:** 2026-03-28  
**Status:** Ready for Dev

## Executive Summary

The Data Agent is a post-scan auditor that ensures zero bad data accumulates during the DEMO data-gathering phase. It runs after every scan cycle, aggressively cleans up issues, and immediately alerts David via Telegram if anything looks wrong.

---

## 1. When Does It Run?

### Primary Trigger: After Every Scan Cycle
- Hook into `ruppert_cycle.py` at the END of every mode handler (`run_full_mode`, `run_weather_only_mode`, `run_crypto_only_mode`, etc.)
- Add `run_data_audit()` call as final step before `save_state()` and `log_cycle('done', ...)`

### Secondary Trigger: On Startup
- At bot startup (when `ruppert_cycle.py` begins), run `run_historical_audit()` for existing data
- Only runs ONCE per day (flag stored in `logs/data_audit_state.json`)

### Tertiary Trigger: Manual
- `python data_agent.py --full` — runs complete historical audit
- `python data_agent.py --today` — audits today's logs only

---

## 2. Check Categories & Priorities

### 🔴 CRITICAL (Run Every Scan Cycle)

| Check | Description | Cleanup Action |
|-------|-------------|----------------|
| **Duplicate Trade IDs** | Same `trade_id` appears twice | DELETE the duplicate (keep first) |
| **Missing Required Fields** | Trade missing `ticker`, `side`, `size_dollars`, `entry_price`, `module` | MARK as `"_invalid": true` in log (don't delete - forensics) |
| **Dry Run Mismatch** | Trade logged with `dry_run: false` when config.DRY_RUN=True | MARK as `"_invalid": true` + ALERT (shouldn't happen) |
| **Module/Ticker Mismatch** | Weather trade (KXHIGH*) logged with `module: crypto` | AUTO-FIX: correct the module field |
| **Position Tracker Drift** | Position in `tracked_positions.json` but no matching open trade log entry | REMOVE from tracker |
| **Orphan Tracker Entries** | Trade log shows exit but tracker still has position | REMOVE from tracker |

### 🟡 IMPORTANT (Run Every Full Cycle)

| Check | Description | Cleanup Action |
|-------|-------------|----------------|
| **Entry Price Outside Spread** | `entry_price` not between `yes_bid` and `yes_ask` at time of trade | FLAG for review (don't auto-fix - might be slippage) |
| **Daily Cap Violation** | Trade placed after module's daily cap was hit | MARK as `"_cap_violation": true` + ALERT |
| **Dashboard P&L Mismatch** | Dashboard computed P&L differs from trade log by >$0.10 | Regenerate `pnl_cache.json` from trade logs |
| **Decision Without Trade** | Decision log shows `decision: ENTER` but no trade log entry | LOG anomaly (timing race is possible) |

### 🟢 PERIODIC (Run Daily at 7am via `report` mode)

| Check | Description | Cleanup Action |
|-------|-------------|----------------|
| **WS Cache Stale Trade** | Trade used REST fallback (`source: rest_fallback` or missing WS cache timestamp) | FLAG for review only |
| **Exit Price vs WS Tracker** | Position tracker logged exit at price X, trade log shows exit at price Y (>5c diff) | ALERT (data inconsistency) |
| **Historical Scan** | All files from a configurable start date | Same rules as above |

---

## 3. Cleanup Logic by Error Type

### Deletion Rules (Aggressive)
Since this is DEMO with fake money:
- **Duplicate records**: DELETE
- **Tracker orphans**: DELETE from tracker
- **Stale state files**: DELETE

### Marking Rules (Preserve for Forensics)
- **Schema violations**: Add `"_invalid": true` field
- **Cap violations**: Add `"_cap_violation": true` field
- **Price anomalies**: Add `"_flagged": "price_outside_spread"` field

### Auto-Fix Rules
- **Wrong module**: Correct it inline
- **Missing `confidence`**: Compute from `edge` if available
- **Missing `timestamp`**: Derive from filename date + trade_id ordering

### Never Auto-Delete
- Trade records with executed orders (non-dry-run `order_result`)
- Decision log entries (audit trail)
- Exit records (P&L calculation depends on them)

---

## 4. Alert Format

### Single Issue Alert
```
🔴 Data Agent Alert

Issue: Duplicate trade_id detected
Ticker: KXHIGHTMIN-26MAR28-T55
Action: Deleted duplicate record
File: logs/trades_2026-03-28.jsonl

Details: trade_id b5519359-1558-428f-8ff5-3412c8bfcf4a appeared twice (lines 1, 15)
```

### Batched Alert (Multiple Issues)
```
🔴 Data Agent: 3 issues found

1. FIXED: Wrong module for KXHIGHNY-26MAR28-B42 (crypto → weather)
2. FIXED: Duplicate trade_id deleted (1 record)
3. FLAGGED: KXBTC15M entry price outside spread — manual review

Run `python data_agent.py --details` for full report.
```

### Alert Fatigue Prevention
- If >5 issues found: Send summary only, write full details to `logs/data_audit_2026-03-28.json`
- Deduplicate alerts: Don't re-alert for same issue within 4 hours
- Track alerted issues in `logs/data_audit_state.json`

---

## 5. Implementation Plan

### New File: `data_agent.py`

```python
"""
Data Agent — Post-scan auditor for Ruppert trading bot.
Ensures zero bad data accumulates during DEMO phase.

Usage:
  python data_agent.py          # Runs standard post-cycle audit
  python data_agent.py --today  # Audits today's logs only
  python data_agent.py --full   # Full historical audit from DATA_AUDIT_START_DATE
  python data_agent.py --details # Show last audit report
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import uuid

LOGS_DIR = Path(__file__).parent / 'logs'
AUDIT_STATE_FILE = LOGS_DIR / 'data_audit_state.json'
DATA_AUDIT_START_DATE = date(2026, 3, 26)  # Audit from this date forward

# ─── Main Functions ───────────────────────────────────────────────────────────

def run_cycle_audit() -> Dict[str, Any]:
    """Quick audit run after each scan cycle. Returns summary."""
    pass

def run_today_audit() -> Dict[str, Any]:
    """Audit today's logs only."""
    pass

def run_historical_audit(start_date: date = DATA_AUDIT_START_DATE) -> Dict[str, Any]:
    """Full historical audit from start_date."""
    pass

def run_startup_audit():
    """Called on ruppert_cycle.py startup. Runs historical audit once per day."""
    pass

# ─── Individual Checks ────────────────────────────────────────────────────────

def check_duplicate_trade_ids(trades: List[Dict]) -> Tuple[List[int], List[str]]:
    """Returns (indices_to_delete, messages)."""
    pass

def check_missing_required_fields(trades: List[Dict]) -> Tuple[List[int], List[str]]:
    """Returns (indices_to_mark_invalid, messages)."""
    pass

def check_module_ticker_mismatch(trades: List[Dict]) -> Tuple[Dict[int, str], List[str]]:
    """Returns (index_to_correct_module_map, messages)."""
    pass

def check_dry_run_mismatch(trades: List[Dict], is_demo: bool) -> Tuple[List[int], List[str]]:
    """Returns (indices_to_mark_invalid, messages)."""
    pass

def check_position_tracker_drift() -> Tuple[List[str], List[str]]:
    """Returns (tickers_to_remove_from_tracker, messages)."""
    pass

def check_daily_cap_violations(trades: List[Dict]) -> Tuple[List[int], List[str]]:
    """Returns (indices_to_flag, messages)."""
    pass

def check_entry_price_spread(trades: List[Dict]) -> Tuple[List[int], List[str]]:
    """Returns (indices_to_flag, messages)."""
    pass

def reconcile_pnl_cache() -> Tuple[bool, float, float]:
    """Returns (needed_fix, old_value, new_value)."""
    pass

# ─── Cleanup Functions ────────────────────────────────────────────────────────

def delete_duplicate_records(log_path: Path, indices: List[int]) -> int:
    """Rewrite log file without duplicate records. Returns count deleted."""
    pass

def mark_records_invalid(log_path: Path, indices: List[int]) -> int:
    """Add _invalid: true to specified records. Returns count marked."""
    pass

def fix_module_fields(log_path: Path, fixes: Dict[int, str]) -> int:
    """Correct module field for specified records. Returns count fixed."""
    pass

def remove_tracker_entries(tickers: List[str]) -> int:
    """Remove specified tickers from tracked_positions.json. Returns count removed."""
    pass

# ─── Alerting ─────────────────────────────────────────────────────────────────

def format_alert(issues: List[str], severity: str = 'warning') -> str:
    """Format issues into a Telegram-friendly message."""
    pass

def send_audit_alert(message: str):
    """Send alert to David via Telegram."""
    from logger import send_telegram
    send_telegram(message)

def should_alert(issue_key: str) -> bool:
    """Check if we've already alerted for this issue in last 4 hours."""
    pass

def record_alert(issue_key: str):
    """Record that we've sent an alert for this issue."""
    pass

# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if '--full' in sys.argv:
        run_historical_audit()
    elif '--today' in sys.argv:
        run_today_audit()
    elif '--details' in sys.argv:
        # Print last audit report
        pass
    else:
        run_cycle_audit()
```

### Integration into `ruppert_cycle.py`

Add at the end of each mode handler, just before `save_state()`:

```python
# Data audit — runs after every scan cycle
try:
    from data_agent import run_cycle_audit
    audit_result = run_cycle_audit()
    if audit_result.get('issues_found', 0) > 0:
        print(f"  [DataAgent] {audit_result['issues_found']} issue(s) found and handled")
except Exception as e:
    print(f"  [DataAgent] Audit failed (non-fatal): {e}")
```

Add at the START of `run_cycle()`, after client init:

```python
# Data audit — startup historical check (runs once per day)
try:
    from data_agent import run_startup_audit
    run_startup_audit()
except Exception as e:
    print(f"  [DataAgent] Startup audit failed (non-fatal): {e}")
```

---

## 6. Historical Audit Strategy

### First Run Behavior
1. Check `logs/data_audit_state.json` for `last_full_audit_date`
2. If missing or older than `DATA_AUDIT_START_DATE`: run full audit
3. Audit all `trades_*.jsonl` files from `DATA_AUDIT_START_DATE` forward
4. Apply same rules but:
   - Don't delete historical records (flag only)
   - Generate summary report to `logs/data_audit_historical_YYYY-MM-DD.json`
   - Send single summary alert: "Historical audit complete: X issues flagged across Y files"

### Incremental Strategy
- After first run, only audit new files (date > last_audit_date)
- Store `last_audit_date` in state file
- Full re-audit can be triggered manually with `--full`

---

## 7. State File Schema

`logs/data_audit_state.json`:
```json
{
  "last_cycle_audit": "2026-03-28T15:30:00",
  "last_full_audit_date": "2026-03-28",
  "alerted_issues": {
    "dup_b5519359": "2026-03-28T15:30:00",
    "invalid_trade_15": "2026-03-28T12:00:00"
  },
  "cumulative_stats": {
    "duplicates_deleted": 3,
    "records_marked_invalid": 1,
    "modules_corrected": 5,
    "tracker_entries_removed": 2,
    "pnl_cache_reconciled": 1
  }
}
```

---

## 8. Success Criteria

1. ✅ Zero duplicate trade_ids in logs
2. ✅ All trades have required fields (or are marked `_invalid`)
3. ✅ Module field matches ticker prefix for all trades
4. ✅ Position tracker matches trade log (no orphans)
5. ✅ Dashboard P&L matches computed P&L (within $0.05)
6. ✅ David gets immediate alert for any issues found
7. ✅ Historical data is audited on first run after deployment

---

## 9. Module Detection Logic

Canonical module inference (reuse from `logger.classify_module`):

```python
def infer_module(ticker: str, source: str) -> str:
    """Infer correct module from ticker prefix."""
    t = ticker.upper()
    if t.startswith('KXHIGH'):
        return 'weather'
    if any(t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')):
        return 'crypto'
    if t.startswith(('KXFED', 'KXFOMC')):
        return 'fed'
    if t.startswith(('KXCPI', 'KXPCE', 'KXJOBS', 'KXUNEMPLOYMENT', 'KXGDP')):
        return 'econ'
    if any(t.startswith(p) for p in ('KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN',
                                      'KXTAIWAN', 'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE')):
        return 'geo'
    return source if source in ('manual', 'weather', 'crypto', 'fed', 'econ', 'geo') else 'other'
```

---

## 10. Required Fields Schema

Every trade record MUST have:
```python
REQUIRED_FIELDS = {
    'trade_id',      # uuid
    'ticker',        # string
    'side',          # 'yes' or 'no'
    'action',        # 'buy', 'open', 'exit', 'settle'
    'size_dollars',  # float
    'module',        # string
    'timestamp',     # ISO datetime
    'date',          # YYYY-MM-DD
}

# Entry-specific (action in ['buy', 'open'])
ENTRY_REQUIRED = REQUIRED_FIELDS | {
    'edge',          # float (can be null for manual)
    'confidence',    # float (can be null for manual)
}
```

---

## 11. Open Questions for David

1. **Alert channel**: Telegram only, or also log to a Slack channel?
2. **Historical cutoff**: Should we audit files before 2026-03-26, or is that the hard start?
3. **Auto-delete aggressiveness**: OK to auto-delete duplicates, or prefer flag-only mode?
4. **Cap violation handling**: Should trades that violated daily caps be marked invalid (excluded from P&L) or just flagged?

---

## Dev Handoff Checklist

- [ ] Create `data_agent.py` with all checks and cleanup functions
- [ ] Add integration hooks to `ruppert_cycle.py`
- [ ] Create `logs/data_audit_state.json` schema
- [ ] Add to Windows Task Scheduler (or rely on cycle integration)
- [ ] Test with existing log files
- [ ] Document alert format in README

**Estimated effort:** 4-6 hours
**Priority:** P0 (blocks clean data collection)
