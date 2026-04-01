# Audit CHANGELOG
_Compact index of all audit findings + runtime issues. Read this before starting any audit._
_Audit detail files: `memory/changelog/audit-logs/YYYY-MM-DD-{domain}.md`_
_Runtime issues: `memory/changelog/runtime/YYYY-MM-DD-issues.md`_
_Archive (Fixed+QA-passed >60 days): `memory/changelog/archive/`_
_Maintained by: CEO (written in Phase 6 of audit-workflow)_

---

## Finding ID Schema
Format: `{DOMAIN}-{SEVERITY}{N}` where:
- DOMAIN: TRADER, STRAT, DS, DA, CEO, RES
- SEVERITY: C (critical), H (high), M (medium), L (low)
- N: sequential within severity tier per audit loop
- Example: `TRADER-C1`, `STRAT-H2`, `DS-M3`

Status values:
- **Fixed** (commit hash) + QA-passed — skip on future audits
- **False-alarm** (reason) — do not re-raise; note scope if DEMO-only
- **Deferred** (reason + condition to revisit)
- **Dismissed** (reason)

## Pruning Rule
Entries marked Fixed+QA-passed older than 60 days → archive to `memory/audit-log/archive/`

---

## 2026-03-29 Runtime Issues (post-audit, evening — 15m optimization)

RUNTIME-2026-03-29-010 | LATE_WINDOW skips 59% of all 15m decisions — WS reconnect cold-start gap + slow fallback poll | Fixed (df9c857 — STRAT-15M-1/2/3/4: REST bootstrap on reconnect, 30s poll, extended entry cutoff, aligned settlement gate) QA-passed

---

## 2026-03-29 Runtime Issues (post-audit, evening)

RUNTIME-2026-03-29-007 | Brief generator showing P&L $0.00 and 18W/0L — `realized_pnl` field name mismatch (records use `pnl`); W/L fallback counted all settlements as wins | Fixed (64cde5f) QA-passed
RUNTIME-2026-03-29-008 | Brief missing Geo/Fed/Econ/Crypto15m modules — no KNOWN_MODULES registry, only shows modules with trades | Fixed (64cde5f) QA-passed
RUNTIME-2026-03-29-009 | Tracker auto-heal sent warning alert on success — info-level issues should not alert; gated on failure only | Fixed (64cde5f) QA-passed

---

## 2026-03-29 Runtime Issues (post-audit)

RUNTIME-2026-03-29-004 | WS feed + watchdog both dead after audit code changes — Task Scheduler only boots watchdog once | Fixed (b631acb — Phase 7 added to audit workflow; Task Scheduler restart-on-failure configured) QA-passed
RUNTIME-2026-03-29-005 | Daily cap violation: weather $933 vs $538 — `_opp_to_signal()` missing `ticker` key, re-entry guard always short-circuited | Fixed (3dead29) QA-passed
RUNTIME-2026-03-29-006 | "Missing from tracker" warning recurring — no auto-heal path for positions missing from tracker | Fixed (a293cbf — `_register_missing_positions()` auto-reconstructs entries) QA-passed

---

## 2026-03-29b Audit Loop

### TRADER Domain

TRADER-NEW-H1 | DRY_RUN resolved at call-time (not import-time) in position_monitor + crypto_15m — mode flip now respected immediately | Fixed (c63bd4f) QA-passed
TRADER-NEW-H2 | DRY_RUN resolved at call-time in post_trade_monitor — live exits no longer simulated after mode flip | Fixed (c63bd4f) QA-passed
TRADER-NEW-M1 | asyncio.get_event_loop() deprecated in Python 3.12+ inside running coroutine — replaced with get_running_loop() | Fixed (c63bd4f) QA-passed
TRADER-NEW-L1 | Bare except in load_traded_tickers swallowed all errors silently — changed to except Exception | Fixed (c63bd4f) QA-passed
TRADER-NEW-L2 | DOGE classifier edge case produced incorrect signal — classifier logic corrected | Fixed (c63bd4f) QA-passed
TRADER-V2-L1 | Bare except at line 317 in trader_v2 swallowed all errors silently — changed to except Exception | Fixed (3ce1550) QA-passed
TRADER-V1 | Round-2 deferred item (barrier_boost tautology) — RESOLVED (already simplified in code, no commit needed) | Dismissed

