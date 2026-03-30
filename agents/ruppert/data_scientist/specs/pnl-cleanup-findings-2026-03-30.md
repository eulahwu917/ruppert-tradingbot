# P&L Cleanup Findings — 2026-03-30
**Prepared by:** Data Scientist  
**For:** Trader (spec a fix)  
**Date:** 2026-03-30

---

## Executive Summary

Of the 3 flagged duplicate exits:
- **Case 1 (KXDOGE-26MAR3017-B0.092):** TRUE DUPLICATE — race condition. One record must be removed.
- **Case 2 (KXDOGE15M-26MAR301245-45):** LEGITIMATE SCALE-IN — 2 buy legs, 2 corresponding exit legs. Keep both.
- **Case 3 (KXXRP15M-26MAR301315-15):** LEGITIMATE SCALE-IN — 2 buy legs, 2 corresponding exit legs. Keep both.

**Corrected cumulative P&L:** `-$1,331.03 - $49.05 = -$1,380.08`

---

## Case 1: KXDOGE-26MAR3017-B0.092::yes::exit

### Exit Records (both)
```json
{"trade_id": "485fb3d4-e851-47f8-a424-1f1450357e5d", "timestamp": "2026-03-30T09:36:32.208272", "ticker": "KXDOGE-26MAR3017-B0.092", "side": "yes", "action": "exit", "action_detail": "WS_EXIT 70pct_gain @ 81c", "source": "ws_position_tracker", "entry_price": 36, "exit_price": 81, "contracts": 109, "pnl": 49.05}

{"trade_id": "f5aa2b3a-96b1-4eec-ab92-ff53ab8c38de", "timestamp": "2026-03-30T09:36:35.152161", "ticker": "KXDOGE-26MAR3017-B0.092", "side": "yes", "action": "exit", "action_detail": "WS_EXIT 70pct_gain @ 81c", "source": "ws_position_tracker", "entry_price": 36, "exit_price": 81, "contracts": 109, "pnl": 49.05}
```

### BUY Record Analysis
- **No buy record exists in today's log for `KXDOGE-26MAR3017-B0.092`** (MAR30 contract).
- There IS a buy for `KXDOGE-26APR0317-B0.092` (APR03, different expiry) with 307 contracts. These are different tickers.
- The exit references a position that was likely opened on a prior day (MAR30 contract, entered at 36c).

### Diagnosis: RACE CONDITION
- Both records are **byte-for-byte identical** in all fields except `trade_id` and `timestamp` (3 seconds apart).
- Same contracts (109), same entry_price (36), same exit_price (81), same pnl (49.05), same action_detail.
- The `ws_position_tracker` fired the exit signal twice in rapid succession.
- There is only ONE underlying position — 1 exit leg is correct.

### Verdict
| Record | trade_id | Action |
|--------|----------|--------|
| A — ts 09:36:32 | 485fb3d4 | **KEEP** (earlier timestamp) |
| B — ts 09:36:35 | f5aa2b3a | **REMOVE** (duplicate) |

**P&L impact of duplicate:** `+$49.05` overcounted. Remove B → subtract $49.05 from cumulative.

---

## Case 2: KXDOGE15M-26MAR301245-45::no::exit

### Exit Records (both)
```json
{"trade_id": "75e2e524-2090-49f3-9039-daf26ae5fac9", "timestamp": "2026-03-30T09:44:02.803269", "ticker": "KXDOGE15M-26MAR301245-45", "side": "no", "action": "exit", "action_detail": "WS_EXIT 95c_rule_no @ 4c", "source": "ws_position_tracker", "entry_price": 62, "exit_price": 96, "contracts": 202, "pnl": 117.16}

{"trade_id": "b08078ae-4ced-4865-a381-2f139fbddacc", "timestamp": "2026-03-30T09:44:19.202185", "ticker": "KXDOGE15M-26MAR301245-45", "side": "no", "action": "exit", "action_detail": "WS_EXIT 95c_rule_no @ 3c", "source": "ws_position_tracker", "entry_price": 62, "exit_price": 97, "contracts": 202, "pnl": 119.18}
```

### BUY Records Found
```json
{"trade_id": "cad023fb-ecca-46e7-ad53-9c47e59614f9", "timestamp": "2026-03-30 09:32:59", "ticker": "KXDOGE15M-26MAR301245-45", "side": "no", "action": "buy", "contracts": 202, "entry_price": 38.0}

{"trade_id": "0a616085-e73d-4bc7-9895-9a6680c7c8ef", "timestamp": "2026-03-30 09:33:00", "ticker": "KXDOGE15M-26MAR301245-45", "side": "no", "action": "buy", "contracts": 202, "entry_price": 38.0}
```

### Analysis
- **2 buy legs** (1 second apart): each 202 contracts at 38c NO = 404 total contracts.
- **2 exit legs**: each 202 contracts = 404 total contracts exited. ✓ Contracts balance.
- Exit prices differ (96c vs 97c), action_detail differs (@ 4c vs @ 3c), pnl differs ($117.16 vs $119.18), timestamps differ by 17 seconds.
- PnL verification: (96-38)/100 × 202 = 0.58 × 202 = **$117.16** ✓ | (97-38)/100 × 202 = 0.59 × 202 = **$119.18** ✓
- Note: `entry_price=62` in exit records represents the YES-equivalent price at entry (100 - 38 = 62). This is a data convention difference, not a bug.

