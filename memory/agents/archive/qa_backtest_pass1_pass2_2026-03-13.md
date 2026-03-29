# QA Report — Backtest Framework Pass 1 + Pass 2
**Date:** 2026-03-13  
**QA Agent:** SA-4  
**Framework directory:** `ruppert-backtest/`  
**Overall Verdict:** ❌ NEEDS FIX FIRST

---

## Summary of Findings

| Check | Status | Severity |
|-------|--------|----------|
| 1A — Kalshi settled_weather.json | ❌ FAIL | CRITICAL |
| 1B — Open-Meteo forecasts | ⚠️ WARNING | Low |
| 1C — Kraken OHLC | ✅ PASS | — |
| 2A — Syntax (all 7 files) | ✅ PASS | — |
| 2B — Signal simulator logic | ⚠️ WARNING | Medium |
| 2C — Strategy simulator P&L | ✅ PASS | — |
| 2D — T vs B market direction | ❌ FAIL | HIGH |
| 2E — 0 trades root cause | ❌ FAIL | CRITICAL (same root as 1A) |

---

## QA PASS 1: DATA VALIDATION

---

### Check 1A — Kalshi settled_weather.json ❌ CRITICAL

**File loaded successfully.** 850 total markets.

**Fields present per record:**
```
ticker, series_ticker, close_time, last_price, yes_ask, yes_bid, open_time, subtitle
```

**Price field population:**
- `last_price` null: **850/850 (100%)** ← CRITICAL
- `yes_ask` null: **850/850 (100%)** ← CRITICAL
- `yes_bid` null: 850/850 (100%)
- `series_ticker` null: 850/850 (also null, but less critical)

**Every single pricing field is null.** The data file has market metadata but zero settlement or trading prices.

**Sample records (10 random):**
```
ticker: KXHIGHTDC-26MAR10-B75.5    close: 2026-03-11T04:00:00Z  last_price: None  yes_ask: None
ticker: KXHIGHPHIL-26MAR11-B80.5   close: 2026-03-12T03:59:00Z  last_price: None  yes_ask: None
ticker: KXHIGHTSATX-26MAR08-B72.5  close: 2026-03-09T05:00:00Z  last_price: None  yes_ask: None
ticker: KXHIGHTSATX-26MAR10-T87    close: 2026-03-11T05:00:00Z  last_price: None  yes_ask: None
ticker: KXHIGHTSFO-26MAR07-B70.5   close: 2026-03-08T08:00:00Z  last_price: None  yes_ask: None
ticker: KXHIGHTDC-26MAR12-T68      close: 2026-03-13T04:00:00Z  last_price: None  yes_ask: None
ticker: KXHIGHNY-26MAR05-B47.5     close: 2026-03-06T04:59:00Z  last_price: None  yes_ask: None
ticker: KXHIGHNY-26MAR12-B64.5     close: 2026-03-13T03:59:00Z  last_price: None  yes_ask: None
ticker: KXHIGHTDAL-26MAR11-T80     close: 2026-03-12T05:00:00Z  last_price: None  yes_ask: None
ticker: KXHIGHTSATX-26MAR05-T91    close: 2026-03-06T06:00:00Z  last_price: None  yes_ask: None
```

**Ticker pattern check:**
Tickers DO follow the expected format `KXHIGH{CITY}-{DATE}-{TYPE}{THRESHOLD}`. Examples observed:
- `KXHIGHNY-26MAR12-T71` (above-threshold, integer)
- `KXHIGHTDC-26MAR10-B75.5` (bracket, decimal)
- `KXHIGHPHIL-26MAR11-B80.5` (bracket, decimal)

City codes in this dataset: `NY`, `TDC`, `PHIL`, `TSATX`, `TSFO`, `TDAL`, `TMIN`, `TLV`, `TOKC`, `TATL`, `CHI`, `MIA`, `HOU`, `LAX`, `PHX`, `AUS`, `DEN`.

**Ticker format: ✅ PASS.** The `T`-prefixed city codes (TDC, TSATX, TSFO, etc.) are legitimate Kalshi series names — `T` is part of the city abbreviation, not the market type.

