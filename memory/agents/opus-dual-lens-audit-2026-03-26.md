# Opus Dual-Lens Audit - 2026-03-26

This document contains two independent audits of the Ruppert trading bot codebase:
1. **Codebase Linkage & Logic Review** - Does everything link correctly? Are there bugs?
2. **Trading Logic Review** - Does the strategy make sense? Would it make money?

---

## AUDIT 1: Codebase Linkage & Logic

### P0 - Critical

**No P0 issues found.** The codebase has been through multiple prior audit rounds (commits dc845f8, c3401ed, 006a8d3) that resolved critical issues including:
- Deleted risk.py restored (MAX_POSITION_SIZE, MAX_DAILY_EXPOSURE)
- actions_taken initialized before try block in ruppert_cycle.py
- config.DRY_RUN used consistently (not undefined config.DEMO_MODE)

### P1 - Important

**P1-1: Dead ensemble confidence check (edge_detector.py:315)**
```python
if confidence < MIN_ENSEMBLE_CONFIDENCE and signal_src == "open_meteo_ensemble":
```
- **Issue**: The signal source was renamed to `"open_meteo_multi_model"` in v3, so this check never triggers.
- **Impact**: Low - subsequent confidence gate at line 320 catches this anyway.
- **Fix**: Update condition to `signal_src == "open_meteo_multi_model"` or remove this check entirely since it's redundant with line 320-326.

**P1-2: Entry price normalization inconsistency (post_trade_monitor.py:105-109)**
```python
if 0 < entry_price < 1:
    entry_price = round((1 - entry_price) * 100)
```
- **Issue**: This assumes entry_price between 0-1 is a probability, but doesn't handle cases where entry_price might be stored as cents already. The check at line 109 converts but only for NO side.
- **Impact**: Medium - could miscalculate P&L for some positions.
- **Fix**: Standardize entry_price storage format across all trade logs, or add explicit `price_format` field.

**P1-3: Crypto client funding rate US access (crypto_client.py:166-185)**
```python
r = requests.get(f'{BINANCE_FUTURES}/fundingRate', ...)
```
- **Issue**: Comment at line 136 says "US accessible" but Binance Futures API is geo-restricted in US. This call will fail for US-based users.
- **Impact**: Funding rate z-score feature will silently fail; degrades signal quality.
- **Fix**: Add graceful fallback when Binance API returns 451 or times out; consider alternative data source.

### P2 - Should Fix

**P2-1: Bare except clauses throughout codebase**
- **Files**: logger.py:156, ruppert_cycle.py:37/91, crypto_scanner.py:75
- **Issue**: Using bare `except:` catches KeyboardInterrupt and SystemExit, making graceful shutdown harder.
- **Fix**: Replace with `except Exception:` throughout.

**P2-2: Opportunity dict field name inconsistency**
- **Issue**: Model probability stored as different field names:
  - Weather: `noaa_prob` (legacy name) and `model_prob`
  - Crypto: `prob_model`
  - Fed: `prob`
  - Econ: `model_prob`
- **Impact**: Confusion when debugging; logger.py:102-106 normalizes via `noaa_prob` fallback.
- **Fix**: Standardize on `model_prob` everywhere, deprecate `noaa_prob`.

**P2-3: NWS grid point mismatch for expanded cities (openmeteo_client.py:98-112)**
- **Issue**: NWS_GRID_POINTS uses grid coordinates that may not exactly match the CITIES lat/lon coordinates. For example, KXHIGHAUS uses gridX=156,gridY=91 but CITIES uses lat=30.1945 (airport coords).
- **Impact**: Could cause slight forecast mismatch between NWS official and Open-Meteo ensemble.
- **Fix**: Verify all NWS grid points match airport station coordinates used in CITIES dict.

**P2-4: GHCND stations incomplete (ghcnd_client.py:37-74)**
- **Issue**: GHCND_STATIONS only covers 6 original cities. The 14 expanded cities (KXHIGHAUS, KXHIGHDEN, etc.) are not in GHCND_STATIONS.
- **Impact**: Expanded cities use DEFAULT_HARDCODED_BIAS_F = 3.0 (now 0.0 per code) which may not be accurate.
- **Fix**: Add GHCND station IDs for all 20 cities to enable proper bias correction.

**P2-5: Log rotation only on cycle run (logger.py:20-48)**
- **Issue**: rotate_logs() is called from ruppert_cycle.py but not from main.py direct invocations.
- **Impact**: Running `python main.py` repeatedly won't rotate logs; could accumulate stale logs.
- **Fix**: Call rotate_logs() at startup in main.py as well.

### P3 - Polish

**P3-1: Magic numbers in crypto volatility config (main.py:483-488)**
```python
SERIES_CFG = [
    ('KXBTC',  btc,  250,   0.025, 18),  # 250 = half_width, 0.025 = daily_vol
```
- **Issue**: Volatility parameters (0.025, 0.030, etc.) are hardcoded without explanation.
- **Fix**: Move to config.py or add inline documentation of data source.

