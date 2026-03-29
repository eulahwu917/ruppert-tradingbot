# SA-2: Researcher Memory
_Accumulated research findings. Don't re-research topics already covered._

---

## Mandate

Monitor quant research, identify new data sources and signals, feed findings to CEO.
Research before recommending — never hype, always cite sources.

---

## Completed Research (2026-03-11)

### 1. Kelly Criterion / Dynamic Position Sizing
**Finding**: 25% fractional Kelly is well-validated for prediction markets (optimal range: 20-30%).
Anti-Martingale (add to winners, reduce losers) confirmed superior to flat sizing.
**Applied**: strategy.py uses 25% fractional Kelly.

### 2. Bayesian Signal Updating
**Finding**: Raw drift thresholds are inferior to Bayesian probability updates for add-on decisions.
Bayesian approach accounts for prior confidence at entry, not just market price drift.
**Status**: Deferred to post-Friday. Current drift-threshold approach is "good enough to validate."

### 3. Prediction Market Exit Strategies
**Finding**: Time decay is critical. Take-profit when >70-80% of value realized.
Settlement hold (<30 min) is standard practice.
**Applied**: strategy.py implements 70% gain rule + 95¢ rule.

### 4. T-Market / Extreme Event Pricing
**Finding**: Favorite-Longshot bias — low-probability events (longshots) are consistently OVERPRICED by crowd.
This gives NO on T-markets a structural edge.
Hedging demand can also cause YES overpricing on adverse weather.
**Applied**: edge_detector.py soft prior — lean NO on T-markets (1.15x confidence), reduce YES (0.85x).

### 5. GFS vs ECMWF Ensemble Quality
**Finding**: ECMWF ensemble materially more accurate than GFS for 1-5 day temperature forecasts.
GFS raw probabilities are uncalibrated — bias correction (+2-4°F) is valid approach.
Brier Skill Score is correct metric for validating ensemble calibration.
**Status**: ECMWF upgrade planned post-Friday. Current GFS approach workable.

### 6. Crypto Distribution (Fat Tails)
**Finding**: Normal distribution is fundamentally wrong for crypto. Bitcoin has daily ±20% moves 50-100x more frequent than normal predicts.
Student's t-distribution (df=3) captures fat tails with minimal complexity.
Log-normal is better than normal but still "fundamentally incomplete."
**Applied**: crypto_client.py now uses Student's t-distribution.

### 7. Volatility Clustering (GARCH)
**Finding**: Crypto vol is not constant — it clusters. High vol yesterday → high vol today.
EWMA (λ=0.94, RiskMetrics standard) captures clustering without full GARCH complexity.
**Applied**: crypto_client.py uses EWMA vol.

### 8. RSI Quality / Multi-Timeframe
**Finding**: RSI most reliable when confirmed across multiple timeframes.
In strong uptrend: RSI stays 40-90 (not overbought at 70). Our binary RSI flag was wrong.
**Applied**: crypto_client.py uses 1h + 4h RSI with tiered scoring.

### 9. Smart Money / Polymarket Wallets
**Finding**: Smart money signals most predictive when tracking consistent specialists (10+ trades in same category).
Position-size weighting more accurate than wallet-count weighting.
3 wallets is too thin — need 20-30 for reliable signal.
**Applied**: crypto_client.py uses size-weighted aggregation. 5 placeholder wallets added (TODO: replace with real addresses).

---

## Research Queue (upcoming)

- [ ] Find top 20-30 verified Polymarket crypto traders from leaderboard
- [ ] Research Jobs/Labor indicators (BLS NFP, unemployment) vs Kalshi market prices
- [ ] Research Commodities signals (EIA oil/gas, FRED gold) vs Kalshi markets
- [ ] Research Bayesian position update implementation for add-on logic
- [ ] Research ECMWF ensemble access via Open-Meteo API
- [ ] Find Brier Score reference implementation for weather calibration
