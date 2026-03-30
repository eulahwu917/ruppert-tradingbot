# Full Domain Audit Workflow
_Last updated: 2026-03-29 — based on full system audit session_

---

## Overview

Run this workflow whenever David requests a full system audit. Repeat the loop until all domains come back clean.

**Domains:** Trader, Strategist, Data Scientist + Data Analyst (combined), CEO, Researcher

---

## Phase 1 — Audit (parallel)

Spawn all domain audit agents simultaneously. Each reads their own files and produces findings.

**Domains to spawn in parallel:**
- Trader → `agents/ruppert/trader/`
- Strategist → `agents/ruppert/strategist/`
- Data Scientist → `agents/ruppert/data_scientist/` (also audits Data Analyst findings — see Phase 1b)
- Data Analyst → `agents/ruppert/data_analyst/`
- CEO → `environments/demo/ruppert_cycle.py`, `agents/ruppert/trader/main.py`, `agents/ruppert/ceo/brief_generator.py`
- Researcher → `agents/ruppert/researcher/`

**Audit prompt template (per agent):**
> You are the [Agent] for the Ruppert trading bot. This is a full domain audit of all files you own.
>
> **Before starting:** Read `memory/changelog/CHANGELOG.md`. For any finding you identify:
> - If it matches a prior **Fixed+QA-passed** entry → skip it (already resolved)
> - If it matches a prior **False-alarm** entry → skip it unless circumstances have changed
> - If it matches a prior **Deferred** entry → check if the deferral condition has been met
> - If it touches the same file/function as any prior entry → read the domain detail file at `memory/changelog/audit-logs/` before writing your spec
>
> Read every file in your domain. For each issue found, classify as Critical / High / Medium / Low with:
> - File and line numbers
> - What the bug/issue is (be precise)
> - Why it matters
> - Severity rationale
>
> Save findings to `memory/agents/audit-[agent]-YYYY-MM-DD.md`.

**Data Analyst special rule:** Data Analyst audits their own domain but does NOT write specs. Their findings go to Data Scientist for review in Phase 1b.

---

## Phase 1b — Data Scientist reviews Data Analyst findings

After both DS and DA audits complete, spawn Data Scientist with both sets:

> You are the Data Scientist. The Data Analyst completed their domain audit — findings at `memory/agents/audit-data-analyst-YYYY-MM-DD.md`. Your own audit findings are at `memory/agents/audit-data-scientist-YYYY-MM-DD.md`.
>
> Review the Data Analyst findings. Amend, accept, or reject each one with your reasoning. You own all specs for both domains.
>
> Save your amended DA findings to `memory/agents/audit-da-amended-YYYY-MM-DD.md`.

---

## Phase 2 — Spec writing (parallel)

Spawn one spec agent per domain with their audit findings. Each produces formal implementation-ready specs.

**Spec prompt template:**
> You are the [Agent]. You completed a domain audit and found X issues (findings at `memory/agents/audit-[agent]-YYYY-MM-DD.md`).
>
> Write formal implementation-ready specs for every finding with:
> - ID: [AGENT]-C1, [AGENT]-H1, [AGENT]-M1, [AGENT]-L1 (C=critical, H=high, M=medium, L=low, sequential)
> - File + line numbers
> - Exact BEFORE/AFTER code blocks
> - Test instructions
> - Notes for Dev
>
> Save to `memory/agents/specs-[agent]-YYYY-MM-DD.md`.

**Data Scientist spec note:** DS writes specs for both DS domain AND the amended DA domain in one file (`specs-data-scientist-YYYY-MM-DD.md`).

---

## Phase 3 — Dev → QA batches (by domain, sequential)

Process one domain at a time. Recommended order:
1. **Trader** (usually has the most criticals — live-money safety)
2. **Strategist**
3. **Data Scientist + Data Analyst** (combined spec file)
4. **CEO**
5. **Researcher** (usually smallest)

### Dev prompt template:
> You are Dev for the Ruppert trading bot. Implement the following N specs for the [Agent] domain.
> All specs have exact BEFORE/AFTER code blocks — implement them precisely as written. Do not modify anything outside the specified lines.
>
> [paste full spec file contents]
>
> After all edits:
> 1. Run `python -m py_compile [all modified files]` from workspace root
> 2. Fix any syntax errors before finishing
> 3. Do NOT git commit — QA handles that
> 4. Report which specs were applied and confirm syntax check passed

