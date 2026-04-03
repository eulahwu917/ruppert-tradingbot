# P1 Issue Review — Data Scientist Domain
_Authored: 2026-04-03 | Reviewer: Data Scientist agent_
_Domain files: logger.py, capital.py, settlement_checker.py, data_agent.py, prediction_scorer.py, brier_tracker.py, data_health_check.py, daily_progress_report.py, optimizer.py_

---

## Summary

| Recommendation | Count |
|----------------|-------|
| 🔴 Bump to P0 — fix immediately | 1 |
| ✅ Fix Now | 12 |
| ⏳ Defer | 5 |
| 🟢 Accept / Downgrade to P3 | 4 |
| ⬛ Out of Domain (annotated per request) | 9 |

---

## 🔴 P0 Bump Recommended

### ISSUE-007 — `compute_closed_pnl_from_logs()` silently returns $0 on any exception
| Field | Value |
|-------|-------|
| **File** | `logger.py` |
| **Impact** | **HIGH — CRITICAL** |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | **Bump to P0 — Fix immediately** |

**Rationale:** This function IS the capital tracking backbone since `pnl_cache.json` was deleted (2026-03-31 overhaul). Any path failure (missing file, JSON decode error, field mismatch) silently returns $0, which propagates to `get_capital()`, which feeds every sizing decision. A $0 capital read will trigger whatever fallback value exists in strategy.py — or result in zero-sized orders. This is not a "P&L display" bug; it's a **capital tracking failure mode** with real trade-sizing consequences. Should have been caught when pnl_cache.json was deleted. Fix: wrap with `logger.error()` and re-raise (or return last known good), never swallow.

---

## ✅ Fix Now — High Impact, Small Effort

_Ordered by impact × ease. All of these should land in the next sprint._

### ISSUE-026 — Settlement checker uses `exit_price = 99` instead of 100 → understates every WIN
| Field | Value |
|-------|-------|
| **File** | `settlement_checker.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Every YES-side win is short-changed by 1¢ × contracts. At current scale (multiple settled positions per day) this compounds. Worse, it means historical P&L is systematically understated — we can't trust any performance figure without knowing how many contracts settled. Fix is a one-line change. No reason to wait.

---

### ISSUE-027 — Settlement checker dry-run P&L formula wildly wrong (asymmetric win vs loss)
| Field | Value |
|-------|-------|
| **File** | `settlement_checker.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | Fix with ISSUE-026 (same function) |
| **Recommendation** | Fix now |

**Rationale:** The paper P&L numbers from the settlement checker are noise — "+$9,800 vs -$100 on the same trade" makes any dry-run validation worthless. Since we use dry-run to sanity-check settlement logic before committing, broken dry-run numbers blind us to formula errors. Fix alongside ISSUE-026 in the same pass.

---

### ISSUE-005 — Optimizer globs `logs/` instead of `logs/trades/` → sees zero live trades
| Field | Value |
|-------|-------|
| **File** | `optimizer.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None — fix first before ISSUE-040/041/046 make sense |
| **Recommendation** | Fix now |

**Rationale:** Every optimizer output — domain stats, cap utilization, exit timing — is currently all-zeros because the path is wrong. This is the root issue for optimizer being completely broken. Fix the glob path first; ISSUE-040, ISSUE-041, ISSUE-046 all depend on the optimizer actually seeing trades.

---

### ISSUE-006 — `prediction_scorer` doesn't flip outcome for NO-side trades → calibration backwards
| Field | Value |
|-------|-------|
| **File** | `prediction_scorer.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** NO-side Brier scores and win rates are inverted. Every NO trade that wins is counted as a calibration failure and vice versa. This means our model calibration data is actively lying to us — if we ever act on it to tune thresholds or strategy, we'll optimize in the wrong direction. Easy fix: check `side == 'NO'` and flip `outcome = 1 - outcome` before scoring.

---

