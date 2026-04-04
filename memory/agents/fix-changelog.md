# Ruppert Fix Changelog
_Every fix must be logged here with issue ID, summary, and commit hash_

---

## Format

```
## Sprint X — YYYY-MM-DD

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-XXX | ... | ... | abc1234 |
```

---

## Batch 5 — Settlement Naive Datetime, P&L Divergence, date.today() Sweep, CRYPTO_15M_SERIES (2026-04-04)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| B5-DS-1 | settlement_checker naive datetime | Removed .split('+')[0]; naive-tz fallback; datetime.now(timezone.utc) | 286268c |
| B5-DS-2 | /api/state vs /api/pnl diverge | Shared _build_close_records() helper; SUM accumulation for multi-leg | 286268c |
| B5-DS-3 | date.today() sweep (22 sites) | data_agent (14), api.py (6), crypto_15m (2), utils.py (1) — all replaced with PDT-aware | 286268c |
| B5-DS-3i | load_traded_tickers() dedup failure | utils.py _today_pdt() added; load_traded_tickers uses it — dedup now correct at UTC midnight | 286268c |
| B5-DS-4 | CRYPTO_15M_SERIES duplicate definitions | Canonical in utils.py; removed from crypto_15m + position_monitor; both import from utils | 286268c |

---

## Batch 4 — WS TZ, Window Guard, Retry Logic, Persistent Mode Cleanup, KXSOL15M, R9 Macro Filter (2026-04-04)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| B4-TRD-1 | WS heartbeat naive TZ | Both ws_feed + watchdog now use datetime.now(timezone.utc) | 24682b6 |
| B4-TRD-2 | _prune_window_guard strips tzinfo | Removed .replace(tzinfo=None); UTC-aware ISO strings throughout | 24682b6 |
| B4-TRD-3 | Window marked evaluated before eval | Deferred write until after eval; _window_retry_after dict + one retry on REST None | 24682b6 |
| B4-TRD-4 | --persistent crashes (retired function) | Deleted run_persistent_ws_mode(); --persistent now calls ws_feed.run() + sys.exit(1) | 24682b6 |
| B4-TRD-5 | KXSOL15M missing from position_monitor | Added to CRYPTO_15M_SERIES; crypto_15m.py hardcoded tuple replaced with constant ref | 24682b6 |
| B4-STR-1 | R9 macro filter dead code | Implemented has_macro_event_within() in utils.py; 40-entry 2026 calendar; conditional import in crypto_15m | 24682b6 |

---

## Batch 3 — NO-side Price, dry_run Tag, Exposure Error Handling, CB Locking, Daily Stop Gate (2026-04-04)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| B3-DS-1 | normalize_entry_price NO-side fallback | Side-aware fallback: NO uses (1-market_prob)*100, YES uses market_prob*100 | bbab631 |
| B3-DS-2 | post_trade_monitor hardcoded dry_run: True | Replaced with not _is_live_enabled() + added env_config import | bbab631 |
| B3-DS-3 | get_daily_exposure() swallows errors | capital.py raises; 11 call sites in 7 files now log+skip instead of 0.0 fallback | bbab631 |
| B3-STR-1 | CB get/set_module_state bypass file lock | Both routed through _rw_locked() using mutable-cell pattern | bbab631 |
| B3-STR-2 | loss_today $0 display diagnostic | Added logger.info() in check_global_net_loss() to surface count + pnl sum | bbab631 |
| B3-TRD-1 | Daily stop-loss fires for NO positions | Added and side == 'yes' gate to outer if; comment explains NO-side exclusion | bbab631 |

---

## Batch 2 — PDT Date Fixes + Dead Code Cleanup (2026-04-04)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| B2-STR-1 | circuit_breaker date.today() at line 263 | Replaced with _today_pdt() — CB now reads correct PDT trade file all day | 538b25d |
| B2-STR-2 | crypto_15m date.today() at lines 155+1232 | Replaced with circuit_breaker._today_pdt() — daily wager resets at PDT midnight | 538b25d |
| B2-DS-1 | settlement_checker date.today() at lines 237-238 | Replaced with _pdt_today() imported from logger — settle records stamped correctly | 538b25d |
| B2-DS-2 | position_tracker date.today() at line 884 | Replaced with date.fromisoformat(_today_pdt()) — idempotency guard reads correct file | 538b25d |
| B2-DS-3 | push_alert NameError in dashboard/api.py | Removed dead push_alert block (lines 63-68) — _logger.error() sufficient | 538b25d |

