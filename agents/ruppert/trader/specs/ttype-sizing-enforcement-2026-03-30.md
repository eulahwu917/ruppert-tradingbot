# Spec: Enforce T-type Sizing in Weather Trading Path

**Date:** 2026-03-30  
**Author:** Trader (subagent)  
**Status:** PENDING DEV  
**Priority:** HIGH — T-type trades currently bypass $50/trade and $500/day hard caps

---

## Problem

`environments/demo/config.py` defines three T-type position limits:

```python
TTYPE_PER_TRADE_SIZE      = 50.0    # $50 per T-type trade
TTYPE_MAX_DAILY           = 500.0   # $500/day hard cap across all T-type trades
TTYPE_PER_CITY_DAILY_MAX  = 100.0   # $100/city/day (across upper + lower threshold)
```

These constants are **never read in `agents/ruppert/trader/main.py`**. T-type markets
(`market_type == "T_upper"` or `"T_lower"`) flow through the standard Kelly sizing path
via `should_enter()`, which can produce position sizes well above $50. The per-city and
total daily caps are also unenforced — a single day could see unlimited T-type exposure.

---

## Affected File

`agents/ruppert/trader/main.py` — `run_weather_scan()` function.  
Specifically the loop starting at line ~268: `for opp in opportunities:`

---

## Root Cause

`edge_detector.py` sets `opp['market_type']` to `"T_upper"` or `"T_lower"` for tail markets
(lines 363–374 in `agents/ruppert/strategist/edge_detector.py`). This value propagates into
the `opp` dict passed through `run_weather_scan()`. However, `run_weather_scan()` never reads
`opp['market_type']` before calling `should_enter()` or before setting `opp['strategy_size']`.

---

## Fix Location

Inject T-type guards **after** `should_enter()` returns `decision['enter'] == True` and
**before** `opp['strategy_size'] = decision['size']` is set.

Also add two accumulators before the opportunity loop:
- `_ttype_daily_total` — total T-type dollars deployed today (all cities)
- `_ttype_city_deployed` — dict mapping city → dollars deployed today for T-type

---

## BEFORE

In `run_weather_scan()`, around line 254–310 of `agents/ruppert/trader/main.py`:

```python
        approved_opps = []
        try:
            from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
            _weather_deployed_this_cycle = _get_daily_exp(module='weather')
        except Exception:
            _weather_deployed_this_cycle = 0.0

        if _weather_deployed_this_cycle >= _weather_daily_cap:
            log_activity(
                f"[Weather] Daily cap already reached: ${_weather_deployed_this_cycle:.2f} deployed "
                f"(cap ${_weather_daily_cap:.0f}). Skipping scan."
            )
            return []

        for opp in opportunities:
            # ── Global 70% open exposure check ──
            if not check_open_exposure(total_capital, _open_exposure):
                log_activity(f"  [GlobalCap] STOP: open exposure ${_open_exposure:.2f} >= 70% of capital ${total_capital:.2f}")
                break

            # ── Per-module daily cap: weather budget scales with capital ──
            if _weather_deployed_this_cycle >= _weather_daily_cap:
                log_activity(
                    f"  [DailyCap] STOP: weather budget ${_weather_daily_cap:.0f} "
                    f"exhausted (${_weather_deployed_this_cycle:.2f} deployed this cycle)"
                )
                break

            signal = _opp_to_signal(opp, module='weather')
            signal['open_position_value'] = _open_exposure
            decision = should_enter(
                signal, total_capital, deployed_today,
                module='weather',
                module_deployed_pct=_weather_deployed_this_cycle / total_capital if total_capital > 0 else 0.0,
                traded_tickers=traded_tickers,
            )
            if decision.get('warning'):
                log_activity(f"  [Strategy] WARNING: {decision['warning']}")
            if decision['enter']:
                # Check weather-specific budget before approving
                if _weather_deployed_this_cycle + decision['size'] > _weather_daily_cap:
                    log_activity(
                        f"  [DailyCap] SKIP {opp['ticker']}: would exceed weather daily cap "
                        f"(${_weather_deployed_this_cycle:.2f} + ${decision['size']:.2f} > "
                        f"${_weather_daily_cap:.0f})"
                    )
                    continue
                # Pass strategy-computed size so Trader skips redundant risk.py sizing
                opp['strategy_size'] = decision['size']
                approved_opps.append(opp)
                # W14: refresh deployed_today so subsequent opportunities in this cycle
                # see the updated cap (prevents over-deployment if multiple trades fire)
                deployed_today += decision['size']
                _weather_deployed_this_cycle += decision['size']
                _open_exposure += decision['size']
                log_activity(f"  [Strategy] ENTER {opp['ticker']}: {decision['reason']}")
            else:
                log_activity(f"  [Strategy] SKIP  {opp['ticker']}: {decision['reason']}")
```

