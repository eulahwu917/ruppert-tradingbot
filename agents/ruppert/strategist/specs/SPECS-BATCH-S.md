# STRATEGIST SPECS — Batch S
**Date:** 2026-03-29  
**Author:** Strategist  
**Status:** Ready for Dev  
**Priority order:** S1 → S2 → S4 → S3 → S5 → S6 (S5/S6 are partially wired already — see notes)

---

## S1: Wire Geo Scan into run_full_mode()

**Priority:** CRITICAL  
**Files to modify:**
- `environments/demo/ruppert_cycle.py` — add step 4c in `run_full_mode()`
- `agents/ruppert/trader/main.py` — add `run_geo_trades()` function

---

### Part A — Create `run_geo_trades()` in trader/main.py

Add the following function to `main.py` after `run_fed_scan()` and before `run_econ_scan()`. Model it on `run_fed_scan()`.

**Import note:** `geopolitical_scanner` already imported at the top of `main.py`:
```python
from geopolitical_scanner import run_geo_scan, format_geo_brief
```
No new imports needed in main.py.

**Function to add:**

```python
def run_geo_trades(dry_run=True, traded_tickers=None, open_position_value=0.0):
    """Run geopolitical market scan and execute trades. Returns list of executed opp dicts."""
    if traded_tickers is None:
        traded_tickers = set()

    executed = []

    if not getattr(config, 'GEO_AUTO_TRADE', False):
        log_activity("[Geo] GEO_AUTO_TRADE=False — skipping")
        return executed

    log_activity("[Geo] Starting geopolitical trade scan...")

    try:
        from agents.ruppert.data_scientist.capital import get_capital as _get_geo_capital, get_buying_power as _get_geo_bp

        geo_markets = run_geo_scan()
        if not geo_markets:
            log_activity("[Geo] No geo opportunities returned by scanner")
            return executed

        log_activity(f"[Geo] Scanner returned {len(geo_markets)} market(s)")

        try:
            _geo_capital  = get_capital()
            _geo_deployed = get_daily_exposure()
        except Exception:
            _geo_capital  = 10000.0
            _geo_deployed = 0.0

        _geo_daily_cap = _geo_capital * getattr(config, 'GEO_DAILY_CAP_PCT', 0.04)
        _geo_deployed_this_cycle = 0.0

        try:
            _geo_open_exposure = max(0.0, _geo_capital - get_buying_power())
        except Exception:
            _geo_open_exposure = open_position_value

        trader = Trader(dry_run=dry_run)

        for opp in geo_markets:
            ticker = opp.get('ticker', '')
            if not ticker:
                continue
            if ticker in traded_tickers:
                log_activity(f"  [Geo] Already traded {ticker} — skipping")
                continue

            if not check_open_exposure(_geo_capital, _geo_open_exposure):
                log_activity(f"  [GlobalCap] STOP: open exposure ${_geo_open_exposure:.2f} >= 70% of capital")
                break

            if _geo_deployed_this_cycle >= _geo_daily_cap:
                log_activity(f"  [DailyCap] STOP: geo budget ${_geo_daily_cap:.0f} exhausted")
                break

            side = opp.get('side', 'yes')
            yes_ask = int(opp.get('yes_ask', 50))
            yes_bid = int(opp.get('yes_bid', yes_ask))
            bet_price = yes_ask if side == 'yes' else 100 - yes_ask

            # Geo: hours_to_settlement from opp or fallback to GEO_MIN_DAYS_TO_EXPIRY
            _geo_days = opp.get('days_to_expiry', getattr(config, 'GEO_MIN_DAYS_TO_EXPIRY', 1))
            _geo_hours = max(24.0, float(_geo_days) * 24)

            signal = {
                'edge':                opp.get('edge', 0.0),
                'win_prob':            opp.get('win_prob', opp.get('model_prob', 0.5)),
                'confidence':          min(opp.get('confidence', 0.0),
                                          getattr(config, 'GEO_MAX_CONFIDENCE', 0.85)),
                'hours_to_settlement': _geo_hours,
                'module':              'geo',
                'vol_ratio':           1.0,
                'side':                side,
                'yes_ask':             yes_ask,
                'yes_bid':             yes_bid,
                'open_position_value': _geo_open_exposure,
            }

            decision = should_enter(
                signal, _geo_capital, _geo_deployed,
                module='geo',
                module_deployed_pct=_geo_deployed_this_cycle / _geo_capital if _geo_capital > 0 else 0.0,
                traded_tickers=traded_tickers,
            )

            if not decision['enter']:
                log_activity(f"  [Strategy] SKIP {ticker}: {decision['reason']}")
                continue

            if _geo_deployed_this_cycle + decision['size'] > _geo_daily_cap:
                log_activity(f"  [DailyCap] SKIP {ticker}: would exceed geo daily cap")
                continue

            size = min(decision['size'], check_daily_cap(_geo_capital, _geo_deployed))
            contracts = max(1, int(size / bet_price * 100))
            actual_cost = round(contracts * bet_price / 100, 2)

            trade_opp = {
                'ticker':       ticker,
                'title':        opp.get('title', ticker),
                'side':         side,
                'action':       'buy',
                'yes_price':    yes_ask,
                'market_prob':  yes_ask / 100,
                'noaa_prob':    None,
                'edge':         opp.get('edge'),
                'confidence':   opp.get('confidence'),
                'size_dollars': actual_cost,
                'contracts':    contracts,
                'source':       'geo',
                'module':       'geo',
                'scan_price':   bet_price,
                'fill_price':   bet_price,
                'scan_contracts': contracts,
                'fill_contracts': contracts,
                'note':         opp.get('reasoning', '')[:200],
                'timestamp':    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date':         str(date.today()),
            }
            trade_opp['strategy_size'] = size

            trader.execute_opportunity(trade_opp)

            traded_tickers.add(ticker)
            _geo_deployed_this_cycle += actual_cost
            _geo_open_exposure += actual_cost
            executed.append(trade_opp)
            log_activity(f"  [Geo] ENTERED {ticker} {side.upper()} {contracts}@{bet_price}c ${actual_cost:.2f}")

    except Exception as e:
        log_activity(f"[Geo] ERROR: {e}")
        import traceback
        traceback.print_exc()

    log_activity(f"[Geo] Done — {len(executed)} trade(s) executed")
    return executed
```