---

## Sprint P2+P3-2 — Logger, WS Feed + Code Hygiene (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-109 | Logger fingerprint sets memory leak | LRU deque+set (maxlen=2000) for both caches; no mid-session wipe | b19e548 |
| ISSUE-124 | win_prob dropped by build_trade_entry | Added `win_prob` field to entry schema | b19e548 |
| ISSUE-125 | Inconsistent timestamp formats | All 3 logger.py sites now use `datetime.now(timezone.utc).isoformat()` | b19e548 |
| ISSUE-122 | Capital threshold inconsistency $100 vs $1000 | `MIN_CAPITAL_ALERT=1000.0` in config; both audit files use it | b19e548 |
| ISSUE-115 | poly_nudge dead code in crypto_15m | Removed 9-line shadow computation block (was unconditionally zeroed) | b19e548 |
| ISSUE-128 | Background create_task not tracked in ws_feed | `_bg_tasks` set + `_spawn()` helper; 3 untracked calls fixed; cancellation in finally | b19e548 |

---

## Sprint P2+P3-1 — Config, Risk + Audit Tools (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-036 | data_integrity_check wrong path | Now reads `logs/trades/` not `logs/` | ae558f1 |
| ISSUE-037 | code_audit scans audit/ not demo/ | ROOT now points to `demo/` | ae558f1 |
| ISSUE-038 | qa_self_test hardcoded Windows path | Replaced with `_WORKSPACE_ROOT` relative path | ae558f1 |
| ISSUE-100 | deprecated file check wrong dir | Now scans `_DEMO_DIR` not `audit/` | ae558f1 |
| ISSUE-119 | Missing module daily cap constants | Added `DEFAULT_MODULE_DAILY_CAP_PCT=0.05` + 13 per-module constants; strategy.py safe fallback | ae558f1 |
| ISSUE-090 | 15m backstop disabled + no enforcement | `CRYPTO_15M_DIR_DAILY_BACKSTOP_ENABLED=True`; enforcement block added; caller passes aggregate wager | ae558f1 |

---

## Sprint P1-6 — Daily Module Pre-Re-Enable (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-016 | Band date filter blocks same-day contracts | `crypto_band_daily.py`: replaced `ct.date() <= today` with `ct <= datetime.now(UTC)` | d161a89 |
| ISSUE-017 | NO-side order wrong fill price | `trader.py`: `no_ask or (100-yes_price)` fallback. `crypto_threshold_daily.py`: `no_ask` added to `trade_opp` (actual bug). `crypto_band_daily.py`: `no_ask` added for robustness | d161a89 |
| ISSUE-057 | 15m Polymarket signal in daily module | `crypto_threshold_daily.py` `compute_s5_polymarket()`: local `get_crypto_consensus` import removed; now calls `get_crypto_daily_consensus` | d161a89 |
| ISSUE-089 | Polymarket yes_price semantic mismatch | `compute_s5_polymarket()`: None guard + `[0.25,0.75]` bounds gate; far-from-money strikes suppressed | d161a89 |
| ISSUE-053 | Daily cap race condition | Both daily files: portalocker import added. `crypto_band_daily`: `_execute_band_trades()` extracted + lock wraps helper call. `crypto_threshold_daily`: lock wraps `execute_opportunity()` | d161a89 |

---

