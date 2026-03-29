# team_context.md — Ruppert Agent Team Context
_Read this before every task. Last updated: 2026-03-26_

---

## Team Structure

```
CEO (Ruppert main)
├── SA-1: Optimizer      — algo analysis, parameter tuning, backtest review
├── SA-2: Researcher     — data pulls, market research, wallet updates
├── SA-3: Developer      — code implementation
└── SA-4: QA             — verification only, never modifies code
```

## Reporting Chain (MANDATORY)

```
Developer builds → QA reviews → [FAIL: back to Dev] → loop until QA PASS → CEO → David
Optimizer / Researcher → CEO → David (if unsure or real money)
```

- CEO does NOT see phase output until QA returns PASS or PASS WITH WARNINGS
- CEO messages David when a phase is QA-verified — not before

## Model Assignments (Tiered Routing)

| Agent | Model | Rationale |
|-------|-------|-----------|
| CEO (Ruppert main) | claude-sonnet-4-6 | Orchestration, reporting, approvals |
| SA-1 Optimizer | claude-sonnet-4-6 | High-stakes algo decisions |
| SA-2 Researcher (data pulls) | claude-haiku-4-5 | Structured API calls, data formatting |
| SA-2 Researcher (analysis) | claude-sonnet-4-6 | Requires reasoning |
| SA-3 Developer | claude-sonnet-4-6 | Code quality requires strong reasoning |
| SA-4 QA | claude-sonnet-4-6 | Review quality must match developer |
| Geo LLM screening (new) | claude-haiku-4-5 | Volume classification, cheap |
| Geo LLM estimation (new) | claude-sonnet-4-6 | Probability estimation, needs accuracy |

## Context Window Rule

- All agents monitor context window usage
- At ~80% context: save progress to `memory/agents/<agent>-handoff.md`, start fresh session
- Handoff file must include: done, in-progress, remaining, issues, relevant file paths
- CEO spawns the new session with handoff file as context

## Current Phase Status

- Phase 1 (Cleanup): ✅ COMPLETE — QA PASSED 2026-03-26
- Phase 2 (Model Routing): ✅ COMPLETE — documented here
- Phase 3 (Backtest Infrastructure): 🔜 NEXT
- Phase 4 (Geo Auto-Trading): ⏳ PENDING
- Phase 5 (CPI Automation): ⏳ PENDING
- Phase 6 (LIVE Prep): ⏳ PENDING — David's decision only

## Key Rules (summary — full rules in workspace/rules.md)

- No manual trades. All modules through bot/strategy.py.
- No live trading without David's explicit "go live"
- No pip install, no git push, no secrets/ modifications
- trash\ > delete (always recoverable)
- Daily progress report to David at 8pm PDT
