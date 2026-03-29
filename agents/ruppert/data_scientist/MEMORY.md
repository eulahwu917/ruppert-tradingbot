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
