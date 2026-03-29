# Ruppert Bot — Deep Audit Report #2 (Opus)
## Date: 2026-03-26

---

## PART 1: CODEBASE REVIEW

### P0 Issues (Critical)

| File | Function/Line | Description | Recommended Fix |
|------|---------------|-------------|-----------------|
| `trader.py` | `check_pre_trade` | Uses undefined `config.MAX_POSITION_SIZE` and `config.MAX_DAILY_EXPOSURE` — these constants were removed but the legacy fallback code still references them. Will crash if `strategy_size` is not provided. | Add `MAX_POSITION_SIZE = 100.0` and `MAX_DAILY_EXPOSURE = 700.0` to config.py, OR delete the entire legacy fallback path since `strategy_size` is always provided by strategy.py |
| `kalshi_client.py` | `search_markets` line ~115 | After `for m in markets[:5]:`, uses `m.ticker` (attribute access) but `m` is a dict, not an object. Will crash in `__main__` test. | Change `m.ticker` to `m.get('ticker')` and `m.title` to `m.get('title')` |
| `ruppert_cycle.py` | Global `actions_taken` scope | `actions_taken` is defined inside the `try` block of STEP 1, but referenced in MODE == 'check' exit with `'actions_taken' in dir()`. If STEP 1 raises early, `actions_taken` is undefined and the fallback `0` is used—but the `for action, ticker...` loop later would crash if it somehow got there. | Move `actions_taken = []` to before the try block (line ~47) |
| `capital.py` | `get_pnl` | Returns `{'closed': 0.0, ...}` if `pnl_cache.json` doesn't exist, but `get_capital()` adds this to deposits. If pnl_cache.json doesn't exist, this is fine (returns 0), but if it exists with corrupted data, the `float()` cast can raise. | Add try/except around the float() conversions |

### P1 Issues (Silent Wrong Behavior)

| File | Function/Line | Description | Recommended Fix |
|------|---------------|-------------|-----------------|
| `edge_detector.py` | `analyze_market` ~line 150 | T-market classification uses `temp_range` from `parse_temp_range_from_title()` which often returns `None` for band markets (title format varies). When `temp_range` is None, `classify_market_type` returns "B_band" even for threshold-based markets. | Parse threshold from ticker (already done) and use that to classify: `high_f == 999` pattern should come from ticker structure, not just title regex |
| `openmeteo_client.py` | `get_current_conditions` | `hours_since_midnight` is parsed from UTC time string but the intent is LOCAL hours. For markets in `America/Chicago` observed at 3pm UTC, this shows hour=15 when local time is 9am. Same-day logic in `get_full_weather_signal` may prematurely skip or weight wrong. | Parse timezone-aware datetime and convert to local timezone before extracting hour |
| `post_trade_monitor.py` | `load_open_positions` | Reads yesterday + today logs but only tracks entries/exits by ticker—not by side. If you BUY NO, then BUY YES on the same ticker, the second entry overwrites the first. | Key by `(ticker, side)` tuple instead of just ticker |
| `strategy.py` | `should_enter` direction filter | Weather direction filter checks `side.upper() != config.WEATHER_DIRECTION_FILTER.upper()` but `WEATHER_DIRECTION_FILTER = "NO"` is uppercase already. This works, but the string comparison is case-sensitive. If someone sets filter to lowercase accidentally, it would block all trades. | Normalize both sides: `side.lower() != config.WEATHER_DIRECTION_FILTER.lower()` |
| `main.py` | `run_weather_scan` | `deployed_today` is updated inside the loop (`deployed_today += decision['size']`) but this shadows the daily cap check that already ran before the loop. The `check_daily_cap` at the top doesn't account for trades placed within this cycle. | This is intentional (W14 fix comment), but the initial `cap_remaining` check at line ~170 is stale by the time the loop finishes. Consider recalculating `cap_remaining` inside the loop. |
| `dashboard/api.py` | `get_pnl_history` | Module P&L uses `classify_module(src, ticker)` which returns 'other' for any series not matching prefixes. Crypto tickers like `KXDOGE` are not in the prefix list, so DOGE trades go to 'other'. | Add 'KXDOGE' to the crypto prefixes in `classify_module` |
| `geo_edge_detector.py` | `extract_edges` | Uses `anthropic.Anthropic()` client but never configures API key from secrets. If `ANTHROPIC_API_KEY` env var isn't set, will fail silently or raise. | Load API key from secrets/kalshi_config.json like other clients |

