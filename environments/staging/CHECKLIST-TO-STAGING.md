# CHECKLIST-TO-STAGING.md
_Purpose: Gates that must be satisfied before DEMO is frozen into a versioned STAGING build_
_Created: 2026-03-29 | Owner: Strategist (technical sign-off) + David (promotion decision)_
_Status: Template — complete before each DEMO→STAGING promotion_

---

## ⚠️ PROMOTION IS DAVID'S DECISION
Strategist validates all gates. David authorizes the freeze. No automated promotion.

---

## The Builds Model

Every DEMO→STAGING promotion creates a new versioned build:

```
environments/staging/
  builds/
    2026-04-15/          ← first promotion from DEMO
      config.py          ← exact config snapshot (risk params, thresholds, caps)
      mode.json          ← {"mode": "staging"}
      build-manifest.json  ← git commit hash, trade stats, approver, date
    2026-05-01/          ← second promotion
      ...
    2026-05-20/          ← current/latest build
      ...
  CHECKLIST-TO-STAGING.md   ← this file
  CHECKLIST-STAGING-VALIDATION.md
```

**LIVE always points to exactly one staging build.** When LIVE is activated, `environments/live/config.py`
is a direct copy of `environments/staging/builds/YYYY-MM-DD/config.py`.

**Rollback = copy from the previous staging build.** Staging IS the version history for LIVE.

### What a Build Contains

A build is minimal but complete for rollback. It contains:

| File | Purpose | Required? |
|------|---------|-----------|
| `config.py` | Exact risk parameters active when this build ran | ✅ P0 |
| `mode.json` | Environment mode (`staging`) | ✅ P0 |
| `build-manifest.json` | Git commit hash, trade stats, approver sign-off | ✅ P0 |
| `secrets-ref.txt` | Which secrets directory was active (path only, no keys) | ✅ P1 |
| `pre_deploy_check_output.txt` | Captured output of pre_deploy_check at freeze time | ✅ P1 |

**The code itself is NOT copied into the build.** Code lives in git. The `build-manifest.json`
records the exact git commit hash so you can always reconstruct the exact code state.
A git tag `staging-YYYY-MM-DD` is created at freeze time.

### `build-manifest.json` Schema
```json
{
  "build_date": "2026-04-15",
  "git_commit": "abc1234",
  "git_tag": "staging-2026-04-15",
  "demo_window": {
    "start": "2026-04-01",
    "end": "2026-04-14",
    "total_trades": 247,
    "by_module": {"weather": 89, "crypto": 71, "geo": 45, "econ": 42},
    "win_rates": {"weather": 0.68, "crypto": 0.64, "geo": 0.62, "econ": 0.60},
    "brier_scores": {"weather": 0.19, "crypto": 0.21, "geo": 0.24, "econ": 0.22}
  },
  "approved_by": "David Wu",
  "approved_at": "2026-04-15T14:32:00-07:00",
  "notes": "First staging build. Weather + crypto fully validated. Geo/econ borderline — David accepted.",
  "activated_in_live": false,
  "live_activated_date": null
}
```

---

## How to Use This Checklist

1. Strategist runs through all gates and marks ✅ / ❌ / ⚠️
2. Strategist writes the Promotion Brief (template at bottom)
3. David reviews brief + any ❌ or ⚠️ items
4. David says "promote to staging" → Strategist creates build, tags git, writes manifest
5. New build directory is created: `environments/staging/builds/YYYY-MM-DD/`

---

## GATE 1 — Runtime Stability (Quantitative)

- [ ] **14+ calendar days of continuous clean DEMO operation**
  - No unhandled exceptions in `logs/activity_*.log` for the last 14 days
  - No `ERROR` or `CRITICAL` lines with unresolved root cause
  - Watchdog has not restarted the bot due to crash in last 14 days

- [ ] **200+ completed trades across all active modules**
  - Check `logs/trades/trades_*.jsonl` across the window
  - Minimum 30 trades per active module (weather, crypto, geo, econ) live for >7 days
  - Module with <30 trades = that module is NOT validated; document explicitly in manifest

- [ ] **Optimizer has run at least once per validated module**
  - Check `logs/proposals/` for optimizer output per module
  - Each module must have completed at least one optimizer cycle post-30-trade threshold
  - Optimizer must not have flagged any unresolved P0 issues

- [ ] **Settlement accuracy: ≥50 settled positions, Brier ≤0.25 per validated module**
  - Check `logs/scored_predictions.jsonl` — count settled predictions
  - Brier score per active module ≤0.25 (threshold defined in `config.py OPTIMIZER_BRIER_FLAG`)
  - Win rate per active module ≥60% (threshold defined in `config.py OPTIMIZER_LOW_WIN_RATE`)

- [ ] **No open circuit-breaker triggers in last 7 days**
  - Check `logs/activity_*.log` for `circuit_breaker` or `HALT` events
  - Any halt in the last 7 days must have documented root cause and resolution in manifest

---

## GATE 2 — Data Integrity (Quantitative)

- [ ] **WS feed uptime ≥95% over 7-day window**
  - Check `logs/ws_feed_heartbeat.json` — compute uptime from `last_heartbeat` timestamps
  - Gaps >5 minutes count against uptime; reconnect storms (>3/hour sustained) = ❌

- [ ] **Truth files reconciled (Data Scientist sign-off required)**
  - `logs/truth/state.json` updated within last 2 cycles
  - `logs/truth/pnl_cache.json` reconciles with `logs/trades/` ±$1.00
  - `logs/truth/deposits.json` balance matches Kalshi demo account ±$1.00

- [ ] **`data_health_check.py` passes clean**
  - Run: `python environments/demo/audit/data_health_check.py`
  - Zero CRITICAL items; P1 items have documented mitigations

