# Developer Task: Remove Bearish Block from Crypto Signal Logic
_Date: 2026-03-12 | SA-3 Developer_

---

## Task Summary
Remove the bearish block from the automated crypto scan in `ruppert_cycle.py` so the
existing NO/high-strike edge logic runs regardless of smart money direction signal.

**Authorized by:** CEO (Ruppert) + David Wu

---

## Investigation Findings

### Files Reviewed
1. `kalshi-bot/main.py` — Main loop orchestrator; handles weather/econ/gaming/geo modules. No crypto scan here; no direction gate found.
2. `kalshi-bot/crypto_client.py` — Builds price signals (`direction = 'BULLISH'|'BEARISH'|'NEUTRAL'` from technical analysis). Uses `momentum_shift = ±sigma*0.08` — a small drift adjustment; NOT the block. Direction is also used for confidence boosting (smart money alignment), not to block entries.
3. `kalshi-bot/ruppert_cycle.py` — **This is where the block lives.** STEP 4 runs the automated crypto scan using a simplified log-normal edge model (`band_prob`).

### The Block

**File:** `kalshi-bot/ruppert_cycle.py`  
**Location:** STEP 4, immediately before the scan loop

```python
# BEFORE (removed):
drift_sigma = -0.6 if direction == 'bearish' else (0.4 if direction == 'bullish' else 0.0)
```

**Mechanism:** When `direction == 'bearish'` (from `logs/crypto_smart_money.json`, produced by `fetch_smart_money.py`), the model applied a `−0.6σ` downward drift to the log-normal price distribution. This shifted the expected price ~1.3% below spot for BTC with 18h horizon. For high-strike bands (the primary NO/edge opportunities), this made `prob_model` very small (1–2%), which in turn pulled `edge_no = mkt_yes - prob_model` to just below the 10% threshold (`CRYPTO_MIN_EDGE_THRESHOLD`). Result: every candidate NO position was filtered out, effectively blocking all crypto entries when smart money was bearish.

### What Was Kept Intact
- `direction` variable still loaded from smart money cache (STEP 2)
- `direction` still included in trade `note` field for logging/reporting
- `direction` still shown in final cycle summary line
- All edge/Kelly/confidence/cap thresholds unchanged
- `crypto_client.py` `momentum_shift` (±8% of sigma) left in place — that's a minor technical signal adjustment, not a directional gate

---

## The Fix

**File:** `kalshi-bot/ruppert_cycle.py`

```python
# AFTER:
# Bearish block removed (approved 2026-03-12: CEO + David).
# Direction signal is kept for logging/reporting below, but no longer
# used to bias the edge model — the NO/high-strike logic runs regardless.
drift_sigma = 0.0
```

`drift_sigma = 0.0` means `drift = 0.0 * sigma = 0.0` for all assets. The probability model now uses the neutral log-normal distribution (E[price] = current price), letting the edge filter surface genuine NO/high-strike opportunities regardless of smart money direction.

---

## Git Status
- **Staged:** `ruppert_cycle.py` (`git add` done)
- **Not pushed:** Awaiting CEO review before `git push`

---

## Side Notes / Things to Flag

1. **`scan_crypto_edge.py`** uses `BEARISH_DRIFT_SIGMA = -0.6` unconditionally (always bearish). This is a standalone diagnostic script, not part of the live scan loop. No change made — not in scope.

2. **`ruppert_cycle.py` also had an uncommitted change** (wallet updater in STEP 1b referencing `bot.wallet_updater`) already in the working tree before this task. That change is unrelated and was left untouched.

3. **`bot/main.py` does not exist** — the task referenced it but the actual crypto directional logic was in `ruppert_cycle.py` (the cycle runner) and `crypto_client.py`. Flagged for CEO.

4. **`main.py` (root)** handles weather via `bot/strategy.py` → `should_enter()`. No direction gate exists there — weather was already direction-agnostic. No change needed.

---

## Reporting Chain
SA-3 (Developer) → SA-4 (QA) → CEO (Ruppert) → David (if live money)
