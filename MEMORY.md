# MEMORY.md — Ruppert Long-Term Memory
_Main session only. Never load in group chats or shared contexts._

## Behavioral Note (2026-04-02)
David explicitly asked: be honest, push back when you disagree. Don't just agree to agree. This applies to technical decisions, sequencing, priorities — everything.

---

## 2026-04-04 — Full Audit Pipeline Complete (12:00-16:40 PDT)

### Audit pipeline ran, System Map at 98%+ confidence

**Phases 0, 1, 2 all complete. Phase 3 pending shadow trades.**

Phase 0 (data): 42 duplicate buy records removed from trades_2026-04-03.jsonl. Capital verified $10,347.42.
Phase 1 (code): Batch A (date.today survivors in 3 active files) + Batch B (capital error handling in 3 files) + 1 regression fix. All committed: dd6540d, d9e3a89.
Phase 2 (System Map): 291+ claims enumerated, ~113 adjudicated. 12 corrections applied. System Map v3.6 (5042e11). Docstrings fixed e67dfd8.

**Key System Map corrections (ground truth from XML/code):**
- settlement_checker: every 30 min 24/7 (not 2x daily)
- post_trade_monitor: every 15 min 6AM-11PM (not 30 min)
- _PROTECTED_ACTIONS: 6 members (not 3)
- pnl_cache.json: never written by synthesizer
- ISSUE-A02: partially resolved in prediction_scorer.py
- CRYPTO_15M_SERIES: ws_feed.py still has local copy (P2 open)

**Open P2 items (non-blocking):**
- ws_feed.py CRYPTO_15M_SERIES import from utils.py
- crypto_band_daily.py + crypto_threshold_daily.py: remaining date.today() (disabled modules)

**System state: HALTED, code clean, System Map fully adjudicated, Phase 3 pending shadow trades**
- Next: David confirms → restart WS feed + watchdog (crypto 15m only)
- Daily modules: OFF until shadow WR >45% / 50+ trades + R9 + R1 vol gate
- System Map: v3.8 (0cfcd82) — all 291 claims adjudicated, 23 corrections applied
- Latent bug to fix before daily module re-enable: crypto_threshold_daily.py S2 passes BTCUSDT (Binance format) to OKX endpoint — likely causes silent 0.0 funding data on S2 signal

---

## 2026-04-04 — Batches 2-5 Complete (10:00-12:00 PDT)

### All 4 batches complete — trading ready to restart
Full pipeline (domain expert specs → adversarial review → revise → Dev → QA → commit) run for every batch.

**Batch 2** (`538b25d`) — PDT date fixes + dead code
- circuit_breaker.py, crypto_15m.py, settlement_checker.py, position_tracker.py, api.py
- 5 files, 7 insertions / 13 deletions

**Batch 3** (`bbab631`) — NO-side price, dry_run tag, exposure error handling, CB locking, daily stop gate
- 11 files, 100 insertions / 46 deletions
- Notable: B3-DS-3 required full spec rewrite — 11 call sites across 7 files, capital.py now raises instead of returning 0.0

**Batch 4** (`24682b6`) — WS TZ, window guard retry, persistent mode cleanup, KXSOL15M, R9 macro filter
- 5 files, 193 insertions / 44 deletions
- Notable: B4-TRD-4 found run_persistent_ws_mode() unconditionally raises — deleted entirely
- R9 implemented properly: 40-entry 2026 FOMC/CPI/NFP calendar in utils.py
- B4-STR-2 diagnosis corrected by Strategist: loss_today key was already correct, $0 display is a separate data issue

**Batch 5** (`286268c`) — Settlement naive datetime, P&L divergence, date.today() sweep (22 sites), CRYPTO_15M_SERIES
- 6 files, all pushed to GitHub
- Critical find (adversarial): load_traded_tickers() in utils.py was dedup-failing at UTC midnight — fixed
- CRYPTO_15M_SERIES consolidated to single canonical definition in utils.py

### System state after batches 2-5: READY TO RESTART TRADING
- Batches 1-5 all complete and pushed ✅
- Next: re-enable WS feed + watchdog (crypto 15m only)
- Daily modules: REMAIN OFF until Strategist shadow WR > 45% over 50+ trades + R9 + R1 vol gate

### Key architectural finding (Batch 3, B3-STR-2)
- Strategist confirmed $0 CB loss display is NOT a key mismatch bug — strategy.py already translates net_loss_today → loss_today
- Root cause is likely missing pnl fields on trade log records or wrong file path — diagnostic log added in check_global_net_loss()

### Adversarial catches across all batches (notable)
- B2-DS-3: wrong line range would have caused dashboard import SyntaxError
- B3-DS-3: spec named wrong function (get_available_capital vs get_buying_power); 11 call sites missed
- B4-TRD-4: fallback to polling path was permanently retired code (unconditional RuntimeError)
- B4-STR-1: NFP May 8 adversarial flag was itself wrong — BLS confirmed May 8 correct
- B5-DS-3: load_traded_tickers() dedup failure missed in initial sweep — adversarial caught it

---

## 2026-04-04 — Post-Cleanup P1/P2 Fix Sprints + Trading Restart

### All 5 post-cleanup sprints complete (00:00-01:00 PDT)
- **Sprint 1** ✅ P1 Exit Safety — 08931ae
- **Sprint 2** ✅ P2 CB + Daily Guards — 3339846
- **Sprint 3** ✅ P2 Runtime Correctness — 7a2dc76
- **Sprint 4** ✅ P2 Display + Reporting — 2962743
- **Sprint 5** ✅ P2 Optimizer/Tests/Cleanup — 80b7d02 + d2a3134
- System Map updated to v3.1
- All commits pushed to GitHub