## Sprint P1-5 — Exit Records + Monitoring (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-108 | Shadow log failures silent | `crypto_15m.py`, `crypto_band_daily.py`: bare `except: pass` → `logger.warning`; `ws_feed.py`: 2× debug→warning | 8a32658 |
| ISSUE-062 | Stale spot price in edge calc | `ws_feed.py`: TODO comment + documented limitation in `evaluate_crypto_entry()` | 8a32658 |
| ISSUE-121 | health check alerts go to log not pending_alerts.json | `data_health_check.py`: `_push_alert()` now writes JSON array to `logs/truth/pending_alerts.json` | 8a32658 |
| ISSUE-098 | NO-side win P&L overstated ~2.4× | `position_monitor.py`: `exit_price=99` → `100`, P&L formula fixed in both YES-win and NO-win paths | 8a32658 |
| ISSUE-074 | Exits missing edge/confidence | `post_trade_monitor.py`: `exit_opp['edge']` and `exit_opp['confidence']` now forwarded from position | 8a32658 |
| ISSUE-079 | check_alert_only_position broken entry_price | `post_trade_monitor.py`: inline broken logic → `normalize_entry_price(pos)` | 8a32658 |
| ISSUE-045 | Legacy positions wrong stop tier default | `config.py`: `STOP_LEGACY_ENTRY_SECS_DEFAULT=120` added; `position_tracker.py`: getattr fallback | 8a32658 |
| ISSUE-023 | position_tracker exits bypass log_trade | Confirmed resolved in Sprint 3; clarifying comment added to import | 8a32658 |
| CLEANUP-063 | Dead pnl_by_day/points code in api.py | `dashboard/api.py`: pnl_by_day accumulation, points build block, and `"points": points` all removed | 8a32658 |

---

## Sprint P1-4 — Dashboard Fixes (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-018 | /api/account NameError | `dashboard/api.py`: replaced `AUTO_SOURCES`/`MANUAL_SOURCES` with `_is_auto()`/`_is_manual()` | d02db9f |
| ISSUE-019 | /api/positions/active UnboundLocalError | `dashboard/api.py`: `side` assignment moved to first statement in loop body | d02db9f |
| ISSUE-063 | P&L chart hardcoded data | `dashboard/api.py`: `pnl_by_day` accumulated from actual trade logs; hardcoded point removed | d02db9f |
| ISSUE-064 | BOT_SRC missing ws_* sources | `dashboard/api.py`: `_is_auto()`/`_is_manual()` promoted to module scope; covers ws_* and crypto_15m | d02db9f |
| ISSUE-065 | Settled positions appear open | `dashboard/api.py`: `exited` set includes both exit+settle; `exit_records` dict is exit-only | d02db9f |
| ISSUE-066 | closed_win_rate uses ticker dedup | `dashboard/api.py`: `_close_records_by_id` keyed on trade_id with (ticker,side) fallback | d02db9f |
| ISSUE-072 | 19 silent exception swallows | `dashboard/api.py`: all bare except → except Exception; _cache_reload_loop() guarded; groups A/B/C logged correctly | d02db9f |

---

## Sprint P1-3 — Analytics + Calibration Pipeline (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-005 | Optimizer sees zero trades (wrong glob path) | `optimizer.py`: `LOGS_DIR.glob()` → `(LOGS_DIR / "trades").glob()` | 2e870f6 |
| ISSUE-041 | Optimizer double-counts closed trades | `optimizer.py`: filter `action in ('buy','open')` before summing | 2e870f6 |
| ISSUE-004 | brier_tracker hardcoded path | `brier_tracker.py`: module-level constants removed; `_get_brier_paths()` lazy helper at function scope | 1ebee0a |
| ISSUE-101 | brier_tracker duplicate scoring | `brier_tracker.py`: `(ticker, ts[:10])` dedup on both sides; null-outcome blocks re-scoring | 1ebee0a |
| ISSUE-103 | Overnight positions write null predicted_prob | `prediction_scorer.py`: `(ticker, side)` fallback index; null on no-match; warning logs | 9a1d78e |
| ISSUE-046 | exit_timestamp field doesn't exist | `optimizer.py`: full fix with buy/exit join, `buy_index` param, `count = len(pnls)` | 9a1d78e |

---

