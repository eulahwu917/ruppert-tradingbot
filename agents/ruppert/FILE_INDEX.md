# FILE_INDEX.md — Where Everything Lives
_Every agent reads this to know where to put and find things._
_Last updated: 2026-03-29 (CEO housekeeping sweep — paths corrected, stale entries removed)_
_Maintained by: CEO. Update during Phase 5 housekeeping after every audit loop._

---

## Workflow Docs (CEO-owned)
- Audit loop workflow: `agents/ruppert/ceo/audit-workflow.md`

## Specs (agent-authored build instructions for Dev)
- Agent-specific specs: `agents/ruppert/{agent}/specs/`
- Shared/cross-agent specs: `environments/demo/specs/`
- Convention: `{AGENT}-SPECS-{BATCH}.md` or `{topic}-spec.md`
- Audit-cycle specs (temp): `memory/agents/specs-{agent}-YYYY-MM-DD.md` (archived after Dev→QA completes)

## Agent Memory
- Long-term: `agents/ruppert/{agent}/MEMORY.md`
- Daily session logs: `memory/YYYY-MM-DD.md` (Ruppert main session)
- Audit findings (temp): `memory/agents/audit-{agent}-YYYY-MM-DD.md`
- Shared team context: superseded by `PIPELINE.md` (do not create new team_context.md)

## Research Reports
- All research output: `environments/demo/reports/research/`
- Format: `report_YYYY-MM-DD.md`
- Opportunities backlog: `environments/demo/logs/truth/opportunities_backlog.json` (Data Scientist owns)

## Logs (runtime outputs — NOT committed to git)
- Trade logs: `environments/demo/logs/trades/trades_YYYY-MM-DD.jsonl` (subdirectory, not root)
- Truth files: `environments/demo/logs/truth/` (Data Scientist owns — authoritative)
- Price cache: `environments/demo/logs/price_cache.json` (Data Analyst writes)
- Scored predictions: `environments/demo/logs/scored_predictions.jsonl` (Strategist schema, Data Scientist writes)
- Cycle log: `environments/demo/logs/cycle_log.jsonl` (single rolling file, not a subdirectory)
- Raw event logs: `environments/demo/logs/raw/` (event_logger output)
- Audit outputs: `environments/demo/logs/audits/` (data audit snapshots)
- Pending alerts: `environments/demo/logs/truth/pending_alerts.json`
- WS heartbeat: `environments/demo/logs/ws_feed_heartbeat.json` (Data Analyst ws_feed writes)

## Daily Briefs
- `environments/demo/reports/daily_brief_YYYY-MM-DD.md`

## Pipeline / Org Docs
- `agents/ruppert/PIPELINE.md` — roles, pipelines, escalation rules (⚠️ known stale — still references old Architect/Optimizer org; update pending)
- `agents/ruppert/RULES.md` — standing rules for all agents

## Archive
- `environments/demo/archive/` — old environment files (includes `pre-phase6-demo-root-2026-03-28/`, `ruppert-backtest-old/`, `dead-backtest-code/`)
- `environments/demo/logs/archive/` — old log files
- `environments/demo/logs/archive/stale-2026-03-28/` — stale logs swept 2026-03-28
- `environments/demo/memory/agents/archive/` — completed/superseded agent spec/audit files
- Never delete — archive only. Always verify a file is no longer in use before archiving.

## Completed Specs (archived, not active)
- `environments/demo/specs/` — active specs only; completed specs moved to `environments/demo/archive/`
- Note: `remove_shims_spec.md` → COMPLETED 2026-03-29 (archived)
- Note: `data_agent_spec.md` → SUPERSEDED 2026-03-29 (code built with different API; archived)
