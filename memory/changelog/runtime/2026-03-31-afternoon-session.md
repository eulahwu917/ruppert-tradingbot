# Runtime Log — 2026-03-31 (Afternoon Session, ~14:00–16:45 PDT)

## Issues Found & Fixed

---

### RUNTIME-2026-03-31-001 | Settlement Checker misconfigured as one-shot
**Severity:** P0
**Root cause:** `Ruppert-SettlementChecker` Task Scheduler task was created as a one-shot (no repetition interval). With 15m crypto contracts expiring every 15 minutes, settlements were only being recorded at 8AM and 11PM — creating hours of P&L limbo.
**Fix:** Recreated task via XML with `<Repetition><Interval>PT30M</Interval>` — runs every 30 min, 24/7.
**Also:** `config_audit.py` updated to verify trigger intervals, not just task existence. `audit-workflow.md` Phase 1c (Scheduler Audit) added. 23 Task Scheduler XML exports created in `scripts/setup/`. `register_all_tasks.ps1` created for disaster recovery.
**Commits:** Dev-scheduler-audit-fix batch

---

### RUNTIME-2026-03-31-002 | Double-entry race condition (position_monitor + ws_feed)
**Severity:** P1
**Root cause:** Two OS processes both connected to Kalshi WS simultaneously — `ws_feed.py` (persistent) and `position_monitor.py` (Task Scheduler 14-min burst). Both called `evaluate_crypto_15m_entry` on the same market. Threading lock doesn't protect across processes = race condition = double entries.
**Evidence:** `KXXRP15M-26MAR311700-00` bought twice at 13:47:04 and 13:47:05 (1 second apart), different module labels (`crypto_15m_dir` vs `crypto_15m`).
**Fix:**
- Disabled `Ruppert-PostTrade-Monitor` Task Scheduler task
- Retired WS mode in `position_monitor.py` (`run_ws_mode`/`run_persistent_ws_mode` stubbed with RuntimeError)
- Created `agents/ruppert/trader/utils.py` with `load_traded_tickers` + `push_alert`
- Inlined `evaluate_crypto_entry` (hourly bands) into `ws_feed.py`
- Updated imports in `crypto_15m.py` and `ws_feed.py`
**Commit:** `2d98328` — refactor: retire position_monitor WS mode, extract utils.py, inline hourly eval into ws_feed
**Smoke test:** 23/23 PASS

---

### RUNTIME-2026-03-31-003 | NO-side exit P&L formula wrong in position_tracker
**Severity:** P1
**Root cause:** `execute_exit()` for NO-side positions used formula `(entry_price + exit_price - 100) * contracts / 100` instead of correct `(exit_price - entry_price) * contracts / 100`. All 70pct_gain_no exits were inflated.
**Impact:** $2,428 P&L overstatement across all NO-side 70% gain exits.
**Fix:** Corrected formula in `position_tracker.py`. Also fixed `action_detail` to log NO price instead of YES bid.
**Commit:** `7f9d54a` (Batch 1)

---

### RUNTIME-2026-03-31-004 | NOAA client silently unavailable in edge_detector
**Severity:** P1
**Root cause:** `edge_detector.py` uses a bare `from noaa_client import ...` which fails silently when run from the agents path (noaa_client lives in environments/demo, not on path). NOAA fallback always disabled without warning.
**Fix:** Absolute path injection before import + warning log when unavailable.
**Commit:** `7f9d54a` (Batch 1)

---

### RUNTIME-2026-03-31-005 | pnl_correction.py not idempotent — wrote duplicates
**Severity:** P1
**Root cause:** Correction script ran twice (11:49 AM and 15:56 PM). No guard against duplicate writes. 41 corrections were written twice = 82 total, causing every correction to double-count and producing impossible negative capital (-$7,472).
**Fix:**
- Dev: added idempotency check — builds `already_corrected` set from existing correction records before writing. Commit `7e59848`.
- DS: removed 41 duplicate correction records from trade logs. Files rewritten atomically.
**Post-cleanup capital:** ~$9,823 (confirmed sane — max loss $10k deposit)

---

### RUNTIME-2026-03-31-006 | 45+ hardcoded values in trading logic
**Severity:** P1/P2
**Root cause:** Large audit found hardcoded thresholds across strategy.py, crypto_15m.py, crypto_1d.py, crypto_long_horizon.py, edge_detector.py — Optimizer can't tune what's not in config.
**Fix:** All moved to config.py using `getattr(config, 'KEY', default)` pattern. 45 new config keys added.
**Commits:** `bec298f` (strategy.py), `a298960` (crypto modules + edge_detector)

---

