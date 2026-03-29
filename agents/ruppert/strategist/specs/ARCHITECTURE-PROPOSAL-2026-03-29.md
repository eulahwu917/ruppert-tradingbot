# Architecture Proposal — Documentation & File Structure Overhaul
**Author:** Strategist  
**Date:** 2026-03-29  
**Status:** APPROVED — EXECUTED 2026-03-29  
**Ownership:** Strategist owns this document going forward. Only Strategist updates it.

---

## 1. Current State Assessment

### What's Accurate
- All five agent ROLE.md files (`strategist`, `data_analyst`, `data_scientist`, `trader`, `researcher`) correctly reflect current team composition and file ownership.
- Memory system (two-tier: long-term MEMORY.md + dated handoffs) is consistent across Strategist, Data Analyst, Data Scientist, and Trader.
- RULES.md is broadly accurate and up to date (last updated 2026-03-26).
- README.md agent org chart is accurate and matches ROLE.md files.
- Spec file convention is mostly in practice: `agents/ruppert/{agent}/specs/` exists for strategist, data_scientist, ceo.

### What's Stale
- **PIPELINE.md** — critically out of date. Still references the old org: Architect, Optimizer, Researcher (Haiku). The current team has Strategist (Opus), Data Scientist (Sonnet), Data Analyst (Haiku), Trader (Sonnet), Researcher (Sonnet). The file even has a banner note at the top acknowledging it's legacy.
- **`environments/demo/memory/agents/team_context.md`** — still uses old SA-1/SA-2/SA-3/SA-4 designations (Optimizer, Researcher, Developer, QA). Current team structure is different.
- **PIPELINE.md model assignment table** — shows Optimizer=Sonnet, which no longer exists. Strategist (Opus) is the new equivalent.
- **RULES.md Rule 11** — reporting chain references "SA-1 (Optimizer), SA-2 (Researcher)" which no longer match team structure.

### What's Missing
- **Researcher has no MEMORY.md** — all other agents do. Researcher has no persistent memory at all.
- **File management index** — no document defines where every type of output (specs, reports, logs, truth files, research, handoffs) lives. This causes agents to invent paths.
- **CEO behavioral rules are not codified** — CEO's scope limits (no analysis, no pre-investigation, provide only observed facts to investigative agents) exist in discussion but not in CEO's ROLE.md.
- **Domain boundary document** — Data Analyst = external feeds; Data Scientist = internal integrity. This is understood but not formally written anywhere.
- **Numbering bugs in ROLE.md files:**
  - `agents/ruppert/data_scientist/ROLE.md` — "Read These On Startup" has two items numbered `3`.
  - `agents/ruppert/trader/ROLE.md` — "Read These On Startup" has two items numbered `3`.

