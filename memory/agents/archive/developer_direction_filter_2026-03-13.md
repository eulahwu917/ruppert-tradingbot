# Developer Summary — Direction Filter & Confidence Gate
**Date:** 2026-03-13
**Task:** Apply Optimizer backtest recommendations to DEMO bot
**SA:** SA-2 Developer (dev-direction-filter session)
**Working dir:** `ruppert-tradingbot-demo/` (LIVE untouched)

---

## Changes Applied

### CHANGE 1: `ruppert-tradingbot-demo/config.py`
- Added `WEATHER_DIRECTION_FILTER = "NO"` — directs strategy to only take NO positions on weather markets (backtest: NO=90.4% win, YES=14.9%)
- Added `MIN_CONFIDENCE` dict (was not present):
  ```python
  MIN_CONFIDENCE = {
      'weather': 0.667,
      'crypto':  0.50,
      'fed':     0.55,
  }
  ```
  Note: `MIN_EDGE` dict does not exist in `config.py` (it lives in `bot/strategy.py`). No `MIN_EDGE` dict was added to config.py — the existing scalar `MIN_EDGE_THRESHOLD = 0.12` was left unchanged. Weather edge updated in strategy.py (see Change 2).

---

### CHANGE 2: `ruppert-tradingbot-demo/bot/strategy.py`
- Added `import config` to imports (was missing; needed for `WEATHER_DIRECTION_FILTER`)
- Updated `MIN_EDGE['weather']` from `0.15` → `0.30` (raising weather edge threshold per backtest)
- Added direction filter block inside `should_enter()`, immediately after the edge gate:
  ```python
  # Direction filter: only trade NO on weather (backtest validation 2026-03-13)
  direction = signal.get('direction', '')
  if module == 'weather' and config.WEATHER_DIRECTION_FILTER:
      if direction.upper() != config.WEATHER_DIRECTION_FILTER.upper():
          return {'enter': False, 'size': 0.0,
                  'reason': f'direction_filter: weather only bets {config.WEATHER_DIRECTION_FILTER}, got {direction}'}
  ```
  Uses the already-extracted `module` variable (from `signal.get('module', 'unknown')`) — no duplicate extraction needed.

---

### CHANGE 3: `ruppert-tradingbot-demo/edge_detector.py`
- Added confidence gate in `analyze_market()` using `config.MIN_CONFIDENCE`, placed immediately before the edge calculation block (after all confidence adjustments including NWS degradation and T-market prior):
  ```python
  min_conf = getattr(config, 'MIN_CONFIDENCE', {}).get('weather', 0.50)
  if confidence < min_conf:
      logger.info(...)
      return None
  ```
- The existing `MIN_ENSEMBLE_CONFIDENCE` check was NOT removed — it uses a different signal_src string (`"open_meteo_ensemble"` vs actual `"open_meteo_multi_model"`) and effectively never fires for the primary path. This is a pre-existing bug; left unchanged per scope rules.
- `config` was already imported in `edge_detector.py`.

---

## Validation
All three files passed `ast.parse()` — no syntax errors.

## Notes for QA
- `bot/strategy.py`: the direction filter triggers when `signal['direction']` is missing/empty (returns `''`). If weather modules don't yet populate `direction`, ALL weather trades will be blocked. Modules should emit `direction: 'no'` or `direction: 'yes'` on their signal dicts. **Recommend QA verifies signal contract.**
- `MIN_EDGE['weather']` in `strategy.py` raised to 0.30. This is a significant tightening — fewer weather trades will qualify. Expected.
- `MIN_CONFIDENCE['weather'] = 0.667` in config is stricter than the old scalar `MIN_CONFIDENCE = 0.50` in strategy.py. Strategy.py's `MIN_CONFIDENCE` scalar remains at `0.50` (universal gate); the `edge_detector.py` gate at `0.667` filters upstream before signals reach strategy.
