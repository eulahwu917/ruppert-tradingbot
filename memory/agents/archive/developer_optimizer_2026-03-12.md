# Developer Summary: Optimizer Loss Review System
_SA-3 Developer | 2026-03-12_

---

## Task
Build the Optimizer Loss Review system — analyzes settled losing trades daily and produces learnings + recommendations.

---

## Files Created / Modified

### 1. `memory/agents/optimizer_learnings.md` — NEW
Cumulative learnings log. Created with initial structure as specified.
Appended to each time `run_loss_review()` finds losses.

### 2. `kalshi-bot/bot/optimizer.py` — NEW (296 lines)
Standalone module. No circular imports with main.py.

**Key function: `run_loss_review(trade_log_paths, output_to_telegram=False) -> dict`**

- Reads all JSONL trade logs from provided paths
- Pairs open/buy trades with their exit records by ticker
- Queries Kalshi API (best-effort) for settled position results
- Identifies losing trades: explicit `realized_pnl < 0` in exit record, OR estimated via API settlement
- Classifies each loss into one of 6 reasons:
  - `edge_too_low`, `overconfident`, `market_timing`, `weather_bias`, `crypto_volatility`, `unknown`
- Builds recommendations — never changes thresholds directly, always flags for CEO review
- Escalates to HIGH priority if same reason appears 3+ times in history
- Writes `logs/optimizer_review_YYYY-MM-DD.jsonl` (one JSON line per losing trade)
- Appends summary section to `memory/agents/optimizer_learnings.md`
- Returns `{losses_analyzed, new_learnings, recommendations}`

**Path resolution:**
- `_ROOT` = workspace root (3 parents up from `bot/optimizer.py`)
- `_BOT_DIR` = `kalshi-bot/`
- All paths computed at runtime — no hardcoded absolute paths

### 3. `kalshi-bot/ruppert_cycle.py` — MODIFIED
Added `report` mode (documented in docstring).

**New `report` mode block:**
- Builds P&L summary (same logic as `daily_report.py`)
- Calls `run_loss_review()` with today's + yesterday's trade logs
- If losses found: appends "📊 OPTIMIZER: X losses reviewed. Top recommendation: [text]"
- If no losses: appends "📊 OPTIMIZER: No losses to review today."
- Queues combined message to `pending_alerts.json` for Telegram delivery
- Exits early (`sys.exit(0)`) — does not run trading cycle steps

---

## Design Decisions

- **Self-contained**: optimizer.py imports from `kalshi_client.py` inside a function, avoiding any module-level circular dependency with `main.py`
- **Graceful degradation**: Kalshi API failure is caught and silenced — falls back to exit record data only
- **No threshold changes**: All recommendations flag for CEO review, per rules.md
- **Significant loss threshold**: `abs(realized_pnl) > $5.00` as specified
- **History counts**: parsed from `optimizer_learnings.md` using regex — counts keyword occurrences per reason category
- **encoding='utf-8'**: all file I/O uses explicit UTF-8 per rules

---

## Git Status
- `bot/optimizer.py` — staged in `kalshi-bot/` repo
- `ruppert_cycle.py` — staged in `kalshi-bot/` repo
- `memory/agents/optimizer_learnings.md` — staged in workspace repo
- NO `git push` performed — awaiting CEO / QA review

---

## Syntax Checks
```
python -m py_compile bot/optimizer.py      → OK
python -m py_compile ruppert_cycle.py      → OK
```

---

## TODOs / Known Limitations
- `KalshiClient.get_positions()` method behavior needs QA verification — the optimizer wraps it in try/except and degrades gracefully if unavailable
- Loss reason classification is heuristic — richer backtest correlation would improve accuracy (flag for SA-2 Researcher)
- `report` mode in `ruppert_cycle.py` duplicates P&L logic from `daily_report.py` — CEO may want to consolidate these in a future sprint
- `output_to_telegram=False` by default in `report` mode block (the alert is queued via `pending_alerts.json` instead, consistent with existing architecture)
