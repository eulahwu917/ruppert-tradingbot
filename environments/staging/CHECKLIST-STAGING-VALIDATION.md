# CHECKLIST-STAGING-VALIDATION.md
_Purpose: Surgical technical work done after DEMO→STAGING freeze, before LIVE promotion_
_Created: 2026-03-29 | Owner: Strategist (sign-off) + Dev/QA (execution)_
_Status: Template — complete for each new staging build before it becomes LIVE_

---

## Context

After a DEMO→STAGING promotion creates `environments/staging/builds/YYYY-MM-DD/`,
this checklist governs the technical hardening that happens before that build can go LIVE.

**The snapshot is locked.** No new features or tuning changes enter staging.
If a bug is found here, it either:
- Gets fixed in DEMO (triggering a new promotion cycle), OR
- Is accepted as a known risk with David's explicit sign-off

Reference the active build throughout: `environments/staging/builds/YYYY-MM-DD/`

---

## PHASE A — Config Lock (P0)

### A1 — Staging Config Derived from Build Snapshot

- [ ] **`environments/staging/builds/YYYY-MM-DD/config.py` exists and contains STAGING-conservative values**
  - This was created during the DEMO→STAGING promotion (see CHECKLIST-TO-STAGING.md)
  - Verify STAGING-tightened values vs DEMO baseline:

  | Parameter | DEMO | STAGING minimum | Notes |
  |-----------|------|-----------------|-------|
  | `WEATHER_DAILY_CAP_PCT` | 7% | 5% | |
  | `CRYPTO_DAILY_CAP_PCT` | 7% | 5% | |
  | `GEO_DAILY_CAP_PCT` | 4% | 3% | |
  | `ECON_DAILY_CAP_PCT` | 4% | 3% | |
  | `MAX_POSITION_PCT` | 1% | 0.75% | |
  | `LOSS_CIRCUIT_BREAKER_PCT` | 5% | 4% | |
  | `MIN_EDGE_THRESHOLD` | 12% | 14% | |
  | `CRYPTO_MIN_EDGE_THRESHOLD` | 12% | 14% | |
  | `CRYPTO_15M_MIN_EDGE` | 5% | 7% | |

  - Every tightened value must have a comment: `# STAGING-tightened from X%`
  - Strategist reviews and signs off on every value

- [ ] **`environments/staging/builds/YYYY-MM-DD/mode.json` = `{"mode": "staging"}`**
  - Confirm `DRY_RUN` behavior is documented:
    - If Kalshi provides a staging sandbox: use it (paper orders against staging market data)
    - If no Kalshi staging env: paper-mode against live market data (no orders placed)
    - Document decision in `build-manifest.json` field `"staging_mode_notes"`

### A2 — Live Config from This Build (when going LIVE)

- [ ] **`environments/live/config.py` will be a direct copy of `builds/YYYY-MM-DD/config.py` + LIVE tightening**
  - LIVE values tighter than STAGING (prepared here, activated in CHECKLIST-TO-LIVE.md):

  | Parameter | STAGING | LIVE minimum | Notes |
  |-----------|---------|--------------|-------|
  | `WEATHER_DAILY_CAP_PCT` | 5% | 4% | |
  | `CRYPTO_DAILY_CAP_PCT` | 5% | 4% | |
  | `GEO_DAILY_CAP_PCT` | 3% | 2% | |
  | `ECON_DAILY_CAP_PCT` | 3% | 2% | |
  | `MAX_POSITION_PCT` | 0.75% | 0.5% | Half of DEMO |
  | `LOSS_CIRCUIT_BREAKER_PCT` | 4% | 3% | |
  | `MIN_EDGE_THRESHOLD` | 14% | 16% | |
  | `CRYPTO_MIN_EDGE_THRESHOLD` | 14% | 16% | |

  - David must explicitly approve every LIVE risk parameter value
  - Draft `environments/live/config.py` here; David approves; activation happens at LIVE go-time

---

## PHASE B — Environment Agnosticism Audit (P0)

- [ ] **Grep: no `"DEMO"` or `"LIVE"` literals in `agents/ruppert/`**
  ```powershell
  Select-String -Path "agents\ruppert\*" -Pattern '"DEMO"|"LIVE"' -Recurse
  ```
  Zero matches required. Any match = P0 bug, block promotion to LIVE.