## Sprint P1-2 — Settlement + Capital Accuracy (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-026 | Settlement exit_price=99 understates wins | `settlement_checker.py` + `post_trade_monitor.py`: exit_price 99→100 in win branches | d3584bf |
| ISSUE-027 | Settlement dry-run P&L formula asymmetric | Both files: win formula `(100-entry_price)*contracts/100`; loss `-(entry_price*contracts/100)` | d3584bf |
| ISSUE-110 | Settlement no retry on API error | `settlement_checker.py` + `post_trade_monitor.py`: 3-attempt retry, 1s/2s delays | d3584bf |
| ISSUE-030 | pnl field missing from cycle/monitor exits | `ruppert_cycle.py`: `pnl` added to opp dict; `post_trade_monitor.py`: `exit_opp['pnl'] = exit_pnl` after computation | 641e2d3 |
| ISSUE-102 | KXXRPD/KXDOGED missing from ticker map | `data_agent.py`: TICKER_MODULE_MAP + _cap_map both updated with xrp/doge threshold daily entries | 641e2d3 |

---

## Sprint P1-1 — Signal Integrity (2026-04-03)

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-129 | Near-zero OI delta z-score spike | `crypto_15m.py`: `prev_oi == 0` → `prev_oi < 1e-6` guard in `fetch_oi_conviction()` | b171271 |
| ISSUE-104 | _module_cap_missing uninitialized | `strategy.py`: `_module_cap_missing = False` before `if module is not None:` block | b171271 |
| ISSUE-069 | crypto_15m fallback to Phase 1 weights silent | `crypto_15m.py`: `hasattr()` check + WARNING log naming missing keys | c03e5b1 |
| ISSUE-114 | Signal weights not asserted to sum 1.0 | `crypto_15m.py`: `raise ValueError` (not assert) if weights don't sum to 1.0 ± 1e-6 | c03e5b1 |
| ISSUE-116 | Polymarket ETH alias matches EtherFi/Ethena | `polymarket_client.py`: word-boundary regex in `_asset_in_title()` + `get_smart_money_signal()` | c03e5b1 |
| ISSUE-096 | WS reconnect flat 5s retry | `ws_feed.py`: exponential backoff 5→10→20→60s cap, both timeout + exception paths | a441a6d |
| ISSUE-032 | Smart money wallets wrong path | `crypto_client.py`: `_WALLETS_FILE` → `env_config.get_paths()['logs']`; warning on empty/missing | a441a6d |
| ISSUE-105 | Window cap overcharged on trim | `crypto_15m.py`: `actual_spend = contracts × price/100` computed inside lock; reservation/rollback/log all use actual_spend | a441a6d |

---

## P0 Mini-Sprint — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-034 | position_monitor WS_ENABLED crash | `position_monitor.py`: WS_ENABLED = True → False; WS path unreachable, polling guaranteed | 07d3eba |
| ISSUE-117 | vol_ratio=0 fires full Kelly | `strategy.py`: `if vol_ratio <= 0: return 0.0` guard before Kelly; shrinkage unconditional after | 07d3eba |
| ISSUE-007 | compute_closed_pnl_from_logs silent $0 | `logger.py`: raises RuntimeError + cache invalidation on failure; `capital.py`: get_capital() + get_pnl() propagate RuntimeError instead of swallowing | c69dee2 |
| ISSUE-006 | NO-side Brier scores inverted | `prediction_scorer.py`: outcome + predicted_prob flipped for NO-side before Brier; edge untouched; None handled | 7fb4d19 |
| ISSUE-040 | Optimizer domain name mismatch | `optimizer.py`: DOMAIN_THRESHOLD 30→10; get_domain_trade_counts() reads domain field first; enrich_trades() uses classify_module() | 058589b |

---

## Sprint 5 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-076 | CB TOCTOU race | `circuit_breaker.py`: `_rw_locked()` helper with portalocker.LOCK_EX; wraps `increment_consecutive_losses()`, `reset_consecutive_losses()`, `update_global_state()`; cold-start FileNotFoundError → w+ fallback | d0f4436 |
| ISSUE-047 | CB trip logging | `circuit_breaker.py`: WARNING log when consecutive losses hit threshold, naming module + count + threshold | d0f4436 |
| ISSUE-044 | Timezone: date.today() in trade records | `ws_feed.py` + `position_tracker.py`: `_today_pdt()` helper added; `str(date.today())` replaced in all trade record `date` fields | b376074 |
| ISSUE-043 | EXIT_GAIN_PCT silent fallback | `position_tracker.py`: `getattr(config, 'EXIT_GAIN_PCT', 0.70)` → raises `ImportError` if key missing from config | b376074 |
| ISSUE-042 | NO-side entry price flip | `position_tracker.py`: removed `100 - entry_price` flip from `add_position()`; removed legacy migration block from `_load()`; `side = key[1]` added to `check_exits()` loop; Design D stops gated to `side == 'yes'`; stale comments cleaned | b376074 |
| ISSUE-042 Part B | NO-side P&L data correction | DS inserted 125 `exit_correction` records into trades_2026-04-02/03.jsonl; CB global state refreshed | (data correction only) |