---

### Part B — Wire into run_full_mode() in ruppert_cycle.py

**Location:** In `run_full_mode()`, after the STEP 4b Fed block (after the `# STEP 4b` block and before `# STEP 5: SECURITY AUDIT`).

**Import pattern:** Other demo-root scanners in ruppert_cycle.py are imported inline. However, `run_geo_trades` lives in `agents.ruppert.trader.main`, which follows the pattern used for `run_weather_scan`, `run_crypto_scan`, and `run_fed_scan`. Use the same pattern.

**Insert after the STEP 4b block:**

```python
    # STEP 4c: GEOPOLITICAL SCAN
    print("\n[4c] Scanning for geopolitical opportunities...")
    new_geo = []
    if getattr(config, 'GEO_AUTO_TRADE', False):
        try:
            from agents.ruppert.trader.main import run_geo_trades as _run_geo_trades
            # Refresh open exposure after Fed trades
            state.open_position_value += sum(t.get('size_dollars', 0) for t in new_fed)
            new_geo = _run_geo_trades(
                dry_run=state.dry_run,
                traded_tickers=state.traded_tickers,
                open_position_value=state.open_position_value,
            )
            if new_geo:
                print(f"  {len(new_geo)} geo trade(s) executed")
                for t in new_geo:
                    print(f"    {t.get('ticker')} {t.get('side','').upper()} edge={t.get('edge',0)*100:.0f}%")
            else:
                print("  No geo opportunities above threshold")
        except Exception as e:
            print(f"  Geo scan error: {e}")
            import traceback; traceback.print_exc()
    else:
        print("  GEO_AUTO_TRADE=False — skipping")

    state.open_position_value += sum(t.get('size_dollars', 0) for t in new_geo)
```