### QA prompt template:
> You are QA for the Ruppert trading bot. Dev just applied N specs to the [Agent] domain. Verify each change.
>
> Files to review: [list]
>
> What was changed: [list each spec ID and what was done]
>
> QA checklist:
> - Read each changed section and confirm it matches the spec
> - Check for unintended side effects in surrounding code
> - [domain-specific checks]
> - Run syntax check: `python -m py_compile [files]`
>
> If all pass:
> ```
> git add [explicit file list]
> git commit -m "[commit message listing all spec IDs]"
> git push
> ```
>
> If any fail: Do NOT commit. Report exactly what failed and the correct fix.

**Key rules:**
- Dev never commits — QA owns all commits
- Each QA prompt includes the exact `git add` + `git commit -m` with all modified files listed explicitly
- Specs resolved-via-parent (e.g., DA-M2 resolved by DA-H1) noted in Dev task so QA can mark them without separate verification
- Audit agents receive observed facts only — no hypotheses in prompts

---

## Phase 4 — Verification loop

After all batches are committed, **re-run Phase 1** (all audit agents in parallel again).

- If any domain comes back with new findings → write specs → run Dev→QA batch for that domain
- If all domains come back clean → proceed to Phase 5
- Repeat until clean

**Why loop:** Fixes can introduce regressions. A second audit pass also catches things the first pass missed, especially in code that was modified.

---

## Phase 5 — CEO Housekeeping

After all domains are clean, CEO does a full housekeeping sweep across the **entire codebase**.