---

## Sprint 1 DS Patches — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-015 | Wrong ImportError log message | `ws_feed.py`: corrected log in `_safe_eval_15m()` — window IS marked, REST fallback also blocked | 2d26cb8 |
| ISSUE-070 | 10× exposure warning | `ws_feed.py`: added comment documenting cap jump from 7% → 70% in `evaluate_crypto_entry()` | 2d26cb8 |
| ISSUE-014 | Log atomicity warning | `ws_feed.py`: added WARNING comment in `_safe_eval_hourly()` re: no file locking in logger.py | 2d26cb8 |

## Sprint 1 Batch 2 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-002 | `_exits_in_flight` race | `position_tracker.py`: added `_exits_lock = asyncio.Lock()`; atomic check+set in `execute_exit()` | 664d81e |
| ISSUE-003 | Exit failure infinite retry | `position_tracker.py`: 3-strike `_exit_failures` counter; abandon + `push_alert` (try/except wrapped) after 3 | 664d81e |
| ISSUE-107 | Stale pos refs after await | `position_tracker.py`: snapshot `entry_price`, `quantity`, `module`, `title`, `size_dollars` to locals before first await | 664d81e |

**DS-NEW-001 (patched same session):** Abandoned positions (ISSUE-003 3-strike path) now write a synthetic `action='exit'`, `action_detail='ABANDONED after 3 exit failures'` JSONL record before remove_position(). Commit: 4a92830. DS-verified ✅

## Sprint 4 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-001 | KXSOL15M added to WS series | `ws_feed.py`: 'KXSOL15M' added to CRYPTO_15M_SERIES | e051551 |
| ISSUE-087 | OBI EWM direction corrected | `crypto_15m.py`: EWM seeds oldest, iterates forward; reversed() removed; one-time logger.info on correction | e051551 |
| ISSUE-035 | Coinbase fail-open blocked | `crypto_15m.py`: `coinbase_price is None` → COINBASE_UNAVAILABLE block; fail-open pattern removed | e051551 |
| ISSUE-073 | Exception swallows fixed | `ws_feed.py`: `_safe_eval_15m()` ERROR + push_alert; `crypto_15m.py`: fetch_price_delta + fetch_okx_price warnings added | e051551 |

## Sprint 3 Batch 2 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-033 | position_monitor fanout on exit | `position_monitor.py`: inline exit in `run_polling_scan()`, no `run_monitor()` call; `place_order(action='sell')`; `remove_position()` called | 2c078c4 |
| ISSUE-094 | position_monitor no CB check | `position_monitor.py`: CB gate + full `_WS_MODULE_MAP_PM` added to `evaluate_crypto_entry()`; `opp['module'] = _ws_module` | 2c078c4 |

## Sprint 3 Batch 1 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-077 | Multi-process JSONL writes | `logger.py`: `_append_jsonl()` with portalocker + fallback warning; used by all write paths in position_tracker + settlement_checker | 019d14d |
| ISSUE-023 | Exit records bypass log_trade() | `logger.py`: `log_exit()` + `log_settle()` wrappers + `_logged_exit_fingerprints` + `build_trade_entry(**extra_fields)`; `position_tracker.py`: all exit/settle writes routed through wrappers | 019d14d |
| ISSUE-025 | Double-settlement race | `position_tracker.py`: `_settle_record_exists()` (today+yesterday) guard in `check_expired_positions()` | 019d14d |
| ISSUE-028 | Phantom settlement from high bid | `settlement_checker.py`: removed unsafe bid-only inference; finalized+ambiguous bid now skips with warning | 019d14d |

