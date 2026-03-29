# SA-3 Developer — Scan Notify Task
_Completed: 2026-03-12_

## Task
Add a Telegram notification at the end of every full scan cycle in `ruppert_cycle.py`.

## What Was Done

### `kalshi-bot/ruppert_cycle.py` — modified
Added `# ── SCAN SUMMARY NOTIFICATION` block at the very end of the file, after the existing
`CYCLE COMPLETE` print banner and before EOF. Triggered only in `full` mode (the `check` and
`report` modes `sys.exit()` before reaching this code).

**Message format sent:**
```
📊 Ruppert Scan — HH:MM AM/PM PDT

🌤 Weather: N opportunities | N trades placed
₿ Crypto: DIRECTION | N opportunities | N trades placed
🏛 Fed: <signal status or "no signal (reason)">

💰 Capital: $X.XX | Deployed: $X.XX | BP: $X.XX
```

**Implementation details:**
- Uses `push_alert('warning', _scan_msg)` — existing local function in `ruppert_cycle.py`
  writes to `logs/pending_alerts.json`. Level `'warning'` chosen (per spec: "use 'warning' if
  simpler") — always forwarded by heartbeat without extra filtering logic.
- Time displayed in PDT using `datetime.timezone(timedelta(hours=-7))` — no `pytz` dependency.
- Fed status read from `logs/fed_scan_latest.json` if it exists; gracefully handles missing file,
  `skip_reason`, active signal, or read errors.
- Buying power = `max(0, capital × 0.70 − deployed_today)` (30% reserve logic).
- `new_weather`, `new_crypto` are always initialized as `[]` before their try blocks, so the
  notification block is safe even when scan steps throw exceptions.
- Entire notification block is wrapped in a top-level `try/except` — a notify failure will never
  crash the cycle.

**logger.py — NOT modified.** The `push_alert()` used is the local one defined in
`ruppert_cycle.py`; it writes all levels without filtering. No changes to `logger.py` needed.

## Git Status
- `ruppert_cycle.py` — staged (`git add`)
- `fed_client.py` — unstaged (pre-existing modification, not in scope for this task)
- No `git push` — CEO pushes EOD

## QA Notes (for SA-4)
- Block is fully non-fatal: wrapped in `try/except`
- No new imports that require `pip install` — only stdlib `datetime.timezone/timedelta`
- No hardcoded API keys or user IDs in the bot file
- `encoding='utf-8'` used for all file reads inside the block
- Unicode emoji written as escape sequences (`\U0001f4ca` etc.) for safe Windows PowerShell handling
- Buying power formula consistent with existing 70%/30% daily cap rule

## Known Gaps / TODOs
- `fed_scan_latest.json` path and schema assumed from context — verify once `fed_client.py` is
  reviewed that it actually writes this file (SA-4 should confirm).
- PDT offset hardcoded to -7h; will be -8h during PST (Nov–Mar). Low priority for now.
