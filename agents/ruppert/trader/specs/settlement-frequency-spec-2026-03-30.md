# Settlement Frequency Fix Spec
**Date:** 2026-03-30  
**Author:** Trader (subagent)  
**Priority:** High  
**Type:** Scheduling fix (not logic fix)

---

## Problem

5 positions (KXBTC15M/KXETH15M for 13:00, 13:15, 13:30 UTC windows) sat unsettled for ~1.5 hours after Kalshi finalized them with result=NO. Settlement checker logic is correct — when run manually it settled all 5 in seconds. Root cause is scheduling frequency.

---

## What the Code Says

`post_trade_monitor.py` docstring states:
> "Runs every 30 minutes via Task Scheduler (6am-11pm)."

But `check_settlements()` has **no internal loop** — it runs once per invocation and exits. It's entirely dependent on the scheduler calling it.

---

## What the Scheduler Actually Has

Two relevant tasks found:

### `\Ruppert-PostTrade-Monitor`
- **Runs:** `-m agents.ruppert.trader.position_monitor` (not `post_trade_monitor.py` directly — separate entry point)
- **Frequency:** Every **15 minutes**
- **Next Run:** N/A (may be disabled or misfiring — `Next Run Time: N/A`)
- **Comment:** "Ruppert post-trade monitor every 15min 6am-11pm"

### `\Ruppert-SettlementChecker`
- **Runs:** `-m environments.demo.settlement_checker`
- **Frequency:** **Daily** — fires at **8:00 AM** and **11:00 PM** only (two triggers, no repeat)
- **Status:** Enabled

---

## Root Cause

The `\Ruppert-SettlementChecker` task fires only **twice a day** (8 AM and 11 PM). For 15m contracts that expire every 15 minutes, this means worst-case **~15 hour lag** between expiry and settlement. The 1.5-hour lag observed today was actually best-case — the positions happened to expire between the 8 AM trigger and the next 11 PM trigger.

The `\Ruppert-PostTrade-Monitor` task (15-min repeat) is the right frequency but shows `Next Run Time: N/A` — it may be misfiring, stopped, or the `position_monitor` module it calls may not invoke `check_settlements()` the same way.

---

## What the Right Frequency Is

**15m contracts expire every 15 minutes.** Target: settle within 1–2 cycles after expiry = **within 15–30 minutes**.

Recommended settlement check frequency: **every 15 minutes** (matching the contract cycle).

---

## Proposed Fix

### Option A — Fix `\Ruppert-SettlementChecker` schedule (recommended)
Change the existing `\Ruppert-SettlementChecker` task from daily (2x/day) to repeat every 15 minutes during trading hours (6 AM–11 PM PDT).

**schtasks change:**
```
schtasks /Change /TN "\Ruppert-SettlementChecker" /RI 15 /DU 9999 /ST 06:00 /ET 23:00
```
Or delete and recreate with a clean repeat-interval trigger.

### Option B — Verify and fix `\Ruppert-PostTrade-Monitor`
The 15-min monitor already exists but shows `Next Run Time: N/A`. Investigate why it's not firing. If `position_monitor.py` already calls `check_settlements()`, fixing this task alone may be sufficient.

Check: does `agents/ruppert/trader/position_monitor.py` call `check_settlements()`?

### Option C — Add settlement call inside existing crypto scan tasks
The crypto scan tasks (8 AM, 10 AM, 12 PM, 2 PM, 4 PM, 6 PM, 8 PM) already run on a regular cadence. Injecting a `check_settlements()` call at the start of each crypto scan would piggyback settlement onto existing infrastructure with zero new tasks.

---

## Recommendation

**Do Option A + B together:**
1. Diagnose why `\Ruppert-PostTrade-Monitor` shows `Next Run Time: N/A` — fix or recreate it with a 15-min repeat
2. Simultaneously fix `\Ruppert-SettlementChecker` to repeat every 15 min instead of daily-only
3. No logic changes needed — the settlement checker works correctly

**Do NOT do Option C** — coupling settlement to scan tasks creates hidden dependencies and makes the scan tasks slower.

---

## Expected Outcome

After fix: 15m positions settle within **15–30 minutes** of Kalshi finalizing them. The 1.5-hour lag becomes a 15–30 minute lag at worst.

---

## Out of Scope

- Logic changes to `check_settlements()` — it's correct
- Changes to how settlements are written to trade logs
- Any live trading changes
