# P1 Trader Review — Pre-Sprint Scoping
_Authored by: Trader agent_
_Date: 2026-04-03_
_Source: master-issues-PRIORITIZED-2026-04-02.md (P1 section)_
_Domain: position_tracker.py, position_monitor.py, post_trade_monitor.py, ws_feed.py, crypto_15m.py, crypto_client.py, strategy.py, circuit_breaker.py, trader.py_

---

## Summary

19 P1 issues assigned for review. Of these:
- **2 should be bumped to P0** — actively corrupt live operations right now
- **12 Fix now** — significant ongoing impact on signal quality, P&L accuracy, or risk
- **4 Defer** — real bugs but low current blast radius
- **1 Accept** — not a real bug (short-circuit protection exists)
- **0 Downgrade to P3** — all confirmed real bugs with real impact

---

## P0 Nominations (Bump Immediately)

| ID | Issue | Why P0 |
|----|-------|--------|
| **ISSUE-117** | `vol_ratio=0` bypasses vol shrinkage → full unscaled Kelly | When vol data is missing (returns 0), `if vol_ratio > 0` guard skips shrinkage entirely. Full Kelly fires instead of $0. This is a **live sizing error** on every trade where vol data gaps — which is common at window open. The position cap limits damage but the sizing intent is completely violated. |
| **ISSUE-034** | `position_monitor WS_ENABLED=True` raises RuntimeError immediately | WS mode is retired but `WS_ENABLED = True` is hardcoded at line 64. Any invocation path that doesn't route through the ws_feed.py shortcut (e.g., no-ws-module fallback) immediately throws RuntimeError before polling fallback can run. Positions go unmonitored. |

---

## Prioritized Fix Table

_Top = highest urgency. Issues in my domain only._