### STRAT Domain

STRAT-H6 | Market impact ceiling used wrong dict keys — ceiling lookups always missed, no cap applied | Fixed (8af93c6) QA-passed
STRAT-M7 | min_edge missing from get_strategy_summary() output — now included for all modules | Fixed (8af93c6) QA-passed
STRAT-M8 | Fed cap not wired into optimizer daily cap denominator — Fed allocation uncapped | Fixed (8af93c6) QA-passed
STRAT-L7 | PnL computation not None-safe — crash on positions with missing exit data | Fixed (8af93c6) QA-passed
STRAT-L8 | Stale/misleading inline comments in strategy core — updated to match current logic | Fixed (8af93c6) QA-passed
STRAT-L9 | Stale/misleading inline comments in strategist support modules — updated | Fixed (8af93c6) QA-passed
STRAT-M9 | Trade records may use size vs size_dollars inconsistently — False-alarm (trade records confirmed to use size_dollars throughout) | False-alarm (trade records confirmed to use size_dollars)
STRAT-V3-L1 | should_enter reason string said "_floored" but branch applies a cap — renamed to _capped | Fixed (3ce1550) QA-passed

### DS Domain (Data Scientist)

DS2-H1 | Exposure scanner only checked current day — all-time scan needed to catch stale open positions | Fixed (984c025) QA-passed
DS2-M1 | Pair-level drift check missing — position tracker drift only checked at ticker level | Fixed (984c025) QA-passed
DS2-M2 | entry_price computed as simple average on scale-ins — should use size-weighted average | Fixed (984c025) QA-passed
DS2-L1 | Minor code quality / comment issue in data_scientist.py | Fixed (984c025) QA-passed
DS2-L2 | Minor code quality / comment issue in data_scientist.py | Fixed (984c025) QA-passed
DS2-L3 | Minor code quality / comment issue in data_scientist.py | Fixed (984c025) QA-passed

### DA Domain (Data Analyst)

DA-M9 | traders_sampled count incremented before processing completes — count can overstate on partial failure | Fixed (984c025) QA-passed
DA-M10 | Singleton reuse issue (downgraded to Low) — client instance reuse across async contexts | Fixed (984c025) QA-passed
DA-M11 | Retry helper missing for Polymarket position fetch — single failure drops all wallet data | Fixed (984c025) QA-passed
DA-L9 | Minor code quality issue in data_analyst.py | Fixed (984c025) QA-passed
DA-L10 | Minor code quality issue in data_analyst.py | Fixed (984c025) QA-passed
DA-L11 | Minor code quality issue in data_analyst.py | Fixed (984c025) QA-passed
DA-L12 | Minor code quality issue in data_analyst.py | Fixed (984c025) QA-passed
DA-L12-PARTIAL | Stale KXHIGHLA ticker in HARDCODED_BIAS_F — replaced with correct active series | Fixed (3ce1550) QA-passed

### CEO Domain

CEO-M4 | CEO domain finding M4 — description in audit detail file | Fixed (d139d76) QA-passed
CEO-M5 | CEO domain finding M5 — description in audit detail file | Fixed (d139d76) QA-passed
CEO-M6 | CEO domain finding M6 — description in audit detail file | Fixed (d139d76) QA-passed
CEO-L4 | CEO domain finding L4 — description in audit detail file | Fixed (d139d76) QA-passed
CEO-L5 | CEO domain finding L5 — description in audit detail file | Fixed (d139d76) QA-passed

### RES Domain (Researcher)

RES-2b-H1 | Researcher high-severity finding from second loop — description in audit detail file | Fixed (d2a2ceb) QA-passed
RES-2b-M1 | Researcher medium finding from second loop — description in audit detail file | Fixed (d2a2ceb) QA-passed
RES-2b-M2 | Researcher medium finding from second loop — description in audit detail file | Fixed (d2a2ceb) QA-passed
RES-2b-L1 | Researcher low finding from second loop — description in audit detail file | Fixed (d2a2ceb) QA-passed
RES-2b-L2 | Researcher low finding from second loop — description in audit detail file | Fixed (d2a2ceb) QA-passed

---

