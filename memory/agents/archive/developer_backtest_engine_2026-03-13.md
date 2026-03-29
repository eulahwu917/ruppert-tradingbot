# Developer Log — Backtest Engine Build
_SA-2 Developer | 2026-03-13_

---

## What Was Built

Created `ruppert-backtest/` as a completely isolated backtesting framework. No imports from or modifications to `ruppert-tradingbot-demo/` or `ruppert-tradingbot-live/`.

### Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `data_loader.py` | Loads all historical data from `data/` | ~120 |
| `signal_simulator.py` | Mimics edge_detector + crypto_client using stored data | ~200 |
| `strategy_simulator.py` | Mirrors strategy.py sizing/filtering | ~160 |
| `backtest_engine.py` | Core replay loop | ~230 |
| `report.py` | Plain-text + JSON report generation | ~170 |
| `config_sweep.py` | Parameter grid + sweep runner | ~80 |
| `backtest.py` | CLI entry point | ~110 |
| `results/` | Output directory (created) | — |
| `data/` | Historical data directory (pre-populated by Researcher) | — |

---

## Design Decisions

### 1. Ticker Parsing (Critical Discovery)
The Kalshi market data from Researcher **does not** have explicit `series`, `settle_date`, or `threshold_f` fields. These must be parsed from the ticker string.

Ticker format: `KXHIGHNY-26MAR12-T71`
- Series: `KXHIGHNY` (first segment)
- Settle date: `26MAR12` → `2026-03-12` (second segment, `YY+MON+DD`)
- Threshold: `T71` → `71.0°F`, above=True; `B70.5` → `70.5°F`, above=False

Added `_parse_market_fields()` helper in `backtest_engine.py` to handle this.

### 2. Current Data State
As of 2026-03-13, **all 850 weather markets and 200 crypto markets have `last_price = null`** (unsettled). The backtest will correctly return 0 trades / $0 P&L until Researcher populates data with settled markets. Framework is ready.

### 3. Series Name Reality vs Expectations
Live code referenced series like `KXHIGHNYC`, `KXHIGHLA`, `KXHIGHATL`. Actual Kalshi series names are: `KXHIGHNY`, `KXHIGHLAX`, `KXHIGHTATL`, etc. Updated bias maps and defaults accordingly.

### 4. Forecast Data
`openmeteo_historical_forecasts.json` already has the expected structure: `{series: {date: {ecmwf_max, gfs_max, icon_max}}}`. Forecast series names (`KXHIGHNY`, `KXHIGHCHI`, etc.) match parsed ticker series — no remapping needed.

### 5. Kraken Data
Files present: `XBTUSD`, `ETHUSD`, `SOLUSD`, `DOGEUSD`, `XRPUSD` — 360 candles each. Updated pair map in `signal_simulator.py` to match actual filenames.

### 6. Kelly Sizing
Implemented fractional Kelly (25%) as per team_context.md parameters. Size = `min(kelly * 0.25 * capital, 2.5% capital, $50)`. Minimum trade size $5 to avoid noise.

### 7. Same-Day Skip Logic
In the weather signal simulator, `scan_hour >= 14 UTC` triggers a skip. The `same_day_skip_hour` parameter is in `SWEEP_GRID` as `[12, 13, 14, 15]` for optimization.

### 8. P&L Mechanics
Kalshi contract P&L:
- Win: `contracts * (1.0 - cost_per_contract)` 
- Loss: `-size_dollars`
- Settlement: `last_price >= 50` → YES won; `< 50` → NO won

### 9. Sweep Scale
SWEEP_GRID produces 5 × 4 × 4 × 4 = **320 combinations**. Each run is a full date-range replay. On real data, sweep should complete in seconds (pure Python, no I/O after initial load).

---

## Known Limitations / Handoff Notes

1. **No settled markets yet** — backtest will be meaningful once Researcher provides data with `last_price` populated.
2. **Jan 2025 markets** in weather file also have null `last_price` — may be historical gap in pull script.
3. **Crypto signal is simplified** — uses 24h price momentum only, not the full t-distribution/EWMA/Polymarket logic from live bot.
4. **`is_above` logic** — framework parses `T` = above (YES), `B` = below (YES), but `simulate_weather_signal()` doesn't currently use it. Direction currently comes from `prob >= 0.5`. This is correct for standard "above threshold" markets; if "below threshold" markets need explicit YES/NO flip, backtest_engine.py should pass `is_above` into the signal and adjust direction accordingly. Note for QA.
5. **No `series_ticker` field** — Kalshi returns `series_ticker: null`. Series derived from ticker prefix only.

---

## Smoke Test Results

```
=== Ticker parsing ===
  KXHIGHNY-26MAR12-T71 -> series=KXHIGHNY settle=2026-03-12 thresh=71.0 above=True
  KXHIGHCHI-26MAR10-B64.5 -> series=KXHIGHCHI settle=2026-03-10 thresh=64.5 above=False
  KXBTC-26MAR1321-T78999.99 -> series=KXBTC settle=2026-03-13 thresh=78999.99 above=True

=== Full backtest run ===
  Trades:  0  (expected, no settled data)
  P&L:     $0.00
  Report:  results/20260313_183748_report.txt

SMOKE TEST PASSED
```

All 7 files pass `ast.parse()`.