**Update summary dict** — change:
```python
    summary = {
        'weather_trades': len(new_weather) if new_weather else 0,
        'crypto_trades':  len(new_crypto) if new_crypto else 0,
        'long_horizon_trades': len(new_long_horizon) if new_long_horizon else 0,
        'fed_trades':     len(new_fed) if new_fed else 0,
        'smart_money':    direction,
        'auto_exits':     len(state.actions_taken),
    }
```
to:
```python
    summary = {
        'weather_trades': len(new_weather) if new_weather else 0,
        'crypto_trades':  len(new_crypto) if new_crypto else 0,
        'long_horizon_trades': len(new_long_horizon) if new_long_horizon else 0,
        'fed_trades':     len(new_fed) if new_fed else 0,
        'geo_trades':     len(new_geo) if new_geo else 0,
        'smart_money':    direction,
        'auto_exits':     len(state.actions_taken),
    }
```

**Update the print summary line** — change:
```python
    print(f"  Weather: {summary['weather_trades']} new | Crypto: {summary['crypto_trades']} new | LongHorizon: {summary['long_horizon_trades']} new | Fed: {summary['fed_trades']} new")
```
to:
```python
    print(f"  Weather: {summary['weather_trades']} new | Crypto: {summary['crypto_trades']} new | LongHorizon: {summary['long_horizon_trades']} new | Fed: {summary['fed_trades']} new | Geo: {summary['geo_trades']} new")
```

**Update the SCAN_COMPLETE log_event call** — add `'geo_trades': summary['geo_trades']` to the dict:
```python
        log_event('SCAN_COMPLETE', {
            'mode': 'full',
            'weather_trades': summary['weather_trades'],
            'crypto_trades': summary['crypto_trades'],
            'long_horizon_trades': summary.get('long_horizon_trades', 0),
            'fed_trades': summary['fed_trades'],
            'geo_trades': summary['geo_trades'],        # ADD THIS LINE
            'smart_money': summary['smart_money'],
            'summary': _scan_msg,
        })
```

**Update the Telegram scan message** — add a geo line. Change the `_scan_msg` f-string to include:
```python
        _geo_trades = summary.get('geo_trades', 0)
        _scan_msg = (
            f"\U0001f4ca Ruppert Scan \u2014 {_time_str} PDT\n\n"
            f"\U0001f324 Weather: {_w_opps} opportunities | {_w_trades} trades placed\n"
            f"\u20bf Crypto: {_c_dir} | {_c_opps} opportunities | {_c_trades} trades placed\n"
            f"\U0001f30d Geo: {_geo_trades} trade(s) placed\n"
            f"\U0001f3db Fed: {_fed_status}"
            f"{_15m_block}\n\n"
            f"\U0001f4b0 Capital: {_cap_line}"
        )
```

**Test:**
1. Set `GEO_AUTO_TRADE=True` in config (already True)
2. Run `python ruppert_cycle.py full` in dry_run mode
3. Verify stdout shows `[4c] Scanning for geopolitical opportunities...`
4. Verify SCAN_COMPLETE event in cycle_log.jsonl contains `geo_trades` key
5. Verify Telegram message includes "🌍 Geo:" line
6. Verify `run_geo_trades` is importable from `agents.ruppert.trader.main`
7. If geopolitical_scanner returns opportunities, verify trades appear in trades_YYYY-MM-DD.jsonl with `source: geo`

---

## S2: Fix Econ bet_direction Case Bug (uppercase YES/NO → lowercase)

**Priority:** CRITICAL  
**Files to modify:**
- `environments/demo/ruppert_cycle.py` — `run_econ_prescan_mode()`

---

**The bug:** `economics_scanner` returns `bet_direction` as `'YES'` or `'NO'` (uppercase). The line:
```python
side = opp.get('bet_direction', 'yes')
```
assigns `side = 'YES'`. Then two conditional expressions:
```python
mkt_price = int(opp.get('yes_ask', 50) if side == 'yes' else opp.get('no_ask', 50))
bet_price = mkt_price if side == 'yes' else 100 - mkt_price
```
always take the `else` branch because `'YES' != 'yes'`. Result: wrong price is used for every econ trade. The trade dict also stores `'side': 'YES'` which the Kalshi `place_order` call receives — Kalshi API requires lowercase.

**Fix:** One-line change in `run_econ_prescan_mode()`.