## 2026-03-29 Audit Loop

### TRADER Domain

TRADER-C1 | `position_tracker._persist()` calls `require_live_enabled()` on every write — blocks position persistence if mode.json wrong | Fixed (0bf4823) + QA-passed
TRADER-C2 | `position_tracker.add_position()` gates with `require_live_enabled()` — live position may never be tracked, exits silently never fire | Fixed (0bf4823) + QA-passed
TRADER-C3 | `execute_exit()` uses module-level `DRY_RUN` constant (import-time freeze) — live positions get simulated exits after mode flip | Fixed (0bf4823) + QA-passed
TRADER-H1 | `run_geo_trades()` unconditionally appends to `executed` regardless of trade result — failed orders counted as successful | Fixed (0bf4823) + QA-passed
TRADER-H2 | Weather trades double-registered in `position_tracker` (once in `trader.py`, once in `main.py`) — exit threshold corrupted | Fixed (0bf4823) + QA-passed
TRADER-H3 | WS settlement detection uses `yes_ask >= 99` instead of `yes_bid` — false settlement signals possible | Fixed (0bf4823) + QA-passed
TRADER-H4 | `crypto_15m.py` R8 drawdown guard divides by `daily_alloc` not `capital` — pauses trading after trivial $20 loss | Fixed (0bf4823) + QA-passed
TRADER-H5 | False-alarm: Kelly sizing `c = entry_price / 100` — correctly converts cents to probability, not a bug | False-alarm (confirmed correct: entry_price in cents / 100 = probability)
TRADER-H6 | `post_trade_monitor.py` settlement checker only looks at today + yesterday — long-horizon positions never settled | Fixed (0bf4823) + QA-passed; window extended to 365 days (01cc632)
TRADER-H7 | `crypto_long_horizon.py` touch_probability unconditional multipliers (1.25/1.4/1.35) — systematically overstates edge | Fixed (0bf4823) + QA-passed
TRADER-H8 | `run_fed_scan()` appends to `executed` before checking result — failed Fed trades block retry for session | Fixed (0bf4823) + QA-passed
TRADER-M1 | Exit log records `exit_price: yes_bid` for NO positions — analytics wrong for NO exits | Fixed (0bf4823) + QA-passed
TRADER-M2 | `position_monitor.evaluate_crypto_entry()` passes `traded_tickers=None` to `should_enter()` | Fixed (0bf4823) + QA-passed
TRADER-M3 | `position_monitor.load_open_positions()` only scans today + yesterday — long-horizon positions invisible | Fixed (0bf4823) + QA-passed; extended to 365 days (01cc632)
TRADER-M4 | `crypto_15m.py` R1 compares price range ratio against volume count (incompatible units) — R1 filter dead | Fixed (0bf4823) + QA-passed
TRADER-M5 | `run_exit_scan()` deprecated function still callable — archived with RuntimeError | Fixed (0bf4823) + QA-passed
TRADER-M6 | False-alarm: `_load()` migration calls `_persist()` — code does call `_persist()`, not a bug | False-alarm (code correctly persists after migration)
TRADER-M7 | `scan_long_horizon_markets()` no settlement date guard — expired markets generate spurious signals | Fixed (0bf4823) + QA-passed
TRADER-M8 | False-alarm: elapsed_secs fallback — defensive code works correctly for stale WS messages | False-alarm (max(0,...) handles negative correctly, LATE_WINDOW skip is correct)
TRADER-M9 | Duplicate `load_open_positions()` implementations in post_trade_monitor and position_monitor — divergence risk | Deferred (refactor is large; both implementations now use same 30/365-day window logic — low risk)
TRADER-L1 | `trader.py` `self.bankroll -= size` is dead code — never read after subtraction | Fixed (0bf4823) + QA-passed
TRADER-L2 | `main.py` `band_prob()` duplicates `crypto_client._band_probability()` with inconsistent model | Deferred (different model choice is intentional per architecture; document when consolidating)
TRADER-L3 | False-alarm: `size_long_horizon()` — `c = win_prob - edge = market_prob`, standard Kelly — not a bug | False-alarm (algebra is correct, standard Kelly formula)
TRADER-L4 | `crypto_15m.py` signal weights sum to 0.90 not 1.0 | Fixed (0bf4823) + QA-passed (weights now sum to 1.00)
TRADER-L5 | `crypto_client.py` `_WALLETS_FILE` resolves to trader/logs/ not env-specific logs — path fragile | Deferred (works in current single-env setup; address when multi-env deployed)
TRADER-L6 | `run_full_scan()` calls scan-only modules without documenting they don't execute trades | Deferred (add docstring clarification in next housekeeping pass)
TRADER-L7 | `run_polling_scan()` detects auto-exits but never executes them — WS backstop is print-only | Fixed (0bf4823) + QA-passed (now delegates to `_run_monitor_exit()`)
TRADER-V1 | Round-2 verification: touch_probability barrier_boost is tautology (always 1.5x) — opaque but correct | Deferred (functional; simplify to `barrier_boost = 1.5` with comment in next batch)
TRADER-V2 | Round-2 verification: annual contracts (365+ day) may still miss window if opened >365 days ago | Deferred (annual contracts rare in DEMO; revisit if annual trading enabled)

