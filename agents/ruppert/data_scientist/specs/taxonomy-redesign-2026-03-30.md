# Module Taxonomy Redesign — Data Scientist Spec
**Date:** 2026-03-30  
**Author:** Ruppert Data Scientist  
**Status:** RECOMMENDATION — Awaiting David approval before implementation

---

## 1. KXBTC vs KXBTCD — Clarified

Both series confirmed via Kalshi API `/trade-api/v2/series/{ticker}`:

| Series  | Title                      | Frequency | Market Type          |
|---------|----------------------------|-----------|----------------------|
| `KXBTCD` | Bitcoin price **Above/below** | **hourly** | Binary: will price be above/below a strike at settlement? |
| `KXBTC`  | Bitcoin **range**            | **hourly** | Range band: will price be within a band at settlement? |
| `KXETHD` | Ethereum price Above/below   | **hourly** | Same as KXBTCD for ETH |
| `KXETH`  | Ethereum range               | **hourly** | Same as KXBTC for ETH |

**Key insight:** Both KXBTC and KXBTCD are hourly. They are NOT differentiated by frequency — they are differentiated by **market structure**:
- `KXBTCD` / `KXETHD` = **Above/below binary** — single strike, YES/NO question
- `KXBTC` / `KXETH` = **Range band** — multi-strike, "will price be within range X–Y?"

Both settle every hour (12am, 1am, 2am... EDT). Same CF Benchmarks RTI reference price.

**Current naming mistake corrected:**
- `crypto_1d` is NOT daily. It trades KXBTCD/KXETHD which settle hourly.
- The name `crypto_1d` (implying "1 day") is incorrect and misleading.
- The `crypto` module (band module in `main.py`) trades KXBTC/KXETH/KXDOGE range bands, also hourly.

---

## 2. Recommended Full Taxonomy

### Design Principles
- `module` = `{category}_{subcategory}` format
- Names describe **market structure + timeframe**, not internal code names
- Maps 1:1 to how trades should be analyzed in performance reports
- Short enough for JSONL field readability

### Complete Module Map

```
PARENT        MODULE VALUE       KALSHI SERIES       MARKET STRUCTURE
──────────────────────────────────────────────────────────────────────
crypto        crypto_15m         KXBTC15M, KXETH15M, KXXRP15M,
                                 KXDOGE15M, KXSOL15M
                                 → 15-min direction (binary YES/NO)

crypto        crypto_1h          KXBTCD, KXETHD, KXSOLD
                                 → hourly above/below binary
                                 (replaces current: crypto_1d)

crypto        crypto_band        KXBTC, KXETH
                                 → hourly price range bands
                                 (replaces current: crypto)

──────────────────────────────────────────────────────────────────────
weather       weather_band       KXHIGH*-B*  (e.g. KXHIGHTDAL-26MAR30-B83.5)
                                 → B-type band markets

weather       weather_threshold  KXHIGH*-T*  (e.g. KXHIGHNY-T77)
                                 → T-type threshold markets
                                 (NOTE: currently not actively traded,
                                  but distinct market structure warrants
                                  own subcategory for future use)

──────────────────────────────────────────────────────────────────────
econ          econ_cpi           KXCPI
                                 → Monthly CPI MoM release

econ          econ_unemployment  KXECONSTATU3, KXUE
                                 → US/global unemployment rate

econ          econ_fed           KXFED, KXFOMC
                                 → Fed funds rate / FOMC decisions
                                 (currently disabled: needs CME FedWatch)

econ          econ_gdp           KXGDP
                                 → GDP QoQ growth (candidate, not active)

econ          econ_recession     KXWRECSS
                                 → Country recession markets

──────────────────────────────────────────────────────────────────────
geo           geo                KXUKRAINE, KXRUSSIA, KXISRAEL, etc.
                                 → Geopolitical (no subcategory needed yet)

other         manual             -
                                 → Hand-placed trades
```

### Why `crypto_band` ≠ `crypto_1h`

These are fundamentally different trading problems despite both being hourly:
- **`crypto_1h`** (KXBTCD): binary above/below — you pick direction, model is `P_above`
- **`crypto_band`** (KXBTC): range prediction — you bet on price staying within a band  
  → Different signal stack, different edge source, different sizing model

They should be separate subcategories even if the same code handles both initially.

---

## 3. Econ Subcategories — Current Scanner Coverage

From `environments/demo/economics_scanner.py`, `ACTIVE_ECON_SERIES`:

```python
ACTIVE_ECON_SERIES = [
    'KXCPI',         # Monthly CPI MoM — HIGHEST VOLUME → econ_cpi
    'KXFED',         # Fed Funds rate — DISABLED (needs CME FedWatch) → econ_fed
    'KXECONSTATU3',  # US Unemployment Rate monthly → econ_unemployment
    'KXUE',          # Global unemployment (Germany, France) → econ_unemployment
    'KXWRECSS',      # Country recession markets → econ_recession
]
```

Additional from `market_scanner.py` candidate list (not yet active):
- `KXGDP` → `econ_gdp`
- `KXPCE` → `econ_pce` (PCE inflation)
- `KXPPI` → `econ_ppi` (Producer Price Index)
- `KXNFP` → `econ_jobs` (Non-Farm Payrolls)
- `KXJOBLESSCLAIMS` → `econ_unemployment` (same subcategory as KXECONSTATU3)

**Current implementation note:** Econ module currently sets `module='econ'` (flat, no subcategory).  
No econ trades have been executed yet (scanner is alert-only, KXFED disabled).

---

## 4. Migration Impact Assessment

### Current Module Values in Trade Logs (as of 2026-03-30)

| Module      | Trade Count | Tickers Sample                          |
|-------------|-------------|-----------------------------------------|
| `crypto`    | 21          | KXDOGE-*-B* (band), KXBTCD-* (above/below mixed!) |
| `crypto_15m`| 108         | KXBTC15M-*, KXETH15M-*                  |
| `weather`   | 98          | KXHIGHT*-B* (all band type)             |

**Critical observation:** Current `crypto` module mixes two distinct market types:
- Band trades (KXBTC/KXETH/KXDOGE range bands) → should be `crypto_band`
- Hourly above/below (KXBTCD via `crypto_1d` source) → should be `crypto_1h`

### File-by-File Changes Required

#### A. `agents/ruppert/data_scientist/logger.py`

**`build_trade_entry()` — module inference (lines ~85-108):**
```python
# CURRENT: collapses all crypto into 'crypto'
elif source == 'crypto' or (source in ('crypto', 'bot') and any(
    t.startswith(p) for p in ('KXBTC', 'KXETH', ...)
)):
    module = 'crypto'

# PROPOSED: distinguish by ticker suffix pattern
elif source in ('crypto', 'bot') and any(t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXSOL', 'KXXRP', 'KXDOGE')):
    # Discriminate by series structure
    if any(t.startswith(p) for p in ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M')):
        module = 'crypto_15m'
    elif any(t.startswith(p) for p in ('KXBTCD', 'KXETHD', 'KXSOLD')):
        module = 'crypto_1h'
    else:
        module = 'crypto_band'  # KXBTC, KXETH, KXDOGE band ranges
elif source == 'crypto_1d':
    module = 'crypto_1h'   # rename source→module mapping
```

**`classify_module()` — dashboard sync (lines ~230-250):**
Same changes as above. This function is the "single source of truth" and is imported by dashboard/api.py.

**`get_daily_exposure()` — module prefix matching:**
The `module.startswith(module + '_')` logic already handles parent-level queries gracefully:
- `get_daily_exposure(module='crypto')` → matches `crypto`, `crypto_15m`, `crypto_1h`, `crypto_band` ✅
- No change needed to signature

#### B. `agents/ruppert/trader/crypto_1d.py`

```python
# CURRENT (line ~811):
'source': 'crypto_1d',
'module': 'crypto_1d',

# PROPOSED:
'source': 'crypto_1d',   # keep source for traceability
'module': 'crypto_1h',   # reflects actual market structure
```

Decision log entries also write `'module': 'crypto_1d'` — should be updated too.

#### C. `agents/ruppert/trader/main.py`

**`run_crypto_scan()` (the band scanner, ~line 640, 683):**
```python
# CURRENT:
'module': 'crypto',
opp['module'] = 'crypto'

# PROPOSED:
'module': 'crypto_band',
opp['module'] = 'crypto_band'
```

**`run_econ_scan()` / econ opportunity dict:**
Currently econ scanner (`economics_scanner.py`) doesn't set `module` — it uses `type: 'economics'`.
When econ trades are eventually placed (line ~1191), the `build_trade_entry()` fallback in logger.py will infer from source/ticker. This is fine for now but should explicitly set `module = 'econ_cpi'` etc. when trades go live.

#### D. `agents/ruppert/data_analyst/kalshi_client.py` / `market_cache.py`
No changes needed — these are data layers, not module-aware.