- [ ] **Grep: no hardcoded `environments/demo/` or `environments/live/` paths in agents**
  ```powershell
  Select-String -Path "agents\ruppert\*" -Pattern 'environments[\\/](demo|live|staging)' -Recurse
  ```
  Zero matches required.

- [ ] **`env_config.py` resolves all three environments correctly**
  - `RUPPERT_ENV=demo` → `environments/demo/`
  - `RUPPERT_ENV=staging` → `environments/staging/builds/YYYY-MM-DD/` (active build)
  - `RUPPERT_ENV=live` → `environments/live/`
  - The "active build" pointer must be a single source of truth — either a symlink
    `environments/staging/current → builds/YYYY-MM-DD/` OR a plain text file
    `environments/staging/ACTIVE_BUILD` containing `"2026-04-15"`
  - Recommend: `ACTIVE_BUILD` plain text file (no symlink complexity on Windows)

- [ ] **`position_monitor.py` hardcoded DEMO path is fixed**
  - `_DEMO_ENV_ROOT` or equivalent must not exist in any executed code path
  - Replaced with `env_config.get_env_root()` call
  - Dev spec → Dev → QA → committed before this validation begins

---

## PHASE C — Config Sourcing Audit (P0)

- [ ] **All `strategy.py` risk constants import from env-scoped `config` — not inline**
  - Audit `agents/ruppert/strategist/strategy.py`:
    - Kelly tier table
    - `MIN_EDGE` per module
    - `MIN_CONFIDENCE` per module
    - `DAILY_CAP_RATIO`
    - `MIN_HOURS_ENTRY` / `MIN_HOURS_ADD`
    - Market impact ceiling
  - Any inline hardcode = P0, requires Dev spec before proceeding

- [ ] **`trader/main.py` position sizing reads from env-scoped `config`**
  - `MAX_POSITION_SIZE`, `MAX_DAILY_EXPOSURE`, `MAX_POSITION_PCT` sourced from config
  - No silent hardcoded fallback defaults

- [ ] **`ruppert_cycle.py` module caps read from env-scoped `config`**
  - `ECON_MAX_DAILY_EXPOSURE`, `GEO_MAX_DAILY_EXPOSURE` etc. sourced from config
  - Verify import chain: ruppert_cycle → config → env-scoped values

---

## PHASE D — Telegram Notification Prefix (P0)

- [ ] **All Telegram alerts include environment prefix**
  - `[DEMO]` → demo environment
  - `[STAGING]` → staging environment
  - `[LIVE]` → live environment
  - Audit locations:
    - `agents/ruppert/ceo/brief_generator.py` — daily report prefix
    - `agents/ruppert/trader/main.py` — trade execution alerts
    - Any `ruppert_cycle.py` direct Telegram calls
    - Data Scientist P&L and health alerts
  - No alert without a prefix is acceptable once STAGING + LIVE run in parallel

- [ ] **Test: run one staging cycle and verify `[STAGING]` prefix on all Telegram messages**
  - `$env:RUPPERT_ENV="staging"; python agents/ruppert/ruppert_cycle.py --dry-run`
  - Every message received must start with `[STAGING]`

---

## PHASE E — Data Isolation Verification (P1)

- [ ] **Staging data root is independent of DEMO**
  - `environments/staging/builds/YYYY-MM-DD/logs/` exists and initialized fresh
  - No symlinks or shared files between demo and staging log directories
  - `environments/staging/builds/YYYY-MM-DD/logs/truth/` initialized empty

- [ ] **Active build pointer is set correctly**
  - Create or update `environments/staging/ACTIVE_BUILD` with the build date: `2026-04-15`
  - `env_config.py` reads this file to resolve staging data root
  - Verify: `RUPPERT_ENV=staging python -c "from agents.ruppert import env_config; print(env_config.get_env_root())"`

- [ ] **Staging secrets confirmed**
  - Document which Kalshi credentials staging uses (separate from LIVE)
  - `environments/staging/secrets/` or `workspace/secrets/` — document resolution chain
  - Confirm staging does NOT use LIVE private key unless explicitly decided and documented

- [ ] **Parallel run isolation test (brief)**
  - Start DEMO cycle and STAGING cycle simultaneously
  - Verify logs appear in correct roots only
  - Verify Telegram prefixes are correct for each

---