### STRAT Domain

STRAT-C1 | S4 spec in SPECS-BATCH-S.md describes adding per-module confidence gate that is already implemented — risk of double-application | Fixed (19d700c) + QA-passed (spec marked ALREADY IMPLEMENTED)
STRAT-C2 | `check_loss_circuit_breaker` defined in strategy.py but never wired into entry path — circuit breaker inert | Fixed (19d700c) + QA-passed (wired into ruppert_cycle.py scan loop)
STRAT-H1 | `should_enter()` test cases missing `open_position_value` field — all tests return false-negative | Fixed (19d700c) + QA-passed
STRAT-H2 | `edge_detector.py` volume-tier discounting happens after divergence gate — ordering bug, thin markets filter incorrectly | Fixed (19d700c) + QA-passed (discount applied before gate)
STRAT-H3 | `_city_has_trade_history` fails open on exception — inverted safety logic for conservative gate | Fixed (19d700c) + QA-passed (now fails closed)
STRAT-H4 | `should_add()` $50 max_allocation default invisible (not in config, not in summary) | Fixed (19d700c) + QA-passed (added to config + get_strategy_summary)
STRAT-H5 | `should_exit()` Rule 3 near-settlement hold blocks exit even on catastrophic reversal | Fixed (19d700c) + QA-passed (catastrophic override added before Rule 3)
STRAT-M1 | `KELLY_FRACTION = 0.16` module constant never used — misleading | Fixed (19d700c) + QA-passed (removed or linked to function)
STRAT-M2 | `optimizer.py` DAILY_CAP omits `CRYPTO_15M_DAILY_CAP_PCT` — utilization denominator wrong | Fixed (19d700c) + QA-passed
STRAT-M3 | NOAA fallback confidence 0.3 bypasses `MIN_ENSEMBLE_CONFIDENCE = 0.5` gate | Fixed (19d700c) + QA-passed (explicit NOAA min confidence gate added)
STRAT-M4 | `parse_temp_range_from_title` regex `[-–to]+` matches individual chars — wrong parse on edge-case titles | Fixed (19d700c) + QA-passed (regex uses alternation now)
STRAT-M5 | `min_viable` = `capital * 0.01` scales with capital creating vanishingly narrow viable window at scale | Fixed (19d700c) + QA-passed (decoupled: `max(5.0, cap * 0.10)`)
STRAT-M6 | `analyze_brier_score` depends on enriched trades but has no guard — silently returns wrong data on raw input | Deferred (documented: requires enriched trades; assert/guard in next batch)
STRAT-L1 | `get_strategy_summary()` has duplicate keys `pct_capital_cap` and `max_position_pct` | Fixed (19d700c) + QA-passed (duplicate removed)
STRAT-L2 | `should_enter` missing daily cap config check is evaluated twice in two locations | Fixed (19d700c) + QA-passed (consolidated to single check)
STRAT-L3 | `TICKER_TO_SERIES` is an identity-mapping dict — should be a set | Deferred (no functional bug; refactor when touching edge_detector.py)
STRAT-L4 | T-market soft prior multiplies confidence up to 1.0 cap — non-smooth cliff at high confidence | Deferred (intentional design; document if ever changed)
STRAT-L5 | `run_domain_experiments` prints misleading "Running experiments" for no-op placeholder | Fixed (19d700c) + QA-passed (output updated to [Placeholder])
STRAT-L6 | S2 spec (bet_direction case bug) marked CRITICAL but may not yet be applied to econ module | Fixed (c470f51) + QA-passed (confirmed applied in verification round)
STRAT-V1 | Round-2: `crypto_15m` MIN_EDGE not in `get_strategy_summary()` output | Fixed (c470f51) + QA-passed (added `min_edge_crypto_15m`)
STRAT-V2 | Round-2: `catastrophic_reversal_override_hold` reason string contains "hold" but branch exits | Fixed (c470f51) + QA-passed (renamed to `catastrophic_reversal_override`)
STRAT-V3 | Round-2: `should_enter` docstring missing optional `warning` return key | Fixed (c470f51) + QA-passed

