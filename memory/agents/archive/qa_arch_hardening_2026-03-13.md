# QA Report — Architecture Hardening Build
**Reviewer:** SA-4 QA  
**Date:** 2026-03-13  
**Build:** Directory Rename + Client-Level DRY_RUN + LIVE Isolation + Dashboard Separation  
**Overall Verdict:** ❌ FAIL (1 CRITICAL issue)

---

## PASS 1 — TECHNICAL

### 1a. Directory Rename ✅ PASS
- `ruppert-tradingbot-demo\` EXISTS ✅
- `kalshi-bot\` does NOT exist ✅

---

### 1b. Task Scheduler — DEMO Tasks ✅ PASS WITH INFO

**INFO:** The QA spec listed expected task names (Ruppert_8am, 9am, 11am, 5pm) that do NOT exist. The actual 6 tasks are:
- `Ruppert_7am` → ruppert-tradingbot-demo\ruppert_cycle.py full ✅
- `Ruppert_12pm` → ruppert-tradingbot-demo\ruppert_cycle.py full ✅
- `Ruppert_3pm` → ruppert-tradingbot-demo\ruppert_cycle.py full ✅
- `Ruppert_10pm` → ruppert-tradingbot-demo\ruppert_cycle.py full ✅
- `Ruppert_7am_Report` → ruppert-tradingbot-demo\daily_report.py ✅
- `Ruppert_7pm_Report` → ruppert-tradingbot-demo\daily_report.py ✅

All 6 actual tasks point to `ruppert-tradingbot-demo\` — NOT `kalshi-bot`. All are ENABLED.

**INFO:** Task naming differs from spec expectation (schedule was built with 7am/12pm/3pm/10pm + 2 reports vs. the spec's 7/8/9/11am/3/5pm). Not a defect — schedule was implemented as designed. Team context should be updated to reflect actual schedule.

---

### 1c. kalshi_client.py — Client-Level DRY_RUN (DEMO) ✅ PASS

File: `ruppert-tradingbot-demo/kalshi_client.py`

- `is_live` property: SET from `self.environment == 'live'` ✅
- `_demo_block()` method: EXISTS, logs and returns safe stub `{"dry_run": True, ...}` ✅
- `place_order`: guarded with `if not self.is_live: return self._demo_block(...)` ✅
- `sell_position`: guarded ✅
- `cancel_order`: guarded ✅
- `amend_order`: guarded ✅
- Read-only methods (`get_balance`, `search_markets`, `get_market`, `get_positions`, `get_orders`): NOT guarded ✅ (correct — read-only is safe)

All 4 order-writing methods confirmed blocked in demo mode.

---

### 1d. LIVE Environment Isolation ✅ PASS

- `ruppert-tradingbot-live/` EXISTS as separate directory ✅
- `secrets/kalshi_config.json`: `"environment": "live"` ✅
- `logs/live_status.json`: `"active": false` ✅
- `mode.json`: `"mode": "live"` ✅
- `ruppert-tradingbot-live/kalshi_client.py`: Same DRY_RUN guard present. With `environment=live`, `is_live=True`, so guard does NOT block — correct behavior for live mode ✅
- `execute_exits.py`: NOT in `ruppert-tradingbot-live/` ✅
- `close_cpi.py`: NOT in `ruppert-tradingbot-live/` ✅

---

### 1e. run_live_dashboard.py — uvicorn ✅ PASS

File: `ruppert-tradingbot-live/run_live_dashboard.py`
- Uses `uvicorn.run("dashboard.api:app", host="0.0.0.0", port=8766, reload=False)` ✅
- No `app.run(...)` (Flask-style) ✅

---

## PASS 2 — OPERATIONAL

### 2a. DEMO Dashboard Header ✅ PASS WITH INFO

File: `ruppert-tradingbot-demo/dashboard/templates/index.html`
- `DEMO DASHBOARD` text in header div ✅
- Amber border `#f59e0b` ✅
- Mode toggle button/modal: REMOVED ✅

**INFO:** The string "toggle" appears in the file in three benign contexts:
1. A dead-code comment block: `// Mode toggle logic` (refers to removed UI)
2. `track.classList.toggle('live', isLive)` — CSS class toggle, not a button
3. `toggleWatch()` function — for the ticker watchlist feature, unrelated to mode

The comment line reads: `// Mode is config-driven (always DEMO on this dashboard). Toggle removed.`  
The mode toggle modal/button is confirmed removed. Dead comment can be cleaned up in a future pass.

---

### 2b. LIVE Dashboard Header + Status Light ✅ PASS

File: `ruppert-tradingbot-live/dashboard/templates/index.html`
- `LIVE DASHBOARD` text ✅
- Red border `#ef4444` ✅
- `status-dot` element exists ✅
- `status-text` element exists ✅
- JavaScript calls `/api/live-status` ✅
- Refreshes every 30 seconds ✅
- Status light is NOT interactive (no onclick) ✅

---

### 2c. LIVE Dashboard API ✅ PASS WITH INFO