### RUNTIME-2026-03-31-007 | post_trade_monitor.py exit threshold not reading config
**Severity:** P1
**Root cause:** `check_weather_position()` and `check_crypto_position()` had `0.70` hardcoded — not reading `config.EXIT_GAIN_PCT`. If config was ever changed, monitor would still use old threshold.
**Fix:** Replaced with `getattr(config, 'EXIT_GAIN_PCT', 0.70)`.
**Commit:** `bec298f`

---

### RUNTIME-2026-03-31-008 | atomic writes missing in post_trade_monitor
**Severity:** P3
**Root cause:** Smoke test check 6 flagged missing `unlink`/`missing_ok` pattern in monitor files.
**Fix:** 3 write blocks in `post_trade_monitor.py` converted to atomic `.tmp` → replace pattern.
**Commit:** `fix: atomic writes in post_trade_monitor + position_monitor`
**Smoke test:** 23/23 PASS, 0 WARN

---

## Performance Observations (2026-03-31)

### Module P&L (corrected, post-dedup)
| Module | W/L | Win% | P&L |
|--------|-----|------|-----|
| crypto_15m_dir (combined w/ old label) | 190/118 | 62% | **+$6,736** |
| crypto_1h_band | 6/5 | 55% | +$28 |
| crypto_1h_dir | 1/3 | 25% | +$49 |
| crypto (hourly bands) | 4/59 | 6% | -$2,907 |
| weather | 0/24 | 0% | -$2,071 |
| weather_band | 4/33 | 11% | -$2,270 |

**Key finding:** crypto_15m_dir is the only module generating meaningful alpha. All others are net negative. Weather has 0 wins — NOAA systematically overconfident. Hourly crypto bands (6% WR) likely broken signal. Data collection continuing — Optimizer review after 30+ trades per module.

### Capital (end of session)
- Starting capital: $10,000
- Closed P&L: ~-$177
- **True capital: ~$9,823**

---

## Deferred Items
- Weather module signal quality — NOAA recalibration needed. Monitoring, not pausing yet.
- pnl_cache.json — marked stale, dashboard ignores it. Deprecate/delete in next cleanup sprint.
- `should_exit()` in strategy.py appears to be dead code in live exit path — confirm and remove.
- 5 double-close records from taxonomy migration (~$565) — marked _invalid, low impact.

---

# Runtime Log — 2026-03-31 (Evening Session, ~19:00–21:30 PDT)

## Issues Found & Fixed

---

### RUNTIME-2026-03-31-009 | pnl_cache.json deleted — P&L single source of truth refactor
**Severity:** P1
**Root cause:** `pnl_cache.json` was a stale intermediate cache that diverged from actual log state across restarts, corrections, and deduplication passes. Multiple agents were reading it and getting different answers depending on when it was last written.
**Fix:** Deleted permanently. Single canonical path established: raw logs → `compute_closed_pnl_from_logs()` → `get_capital()`. mtime-based in-process cache added for performance (no file-based caching).
**Impact:** All agents must stop referencing `pnl_cache.json`. DS MEMORY.md updated to reflect deletion.

---

### RUNTIME-2026-03-31-010 | CB (Capital Bridge) reading wrong P&L field
**Severity:** P1
**Root cause:** CB was reading `realized_pnl` from trade log records. Actual field name in records is `pnl`. All closed-trade P&L read by CB was silently zero.
**Fix:** Field reference corrected to `pnl`. Also added negative capital guard — prevents impossible capital values from propagating downstream.

---

### RUNTIME-2026-03-31-011 | NO-side P&L formula bug in ws_feed
**Severity:** P1
**Root cause:** ws_feed was using an incorrect formula for NO-side settlement P&L calculation. Formula was computing wrong profit/loss on all NO-side settled positions.
**Fix:** Formula corrected. ws_feed restarted to load corrected logic. 3 correction records applied to affected historical entries to reconcile past settlements.

---

### RUNTIME-2026-03-31-012 | Brief generator showing $19K P&L (wrong)
**Severity:** P1
**Root cause:** `brief_generator.py` had its own P&L summation logic that did not include `exit_correction` records — it diverged from `compute_closed_pnl_from_logs()`. Also had a hardcoded `KNOWN_MODULES` list that missed new modules.
**Fix:**
- Now calls `compute_closed_pnl_from_logs()` directly — same source as `get_capital()`
- Module list made dynamic — scans log records rather than using hardcoded list
- Brief P&L now matches dashboard capital exactly

---