### DS Domain (Data Scientist)

DS-H1 | `get_daily_exposure()` uses last-wins assignment for scale-in positions — deployed capital understated | Fixed (c2b8435) + QA-passed
DS-H2 | `get_daily_summary()` includes exit/settle records in `total_exposure` — exposure overstated in dashboard | Fixed (c2b8435) + QA-passed
DS-M1 | `check_tracker_drift()` key-type mismatch — (ticker,side) pair comparison broken — false drift reports | Fixed (c2b8435) + QA-passed
DS-M2 | `_remove_tracker_orphans()` receives ticker strings but tracker uses ticker::side keys — sibling-side deletion risk | Fixed (c2b8435) + QA-passed
DS-M3 | `synthesize_pnl_cache()` `events` parameter dead input — misleading API | Fixed (c2b8435) + QA-passed (comment added: parameter intentionally unused)
DS-M4 | `normalize_entry_price()` or-falsy bug — 0¢ YES entries incorrectly replaced by market_prob | Fixed (c2b8435) + QA-passed
DS-L1 | `all_today` dead variable in `run_post_scan_audit()` | Fixed (c2b8435) + QA-passed
DS-L2 | `check_decision_log_orphans()` only scans `decisions_15m.jsonl` — other modules not covered | Fixed (c2b8435) + QA-passed (now scans all 5 decision logs)
DS-L3 | Bare `except:` clauses in `logger.py` suppress all exceptions silently | Fixed (c2b8435) + QA-passed (changed to `except Exception:`)
DS-V1 | Round-2: `asyncio.get_event_loop()` deprecated in Python 3.12+ inside running coroutine (ws_feed.py) | Fixed (c470f51) + QA-passed (use `get_running_loop()`)
DS-V2 | Round-2: `fetch_smart_money.py` `sampled_count` incremented before position processing completes | Deferred (cosmetic; outer try/except handles; low blast radius)

### DA Domain (Data Analyst — specs owned by DS)

DA-H1 | WS keepalive not self-contained — auth headers not rebuilt on reconnect causing silent auth expiry | Fixed (852ef0c) + QA-passed
DA-H2 | `search_markets()` weather series hardcoded — diverges from `openmeteo_client.CITIES` | Fixed (c2b8435) + QA-passed (derives from CITIES)
DA-H3 | `_get_positions_raw()` no retry logic — single transient error drops all position data | Fixed (c2b8435) + QA-passed (3-attempt retry with exponential backoff)
DA-H4 | `ws_feed.py` ImportError on crypto_15m import marks window evaluated — masks real import failures | Fixed (c2b8435) + QA-passed
DA-M1 | `place_order()` no retry on transient errors | Fixed (852ef0c) + QA-passed
DA-M2 | False-alarm: `get_open_positions_from_logs()` scale-in aggregation was fixed in prior batch | False-alarm (SPEC-scalein-position-fix already applied to data_agent.py)
DA-M3 | `get_nws_current_obs()` rename needed + backward-compat alias | Fixed (c2b8435) + QA-passed
DA-M4 | `compute_station_bias()` off-by-one lookback window | Fixed (c2b8435) + QA-passed
DA-M5 | `fetch_smart_money.py` no retry on Polymarket API calls — single failure drops wallet data | Fixed (c2b8435) + QA-passed
DA-M6 | JSON guard missing in market cache writes | Fixed (852ef0c) + QA-passed
DA-M7 | Ensemble retry not implemented — single model failure drops multi-model forecast | Fixed (852ef0c) + QA-passed
DA-M8 | `_enrich_and_compute_depth` blocking I/O called in async context — should use executor | Fixed (c2b8435) + QA-passed
DA-L1 | `KalshiMarket` dataclass unused — remove to reduce confusion | Fixed (c2b8435) + QA-passed
DA-L2 | `place_order` client_order_id uses seconds timestamp, not milliseconds | Deferred (Kalshi API accepts both; verify with live test before changing)
DA-L3 | `MIN_PNL_EXCLUSIVE = 0.0` rename for clarity | Fixed (c2b8435) + QA-passed
DA-L4 | `ghcnd_client.py` uses deprecated `datetime.utcnow()` | Fixed (c2b8435) + QA-passed

