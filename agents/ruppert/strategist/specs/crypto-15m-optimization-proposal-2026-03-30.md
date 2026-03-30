# Crypto 15m Module — Optimization Proposal
**Date:** 2026-03-30  
**Author:** Strategist (Ruppert)  
**Inputs:** `crypto-15m-analysis-2026-03-30.md` (Data Scientist)  
**Mode:** DEMO only — conservative, reversible changes  
**Goal:** Reach 30 trades as fast as possible to unlock Optimizer

---

## Executive Summary

The system has strong signals (median edge 0.173 = 9× threshold) but zero entries. The problem is entirely in timing/gating infrastructure, not signal quality. Two issues account for ~92% of all skips:

1. **STRATEGY_GATE `too_close_to_settlement`** — a module-agnostic gate set at 0.5h (30 min) is physically impossible to satisfy on 15m contracts (max window = 0.25h). This gate blocks **100% of decisions that reach it** — which after timing filters is ~56% of qualified post-timing decisions, and 93.4% of all strong-signal records.

2. **Timing gates (LATE_WINDOW + EARLY_WINDOW)** — the actual entry window is 120-720s = 10 min out of 15, and WS reconnects are landing at ~775s median (55s past cutoff), eating further entries.

Fix Issue 1 first. It's the highest-impact, lowest-risk change and requires only a config addition + a 3-line strategy.py patch. Issues 2-4 are secondary wins.

---

## Issue 1: STRATEGY_GATE `too_close_to_settlement` [P0 — CRITICAL]

### Root Cause

**Location:** `agents/ruppert/strategist/strategy.py`, line `MIN_HOURS_ENTRY = 0.5`

**What it does:** In `should_enter()`, the first check is:
```python
if hours < MIN_HOURS_ENTRY:
    return {'enter': False, 'size': 0.0,
            'reason': f'too_close_to_settlement ({hours:.2f}h < {MIN_HOURS_ENTRY}h)'}
```

**Why it always fires for 15m:** In `crypto_15m.py`, the signal passes:
```python
'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
```
A 15m window is 900 seconds = 0.25h total. At the start of the primary entry window (elapsed=120s), `hours_to_settlement = (900-120)/3600 = 0.217h`. Even at window-open (elapsed=0), the maximum is **0.25h**. Since `MIN_HOURS_ENTRY = 0.5h`, **every single 15m entry is blocked by this gate.** The gate was designed for hourly or daily markets and was never adapted for 15m contracts.

### What the Data Shows

The DS found the gate fires when 0.05–0.22h remain before settlement — which is the **entire** valid entry zone for a 15m contract. The 0.3–0.5h band never triggers because it's physically unreachable on a 15m window.

Strong-signal records blocked by this gate (edge ≥ 0.02 AND P_final ≥ 0.55): **4,623 of 4,950 = 93.4%**.

### Proposed Fix

Add a per-module override for `MIN_HOURS_ENTRY`, mirroring how `MIN_CONFIDENCE` is already implemented as a dict in `config.py`.

**Step 1: Add to `config.py` (environments/demo/config.py):**
```python
# Minimum hours to settlement before allowing entry — per module
# Default (hourly/daily markets): 0.5h (30 min)
# crypto_15m: 0.04h (≈2.4 min) — 15m window is only 0.25h total
MIN_HOURS_ENTRY = {
    'default':    0.5,
    'crypto_15m': 0.04,   # 2.4 min remaining = allows all primary + secondary window entries
}
```

**Step 2: Update `strategy.py` `should_enter()`, replace the time gate block:**
```python
# --- Time gate ---
_min_hours_map = getattr(config, 'MIN_HOURS_ENTRY', None)
if isinstance(_min_hours_map, dict):
    _effective_min_hours = _min_hours_map.get(signal_module, _min_hours_map.get('default', MIN_HOURS_ENTRY))
else:
    _effective_min_hours = MIN_HOURS_ENTRY  # fallback: hardcoded 0.5h constant
if hours < _effective_min_hours:
    return {'enter': False, 'size': 0.0,
            'reason': f'too_close_to_settlement ({hours:.2f}h < {_effective_min_hours}h)'}
```

