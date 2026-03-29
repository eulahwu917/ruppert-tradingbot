# HEARTBEAT.md — Ruppert Autonomous Monitoring


## On every heartbeat (always check first):
- Run `session_status` — if context ≥ 70%, warn David immediately before doing anything else

## On every heartbeat:
1. Check `ruppert-tradingbot-demo/logs/pending_alerts.json` — if non-empty, forward alerts to David and clear the file
2. Check `ruppert-tradingbot-demo/logs/cycle_log.jsonl` — if last cycle was >8h ago and it's daytime, note it

## Alert levels to forward:
- `exit`     → "ACTION NEEDED: [message]" — send immediately
- `warning`  → "HEADS UP: [message]" — send if daytime (8am–11pm PDT)
- `security` → "SECURITY: [message]" — send always
- `info`     → skip (just log noise)

## Schedule (automated via Task Scheduler — no heartbeat action needed):
- 07:00  Full cycle: scan + smart money + execute new trades (DEMO)
- 07:00  Daily report (DEMO)
- 12:00  Position check: auto-exit if needed (DEMO)
- 15:00  Full cycle: afternoon scan + execute (DEMO)
- 22:00  Position check: overnight positioning (DEMO)
## LIVE Status: inactive (pre-flight checklist not yet complete)

## Weekly (Fridays, daytime):
- Run self-improvement report: `python skills/xiucheng-self-improving-agent/self_improving.py --report`
- If suggestions exist for SOUL.md, flag to David

## Do NOT trigger manual scans from heartbeat — Task Scheduler handles it.
## Only forward pending_alerts.json contents to David.


## Secrets Rotation (quarterly)
- Next due: 2026-06-28
- On that week: alert David to rotate GitHub token + Kalshi API key
