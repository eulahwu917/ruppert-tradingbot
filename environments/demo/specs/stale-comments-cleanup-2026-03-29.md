# Spec: Stale Comment Cleanup
**Author:** CEO  
**Date:** 2026-03-29  
**Priority:** P3 - Minor cleanup  
**Assigned to:** Dev

---

## Overview

CEO housekeeping sweep found 3 stale/misleading comments in source files. No logic changes needed — comment-only cleanup.

---

## Fix 1 — `ruppert_cycle.py` lines 1194–1197

**File:** `environments/demo/ruppert_cycle.py`

**Current (stale):**
```python
        # 🔬 Data Scientist: post-scan audit (non-fatal) ─────────────────
        # Note: 'smart' mode currently runs as check_mode (position check only).
        # TODO: implement smart money refresh + light synthesis when ready.
        # Until then, the data agent audit still runs (line below) as a lightweight signal.
```

**Replace with:**
```python
        # Data Scientist: post-scan audit (non-fatal)
        # Note: 'smart' mode currently runs as check_mode (position check only).
        # Smart money refresh not yet implemented — runs check_mode until then.
```

**Reason:** 
- "data agent" is an old role name — the team calls it Data Scientist now  
- The TODO has been open since 2026-03-28 with no imminent timeline — it's misleading to call it a TODO in running code  
- "the data agent audit still runs" is confusing given the rename

---

## Fix 2 — `agents/ruppert/trader/main.py` line 1031

**File:** `agents/ruppert/trader/main.py`

**Current (stale):**
```python
    # run_exit_scan() has a # TODO: live mode stub and is dead code - do not call here.
```

**Replace with:**
```python
    # run_exit_scan() is archived (see archive/run_exit_scan_archived.py). Do not call here.
```

**Reason:** The inner "# TODO: live mode stub" reference is confusing — the function now raises RuntimeError. The comment should just point to the archive.

---

## Fix 3 — `environments/demo/ruppert_cycle.py` line 93 (docstring)

**File:** `environments/demo/ruppert_cycle.py`

**Current:**
```python
    """Write traded_tickers + metadata to logs/state.json for cross-cycle persistence.
    Also logs a STATE_UPDATE event so Data Scientist can synthesize state.
    """
```

This one is borderline — "Data Scientist" as a role name in a comment is fine and accurate. **Skip this fix.** Not stale.

---

## QA Criteria

- No logic changes — comment-only edits  
- `smoke_test.py` still passes after edits  
- No new imports introduced  