**Root cause of null prices:** The Kalshi batch market listing API (`/markets` or `/series/{series}/markets`) returns `last_price: null` when a market has not had individual data fetched or when settlement hasn't been individually recorded. The settlement price is not populated automatically in bulk responses.

---

### Check 1B — Open-Meteo forecasts ⚠️ WARNING

**File loaded successfully.**

**Structure:** Nested dict `{series → {date → {ecmwf_max, gfs_max, icon_max}}}` ✅

**Top-level city series (20 total):**
```
KXHIGHNY, KXHIGHCHI, KXHIGHMIA, KXHIGHHOU, KXHIGHPHX, KXHIGHLA, KXHIGHAUS,
KXHIGHDEN, KXHIGHLAX, KXHIGHPHIL, KXHIGHTMIN, KXHIGHTDAL, KXHIGHTDC, KXHIGHTLV,
KXHIGHTNOU, KXHIGHTOKC, KXHIGHTSFO, KXHIGHTSEA, KXHIGHTSATX, KXHIGHTATL
```

**Sample dates for KXHIGHNY:**
```
2026-02-27: {ecmwf_max: 33.9, gfs_max: 41.3, icon_max: 41.3}
2026-02-28: {ecmwf_max: 37.2, gfs_max: 52.9, icon_max: 49.3}
2026-03-01: {ecmwf_max: 37.3, gfs_max: 44.0, icon_max: 41.4}
2026-03-02: {ecmwf_max: 28.1, gfs_max: 33.9, icon_max: 32.0}
2026-03-03: {ecmwf_max: 33.8, gfs_max: 36.1, icon_max: 33.8}
```
Temperature values (30–53°F for NYC in Feb/Mar) look realistic ✅

**⚠️ WARNING — gfs_seamless field not explicitly confirmed:**
The file uses the generic key `gfs_max`. The check asked to verify `gfs_seamless` (not `gfs025`) was used during data collection. Since both strings (`gfs_seamless` and `gfs025`) are absent from the JSON, we cannot confirm which Open-Meteo model parameter was used to fetch the data. If `gfs025` was used (which was listed as unavailable), the GFS values may be unreliable or placeholder zeros. **Researcher should confirm the fetch script used `gfs_seamless`.**

---

### Check 1C — Kraken OHLC ✅ PASS

**File loaded:** `data/kraken_ohlc_XBTUSD.json`

**Structure:** List of 360 dicts (≥300 ✅) with fields:
```
{timestamp, open, high, low, close, volume}
```
Note: structure is dict-based (not list-of-lists as spec anticipated), but `data_loader.py`'s `get_price_at_time()` handles both formats correctly via duck typing. ✅

**Sample candles:**
```
First: {timestamp: 1772150400, open: 67484.2, high: 67546.9, low: 67021.4, close: 67224.2, volume: 101.87}
Last:  {timestamp: 1773442800, open: 70799.0, high: 71000.0, low: 70728.1, close: 70953.0, volume: 44.81}
```

**Close price range:** $67,224 – $70,953 — well within $60k–$90k expected range ✅

**One note:** `get_price_at_time()` uses `c.get("time", c.get("timestamp", 0))` — the file uses `timestamp` (not `time`), so it falls back to the second key. Works correctly. ✅

---

## QA PASS 2: ENGINE LOGIC

---

### Check 2A — Syntax (all 7 files) ✅ PASS

```
PASS: data_loader.py
PASS: signal_simulator.py
PASS: strategy_simulator.py
PASS: backtest_engine.py
PASS: report.py
PASS: config_sweep.py
PASS: backtest.py
```
All files parse cleanly with `ast.parse()`. No syntax errors.

---

### Check 2B — Signal simulator logic ⚠️ WARNING

**Weather ensemble weights:**
```python
_WEATHER_WEIGHTS = {"ecmwf": 0.40, "gfs": 0.40, "icon": 0.20}
```
ECMWF=0.40 ✅, GFS=0.40 ✅, ICON=0.20 ✅, Sum=1.00 ✅

**Same-day skip logic — ⚠️ WARNING (over-aggressive):**