### RUNTIME-2026-03-31-013 | Geo module confirmed dead (GDELT timeout)
**Severity:** P2
**Root cause:** All GDELT API calls timing out. Geo module has been non-functional for unknown duration — no trades, no errors surfaced to brief.
**Status:** Deferred. Replacement stack identified: TheNewsAPI (keyword search + `found` volume count for spike detection). Not yet built — scoped for future sprint.
**Note:** TheNewsAPI key saved to `secrets/thenewsapi_config.json`.

---

## New Infrastructure Built (Evening Session)

### terminal_signal_logger.py
- **Path:** `environments/demo/terminal_signal_logger.py`
- **Purpose:** Shadow logger — fires at T-90s before close for every open crypto_15m_dir position
- **Logs:** TFI, OBI, MACD, OI signal at T-90s vs signal at entry
- **Output:** `logs/terminal_signals/YYYY-MM-DD.jsonl`
- **Status:** Live, collecting. 36 records logged evening of 2026-03-31.
- **Hypothesis being tested:** Does terminal-window signal contradiction predict losses? (Hypothesis 2 from strategist MEMORY.md)

### intra_window_logger.py
- **Path:** `environments/demo/intra_window_logger.py`
- **Purpose:** Logs yes_bid/ask every 60s for each open crypto_15m_dir position
- **Output:** `logs/price_series/{ticker}.jsonl`
- **Status:** Live, collecting.
- **Use case:** Future backtest price series reconstruction — understand intra-window price paths

### polymarket_client.py
- **Path:** `agents/ruppert/data_analyst/polymarket_client.py`
- **Purpose:** Shared Polymarket signal client for all agents
- **Functions:** `get_crypto_consensus()`, `get_geo_signals()`, `get_wallet_positions()`, `get_smart_money_signal()`, `get_markets_by_keyword()`
- **Status:** Shadow mode only — NOT wired into any live module
- **Plan:** 7-day shadow collection → 200+ trades → correlation analysis → potential YES-side gate filter

### data_toolkit.py
- **Path:** `scripts/data_toolkit.py`
- **Purpose:** Fast agent analysis CLI — replaces manual raw log reads
- **Usage:** `python scripts/data_toolkit.py winrate --module crypto_15m_dir --days 7 --by asset,hour,side`
- **Performance:** <3s for all queries
- **Status:** Live — all agents should use this

### Sports Odds Collector (fixed)
- Kalshi `series_ticker` query corrected
- `bird` full path fixed (xurl removed entirely)
- Now collecting: 11 NBA + 33 MLB games daily
- `/api/sports` endpoint added + UI dashboard card showing Vegas vs Kalshi gap live

---

## Strategist Analysis (Evening Session)

### Crypto Win Rate Analysis (296 trades, Mar 30-31 data)

| Dimension | Value |
|-----------|-------|
| NO side WR | **87.6%** |
| YES side WR | **56.3%** |
| 09:00 EDT WR | **38.9%** (18 trades) |
| Entry 35–65c WR | **80–82%** |
| Entry <35c WR | **57–65%** |
| ETH WR | 79.5% |
| XRP WR | 74.7% |
| DOGE WR | 75.7% |
| BTC WR | 70.3% |

**Key takeaway:** YES side (56.3%) is the weak flank. 09:00 EDT is a dead zone. Entry price below 35c significantly degrades performance.

### Polymarket Decision
- Shadow log only for 7 days — do NOT wire into live weights
- After 200+ shadow trades: run correlation vs settlement outcome
- Hypothesis: Polymarket consensus could serve as YES-side gate filter

---

## Agent MEMORY.md Updates (Evening Session)

All 5 agent MEMORY files appended with 2026-03-31 session context:
- `agents/ruppert/data_analyst/MEMORY.md` — Polymarket, sports, TheNewsAPI, data_toolkit, capital
- `agents/ruppert/data_scientist/MEMORY.md` — pnl_cache deletion, new log paths, NO-side fix, data_toolkit, capital
- `agents/ruppert/researcher/MEMORY.md` — new data sources, sports odds, data_toolkit, capital
- `agents/ruppert/strategist/MEMORY.md` — win rate findings, Polymarket decision, dead zone, data_toolkit, capital
- `agents/ruppert/trader/MEMORY.md` — pnl_cache deletion, CB fixes, NO-side formula, brief generator, capital

---

## Capital (End of Evening Session)
- **~$13,146** (up from ~$9,823 at end of afternoon session — live trading gains during evening)

---

## Deferred Items (Evening)
- 09:00 EDT skip gate — needs spec + David approval before wiring
- YES-side gate filter — pending 7-day Polymarket shadow data
- Geo replacement stack (TheNewsAPI) — scoped, not yet built
- Proposal A (payoff-aware NO scaling at 70c+) — approved in principle, spec → Dev when David says go
- Proposal B (correlated window halt) — approved in principle, spec → Dev when David says go