### System state: READY TO RESTART TRADING
- P0 bug free ✅
- All P1 and P2 fixes complete ✅
- Dead modules stripped (weather/geo/econ/fed/sports) ✅
- Codebase clean — no import crashes
- Next action: re-enable WS feed + watchdog (crypto 15m only)
- Daily modules (band/threshold): REMAIN OFF until Strategist shadow WR > 45% over 50+ trades

### Fix pipeline (David approved — permanent)
1. DS/Strategist/Trader specs → 2. Adversarial review → 3. Revise → 4. Dev builds → 5. QA → 6. Commit → 7. System Map + MEMORY.md + daily log + changelog

### Batch 1 adversarial review complete (2026-04-04)
- **B1-1 (watchdog double-spawn):** PASS — skip dead `import signal`, call site is lines 117-120 not 118-120 (cosmetic)
- **B1-2 (last-write-wins):** PASS for DEMO — flagged that `run_monitor()` will process multi-buy legs independently (safe DEMO, needs dedup for LIVE)
- **B1-3 (phantom settlement):** PASS — no corrections, ship as spec'd
- Full review: memory/batch1-adversarial-2026-04-04.md

### Key adversarial catches tonight:
- Sprint 1: release_exit_lock import was missing — would have crashed on first exit
- Sprint 2: third wrong-N site in post_trade_monitor missed by spec
- Sprint 4: actions_taken auto-exit proposal was scope creep + double-exit risk → minimal path taken
- Sprint 5: wrong constant name (CB_DAILY_LOSS_LIMIT_PCT → LOSS_CIRCUIT_BREAKER_PCT)
- Sprint 5: CME config had plaintext API password — flagged David to rotate

### Batch 1 fixes (2026-04-04) — commit 6b09ebe
- Watchdog double-spawn (ISSUE-I01): kill_existing_ws_feed() ported to active watchdog — RESOLVED
- Post_trade_monitor multi-buy overwrite: FIFO list accumulation — RESOLVED
- Phantom settlement inference: status gate ported from settlement_checker — RESOLVED
- Trading still halted — docs updates running before restart

### Adversarial framework (David approved, 2026-04-04)
- ALL agent recommendations go through adversarial review before reaching David
- Strategist, DS, Trader — all go through the gauntlet
- No exceptions

### Daily module re-enable checklist (updated 2026-04-04)
1. Shadow WR > 45% over 50+ clean trades
2. R9 macro filter (FOMC/CPI/NFP, 2h pre / 1h post, entries only)
3. R1-equivalent vol gate (catches tariffs + unscheduled events)
4. All P1 bugs fixed

### Overnight audit findings (2026-04-04)
- **6 P1 bugs** found across double-pass audit (7 agents + combined pass + adversarial + synthesis)
- **Most critical:** date.today() at 50+ sites silently disables CB during UTC/PDT gap; watchdog double-spawn fix in wrong file; R9 macro filter dead code
- **System is DEMO-safe, NOT LIVE-ready**
- **System Map v3.2** — 22 corrections applied, new DEMO vs LIVE section added
- **41-item DEMO→LIVE checklist** — memory/overnight-final-report-2026-04-04.md Section 5
- **Full report for David:** memory/overnight-final-report-2026-04-04.md

### CME API key rotation (David's action)
- `secrets/cme_config.json` deleted but contained `"api_password": "tnqdnYn#g#r9e3Ar$n*Rq7Q6"`
- David to deactivate this key at CME Group when convenient

### P3 backlog (deferred — no sprint needed)
- 13 items, see memory/adversarial-review-findings-2026-04-03.md
- Review after 30+ trades per domain when Optimizer runs
- Rate limiter (Kalshi): deferred to pre-LIVE checklist

---

## Major Session: 2026-04-02 Evening → 2026-04-03 Morning

### System Map Built (v1.1)
- **Location:** `agents/ruppert/docs/SYSTEM_MAP.md` (committed `4378c11`)
- Built from 6 research agents + 10 independent audit passes (avg 8.1/10 confidence)
- **Obsidian copy:** `2026-04-03 Ruppert System Map v1.1.md`
- This is the definitive reference for how the system works — always read before making architectural decisions

### Exhaustive Bug Hunt Complete
- **118 unique issues** found across entire codebase
- Consolidated: `memory/agents/master-issues-CONSOLIDATED-2026-04-02.md`
- Prioritized: `memory/agents/master-issues-PRIORITIZED-2026-04-02.md`
- **Obsidian copies:** `2026-04-03 Ruppert Bug Report - Consolidated 118 Issues.md` and `2026-04-03 Ruppert Bug Report - Prioritized P0-P4.md`

### Fix Plan — 5 Sprints Approved by David
- **Full plan:** `memory/2026-04-03-fix-plan.md`
- **Obsidian copy:** `2026-04-03 Ruppert Fix Plan - 5 Sprints.md`
- **Changelog:** `memory/agents/fix-changelog.md` (update after every commit with issue ID)

**Sprint order:**
1. ✅ COMPLETE — 15m feed stability + duplicate order prevention (9 issues + DS-NEW-001)
2. ✅ COMPLETE — Capital and position state accuracy (8 issues + ISSUE-099)
3. ✅ COMPLETE — Settlement and double-exit prevention (6 issues)
4. ✅ COMPLETE — 15m signal correctness (4 issues)
5. ✅ COMPLETE — Circuit breaker coverage + timezone + NO-side P&L fix (5 issues) — commits d0f4436, b376074

**Rules:**
- Every fix gets a plain English spec reviewed by David before Dev touches code
- Commit messages must include issue ID: `fix: ISSUE-XXX description`
- After every sprint, log changes in fix-changelog.md
- QA updates SYSTEM_MAP.md after each sprint