The code reads:
```python
if scan_hour_utc >= 14:
    empty["skip"] = True
    empty["reason"] = "same_day skip: scan_hour >= 14"
    return empty
```
This is applied to **all** scans unconditionally (no check whether `target_date == scan_date`). In the backtest, every scan IS same-day by design, so this logic is technically correct per the spec — but it means **scan hours 15 and 22 will ALWAYS skip**. The configured scan hours are `[7, 12, 15, 22]`; only hours 7 and 12 will ever generate weather signals.

This is a known design choice, but worth flagging: 50% of scan hours are dead weight for weather. No action required — just document it.

**Crypto signal uses live price momentum ✅:**
```python
price_now  = get_price_at_time(candles, scan_ts)
price_prev = get_price_at_time(candles, prev_ts)
change_24h = (price_now - price_prev) / price_prev
```
Momentum is computed dynamically from Kraken OHLC candles at scan_ts. No hardcoded values. ✅

---

### Check 2C — Strategy simulator P&L mechanics ✅ PASS

**`compute_pnl()` logic:**
```python
yes_won = last_price >= 50
if side == "YES":
    won = yes_won
else:
    won = not yes_won

if won:
    pnl = contracts * (1.0 - cost_per_contract)   # (1.00 - entry_price) * contracts ✅
else:
    pnl = -size_dollars                            # -entry_price * contracts ✅
```
Mechanics verified correct for both YES and NO sides. ✅

**Daily cap logic present:**
```python
daily_cap_limit = capital * config["daily_cap_pct"]   # 70% of capital
daily_deployed = 0.0
# ...
available_capital = min(capital, daily_cap_limit - daily_deployed)
if available_capital <= 0:
    break
```
Implemented in `backtest_engine.py`. ✅

**Sizing caps:**
```python
cap1 = capital * config["pct_capital_cap"]   # 2.5% of capital
cap2 = config["max_position_cap"]            # $50 hard cap
size = min(raw_size, cap1, cap2)
```
Both PCT_CAPITAL_CAP and MAX_POSITION_CAP are respected. ✅

---

### Check 2D — T vs B market direction ❌ HIGH SEVERITY

**Bug confirmed as described.** 

The `is_above` flag is parsed correctly in `_parse_market_fields()`:
```python
m["is_above"] = (direction_char == "T")  # T = above, B = below/bracket
```

But in `run_backtest()`, the value is extracted and then **never used**:
```python
is_above = market.get("is_above", True)
# ... is never passed to simulate_weather_signal() or used to flip direction
```

The signal simulator computes: `direction = "YES" if weighted_prob >= 0.5 else "NO"` — for ALL market types identically.

**For T markets:** YES = temp above threshold. If model prob ≥ 0.5, direction=YES → correct. ✅  
**For B markets:** YES = temp WITHIN bracket range (e.g., 47°–48°). The model is checking `temp >= threshold - bias`, not whether it falls within a narrow bracket. This produces wrong direction signals and therefore wrong P&L on all B markets.

**Scope of impact — MORE SEVERE THAN DEVELOPER ESTIMATED:**

Actual market split from the dataset:
- **T markets: 305 (35.9%)**  
- **B markets: 545 (64.1%)**

The developer said "mostly T markets" but the data is **actually majority B markets** (64%). This is NOT safe to ignore for the initial backtest. Running with B markets incorrectly handled means ~64% of the dataset has potentially inverted or nonsensical signals.

**Recommendation:** This needs to be fixed before the backtest produces meaningful results. Options:
1. **Filter to T markets only** for the initial backtest (`if not market.get("is_above", True): continue`) — fastest path to a valid result
2. **Implement proper B market logic** — for bracket markets, YES wins if `lower <= actual_high <= upper`; this requires knowing both bracket bounds and actual settlement temperature, which adds data requirements

**For an initial valid backtest, Option 1 (filter to T markets only) is the pragmatic fix** — it sacrifices 64% of the market universe but produces correct results on the remaining 35.9% (305 markets).

---

### Check 2E — 0 trades root cause ❌ CRITICAL

**Root cause confirmed.** The filter is in `strategy_simulator.py`:

```python
last_price = market.get("last_price")
if last_price is None:
    return {**no_trade, "reason": "no last_price (unsettled)"}
```

Since **all 850 markets have `last_price = None`**, every single trade decision returns "no last_price (unsettled)" → 0 trades.