## Sprint 2 Batch 3 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-055 | Settled positions resurrected | `data_agent.py`: `_has_close_record()` guard inside `_register_missing_positions()` before `add_position()` | 45d3a9b |
| ISSUE-056 | `_cleanup_duplicates()` deletes exit records | `data_agent.py`: `_PROTECTED_ACTIONS` set; streaming pattern preserved; `log_activity()` on preserved duplicate | 45d3a9b |
| ISSUE-051 | Capital fallback silent | `capital.py`: `send_telegram()` + `log_activity()` on fallback, 4-hour dedup file, 500-char error cap | 45d3a9b |

## Sprint 2 Batch 2 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-029/099 | Failed orders phantom capital | `trader.py`: `opportunity['action']='failed_order'`, `size_dollars=0.0` on failure path; `logger.py`: explicit `failed_order` exclusion in `get_daily_exposure()` | d286b28 |
| ISSUE-078 | Trader init crash on API error | `trader.py`: `get_balance()` + `refresh_balance()` wrapped in try/except with `capital.get_capital()` fallback | d286b28 |

## Sprint 2 Batch 1 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-024 | state.json atomic write | `ruppert_cycle.py`: write-to-tmp + `Path.replace()` in `save_state()` | ff9be04 |
| ISSUE-052 | Process lock on scan cycles | `ruppert_cycle.py`: `_acquire_cycle_lock()` + `_release_cycle_lock()` with PID file, stale detection, try/finally | ff9be04 |
| ISSUE-031 | Cycle exits don't remove from tracker | `ruppert_cycle.py`: `remove_position()` called in both paths in `run_position_check()`, before `release_exit_lock()` | ff9be04 |

## Sprint 1 Batch 1 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-070 | WS feed 7% cap → 70% | `ws_feed.py`: replaced `CRYPTO_DAILY_CAP_PCT` with `DAILY_CAP_RATIO` in `evaluate_crypto_entry()` | ceba350 |
| ISSUE-015 | WS eval dedup | `ws_feed.py`: added `_window_eval_lock = asyncio.Lock()`; atomic check+set in `_safe_eval_15m()` before eval; deleted post-eval write block | ceba350 |
| ISSUE-060 | WS + REST fallback dedup | `ws_feed.py`: same `_window_eval_lock` in `_check_and_fire_fallback()`; guard written inside lock before eval | ceba350 |
| ISSUE-014 | Blocking I/O in async handler | `ws_feed.py`: `evaluate_crypto_entry()` wrapped in `run_in_executor` inside `_safe_eval_hourly()` | ceba350 |
| ISSUE-061 | `_rest_refresh_stale` blocks event loop | `ws_feed.py`: `get_market()` calls wrapped in `run_in_executor` per ticker | ceba350 |
| ISSUE-049 | Watchdog spawns duplicate ws_feed | `ws_feed_watchdog.py`: added `kill_existing_ws_feed()` (PID from heartbeat, psutil/taskkill); called before every spawn | ceba350 |

## Sprint 1 Batch 2 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-002 | `_exits_in_flight` race → double-exits | `position_tracker.py`: added `_exits_lock = asyncio.Lock()`; check+add wrapped in `async with _exits_lock` in `execute_exit()` | 664d81e |
| ISSUE-003 | Exit failure → infinite retry | `position_tracker.py`: `_exit_failures` counter on `pos`; abandon after 3 failures with `push_alert` (in try/except) + `remove_position()` | 664d81e |
| ISSUE-107 | `_tracked` mutated during await → stale refs | `position_tracker.py`: snapshot `entry_price`, `quantity`, `module`, `title`, `size_dollars` to locals before lock release in `execute_exit()` | 664d81e |

## Sprint 1 DS Patches — 2026-04-03