**P3-2: Unused CONFIDENCE_FILTER in crypto_scanner (crypto_scanner.py:45-46)**
```python
CONFIDENCE_FILTER = ['medium', 'high']
```
- **Issue**: This filter is used, but the crypto_client returns 'low'/'medium'/'high' based on edge_score thresholds not documented here.
- **Fix**: Add comment explaining confidence tier derivation.

**P3-3: Inconsistent timezone handling (economics_client.py:153)**
```python
'fetched_at': datetime.utcnow().isoformat(),
```
- **Issue**: Uses `datetime.utcnow()` which is deprecated; other files use `datetime.now(timezone.utc)`.
- **Fix**: Use `datetime.now(timezone.utc).isoformat()` for consistency.

**P3-4: FOMC calendar hardcoded for 2026 only (economics_client.py:45-54, fed_client.py:52-61)**
- **Issue**: Calendar only covers 2026. Will need manual update for 2027.
- **Fix**: Already has CME API integration in fed_client.py; ensure economics_client.py falls back to fed_client calendar.

**P3-5: Kraken pair inconsistency (crypto_client.py:54-57)**
```python
'DOGE': {'cg_id': 'dogecoin',  'kraken_pair': 'XDGUSD', ...}
```
- **Issue**: DOGE pair is `XDGUSD` but other pairs use `XXBTZUSD`, `XETHZUSD` format.
- **Fix**: Verify this is correct Kraken pair; add comment if intentional.

### Clean (No Issues Found)

- **Import resolution**: All imports resolve to existing modules/functions.
- **Config constants**: All `config.X` references exist in config.py.
- **File I/O paths**: Consistently use `Path()` or `os.path.join()` with forward slashes.
- **Capital tracking**: Single source of truth in capital.py with proper fallbacks.
- **Trade logging**: logger.py build_trade_entry() enforces schema with uuid.
- **Strategy gates**: bot/strategy.py should_enter() applies all filters in correct order.
- **Exit logic**: should_exit() priority order is correct (95c > 70% gain > near-settlement > reversal).

### Audit 1 Executive Summary

The Ruppert codebase is in **good shape** after recent audit fixes. No critical P0 issues were found. The main concerns are:

1. **P1-3 Binance geo-restriction** could silently degrade crypto signal quality for US users.
2. **P2-4 Missing GHCND stations** means 14 of 20 cities use unvalidated bias correction.
3. **P2-2 Field name inconsistency** creates maintenance burden but doesn't affect runtime.

The code demonstrates defensive programming practices: try/except blocks with fallbacks, single source of truth patterns, and extensive logging. The prior audit rounds have cleaned up the major issues.

---

## AUDIT 2: Trading Logic

### Structural Concerns

**S1: Weather NO-only filter assumes historical edge persists**
- The 90.4% NO win rate came from backtest data. Markets are adaptive; if this edge is exploitable, other participants will compete it away.
- **Mitigation**: Shadow-logging YES signals (edge_detector.py:41-61) will reveal if the filter is leaving money on the table.
- **Risk**: Medium. If the edge was data-mined from noise, live performance will regress toward 50%.

**S2: Expanded cities have unvalidated bias**
- 14 new cities (Austin, Denver, etc.) use DEFAULT_BIAS_F = 0.0 (changed from 3.0).
- Without GHCND bias correction, model forecasts may systematically miss the settlement price.
- **Mitigation**: Code attempts GHCND refresh but stations aren't configured.
- **Risk**: Medium. Could cause consistent losses on expanded city markets.

**S3: Fed module effectively disabled**
- economics_scanner.py:89-90 skips all KXFED markets with comment "requires CME FedWatch data for reliable signals".
- fed_client.py has CME integration but requires OAuth credentials not all users will have.
- **Mitigation**: Fed is correctly disabled rather than trading with poor signals.
- **Risk**: Low. Missed opportunity rather than loss exposure.

**S4: Crypto vol assumptions are static**
- Hardcoded `daily_vol` values (BTC 2.5%, ETH 3.0%, etc.) don't adapt to regime changes.
- Post-halving or during black swan events, actual vol could be 2-3x higher.
- **Mitigation**: Quarter-Kelly and 1% position cap limit max loss per trade.
- **Risk**: Medium. Could over-size during high-vol regimes.

### Edge Quality Assessment

| Module | Signal Source | Edge Quality | Confidence |
|--------|--------------|--------------|------------|
| Weather | Multi-model ensemble (ECMWF+GEFS+ICON) + GHCND bias | **High** - Physics-based, uncorrelated models | High for original 6 cities |
| Crypto | Log-normal band probability + momentum scoring | **Medium** - Sound math but sensitive to vol estimate | Medium |
| Geo | LLM two-stage pipeline (Haiku + Sonnet) | **Low** - Experimental, capped at 0.85 confidence | Low |
| Econ | BLS/FRED data + normal approximation | **Medium** - Good data but naive model | Medium |
| Fed | CME FedWatch + Polymarket blend | **High** - Professional-grade data | N/A (disabled) |