### P2 Issues (Minor Bugs)

| File | Function/Line | Description | Recommended Fix |
|------|---------------|-------------|-----------------|
| `ghcnd_client.py` | `compute_station_bias` | Uses yesterday as end_date, but lookback starts from `today - (lookback_days + 1)`. Off-by-one: should be `today - timedelta(days=lookback_days)` to `today - timedelta(days=1)`. Currently fetches 31 days for a 30-day lookback. | Change to `today - timedelta(days=lookback_days)` |
| `openmeteo_client.py` | `_fetch_raw_ensemble` | `forecast_days = max(days_ahead + 2, 3)` — if target is 7 days out, this requests 9 days of forecast but caps at 16. Fine, but the +2 buffer is undocumented and inconsistent with NOAA which uses exact date. | Add comment explaining the +2 buffer, or just use `days_ahead + 1` |
| `crypto_scanner.py` | `band_prob` | Log-normal probability assumes zero drift by default, but `drift` parameter is never passed from callers. The `drift_sigma` variable in `main.py/run_crypto_scan` is set to 0.0 and never used. | Either remove drift parameter or wire it through properly |
| `optimizer.py` | `detect_module` | For tickers with "CPI" it returns "econ", but KXCPI tickers are actually fed/econ hybrid. The module detection doesn't handle "KXFED" prefix for Fed rate decisions. | Add explicit check for `ticker.startswith("KXFED")` |
| `logger.py` | `build_trade_entry` | Falls back to `module = source` when module can't be determined. If source is 'bot', module becomes 'bot' which is not a valid module in config.MIN_CONFIDENCE. | Default to 'weather' for 'bot' source, or 'unknown' |
| `economics_scanner.py` | `find_econ_opportunities` | Returns empty list `[]` — this is a stub. The entire module is non-functional. | Document that this is a stub, or implement actual economics scanning |

### P3 Issues (Design/Smell)

| File | Issue | Description |
|------|-------|-------------|
| `config.py` | Redundant constants | `ECON_MAX_POSITION` and `ECON_MAX_DAILY_EXPOSURE` exist but are "kept for ruppert_cycle.py budget checks" — these should be removed and replaced with the centralized `MAX_POSITION_PCT` system. |
| `capital.py` + `logger.py` | Circular dependency smell | `logger.py` has `get_computed_capital` that delegates to `capital.get_capital`, and `capital.py` imports from `logger` for `get_daily_exposure`. This works but is confusing. |
| `edge_detector.py` | Shadow logging | `_shadow_log_yes_signal` logs YES signals that were blocked to a separate file. Good for counterfactual analysis, but the function is called from both edge_detector.py and main.py — potential duplicate logging. |
| `geopolitical_scanner.py` | No edge calculation | Returns `news_volume` but no actual probability edge. The module is marked `GEO_AUTO_TRADE = False` which is correct, but the scanner pretends to find "opportunities" when it really just finds "markets with news". |
| `dashboard/api.py` | 1200+ lines | This file is massive. Endpoint handlers, P&L calculation, market classification, and price fetching are all mixed together. Should be split into routes.py, pnl_service.py, market_service.py. |
| `fed_client.py` | External API dependency | Fetches from CME FedWatch via a JSON endpoint that could change format at any time. No schema validation. |
| `post_trade_monitor.py` | Duplicates exit logic | Has its own 95c rule, 70% gain rule implementation that partially overlaps with `strategy.py/should_exit`. |

---

## PART 2: TRADING LOGIC REVIEW

### Signal Quality