### ISSUE-108 — Logger import failures logged at DEBUG only → shadow log silently disabled
| Field | Value |
|-------|-------|
| **File** | `logger.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Shadow logging (terminal signals, price series) is new infrastructure that we explicitly built in March. If the import fails, the feature silently turns off at DEBUG level — we'd never know from INFO logs. This means we could be running with no price series data accumulating and have no indication. Given shadow logs feed the backtest pipeline, silent failure here is high impact. Fix: log at WARNING or ERROR on import failure.

---

### ISSUE-110 — Settlement checker has no retry on Kalshi API error → position silently skipped
| Field | Value |
|-------|-------|
| **File** | `settlement_checker.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Settlement is the final step of the trade lifecycle — if we miss it, the position stays open forever (or until the next 24h pass). At current frequency, a single API hiccup silently delays settlement by 24h, holding capital hostage and potentially triggering ghost-position logic. Add a simple 2–3 retry with backoff. Small effort, high consequence to skip.

---

### ISSUE-121 — `data_health_check._push_alert()` writes to log instead of `pending_alerts.json`
| Field | Value |
|-------|-------|
| **File** | `data_health_check.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Health check alerts never reach the alert consumer (Telegram/heartbeat). This means the entire data health monitoring pipeline is muted — we could have truth file corruption or capital anomalies and never get notified. Fix: write to `environments/demo/logs/truth/pending_alerts.json` as the rest of the alert system does.

---

### ISSUE-102 — `TICKER_MODULE_MAP` missing `KXBTCD` prefix → threshold daily BTC misclassified
| Field | Value |
|-------|-------|
| **File** | `logger.py` / `data_agent.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Every BTC threshold daily trade is classified to the wrong module in analytics. This corrupts module-level P&L attribution, cap utilization stats, and optimizer inputs for the daily module. Since `crypto_threshold_daily` is one of the active modules, this is live data quality corruption. Fix is a map entry addition.

---

