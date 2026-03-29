# QA Investigation: Below-Threshold Crypto Trade Execution
**Date:** 2026-03-13
**Investigator:** SA-4 (QA)
**Subject:** Two crypto trades executed with edge below 12% minimum

---

## Trades Under Investigation

| Ticker | Edge | Threshold (at time) | Status |
|--------|------|---------------------|--------|
| KXXRP-26MAR1217-B1.4099500 | 11.6% (0.116) | 10% | ✅ Above threshold at time of trade |
| KXETH-26MAR1217-B2140 | 11.2% (0.112) | 10% | ✅ Above threshold at time of trade |

---

## Finding 1: Trades Were NOT Below-Threshold at Time of Execution

The task stated these trades appear in `trades_2026-03-12.jsonl`. **They do not — that file does not exist.** Both trades are in `trades_2026-03-11.jsonl`, placed at `2026-03-11T15:00:05`.

At that time, `config.py` had:
```
CRYPTO_MIN_EDGE_THRESHOLD = 0.10   # 10% min edge (crypto is noisier)
```

Both edges (11.6%, 11.2%) were **above the 10% threshold in effect** — they correctly passed the filter. There was no bug at execution time.

---

## Finding 2: Threshold Raised to 12% After the Trades — "Batch E" Commit

The threshold was raised from 10% → 12% in commit `8585781` on **2026-03-12 23:26:50**:

```
Batch E: edge thresholds to 12% all modules + QA warning fixes
config.py: MIN_EDGE_THRESHOLD 0.15->0.12, CRYPTO_MIN_EDGE_THRESHOLD 0.10->0.12
Approved: David 2026-03-12
```

When these historical trades are viewed against the *current* 12% threshold, they appear to be violations — but they were not violations at the time they executed.

---

## Finding 3: `strategy.py` Was NOT Wired Into the Crypto Path

The crypto scan in `ruppert_cycle.py` uses `config.CRYPTO_MIN_EDGE_THRESHOLD` directly:
```python
if best_edge < config.CRYPTO_MIN_EDGE_THRESHOLD: continue
```

It does **not** call `strategy.should_enter()`. This is a known pending issue per `team_context.md`:
> `bot/strategy.py` not yet wired into `main.py` — pending

Additionally, `strategy.py` has `MIN_EDGE['crypto'] = 0.10` — still at the old 10% value — creating a latent inconsistency for when it does get wired in.

---

## Finding 4: Edge Logged vs. Edge Used for Filtering — Same Calculation

The `edge` value in the trade log (`round(best_edge, 3)`) is derived from the same `best_edge` variable used in the filter:
```python
best_edge = max(edge_no, edge_yes)
if best_edge < config.CRYPTO_MIN_EDGE_THRESHOLD: continue
...
opp = { ..., 'edge': round(best_edge, 3), ... }
```
There is **no discrepancy** between what was filtered and what was logged.

---

## Root Cause Summary

**Not a bug.** The trades were placed under the old `CRYPTO_MIN_EDGE_THRESHOLD = 0.10` (10%), and both edges (11.6%, 11.2%) were legitimately above that threshold. They only appear to be violations when viewed against the current 12% threshold introduced in "Batch E" the following day.

The anomaly is a **threshold change creating retroactive apparent violations** — not a filtering failure.

---

## Is This Still a Live Bug?

**No.** `config.py` now has `CRYPTO_MIN_EDGE_THRESHOLD = 0.12`. All future crypto trades will be filtered at 12%.

---

## Recommendations

1. **Fix `strategy.py` crypto min edge**: Update `MIN_EDGE['crypto']` from `0.10` → `0.12` to stay consistent with `config.py`. When `strategy.py` gets wired in, this would otherwise silently allow 10% edge trades.

   ```python
   # strategy.py line ~15
   MIN_EDGE = {
       'weather': 0.15,
       'crypto':  0.12,   # ← was 0.10; raise to match config.py
   }
   ```
   **Owner:** SA-3 (Developer), needs Optimizer sign-off per team rules.

2. **Wire `strategy.py` into the crypto path**: Until `should_enter()` is called for crypto, edge thresholds and daily cap enforcement are split across `config.py` (filter) and `strategy.py` (sizing). The daily cap check was added to `ruppert_cycle.py` as a workaround, but full consolidation into `strategy.py` is cleaner and reduces divergence risk.

3. **Consider adding a threshold version stamp to trade logs**: Logging `min_edge_threshold_at_execution` with each trade would prevent future confusion when thresholds change.

---

## Files Reviewed

| File | Key Finding |
|------|-------------|
| `ruppert-tradingbot-demo/bot/strategy.py` | `MIN_EDGE['crypto'] = 0.10` — stale, inconsistent with config |
| `ruppert-tradingbot-demo/config.py` | `CRYPTO_MIN_EDGE_THRESHOLD = 0.12` (current, after Batch E) |
| `ruppert-tradingbot-demo/ruppert_cycle.py` | Uses `config.CRYPTO_MIN_EDGE_THRESHOLD` directly; does not call `strategy.should_enter()` |
| `ruppert-tradingbot-demo/logs/trades_2026-03-11.jsonl` | Trades placed at 15:00:05 under old 10% threshold |
| git commit `8585781` | Threshold raised 10% → 12% on 2026-03-12 23:26:50 (after trades) |