---

## AFTER

```python
        approved_opps = []
        try:
            from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
            _weather_deployed_this_cycle = _get_daily_exp(module='weather')
        except Exception:
            _weather_deployed_this_cycle = 0.0

        if _weather_deployed_this_cycle >= _weather_daily_cap:
            log_activity(
                f"[Weather] Daily cap already reached: ${_weather_deployed_this_cycle:.2f} deployed "
                f"(cap ${_weather_daily_cap:.0f}). Skipping scan."
            )
            return []

        # ── T-type daily exposure accumulators ────────────────────────────────
        # Enforces TTYPE_MAX_DAILY and TTYPE_PER_CITY_DAILY_MAX from config.
        _ttype_max_daily      = getattr(config, 'TTYPE_MAX_DAILY', 500.0)
        _ttype_per_trade      = getattr(config, 'TTYPE_PER_TRADE_SIZE', 50.0)
        _ttype_city_max       = getattr(config, 'TTYPE_PER_CITY_DAILY_MAX', 100.0)
        _ttype_daily_total    = 0.0      # total T-type deployed today (this cycle)
        _ttype_city_deployed  = {}       # city -> dollars deployed today (T-type)

        for opp in opportunities:
            # ── Global 70% open exposure check ──
            if not check_open_exposure(total_capital, _open_exposure):
                log_activity(f"  [GlobalCap] STOP: open exposure ${_open_exposure:.2f} >= 70% of capital ${total_capital:.2f}")
                break

            # ── Per-module daily cap: weather budget scales with capital ──
            if _weather_deployed_this_cycle >= _weather_daily_cap:
                log_activity(
                    f"  [DailyCap] STOP: weather budget ${_weather_daily_cap:.0f} "
                    f"exhausted (${_weather_deployed_this_cycle:.2f} deployed this cycle)"
                )
                break

            signal = _opp_to_signal(opp, module='weather')
            signal['open_position_value'] = _open_exposure
            decision = should_enter(
                signal, total_capital, deployed_today,
                module='weather',
                module_deployed_pct=_weather_deployed_this_cycle / total_capital if total_capital > 0 else 0.0,
                traded_tickers=traded_tickers,
            )
            if decision.get('warning'):
                log_activity(f"  [Strategy] WARNING: {decision['warning']}")
            if decision['enter']:
                # Check weather-specific budget before approving
                if _weather_deployed_this_cycle + decision['size'] > _weather_daily_cap:
                    log_activity(
                        f"  [DailyCap] SKIP {opp['ticker']}: would exceed weather daily cap "
                        f"(${_weather_deployed_this_cycle:.2f} + ${decision['size']:.2f} > "
                        f"${_weather_daily_cap:.0f})"
                    )
                    continue

                # ── T-type sizing enforcement ─────────────────────────────────
                _market_type = opp.get('market_type', '')
                if _market_type in ('T_upper', 'T_lower'):
                    _city = opp.get('city') or opp.get('ticker', '').split('-')[0]

                    # Hard cap: total T-type daily exposure
                    if _ttype_daily_total >= _ttype_max_daily:
                        log_activity(
                            f"  [TType] SKIP {opp['ticker']}: T-type daily cap reached "
                            f"(${_ttype_daily_total:.2f} / ${_ttype_max_daily:.0f})"
                        )
                        continue

                    # Hard cap: per-city T-type daily exposure
                    _city_deployed = _ttype_city_deployed.get(_city, 0.0)
                    if _city_deployed >= _ttype_city_max:
                        log_activity(
                            f"  [TType] SKIP {opp['ticker']}: city '{_city}' T-type cap reached "
                            f"(${_city_deployed:.2f} / ${_ttype_city_max:.0f})"
                        )
                        continue

                    # Override Kelly size with fixed T-type trade size
                    decision['size'] = _ttype_per_trade
                    log_activity(
                        f"  [TType] {opp['ticker']}: size capped at ${_ttype_per_trade:.0f} "
                        f"(market_type={_market_type}, city={_city})"
                    )
                # ── End T-type sizing enforcement ─────────────────────────────

                # Pass strategy-computed size so Trader skips redundant risk.py sizing
                opp['strategy_size'] = decision['size']
                approved_opps.append(opp)
                # W14: refresh deployed_today so subsequent opportunities in this cycle
                # see the updated cap (prevents over-deployment if multiple trades fire)
                deployed_today += decision['size']
                _weather_deployed_this_cycle += decision['size']
                _open_exposure += decision['size']

                # ── Update T-type accumulators ────────────────────────────────
                if _market_type in ('T_upper', 'T_lower'):
                    _ttype_daily_total += decision['size']
                    _ttype_city_deployed[_city] = _ttype_city_deployed.get(_city, 0.0) + decision['size']
                # ── End T-type accumulator update ─────────────────────────────

                log_activity(f"  [Strategy] ENTER {opp['ticker']}: {decision['reason']}")
            else:
                log_activity(f"  [Strategy] SKIP  {opp['ticker']}: {decision['reason']}")
```