### ISSUE-004 — `brier_tracker.py` writes predictions to hardcoded path
| Field | Value |
|-------|-------|
| **File** | `brier_tracker.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Brier tracker is the calibration feedback loop. If predictions write to the wrong path in production, the entire Brier scoring pipeline silently produces no data. Fix: use config-driven paths, same as the rest of the system.

---

### ISSUE-040 — Domain name mismatch between scorer (`crypto_dir_15m_btc`) and optimizer (`crypto`) → per-domain optimization blind
| Field | Value |
|-------|-------|
| **File** | `prediction_scorer.py`, `optimizer.py` |
| **Impact** | High |
| **Effort** | Medium |
| **Sequencing** | Fix ISSUE-005 first (optimizer needs to see trades before domain lookup matters) |
| **Recommendation** | Fix now |

**Rationale:** The optimizer's `detect_module()` flattens `crypto_dir_15m_btc` → `crypto`, so all per-asset, per-direction threshold optimization is completely blind. We can't tune BTC vs ETH vs SOL thresholds independently if they all collapse to one bucket. This is the core reason the optimizer can't differentiate modules. Medium effort because it requires reconciling naming conventions across two files and ensuring the scorer doesn't break downstream consumers.

---

### ISSUE-065 — Settled positions appear as open — dashboard misses `action='settle'`
| Field | Value |
|-------|-------|
| **File** | `settlement_checker.py`, `dashboard/api.py` |
| **Impact** | High |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Settlement_checker.py (my domain) is writing `action='settle'` records, but the dashboard doesn't recognize them as closing events. The fix on my side: verify settle records have the right schema. The api.py fix is on the dashboard side, but the root cause belongs here — ensuring settle records are correctly formed is my responsibility.

---

### ISSUE-103 — Multi-day positions: scorer writes `null predicted_prob` when buy date ≠ settle date
| Field | Value |
|-------|-------|
| **File** | `prediction_scorer.py` |
| **Impact** | High |
| **Effort** | Medium |
| **Sequencing** | None |
| **Recommendation** | Fix now |

**Rationale:** Overnight positions (anything held past midnight) corrupt the calibration pipeline with null probability entries. These nulls either break downstream Brier calculations or silently get excluded, creating selection bias (only intraday trades get calibrated). Since we're holding daily contracts overnight regularly, this affects a substantial fraction of our data. Fix: look up buy record's probability when settle date ≠ buy date.

---

## ⏳ Defer — Fix Soon (Next 1–2 Sprints)

### ISSUE-050 — `prediction_scorer` only uses first buy leg's probability for scale-in trades
| Field | Value |
|-------|-------|
| **File** | `prediction_scorer.py` |
| **Impact** | Medium |
| **Effort** | Medium |
| **Sequencing** | Fix ISSUE-103 first (null prob fix more urgent) |
| **Recommendation** | Defer (next sprint) |

**Rationale:** Brier bias for scale-in trades is real but affects a smaller subset of trades. The weighted average of entry probabilities would be more correct, but this is an analytical refinement, not a live-trading blocker.

---

### ISSUE-041 — `analyze_daily_cap_utilization()` double-counts every closed trade
| Field | Value |
|-------|-------|
| **File** | `optimizer.py` |
| **Impact** | Medium |
| **Effort** | Small |
| **Sequencing** | Fix ISSUE-005 first (optimizer path fix required) |
| **Recommendation** | Defer (same sprint as ISSUE-005) |

**Rationale:** Cap utilization appearing 2× actual gives false "cap exhausted" signals, but this is an analytical tool bug, not a live-trading bug. Fix after ISSUE-005 since the entire optimizer is currently reading zero trades anyway.

---

### ISSUE-048 — `crypto_long` routing conflict → `data_agent` auto-fix loop writes records repeatedly
| Field | Value |
|-------|-------|
| **File** | `data_agent.py`, `logger.py` |
| **Impact** | Medium |
| **Effort** | Medium |
| **Sequencing** | None |
| **Recommendation** | Defer (next sprint) |

**Rationale:** The auto-fix loop writing records repeatedly corrupts module-level analytics but doesn't affect live trade entry/exit decisions. Fix before the next performance review cycle when we'll need clean per-module analytics.

---

### ISSUE-075 — `data_agent.py` audit files written non-atomically → concurrent audit runs corrupt output
| Field | Value |
|-------|-------|
| **File** | `data_agent.py` |
| **Impact** | Medium |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Defer (next sprint) |

**Rationale:** Concurrent audit runs are possible but not the common case. The corruption risk is real but low frequency. Apply the standard atomic-write pattern (write to `.tmp`, then rename) when we're doing the data_agent pass.

---

### ISSUE-095 — Two conflicting P&L totals in daily progress report — unlabeled
| Field | Value |
|-------|-------|
| **File** | `daily_progress_report.py` |
| **Impact** | Medium |
| **Effort** | Small |
| **Sequencing** | None |
| **Recommendation** | Defer (next sprint) |

**Rationale:** Confusing and misleading in performance review, but doesn't affect live trading. Fix: label each total clearly (e.g., "Open P&L" vs "Closed P&L") and reconcile the two computation paths. Medium priority — David reads this report, so it should be accurate.

---

## 🟢 Downgrade to P3 Recommended

### ISSUE-046 — `analyze_exit_timing()` reads `exit_timestamp` field that doesn't exist
| Field | Value |
|-------|-------|
| **File** | `optimizer.py` |
| **Current Priority** | P1 |
| **Recommended** | P3 |
| **Rationale** | Hold time analysis is purely analytical — no live trading impact. Fix after ISSUE-005 and ISSUE-040 are resolved and the optimizer is actually useful. Not worth its own sprint slot. |

---

### ISSUE-101 — `brier_tracker.score_prediction()` allows duplicate entries
| Field | Value |
|-------|-------|
| **File** | `brier_tracker.py` |
| **Current Priority** | P1 |
| **Recommended** | P3 |
| **Rationale** | Inflated Brier sample count is an analytical quality issue, not a trading blocker. We're not yet acting on Brier scores to make live decisions. Add a dedup check when we formalize the calibration feedback loop. |

---

### ISSUE-036 — `data_integrity_check.py` checks wrong path → always returns false "OK"
| Field | Value |
|-------|-------|
| **File** | `data_integrity_check.py` |
| **Current Priority** | P1 |
| **Recommended** | P3 |
| **Rationale** | This is an audit tool, not a live system. A broken audit tool is bad, but it doesn't corrupt data — it just fails to detect corruption. Fix in a tooling cleanup sprint, not alongside live-system fixes. |

---

### ISSUE-086 — `exit_correction` records excluded from Today/7-day P&L in brief_generator
| Field | Value |
|-------|-------|
| **File** | `brief_generator.py` (out of domain, but affects P&L reporting) |
| **Current Priority** | P1 |
| **Recommended** | P3 |
| **Rationale** | We've applied correction records, so they need to show up in P&L reports. However, brief_generator is a reporting tool — wrong P&L in the brief doesn't affect trading. Flag to whoever owns brief_generator. The number of correction records is currently small. |

---

## ⬛ Out of Domain — Annotated Per Request

_These issues touch adjacent systems. My annotations reflect data quality impact, not code ownership._

### ISSUE-018 — `/api/account` crashes with NameError on every call
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| Medium | Small | Fix now |

Dashboard API bug, not my files. But: the account page is the primary P&L view David uses. Fix blocks basic visibility. Whoever owns `dashboard/api.py` should treat this as high priority.

---

### ISSUE-019 — `/api/positions/active` crashes — `side` used before assigned
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| High | Small | Fix now |

Active positions endpoint broken permanently is effectively a dashboard blackout. Same owner as ISSUE-018 — fix together in one pass.

---

### ISSUE-030 — `pnl` field absent from most exits → most P&L silently computed as $0
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| High | Medium | Fix now |

**This directly affects my domain.** `compute_closed_pnl_from_logs()` in logger.py sums `pnl` fields. If most exits don't have the field, the function returns near-zero for all non-WS exits. This is an upstream bug in `ruppert_cycle.py` and `post_trade_monitor.py` — but the symptom lands in my capital computation. Whoever fixes this should coordinate with DS to verify logger.py P&L computation picks up the corrected records correctly.

---

### ISSUE-037 — `code_audit.py` scans `audit/` instead of `demo/` → misses every production module
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| Low | Small | Downgrade to P3 |

DevOps/tooling concern. Not blocking anything live.

---

### ISSUE-038 — `qa_self_test.py` hardcoded absolute Windows path → breaks everywhere else
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| Low | Small | Downgrade to P3 |

CI hygiene issue only. No live trading impact.

---

### ISSUE-063 — P&L chart hardcodes `"2026-03-10"` as historical data point
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| Medium | Small | Fix now |

Fabricated data in the dashboard is misleading for performance review. Fix: pull from actual trade logs. This affects trust in the dashboard, which David relies on.

---

### ISSUE-064 — `BOT_SRC` tuple missing `ws_*` source labels → deployed capital understated
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| High | Small | Fix now |

WS-originated trades (which are most 15m trades now) are invisible to the capital tracker. This means deployed capital is systematically understated in the dashboard — David might think we have more room to deploy than we do. Fix is adding the `ws_*` labels to the tuple.

---

### ISSUE-066 — `closed_win_rate` uses ticker-dedup instead of trade_id
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| Medium | Small | Fix now |

Win rate is a key metric David uses to evaluate strategy performance. Ticker-dedup collapses multiple trades on the same ticker, making the rate meaningless. Fix: deduplicate on `trade_id`.

---

### ISSUE-072 — 19 exception swallows in dashboard API → all errors silently hidden
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| High | Medium | Fix now |

19 silent exception swallows means the dashboard can return completely wrong data with zero indication. This is a systemic trust issue with the dashboard. Whoever owns `dashboard/api.py` should treat this as high priority — it makes every other dashboard bug invisible.

---

### ISSUE-100 — `qa_self_test.py` deprecated file check scans wrong directory → always passes falsely
| Impact | Effort | Recommendation |
|--------|--------|----------------|
| Low | Small | Downgrade to P3 |

False QA pass on deprecated files is a tooling quality issue. No live impact.

---

## Priority Summary Table

| Rank | Issue | File | Impact | Effort | Recommendation |
|------|-------|------|--------|--------|----------------|
| 1 | ISSUE-007 | logger.py | **CRITICAL** | Small | **🔴 BUMP TO P0** |
| 2 | ISSUE-026 | settlement_checker.py | High | Small | ✅ Fix now |
| 3 | ISSUE-027 | settlement_checker.py | High | Small | ✅ Fix now |
| 4 | ISSUE-005 | optimizer.py | High | Small | ✅ Fix now |
| 5 | ISSUE-006 | prediction_scorer.py | High | Small | ✅ Fix now |
| 6 | ISSUE-108 | logger.py | High | Small | ✅ Fix now |
| 7 | ISSUE-110 | settlement_checker.py | High | Small | ✅ Fix now |
| 8 | ISSUE-121 | data_health_check.py | High | Small | ✅ Fix now |
| 9 | ISSUE-102 | logger.py / data_agent.py | High | Small | ✅ Fix now |
| 10 | ISSUE-004 | brier_tracker.py | High | Small | ✅ Fix now |
| 11 | ISSUE-040 | prediction_scorer.py + optimizer.py | High | Medium | ✅ Fix now |
| 12 | ISSUE-065 | settlement_checker.py + api.py | High | Small | ✅ Fix now |
| 13 | ISSUE-103 | prediction_scorer.py | High | Medium | ✅ Fix now |
| 14 | ISSUE-050 | prediction_scorer.py | Medium | Medium | ⏳ Defer |
| 15 | ISSUE-041 | optimizer.py | Medium | Small | ⏳ Defer (after ISSUE-005) |
| 16 | ISSUE-048 | data_agent.py | Medium | Medium | ⏳ Defer |
| 17 | ISSUE-075 | data_agent.py | Medium | Small | ⏳ Defer |
| 18 | ISSUE-095 | daily_progress_report.py | Medium | Small | ⏳ Defer |
| 19 | ISSUE-046 | optimizer.py | Low | Small | 🟢 Downgrade to P3 |
| 20 | ISSUE-101 | brier_tracker.py | Low | Small | 🟢 Downgrade to P3 |
| 21 | ISSUE-036 | data_integrity_check.py | Low | Small | 🟢 Downgrade to P3 |
| 22 | ISSUE-086 | brief_generator.py | Low | Small | 🟢 Downgrade to P3 |

---

## Key Cross-Domain Dependencies I'm Flagging

1. **ISSUE-030 (ruppert_cycle.py / post_trade_monitor.py)** → Missing `pnl` field on exits means `compute_closed_pnl_from_logs()` (my code) reads near-zero for most exits. This is the upstream-most data quality bug affecting my domain. Coordinate: whoever fixes ISSUE-030 should hand off to DS to verify logger.py picks up corrected records.

2. **ISSUE-005 → ISSUE-040 → ISSUE-041 → ISSUE-046** — Optimizer issues have a dependency chain. Fix the path (ISSUE-005) first, then domain naming (ISSUE-040), then the counting/field bugs. Running them in wrong order wastes effort.

3. **ISSUE-007 + ISSUE-030** — Both affect the same P&L computation path. If ISSUE-030 is fixed (exits get `pnl` field) but ISSUE-007 isn't (exceptions still silently return $0), we still have no protection against capital tracking failures. Fix both.

4. **Settlement cluster: ISSUE-026 + ISSUE-027 + ISSUE-110 + ISSUE-065** — All settlement_checker.py issues. Fix in one pass to avoid touching the file 4 separate times.

---

_Review complete. 2026-04-03. Data Scientist._