### Sprint 1 — COMPLETE (2026-04-03 morning)
- **9 issues fixed + DS-NEW-001 patch** across 4 commits: `ceba350`, `664d81e`, `2d26cb8`, `4a92830`
- All issues marked ✅ in `memory/agents/master-issues-PRIORITIZED-2026-04-02.md`
- Full changelog: `memory/agents/fix-changelog.md`
- **Process change (David):** DA is data-fetching only. All spec reviews → DS going forward.
- **Log atomicity (ISSUE-014):** logger.py has no file locking — acceptable for DEMO, must fix before LIVE
- **Pipeline violations noted:** Dev committed without waiting for DS sign-off (Batch 2, DS-NEW-001) — process to be reinforced

### All P1 Sprints COMPLETE (2026-04-03)
- **Sprint P1-1** ✅ Signal Integrity (8 issues): ISSUE-096, 032, 129, 114, 069, 116, 104, 105 — b171271, c03e5b1, a441a6d
- **Sprint P1-2** ✅ Settlement + Capital Accuracy (5 issues): ISSUE-026, 027, 110, 030, 102 — d3584bf, 641e2d3
- **Sprint P1-3** ✅ Analytics + Calibration (6 issues): ISSUE-005, 041, 004, 101, 103, 046 — 2e870f6, 1ebee0a, 9a1d78e
- **Sprint P1-4** ✅ Dashboard Fixes (7 issues): ISSUE-018, 019, 063, 064, 065, 066, 072 — d02db9f
- **Sprint P1-5** ✅ Exit Records + Monitoring (8 issues + CLEANUP): ISSUE-108, 062, 121, 098, 074, 079, 045, 023 — 8a32658
- **Sprint P1-6** ✅ Daily Module Pre-Re-Enable (5 issues): ISSUE-016, 017, 057, 089, 053 — d161a89

**Pipeline rules (locked in):**
- Adversarial reviewer is always a SEPARATE agent from the domain expert who wrote specs — enforced from P1-6 onward
- System Map audit deferred until ALL P1-P3 sprints complete (currently at v1.4 as of Sprint 5 P0)
- Daily modules stay OFF until Strategist shadow WR > 45% over 50+ trades

### P2+P3 Sprints COMPLETE (2026-04-03 evening)
- **P2+P3-1** ✅ Config, Risk + Audit Tools — ISSUE-036, 037, 038, 100, 119, 090 — ae558f1
- **P2+P3-2** ✅ Logger, WS Feed + Code Hygiene — ISSUE-109, 124, 125, 122, 115, 128 — b19e548
- ISSUE-071 deferred (no CI pipeline exists; import pattern works fine)
- Live env archived to `environments/archive/live/` — will rebuild from scratch
- Autoresearch archived — will be replaced with new backtest engine
- System Map v2.1: live env + autoresearch removed
- Remaining open: P3 disabled-module issues (weather/econ/geo/fed) — skip until modules re-enabled
- **Next session:** Strip inactive modules (weather/econ/geo/fed) from demo + restart trading

**Notable P1 findings:**
- ISSUE-023 confirmed already resolved in Sprint 3 (log_exit alias was public wrapper all along)
- ISSUE-017 root cause was threshold module only — band module was never broken (indirect price encoding)
- crypto_band_daily.py was missing `logging` import entirely despite using logger.warning (latent NameError fixed in P1-6)
- Dev subagent timed out repeatedly during P1-6; Ruppert implemented directly from reviewed specs

### P0 Mini-Sprint — COMPLETE (2026-04-03)
5 additional P0 issues found during P1 domain reviews and fixed immediately:
- ISSUE-034: position_monitor WS_ENABLED crash — 07d3eba
- ISSUE-117: vol_ratio=0 fires full Kelly — 07d3eba
- ISSUE-007: compute_closed_pnl_from_logs silent $0 — c69dee2
- ISSUE-006: NO-side Brier inverted — 7fb4d19
- ISSUE-040: optimizer domain name mismatch — 058589b
- Adversarial reviewer introduced to pipeline — catches spec bugs before Dev builds
- ISSUE-104 closed as invalid (Python short-circuit protects it, not a real bug)

### All P0 Sprints Complete (2026-04-03)
- All 5 sprints done. 29 P0 issues fixed across 10+ commits.
- Trading remains halted pending System Map update + P1 scoping.
- **Next:** System Map update (Trader + DS authors, QA verifies), then P1 domain reviews.

### Sprint 5 — COMPLETE (2026-04-03)
- **5 issues fixed** — commits d0f4436, b376074
- ISSUE-076: CB file lock (portalocker) on all read-modify-write ops
- ISSUE-047: Per-asset CB trip logging confirmed + added
- ISSUE-044: _today_pdt() helper in ws_feed.py + position_tracker.py
- ISSUE-043: EXIT_GAIN_PCT raises ImportError if missing (no silent 0.70 fallback)
- ISSUE-042: NO-side flip removed from add_position(); Design D stops gated to YES only; side=key[1] in check_exits()
- ISSUE-042 Part B: DS inserted 125 exit_correction records; capital corrected
- Post-correction capital (clean, after dupe removal): **$10,347.42**
- Module P&L (Apr 2-3): 15m directional +$13,475 total; daily band/threshold -$13,128 total — nearly flat overall
- Daily modules (esp. crypto_threshold_daily_btc at 3.4% WR) are bleeding. Needs P1 review.

### Known Active Issues (as of 2026-04-03 — post all P0 sprints)
- All P0 issues resolved ✅
- Trading halted (WS feed killed 12:06 PDT Apr 3 — was running through halt)
- Daily modules severely underperforming — assess in P1