| Patch | Related Issue | Summary | Commit |
|-------|--------------|---------|--------|
| Patch A | ISSUE-070 | `ws_feed.py`: comment warning that DAILY_CAP_RATIO = 10× old cap — monitor first 3 live days | 2d26cb8 |
| Patch B | ISSUE-015 | `ws_feed.py`: fixed lying ImportError log ("NOT marked" → "IS marked"); guard IS set before import attempt | 2d26cb8 |
| Patch C | ISSUE-014 | `ws_feed.py`: comment warning that log_trade() runs in thread executor — not file-locked; must address before LIVE | 2d26cb8 |

## Sprint 1 DS-NEW-001 — 2026-04-03

| ID | File | Summary | Commit |
|----|------|---------|--------|
| DS-NEW-001 | position_tracker.py | Abandoned positions (3-strike) now write a JSONL exit record with `action_detail='ABANDONED'` and `pnl=-(cost)`. Uses `_abandon_log_path` (inline, not reusing later-defined `log_path`). Wrapped in try/except. Fixes audit trail gap found by DS. | 4a92830 |

## Sprint 1 P1 Fixes — 2026-04-04

| ID | File | Summary | Commit |
|----|------|---------|--------|
| P1-1 | position_tracker.py | Unified exit locking: `acquire_exit_lock`/`release_exit_lock` added to execute_exit — dedup-guard path + finally block both release | 08931ae |
| P1-2 | post_trade_monitor.py | Settlement checker write now uses `_append_jsonl()` (portalocker-protected) instead of raw open()+write() | 08931ae |

## Sprint 2 P2 Fixes — 2026-04-04

| ID | File | Summary | Commit |
|----|------|---------|--------|
| P2-CB-1 | circuit_breaker.py | CB threshold lookup now uses per-module prefix mapping instead of wrong fallback chain | 3339846 |
| P2-CB-2 | strategy.py | CB check added to `should_enter()` — defensive guard for new modules that bypass individual CB calls | 3339846 |
| P2-DM-1 | crypto_band_daily.py | Disable guard added (`BAND_DAILY_ENABLED` config flag) | 3339846 |
| P2-DM-2 | crypto_threshold_daily.py | Disable guard added (`THRESHOLD_DAILY_ENABLED` config flag) | 3339846 |
| P2-PTM | post_trade_monitor.py | Additional hardening from Sprint 2 review | 3339846 |
| P2-CFG | config.py | New enable/disable flags for daily modules | 3339846 |

**Pipeline note:** ceba350 also includes unspecced `start_ws_feed()` changes in `ws_feed_watchdog.py` (PYTHONPATH + module path fix, labeled "P1-2 fix"). These were not in Sprint 1 spec but were reviewed and confirmed beneficial by DS audit. No rollback needed.

---

## 2026-04-04 Sprints (Post-cleanup P1/P2 fixes)

### Sprint 1-2026-04-04 — P1: Exit Safety (08931ae)
| ID | File | Fix | Commit |
|----|------|-----|--------|
| P1-EXIT-1 | position_tracker.py | execute_exit() now acquires file-based lock via acquire_exit_lock() before proceeding — coordinates with post_trade_monitor to prevent double-exit P&L corruption | 08931ae |
| P1-EXIT-2 | post_trade_monitor.py | check_settlements() now uses _append_jsonl() for JSONL writes (was raw open() without locking) | 08931ae |

### Sprint 2-2026-04-04 — P2: Circuit Breaker + Daily Module Guards (3339846)
| ID | File | Fix | Commit |
|----|------|-----|--------|
| P2-CB-3 | circuit_breaker.py | increment_consecutive_losses(): N resolved by module prefix (crypto_dir_15m_* → N=3, crypto_band/threshold_daily_* → N=5) instead of fallback chain that always picked 15m N | 3339846 |
| P2-CB-4 | post_trade_monitor.py | update_1h_circuit_breaker(): same prefix-based N resolution for settlement logging | 3339846 |
| P2-CB-5 | strategy.py | CB backstop gate added to should_enter() — defensive layer catches modules that forget primary CB check | 3339846 |
| P2-DM-3 | config.py | CRYPTO_BAND_DAILY_ENABLED=False, CRYPTO_THRESHOLD_DAILY_ENABLED=False added | 3339846 |
| P2-DM-4 | crypto_band_daily.py | RuntimeError guard in run_crypto_scan() if CRYPTO_BAND_DAILY_ENABLED=False | 3339846 |
| P2-DM-5 | crypto_threshold_daily.py | RuntimeError guard in evaluate_crypto_1d_entry() if CRYPTO_THRESHOLD_DAILY_ENABLED=False | 3339846 |

