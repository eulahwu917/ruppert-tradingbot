# DS Audit — 2026-03-30 Afternoon
**Prepared by:** Data Scientist subagent  
**Time:** ~13:21 PDT  
**Status:** Findings only. No fixes applied.

---

## Investigation 1: Dashboard P&L Numbers

### 1. What is closed P&L in pnl_cache.json?

```
closed_pnl: -1331.03
open_pnl:    0.00
```

### 2. Today's 15m Trades — Settle Count & P&L

**15 settle records** (action=settle, module=crypto_15m) found in today's log.

| Ticker | Result | PNL |
|---|---|---|
| KXBTC15M-26MAR301300-00 | LOSS | -78.12 |
| KXETH15M-26MAR301300-00 | LOSS | -78.12 |
| KXBTC15M-26MAR301315-15 | LOSS | -20.16 |
| KXETH15M-26MAR301330-30 | LOSS | -83.16 |
| KXBTC15M-26MAR301330-30 | LOSS | -83.15 |
| KXBTC15M-26MAR301415-15 | LOSS | -83.07 |
| KXXRP15M-26MAR301415-15 | LOSS | -83.16 |
| KXDOGE15M-26MAR301430-30 | LOSS | -82.80 |
| KXXRP15M-26MAR301430-30 | LOSS | -83.05 |
| KXBTC15M-26MAR301430-30 | LOSS | -82.95 |
| KXETH15M-26MAR301430-30 | LOSS | -82.96 |
| KXETH15M-26MAR301445-45 | WIN | +127.80 |
| KXBTC15M-26MAR301445-45 | WIN | +173.53 |
| KXDOGE15M-26MAR301445-45 | WIN | +138.88 |
| KXXRP15M-26MAR301445-45 | WIN | +191.13 |

Plus 1 weather settle: KXHIGHNY-26MAR31 LOSS -76.80

**15m settle net: -209.36**  
**All settle net today: -286.16**

Also 14 WS exit records (action=exit) today with total pnl: **+1,906.33**

**Total today's closed P&L from log: +1,620.17**

### 3. Does Dashboard Account Value / Closed P&L Make Sense?

**pnl_cache (-1331.03) is clearly cumulative (multi-day), NOT today-only.**  
Today's activity alone is +$1,620.17 from the trades log. If the dashboard is presenting `pnl_cache.closed_pnl` as today's closed P&L, it is wrong. Prior history implied by subtraction = **-2,951.20** (large cumulative drawdown before today).

No `/api/state` was accessible to compare dashboard display value directly, so this is a file-level finding only.

### 4. Duplicate Settle Records (Same Ticker Appearing Twice)?

**No duplicate settle records found** — each ticker+slot appears once in settle records.

However, **TWO MISSING SETTLE records identified:**

- `KXBTC15M-26MAR301300-00`: Two buy records opened at 09:46:39 (124 contracts @ 63¢ each). Only **one** settle record present. One position (124 contracts @ 63¢) has no corresponding settle → loss of ~-78.12 not recorded in pnl_cache.
- `KXETH15M-26MAR301300-00`: Two buy records opened (130 contracts @ 60¢, 124 contracts @ 63¢). Only **one** settle record (the 124@63 position). The 130@60 position has no settle → loss of ~-78.00 not recorded in pnl_cache.

**pnl_cache is understated by approximately -$156 from missing settlements.**

### 5. Trades Log Settle Sum vs pnl_cache

| Source | Value |
|---|---|
| Sum of all settle pnl in today's log | -286.16 |
| Sum of all exit pnl in today's log | +1,906.33 |
| Today's total closed P&L from log | **+1,620.17** |
| pnl_cache.closed_pnl | **-1,331.03** |

**They do not match.** pnl_cache is cumulative across all time; today's log represents only today's events. This is expected behavior if pnl_cache accumulates across sessions — but it means pnl_cache alone cannot tell you today's P&L.

---

### ⚠️ Key Anomaly: Duplicate WS Exit Record

**KXDOGE-26MAR3017-B0.092** has **two exit records** 3 seconds apart:

| trade_id | timestamp | contracts | entry | exit | pnl |
|---|---|---|---|---|---|
| 485fb3d4 | 09:36:32 | 109 | 36¢ | 81¢ | 49.05 |
| f5aa2b3a | 09:36:35 | 109 | 36¢ | 81¢ | 49.05 |

Identical ticker, contracts, prices, pnl — 3-second gap. **One is a ghost exit fired by ws_position_tracker twice.** This inflates closed P&L by +$49.05 in the trades log and (if pnl_cache ingests exits) in pnl_cache as well.

---

### ⚠️ Secondary Anomaly: Double Position Opened on KXDOGE15M-26MAR301245-45

Two buy records opened 1 second apart (09:32:59 and 09:33:00), both 202 contracts @ 38¢ NO side. Both exited, contributing pnl of +117.16 and +119.18. Likely the crypto_15m scanner fired twice in the same candle, opening duplicate positions. Total overstatement if one position is phantom: +$117–119.

---

## Investigation 2: Watchdog Keeps Dying

### 1. How is the watchdog launched?

Via **Windows Task Scheduler** task named `Ruppert-WS-Watchdog`:
```
Command: python.exe -m scripts.ws_feed_watchdog
Working Dir: C:\Users\David Wu\.openclaw\workspace
Run As: David Wu
```

### 2. Task Scheduler Settings — Are They Correct?

**Schedule Type: `At logon time`**  
This is the core problem. The task only launches once when the user logs into Windows. There is:

- ❌ **No restart-on-failure setting** — if it crashes, it stays dead
- ❌ **No daily trigger or recurring schedule** — it does not relaunch on a schedule
- ❌ **No recovery action configured** (would appear as "Restart every X minutes" in task settings)
- ⚠️ **Power Management: Stop On Battery Mode** — if the machine switched to battery power, the task is killed outright with no restart

Last Result code from schtasks: **267009** — non-zero, indicating the process exited with an error.

### 3. Why Did It Die Today?

**Timeline from watchdog.log:**

| Time | Event |
|---|---|
| 2026-03-29 22:39:39 | Watchdog started (no further entries that night) |
| — | ~14.7 hour gap — complete silence |
| 2026-03-30 13:20:07 | Watchdog started again (manual restart or login?) |

With a 5-minute check interval, a running watchdog would log every 5 minutes when stale. **Zero entries between 22:39:39 and 13:20:07 means the process died very shortly after starting** (before its first check interval), or was killed immediately.

Likely causes (in order of probability):

1. **Process crash on startup** — the watchdog started at 22:39:39 but raised an unhandled exception before logging its first check. The 14.7h gap with zero entries (not even a stale-heartbeat log) suggests it died within seconds of launch. Exit code 267009 supports a crash.
2. **Battery/power event** — Power Management setting "Stop On Battery Mode" would silently kill the task if the machine switched to battery at any point overnight.
3. **No restart mechanism** — Once dead for any reason, it stays dead until the next user login (which triggered the 13:20 restart).

**Root cause: Task Scheduler trigger is `At logon time` with no restart-on-failure.** A single crash = permanent outage until next login. The watchdog needs a `Restart` action (e.g., restart every 1 minute, up to 3 times) in its task settings to be resilient.

---

## Summary of Findings

| Issue | Severity | Impact |
|---|---|---|
| Duplicate WS exit for KXDOGE classic | High | +$49.05 phantom P&L in closed_pnl |
| Two missing settle records (BTC + ETH 1300 slot) | High | ~-$156 understated loss in pnl_cache |
| Double position opened on KXDOGE15M 12:45 slot | Medium | Double contracts traded, ~$236 potentially phantom gain |
| pnl_cache is cumulative — not daily | Low | Dashboard confusion if displayed as "today" |
| Watchdog: `At logon time` trigger, no restart-on-failure | Critical | Every crash = hours of ws_feed downtime |
| Watchdog: Stop On Battery Mode enabled | Medium | Silent kill on any battery/power event |
