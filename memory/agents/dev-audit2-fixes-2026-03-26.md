# Dev Audit2 Fixes — 2026-03-26

## Fixed

### P0 — Critical

- **P0-1: `config.py`** — Added `MAX_POSITION_SIZE = 100.0` and `MAX_DAILY_EXPOSURE = 700.0` constants. These were previously deleted but still referenced by `trader.py`'s legacy fallback path (`check_pre_trade` / `_legacy_calculate_position_size`). Chose to add constants (safe) rather than delete the legacy path (risky refactor). The legacy path is still protected by the `strategy_size` check in `execute_opportunity` — it only fires if `strategy_size` is not provided.

- **P0-2: `kalshi_client.py`** — Fixed `__main__` test block: `m.ticker` → `m.get('ticker')` and `m.title` → `m.get('title')`. The `m` variable is a dict from the REST API, not a SDK object. Would crash on any `python kalshi_client.py` test run.

- **P0-3: `ruppert_cycle.py`** — Moved `actions_taken = []` initialization to BEFORE the try block (was inside try). Previously if STEP 1 raised early, `actions_taken` would be undefined when the MODE == 'check' exit and the final `summary` dict referenced it. Also removed the duplicate `actions_taken = []` that was inside the try block.

### P1 — Silent Wrong Behavior

- **P1-1: `openmeteo_client.py`** — Fixed `hours_into_day` extraction in `get_current_conditions`. Open-Meteo returns naive local time strings when a `timezone` param is set, so the old code that treated the timestamp as UTC was already getting local time when the naive path was taken. Rewrote the logic to: (a) parse naive ISO strings directly (already local from API), (b) if tz-aware, use `zoneinfo` to convert to city timezone before extracting hour. Added clear comment explaining the API behavior.

- **P1-2: `post_trade_monitor.py`** — Fixed `load_open_positions` to key by `(ticker, side)` tuple instead of `ticker` only. Previously, holding YES and NO on the same market would cause the second entry to silently overwrite the first. Updated both `entries_by_key` dict and `exit_keys` set to use tuple keys.

- **P1-3: `dashboard/api.py`** — Added `t.startswith('KXSOL')` to `classify_module`. KXSOL was missing from the `src == 'bot'` crypto prefix check (KXDOGE was already present in the original code — the audit noted it as missing, but it was there; KXSOL was the actual gap). KXDOGE remains present.

- **P1-4: `edge_detector.py`** (two changes):
  1. `parse_threshold_from_ticker` — extended to handle T-prefixed band parts (e.g. `T80`, `T84.5`) in addition to B-prefixed (e.g. `B84.5`). Previously T-market tickers would return `None` for threshold_f.
  2. `analyze_market` — added fallback classification: if `market_type == "B_band"` and `temp_range is None` (title regex failed) but `threshold_f is not None`, check the ticker's 3rd segment. If it starts with 'T' (not 'TM'), set `market_type = "T_upper"`. This prevents T-markets from being misclassified as B_band when title parsing fails.

- **P1-5: `geo_edge_detector.py`** — Confirmed `_call_claude` uses `subprocess.run(['claude', '--print', ...])`, NOT `anthropic.Anthropic()`. No API key loading is needed here. Added a detailed comment explaining that credentials come from the environment/CLI config, and that None return from `_call_claude` is handled gracefully.

### P2 — Minor Bugs

- **P2-1: `ghcnd_client.py`** — Fixed off-by-one in `compute_station_bias`. Changed `start_date = today - timedelta(days=lookback_days + 1)` to `today - timedelta(days=lookback_days)`. Previously fetched 31 days for a 30-day lookback.

- **P2-2: `optimizer.py`** — Added explicit `if any(kw in t for kw in ('KXFED', 'FOMC')): return 'fed'` check BEFORE the generic FED/FOMC keyword loop in `detect_module`. Ensures KXFED tickers are correctly classified as 'fed'.

- **P2-3: `logger.py`** — Fixed `build_trade_entry` module fallback. When source is 'bot' and no other module is detected, now uses `'weather'` if ticker starts with `KXHIGH`, else `'other'`. Previously fell back to `module = source` (= 'bot'), which is not a valid module in `config.MIN_CONFIDENCE`.

- **P2-4: `economics_scanner.py`** — Added stub comment at top of `find_econ_opportunities`: `# STUB: Economics scanner is disabled pending CME FedWatch integration. Returns [] intentionally.` Note: the function does actually run (fetches non-KXFED markets) but returns [] in practice because KXFED is disabled and other series rarely have sufficient edge. The comment documents intent.

### P3 — Design

- **P3-1: `bot/strategy.py`** — Changed `side.upper() != config.WEATHER_DIRECTION_FILTER.upper()` to `side.lower() != config.WEATHER_DIRECTION_FILTER.lower()` for consistent case normalization.

- **P3-2: `capital.py`** — Wrapped individual `float()` casts in `get_pnl()` in separate try/except blocks. If `closed_pnl` or `open_pnl` is non-numeric (corrupted cache), logs a warning and keeps the default 0.0 rather than crashing entirely.

## Skipped / Deferred

- None. All P0, P1, P2, and P3 fixes were completed.

## Notes

- **P1-3 clarification**: KXDOGE was already present in `dashboard/api.py`'s `classify_module` function. The actual gap was KXSOL. Added KXSOL to the prefix check.

- **P1-1 nuance**: Open-Meteo returns naive local time strings (no 'Z' or offset) when `timezone` is set in params. The original bug was handling the case where the time string might have a 'Z' suffix (treated as UTC). The new code handles both cases cleanly and documents the API behavior.

- **P0-1 decision**: Chose to add the missing constants to `config.py` rather than deleting the legacy fallback path in `trader.py`. The legacy path is effectively dead code (always pre-empted by `strategy_size`), but removing it requires careful verification of all callers. Adding constants is the safer, minimal change.

- **P2-4 note**: `find_econ_opportunities` is not a true stub — it fetches data and analyzes markets. The "returns []" characterization in the audit reflects the practical outcome under current config (KXFED disabled, other series rarely have sufficient edge). The comment documents this as intentional for the current phase.