### Sprint 3-2026-04-04 — P2: Runtime Correctness (7a2dc76)
| ID | File | Fix | Commit |
|----|------|-----|--------|
| P2-RT-1 | config.py | load_config() now has try/except with FATAL message on FileNotFoundError/JSONDecodeError | 7a2dc76 |
| P2-RT-2 | config.py | _MODE_FILE now uses same three-tier workspace shim resolution as SECRETS_DIR | 7a2dc76 |
| P2-RT-3 | position_tracker.py | GIL safety comment added to _persist() — sync functions, no lock needed under CPython | 7a2dc76 |
| P2-RT-4 | ws_feed.py | Comment added: check_expired_positions() pauses during WS reconnect; post_trade_monitor is backstop | 7a2dc76 |

### Sprint 4-2026-04-04 — P2: Display + Reporting (2962743)
| ID | File | Fix | Commit |
|----|------|-----|--------|
| P2-DP-1 | ruppert_cycle.py | run_position_check() P&L now uses bid price (not ask) with is-not-None fallback to ask | 2962743 |
| P2-DP-2 | ruppert_cycle.py | run_position_check() docstring corrected — display-only, not auto-exit | 2962743 |
| P2-DP-3 | ruppert_cycle.py | _get_local_tz() now uses zoneinfo.ZoneInfo('America/Los_Angeles') (was hardcoded UTC-7/-8) | 2962743 |
| P2-DP-4 | ruppert_cycle.py | Dead 'smart' mode fully removed from dispatch, docstring, audit gates | 2962743 |
| P2-DP-5 | logger.py | All date.today() calls replaced with _pdt_today() (3 sites: build_trade_entry, get_daily_summary, rotate_logs) | 2962743 |

### Batch 1-2026-04-04 — Trading Safety P1 fixes (6b09ebe)
| ID | File | Fix | Commit |
|----|------|-----|--------|
| B1-1 | scripts/ws_feed_watchdog.py | kill_existing_ws_feed() ported to active watchdog — kills stale ws_feed before respawning | 6b09ebe |
| B1-2 | post_trade_monitor.py | load_open_positions() + check_settlements() inline loader: FIFO list accumulation replaces last-write-wins for multi-buy positions | 6b09ebe |
| B1-3 | post_trade_monitor.py | Phantom settlement fix: result inference now requires status='settled'/'finalized' (ported from settlement_checker.py ISSUE-028 fix) | 6b09ebe |

### Sprint 5-2026-04-04 — P2: Optimizer, Tests, Cleanup (80b7d02 + d2a3134)
| ID | File | Fix | Commit |
|----|------|-----|--------|
| P2-OPT-1 | optimizer.py | detect_module() deleted; classify_module() from logger.py used at callsite | d2a3134 |
| P2-OPT-2 | optimizer.py | DAILY_CAP now uses LOSS_CIRCUIT_BREAKER_PCT (0.05) instead of stale removed constants | d2a3134 |
| P2-TEST-1 | test_cycle_modes.py | crypto_1d added to REQUIRED_MODES and handler dict | d2a3134 |
| P2-TEST-2 | test_patterns.py | crypto_1d and 'report' added to REQUIRED_MODES | d2a3134 |
| P2-SEC-1 | secrets/ | CME secret files deleted (cme_config.json, cme_gcp_credential.json, cme_token_cache.json) | d2a3134 |
| P2-CRASH | audit/qa_health_check.py | Dead weather/NOAA/FRED/OpenMeteo sections removed (crash fix — was ImportError on import) | 80b7d02 |
| P2-CLN-1 | audit/data_health_check.py | check_nws(), check_openmeteo() removed | d2a3134 |
| P2-CLN-2 | 9 other files | Dead weather/geo/econ remnants cleaned (noaa_prob fields, architecture comments, whitelist entries) | d2a3134 |
