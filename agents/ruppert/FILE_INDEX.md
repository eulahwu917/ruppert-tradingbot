# FILE_INDEX.md — Where Everything Lives
_Every agent reads this to know where to put and find things._
_Last updated: 2026-03-29_

---

## Specs (agent-authored build instructions for Dev)
- Agent-specific specs: `agents/ruppert/{agent}/specs/`
- Shared/cross-agent specs: `environments/demo/specs/`
- Convention: `{AGENT}-SPECS-{BATCH}.md` or `{topic}-spec.md`

## Agent Memory
- Long-term: `agents/ruppert/{agent}/MEMORY.md`
- Handoffs: `memory/agents/{agent}-YYYY-MM-DD.md`
- Shared team context: `memory/agents/team_context.md`

## Research Reports
- All research output: `reports/research/`
- Format: `report_YYYY-MM-DD.md`

## Logs (runtime outputs — NOT committed to git)
- Trade logs: `environments/demo/logs/trades_YYYY-MM-DD.jsonl`
- Truth files: `environments/demo/logs/truth/` (Data Scientist owns)
- Price cache: `environments/demo/logs/price_cache.json` (Data Analyst writes)
- Scored predictions: `environments/demo/logs/scored_predictions.jsonl` (Strategist schema, Data Scientist writes)
- Cycle logs: `environments/demo/logs/cycle_logs/`
- Opportunities backlog: `environments/demo/logs/opportunities_backlog.json`

## Dev/QA Handoff Records
- Dev reports: `memory/agents/dev-{task}-YYYY-MM-DD.md`
- QA reports: `memory/agents/qa-{task}-YYYY-MM-DD.md`

## Daily Briefs
- `environments/demo/reports/daily_brief_YYYY-MM-DD.md`

## Decision Memos (Strategist)
- `memory/agents/strategist-{topic}-YYYY-MM-DD.md`

## Archive
- `environments/demo/archive/` — old environment files
- `environments/demo/logs/archive/` — old log files