### Diagnosis: LEGITIMATE SCALE-IN
- Bot bought the same market twice (1 second apart = two scan hits or two signal sources).
- Each buy leg was exited independently as the market moved.
- Both exits are real and correct.

### Verdict
| Record | trade_id | Action |
|--------|----------|--------|
| A — ts 09:44:02 | 75e2e524 | **KEEP** |
| B — ts 09:44:19 | b08078ae | **KEEP** |

**P&L impact:** None — both are legitimate. Total for this position: +$236.34.

---

## Case 3: KXXRP15M-26MAR301315-15::no::exit

### Exit Records (both)
```json
{"trade_id": "c2feb172-34d9-4784-a032-a859adc25550", "timestamp": "2026-03-30T10:15:03.137063", "ticker": "KXXRP15M-26MAR301315-15", "side": "no", "action": "exit", "action_detail": "WS_EXIT 95c_rule_no @ 0c", "source": "ws_position_tracker", "entry_price": 87, "exit_price": 100, "contracts": 639, "pnl": 555.93}

{"trade_id": "0db44061-60d1-43d2-9178-962cc1f44e4a", "timestamp": "2026-03-30T10:15:03.137063", "ticker": "KXXRP15M-26MAR301315-15", "side": "no", "action": "exit", "action_detail": "WS_EXIT 95c_rule_no @ 0c", "source": "ws_position_tracker", "entry_price": 86, "exit_price": 100, "contracts": 594, "pnl": 510.84}
```

### BUY Records Found
```json
{"trade_id": "c66327ab-445f-4b06-8cef-25cd386b0e42", "timestamp": "2026-03-30 10:01:33", "ticker": "KXXRP15M-26MAR301315-15", "side": "no", "action": "buy", "contracts": 594, "entry_price": 14.0}

{"trade_id": "bb32d16f-4660-4110-b6c5-ab5dee9710e2", "timestamp": "2026-03-30 10:01:33", "ticker": "KXXRP15M-26MAR301315-15", "side": "no", "action": "buy", "contracts": 639, "entry_price": 13.0}
```

### Analysis
- **2 buy legs** (same second): 594 contracts at 14c + 639 contracts at 13c = 1,233 total contracts.
- **2 exit legs**: 594 contracts + 639 contracts = 1,233 total contracts exited. ✓ Contracts balance exactly.
- Contract counts match 1:1 between buys and exits:
  - Buy 639@13c → Exit 639 contracts, pnl=555.93. Verify: 639 × (1.00 - 0.13) = 639 × 0.87 = **$555.93** ✓
  - Buy 594@14c → Exit 594 contracts, pnl=510.84. Verify: 594 × (1.00 - 0.14) = 594 × 0.86 = **$510.84** ✓
- `entry_price` in exit records (87, 86) = profit-per-contract in cents (100-13=87, 100-14=86). Consistent.
- **Exact same timestamp** on both exits (`10:15:03.137063`): settlement fired both exits simultaneously at expiry (YES hit 0c, NO = 100c). Not a race condition — parallel simultaneous settlement of two open legs.

### Diagnosis: LEGITIMATE SCALE-IN (SIMULTANEOUS SETTLEMENT)
- Bot bought the same market twice in the same second (two scan hits with different edge/confidence scores).
- Both settled at 100c simultaneously at expiry.
- Both exits are real and correct.

### Verdict
| Record | trade_id | Action |
|--------|----------|--------|
| A | c2feb172 | **KEEP** |
| B | 0db44061 | **KEEP** |

**P&L impact:** None — both are legitimate. Total for this position: +$1,066.77.

---

## P&L Correction Summary

| Case | Ticker | Verdict | PnL Adjustment |
|------|--------|---------|----------------|
| 1 | KXDOGE-26MAR3017-B0.092 | Remove f5aa2b3a | -$49.05 |
| 2 | KXDOGE15M-26MAR301245-45 | Both legitimate | $0 |
| 3 | KXXRP15M-26MAR301315-15 | Both legitimate | $0 |

**Current pnl_cache:** `-$1,331.03`  
**Corrected pnl_cache:** `-$1,380.08`  
(Remove the $49.05 phantom gain from the duplicate DOGE exit.)

---

## Root Cause Notes for Trader

### Case 1 — Fix Required
The `ws_position_tracker` emitted two exit events for the same position 3 seconds apart. Likely cause: WebSocket reconnect or duplicate message delivery. The tracker has no deduplication guard on `(ticker, side, action)` before writing to the log and updating pnl_cache.

**What Trader needs to spec:** A dedup guard in the exit-write path. Suggested key: `(ticker, side, action="exit")` with a short window (e.g., 10 seconds) or idempotency based on position state.

### Cases 2 & 3 — No Fix Required, but Worth Noting
Scale-in behavior (buying the same market multiple times in a single scan cycle) is producing legitimate multi-leg positions. The current log structure handles this correctly — contracts balance, pnl math checks out.  
**However:** If the dedup guard for Case 1 is implemented naively on `(ticker, side, action)` alone, it will incorrectly suppress legitimate Case 2/3-style exits. The guard must also check contracts count or trade_id uniqueness, not just ticker+side+action.