File: `ruppert-tradingbot-live/dashboard/api.py`
- Port 8766: Confirmed in docstring and `run_live_dashboard.py` ✅
- `/api/live-status` endpoint: EXISTS, reads from `logs/live_status.json` ✅
- `/api/set-mode` endpoint: Does NOT exist ✅
- **INFO:** `/api/mode` POST exists but is a proper no-op — returns `{"mode": "live", "ok": True, "note": "Mode is config-driven. Toggle disabled."}`. Acceptable.
- **INFO:** In `/api/highconviction/execute`, `is_live = False` is hardcoded with a `# TODO` comment. This is a safety net for now, but Developer should wire this from config before go-live.

---

### 2d. Port Check ❌ CRITICAL FAIL

- Port 8765 (DEMO): LISTENING ✅ (demo dashboard running as expected)
- Port 8766 (LIVE): **LISTENING ❌ — LIVE DASHBOARD IS RUNNING**

```
TCP  0.0.0.0:8766  0.0.0.0:0  LISTENING  PID 9720
TCP  [::]:8766     [::]:0     LISTENING  PID 9720
```

PID 9720 = `python.exe` running the live dashboard.

**The LIVE dashboard should NOT be running during the DEMO phase.** While `live_status.json` has `active: false` (status light shows red/off), the API process is live on the network. With `kalshi_config.json` having `environment: live` and `is_live=True` in the client, any direct API call to the live dashboard endpoints could trigger real Kalshi API calls.

**Developer must identify and terminate PID 9720. Determine what started it (manual run, scheduled task, startup script) and prevent it from auto-starting.**

---

### 2e. Git Remotes ✅ PASS

- `ruppert-tradingbot-demo`: `https://github.com/eulahwu917/ruppert-tradingbot-demo.git` ✅
- `ruppert-tradingbot-live`: `https://github.com/eulahwu917/ruppert-tradingbot-live.git` ✅

---

### 2f. LIVE Task Scheduler Tasks ✅ PASS

All 6 `Ruppert_LIVE_*` tasks checked:
- `Ruppert_LIVE_7am`: NOT in scheduler ✅
- `Ruppert_LIVE_8am`: NOT in scheduler ✅
- `Ruppert_LIVE_9am`: NOT in scheduler ✅
- `Ruppert_LIVE_11am`: NOT in scheduler ✅
- `Ruppert_LIVE_3pm`: NOT in scheduler ✅
- `Ruppert_LIVE_5pm`: NOT in scheduler ✅

`setup_live_tasks.bat` has NOT been run. Correct — LIVE tasks should not be scheduled yet.

---

### 2g. PREFLIGHT.md ✅ PASS

File: `ruppert-tradingbot-live/PREFLIGHT.md` EXISTS
- Optimizer Review section: ✅ (includes module performance, edge thresholds, sizing, known weaknesses)
- QA Pass 1 (Technical) section: ✅
- QA Pass 2 (Operational) section: ✅
- 3-question go-live procedure: ✅ (Q1 "Are you sure?", Q2 "Are you 100% sure?", Q3 "Running setup_live_tasks.bat now, you sure?")
- Emergency Stop procedure: ✅ (6 schtasks /DISABLE commands + live_status.json reset)

---

### 2h. setup_live_tasks.bat ✅ PASS

- File EXISTS in `ruppert-tradingbot-live/` ✅
- LIVE tasks NOT in Task Scheduler (bat not run) ✅

---

## Issue Summary

| Severity | Check | Description |
|----------|-------|-------------|
| ❌ CRITICAL | 2d | Port 8766 is LISTENING — LIVE dashboard running (PID 9720). Must be stopped immediately. |
| ⚠️ WARNING | 2c | `/api/highconviction/execute` has `is_live = False` hardcoded with `# TODO`. Must be wired from config before go-live. |
| ℹ️ INFO | 1b | DEMO task names differ from spec expectation. Actual schedule: 7am/12pm/3pm/10pm + 2 reports. All correct paths. |
| ℹ️ INFO | 2a | Dead-code comment block `// Mode toggle logic` remains in DEMO HTML. Cosmetic — safe to clean up later. |
| ℹ️ INFO | 2c | `/api/mode` POST exists as no-op. Not `/api/set-mode`. Acceptable implementation. |
| ℹ️ INFO | docs | `memory/agents/team_context.md` still lists `kalshi-bot\` as the bot directory. Needs update. |

---

## Action Items for Developer

### CRITICAL (must fix before next QA pass):
1. **Stop PID 9720** — kill the live dashboard process: `Stop-Process -Id 9720 -Force`
2. **Identify what started it** — check if there's a startup script, scheduled task, or manual run that launched the live dashboard. Prevent auto-restart.
3. Confirm port 8766 is free after stopping.

### Pre-Go-Live (before flipping to live):
4. **Wire `is_live` from config** in `/api/highconviction/execute` (currently hardcoded `False`).

### Optional Cleanup:
5. Update `memory/agents/team_context.md` with correct bot directory (`ruppert-tradingbot-demo`) and actual task schedule.
6. Remove dead-code comment `// Mode toggle logic` block from DEMO dashboard HTML.

---

## Overall Verdict

**❌ FAIL**

One CRITICAL issue: LIVE dashboard is actively running (port 8766, PID 9720) during DEMO phase. All other technical checks pass. Build is architecturally sound — the DRY_RUN guard is correctly implemented in both environments, LIVE isolation is solid, and all safety rails are in place. Once PID 9720 is terminated and the cause identified, this build should be re-reviewed at the port check (2d) only — all other items are PASS.
