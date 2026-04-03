# HEARTBEAT.md — Ruppert Autonomous Monitoring


## On every heartbeat (always check first):
- Run `session_status` — if context ≥ 70%, warn David immediately before doing anything else

## On every heartbeat:
1. Check `environments/demo/logs/truth/pending_alerts.json` — if non-empty, forward alerts to David and clear the file
2. Check `environments/demo/logs/cycle_log.jsonl` — if last cycle was >8h ago and it's daytime, note it

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
- Run self-improvement report for Ruppert (main session only):
  `python -c "import sys; sys.path.insert(0, 'skills/xiucheng-self-improving-agent'); from self_improving import SelfImprovingAgent; from pathlib import Path; sia = SelfImprovingAgent(workspace='.'); sia.improvement_log = Path('memory/ruppert_improvement_log.md'); sia.soul_file = Path('SOUL.md'); print(sia.generate_weekly_report())"`
- Sub-agents (Strategist, Data Scientist, Data Analyst, Trader) do NOT use SIA — they have no user feedback loop. Their continuity is CHANGELOG + MEMORY.md.
- Review the report: are there recurring patterns? Things David keeps correcting? Flag anything worth acting on.

## Do NOT trigger manual scans from heartbeat — Task Scheduler handles it.
## Only forward pending_alerts.json contents to David.

## Optimizer Monitoring (check daily, daytime only):
- Run domain trade count check:
  ```
  python -c "import sys; sys.path.insert(0, '.'); from agents.ruppert.strategist.optimizer import get_domain_trade_counts; counts = get_domain_trade_counts(); [print(f'{d}: {c}/30') for d,c in counts.items()]"
  ```
- Report counts to David once per day (morning) so he can track progress
- If any domain crosses 30 trades for the first time: alert David — "📊 [domain] just hit 30+ scored trades — eligible for optimizer analysis"
- If ALL domains hit 30+: alert David — "🎯 All domains ready — trigger Strategist to run optimizer and assess proposal quality"
- Check `environments/demo/logs/proposals/` — if a new optimizer_proposals_*.md appeared since last check, forward its contents to David


## One-time: 2026-04-02 noon check-in (David requested)
- Send David a morning summary: overnight trade data, first runs of threshold_daily + band_daily, WS health, P&L
- Check `memory/noon-reminder-2026-04-02.json` and delete after sending

## Weekend Tasks (next weekend)
- Run Optimizer for weather domain (66 trades, well past 30-trade threshold)
- Trigger: "Run Optimizer for weather domain"

## Secrets Rotation (quarterly)
- Next due: 2026-06-28
- On that week: alert David to rotate GitHub token + Kalshi API key