#### E. `agents/ruppert/strategist/strategy.py`
Check for any `MIN_CONFIDENCE` or `module=` gating — if `crypto_1d` or `crypto` are hardcoded as keys, they'll need updating. (Not audited in this pass — assign to Dev.)

---

## 5. Weather Subcategory Note

Current trade logs show 98 weather trades, ALL of type `weather_band` (KXHIGHT*-B* tickers).  
No `weather_threshold` (T-type) trades have been executed.

**Proposed change:** Split `module='weather'` → `module='weather_band'`  
The current `build_trade_entry()` and `classify_module()` both return `'weather'` for all KXHIGH* tickers regardless of B vs T type. A simple ticker check can discriminate:
- `-B` in ticker → `weather_band`  
- `-T` in ticker → `weather_threshold`

---

## 6. Summary of Module Renames (old → new)

| Old `module` value | New `module` value | Condition |
|--------------------|-------------------|-----------|
| `crypto`           | `crypto_band`     | Ticker is KXBTC/KXETH/KXDOGE band (no 15M/D suffix) |
| `crypto_1d`        | `crypto_1h`       | Source is `crypto_1d`, tickers KXBTCD/KXETHD |
| `crypto_15m`       | `crypto_15m`      | ✅ No change |
| `weather`          | `weather_band`    | Ticker contains `-B` |
| `weather`          | `weather_threshold`| Ticker contains `-T` |
| `econ`             | `econ_cpi`        | Ticker starts with KXCPI |
| `econ`             | `econ_unemployment`| Ticker starts with KXECONSTATU3/KXUE |
| `econ`             | `econ_fed`        | Ticker starts with KXFED/KXFOMC |
| `econ`             | `econ_recession`  | Ticker starts with KXWRECSS |
| `fed`              | `econ_fed`        | Source/ticker is fed-related (merge fed→econ_fed) |
| `geo`              | `geo`             | ✅ No change needed |
| `manual`           | `manual`          | ✅ No change |

---

## 7. Recommendation: Do It Now

**Verdict: YES — migrate now. Trade count is the window.**

Reasons:
1. **227 total trades** (21 crypto_band + 108 crypto_15m + 98 weather) — small enough to backfill
2. **No econ trades yet** — zero migration cost on econ subcategories
3. **`crypto` label is already wrong** — it mixes band trades with 1h above/below, corrupting any per-module performance analysis
4. **Historical archive files** (Mar 10–13) also have mixed `crypto` — backfill is still tractable
5. **`crypto_1d` as a module name is actively misleading** for anyone reading logs or performance reports
6. **Weather subcategory split** is low-risk: all 98 current trades are band type, so `weather` → `weather_band` is a safe rename

**Recommendation NOT to wait:**  
Every additional `crypto` trade logged under the wrong subcategory makes the eventual backfill harder and corrupts rolling performance metrics (win rate, Kelly sizing calibration) that depend on module-level segmentation.

### Implementation Priority

1. **(Highest)** `classify_module()` in logger.py — single source of truth, fixes new trades immediately
2. **(Highest)** `build_trade_entry()` in logger.py — fallback inference
3. **(High)** `crypto_1d.py` — fix `module='crypto_1d'` → `'crypto_1h'`
4. **(High)** `main.py` band scanner — fix `module='crypto'` → `'crypto_band'`
5. **(Medium)** Write backfill script to relabel existing JSONL trade files
6. **(Low)** `strategy.py` audit for hardcoded module names
7. **(Low)** Econ subcategory labels (no trades yet, can wait for first econ trade)

### Backfill Strategy

Since all trade files are JSONL (one record per line), a simple Python script can:
1. Read each `trades_*.jsonl` line
2. Re-derive correct module via `classify_module(rec['source'], rec['ticker'])`  
   **after** the function is updated
3. Write corrected records back

This is safe to do before any new trades are placed. The CEO should authorize the backfill as a one-time migration.

---

## 8. Open Questions for David

1. **`crypto_band` scanner**: Is it currently active / producing real trades, or just the demo KXDOGE band trades? Need to verify whether KXBTC (not KXBTCD) band markets are intentionally traded or legacy.
2. **`econ_fed` / `fed` merge**: Currently logger has a separate `fed` module path. Should `fed` be merged into `econ_fed`, or kept separate (since Fed trading is a distinct strategy)?
3. **Backfill approval**: Authorize the backfill script to relabel the ~21 existing `crypto` trades to `crypto_band` or `crypto_1h` as appropriate?
4. **`weather_threshold` activation**: No T-type weather trades. Is this intentional (edge_detector only outputs B-type)?