| Module | Assessment |
|--------|------------|
| **Weather** | **STRONG.** Multi-model ensemble (ECMWF 40% + GEFS 40% + ICON 20%) with GHCND bias correction is state-of-the-art. Confidence degradation when NWS unavailable is appropriate. Direction filter (NO-only) backed by 90.4% vs 14.9% backtest win rate. |
| **Crypto** | **MODERATE.** Log-normal band probability is mathematically sound but assumes constant volatility (daily_vol) and zero drift. No momentum, no sentiment beyond smart money wallet scan. Smart money signal (Polymarket leaderboard) adds value but wallet staleness check (>25h) is weak. |
| **Fed** | **WEAK-TO-MODERATE.** Relies on CME FedWatch as "smart money" proxy, but FedWatch is backward-looking (already priced in). The 7-day signal window is good. No independent Fed probability model. |
| **Econ** | **STUB.** `find_econ_opportunities()` returns empty list. Module non-functional. |
| **Geo** | **NON-FUNCTIONAL.** Finds news volume but calculates no edge. Correctly disabled via `GEO_AUTO_TRADE = False`. |

### Edge Calculation

| Aspect | Assessment |
|--------|------------|
| **Formula** | `edge = model_prob - market_implied_prob` is correct. |
| **Bias correction** | Weather: GHCND rolling bias (30-day NOAA vs ERA5) is excellent. Falls back to hardcoded offsets gracefully. |
| **Confidence** | Weather uses `weighted_conf = sum(norm_weights[m] * successful[m]["confidence"])` where confidence = `abs(prob - 0.5) * 2`. This is a measure of ensemble agreement, not prediction accuracy. Fine for filtering, but conflates "agreement" with "calibration". |
| **Systematic errors** | Crypto: daily_vol is hardcoded per asset (0.025 for BTC, 0.045 for XRP). Volatility changes over time — this will under/over-estimate edge during vol regimes. |
| **T-market soft prior** | Correctly implements longshot bias adjustment (YES side confidence * 0.85, NO side * 1.15 for |edge| <= 0.30). However, the implementation in edge_detector.py modifies confidence AFTER the min_edge gate, so a YES signal with edge=0.13 passes the 0.12 threshold but then gets confidence-penalized — potentially below MIN_CONFIDENCE. The order is: edge gate → direction filter → confidence adjustment. This is correct. |

### Sizing & Risk Management

| Aspect | Assessment |
|--------|------------|
| **Kelly fraction** | 6-tier confidence-based Kelly (0.05 to 0.16) is conservative. Max position = 1% of capital per trade (config.MAX_POSITION_PCT = 0.01). Good. |
| **Daily cap** | 70% of total capital max daily deployment (DAILY_CAP_RATIO = 0.70). Per-module caps (weather 7%, crypto 7%, geo 4%, econ 4%). Sound structure. |
| **Open exposure check** | `check_open_exposure` enforces global 70% cap in real-time. Good. |
| **Market impact ceiling** | Spread-based sizing reduction (>7c spread → floor at $25) is excellent Phase 1 implementation. OI cap (5% of open interest) ready for Phase 2. |
| **Position cap coherence** | Weather and crypto both use MAX_POSITION_PCT = 0.01 (1% of capital). With $10k starting capital, max position = $100. But Kelly at 0.16 max fraction × 0.30 edge / 0.30 (1 - win_prob) = 0.16 × 1.0 × $10k = $1600, capped to $100. The cap is binding — Kelly rarely matters. This is fine for capital preservation but limits upside. |

### Exit Rules

| Rule | Assessment |
|------|------------|
| **95c rule** | Exit 100% when bid ≥ 95c. Sound — locks in near-guaranteed profit. |
| **70% gain rule** | Exit 100% when gain ≥ 70% of max upside. Mathematically: `(cur_bid - entry_price) / (100 - entry_price) >= 0.70`. Good risk/reward crystallization. |
| **Near-settlement hold** | Don't exit if < 30 min to settlement. Correct — market will resolve anyway, avoid slippage. |
| **Reversal rule** | Scaled exit (25% / 50% / 100%) when edge collapses by (0.10 / 0.20 / 0.35). Good stop-loss structure. But relies on re-calculating edge from fresh signal — if signal API fails, reversal won't trigger. |
| **Conflict: post_trade_monitor vs strategy.py** | Both implement 95c and 70% gain rules. post_trade_monitor uses `entry_price = entry_rec.get('entry_price') or (100 - round(pos.get('market_prob',0.5)*100))` — different calculation than strategy.py. Could produce inconsistent exits. |