### David's Strategic Decisions (authoritative, 2026-04-03)
- **Priority order:** crypto_dir_15m first → crypto daily → then live
- **System Map naming:** "System Map" (not Data Dictionary, not Code Map)
- **Fix process:** Spec in plain English → David reviews → Dev implements → QA verifies
- **Going live requires:** P0 + P1 + P2 all clean
- **Daily modules:** Left running despite tariff volatility losses (David's call, 2026-04-03)

### Trading Halted (2026-04-03 08:56 PDT)
- All trading halted by David while Sprint fixes are in progress
- WS feed killed, all Task Scheduler tasks disabled
- Tasks to re-enable when ready: Ruppert-WS-Watchdog, Ruppert-WS-Persistent, Ruppert-Crypto-930AM, Ruppert-MidnightRestart, RuppertDashboard
- Do NOT re-enable until Sprint 1 is complete and QA passes

### Dashboard Fix (2026-04-02)
- Module P&L breakdown fixed — was showing ~$710 phantom losses (commit `ed34247`)
- Uses canonical `compute_closed_pnl_from_logs()` path now

---

## Access Restrictions

- **Do NOT touch any other agent's documents.** Only allowed to read/write:
  - Own agent files: `C:\Users\David Wu\.openclaw\agents\main\`
  - OpenClaw config: `C:\Users\David Wu\.openclaw\openclaw.json`
  - Workspace: `C:\Users\David Wu\.openclaw\workspace\`
- If a second agent is ever added (agent 2 or any other), their files are strictly off-limits.
- This rule applies to Ruppert (main) and all sub-agents.

---

## Obsidian Integration
- **Vault path**: `C:\Users\David Wu\Obsidian Vault\5_AI Knowledge\Ruppert-Agent\`
- **Write**: final, polished markdown notes only — no raw dumps, no logs, no intermediate work
- **Filenames**: descriptive, date-prefixed, e.g. `2026-03-23 Trading Bot Research Summary.md`
- **Sync**: Obsidian Sync handles distribution to David's other devices automatically
- **Rule**: only write things David would actually want to read

## Opus Evaluation (2026-03-26) — Key Findings

### What's Working (DO NOT CHANGE)
- Quarter-Kelly sizing (25%) — industry validated
- 95c rule + 70% gain exit — PRIMARY alpha source (100% of wins used these)
- Multi-model ensemble (ECMWF 40% + GEFS 40% + ICON 20%)
- Weather direction filter: originally NO-only, **retired 2026-03-28** — both YES and NO now allowed based on edge sign
- Market impact ceiling in strategy.py
- Demo/Live isolation architecture
- Developer → QA → CEO pipeline

### Critical Fixes — ALL RESOLVED (2026-03-26)
- ✅ Miami NWS grid fixed: `MFL/106,51`
- ✅ Crypto path wired through strategy.py
- ✅ ~117 patch files cleaned (DEMO + LIVE)
- ✅ scipy confirmed wired correctly
- ✅ Smart money wallets — fully wired (see Batch 2 below)

### QA Data Audit Findings (2026-03-26)
- **Root cause of -$341 loss (Mar 13):** Direction filter not enforced — 28 YES weather trades placed despite WEATHER_DIRECTION_FILTER='NO'. FIXED.
- Daily exposure cap not enforced — FIXED (per-cycle counter in main.py)
- Same-day time gate not enforced — FIXED (ticker-based, config-driven, 2pm cutoff)
- Log schema inconsistencies — FIXED (UUID trade IDs, standardized fields)
- P&L rounding $1.96 gap — FIXED (single loop computation)
- 12-day task scheduler gap — FIXED (4 new tasks created, 6 old deleted)
- Real bot P&L without Mar 13 bug: ~+$81 (consistent with Opus +$84.52 figure)

### David's Strategic Decisions (authoritative)
- No rush to LIVE — optimize in DEMO first, target $1,000-$2,000 capital
- Full automation: ALL manual trades removed, gaming scout removed, geo made auto
- LIVE is EXCLUSIVELY David's decision — scorecard required, David says "go live"
- Tiered model routing: CEO = Sonnet; Architect = Opus; Optimizer = Opus; Researcher = Haiku; Developer = Claude Code (Sonnet); QA = Claude Code (Sonnet, separate session)
- Org: CEO directs Dev/QA/Researcher. Architect + Optimizer are peers to CEO. CEO+Architect disagree → David. CEO+Optimizer disagree → David. LIVE always David's call.
- CEO does NOT touch code or algorithm parameters — Dev and Optimizer own those respectively
- PIPELINE.md in repo documents all roles, pipelines, and escalation rules (committed 2026-03-26)
- Daily progress reports at 8pm PDT via Telegram (CEO sends)

### Bot Performance (DEMO, March 10-12)
- Bot trades: 9W / 1L (~90% win rate)
- Manual trades: 0W / 3L (0% win rate) — ALL manual paths being removed
- Net: ~+$84.52

### 6-Phase Implementation Plan — ALL COMPLETE (2026-03-26)
- ✅ Phase 1: Cleanup — gaming scout removed, 117 patch files trashed, Miami NWS fixed, manual trades removed, crypto wired through strategy.py
- ✅ Phase 2: Tiered model routing — documented in team_context.md
- ✅ Phase 3: Backtest infrastructure — run_backtest.py, autoresearch.py, program.md built. Dataset only 22 trades — needs expansion before autoresearch can run.
- ✅ Phase 4: Geo auto-trading — GDELT + Haiku/Sonnet pipeline. GEO_AUTO_TRADE=True in DEMO.
- ✅ Phase 5: CPI/Economics full automation + Fed inline sizing fixed + daily_progress_report.py
- 🔒 Phase 6: LIVE — on-demand scorecard, David decides

### Evening Session 2 (2026-03-26 ~7pm–8pm) — Opus Review + Full Sweep

**Opus codebase review findings (P0/P1/P2/P3) — ALL RESOLVED**
- ✅ P0: Crypto crash (`CRYPTO_MAX_POSITION_SIZE` ref to commented-out constant) — fixed
- ✅ P0: Crypto + Fed bypassing strategy.py entirely — both now route through should_enter()
- ✅ P1: Crypto confidence was edge proxy — now real composite (edge 50% + spread 30% + time 20%)
- ✅ P2: Optimizer thresholds hardcoded → moved to config.py as OPTIMIZER_* constants
- ✅ P2: config.py legacy dead comments cleaned
- ✅ P3: Crypto + Fed extracted to main.py as run_crypto_scan() / run_fed_scan()
- ✅ P3: All 3 modules uniform — ruppert_cycle.py delegates to main.py (458 lines, was 765)

**Dead code removed**
- risk.py (v1 legacy Kelly), trash/ folder (83 files), 6 dead root scripts
- norm_cdf/band_prob orphaned from ruppert_cycle.py
- qa scripts: import guards added

**Note on Opus hallucination**: Opus reported bot/risk.py as a crash risk — it exists at root level risk.py but was never called for active modules. Now trashed.

**Git**: committed + pushed `9c97f73` (110 files changed)

### Evening Session (2026-03-26) — Capital Architecture Overhaul

**Optimizer built (optimizer.py) — QA PASS**
- 6-dimension analysis: win rate/module, confidence tiers, exit timing, Brier score, daily cap utilization, sizing
- Bonferroni threshold = 0.05/6 = 0.0083
- Skips win-rate proposals when no scored outcomes exist
- Writes to logs/optimizer_proposals_YYYY-MM-DD.md

**Capital-scaled risk system — QA PASS**
- Per-module daily caps now % of capital (not fixed dollars):
  - WEATHER_DAILY_CAP_PCT=0.07, CRYPTO_DAILY_CAP_PCT=0.07, GEO_DAILY_CAP_PCT=0.04, ECON_DAILY_CAP_PCT=0.04
- Per-trade position cap: MAX_POSITION_PCT=0.01 (1% of capital, was hardcoded $25)
- OI cap activated: no single position > 5% of market open interest
- 70% global cap wired as real-time open exposure check in should_enter()
- At $10k: $700/$700/$400/$400 per module, $2,200 combined ceiling, $100/trade

**David's capital philosophy (authoritative):**
- Old win-rate data invalid (confidence field wasn't logged) — clean slate
- Module caps should reflect performance going forward — Optimizer will surface adjustments
- Underperforming modules: lower cap or close. Outperforming: raise cap.

**logger.py bug fixed:** build_trade_entry() was silently dropping `confidence` field — now written to every trade log

**DRY_RUN source of truth:** config.py reads mode.json → DRY_RUN = (mode != 'live'). All modules use config.DRY_RUN.

### Post-Phase Work (2026-03-26 afternoon session)

**Batch 1 — Code quality fixes (QA PASS)**
- security_audit.py: comment lines skipped (false positive fix)
- config_audit.py: accepts state 3/'Running' as valid Task Scheduler state
- test_modules.py: deleted (dead gaming_scout reference)
- code_audit.py: docstrings stripped before LIVE mode regex
- config.py: MIN_CONFIDENCE['weather'] → 0.25 (matches strategy.py)
- qa_self_test.py: created (monthly QA self-test, 17 checks)

**Batch 2 — Smart money wiring (QA PASS)**
- fetch_smart_money.py: hardcoded 4-wallet dict replaced with _load_wallets() reading logs/smart_money_wallets.json
- crypto_client.py: staleness check added (>25h warning)
- bot/wallet_updater.py: already correct, date updated. Runs at 7am daily, writes fresh leaderboard wallets to JSON

**Batch 3 — Scan schedule v2 + post-trade monitor (QA PASS WITH WARNINGS — both fixed)**
- ruppert_cycle.py: new modes added: weather_only, crypto_only, econ_prescan
- post_trade_monitor.py: NEW — unified post-entry watcher for all modules, every 30 min. Auto-exits at 95c/70% gain (weather+crypto). Alert-only for econ/geo/fed. DRY_RUN reads from config.
- Task Scheduler v2: applied (see infrastructure above)
- QA warnings fixed: DRY_RUN now reads from config; config_audit accepts numeric state 3

### Optimizer — BUILT + QA PASS (2026-03-26)
- **Frequency**: Monthly by default, or triggered after 30+ new trades or 3+ losses in 7 days
- **Min dataset**: 30 trades per module — self-aborts if insufficient data
- **Model**: Opus for analysis/proposals, Haiku for data prep
- **Dimensions**: entry timing, edge calibration (Brier score), module P&L, sizing, exit timing, market selection, scan schedule
- **Output**: optimizer_proposals_YYYY-MM-DD.md → CEO reviews → David approves → Dev builds
- **Thresholds**: all in config.py as OPTIMIZER_* constants (tunable without code changes)

### Opus Audit #2 Findings (2026-03-26 ~8:33pm–8:55pm) — ALL RESOLVED

**P0 fixes:**
- trader.py: restored MAX_POSITION_SIZE=100.0 + MAX_DAILY_EXPOSURE=700.0 to config.py (legacy fallback path)
- kalshi_client.py: fixed m.ticker/m.title dict attribute bug in __main__ test block
- ruppert_cycle.py: moved actions_taken=[] before try block (scope bug)

**P1 fixes:**
- openmeteo_client.py: hours_since_midnight now uses local time not UTC (same-day cutoff was firing at wrong times)
- post_trade_monitor.py: positions keyed by (ticker, side) not ticker alone
- dashboard/api.py: KXSOL added to crypto module classifier
- edge_detector.py: T-market type inference fallback when title regex fails

**P2/P3 fixes:** ghcnd_client off-by-one, optimizer.py redundant check, logger.py module fallback, economics_scanner.py comment accuracy, strategy.py lowercase normalization, capital.py float() safety

**Geo restored:** GEO_AUTO_TRADE = True in DEMO. Session 3 had set it False (news_volume signal concern) but actual trade path uses LLM pipeline (Haiku+Sonnet). DEMO = all modules ON for data collection.

**Git:** committed + pushed `1719e49` (18 files)

### WS-First Architecture (2026-03-28, activated)
- **`market_cache.py`** — thread-safe price cache, 60s stale threshold, 300s purge, `logs/price_cache.json` persistence
- **`position_tracker.py`** — WS-driven real-time exits (95c rule + 70% gain), replaces 30-min polling. Disk persistence.
- **`ws_feed.py`** — single persistent WS, subscribes to ALL tickers, filters by `WS_ACTIVE_SERIES` (30 prefixes). Routes to cache + exits + crypto entry eval.
- **Modules integrated:** `edge_detector.py`, `economics_scanner.py`, `fed_client.py`, `crypto_client.py` — all use cache-first + REST fallback
- **`post_trade_monitor.py`** — kept as safety net, deprecated
- **Task Scheduler:** `Ruppert-WS-Persistent` now runs `ws_feed.py` directly
- **WS URL fix:** was hitting `demo-api.kalshi.co` (wrong), now `api.elections.kalshi.com` (correct)
- **Exit latency:** was 30 min polling → now <1 second via WS position tracker
- **REST:** orders + startup + reconnect recovery only

### 15-Min Crypto Binary Module (2026-03-28, activated)
- **Module:** `crypto_15m.py` — handles KXBTC15M/KXETH15M/KXXRP15M/KXDOGE15M
- **Signals:** TFI 0.40 + OBI 0.25 + MACD-5m 0.15 + OI-delta 0.10 (weights FIXED, do not tune)
- **Sigmoid scale:** 1.0 — intentionally uncalibrated, autoresearcher will tune from live data
- **Min edge:** 8c primary (2-8min), 10c secondary (8-11min)
- **Decision log:** `logs/decisions_15m.jsonl` — ALL evaluations including skips
- **Task Scheduler:** `Ruppert-WS-Persistent` fires daily at 6AM, self-exits outside 6AM-11PM
- **Autoresearcher:** crypto_15m domain added, needs 30 trades before first analysis
- **Key audit finding:** Coinbase-Binance basis filter (R10) critical — Kalshi settles on Coinbase
- **Status:** DEMO active as of 2026-03-28

### Known Issues / Prompt Template Bug
- `openclaw system event --mode now` is wrong — should be `--model` or flag doesn't exist. Remove from all Dev/QA prompt templates. Notify command was causing phantom exit code 1s.

### Autoresearch Safety
- Bonferroni correction required: after N experiments, improvement must exceed 0.05/N
- Min 30 trades in BOTH in-sample AND out-of-sample
- Can tune: MIN_EDGE, Kelly tiers, exit thresholds, confidence gates, daily cap
- Cannot touch: API keys, file paths, risk hard caps ($50 max position)

---

## Setup & Infrastructure

- **Git**: user.name=Ruppert, user.email=ruppert@kalshi-bot; GitHub token embedded in remote URL; expires ~June 2026
- **GitHub repo**: https://github.com/eulahwu917/ruppert-tradingbot (remote: origin, branch: main)
- **Dashboard**: port 8765, network address http://192.168.4.31:8765
- **Python**: `C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe`
- **Bot directories**: `C:\Users\David Wu\.openclaw\workspace\environments\demo\` (active DEMO) and `C:\Users\David Wu\.openclaw\workspace\environments\live\` (inactive LIVE) — previously at `Projects\ruppert-tradingbot-demo\` (moved)
- **Kalshi API key**: read from `secrets/kalshi_config.json` — never hardcode
- **Demo mode**: ALL modules ON (Weather, Crypto, Geo, Fed, Econ). LIVE: only Weather+Crypto ON.
- **Task Scheduler (v2 — active as of 2026-03-26)**:
  - 5:00am — econ_prescan (self-exits if no release today)
  - 6:00am–11pm — post_trade_monitor.py every 30 min
  - 7:00am — full cycle
  - 10:00am — crypto_only
  - 3:00pm — full cycle
  - 6:00pm — crypto_only
  - 7:00pm — weather_only (catches next-day markets opening)
  - 10:00pm — check (positions only)
  - 8:00pm — daily progress report
- **Pipeline rule**: Dev → QA → Dev loop until PASS → CEO → David. CEO notifies David immediately on QA pass.
- **Context window rule**: All agents save handoff at ~80% and start fresh session.

## Elevated Commands — Confirmation Required
- Elevated exec is enabled from Telegram
- **RULE: Always confirm with David before running any elevated command.** No exceptions.
- Show the exact command, explain what it does, wait for explicit "go ahead" / "yes" / approval
- This applies to: Task Scheduler changes, system config, anything requiring admin

## Security

- `groupPolicy` set to `"deny"` on 2026-03-11 — I do not respond in any group chats
- `dmPolicy: "pairing"` — only David can DM me
- No `groupAllowFrom` entries — cleaned out on 2026-03-11

## 2026-03-28 Major Architecture Session

### Bugs Fixed
- pnl_cache.json corruption: dashboard/api.py was overwriting Data Scientist's truth file
- settle records not counted in P&L (action=settle was ignored)
- Weather trades never registered in position tracker (tracker.add_position() missing from trader.py)

### New Architecture: Agent Ownership Model
Principle: every script has an agent owner; agents own truth files; scripts append events only

**Final org chart:**
- CEO (Sonnet) — ruppert_cycle.py, state.json
- Strategist (Opus, on-demand) — strategy.py, edge_detector.py, optimizer.py
- Data Scientist (Sonnet) — data_agent.py, capital.py, logger.py, dashboard, notifications, pnl_cache.json, pending_alerts.json
  - Data Analyst (Haiku) — all data fetching scripts, price_cache, ghcnd_bias_cache, smart_money files
  - Researcher (Sonnet) — new build, opportunities_backlog.json, reports/research/
- Trader (Sonnet) — trader.py, post_trade_monitor.py, position_monitor.py, tracked_positions.json
- Dev (Sonnet) + QA (Haiku) — pipeline only

### Phases Built (1-5)
1. Event-driven architecture: scripts log events, no truth file writes
2. Data Scientist synthesizer: reads events → writes truth files
3. Folder restructure: agents/data_scientist/, agents/trader/, agents/data_analyst/, agents/strategist/, agents/researcher/, agents/ceo/
4. Dashboard hardened read-only
5. Researcher agent + CEO brief generator (daily_brief_YYYY-MM-DD.md)

### Phase 6 Plan (saved to memory/phase6-plan.md)
- Rename projects/ → environments/ (demo, live)
- Agents at .openclaw/workspace/agents/ level
- Passive income folder: wipe
- Live = read-only until David says go
- CEO role: trading only
- Trader: hybrid (ws_feed persistent for crypto 15m, cron for rest)
- Full system audit after Phase 6 (batched: Strategist arch audit, QA code audit, Data Scientist data audit, Strategist algo audit)

### Task Scheduler
- Ruppert-DailyProgressReport → now runs agents.ceo.brief_generator
- Ruppert-Research-Weekly → new, Sundays 8am


## 2026-03-28 Phase 6 + Full System Audit Complete

### Phase 6 (workspace restructure)
- projects/ → environments/ (demo + live)
- Agents extracted to workspace/agents/ruppert/
- Old demo agents archived to archive/demo-agents-pre-phase6/
- passive-income-research deleted
- env_config.py: environment-aware path resolution
- require_live_enabled() guard: live write protection
- ws_feed watchdog added (scripts/ws_feed_watchdog.py)
- CEO role hardening (check_role_boundary())

### Full System Audit Findings (all resolved)
- Architecture: PASS. require_live_enabled() guards wired to trader.py, position_tracker.py, logger.py
- Code: PASS. 25/25 tests, clean imports, Task Scheduler correct
- Data: capital.py now reads from logs/truth/pnl_cache.json (authoritative). Live dashboard write removed. data_health_check.py path fixed.
- Algo: PASS. All parameters intact. NO-only weather filter RETIRED — both YES and NO now allowed based on edge sign.
- Trader: crypto/fed now route through Trader.execute_opportunity(). Fed P&L bug fixed (scan_price/fill_price added). run_exit_scan() removed from orchestration. Exception-safe trade logging added.

### Weather Direction Filter — RETIRED 2026-03-28
David's decision: YES weather trades are now allowed. Both directions based on edge sign.
Previous: NO-only (90.4% win rate was NO-only era)


## 2026-03-28 Final System Audit + All Bugs Fixed

### Additional bugs found and fixed after Phase 6 audit
- position_monitor: should_enter() wrong signature (2 args → 3), missing open_position_value → 70% cap was silently disabled for WS crypto entries
- crypto_long_horizon: should_enter() never called — 70% global cap bypassed entirely. Now enforced per-opportunity.
- crypto_15m: get_daily_exposure() called with arg it doesn't accept → crash fixed
- crypto_15m: hardcoded LOGS_DIR → fixed to env_config
- position_monitor: stale bot.strategy import → fixed
- edge_detector: noaa_client bare import crash risk → guarded
- edge_detector: signal_src string mismatch → ensemble confidence gate now fires
- market_cache: REST fallback wrong field names → fixed (yes_bid not yes_bid_dollars)
- fetch_smart_money: hardcoded output path → fixed
- market_scanner: Unicode crash on Windows → fixed
- post_trade_monitor: YES-side 95c rule was missing → added
- ruppert_cycle: same-day re-entry blocked (Strategist decision)
- ruppert_cycle: smart mode now triggers synthesizer (Data Scientist decision: lighter synthesis)

### Pipeline updates (PIPELINE.md v3.0)
- Trader executes autonomously within thresholds — CEO NOT in per-trade loop
- CEO involvement: exceptions only (hard limit, circuit breaker, anomaly, new instrument)
- Agent Ownership & Boundaries section added: each agent owns their domain, no agent touches another's
- Live flip: 3 explicit David confirmations required
- Data retention: trade logs forever, research reports forever, all else 1 year
- Secrets rotation: every 3 months, next due 2026-06-28 (in HEARTBEAT.md)
- Researcher cadence: weekly light Sunday + monthly deep first Sunday
- Optimizer cadence: monthly or 30+ trades or 3+ losses in 7 days

### Weather direction filter
RETIRED 2026-03-28. Both YES and NO now trade based on edge sign.

## Deferred: SIA + Infrastructure

### SIA Wiring (defer, David to follow up)
- xiucheng SIA should read agent MEMORY.md files directly instead of separate improvement_log.md
- Just point `sia.improvement_log` at the existing MEMORY.md — no synthesizer needed
- Small change to `run_self_improvement.py` (5 lines) to display MEMORY.md content in report
- Currently Friday heartbeat runs SIA for Ruppert main only; sub-agents deferred until this is wired
- **Status:** Deferred — David to follow up

### Infrastructure Overhaul for Staging/LIVE (David + Strategist)
- At some point before LIVE flip, need a full infrastructure overhaul
- David will work with Strategist on this
- Covers: DEMO→STAGING→LIVE promotion process, agent org chart for LIVE ops, monitoring, rollback
- Checklists exist at `environments/staging/CHECKLIST-TO-STAGING.md` and `environments/live/CHECKLIST-TO-LIVE.md`
- **Status:** Deferred — trigger when approaching LIVE readiness

## 2026-03-29 Evening + Post-Audit Session

### Key bugs found and fixed
- **DRY_RUN import-time freeze** still present in position_monitor.py + crypto_15m.py after prior fix — fixed c63bd4f
- **Market impact ceiling completely inactive for weather** — edge_detector.py returned `yes_price` but should_enter() checked for `yes_ask`/`yes_bid` — key mismatch, ceiling never fired — fixed 8af93c6
- **Daily exposure 2-day lookback** — multi-day open positions invisible to cap checks — fixed 984c025
- **Same-day re-entry guard broken** — `_opp_to_signal()` in main.py missing `'ticker'` key → guard always short-circuited → 3pm + 7pm scans double-bought same weather markets ($933 vs $538 cap) — fixed 3dead29
- **WS feed + watchdog both dead** after audit code changes — Task Scheduler only boots watchdog once; Phase 7 (system restart check) added to audit-workflow.md — b631acb
- **"Missing from tracker" warning** — self-heal path added: auto-reconstructs entries from trade log data — a293cbf

### Pipeline improvements
- **Phase 7** added to audit-workflow.md: always restart persistent processes (ws_feed, watchdog, dashboard) if their code was changed during audit
- **PIPELINE.md Rule 5** confirmed as the enforcement point for runtime changelog logging (not RULES.md)
- **Task Scheduler**: Ruppert-WS-Watchdog now has restart-on-failure (10x, every 2 min)

### 15m crypto status
- 40,381 decisions logged, 0 entries still
- Thresholds relaxed today (MIN_EDGE 0.05→0.02, etc.) — needs full day to assess
- THIN_MARKET was biggest blocker pre-relaxation (2,512 kills with good signals)

### David hands-off
- Going hands-off ~1 week from 2026-03-30
- System in cleanest state ever: 0 Critical, 0 High outstanding after full audit loop

## 2026-03-31 — Major Session

### Performance
- 3/31 P&L: **+$12,723.44 VERIFIED** (DS full audit). 95 exits, 100% win rate on closed positions.
- 3/30 P&L: +$4,184 adjusted (was $4,459 — phantom exit +$119 + missing settle legs -$156)
- All-time closed P&L as of EOD 3/31: +$14,387 (adjusted)

### Bug Fixes (commit 474bdc2)
- **P0 WS phantom exit**: `_recently_exited` 300s TTL cooldown added to position_tracker. Premature `_exits_in_flight.discard()` removed from `remove_position()`.
- **P1 Missing settle legs**: `add_position()` now accumulates+blends instead of overwriting. `load_all_unsettled()` uses FIFO exit-count matching.
- **P2 Duplicate buy log entries**: `is_tracked()` guard in `execute_opportunity()` + fingerprint dedup in `log_trade()`.

### Architecture: Single Source of Truth (commits a19f75c + ee55ec4)
- **Phase 1**: All hardcoded constants moved to config.py. Full taxonomy migration. Zero behavior change.
- **Phase 2**: Approved changes applied as config edits.
- `strategy.py` was already the central execution brain (~70% of Option B already done).
- `TICKER_MODULE_MAP` in data_agent.py was the root cause of the crypto cap bug — was overwriting `crypto_15m_dir` → `crypto_15m` on every audit cycle.

### David's Strategic Decisions (authoritative, 2026-03-31)
- **Daily caps fully removed**. Window cap (4%) + CB (N=3, hard stop) are the risk controls.
- **Window cap raised: 2% → 4%** (`CRYPTO_15M_WINDOW_CAP_PCT = 0.04`). Worst-case before CB: ~$2,880.
- **Exit threshold: 70% → 90%** — new positions only. Existing tracked positions keep 70%.
- **MIN_CONFIDENCE crypto_15m_dir: 0.50 → 0.40** — provisional, 2-week Optimizer review gate.
- **Signal weights: W_TFI 0.42→0.50, W_OI 0.18→0.10** (sum = 1.00).
- **1h Band CB added**: N=3 consecutive complete-loss hours → hard stop.
- **crypto_15m keeps half-Kelly** (intentional — 15m too short for tiered-Kelly).
- **Phase 3 deferred**: move half-Kelly params to config after 30+ days data.
- **Dead zone (6:30-10am EDT)**: watch only — need 30+ trades before adding gate.

### Open Items (2026-03-31)
- `get_strategy_summary()` fallback: should be 0.90, currently 0.70 (cosmetic, fix next commit)
- ISSUE-01: `MIN_EDGE_CRYPTO_15M_DIR = 0.12` (strategy gate) vs `CRYPTO_15M_MIN_EDGE = 0.02` (local gate) — Optimizer review after 30+ days
- ISSUE-03: TICKER_MODULE_MAP weather_band/threshold ambiguity — DS to spec fix
- ISSUE-05: `CRYPTO_1D_DAILY_CAP_PCT` may still be used by crypto_1d internally — Dev to verify
- 2-week Optimizer review: check win rate on 0.40-0.44 confidence band (approx 2026-04-14)