## PHASE F — Old LIVE Codebase Archival (P1)

_(One-time task — skip if already done in a prior build cycle)_

- [ ] **Archive `environments/live/` pre-Phase-6 standalone codebase**
  - Archive to: `environments/live/archive/pre-phase6-live-YYYY-MM-DD/`
  - Files to archive: `main.py`, `trader.py`, `position_monitor.py`, `kalshi_client.py`,
    `crypto_client.py`, `economics_client.py`, `economics_scanner.py`, `fed_client.py`,
    `geo_client.py`, `geo_edge_detector.py`, `geopolitical_scanner.py`, `ghcnd_client.py`,
    `logger.py`, `noaa_client.py`, `openmeteo_client.py`, `edge_detector.py`,
    `daily_progress_report.py`, `fetch_smart_money.py`
  - After archive: LIVE env contains only `config.py`, `mode.json`, `secrets/`, `logs/`, `config/`, `archive/`
  - Add `environments/live/README.md`: "LIVE runs `agents/ruppert/ruppert_cycle.py`
    with `RUPPERT_ENV=live`. This directory contains config, secrets, and logs only."

---

## PHASE G — Task Scheduler Definitions (P1)

_(Prepared here, activated in CHECKLIST-TO-LIVE.md)_

- [ ] **Draft STAGING task XML set** (for staging dry-run testing)
  - All DEMO tasks cloned with `RUPPERT_ENV=staging`
  - Tasks: full cycle, crypto_only, weather_only, econ_prescan, settlement checker,
    WS feed, daily report, health check
  - Store in `environments/staging/builds/YYYY-MM-DD/task-scheduler/`
  - NOT activated until David approves staging as a live parallel process

- [ ] **Draft LIVE task XML set** (stored, not activated)
  - All tasks with `RUPPERT_ENV=live`
  - Separate WS feed process with independent heartbeat + reconnect
  - Store in `environments/live/task-scheduler/`
  - Activation handled in CHECKLIST-TO-LIVE.md under "Activation Steps"

---

## PHASE H — Kill Switch & Rollback (P1)

- [ ] **Software kill switch implemented in `ruppert_cycle.py`**
  - Reading `mode.json` at startup; if `{"mode": "halted"}` → exit gracefully with `[LIVE] HALTED` Telegram alert
  - Test in STAGING: set `environments/staging/builds/YYYY-MM-DD/mode.json` → `{"mode": "halted"}`
  - Confirm cycle exits cleanly and sends Telegram notification

- [ ] **Rollback procedure documented for this build**
  - "Rollback LIVE to previous staging build" means:
    1. Copy `environments/staging/builds/PREV-DATE/config.py` → `environments/live/config.py`
    2. Restart LIVE Task Scheduler tasks (or they auto-restart on next schedule)
    3. Confirm `[LIVE]` alerts resume with correct config
  - Identify which build is the rollback target: `[previous build date]`
  - Document in `build-manifest.json` field `"rollback_target"`

---

## PHASE I — Smoke Tests (P1)

- [ ] **Full test suite passes with staging config loaded**
  - Run: `$env:RUPPERT_ENV="staging"; python -m pytest environments/demo/tests/ -v`
  - Zero failures

- [ ] **Single dry-run cycle completes without errors**
  - `$env:RUPPERT_ENV="staging"; python agents/ruppert/ruppert_cycle.py --dry-run`
  - No exceptions; all module outputs appear in staging data root
  - Telegram receives `[STAGING]` prefixed messages

- [ ] **`pre_deploy_check.py` passes against staging config**
  - `$env:RUPPERT_ENV="staging"; python environments/demo/pre_deploy_check.py`
  - All GREEN or documented YELLOW

---

## Sign-Off Before Handing to CHECKLIST-TO-LIVE.md

| Role | Required sign-off | Scope |
|------|-------------------|-------|
| Strategist | ✅ All P0/P1 items | Algorithm + config isolation |
| Data Scientist | ✅ Phases D + E | Data isolation + Telegram prefixes |
| CEO | ✅ Phases F + G + H | Ops, archival, task scheduler, kill switch |
| David | ✅ Phase A LIVE config values | Risk parameter approval for LIVE |

When all items above are checked, the build is ready for CHECKLIST-TO-LIVE.md.

---

_Last updated: 2026-03-29_