**CEO housekeeping prompt:**
> You are the CEO for the Ruppert trading bot. All domain audits are complete and fixes have been applied.
>
> Do a full housekeeping sweep across the entire codebase — not just your own domain. Review:
>
> 1. **Stale files** — scripts, modules, or config files that are no longer called by anything. Verify via grep/search before archiving.
> 2. **Dead imports** — modules imported but never used in key files
> 3. **Orphaned specs/docs** — spec files in memory/ or agents/ that reference code that no longer exists
> 4. **Archive candidates** — anything confirmed unused: move to `environments/demo/archive/` (never delete)
> 5. **Stale comments** — docstrings or inline comments referencing old behavior, old file paths, or old agent names
> 6. **TODO/FIXME sweep** — list all TODOs/FIXMEs found; flag any that are now irrelevant given today's fixes
> 7. **Update FILE_INDEX.md** — review `agents/ruppert/FILE_INDEX.md` and update any paths, sections, or descriptions that are now stale given today's changes. This is mandatory at the end of every housekeeping phase.
>
> Rules:
> - NEVER delete files — archive only (`environments/demo/archive/` for demo files, `archive/` for workspace-level)
> - Always verify a file is no longer in use (via grep) before archiving
> - Stale comments in code: write a spec for Dev (do not edit code directly)
> - Orphaned docs: archive directly (no Dev needed)
> - FILE_INDEX.md: edit directly (no Dev needed — it's a doc file)
>
> Output:
> - List of files archived (with reason)
> - List of stale comments found → specs for Dev
> - List of TODOs/FIXMEs reviewed (keep or dismiss)
> - Summary of FILE_INDEX.md changes made
> - Anything that needs David's decision

---

## Phase 6 — Write Audit Log

After housekeeping is complete, CEO writes the permanent audit record.

**Folder structure:**
```
memory/changelog/
  CHANGELOG.md              ← master index (audit + runtime findings)
  audit-logs/               ← full per-domain detail files
  runtime/                  ← bugs/alerts surfaced between audits
  archive/                  ← entries older than 60 days (Fixed+QA-passed)
```

**Steps:**
1. Read all audit finding files from this loop: `memory/agents/audit-{domain}-YYYY-MM-DD.md` and `memory/agents/audit2-{domain}-YYYY-MM-DD.md`
2. Update `memory/changelog/CHANGELOG.md` — add a new date section with one-line entries for every finding. Format: `{ID} | {description} | {status}`
   - Status values: `Fixed (commit hash) QA-passed` / `False-alarm (reason)` / `Deferred (condition to revisit)` / `Dismissed`
3. Create domain detail files: `memory/changelog/audit-logs/YYYY-MM-DD-{domain}.md` — full detail per finding (no raw code blobs, descriptions only)
4. For runtime issues surfaced during the session: update `memory/changelog/runtime/YYYY-MM-DD-issues.md`
5. Archive temp files: move `memory/agents/audit-*.md`, `memory/agents/audit2-*.md`, `memory/agents/specs-*.md` from this loop to `memory/agents/archive/`
6. Pruning: move Fixed+QA-passed entries older than 60 days from CHANGELOG into `memory/changelog/archive/`
7. Commit: `git add agents/ruppert/ceo/audit-workflow.md agents/ruppert/FILE_INDEX.md` (memory/ is gitignored — no need to add those)

---

## Phase 7 — System Restart Check

After the audit log is written, CEO checks whether any persistent processes need restarting due to code changes in this session.

**Persistent processes to check:**
- `ws_feed.py` (WS feed) — PID in `logs/ws_feed_heartbeat.json`
- `ws_feed_watchdog.py` (Watchdog) — Task Scheduler task `Ruppert-WS-Watchdog`
- Dashboard (`uvicorn`) — Task Scheduler task `RuppertDashboard`

**Files that trigger a restart if changed:**
- ws_feed.py → restart WS feed (watchdog will do it automatically if killed)
- ws_feed_watchdog.py → restart watchdog Task Scheduler task
- dashboard/api.py → restart dashboard

**Procedure:**
1. Check which files were modified this audit session (from git log or commit messages)
2. For each modified file, check if the corresponding process is running the OLD code:
   - WS feed: compare heartbeat PID start time vs commit time
   - Watchdog: `Get-ScheduledTaskInfo -TaskName Ruppert-WS-Watchdog | Select LastRunTime`
   - Dashboard: check process start time
3. If any process needs restart:
   - **WS feed**: kill the old PID — watchdog will auto-restart it within 10 min (or trigger watchdog manually via `Start-ScheduledTask Ruppert-WS-Watchdog`)
   - **Watchdog**: `Stop-ScheduledTask` then `Start-ScheduledTask -TaskName Ruppert-WS-Watchdog`
   - **Dashboard**: `Stop-ScheduledTask` then `Start-ScheduledTask -TaskName RuppertDashboard`
4. Verify fresh heartbeat written within 2 min after restart

**If no code changes this session:** Skip this phase — output "Phase 7: No restarts needed."

**Note (from 2026-03-29b):** The watchdog can die if ws_feed.py is edited mid-run (import error propagates back). If both watchdog AND ws_feed are dead after an audit, restart the watchdog via Task Scheduler first — it will auto-restart ws_feed.

---

## Full workflow summary

```
Phase 1:  Audit all domains (parallel) — read CHANGELOG.md first
Phase 1b: DS reviews + amends DA findings
Phase 2:  Spec writing (parallel)
Phase 3:  Dev→QA batches (sequential, criticals-first domain order)
Phase 4:  Verification loop (re-audit → fix → repeat until clean)
Phase 5:  CEO housekeeping (stale files/code sweep, archive only)
Phase 6:  CEO writes audit log (CHANGELOG + domain files + archive temp files)
Phase 7:  System restart check (restart any processes whose code was changed)
```

---

## Tips from 2026-03-29 session

- CEO domain is medium-sized — don't skip it. `ruppert_cycle.py` is the orchestration spine and had 18 findings.
- Data Scientist spec agents take ~10 min (large domain). Spawn them first.
- QA is fast (~2 min per batch) — don't spawn QA before Dev finishes.
- Specs resolved-via-parent: always note in Dev task (saves QA confusion).
- config_audit.py (Researcher): always query actual Task Scheduler before populating REQUIRED_TASKS.
- After the audit loop, check for duplicate Task Scheduler registrations — these don't break anything but should be cleaned up.

## Tips from 2026-03-29b session

- **Always run Phase 7.** Code changes to ws_feed.py or watchdog will leave persistent processes running on old code. Discovered when WS feed died at 4:16pm and watchdog had also died — neither restarted because Task Scheduler only fires watchdog on boot. Fixed: Task Scheduler now retries watchdog on failure (10x, every 2 min).
- If watchdog log shows only one run from morning boot, it crashed. Check with `Get-Process python*` — if only dashboard is running, both are dead.
- Killing the old ws_feed PID is enough — the watchdog detects stale heartbeat within 10 min and auto-restarts.
