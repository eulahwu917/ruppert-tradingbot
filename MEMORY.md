# MEMORY.md — Ruppert Long-Term Memory
_Main session only. Never load in group chats or shared contexts._

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
- **Dashboard**: port 8765, network address http://192.168.4.31:8765
- **Python**: `C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe`
- **Bot directories**: `Projects\ruppert-tradingbot-demo\` (active) and `Projects\ruppert-tradingbot-live\` (inactive)
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