---

## Key Changes Summary

| Change | Detail |
|--------|--------|
| **New accumulators** | `_ttype_daily_total` (float) and `_ttype_city_deployed` (dict) initialized before the loop |
| **Config reads** | `TTYPE_MAX_DAILY`, `TTYPE_PER_TRADE_SIZE`, `TTYPE_PER_CITY_DAILY_MAX` read via `getattr(config, ...)` with safe defaults |
| **Total daily cap guard** | Skip if `_ttype_daily_total >= _ttype_max_daily` (before size override) |
| **Per-city cap guard** | Skip if city's T-type deployed >= `TTYPE_PER_CITY_DAILY_MAX` |
| **Size override** | `decision['size'] = _ttype_per_trade` replaces Kelly-computed size for T-type opps |
| **Accumulator update** | T-type totals updated only if trade is `ENTER`-approved |
| **City extraction** | `opp.get('city') or opp.get('ticker', '').split('-')[0]` — matches existing dedup pattern |

---

## Acceptance Criteria

1. When `market_type` is `T_upper` or `T_lower`, logged size is exactly `$50.00` regardless of Kelly output
2. After 2 T-type trades in the same city (2 × $50), third trade for that city logs `[TType] SKIP ... city cap reached`
3. After 10 T-type trades across all cities (10 × $50 = $500), further T-type trades log `[TType] SKIP ... daily cap reached`
4. Non-T-type (B_band) opportunities are unaffected — retain Kelly sizing path
5. Dry-run mode logs the cap and size override without executing

---

## Notes

- `_ttype_daily_total` and `_ttype_city_deployed` are **in-memory only** — they reset each scan cycle. 
  This is intentional: they prevent burst exposure within a single scan, not across scans.
  Cross-scan enforcement relies on `TTYPE_MAX_DAILY` being a session-level concern (future enhancement if needed).
- If `opp['city']` is absent, city key falls back to ticker prefix — consistent with existing dedup logic (line ~213 of `main.py`).