| Rank | ID | Impact | Effort | Sequencing | Rec | File | Summary |
|------|----|--------|--------|------------|-----|------|---------|
| 1 | **ISSUE-117** | **High** | Small | None | **P0 → Fix Now** | `strategy.py` | `vol_ratio=0` skips Kelly shrinkage → full unscaled position fires. Guard is `if vol_ratio > 0` but zero means "missing data" and should size to $0, not full Kelly. One-line fix: `if vol_ratio > 0` → `if vol_ratio and vol_ratio > 0`. |
| 2 | **ISSUE-034** | **High** | Small | None | **P0 → Fix Now** | `position_monitor.py` | `WS_ENABLED = True` hardcoded crashes any fallback path via RuntimeError. Fix: set `WS_ENABLED = False` since WS is retired here; ws_feed.py owns WS. |
| 3 | **ISSUE-098** | **High** | Small | None | **Fix Now** | `position_monitor.py` | NO-side win P&L overstated ~2.4× via `normalize_entry_price()`. When NO entry was e.g. 30¢, normalize flips it to 70¢. Then `(99 - 70) × contracts / 100` → completely wrong. Paper performance inflated for every NO win. Settlement checker in post_trade_monitor uses same formula correctly elsewhere but position_monitor has the bug. Fix: use raw `fill_price` directly for settlement P&L in monitor. |
| 4 | **ISSUE-062** | **High** | Medium | None | **Fix Now** | `ws_feed.py` | Stale spot price in edge calculation — WS eval uses cached price that can be minutes old during fast-moving markets. Edge is computed as `model_prob - market_prob` where market_prob comes from the tick that triggered eval, but the BTC/ETH spot price feeding into the model probability is REST-fetched with a TTL cache. On high-volatility windows this creates directional error. Fix: require fresh spot fetch if cache is >30s old before 15m eval. |
| 5 | **ISSUE-096** | **High** | Small | None | **Fix Now** | `ws_feed.py` | WS reconnect flat 5s retry forever. Confirmed: `await asyncio.sleep(5)` with no backoff (line 931). During outage this hammers Kalshi at 12 conn/min — classic ban trigger. Standard exponential backoff (5s→10s→20s→60s cap) is a trivial fix. High urgency because an outage compounds itself. |
| 6 | **ISSUE-032** | **High** | Small | None | **Fix Now** | `crypto_client.py` | Wallet file resolves to `Path(__file__).parent / 'logs' / 'smart_money_wallets.json'` = `agents/ruppert/trader/logs/smart_money_wallets.json`. But `wallet_updater.py` writes to `environments/demo/logs/smart_money_wallets.json`. These are different paths. Confirmed: trader/logs/ file is MISSING; demo/logs/ file EXISTS. So `_load_wallets()` always falls back to the 3-wallet hardcoded stub. Fix: use `env_config.get_paths()['logs']` for the wallet path, same as everything else. |
| 7 | **ISSUE-129** | **High** | Small | None | **Fix Now** | `crypto_15m.py` | Near-zero OI delta produces astronomical z-score. `_z_score()` divides by rolling stdev. If first few ticks have near-zero variance (common at window open), stdev→0 → oi_z spikes to ±hundreds before clipping. Clip in `_z_score()` bounds to [-2, 2] does rescue this, but the z-score still contributes full OI weight for those early windows. Fix: guard stdev with `max(stdev, 1e-6)` in z-score and add explicit `prev_oi==0` guard in OI delta calc (already partially handled — confirm guard covers near-zero not just exact zero). |
| 8 | **ISSUE-069** | **Medium** | Small | None | **Fix Now** | `crypto_15m.py` | `getattr()` fallback for signal weights uses Phase 1 defaults when config import fails. If config fails silently at module load, W_TFI=0.42, W_OBI=0.25, W_MACD=0.15, W_OI=0.18 — these are old weights not matching current tuning. The fix is to catch ImportError at startup and halt with a clear error rather than silently reverting. Low blast radius (config failure is rare) but directionally wrong signal is worse than no signal. |
| 9 | **ISSUE-114** | **Medium** | Small | Depends on ISSUE-069 | **Fix Now** | `crypto_15m.py` | Signal weights not asserted to sum to 1.0. Currently W_TFI + W_OBI + W_MACD + W_OI = 0.42+0.25+0.15+0.18 = 1.00 (correct with defaults). But a bad config override producing weights ≠ 1.0 silently scales the composite score and shifts P_directional. Add: `assert abs(W_TFI + W_OBI + W_MACD + W_OI - 1.0) < 1e-6, f"Signal weights don't sum to 1: {W_TFI+W_OBI+W_MACD+W_OI}"` at module init. Fix after ISSUE-069 so the import guard comes first. |
| 10 | **ISSUE-079** | **Medium** | Small | None | **Fix Now** | `post_trade_monitor.py` | `check_alert_only_position()` has broken entry_price normalization. Code: `entry_price = pos.get('entry_price') or pos.get('market_prob', 0.5) * 100`. If entry_price=0 (zero-valued but present), `or` falls through to market_prob. Then the inline normalization `if 0 < entry_price < 1: entry_price = round((1-entry_price)*100)` checks the market_prob path which may be 0.3 → treated as 30% → normalized to 70¢ for NO. But for YES positions, this flips the price entirely. The `pnl = round((cur_price - entry_price) * contracts / 100, 2) if entry_price else 0` then returns $0 for any entry_price=0. Alerting is wrong for all econ/geo/fed positions with zero entry_price in the record. Fix: use `normalize_entry_price(pos)` consistently here instead of inline logic. |
| 11 | **ISSUE-104** | **Low** | Trivial | None | **Accept (not a real bug)** | `strategy.py` | ISSUE description says "`_module_cap_missing` unassigned when `module=None` → NameError". **This is NOT a real bug.** The only reference to `_module_cap_missing` outside the `if module is not None:` block is at line 454: `if module is not None and _module_cap_missing:` — Python short-circuit evaluation means `_module_cap_missing` is never evaluated when `module is None`. No NameError possible. Recommend: close as invalid, add a comment noting the short-circuit protection for clarity. |
| 12 | **ISSUE-105** | **Medium** | Small | None | **Fix Now** | `crypto_15m.py` | Window cap counter overcharged. When `position_usd` is trimmed to e.g. $3 (barely above the $5 floor), the window exposure counter is incremented by $3. But `contracts = max(1, int(3 / 0.40))` = at least 1 contract → actual spend = 1 × $0.40 = $0.40. The counter shows $3 charged but only $0.40 was actually deployed. Over 5 assets × 96 windows/day, this systematically understates remaining capacity. Fix: update `_window_exposure` after executing, using `contracts × entry_price / 100` as the actual amount, not the pre-trim `position_usd`. |
| 13 | **ISSUE-045** | **Medium** | Small | None | **Fix Now** | `position_tracker.py` | Legacy positions missing `entry_secs_in_window` get default of 120 (2 min). This means every "legacy" position — i.e., all positions opened before this field was added — is treated as an early-window entry and gets the tightest stop tier (`STOP_GUARD_EARLY_PRIMARY` = 480s guard before stop fires). Positions that were actually entered at 8+ min (late window, should have shortest guard) get maximum guard instead. Stop behavior is inverted for legacy positions. Fix: try to infer `entry_secs_in_window` from `added_at` + window open time, default to mid-range (300) not minimum (120) when unknown. |
| 14 | **ISSUE-074** | **Medium** | Small | None | **Fix Now** | `post_trade_monitor.py` | Exit records from post_trade_monitor missing `edge` and `confidence` fields. Confirmed: `check_alert_only_position()` builds exit records without these fields. The settlement records do pass `entry_edge: pos.get("edge", None)` and `confidence: pos.get("confidence", None)` — so it's the non-settlement exits that are missing these. Optimizer then sees 0 average edge on these exits. Fix: add `edge` and `confidence` passthrough to all exit record builders in post_trade_monitor. |
| 15 | **ISSUE-057** | **Medium** | Medium | None | **Defer** | `crypto_15m.py` (via crypto_threshold_daily) | Polymarket 20% weight uses 15m short-window consensus for daily-scale trades. However, reviewing crypto_15m.py, Polymarket is currently shadow-only with `poly_nudge = 0.0` (unconditionally zeroed, line 1009). For crypto_15m this is already moot. The issue is in `crypto_threshold_daily.py` which is NOT in my domain. Flagging for the daily module owner. Defer for Trader until daily modules are the focus. |
| 16 | **ISSUE-053** | **Medium** | Medium | None | **Defer** | `crypto_threshold_daily.py` / `crypto_band_daily.py` | Daily cap race — concurrent asset evals both pass cap before either trade logs. These files are not in my core domain. The crypto_15m module already uses `_window_lock` threading.Lock for this protection. The daily modules appear to lack equivalent protection. Defer: daily modules are P1 focus, not 15m. When daily module sprint begins, apply same lock pattern from crypto_15m. |
| 17 | **ISSUE-023** | **Medium** | Medium | None | **Fix Now** | `position_tracker.py` | `position_tracker` bypasses `log_trade()` for exit records. Confirmed: exits use `_log_exit()` directly, which is `logger.log_exit()`. This means dedup fingerprinting from `log_trade()` doesn't fire, and ~15 schema fields are absent. The dedup risk (double-write) is lower than P0 because `_exits_in_flight` already guards concurrent exits in-memory. But the schema gaps affect analytics downstream. Fix: route WS exits through `log_trade()` or ensure `_log_exit()` populates the same fingerprint and schema. Medium effort due to schema reconciliation needed. |
| 18 | **ISSUE-048** | **Low** | Small | None | **Defer** | `data_agent.py` / `logger.py` | `crypto_long` routing conflict → data_agent auto-fix loop writes records repeatedly. This is data_agent's domain, not core trader. The repeated writes are a data pollution issue but don't affect live 15m trading. Defer to data agent sprint. |
| 19 | **ISSUE-075** | **Low** | Small | None | **Defer** | `data_agent.py` | Audit files written non-atomically. Not in core trader domain. Low immediate risk at current concurrency levels. Defer to data agent sprint. |