**Diagnosis:** The data was pulled using a Kalshi API endpoint that lists markets in bulk. Bulk listing endpoints return `last_price: null` — they return metadata (tickers, open/close times, strike prices) but not settlement prices. Settlement prices must be fetched individually per market via the individual market endpoint.

**Kalshi API context:**
- Bulk endpoint: `GET /markets?series={series}` → returns market list, `last_price` is null until individually fetched post-settlement
- Individual endpoint: `GET /markets/{ticker}` → returns full market data including `last_price` after settlement

**Proposed fix — RECOMMENDED: Re-pull with individual fetches (Option A)**

For each of the 850 market tickers, fetch `GET /markets/{ticker}` and update the `last_price` field. After market close, `last_price` should be 1 (NO won) or 99 (YES won), or the final trading price if market was traded.

Pseudo-code:
```python
for market in markets:
    ticker = market["ticker"]
    result = kalshi_client.get_market(ticker)
    market["last_price"] = result.get("last_price")
    market["yes_ask"] = result.get("yes_ask")
    market["yes_bid"] = result.get("yes_bid")
```

This approach is correct and complete. Rate-limit: Kalshi allows ~10 req/sec; 850 markets ≈ 85 seconds at full rate.

**Alternative fix — Check for alternate field names (Option B)**

The Kalshi API may also return settlement via `result` (string: "yes"/"no"), `result_time`, or `close_price`. If the bulk fetch returns any of these, the data loader could use them as a proxy. However, from the current file structure, no such fields are present — the file only has `{ticker, series_ticker, close_time, last_price, yes_ask, yes_bid, open_time, subtitle}`. Option B is not viable with the current data.

**Conclusion: Option A (individual market fetches) is the only viable fix.** Researcher needs to update the data-pull script to fetch each market individually after its `close_time`.

---

## Overall Verdict: ❌ NEEDS FIX FIRST

### Blocking Issues (must fix before backtest produces valid results):

1. **[CRITICAL] Check 1A / 2E — Null settlement prices** — All 850 `last_price = None`. Backtest generates 0 trades. Fix: re-pull with individual `GET /markets/{ticker}` calls per market.

2. **[HIGH] Check 2D — B market direction bug** — 64.1% of markets (545/850) are bracket markets; signals are computed identically to T markets, producing wrong directions. Fix: either filter to T-only for initial run, or implement proper bracket logic.

### Non-blocking Issues (fix in next iteration):

3. **[WARNING] Check 1B — GFS model source unconfirmed** — `gfs_seamless` vs `gfs025` not verifiable from file content alone. Researcher should confirm fetch script uses `gfs_seamless`.

4. **[WARNING] Check 2B — Same-day skip is always-on** — Scan hours 15 and 22 will always skip weather signals. Known design choice, just worth documenting. Crypto signals not affected.

### Clean Passes:
- ✅ All 7 engine files: clean syntax
- ✅ Kraken OHLC: 360 candles, dict format handled, prices in range
- ✅ P&L mechanics: correct YES/NO settlement math
- ✅ Daily cap and sizing caps: correctly implemented
- ✅ Crypto signal: live momentum from OHLC, no hardcoded values
- ✅ Ticker format: valid Kalshi patterns

---

## Action Items for Developer (SA-3)

**Priority 1 — Data fix (blocker):**
- Update `fetch_kalshi_data.py` (or equivalent) to fetch each market individually after `close_time` has passed
- Save updated data back to `kalshi_settled_weather.json` with `last_price` populated
- Verify at least 20% of markets have non-null `last_price` before re-running backtest

**Priority 2 — B market fix (high):**
- In `backtest_engine.py` `run_backtest()`, add filter to skip B markets until proper bracket logic is implemented:
  ```python
  if not market.get("is_above", True):
      continue  # skip bracket markets for now
  ```
  OR pass `is_above` into signal logic and handle both types.

**Priority 3 — GFS source confirmation (low):**
- SA-2 Researcher: confirm the Open-Meteo fetch used `gfs_seamless` model parameter, not `gfs025`

---

*Report written by SA-4 QA. Routing to CEO (Ruppert) for approval before action.*