### CEO Domain

CEO-C1 | `scipy` used in `main.py` `band_prob()` but missing from `requirements.txt` — breaks fresh environment | Fixed (a8770f3) + QA-passed
CEO-H1 | `run_weather_scan()` missing `traded_tickers` + `open_position_value` params — in-cycle dedup and cap checks broken | Fixed (a8770f3) + QA-passed
CEO-H2 | `_get_open_positions_summary()` only reads today's trades — multi-day positions invisible in brief | Fixed (a8770f3) + QA-passed (7-day lookback)
CEO-M1 | `run_position_check()` skips crypto/fed/geo positions — count misleading, no P&L for 2/3 of modules | Fixed (a8770f3) + QA-passed
CEO-M2 | `smart` mode comment mismatch — comment says one thing, code does another | Fixed (a8770f3) + QA-passed
CEO-M3 | `brief_generator.py` hardcodes 'PDT' timezone — wrong label 5 months/year | Fixed (a8770f3) + QA-passed (dynamic DST check)
CEO-L1 | Stale `Optional` import in `ruppert_cycle.py` | Fixed (a8770f3) + QA-passed
CEO-L2 | `main.py` bare imports order-dependent on ruppert_cycle sys.path setup — breaks standalone/test use | Fixed (a8770f3) + QA-passed
CEO-L3 | `run_exit_scan()` dead code with no callers — 150 lines of deprecated function | Fixed (a8770f3) + QA-passed (archived with RuntimeError stub)

### RES Domain (Researcher)

RES-H1 | Duplicate Task Scheduler entries: `Ruppert-ArchitectureResearch` and `Ruppert-Research-Weekly` both invoke weekly scan — double execution every Sunday | Fixed (0d83d20) + QA-passed (`Ruppert-ArchitectureResearch` deleted)
RES-H2 | `CA_RESTRICTED_SERIES` not filtered before API scan — 8 wasted calls per run + misleading report noise | Fixed (0d83d20) + QA-passed (pre-filter added to `scan_all_candidates()`)
RES-M1 | `scan_all_candidates()` no pre-filter for restricted series — restriction only applied post-scan | Fixed (0d83d20) + QA-passed (resolved by RES-H2 fix)
RES-M2 | `generate_signal_hypotheses` references `economics_client.py` which may not exist | Fixed (0d83d20) + QA-passed (comment updated with correct path)
RES-M3 | `KXISA` wrong series code for Initial Jobless Claims — likely ISA (UK savings) | Fixed (0d83d20) + QA-passed (corrected to `KXJOBLESSCLAIMS`)
RES-L1 | ROLE.md references wrong task name (`Ruppert-ArchitectureResearch` vs `Ruppert-Research-Weekly`) | Fixed (0d83d20) + QA-passed
RES-L2 | `get_ws_feed_script()` dead function — never called, misleading return value | Fixed (0d83d20) + QA-passed (removed)
RES-L3 | `ws_feed_watchdog.py` hardcoded Python path — fragile on env rebuild | Fixed (0d83d20) + QA-passed (uses `sys.executable`)
RES-L4 | `event_logger.py` `LOGS_DIR.mkdir()` at import time — filesystem side effect on import | Fixed (0d83d20) + QA-passed (moved inside `log_event()`)
RES-L5 | `__init__.py` eager imports expose hidden dependency chain | Fixed (0d83d20) + QA-passed (lazy imports)
RES-V1 | Round-2: `config_audit.py` still lists `Ruppert-ArchitectureResearch` in REQUIRED_TASKS — false FAIL on every audit run | Fixed (c470f51) + QA-passed (removed from both config_audit.py files)
RES-V2 | Round-2: Duplicate Task Scheduler registrations for `Ruppert-SettlementChecker` and `Ruppert-WS-Persistent` | Deferred (outside researcher domain; Ops to investigate duplicate registration cause)