**Change this line:**
```python
side = opp.get('bet_direction', 'yes')
```
**To:**
```python
side = opp.get('bet_direction', 'yes').lower()
```

**Location:** Inside the `for opp in _econ_opps:` loop in `run_econ_prescan_mode()`, immediately after the `if ticker in state.traded_tickers:` block.

**Kalshi side parameter:** Confirmed — `KalshiClient.place_order(ticker, side, price, contracts)` passes `side` directly into the Kalshi REST API order payload. Kalshi REST API v2 expects lowercase `'yes'` or `'no'`. No other change needed to kalshi_client.py.

**Test:**
1. Run `python ruppert_cycle.py econ_prescan` in dry_run mode when an econ release is scheduled today
2. Verify `side` printed in the `[DEMO] BUY` log line is `YES` or `NO` (uppercase) — it should now be `yes` or `no`
3. Verify `bet_price` in log is numerically correct: for a YES bet, bet_price should equal yes_ask; for a NO bet, bet_price should equal `100 - yes_ask`
4. Verify trade record in trades_YYYY-MM-DD.jsonl has `"side": "yes"` or `"side": "no"` (lowercase)
5. In live mode: verify no Kalshi API error on `place_order` due to invalid side value

---

## S3: Unify scored_predictions.jsonl Schema

**Priority:** HIGH  
**Files to modify:**
- `environments/demo/prediction_scorer.py` — `score_new_settlements()`

---

**The problem:**
- `prediction_scorer.py` writes `actual_result` (string from settlement_result) — not `outcome` or `brier_score`
- `brier_tracker.py` writes `outcome` (int 0/1) and `brier_score` (float) — correct schema
- `optimizer.py` reads `outcome` — gets `None` from all prediction_scorer records
- Both write to the same file `logs/scored_predictions.jsonl` with incompatible schemas

