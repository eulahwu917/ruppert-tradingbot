# MEMORY.md — Data Scientist Long-Term Memory
_Owned by: Data Scientist agent. Updated after synthesis issues, data health findings, or P&L anomalies._

---

## Truth Files I Own
- `environments/demo/logs/truth/pnl_cache.json` — authoritative P&L (never let other agents overwrite)
- `environments/demo/logs/truth/pending_alerts.json` — alerts queue (Ruppert/heartbeat reads this)
- `environments/demo/logs/cycle_log.jsonl` — cycle history

## Capital State
- capital.py reads from `logs/truth/pnl_cache.json` as source of truth
- Live dashboard is read-only — never writes back
- Per-module daily caps scale with capital (%, not fixed dollars)

## Synthesis Rules
- Scripts log events only — I synthesize into truth files
- Never let trader.py or other agents write to pnl_cache.json directly
- settle records count toward P&L (action=settle must be included — bug fixed 2026-03-28)
- pnl_cache.json corruption fix: dashboard/api.py was overwriting truth file — now read-only (fixed 2026-03-28)

## Known Issues / Fixed
- 2026-03-28: pnl_cache.json was being overwritten by dashboard — fixed, dashboard now read-only
- 2026-03-28: settle records were ignored in P&L calculation — fixed
- 2026-03-28: logger.py was silently dropping `confidence` field — fixed, now written to every trade log

## Data Health Checks
- `data_health_check.py` path fixed (2026-03-28)
- Run periodically to verify truth file integrity

## Lessons Learned
- Old win-rate data by confidence tier is invalid (confidence field wasn't logged before 2026-03-26)
- Bot P&L without Mar 13 bug: ~+$81 (consistent with Opus figure of +$84.52)
- Always verify settle records are included when computing P&L — easy to miss

---

## 2026-03-31 Session Update

### P&L Architecture Overhaul — CRITICAL
- **`pnl_cache.json` deleted permanently.** Do not recreate. It was the source of stale/wrong P&L.
- Single canonical path: raw logs → `compute_closed_pnl_from_logs()` → `get_capital()`
- mtime-based in-process cache added for performance
- Update all references: `Truth Files I Own` section below is now stale — remove `pnl_cache.json`

### Truth Files I Own (UPDATED)
- `environments/demo/logs/truth/pending_alerts.json` — alerts queue
- `environments/demo/logs/cycle_log.jsonl` — cycle history
- ~~`pnl_cache.json`~~ — **DELETED. P&L now computed live from raw logs.**

### New Logging Infrastructure
- `logs/terminal_signals/YYYY-MM-DD.jsonl` — terminal signal shadow logs (T-90s before close). 36 records collected tonight.
- `logs/price_series/{ticker}.jsonl` — intra-window yes_bid/ask every 60s per open position. For backtest price series.

### New Analysis Tool
- `python scripts/data_toolkit.py winrate --module crypto_15m_dir --days 7 --by asset,hour,side`
- Returns in <3s. All DS analysis should use this CLI instead of reading raw files.

### NO-side P&L Bug Fix
- Formula was wrong for NO-side P&L calculation
- ws_feed restarted to load corrected formula
- 3 correction records applied to affected historical entries

### Capital at EOD: ~$13,146