---

## P0 Escalation Details

### ISSUE-117 — `vol_ratio=0` fires full Kelly

**Location:** `strategy.py` → `calculate_position_size()`, line 237

```python
# Current (BROKEN):
if vol_ratio > 0:
    kelly_size *= (1.0 / vol_ratio)

# When vol_ratio=0: guard skips → kelly_size unchanged → full Kelly fires
# Fix:
if vol_ratio and vol_ratio > 0:
    kelly_size *= (1.0 / vol_ratio)
# Or better: treat vol_ratio=0 as "data missing" → return 0.0
```

**Blast radius:** Every 15m entry where vol data wasn't available at eval time. Currently `vol_ratio` defaults to 1.0 if not in signal dict, so this only fires if a caller explicitly passes 0. Check callers — if any signal builder returns `vol_ratio=0` on data failure, this fires in production. P4 annotation in issues says `vol_ratio` is always 1.0 (ISSUE-123) — if true, this is latent. But the logic is semantically wrong and should be fixed before any vol signal is wired.

---

### ISSUE-034 — `WS_ENABLED=True` crashes position_monitor

**Location:** `position_monitor.py`, line 64 and `main()` fallback path, lines 661-678

```python
# Line 64 (current):
WS_ENABLED = True  # ← This is wrong. WS is retired.

# Fallback path (line 655+):
# When ws_feed.py import fails → falls through to check WS_ENABLED
# → ws_available=True → asyncio.run(run_ws_mode(client))
# → run_ws_mode() raises RuntimeError immediately
# → uncaught → monitor exits without checking any positions
```