### What's in the Wrong Place
- `agents/ruppert/data_analyst/SPEC-rest-fallback-poll.md` — loose spec file in agent root, should be in `agents/ruppert/data_analyst/specs/` (which doesn't exist yet) or `environments/demo/specs/`.
- `agents/ruppert/data_analyst/SPECS_BATCH_DA.md` — same issue, loose in agent root.
- `agents/ruppert/specs/` — two files here (`SPEC-crypto15m-threshold-relaxation.md`, `TRADER-SPECS-ROUND2.md`). These are agent-specific specs parked at the wrong level. Trader spec belongs in `agents/ruppert/trader/specs/`, crypto spec belongs with Strategist.
- `environments/demo/DEV_ROLE.md` — agent documentation in the environment directory. Belongs in `agents/ruppert/dev/ROLE.md` (flagged separately below — requires David decision).
- `environments/demo/specs/` — large collection of specs in the environment directory rather than in owning agent's specs folder. This creates confusion about spec ownership.
- `environments/demo/memory/agents/team_context.md` — shared team context in the environment directory. Should be at `memory/agents/team_context.md` (workspace-level) or simply absorbed into PIPELINE.md.

### Confirmed: settlement_checker → synthesizer Integration
Item #11 from deferred list: confirmed. `environments/demo/settlement_checker.py` line 272 imports and calls `synthesizer.synthesize_pnl_cache`. The trigger is wired. No action needed.

### "Data Agent" Naming Confusion
Item #12: `environments/demo/ruppert_cycle.py` lines 1117 and 1152 reference "Data Agent" in comments. These are **comments only** — a code search confirms the actual class/function is `data_agent.py` (the file name). Comments should say "Data Scientist" to reduce confusion. This is a Dev task (comment cleanup), not a doc task. Flag for CEO to add to next Dev batch.

---

## 2. Proposed Changes — Per File

### CEO (`agents/ruppert/ceo/ROLE.md`)
**Changes:** Add explicit behavioral rules for CEO scope. Currently missing.

**Add this section before the final Rules block:**

```markdown
## CEO Behavioral Rules (What CEO Does NOT Do)

- CEO routes and compiles. CEO does NOT analyze, pre-investigate, or edit code — ever.
- When spawning investigative agents (Strategist, Data Scientist): provide **observed facts only** — no hypotheses, no suspected causes, no pre-analysis.
- Spec must be **fully reviewed by all relevant parties** BEFORE going to Dev.
- Dev must NOT be sent a build task before role owners have reviewed all flags.
- If CEO spots a bug: write what was observed (not why) → spawn Strategist or Data Scientist to investigate → wait for findings → write spec → Dev → QA.
```

**Rationale:** CEO currently has a clear "never touch code" rule but no rule about pre-investigation or hypothesis injection, which caused problems in past sessions.

**Note:** CEO ROLE.md changes require CEO (Ruppert) to review jointly with David before applying.

---

### Data Scientist (`agents/ruppert/data_scientist/ROLE.md`)
**Changes:**
1. Fix duplicate `3.` numbering in "Read These On Startup" (items 3 and 3 — second should be 4, etc. — renumber through 6).
2. Add explicit domain boundary statement.

**Numbering fix (Read These On Startup):**
```
1. MEMORY.md
2. memory/agents/data-scientist-*.md (handoff)
3. improvement_log.md (if exists)
4. data_agent.py
5. synthesizer.py
6. environments/demo/logs/truth/pnl_cache.json
7. environments/demo/logs/pending_alerts.json
```

**Add to Domain section:**
```markdown
**Domain boundary:** You own internal data integrity. Data Analyst owns external data fetching.
You never fetch from external APIs directly — delegate to Data Analyst.
```

---

### Trader (`agents/ruppert/trader/ROLE.md`)
**Changes:**
1. Fix duplicate `3.` numbering in "Read These On Startup" (same bug as Data Scientist).

**Numbering fix (Read These On Startup):**
```
1. MEMORY.md
2. memory/agents/trader-*.md (handoff)
3. improvement_log.md (if exists)
4. trader.py
5. position_tracker.py
6. main.py
7. environments/demo/logs/tracked_positions.json
```

---

### Data Analyst (`agents/ruppert/data_analyst/ROLE.md`)
**Changes:**
1. Add explicit domain boundary statement.
2. Note that Data Analyst specs go in `agents/ruppert/data_analyst/specs/` (create directory).

**Add to Domain section:**
```markdown
**Domain boundary:** You own external data fetching only. You do NOT synthesize, audit, or write truth files.
All your outputs go to Data Scientist for review before any downstream use.
```

---

### Researcher (`agents/ruppert/researcher/ROLE.md`)
**Changes:**
1. Add Memory System section (currently absent).

**Add after the Rules section:**
```markdown
## Memory System

- **Long-term:** `agents/ruppert/researcher/MEMORY.md` — synthesized learnings, persists forever.
  Update when you discover recurring patterns, dead markets, or market-specific constraints.
- **Handoffs:** `memory/agents/researcher-YYYY-MM-DD.md` — where you left off. Write on context limit.

## Read These On Startup

1. `agents/ruppert/researcher/MEMORY.md` — your long-term memory (if exists)
2. `memory/agents/researcher-*.md` — latest handoff note (if exists)
3. `logs/opportunities_backlog.json` (if exists)
4. `agents/ruppert/researcher/research_agent.py`
5. `agents/ruppert/researcher/market_scanner.py`
```

---

### PIPELINE.md (full rewrite — see Section 4 below)

---

### RULES.md
**Changes:**
1. Fix Rule 11 — update reporting chain to use current agent names (not SA-1/SA-2).
2. Add root cause discipline rule (deferred item #14, #16).
3. Confirm Rule 0 (Data Analyst output reviewed by Data Scientist before Dev) — already present as Rule 0 in current PIPELINE.md; move into RULES.md since PIPELINE.md is being rewritten.

**Updated Rule 11:**
```markdown
## 11. Reporting Chain

Developer builds → QA reviews → [FAIL: back to Dev] → loop until QA PASS → CEO → David (if real money)
Strategist / Data Scientist / Researcher → CEO → David (if CEO unsure or real money)

- Dev output ALWAYS goes to QA before CEO sees it
- QA reports PASS/FAIL/WARNINGS; never modifies code; sends FAIL back to Developer with specifics
- CEO escalates to David when:
  - Phase is fully QA-verified (PASS)
  - Decision involves manual positions or real money
  - Core algo parameters change
  - Something irreversible is about to happen
  - CEO is genuinely unsure
```

**Add new Rule 15:**
```markdown
## 15. Root Cause Discipline

- All bug fixes must address root cause. No masking. No easy fixes.
- Masking = making the symptom disappear without understanding why it occurred.
- If the root cause requires more investigation, say so — don't ship a workaround.
- If time pressure exists: tell David ("can't fix root cause before next scan window — want to delay or approve exception?"). Never self-authorize a shortcut.
```

**Add new Rule 16 (consolidate into Rule 15 if preferred):**
```markdown
## 16. Data Analyst Spec Review Gate

Data Analyst (Haiku) output must be reviewed by Data Scientist (Sonnet) before going to Dev.
Haiku makes mistakes. Data Scientist is the reviewer. This applies to:
- Specs authored by Data Analyst
- Data analysis or infrastructure proposals
- Any work product that will be handed to Dev for implementation
This rule exists because model tier differences create systematic blind spots.
```

---

### `environments/demo/memory/agents/team_context.md`
**Changes:** Update to reflect current team structure. SA-1/SA-2/SA-3/SA-4 designations are legacy (those were Optimizer/Researcher/Developer/QA). Current agents: Strategist, Data Scientist, Data Analyst, Trader, Researcher, Dev, QA.

This file is in the wrong directory (should be `memory/agents/team_context.md`), but moving it risks breaking any references — **flag for David to decide** (see Section 5).

---

## 3. New Documents to Create

### A. `agents/ruppert/FILE_INDEX.md` — File Management Index
The single source of truth for where every type of output lives.

**Proposed content:**

```markdown
# FILE_INDEX.md — Where Everything Lives
_Every agent reads this to know where to put and find things._
_Last updated: 2026-03-29_

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
```

---

### B. `agents/ruppert/researcher/MEMORY.md` — Researcher Long-Term Memory
Currently absent. Researcher is the only agent without persistent memory.

**Proposed initial content:**

```markdown
# MEMORY.md — Researcher Long-Term Memory
_Owned by: Researcher agent. Updated after scans, discoveries, or pattern findings._

---

## Market Scan History
- Last light scan: 2026-03-29 (weekly Sunday scan)
- Last deep scan: not yet run

## Known Market Constraints
- California-based operation: avoid sports and election prediction markets
- Geo markets: high edge variance, manual approval required

## Discovered Opportunities
- See `logs/opportunities_backlog.json` for active queue

## Lessons Learned
- (populate after first real scan cycle)
```

---

### C. `agents/ruppert/data_analyst/specs/` directory
Create this directory so Data Analyst has a proper home for its specs (currently cluttering agent root).

**Files to move (documentation only — no Python):**
- `agents/ruppert/data_analyst/SPEC-rest-fallback-poll.md` → `agents/ruppert/data_analyst/specs/SPEC-rest-fallback-poll.md`
- `agents/ruppert/data_analyst/SPECS_BATCH_DA.md` → `agents/ruppert/data_analyst/specs/SPECS_BATCH_DA.md`

**Note:** These are .md files, not Python files. Moving them is safe (no imports affected).

---

### D. `agents/ruppert/trader/specs/` directory
Create this directory. Move misplaced spec:
- `agents/ruppert/specs/TRADER-SPECS-ROUND2.md` → `agents/ruppert/trader/specs/TRADER-SPECS-ROUND2.md`

---

### E. `agents/ruppert/strategist/specs/` for Strategist crypto spec
- `agents/ruppert/specs/SPEC-crypto15m-threshold-relaxation.md` → `agents/ruppert/strategist/specs/SPEC-crypto15m-threshold-relaxation.md`

After above moves, `agents/ruppert/specs/` directory will be empty and can be removed. **Verify before deleting.**

---

## 4. PIPELINE.md — Full Proposed Rewrite

```markdown
# PIPELINE.md — Ruppert Team Pipeline & Operating Rules
_Last updated: 2026-03-29 | Approved by David Wu_

---

## Org Structure

```
David Wu (Owner — final call on everything)
    │
   CEO (claude-sonnet-4-6)
    │
    ├── Strategist (claude-opus-4-5) — algorithm, edge, optimization, specs
    ├── Trader (claude-sonnet-4-6) — execution, positions
    ├── Data Scientist (claude-sonnet-4-6) — P&L, truth files, audit
    │       └── Data Analyst (claude-haiku-4-5) — external data fetching
    ├── Researcher (claude-sonnet-4-6) — market discovery
    ├── Dev (Claude Code) — builds all specs
    └── QA (Claude Code, separate session) — verifies all Dev output
```

---

## Domain Boundaries

| Agent | Owns | Does NOT own |
|-------|------|-------------|
| Strategist | Algorithm, edge, sizing, optimization specs | Code, execution, data |
| Trader | Trade execution, position management | Algorithm decisions, data |
| Data Scientist | Truth files, P&L, audit, synthesis | External data fetching |
| Data Analyst | External API calls, price cache, weather data | Truth files, synthesis |
| Researcher | Market discovery, opportunity reports | Trading, execution |
| CEO | Routing, reporting, spec review, David liaison | Analysis, investigation, code |
| Dev | Building from specs | Design, testing |
| QA | Verification | Code changes |

---

## Pipelines

### Code Change Pipeline
```
CEO identifies need
  → Owner agent (Strategist / Data Scientist / etc.) writes spec
  → If Data Analyst authored spec: Data Scientist reviews before Dev
  → CEO confirms all relevant parties have reviewed
  → Dev implements
  → QA verifies (separate session)
  → CEO reviews QA result
  → Commits (DEMO) or escalates to David (LIVE)
```

### Algorithm Change Pipeline
```
Strategist proposes change (from optimizer or trade data)
  → CEO reviews proposal
  → David approves
  → Dev implements
  → QA validates
  → Ships
```

### Bug Investigation Pipeline
```
CEO observes anomaly (records facts only — no hypotheses)
  → CEO routes to appropriate investigative agent
    (Data Scientist for data/P&L issues, Strategist for algo issues)
  → Investigative agent finds root cause
  → Investigative agent writes spec for fix
  → All relevant parties review spec
  → Dev implements
  → QA verifies
  → CEO approves and commits
```

### Researcher Pipeline
```
Scheduled scan (Sunday 8am weekly / first Sunday monthly deep)
  OR CEO-triggered scan
  → Researcher produces report to reports/research/
  → Researcher updates opportunities_backlog.json
  → CEO reviews findings
  → David informed of high-value opportunities
  → CEO initiates Strategist evaluation if warranted
```

### LIVE Deployment Pipeline
```
LIVE requires David's explicit 3-confirmation approval
  → Pre-flight scorecard (all modules GREEN/YELLOW/RED)
  → David reviews scorecard
  → David says "go live" (three times, explicitly)
  → No agent can activate LIVE autonomously. Ever.
```

---

## Hard Rules

### Rule 0 — Data Analyst Review Gate
Data Analyst (Haiku) output must be reviewed by Data Scientist (Sonnet) before going to Dev.
Haiku makes mistakes. Data Scientist is the reviewer. Applies to: specs, data analysis, infrastructure proposals, any work product from Data Analyst.

### Rule 1 — No Direct Code Editing
**CEO, Strategist, Data Scientist, and all role agents NEVER edit production code.**
This means NEVER — not for one-liners, not for "trivial" fixes, not for anything.
ALWAYS: write spec → Dev → QA.

### Rule 2 — CEO Behavioral Constraints
- CEO routes and compiles. CEO does NOT analyze, pre-investigate, or edit code.
- When spawning investigative agents: provide **observed facts only**. No hypotheses. No suspected causes.
- Spec must be fully reviewed by all relevant parties BEFORE going to Dev.
- Dev must NOT be sent a build task before role owners have reviewed flags.

### Rule 3 — Dev/QA Independence
- Dev does NOT self-approve.
- QA is always a separate session.
- CEO does NOT see phase output until QA returns PASS or PASS WITH WARNINGS.

### Rule 4 — LIVE Requires David
No LIVE trades without David's explicit 3-confirmation go-ahead. No agent self-authorizes.

### Rule 5 — Root Cause Discipline
All bug fixes must address root cause. No masking. No easy fixes.
If root cause is unclear: investigate first, then spec. Never ship a workaround and call it a fix.
Time pressure is not an exception — escalate to David if timeline conflicts with proper process.

### Rule 6 — Optimizer/Algo Proposals
- Strategist proposals require David approval before implementation.
- Minimum 30 scored trades per domain before Bonferroni-corrected proposals are meaningful.
- Strategist owns all algorithm parameters: confidence thresholds, Kelly tiers, exit rules, sizing.

### Rule 7 — Context Window
All agents monitor context usage. At ~80%: save handoff to `memory/agents/{agent}-handoff.md`, then start fresh. Never let a session run to the limit.

### Rule 8 — Spec Location Convention
- Agent-specific specs: `agents/ruppert/{agent}/specs/`
- Cross-agent or environment specs: `environments/demo/specs/`
- Specs must be reviewed by domain owner before going to Dev.

---

## Model Assignments

| Agent | Model | Notes |
|-------|-------|-------|
| CEO | claude-sonnet-4-6 | Orchestration, routing, reporting |
| Strategist | claude-opus-4-5 | Algorithm decisions, deep analysis |
| Trader | claude-sonnet-4-6 | Execution, position management |
| Data Scientist | claude-sonnet-4-6 | Truth files, P&L audit |
| Data Analyst | claude-haiku-4-5 | Fast, cheap data pulls |
| Researcher | claude-sonnet-4-6 | Market discovery, analysis |
| Dev | Claude Code (Sonnet) | Build from specs |
| QA | Claude Code (Sonnet) | Separate session, verify only |
| Geo LLM screening | claude-haiku-4-5 | Volume classification |
| Geo LLM estimation | claude-sonnet-4-6 | Probability estimation |
```

---

## 5. Flagged Demo Items — David Decides

These are in `environments/demo/` and out of scope for the main proposal. Flagged separately for David's decision.

### Flag A: `environments/demo/DEV_ROLE.md`
**Issue:** Dev's ROLE.md is living in the environment directory, not in `agents/ruppert/dev/ROLE.md`.  
**Why this matters:** All other agent ROLE.md files live in `agents/ruppert/{agent}/ROLE.md`. Dev is the exception — possibly because Dev has no Python files in agents/ (Dev is a pipeline agent, not a module agent).  
**Options:**
1. Move to `agents/ruppert/dev/ROLE.md` (creates a dev/ directory with only a ROLE.md — fine)
2. Leave as-is (exception is acceptable since Dev has no agents/ module)
**Recommendation:** Move to `agents/ruppert/dev/ROLE.md` for consistency. The file itself is accurate and current — no content changes needed.

### Flag B: `environments/demo/memory/agents/team_context.md`
**Issue:** team_context.md is in `environments/demo/memory/agents/` but it's a team-wide shared document, not environment-specific.  
**Also:** Content is stale — uses SA-1/SA-2/SA-3/SA-4 designations from old org chart.  
**Options:**
1. Move to `memory/agents/team_context.md` (workspace-level) and update content
2. Delete it — its content would be fully superseded by the new PIPELINE.md
3. Leave it in demo/memory/agents/ but update content  
**Recommendation:** Option 2 — delete it. The new PIPELINE.md replaces everything in it. PIPELINE.md is now the single source of truth for team structure, model assignments, and reporting chain. Keeping team_context.md risks drift.

### Flag C: `environments/demo/memory/agents/` — Old Opus/Architect Memos
**Issue:** This directory contains memos from Architect and Opus (old agent names) that no longer map to current agents. Examples: `opus-codebase-review-2026-03-26.md`, `architect-cycle-refactor-plan-2026-03-27.md`, `architect-state.md`.  
**These are historical records, not current team state.**  
**Options:**
1. Archive them to `environments/demo/memory/agents/archive/` (some already in archive/)
2. Leave as-is (they're just old memos, not hurting anything)
**Recommendation:** Leave as-is. They're historical. Moving them provides no operational benefit and risks confusion if anyone references them.

### Flag D: `environments/demo/specs/` — Spec Consolidation
**Issue:** A large collection of specs lives in the environment directory. Per the proposed spec location convention, agent-specific specs should live in `agents/ruppert/{agent}/specs/`.  
**Examples of well-placed specs in demo/specs/:** `DS-001-account-value-double-count.md` (Data Scientist), `settlement_checker_spec.md` (cross-agent), `TRADER-SPECS-BATCH-T.md` (Trader).  
**This is a large migration and lower priority than the doc changes above.**  
**Options:**
1. Leave `environments/demo/specs/` as-is for historical specs; new specs go in agent specs/ going forward
2. Migrate all to agent folders over time
**Recommendation:** Option 1. Don't migrate existing specs — they're historical. Going forward, new specs go to `agents/ruppert/{agent}/specs/`. CEO enforces this in spec routing.

---

## 6. What Doesn't Need to Change

The following are explicitly **not** proposed for change. They're accurate, working, and touching them creates risk without benefit.

| File/Directory | Why Leave Alone |
|----------------|-----------------|
| `README.md` | Accurate. Agent org chart matches current team. Minor reference to `environments/demo/docs/PIPELINE.md` at bottom (that path doesn't exist — a comment-only issue, not operational). |
| `SOUL.md` | Accurate and current. CEO/David governance. |
| `AGENTS.md` | Accurate. CEO/David governance. |
| `USER.md` | Accurate. CEO/David governance. |
| `IDENTITY.md` | Accurate. CEO/David governance. |
| `agents/ruppert/ceo/specs/CEO_SPECS_BATCH_C.md` | Historical spec. Leave in place. |
| `agents/ruppert/strategist/specs/SPECS-BATCH-S.md` | Historical spec. Leave in place. |
| `agents/ruppert/data_scientist/specs/DATA_SCIENTIST_SPECS_R2.md` | Historical spec. Leave in place. |
| `environments/demo/memory/agents/strategist-optimizer-decision-2026-03-28.md` | Correct location for a Strategist memo. |
| All Python files, `__init__.py`, `__pycache__/` | Out of scope. No Python changes in this proposal. |
| All `logs/`, `reports/`, `secrets/` directories | Runtime outputs. Not doc files. |
| `HEARTBEAT.md` | CEO/operational file. Not in scope. |
| `agents/ruppert/strategist/MEMORY.md` | Current and accurate. Updated by Strategist as needed. |
| `agents/ruppert/data_analyst/MEMORY.md` | Exists. Content is agent's own. |
| `agents/ruppert/data_scientist/MEMORY.md` | Exists. Content is agent's own. |
| `agents/ruppert/trader/MEMORY.md` | Exists. Content is agent's own. |

---

## Deferred Item Checklist

| # | Item | Disposition |
|---|------|-------------|
| 1 | Strategist leads agent file structure proposal | ✅ This document |
| 2 | CEO weighs in on workspace root files | ✅ Proposed: leave alone (Section 6). CEO reviews jointly with David. |
| 3 | File management index | ✅ New doc: `agents/ruppert/FILE_INDEX.md` (Section 3A) |
| 4 | PIPELINE.md full rewrite | ✅ Full rewrite in Section 4 |
| 5 | Data Analyst spec ownership: DS reviews before Dev | ✅ Codified as Rule 0 in new PIPELINE.md and in RULES.md Rule 16 |
| 6 | Domain boundaries explicit | ✅ Added to Data Scientist and Data Analyst ROLE.md (Section 2); table in PIPELINE.md |
| 7 | Demo environment: no agent .md files | ✅ Flagged: DEV_ROLE.md (Flag A). David decides. |
| 8 | Workspace root .md review | ✅ Section 6: all workspace root files assessed; none need changes |
| 9 | Spec file location convention | ✅ Codified in PIPELINE.md Rule 8; new agent specs/ dirs in Section 3 |
| 10 | Researcher: needs MEMORY.md | ✅ New doc proposed (Section 3B) |
| 11 | settlement_checker → synthesizer trigger | ✅ Confirmed already done. No action needed. |
| 12 | "Data Agent" naming confusion | ✅ Assessed: comments only in ruppert_cycle.py. Flag for Dev comment cleanup in next batch. |
| 13 | ROLE.md numbering bugs | ✅ Fixes proposed for Data Scientist and Trader (Section 2) |
| 14 | Root cause discipline | ✅ PIPELINE.md Rule 5; RULES.md Rule 15 |
| 15 | CEO behavioral rules | ✅ CEO ROLE.md addition (Section 2); PIPELINE.md Rule 2 |
| 16 | All fixes: root cause only | ✅ Same as #14 |
| — | Additional CEO behavioral rules | ✅ PIPELINE.md Rule 2 (all four points incorporated) |

---

## Implementation Order (If David Approves)

**Phase 1 — Safe fixes (no risk, no reviews needed):**
1. Fix numbering bugs in Data Scientist ROLE.md (#3 duplicate)
2. Fix numbering bugs in Trader ROLE.md (#3 duplicate)
3. Create `agents/ruppert/researcher/MEMORY.md` (new file, no dependencies)
4. Create `agents/ruppert/data_analyst/specs/` directory
5. Move two loose .md spec files from data_analyst root to data_analyst/specs/
6. Create `agents/ruppert/trader/specs/` directory
7. Move TRADER-SPECS-ROUND2.md from agents/ruppert/specs/ to trader/specs/
8. Move crypto spec from agents/ruppert/specs/ to strategist/specs/

**Phase 2 — Content updates (low risk):**
9. Add domain boundaries to Data Analyst ROLE.md
10. Add domain boundaries to Data Scientist ROLE.md
11. Add Memory System section to Researcher ROLE.md
12. Write PIPELINE.md (full rewrite — highest value item)
13. Add Rule 15 (root cause) to RULES.md
14. Add Rule 16 (DA review gate) to RULES.md
15. Update RULES.md Rule 11 (reporting chain agent names)
16. Create FILE_INDEX.md

**Phase 3 — CEO review required:**
17. CEO ROLE.md behavioral rules addition (CEO + David review jointly)

**Phase 4 — David decides (flagged items):**
18. DEV_ROLE.md location (Flag A)
19. team_context.md disposition (Flag B — recommend delete)

**Out of scope for now:**
- environments/demo/specs/ migration (Flag D) — leave as-is, enforce going forward
- "Data Agent" comment fix in ruppert_cycle.py — add to next Dev batch

---

*Strategist — 2026-03-29 — This document is the single source of truth for agent architecture going forward. Only Strategist updates it.*