**Current → Proposed:**
| Parameter | Current | Proposed |
|-----------|---------|----------|
| MIN_HOURS_ENTRY (strategy.py constant) | 0.5h (global) | 0.5h (default, unchanged) |
| MIN_HOURS_ENTRY for crypto_15m | 0.5h (inherited) | **0.04h** |

### Why 0.04h?

- **Primary window** (elapsed 120-480s): hours_to_settlement = 0.117–0.217h → all pass ✓
- **Secondary window** (elapsed 480-720s): hours_to_settlement = 0.050–0.117h → all pass ✓
- **Entry cutoff** (elapsed=720s): hours_to_settlement = 0.050h → passes ✓
- **0.04h threshold** (2.4 min remaining): would only block if elapsed ≥ 756s. But `CRYPTO_15M_ENTRY_CUTOFF_SECS = 720s` timing gate already handles this — the timing gate is the binding constraint, not the strategy gate.
- **All other modules** (weather, crypto, econ, geo, fed) are completely unaffected — they still use 0.5h.

### Rationale

0.04h is not arbitrary. It provides a small safety buffer (don't enter with <2.4 min to settlement) while allowing the timing gate to be the true control surface. For 15m binaries, price direction is essentially locked by the settlement moment — entering at 3-4 min remaining is operationally fine.

Do NOT use 0.0h — we want an explicit floor, not no protection.

### Expected Impact
- **Unlocks ~4,623 strong-signal primary-window records** from STRATEGY_GATE blocking
- **In the current run rate (41h data):** This should drive the system to enter on qualified signals almost every window where signals are strong
- **Conservative estimate:** 2-5 entries per hour across 4 tickers in favorable windows
- **Path to 30 trades:** Days, not weeks

### Risk
- **Low.** This is DEMO only. No real capital at risk.
- The only new risk is entering trades that were previously blocked. Given median edge = 0.173 (9× the 0.02 floor), these are high-quality signals.
- The timing gate (`CRYPTO_15M_ENTRY_CUTOFF_SECS`) remains fully intact as the late-window guard.
- All other modules (weather, crypto hourly, econ) are unaffected.
- **Reversible:** Change `MIN_HOURS_ENTRY` dict entry back to 0.5 to restore prior behavior.

---

## Issue 2: EARLY_WINDOW 120s Cutoff [P2]

### Root Cause

**Location:** `crypto_15m.py`, hardcoded in:
```python
if elapsed_secs < 120:
    _log_decision(..., 'SKIP', 'EARLY_WINDOW', ...)
    return
```

Current: First 120s (2 min) of every 15m window is blocked. Combined with `ENTRY_CUTOFF_SECS=720s`, the actual entry window is 120-720s = 600s = 10 min out of 15.

### What the Data Shows

- 34,880 records blocked by EARLY_WINDOW (30.8% of all decisions)
- **Median elapsed for EARLY blocks: 64.2s** — the WS is routinely firing in the 60-119s range
- 9,331 records (26.8% of EARLY_WINDOW) are in the 90-120s band — 30 seconds away from being eligible
- If cutoff drops to 60s: 18,968 records re-admitted (90-120s + 60-90s bands)
- If cutoff drops to 90s: 9,331 records re-admitted (90-120s band only)

### Proposed Fix

**Current → Proposed:**
| Parameter | Current | Proposed |
|-----------|---------|----------|
| EARLY_WINDOW hardcoded cutoff | 120s | **60s** |

**Add to `config.py`:**
```python
CRYPTO_15M_EARLY_WINDOW_SECS = 60   # DATA COLLECTION: was 120s; 60s allows more early-window entries
```

**Update `crypto_15m.py`:**
```python
_early_cutoff = getattr(config, 'CRYPTO_15M_EARLY_WINDOW_SECS', 120)
if elapsed_secs < _early_cutoff:
    ...
```

### Why 60s?

- At 60s elapsed, 840s remain in the window — well before midpoint
- TFI, OBI, MACD signals are computed from rolling 5-min windows and OKX orderbook snapshots — they don't need the first 2 min to "settle"
- The 120s guard was likely a conservative warm-up margin; 60s is still a meaningful buffer
- Risk: at 60-120s, the candle is just 1-2 minutes old. MACD on 5m candles is inherently a bit delayed, but TFI and OBI are near-realtime
- **Conservative alternative:** 90s (re-admits only 9,331 records, lower risk but less impact)

### Expected Impact
- 60s cutoff: ~18,968 additional records eligible (combined 60-120s band re-admitted)
- Secondary effect: improves primary zone coverage, since many WS events arrive in this 60-120s zone
- **In practice:** Incremental — the STRATEGY_GATE fix (Issue 1) will have already unlocked the most entries; this provides additional margin

### Risk
- **Low-Medium.** Slightly noisier signal quality in 60-90s range vs 90-120s. But since edge threshold (0.02) still applies, weak signals won't enter.
- **Reversible:** Change `CRYPTO_15M_EARLY_WINDOW_SECS` back to 120.
- **Recommendation:** Apply 90s first; re-evaluate after first 30 trades.

---

## Issue 3: LATE_WINDOW Classification Bug (660 vs 720s) [P3 — Investigate]

### Root Cause (Probable)

The DS flagged **12,104 LATE_WINDOW records with elapsed_secs < 720s** (range 660-719.9s). These should be in the secondary window (720s cutoff), not LATE.

Looking at `crypto_15m.py`:
```python
_entry_cutoff = getattr(config, 'CRYPTO_15M_ENTRY_CUTOFF_SECS', 660)
```

**The default fallback is `660`, but `config.py` sets `CRYPTO_15M_ENTRY_CUTOFF_SECS = 720`.**

The most likely explanation: these 12,104 records were logged **before `CRYPTO_15M_ENTRY_CUTOFF_SECS` was added to config.py** — i.e., during the early part of the data window (2026-03-28 to 2026-03-29) when the code fell back to the hardcoded 660 default. After the config value was set, records correctly use 720.

### Proposed Action

**Do NOT defer. Verify and close quickly.**

1. Check the git log for `config.py` — when was `CRYPTO_15M_ENTRY_CUTOFF_SECS = 720` added?
2. Confirm: are the 12,104 records concentrated in early timestamps (2026-03-28)?
3. If yes: this is **stale data artifact**, not an ongoing bug. No code change needed.
4. If records span to 2026-03-30 as well: there may be a startup race condition where `config.py` isn't loaded before the first WS tick. Investigate the import order in `ws_feed.py` / module startup.

**In either case:** The line `getattr(config, 'CRYPTO_15M_ENTRY_CUTOFF_SECS', 660)` should be updated to default to `720` (not `660`) as a defensive measure:

**`crypto_15m.py` change (defensive):**
```python
# Old: default=660 (wrong -- 720 is correct)
_entry_cutoff = getattr(config, 'CRYPTO_15M_ENTRY_CUTOFF_SECS', 720)
```

| Parameter | Current | Proposed |
|-----------|---------|----------|
| `CRYPTO_15M_ENTRY_CUTOFF_SECS` default in code | 660 (fallback) | **720** (defensive default) |
| `CRYPTO_15M_ENTRY_CUTOFF_SECS` in config.py | 720 | 720 (unchanged) |

### Expected Impact
- **Negligible in production** (config.py sets 720 so this is a safety fix only)
- Eliminates data ambiguity for future DS analysis
- **Zero risk** — code change is one character: `660` → `720` in default parameter

---

## Issue 4: LATE_WINDOW Median at 775s — Raise Cutoff vs Fix WS [P1]

### Root Cause

WS reconnects are arriving at ~775s elapsed median — **55 seconds past the 720s entry cutoff**. This means the WS reconnect event lands after the trading window has closed, and the system immediately classifies the decision as LATE_WINDOW.

DS data: 18,208 records in the 720-780s range (31.4% of all LATE_WINDOW) — these are "close calls" that missed by 0-60 seconds.

### Two Options

**Option A: Raise ENTRY_CUTOFF_SECS from 720s to 800s (Quick win)**

| Parameter | Current | Proposed |
|-----------|---------|----------|
| `CRYPTO_15M_ENTRY_CUTOFF_SECS` (config.py) | 720s | **800s** |

- Re-admits 18,208 records (all 720-780s close calls, plus some 780-800s)
- At 800s elapsed, hours_to_settlement = (900-800)/3600 = 0.028h (1.7 min remaining)
- Entry at 1.7 min remaining on a 15m binary is operationally fine — the direction is essentially decided at that point, and our edge is based on spot signals that don't change in the last 1-2 min
- Min-edge and strategy gate still apply — garbage signals won't enter
- **Risk:** Very close to settlement. Kalshi may have reduced liquidity at ~800s, but the DS shows THIN_MARKET only blocks 2.6% of all decisions — liquidity is not the issue in the 720-800s range specifically

**Option B: Fix WS Reconnect Latency (Root cause, longer term)**

- DS found March 30 had only 55.9% coverage (vs 96.1% on March 29) — suggests systematic WS instability
- Fixing the root cause (why is WS reconnecting at ~775s median?) would benefit all windows, not just 720-800s
- But this requires investigating `ws_feed.py` reconnect behavior and may involve infrastructure changes
- Timeline: days to weeks, not hours

### Proposed Action: BOTH, sequenced

**Immediate (config change, low risk):** Raise `CRYPTO_15M_ENTRY_CUTOFF_SECS` to 800s.
**Follow-up (investigation spec):** File a separate bug report for WS reconnect latency.

**Why 800s specifically?**
- Captures the bulk of close calls (18,208 records in 720-780s band)
- Leaves 100s buffer before end of window (900s) — sensible floor
- Avoids setting cutoff to 840s+ which would push entries within 1 min of settlement
- After Issue 1 is fixed, the system will enter on many windows before they reach 720s anyway — this is a safety net, not the main path

### Expected Impact
- Re-admits ~18,208 LATE_WINDOW close calls
- In practice, many of these will be filtered by THIN_MARKET (WS reconnect events sometimes land during low-liquidity moments), but a meaningful fraction will enter
- **Secondary effect on Issue 3:** If ENTRY_CUTOFF_SECS moves to 800s, the "660 vs 720" bug becomes even less important

### Risk
- **Low.** DEMO mode. At 800s elapsed, trading is tight but not reckless on 15m binaries.
- **Reversible:** Change config back to 720 to restore prior behavior.

---

## Priority and Implementation Order

| Priority | Issue | Config Change | Code Change | Expected Entries Unlocked |
|----------|-------|--------------|-------------|--------------------------|
| **P0** | STRATEGY_GATE: MIN_HOURS_ENTRY | Add `MIN_HOURS_ENTRY` dict with `crypto_15m: 0.04` | 3-line patch in `strategy.py` `should_enter()` | **~4,623 strong-signal records → primary driver of entries** |
| **P1** | LATE_WINDOW cutoff | `CRYPTO_15M_ENTRY_CUTOFF_SECS: 720 → 800` | Defensive default change in `crypto_15m.py` | ~18,208 close-call records re-admitted |
| **P2** | EARLY_WINDOW cutoff | Add `CRYPTO_15M_EARLY_WINDOW_SECS: 90` (conservative) | Use config value in `crypto_15m.py` | ~9,331 records re-admitted |
| **P3** | LATE_WINDOW bug (660/720) | None | 1-char defensive fix (`660→720` default) | Negligible (data quality only) |

**Recommended sequence:**
1. Apply P0 immediately — this alone should unlock the path to 30 trades
2. Apply P1 concurrently (trivial config change, zero-risk)  
3. Apply P3 concurrently (defensive fix, <1 min effort)
4. Apply P2 after first 5 trades confirm P0/P1 are working
5. Investigate WS reconnect (P1 root cause) as a separate task after 30 trades collected

---

## What NOT to Touch (Per Constraints)

- Signal weights (W_TFI, W_OBI, W_MACD, W_OI) — not a bottleneck
- Kelly sizing, MIN_EDGE, MIN_CONVICTION thresholds — already relaxed for data collection; signals are passing
- Exit thresholds, 95¢ rule, reversal rules — no need to change
- Market quality filters (THIN_MARKET, WIDE_SPREAD) — only 4.3% of decisions; secondary concern

---

## Summary of Expected Outcome

After P0 + P1 are applied:
- **STRATEGY_GATE** no longer blocks any primary/secondary window 15m entries
- **LATE_WINDOW** now admits 18,208 additional close-call records
- Combined with existing strong signal quality (median edge = 0.173), the system should begin entering trades within hours of deployment
- Path to 30 trades: **2-5 days** at current market activity levels vs. **never** at current configuration

---

*Generated by Ruppert Strategist subagent | 2026-03-30*