**Blast radius:** Any invocation of position_monitor where ws_feed.py import fails (e.g., ws/ module unavailable). In that scenario, the fallback intended behavior (polling mode) never runs because `WS_ENABLED=True` sends it down the dead code path. Fix: `WS_ENABLED = False`.

---

## Issues NOT in My Domain (P1 List) — FYI

These P1 issues appeared in the list but are not trader domain files:

| ID | File | Owner |
|----|------|-------|
| ISSUE-016 | `crypto_band_daily.py` | Daily module owner |
| ISSUE-017 | `crypto_band_daily.py`, `crypto_threshold_daily.py` | Daily module owner |
| ISSUE-026/027/028/030 | `settlement_checker.py`, `ruppert_cycle.py` | Ops/cycle owner |
| ISSUE-036/037/038/100 | Audit/QA tools | QA owner |
| ISSUE-040/041/046/050 | `optimizer.py`, `prediction_scorer.py` | Analytics owner |
| ISSUE-063–066/072 | `dashboard/api.py` | Dashboard owner |
| ISSUE-086/095 | `brief_generator.py`, `daily_progress_report.py` | Reporting owner |
| ISSUE-088/089/116 | `polymarket_client.py` | Data analyst owner |

**Note on ISSUE-017** (NO-side order uses `100 - yes_ask` instead of `no_ask`): This is critical for daily modules but also has latent impact on `position_monitor.py` settlement P&L. The settlement P&L in position_monitor uses `normalize_entry_price(pos)` which applies the same flip. Recommend whoever fixes ISSUE-017 also review settlement P&L computation in position_monitor.

---

## Sequencing Recommendations

**Sprint order for my domain:**

1. **ISSUE-117** + **ISSUE-034** (P0, trivial, do immediately — 1 line each)
2. **ISSUE-096** (WS reconnect backoff — safety before next outage)
3. **ISSUE-032** (wallet path fix — affects signal quality every cycle)
4. **ISSUE-098** (NO-side P&L — corrupts paper performance metrics)
5. **ISSUE-129** + **ISSUE-114** + **ISSUE-069** (signal integrity cluster — fix together)
6. **ISSUE-105** + **ISSUE-045** (cap/stop precision — fix together, both are position lifecycle)
7. **ISSUE-062** (stale spot price — medium effort, needs cache invalidation design)
8. **ISSUE-074** + **ISSUE-079** + **ISSUE-023** (exit record schema — fix together)

---

## Risk Summary

| Category | Issues | Status |
|----------|--------|--------|
| Active money at risk (live sizing wrong) | ISSUE-117 | 🔴 P0 |
| Active monitoring gap (positions unchecked) | ISSUE-034 | 🔴 P0 |
| Signal degraded (wrong data) | ISSUE-032, ISSUE-062, ISSUE-129 | 🟠 High |
| Risk control gaps | ISSUE-105, ISSUE-096 | 🟠 High |
| P&L / analytics corrupted | ISSUE-098, ISSUE-074, ISSUE-079 | 🟠 High |
| Code hygiene / latent bugs | ISSUE-069, ISSUE-114, ISSUE-045, ISSUE-023 | 🟡 Medium |
| Not a real bug | ISSUE-104 | ✅ Close |
| Out of domain / defer | ISSUE-053, ISSUE-057, ISSUE-048, ISSUE-075 | ⚪ Defer |