**Weather edge is the strongest signal**. The 90.4% NO win rate is plausible because:
1. Tail events (above/below extremes) settle YES only ~5% of time historically
2. Retail bettors have longshot bias; NO is systematically underpriced
3. Multi-model ensemble outperforms any single forecast

**Crypto edge is theoretically sound but unproven**. The Student's t-distribution for fat tails is appropriate, but:
- Band width parameters are hardcoded, not calibrated
- Funding rate z-score signal requires non-US API access
- Smart money signal relies on Polymarket leaderboard data

**Geo edge is speculative**. LLM probability estimates are not calibrated against outcomes. The 0.85 confidence cap acknowledges this.

### Risk Management Assessment

**Position Sizing Stack:**
```
1. Kelly formula with confidence-tiered fractions (5-16% of Kelly)
2. Market impact ceiling (spread > 7c → floor at $25)
3. Open interest cap (5% of OI)
4. Per-trade 1% of capital cap
5. Module daily caps (Weather 7%, Crypto 7%, Geo 4%, Econ 4%)
6. Global 70% daily deployment cap
7. Global 70% open exposure cap
```

This is **appropriately conservative**. The stacked caps mean actual Kelly deployment is ~1-2% of theoretical Kelly. This is correct given:
- Unproven calibration (only 22 trades)
- Prediction market liquidity constraints
- Model uncertainty

**Exit Rules:**
- 95c rule locks in near-certain profit (correct)
- 70% gain rule takes profit early (possibly too aggressive)
- Near-settlement hold avoids slippage (correct)
- Reversal rule scales exit by severity (correct)

The 70% gain threshold may exit too early in trending markets, but for prediction markets with hard settlement times, this is reasonable.

### What Could Go Wrong Early

1. **Weather edge doesn't persist**: If the 90.4% NO win rate was backtest overfit, live results will disappoint. First 30 weather trades are the key test.

2. **Expanded city bias errors**: Trading KXHIGHAUS, KXHIGHDEN etc. with 0.0 bias when actual bias is +3-4F will cause systematic losses.

3. **Crypto vol regime change**: A sudden vol spike (e.g., exchange hack, regulatory news) could blow through position limits before the model adjusts.

4. **Geo LLM hallucination**: LLM probability estimates are not grounded in base rates. A confident-sounding but wrong estimate could trigger a bad trade.

5. **API reliability**: Multiple external APIs (Kalshi, Open-Meteo, GDELT, Polymarket, Kraken, CoinGecko). Any extended outage degrades the system.

### Overall Verdict

**Will this make money?**

**Probably, IF:**
- The weather NO edge is real (not backtest overfit)
- Trading is restricted to the original 6 validated cities
- The conservative Kelly sizing limits drawdowns during learning phase
- Crypto vol parameters are periodically recalibrated

**Structural advantages:**
- Multi-source data (not reliant on single API)
- Defensive risk management (multiple overlapping caps)
- Comprehensive logging for post-hoc analysis
- Optimizer framework for parameter tuning

**Structural disadvantages:**
- Unvalidated edge on 14 of 20 weather cities
- Crypto funding rate signal broken for US users
- No intraday scanning (CPI/NFP post-print window missed)
- Fed module disabled despite having best-quality signal source

**Recommendation:**
1. **Restrict weather trading to original 6 cities** until GHCND bias correction is validated for expanded cities
2. **Run 30+ trades per module** before trusting optimizer output
3. **Monitor Brier scores closely** - if >0.25, recalibrate confidence thresholds
4. **Enable Fed module** if CME credentials are available - it's the highest-quality signal
5. **Add Binance fallback** for crypto funding rates (use alternative data source for US users)

**Expected first-month outcome (DEMO mode):**
- Weather: 15-20 trades, 65-80% win rate if edge is real
- Crypto: 5-10 trades, 50-60% win rate (vol estimation is noisy)
- Geo: 2-5 trades, 40-60% win rate (LLM is experimental)
- Overall P&L: Slightly positive if weather edge holds, break-even otherwise

### Audit 2 Executive Summary

The Ruppert trading strategy is **fundamentally sound** but **not yet validated**. The weather module has the strongest edge thesis (multi-model ensemble + longshot bias exploitation), but the 90.4% win rate needs live confirmation. The risk management is appropriately conservative for a cold-start system.

The main strategic concerns are:
1. **14 expanded cities lack validated bias correction** - trade only original 6 until fixed
2. **Crypto vol parameters are static** - could over-size in high-vol regimes
3. **Fed module disabled** despite having professional-grade signal source

With 22 trades so far, the system is still in **data collection mode**. The first 30+ trades per module will reveal whether the edges are real or backtest artifacts. The comprehensive logging and optimizer framework are well-designed to surface these issues.

**Bottom line**: The strategy could make money, but it's too early to know. The code is production-quality; the edge quality is unproven. Run in DEMO mode for another 2-4 weeks, then reassess based on Brier scores and win rates.

---

*Audit completed 2026-03-26 by Claude Opus 4.5*
*Files reviewed: 42 Python files, 4 JSON config files*
*Lines of code audited: ~8,500*
