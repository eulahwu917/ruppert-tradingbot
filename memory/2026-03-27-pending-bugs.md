# Pending Bug Batch — 2026-03-27 (RESOLVED)

## Context
Investigating trades from today's scans before fixing. David's instruction: wait for 6pm + 7pm scans to see if more issues surface, then fix all at once.

---

## Bug 1: City dedup not working for same-city multi-band trades
- **Evidence**: 3pm scan — 4 Chicago trades (T37, T44, B39.5, B41.5) + 2 Miami trades (B79.5 + T79) for same city+date
- **Root cause**: Fix (`323e4ab`) committed 4:43pm, AFTER the 3pm scan
- **Status**: Should be clean at 7pm — confirm in logs
- **Fix needed**: None if 7pm scan shows 1 trade per city

---

## Bug 2: Chicago probabilities are logically contradictory
- **Evidence**: T37 YES (noaa_prob=0.95) = "high < 37°F" AND T44 YES (noaa_prob=0.95) = "high > 44°F" — can't both be true
- **Root cause hypothesis**: `edge_detector.py` may be computing `P(high > threshold)` for ALL market types, including T-lower ("<X°F") markets where it should compute `P(high < threshold)`
- **Status**: ⚠️ UNCONFIRMED — watch 7pm scan for Chicago T-lower markets
- **Fix needed**: YES — if confirmed, direction inversion in edge_detector for T-lower markets

---

## Bug 3: noaa_prob=1.0 on Miami + Philly Mar 28 trades
- **Evidence**: 3 trades with noaa_prob=1.0, confidence=1.0 (KXHIGHMIA-26MAR28-B79.5, T79, KXHIGHPHIL-26MAR28-T42)
- **Root cause**: Ensemble member counting (`prob = above/total`) CAN return exactly 1.0 if all members agree. Mathematically valid but suspicious. May be same T-direction flip issue as Bug 2 (Philly T42 = "high < 42°F" on Mar 28 — maybe the ensemble genuinely agrees it won't hit 42°F, but the direction flip makes it trade YES when it should skip/trade NO).
- **Status**: ⚠️ UNCONFIRMED — linked to Bug 2
- **Fix needed**: Investigate T-direction computation in edge_detector + openmeteo_client

---

## Bug 4: Crypto confidence > 1.0 (ETH NO @ 66c, confidence=1.188)
- **Evidence**: trade `cf18392c` at 15:05 — confidence=1.188
- **Root cause**: `_spread_score` not clamped; inverted orderbook (yes_ask < no_ask) produced spread < 0, so `1.0 - (negative/20) > 1.0`. Fix committed in `323e4ab` (4:43pm).
- **Status**: ✅ Pre-fix artifact — should be clean going forward
- **Fix needed**: None (already fixed)

---

---

## Bug 5: Telegram notifications not firing for 6pm + 7pm scans
- **Evidence**: 5am/7am/3pm all log "[SCAN NOTIFY] Cycle summary sent directly via Telegram". 6pm and 7pm activity logs end abruptly after `Executed X/X opportunities` with NO notify line at all.
- **Root cause hypothesis**: `openclaw` CLI not on PATH when Task Scheduler runs from the new `projects/ruppert-tradingbot-demo/` working directory. Or the notify call is silently crashing after a code path that changed. Need to check `ruppert_cycle.py` notify section and Task Scheduler working dir config.
- **Status**: ⚠️ CONFIRMED — notifications broken for 6pm + 7pm scans
- **Fix needed**: YES — investigate PATH or notify call crash in ruppert_cycle.py

---

## Confirmed Clean
- Dedup fix: ✅ committed
- Crypto confidence ceiling: ✅ committed
- Cross-cycle dedup (state.json): ✅ committed
- mode handlers (econ_prescan/weather_only/crypto_only): ✅ committed

---

## Watch at 6pm scan (crypto_only)
- Any crypto confidence > 1.0?
- Any new ghost/1c trades?
- Telegram notification received?

## Watch at 7pm scan (weather_only)
- Chicago: should be 1 trade max (highest-edge band)
- Miami: should be 1 trade max (highest-edge band)
- T-lower markets: are probabilities directionally correct?
- Any noaa_prob=1.0 trades?
- Telegram notification received?