---

## 2026-03-31 Evening Session Findings (~19:00–21:30 PDT)

### Infrastructure / Ops

OPS-E1 | `pnl_cache.json` deleted permanently — was source of stale P&L across restarts. Single canonical path now: raw logs → `compute_closed_pnl_from_logs()` → `get_capital()`. mtime-based in-process cache added. | Fixed (no commit — file deletion + code fix)

OPS-E2 | Brief generator showed $19K P&L — was missing `exit_correction` records in its own P&L calculation, diverging from `get_capital()`. Now uses canonical function. Module list made dynamic (no more hardcoded KNOWN_MODULES). | Fixed QA-passed

OPS-E3 | CB (Capital Bridge) `realized_pnl` field bug — records use `pnl`, not `realized_pnl`. CB was reading zero for all closed trades. Also added negative capital guard. | Fixed QA-passed

OPS-E4 | NO-side P&L formula bug in ws_feed — formula incorrect for NO-side settlement calculation. ws_feed restarted to load fix. 3 correction records applied to affected historical entries. | Fixed QA-passed

OPS-E5 | Geo module confirmed dead — GDELT timeout on all calls. Replacement stack identified (TheNewsAPI + structured keyword queries). Not yet built. | Deferred — replacement stack scoped

### New Infrastructure

NEW-E1 | `environments/demo/terminal_signal_logger.py` — shadow logger fires at T-90s before close. Logs TFI/OBI/MACD/OI signal vs entry signal to `logs/terminal_signals/YYYY-MM-DD.jsonl`. 36 records collected evening of 3/31. | Live, collecting

NEW-E2 | `environments/demo/intra_window_logger.py` — logs yes_bid/ask every 60s per open crypto_15m_dir position to `logs/price_series/{ticker}.jsonl`. For future backtest price series reconstruction. | Live, collecting

NEW-E3 | `agents/ruppert/data_analyst/polymarket_client.py` — shared Polymarket signal client. Functions: `get_crypto_consensus()`, `get_geo_signals()`, `get_wallet_positions()`, `get_smart_money_signal()`, `get_markets_by_keyword()`. Shadow mode only — NOT wired into any module. | Shadow — 7-day collection in progress

NEW-E4 | `scripts/data_toolkit.py` — agent analysis CLI. `python scripts/data_toolkit.py winrate --module crypto_15m_dir --days 7 --by asset,hour,side`. Returns in <3s. All agents should use this instead of reading raw files. | Live

NEW-E5 | Sports odds collector fixed — Kalshi `series_ticker` query corrected, `bird` full path fixed. Now collecting 11 NBA + 33 MLB games daily. `/api/sports` endpoint + UI dashboard card showing Vegas vs Kalshi gap. | Live

NEW-E6 | `bird` CLI confirmed as sole X search tool — `xurl` removed. TheNewsAPI key saved to `secrets/thenewsapi_config.json`. | Confirmed

### Strategist Analysis

STRAT-E1 | Crypto win rate analysis (296 trades, Mar 30-31): NO side 87.6% WR vs YES side 56.3% — major asymmetry. YES side is weak flank. | Finding logged — see strategist MEMORY.md

STRAT-E2 | 09:00 EDT dead zone: 38.9% WR (18 trades) — candidate for skip gate. | Pending — needs spec + David approval before wiring

STRAT-E3 | Entry price sweet spot: 35–65c = 80–82% WR; below 35c = 57–65%. | Finding logged — Proposal A (payoff-aware NO scaling) already covers this partially

STRAT-E4 | Asset WRs: ETH 79.5%, XRP 74.7%, DOGE 75.7%, BTC 70.3%. | Finding logged

