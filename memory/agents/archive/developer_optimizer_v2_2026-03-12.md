# SA-3 Developer — Optimizer Trigger v2
_Task completed: 2026-03-12_

## What Was Done

Added a `report` mode to `kalshi-bot/ruppert_cycle.py` that implements 7am loss detection and triggers an optimizer review workflow.

## Insertion Point

After the `if MODE == 'check': ... sys.exit(0)` block, before STEP 2 (Smart Money Refresh).  
Control flow:
- `check` mode → STEP 1 → exit
- **`report` mode → STEP 1 → P&L summary → loss scan → exit**  ← NEW
- `full` mode → STEP 1 → STEP 2 → STEP 3 → STEP 4 → STEP 5

## Logic Summary

### Trade Log Loading
- Reads `logs/trades_YYYY-MM-DD.jsonl` for **today + yesterday**
- Handles missing files gracefully; skips malformed lines

### Record Grouping
- `action in ('buy', 'open')` → `entries_by_ticker[ticker]` (latest entry per ticker)
- `action == 'exit'` → `exit_records` list

### P&L Summary
Printed to stdout (for Task Scheduler log):
- `total_deployed`: sum of `size_dollars` from all entry records
- `total_exited`: sum of `size_dollars` from all exit records
- `net_pnl_approx`: `total_exited - total_deployed`

### Loss Detection
For each exit record:
1. Check if `realized_pnl` field is already present in the record (future-proof)
2. If not: compute `realized_pnl = exit.size_dollars - entry.size_dollars` (cost basis diff)
3. If `realized_pnl < 0` → loss

### Output Files

**`logs/pending_optimizer_review.json`** — written only if ≥1 loss found:
```json
{
  "date": "YYYY-MM-DD",
  "losses": [
    {
      "ticker": "...",
      "side": "...",
      "realized_pnl": -5.00,
      "entry_edge": 0.18,
      "source": "weather",
      "timestamp": "..."
    }
  ],
  "total_loss": -10.00
}
```

**`logs/pending_alerts.json`** — optimizer alert appended via `push_alert()`:
```json
{
  "level": "optimizer",
  "message": "Loss review ready: X losing trade(s) totaling $Y.00. Optimizer review needed.",
  ...
}
```

### No-loss case
If no losses found: no files written, stdout message `"No losses detected — skipping optimizer review file"`.

## Git State
- `ruppert_cycle.py` staged (`git add` done)
- No `git push` (per rules — CEO reviews before pushing)

## Notes / TODOs for CEO
- The current auto-exit code does NOT write `realized_pnl` to the trade log record.
  The report mode falls back to computing it from `size_dollars` diff, which is a
  reasonable approximation. If more precision is needed, the auto-exit opp dict in
  STEP 1 could be updated to include `realized_pnl: pnl` before calling `log_trade()`.
- `report` mode still runs STEP 1 (position check) before the report logic. This means
  it checks live market prices for open positions. That's intentional — the position
  check could trigger auto-exits that should be captured in the same run.
- Task Scheduler: the 7am scheduled task should call `python ruppert_cycle.py report`
  (currently may be calling `full`). CEO should verify/update the Task Scheduler entry.
- `bot/optimizer.py.bak` is present in the repo as an untracked file — not staged,
  not touched. CEO may want to review or move to trash/.