**Canonical schema** (all fields, all writers must conform):
```json
{
  "domain":          "weather",
  "ticker":          "KXHIGHMIA-26MAR11-B84",
  "predicted_prob":  0.7823,
  "outcome":         1,
  "brier_score":     0.0477,
  "edge":            0.1540,
  "confidence":      0.6200,
  "date":            "2026-03-11",
  "settlement_date": "2026-03-11",
  "pnl":             2.45
}
```
- `outcome`: int `1` = our side won (profitable), `0` = lost. Derived from `settlement_result`.
- `brier_score`: float, computed as `round((outcome - predicted_prob) ** 2, 4)`.
- Remove `actual_result` field entirely from prediction_scorer output.
- Remove `entry_price` and `city` from scored_predictions (keep in raw trade log; they don't belong in the canonical prediction record).

**How to derive `outcome` from `settlement_result`:**
The `settlement_result` field in exit/settle records is a string. Treat as:
- `'yes'` or `'YES'` or `'1'` or `'true'` or `'True'` → `1`
- `'no'` or `'NO'` or `'0'` or `'false'` or `'False'` → `0`
- Anything else (None, empty, unknown) → `None` (do not compute brier_score; write `None` for both)

**Change in `score_new_settlements()`** — replace the `scored` dict construction:

**Remove:**
```python
        scored = {
            "domain":          module or None,
            "ticker":          ticker,
            "predicted_prob":  round(float(predicted_prob), 4) if predicted_prob is not None else None,
            "actual_result":   rec.get('settlement_result') or None,
            "edge":            round(float(buy_rec.get('edge', 0)), 4) if buy_rec.get('edge') is not None else None,
            "confidence":      round(float(buy_rec.get('confidence', 0)), 4) if buy_rec.get('confidence') is not None else None,
            "entry_price":     buy_rec.get('fill_price') or buy_rec.get('scan_price') or None,
            "pnl":             round(float(rec.get('pnl', 0)), 2) if rec.get('pnl') is not None else None,
            "city":            city,
            "date":            trade_date,
            "settlement_date": rec.get('date', trade_date),
        }
```

**Replace with:**
```python
        # Derive outcome (int 0/1) from settlement_result
        _settlement_result = rec.get('settlement_result')
        if _settlement_result is not None:
            _sr_str = str(_settlement_result).strip().lower()
            if _sr_str in ('yes', '1', 'true'):
                _outcome = 1
            elif _sr_str in ('no', '0', 'false'):
                _outcome = 0
            else:
                _outcome = None
        else:
            _outcome = None

        # Compute Brier score
        _brier = None
        if _outcome is not None and predicted_prob is not None:
            _brier = round((_outcome - float(predicted_prob)) ** 2, 4)

        scored = {
            "domain":          module or None,
            "ticker":          ticker,
            "predicted_prob":  round(float(predicted_prob), 4) if predicted_prob is not None else None,
            "outcome":         _outcome,
            "brier_score":     _brier,
            "edge":            round(float(buy_rec.get('edge', 0)), 4) if buy_rec.get('edge') is not None else None,
            "confidence":      round(float(buy_rec.get('confidence', 0)), 4) if buy_rec.get('confidence') is not None else None,
            "date":            trade_date,
            "settlement_date": rec.get('date', trade_date),
            "pnl":             round(float(rec.get('pnl', 0)), 2) if rec.get('pnl') is not None else None,
        }
```

**Migration decision:** Go forward only. Existing records in `scored_predictions.jsonl` with `actual_result` instead of `outcome`/`brier_score` will remain as-is (they predate the fix). The optimizer will continue to get `None` for those records. **Do not attempt to migrate existing records** — risk of data corruption is not worth it for DEMO data. After 30+ new scored records accumulate with the correct schema, the optimizer will have sufficient data. If David wants a migration later, that's a separate task.

**Also update brier_tracker.py** to confirm it writes to the same canonical schema — currently it does write `outcome` and `brier_score` which is correct, but it also writes extra fields (`ts`, `market_price`, `side`, `resolved_at`) not in the canonical schema. These extra fields are harmless (optimizer ignores unknown keys). No change needed to brier_tracker.py.

**Test:**
1. Manually create a fake exit/settle record in today's trade log with `settlement_result: "yes"` and a matching buy record with `noaa_prob: 0.75`
2. Run `python -m environments.demo.prediction_scorer`
3. Open `logs/scored_predictions.jsonl` — new record should have:
   - `"outcome": 1`
   - `"brier_score": 0.0625` (i.e., (1 - 0.75)^2)
   - No `"actual_result"` key
   - No `"city"` or `"entry_price"` key
4. Run optimizer on the file — confirm `outcome` is not None for new records

---

## S4: Enforce Per-Module MIN_CONFIDENCE in strategy.py

**Priority:** HIGH  
**Files to modify:**
- `agents/ruppert/strategist/strategy.py` — `should_enter()`

---

**The bug:** `strategy.py` has a module-level constant `MIN_CONFIDENCE = 0.25` and uses it as a universal gate. `config.MIN_CONFIDENCE` is a dict `{'weather': 0.25, 'crypto': 0.50, 'fed': 0.55, 'geo': 0.50}` that is never consulted. Crypto/fed/geo trades can enter with confidence as low as 0.25 when their module minimums are 0.50–0.55.

**Fix:** After the existing universal confidence check in `should_enter()`, add a per-module lookup.

**Locate this block in `should_enter()`:**
```python
    # --- Confidence gate ---
    if confidence < MIN_CONFIDENCE:
        return {'enter': False, 'size': 0.0,
                'reason': f'low_confidence ({confidence:.2f} < {MIN_CONFIDENCE})'}
```

**Insert immediately after it:**
```python
    # --- Per-module confidence gate ---
    # config.MIN_CONFIDENCE is a dict; fall back to universal MIN_CONFIDENCE if module not listed
    _module_min_conf = getattr(config, 'MIN_CONFIDENCE', {})
    if isinstance(_module_min_conf, dict):
        _per_module_thresh = _module_min_conf.get(signal_module, MIN_CONFIDENCE)
    else:
        _per_module_thresh = MIN_CONFIDENCE  # safety: config.MIN_CONFIDENCE not a dict
    if confidence < _per_module_thresh:
        return {'enter': False, 'size': 0.0,
                'reason': f'low_confidence_module ({confidence:.2f} < {_per_module_thresh} for {signal_module})'}
```

**Design notes:**
- The universal `MIN_CONFIDENCE = 0.25` check stays as the first gate (fast fail for obviously uncalibrated signals)
- The per-module check runs second — it catches modules with stricter requirements
- `getattr(config, 'MIN_CONFIDENCE', {})` handles the case where the config key is absent
- `isinstance` guard handles the case where someone sets `MIN_CONFIDENCE` to a float in config (backward compatible)
- `signal_module` is already extracted at the top of `should_enter()` as `signal_module = signal.get('module', 'unknown')`

**Test:**
1. Call `should_enter()` with a crypto signal where `confidence=0.35` (above universal 0.25, below crypto minimum 0.50):
   - Expected: `enter=False`, reason contains `low_confidence_module`
2. Call `should_enter()` with a weather signal where `confidence=0.30` (above weather minimum 0.25):
   - Expected: `enter=True` (if edge/other gates pass)
3. Call `should_enter()` with a fed signal where `confidence=0.50` (below fed minimum 0.55):
   - Expected: `enter=False`, reason contains `low_confidence_module`
4. Call `should_enter()` with a signal where `module='unknown_module'` and `confidence=0.30`:
   - Expected: falls back to universal `MIN_CONFIDENCE=0.25` — should pass confidence gate
5. Add unit test assertions to `strategy.py __main__` block if QA wants a regression harness

---

## S5: Wire baselines.py into Execution Paths

**Priority:** HIGH  
**Files to modify:**
- `agents/ruppert/trader/main.py` — `run_fed_scan()`, `run_crypto_scan()`

---

**Context check:** After reading the actual code:
- `log_always_no_weather()` IS already wired in `run_weather_scan()` (loop before strategy gate — correct per docstring). No change needed.
- `log_uniform_sizing()` is NOT wired anywhere. Needs to be added.
- `log_follow_cme_fed()` is NOT wired anywhere. Needs to be added.

**Function signatures from baselines.py:**
```python
def log_always_no_weather(ticker: str, no_price: float, actual_action: str, actual_price: float)
    # no_price: float 0-1 (e.g. 0.45 for 45c)
    # actual_price: float 0-1

def log_follow_cme_fed(ticker: str, cme_prob: float, market_price: float,
                       actual_action: str, actual_price: float,
                       ensemble_prob: float = None)
    # cme_prob: float 0-1 (CME FedWatch probability)
    # market_price: float 0-1 (Kalshi yes_ask / 100)

def log_uniform_sizing(ticker: str, domain: str, actual_action: str,
                       actual_price: float, actual_size: float,
                       uniform_size: float = 10.0)
    # actual_price: float 0-1
    # actual_size: float dollars (Kelly-computed)
    # uniform_size: float dollars (default $10.0)
```

---

### Change 1 — Wire `log_uniform_sizing` into `run_crypto_scan()`

**Location:** In `run_crypto_scan()`, inside the `for t in new_crypto[:3]:` loop, after `trader.execute_opportunity(opp)` and before `traded_tickers.add(t['ticker'])`.

**Insert:**
```python
            # Baseline: log uniform sizing vs actual Kelly sizing
            try:
                from baselines import log_uniform_sizing
                log_uniform_sizing(
                    ticker=t['ticker'],
                    domain='crypto',
                    actual_action=t['side'],
                    actual_price=t['price'] / 100,
                    actual_size=actual_cost,
                )
            except Exception:
                pass
```

---

### Change 2 — Wire `log_follow_cme_fed` and `log_uniform_sizing` into `run_fed_scan()`

**Location:** In `run_fed_scan()`, after `executed.append(opp)` inside the `else:` block where the trade is executed.

The `fed_signal` dict from `_run_fed_scan_inner()` contains:
- `fed_signal.get('prob')` — this is the CME FedWatch / Polymarket blended probability
- `fed_signal.get('market_price')` — Kalshi market price (float 0-1)
- `fed_signal.get('ensemble_prob')` — ensemble probability (may be same as prob)

**Insert after `executed.append(opp)`:**
```python
                    # Baseline: log what pure CME-follow would have done
                    try:
                        from baselines import log_follow_cme_fed, log_uniform_sizing
                        _cme_prob = fed_signal.get('prob', 0.5)           # CME/blended prob
                        _mkt_price_f = fed_signal.get('market_price', 0.5) # Kalshi price 0-1
                        log_follow_cme_fed(
                            ticker=ticker,
                            cme_prob=_cme_prob,
                            market_price=_mkt_price_f,
                            actual_action=side,
                            actual_price=bet_price / 100,
                            ensemble_prob=fed_signal.get('ensemble_prob'),
                        )
                        # Baseline: uniform sizing vs Kelly
                        log_uniform_sizing(
                            ticker=ticker,
                            domain='fed',
                            actual_action=side,
                            actual_price=bet_price / 100,
                            actual_size=actual_cost,
                        )
                    except Exception:
                        pass
```

---

### Change 3 — Wire `log_uniform_sizing` into `run_weather_scan()`

**Location:** In `run_weather_scan()`, inside the `for opp in approved_opps:` loop after `trader.execute_all(approved_opps)`. Actually since `execute_all` runs as a batch, wire it in the existing `for opp in approved_opps:` loop that already calls `log_prediction`.

**The existing loop after `trader.execute_all(approved_opps)`:**
```python
                for opp in approved_opps:
                    try:
                        from brier_tracker import log_prediction
                        log_prediction(...)
                    except Exception:
                        pass
```

**Add `log_uniform_sizing` inside the same loop:**
```python
                for opp in approved_opps:
                    try:
                        from brier_tracker import log_prediction
                        log_prediction(
                            domain='weather',
                            ticker=opp.get('ticker', ''),
                            predicted_prob=opp.get('win_prob', opp.get('prob', 0.5)),
                            market_price=opp.get('market_price', opp.get('yes_ask', 50) / 100),
                            edge=opp.get('edge', 0),
                            side=opp.get('side', '')
                        )
                    except Exception:
                        pass
                    # Baseline: uniform sizing vs Kelly
                    try:
                        from baselines import log_uniform_sizing
                        _actual_price_f = opp.get('yes_ask', 50) / 100 if opp.get('side') == 'yes' \
                                          else (100 - opp.get('yes_ask', 50)) / 100
                        log_uniform_sizing(
                            ticker=opp.get('ticker', ''),
                            domain='weather',
                            actual_action=opp.get('side', 'no'),
                            actual_price=_actual_price_f,
                            actual_size=opp.get('strategy_size', opp.get('size_dollars', 0)),
                        )
                    except Exception:
                        pass
```

**Test:**
1. Run `python -m agents.ruppert.trader.main --weather` in dry_run
2. Verify `logs/baselines.jsonl` has new entries with `baseline_type: "always_no_weather"` AND `baseline_type: "uniform_sizing"` for weather trades
3. Run `python ruppert_cycle.py full` in dry_run when Fed is in signal window
4. Verify `logs/baselines.jsonl` has `baseline_type: "follow_cme_fed"` and `baseline_type: "uniform_sizing"` for Fed trades
5. Verify `baseline_price` and `actual_price` are floats in 0–1 range (not cents)

---

## S6: Wire brier_tracker.log_prediction() for Crypto and Fed

**Priority:** HIGH  
**Files to modify:**
- `agents/ruppert/trader/main.py` — `run_crypto_scan()`, `run_fed_scan()`

---

**Context check:** After reading the actual code:
- `log_prediction()` IS already called for weather trades in `run_weather_scan()` (inside the `for opp in approved_opps:` loop after `trader.execute_all()`). No change needed for weather.
- `log_prediction()` is NOT called anywhere in `run_crypto_scan()`.
- `log_prediction()` is NOT called anywhere in `run_fed_scan()`.

**Function signature from brier_tracker.py:**
```python
def log_prediction(domain: str, ticker: str, predicted_prob: float,
                   market_price: float, edge: float, side: str = "",
                   extra: dict = None):
    # domain: 'weather' | 'crypto' | 'fed' | 'geo' | 'econ'
    # predicted_prob: Model's estimated WIN probability (0-1)
    # market_price: Market price at time of entry (0-1) — NOT cents
    # edge: predicted_prob - market_price
    # side: 'yes' or 'no'
```

---

### Change 1 — Wire into `run_crypto_scan()`

**Location:** After `trader.execute_opportunity(opp)` in the `for t in new_crypto[:3]:` loop, alongside the baselines call (S5 Change 1).

**Insert:**
```python
            # Log Brier prediction at trade entry
            try:
                from brier_tracker import log_prediction
                log_prediction(
                    domain='crypto',
                    ticker=t['ticker'],
                    predicted_prob=t['prob_model'],         # model's WIN probability
                    market_price=t['yes_ask'] / 100,        # Kalshi yes_ask as 0-1 float
                    edge=t['edge'],
                    side=t['side'],
                )
            except Exception:
                pass
```

**Field mapping for crypto:**
- `predicted_prob` → `t['prob_model']` (log-normal band probability from `band_prob()`)
- `market_price` → `t['yes_ask'] / 100` (market's implied probability)
- `edge` → `t['edge']` (already computed as `best_edge`)
- `side` → `t['side']` (already lowercase `'yes'` or `'no'`)

---

### Change 2 — Wire into `run_fed_scan()`

**Location:** After `executed.append(opp)` in the trade execution block, alongside the baselines calls (S5 Change 2).

**Insert into the same try/except block or adjacent one:**
```python
                    # Log Brier prediction at trade entry
                    try:
                        from brier_tracker import log_prediction
                        log_prediction(
                            domain='fed',
                            ticker=ticker,
                            predicted_prob=fed_signal.get('prob', 0.5),         # model WIN prob
                            market_price=fed_signal.get('market_price', 0.5),   # Kalshi price 0-1
                            edge=fed_signal.get('edge', 0.0),
                            side=side,
                        )
                    except Exception:
                        pass
```

**Field mapping for fed:**
- `predicted_prob` → `fed_signal.get('prob', 0.5)` (CME/Polymarket blended probability)
- `market_price` → `fed_signal.get('market_price', 0.5)` (Kalshi market implied prob, 0-1)
- `edge` → `fed_signal.get('edge', 0.0)`
- `side` → `side` (already lowercase — from `fed_signal.get("direction", "yes")`)

---

### Change 3 — Wire into `run_geo_trades()` (new function from S1)

Add `log_prediction` call in `run_geo_trades()` after `trader.execute_opportunity(trade_opp)`:

```python
            # Log Brier prediction at trade entry
            try:
                from brier_tracker import log_prediction
                log_prediction(
                    domain='geo',
                    ticker=ticker,
                    predicted_prob=opp.get('win_prob', opp.get('model_prob', 0.5)),
                    market_price=yes_ask / 100,
                    edge=opp.get('edge', 0.0),
                    side=side,
                )
            except Exception:
                pass
```

**Test:**
1. Run `python -m agents.ruppert.trader.main --weather` (weather already wired — confirm baseline)
2. Run crypto scan in dry_run with any crypto opportunity
3. Verify `logs/predictions.jsonl` has new entry with `domain: "crypto"`, `outcome: null`, `brier_score: null`
4. Run fed scan in dry_run when in FOMC signal window
5. Verify `logs/predictions.jsonl` has new entry with `domain: "fed"`
6. Run geo scan in dry_run
7. Verify `logs/predictions.jsonl` has new entry with `domain: "geo"`
8. Verify `predicted_prob` is in 0–1 range (not a percentage) for all entries
9. Simulate a contract resolution: call `brier_tracker.score_prediction(ticker, outcome=1)` manually for a crypto ticker — verify `scored_predictions.jsonl` gets a new entry with non-None `brier_score`

---

## Implementation Order

Dev should implement in this sequence to minimize cross-dependencies:

1. **S2** (one-line fix, isolated, unblock econ trades immediately)
2. **S4** (one-location change in strategy.py, no dependencies)
3. **S3** (prediction_scorer schema change, isolated)
4. **S1** (new function + wiring — biggest change, needs S4 working first so geo trades obey confidence gate)
5. **S6** (add log_prediction calls — do after S1 so geo is also covered)
6. **S5** (add baseline calls — last, lowest risk)

Each spec is independently deployable. QA can verify each in isolation before merging the next.