- [ ] **No unknown log files in `workspace/logs/` root**
  - Any file written to workspace root `logs/` = env isolation breach
  - Must be zero before freeze

---

## GATE 3 — Codebase Cleanliness (Qualitative)

- [ ] **No open CRITICAL items in specs or agent memory**
  - Scan `environments/demo/specs/` — no P0 items with status = OPEN
  - Scan `environments/demo/memory/agents/` — no active agent memory noting unresolved P0 bugs
  - Any open P0 = automatic ❌, promotion blocked

- [ ] **`pre_deploy_check.py` passes (capture output for build artifact)**
  - Run: `python environments/demo/pre_deploy_check.py`
  - All checks GREEN or documented YELLOW with accepted risk
  - Save output to `environments/staging/builds/YYYY-MM-DD/pre_deploy_check_output.txt`

- [ ] **Full test suite passes**
  - Run: `cd environments/demo && python -m pytest tests/ -v`
  - Zero failures, zero errors; warnings reviewed and accepted

- [ ] **`smoke_test.py` passes**
  - Run: `python environments/demo/smoke_test.py`

---

## GATE 4 — Architecture Compliance (Qualitative)

- [ ] **Agents are fully environment-agnostic**
  - No literal `"DEMO"` or `"LIVE"` anywhere under `agents/ruppert/`
  - Run: `Select-String -Path "agents\ruppert\*" -Pattern '"DEMO"|"LIVE"' -Recurse`
  - Zero matches required

- [ ] **`strategy.py` constants are config-sourced, not inline**
  - No bare float/int risk thresholds hardcoded in `agents/ruppert/strategist/strategy.py`
  - All tunable values imported from env-scoped `config.py`

- [ ] **`position_monitor.py` uses `env_config.get_env_root()` — not hardcoded DEMO path**
  - `_DEMO_ENV_ROOT` or equivalent must not exist in any executed code path

- [ ] **Telegram notifications include `[DEMO]` prefix on all outbound messages**
  - Spot-check last 20 Telegram alerts — every alert starts with `[DEMO]`

---

## GATE 5 — David's Qualitative Sign-Off

- [ ] **David has reviewed the last 7-day P&L summary**
  - Data Scientist generates fresh report; David explicitly confirms he's reviewed it

- [ ] **No open watch-list items David hasn't seen**
  - All unresolved Telegram alerts from last 7 days acknowledged
  - All open optimizer recommendations reviewed

- [ ] **David confirms timing is right**
  - Ask: "Any market conditions that warrant waiting before freezing?"

---

## Promotion Actions (after David approves)

1. Create build directory: `environments/staging/builds/YYYY-MM-DD/`
2. Copy `environments/demo/config.py` → `environments/staging/builds/YYYY-MM-DD/config.py`
3. Write `environments/staging/builds/YYYY-MM-DD/mode.json` → `{"mode": "staging"}`
4. Write `build-manifest.json` with all fields (template above)
5. Save `pre_deploy_check_output.txt` into build directory
6. Git commit the staging build: `git add environments/staging/builds/YYYY-MM-DD/ && git commit -m "staging build YYYY-MM-DD"`
7. Git tag: `git tag staging-YYYY-MM-DD`
8. Git push: `git push && git push --tags`
9. Confirm to David: "Build YYYY-MM-DD created. Git tag: staging-YYYY-MM-DD. Proceed to staging validation."

---

## Promotion Brief Template

```
DEMO → STAGING PROMOTION BRIEF
Date: YYYY-MM-DD
Prepared by: Strategist

DEMO WINDOW: [start] → [end] ([N] days)
TRADES: [total] ([weather N], [crypto N], [geo N], [econ N])
WIN RATES: weather [%], crypto [%], geo [%], econ [%]
BRIER SCORES: weather [X], crypto [X], geo [X], econ [X]
OPTIMIZER: [ran / not run / flagged issues — list]
VALIDATED MODULES: [list modules with ≥30 trades]
UNVALIDATED MODULES: [list modules below threshold — will NOT go to LIVE]
OPEN ISSUES: [any ❌ or ⚠️ with mitigations or accepted risks]
GIT COMMIT: [hash]
RECOMMENDATION: [PROMOTE / HOLD — one sentence reason]
```

---

_Last updated: 2026-03-29_

---

## ℹ️ Org Chart Changes at Staging (informational — tackle when closer to go-live)

When STAGING is active and LIVE is being prepared, the agent team needs scope adjustments.
**Strategist recommendation (2026-03-29):** No new agents needed immediately. Two role extensions:

| Role | Current | Change needed |
|------|---------|---------------|
| **CEO** | Manages everything informally | Explicitly bounded to DEMO operations only |
| **Strategist** | Algorithm + edge | + Release Manager: owns all 3 checklists, promotion scorecard, go-live gate |
| **Data Scientist** | DEMO P&L + truth files | + Live Trading Monitor: LIVE daily brief, anomaly escalation directly to David (CEO bypassed for LIVE alerts) |

**Key principle:** LIVE anomalies skip CEO and go directly to Data Scientist → David. CEO is too slow in the loop for real-money issues.

**One role held in reserve:** Dedicated Live Trading Monitor agent if Data Scientist gets overloaded after ~30 days of LIVE. Don't create until needed.

**Action items (defer until staging is active):**
- [ ] Update CEO ROLE.md with DEMO-only scope boundary
- [ ] Update Strategist ROLE.md with Release Manager responsibilities
- [ ] Update Data Scientist ROLE.md with Live Trading Monitor responsibilities
- [ ] Rewrite PIPELINE.md (currently stale — still references old Architect/Optimizer org)
