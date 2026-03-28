# Ruppert Trading Bot — Development Pipeline

**Version:** 2.0  
**Date:** 2026-03-28  
**Author:** Strategist (Opus)

---

## Overview

This document defines how code changes flow through the Ruppert trading bot organization. No agent edits trading code directly — all changes go through the Dev/QA pipeline.

---

## Agent Roles in the Pipeline

### CEO (Sonnet)
- **Does:** Reviews proposals, presents to David for approval
- **Does NOT:** Edit code, run tests, commit changes

### Strategist (Opus)
- **Does:** Writes architecture specs, proposes parameter changes, reviews optimizer proposals
- **Does NOT:** Implement code changes

### Data Scientist (Sonnet)
- **Does:** Identifies data bugs, proposes fixes
- **Does NOT:** Fix bugs directly

### Trader (Sonnet)
- **Does:** Reports execution issues, proposes improvements
- **Does NOT:** Modify execution code

### Dev (Sonnet)
- **Does:** Implements specs, writes code, creates PRs
- **Does NOT:** Approve own changes, deploy directly

### QA (Haiku)
- **Does:** Reviews code, runs tests, validates changes
- **Does NOT:** Write production code

---

## Pipeline Flow

```
[Issue/Spec Created]
        │
        ▼
   [Dev Receives Spec]
        │
        ▼
   [Dev Implements Code]
        │
        ▼
   [Dev Submits to QA]
        │
        ▼
   [QA Reviews & Tests]
        │
    ┌───┴───┐
    │       │
  [PASS]  [FAIL]
    │       │
    ▼       ▼
 [CEO     [Back to
 Review]   Dev]
    │
    ▼
 [David
 Approval]
    │
    ▼
 [Commit &
 Deploy]
```

---

## Spec Format

When any agent identifies a code change needed, they write a spec in this format:

### Spec Template

```markdown
# [Title]

**Type:** [Bug Fix | Feature | Refactor | Config Change]
**Priority:** [P0 Critical | P1 High | P2 Medium | P3 Low]
**Requested By:** [Agent Name]
**Date:** YYYY-MM-DD

## Problem Statement
[What's wrong or what's needed]

## Proposed Solution
[How to fix it]

## Files to Modify
- `path/to/file.py` — [what changes]

## Implementation Details
[Specific code changes, pseudocode, or examples]

## Testing Requirements
- [ ] Test case 1
- [ ] Test case 2

## Rollback Plan
[How to revert if something goes wrong]
```

### Spec Storage

- Specs go in: `docs/specs/YYYY-MM-DD-<title>.md`
- Active specs: `docs/specs/active/`
- Completed specs: `docs/specs/completed/`

---

## Dev Workflow

### 1. Receive Spec

Dev is spawned as a subagent with the spec:

```
You are Dev for the Ruppert trading bot.
Implement the following spec: [spec content]

Rules:
- Implement exactly what the spec says
- Write clean, documented code
- Include inline comments explaining non-obvious logic
- Output the complete modified files
- Do not commit — output goes to QA
```

### 2. Implement

Dev writes code and outputs:

```markdown
## Implementation Complete

### Files Modified

#### `path/to/file.py`
```python
# Full file content here
```

#### `path/to/other_file.py`
```python
# Full file content here
```

### Changes Summary
- [Change 1]
- [Change 2]

### Testing Notes
- [Any notes for QA]
```

### 3. Submit to QA

CEO spawns QA with Dev's output:

```
You are QA for the Ruppert trading bot.
Review and test the following implementation: [Dev output]
Original spec: [spec content]

Checklist:
- [ ] Code matches spec requirements
- [ ] No syntax errors
- [ ] Imports are correct
- [ ] No obvious logic bugs
- [ ] Edge cases handled
- [ ] Error handling present
- [ ] Logging appropriate
- [ ] No hardcoded secrets/values

Output: PASS or FAIL with details
```

---

## QA Workflow

### Review Checklist

1. **Spec Compliance**
   - Does the code do what the spec asked?
   - Are all requirements addressed?

2. **Code Quality**
   - Python syntax valid?
   - Imports resolve correctly?
   - Naming conventions followed?

3. **Logic Validation**
   - Happy path works?
   - Edge cases handled?
   - Error conditions covered?

4. **Safety Checks**
   - No direct truth file writes from scripts?
   - Proper event logging used?
   - No infinite loops?
   - No silent failures?

5. **Integration**
   - Import paths correct for new structure?
   - Compatible with existing code?

### QA Output

**On PASS:**
```markdown
## QA PASS

**Spec:** [title]
**Dev Implementation:** Reviewed

### Verification
- [x] Spec requirements met
- [x] Code quality acceptable
- [x] No obvious bugs
- [x] Ready for CEO review

### Notes
[Any observations]
```

**On FAIL:**
```markdown
## QA FAIL

**Spec:** [title]
**Dev Implementation:** Rejected

### Issues Found
1. [Issue 1 — what's wrong and where]
2. [Issue 2]

### Required Fixes
1. [What needs to change]
2. [What needs to change]

### Action
Return to Dev for fixes.
```

---

## CEO Review

After QA PASS, CEO reviews:

1. **Risk Assessment**
   - What could go wrong?
   - Is this change reversible?

2. **David Approval**
   - Present change to David
   - Get explicit approval

3. **Deployment**
   - Apply code changes
   - Update Task Scheduler if needed
   - Verify in production

---

## Emergency Hotfix Flow

For P0 Critical issues during live trading:

1. **CEO identifies critical bug**
2. **CEO writes minimal spec** (no full template needed)
3. **Dev implements fix**
4. **CEO reviews** (QA can be skipped for P0)
5. **David approves** (can be expedited)
6. **Deploy immediately**
7. **Full QA review post-deployment**

**Example P0:** Circuit breaker not triggering, trades executing without size limits, API credentials exposed.

---

## Config Changes

Parameter changes (thresholds, caps, etc.) follow abbreviated flow:

1. **Optimizer proposes change** → `logs/proposals/optimizer_proposals_*.md`
2. **CEO reviews proposal**
3. **Strategist validates** (model assumptions, edge cases)
4. **David approves**
5. **Dev updates `config/config.py`**
6. **QA validates syntax**
7. **Deploy**

No full spec needed for config-only changes.

---

## Pipeline Anti-Patterns

### ❌ Never Do These

1. **Agent edits code directly**
   - Even "obvious" fixes go through pipeline
   - "Just this once" is how bugs happen

2. **Skip QA for "simple" changes**
   - Simple changes have simple bugs
   - QA catches import errors, typos

3. **Self-approve changes**
   - Dev cannot approve own code
   - CEO cannot approve without David

4. **Edit production files directly**
   - Always work on proposed changes
   - Apply only after full pipeline

5. **Bypass David for "urgent" fixes**
   - P0 gets expedited review, not skipped review
   - Document the urgency, still get approval

---

## Task Scheduler Integration

After code changes that affect scheduled tasks:

1. **Identify affected tasks**
2. **Update Task Scheduler entries**
3. **Verify paths are correct**
4. **Test task runs manually**

### Current Task Inventory

| Task Name | Schedule | Command | Notes |
|-----------|----------|---------|-------|
| Ruppert-Full-7AM | 7:00 AM | `python ruppert_cycle.py full` | Full scan + trading |
| Ruppert-Full-3PM | 3:00 PM | `python ruppert_cycle.py full` | Full scan + trading |
| Ruppert-Check-10PM | 10:00 PM | `python ruppert_cycle.py check` | Position check only |
| Ruppert-Report-7AM | 7:00 AM (Sun) | `python ruppert_cycle.py report` | Weekly optimizer |
| Ruppert-PostMonitor | Every 30min | `python -m agents.trader.post_trade_monitor` | Polling fallback |
| Ruppert-WSFeed | Market hours | `python -m agents.data_analyst.ws_feed` | WS price feed |
| Ruppert-Dashboard | Always | `uvicorn dashboard.api:app --port 8765` | Dashboard API |

---

## Deployment Checklist

Before any deployment:

- [ ] QA PASS confirmed
- [ ] David approval received
- [ ] Backup current files
- [ ] Apply changes
- [ ] Verify syntax: `python -m py_compile <file>`
- [ ] Test import: `python -c "import <module>"`
- [ ] Run manual test if applicable
- [ ] Monitor first cycle after deployment
- [ ] Document what was deployed

---

## Rollback Procedure

If deployment breaks something:

1. **Immediate:** Stop affected Task Scheduler tasks
2. **Restore:** Replace files from backup
3. **Verify:** Test restored code works
4. **Resume:** Re-enable Task Scheduler tasks
5. **Document:** What went wrong, why
6. **Fix:** Go back through pipeline with corrected spec

---

## Spec Examples

### Example: Bug Fix Spec

```markdown
# Fix P&L Cache Race Condition

**Type:** Bug Fix
**Priority:** P1 High
**Requested By:** Data Scientist
**Date:** 2026-03-28

## Problem Statement
Multiple scripts call `_update_pnl_cache()` directly, causing race conditions.
When two scripts update simultaneously, one write can be lost.

## Proposed Solution
Remove direct P&L cache writes. Scripts log SETTLEMENT events.
Data Scientist synthesizes P&L from trade logs.

## Files to Modify
- `agents/trader/post_trade_monitor.py` — Remove `_update_pnl_cache()` calls
- `agents/trader/position_monitor.py` — Remove `_update_pnl_cache()` calls

## Implementation Details
Replace:
```python
_update_pnl_cache(round(pnl, 2))
```

With:
```python
from scripts.event_logger import log_event
log_event('SETTLEMENT', {'ticker': ticker, 'pnl': round(pnl, 2), ...})
```

## Testing Requirements
- [ ] No syntax errors after change
- [ ] Settlement events appear in `logs/raw/events_*.jsonl`
- [ ] P&L still accurate after synthesis runs

## Rollback Plan
Restore previous versions from backup.
```

### Example: Feature Spec

```markdown
# Add Researcher Agent Weekly Scan

**Type:** Feature
**Priority:** P2 Medium
**Requested By:** CEO
**Date:** 2026-03-28

## Problem Statement
No systematic process for discovering new trading opportunities.
Currently relies on manual observation.

## Proposed Solution
Create Researcher agent that runs weekly to:
- Scan for new Kalshi series
- Identify underserved markets
- Generate opportunity reports

## Files to Create
- `agents/researcher/__init__.py`
- `agents/researcher/research_agent.py`
- `agents/researcher/market_scanner.py`

## Implementation Details
[See AGENT_OWNERSHIP_ARCHITECTURE.md Part 5.4]

## Testing Requirements
- [ ] Script runs without errors
- [ ] Report generated in `research/reports/`
- [ ] JSON output is valid

## Rollback Plan
Delete new files, remove from Task Scheduler.
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-26 | Initial pipeline definition |
| 2.0 | 2026-03-28 | Updated for new agent structure, added spec format |

---

*Pipeline document complete. All agents follow this process.*