### Agent MEMORY.md Updates
- `agents/ruppert/data_analyst/MEMORY.md` — appended: Polymarket client, sports collector, TheNewsAPI, data_toolkit, capital
- `agents/ruppert/data_scientist/MEMORY.md` — appended: pnl_cache deletion, new log files, NO-side fix, data_toolkit, capital
- `agents/ruppert/researcher/MEMORY.md` — appended: new data sources, sports odds, data_toolkit, capital
- `agents/ruppert/strategist/MEMORY.md` — appended: win rate analysis, Polymarket decision, 09:00 dead zone, data_toolkit, capital
- `agents/ruppert/trader/MEMORY.md` — appended: pnl_cache deletion, CB fixes, NO-side formula, brief generator, capital

### Capital at EOD: ~$13,146

---

## 2026-03-31 Afternoon Session Findings

### Infrastructure / Ops

OPS-C1 | `Ruppert-SettlementChecker` misconfigured as one-shot — no repetition interval. 15m contracts expiring every 15 min were going unsettled for hours | Fixed (recreated via XML with PT30M repetition, 24/7) + config_audit updated to verify trigger intervals + Phase 1c Scheduler Audit added to audit-workflow.md + 23 setup XMLs + register_all_tasks.ps1 created

OPS-C2 | Double-entry race condition: `position_monitor.py` Task Scheduler job opened second WS connection, both fired `evaluate_crypto_15m_entry` on same market simultaneously. Threading lock doesn't protect cross-process | Fixed (2d98328 — disabled Ruppert-PostTrade-Monitor, retired WS mode in position_monitor.py, extracted utils.py, inlined hourly eval into ws_feed.py) QA-passed 23/23

OPS-C3 | `pnl_correction.py` not idempotent — ran twice (11:49AM + 15:56PM), wrote 41 corrections twice each, produced impossible negative capital (-$7,472) | Fixed (7e59848 — idempotency check added) + DS removed 41 duplicate records from trade logs. True capital confirmed ~$9,823.

### Trader Domain

TRADER-P1-A | NO-side exit P&L formula wrong: `(entry+exit-100)*c/100` instead of `(exit-entry)*c/100`. Affected all 70pct_gain_no exits. $2,428 overstatement | Fixed (7f9d54a) QA-passed

TRADER-P1-B | `post_trade_monitor.py` exit thresholds hardcoded at 0.70 — not reading `config.EXIT_GAIN_PCT` | Fixed (bec298f) QA-passed

TRADER-P3-A | Atomic writes missing in `post_trade_monitor.py` state files | Fixed — 3 write blocks converted to .tmp→replace pattern QA-passed 23/23

### Strategist Domain

STRAT-P1-A | 45+ hardcoded values across strategy.py, crypto_15m.py, crypto_1d.py, crypto_long_horizon.py, edge_detector.py — Optimizer cannot tune | Fixed (bec298f, a298960 — 45 new config keys added) QA-passed

STRAT-P1-B | `edge_detector.py` NOAA client import silently fails when run from agents path — NOAA fallback always disabled with no warning | Fixed (7f9d54a — absolute path injection + warning log) QA-passed

### Data Scientist Domain

DS-P1-A | Weather module: 0W/24L, NOAA systematically overconfident (21 trades entered at 1¢ lost). Average claimed edge 0.73, actual win rate 7% | Deferred — data collection continuing, Optimizer review after 30+ trades

DS-P1-B | `crypto_15m` (old label) 25% win rate was real underperformer — confirmed as mix of phantom wins + double-entries from race condition. Resolved by OPS-C2 + correction dedup.

DS-P2-A | 5 double-close records from taxonomy migration (~$565 double-counted) | Fixed — marked _invalid in trade logs (2d541f4)

DS-P3-A | `pnl_cache.json` stale, not updated after corrections | Annotated stale:true — dashboard ignores it. Deprecate in next cleanup sprint.

### Module Performance Summary (2026-03-31, corrected)
- crypto_15m_dir (combined): 190W/118L, 62% WR, +$6,736 — only profitable module
- crypto (hourly bands): 4W/59L, 6% WR, -$2,907 — broken signal
- weather: 0W/24L, 0% WR, -$2,071 — NOAA overconfident
- weather_band: 4W/33L, 11% WR, -$2,270
- True capital: ~$9,823