### Direction Bias

| Filter | Assessment |
|--------|------------|
| **NO-only on weather** | `WEATHER_DIRECTION_FILTER = "NO"` backed by backtest: NO=90.4% win rate, YES=14.9%. This is a HUGE edge. Justified. |
| **Shadow logging YES** | YES signals are logged to `logs/weather_yes_shadow.jsonl` for counterfactual analysis. Good. |
| **Crypto direction** | Uses smart money signal (bullish/bearish/neutral) to inform direction but doesn't hard-filter like weather. Reasonable — crypto signal is weaker. |

### Module Readiness (for LIVE)

| Module | Status | Reason |
|--------|--------|--------|
| **Weather** | ✅ **READY** | Multi-model ensemble is robust. Bias correction via GHCND is validated. Direction filter (NO-only) backed by strong backtest. Exit rules are sound. |
| **Crypto** | ⚠️ **NEEDS WORK** | Log-normal model is OK but static daily_vol is a liability. Smart money signal adds value but staleness handling is weak. Recommend adding real-time vol scaling (e.g., 7-day rolling vol from Kraken). |
| **Fed** | ⚠️ **NEEDS WORK** | FedWatch dependency is fragile. 7-day signal window is good. Needs independent probability model (yield curve, Fed fund futures spread). |
| **Econ** | ❌ **DISABLE** | Stub. `find_econ_opportunities()` returns empty list. Should be disabled or removed. |
| **Geo** | ❌ **DISABLE** | No edge signal. Correctly disabled (`GEO_AUTO_TRADE = False`). Leave disabled until LLM-based edge is validated. |

### Overall Assessment

**Is this system ready to go live?**

**CONDITIONALLY YES — for weather module only.** The weather pipeline is production-grade: multi-model ensemble, bias correction, NO-only filter, sound sizing, and robust exit rules.

**TOP 3 THINGS TO FIX BEFORE GOING LIVE:**

1. **P0: Fix `trader.py` undefined config constants.** Add `MAX_POSITION_SIZE = 100.0` and `MAX_DAILY_EXPOSURE = 700.0` to config.py, or delete the legacy fallback path entirely since strategy_size is always provided.

2. **P0: Fix `kalshi_client.py` attribute access bug.** In `__main__` test block, change `m.ticker` → `m.get('ticker')`. This will crash on any test run.

3. **P1: Fix `openmeteo_client.py` hours_since_midnight timezone bug.** The same-day logic uses UTC hour instead of local hour. A 2pm local cutoff will fire at wrong times for non-UTC cities. Parse timezone-aware datetime and convert to local.

---

## APPENDIX: Additional Observations

### Positive Findings
- **Atomic trade logging**: `build_trade_entry` generates UUID trade_id, enforces schema consistency.
- **Rate limiting**: `kalshi_client._get_with_retry` handles 429 with exponential backoff.
- **Orderbook enrichment**: `search_markets` fetches real bid/ask from orderbook endpoint instead of relying on stale REST data.
- **Mode isolation**: `DRY_RUN` derived from `mode.json`, not hardcoded. `_demo_block` prevents accidental live orders.
- **Log rotation**: 90-day retention with `rotate_logs()`.

### Risk Factors
- **Single point of failure**: All weather data flows through Open-Meteo. If their ensemble API degrades, the bot has no fallback except NOAA single probability (much weaker signal).
- **Capital tracking in DEMO**: `get_capital()` sums deposits from `demo_deposits.jsonl` + closed P&L from `pnl_cache.json`. If either file is corrupted, capital is wrong. No integrity check.
- **Time zone complexity**: Markets are in local time, NWS is in local time, Open-Meteo can return UTC or local depending on params, and the bot runs in `America/Los_Angeles`. Multiple timezone conversions increase bug surface area.

---

*Report generated by Opus deep audit subagent. Review recommended before live deployment.*
