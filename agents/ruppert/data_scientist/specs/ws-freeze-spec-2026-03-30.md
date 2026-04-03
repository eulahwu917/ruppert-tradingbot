# WS Feed Freeze & Watchdog Failure — Incident Spec
**Date:** 2026-03-30  
**Authored by:** Data Scientist  
**Status:** Findings complete — awaiting Dev/fix handoff

---

## Incident Summary

The WebSocket feed (PID 56364) stopped heartbeating at **11:33 PDT** (18:33 UTC).  
15m crypto decisions stopped at **11:31 PDT** (last entry: `KXXRP15M-26MAR301445-45`).  
The watchdog **did not restart** the WS feed, leaving it dead for **100+ minutes**.

---

## Findings

### 1. Watchdog log — completely silent after 22:39 PDT on 2026-03-29

The watchdog.log ends at:
```
[2026-03-29 22:39:39] Watchdog starting for environment: demo
[2026-03-29 22:39:39] Check interval: 300s
[2026-03-29 22:39:39] Heartbeat stale threshold: 600s
```

**There are zero watchdog entries for all of 2026-03-30.** The watchdog process itself died sometime overnight on 2026-03-29 after its last startup at 22:39. It never ran again. This is why it didn't detect or restart the frozen WS feed at 11:43 PDT as expected.

### 2. Activity log — WS Feed froze silently at 11:33 PDT

From `activity_2026-03-30.log`:
- WS Feed was actively cycling (Disconnected/Connected loop) until at least ~10:58
- **Last crypto 15m entries:** `11:31:38–11:31:53` (KXETH, KXBTC, KXDOGE, KXXRP all entered 1445-45 window)
- **Last WS Feed heartbeat file timestamp:** `2026-03-30T11:33:24` (confirmed in `ws_feed_heartbeat.json`)
- **No Disconnected/Connected entries after 10:58** in the log — the WS Feed log went completely silent before the heartbeat file was last written

The WS feed did not log a crash, exception, or disconnect. It appears to have entered a **hung state** (connected but not processing/heartbeating), not a clean crash.

### 3. DataAgent audit at 12:00-12:01 PDT — ran after the freeze

At 12:00:55–12:01:07 PDT, the DataAgent ran its hourly cycle:
- Removed 11 orphaned tracker entries
- Reconstructed 2 missing entries (KXBTC15M-26MAR301445-45, KXETH15M-26MAR301445-45)
- Fixed 5 audit issues, 14 auto-fixed
- Updated state.json, cycle_log.jsonl, etc.

**The DataAgent itself ran fine** — it's not the cause. However, the 15m positions entered at 11:31 (KXDOGE15M and KXXRP15M for 1445-45 window) were **not in the tracker** and had to be reconstructed, suggesting the WS feed froze mid-cycle or immediately after the 11:31 entries, before position tracking was written.

### 4. PID 56364 — confirmed dead

```
Get-Process -Id 56364  →  NOT FOUND
```

The WS feed process is no longer running.

---

## Root Cause Analysis

**Two separate failures compounded:**

#### Failure 1: Watchdog process died overnight (primary failure)
The watchdog last logged at `2026-03-29 22:39:39`. It never logged again on 2026-03-30. The watchdog process itself silently terminated — likely due to:
- An unhandled exception in the `run_watchdog()` loop that escaped the `try/except` (e.g., during `time.sleep()` or OS-level signal)
- No crash log, no stderr capture (stderr is `DEVNULL` for ws_feed; the watchdog itself logs to file but only inside the try/except — outer crashes are silent)
- No process supervisor watching the watchdog itself

**The watchdog has no watchdog.** If it crashes, nothing restarts it.

#### Failure 2: WS feed entered a hung state (secondary failure)
The WS feed (PID 56364) stopped heartbeating at 11:33 PDT but did not log a crash or disconnect. This is a **silent hang** — the Python process was still alive (no OS kill) but stopped doing useful work. The heartbeat update loop stalled without raising an exception.

Common causes for this pattern:
- A blocking `await` or `recv()` that never returned (no server-side close frame)
- An async task that stopped scheduling due to event loop starvation
- A resource lock contention during the DataAgent's concurrent file writes

---

## Timeline

| Time (PDT) | Event |
|---|---|
| 22:39 2026-03-29 | Watchdog last started — then silently died |
| ~11:31 | Last 15m crypto entries (1445-45 window) |
| 11:33 | Last WS heartbeat written (`ws_feed_heartbeat.json`) |
| ~11:43 | Watchdog **should have** triggered restart (10min stale) — but was dead |
| 12:00-12:01 | DataAgent audit ran, noted missing positions, auto-fixed |
| 13:16 | David flagged the freeze — investigation began |

---

## Required Fixes (for Dev)

### Fix 1: Watchdog must be supervised (critical)
The watchdog process itself has no supervisor. If it dies, the entire restart mechanism is gone.

**Options (in order of preference):**
1. **Windows Task Scheduler with `RestartOnFailure` enabled** — configure the watchdog Task Scheduler entry to restart on failure, up to 3 times with a 60s delay.
2. **Wrap watchdog in a bat/ps1 loop** — a simple outer script that re-launches watchdog.py if it exits.
3. **Add outer retry loop to watchdog.py** — wrap `run_watchdog()` in a while-True with restart logic at the `__main__` level.

### Fix 2: Watchdog startup logging needs a daily heartbeat (important)
The watchdog only logs on startup and on restart events. If it runs normally for hours, the log file shows nothing — making it impossible to distinguish "watchdog is running and WS is healthy" from "watchdog is dead."

**Spec:** Add a periodic "watchdog alive" log entry (e.g., every 30 minutes) inside the main loop, even when no restart is needed.

### Fix 3: WS feed hang detection (important)
The WS feed can enter a hung state without crashing. The current heartbeat mechanism is correct, but the WS feed's internal async loop needs a watchdog timeout — if no message is received within N seconds, force a reconnect.

**Spec:** Add an `asyncio.wait_for()` timeout wrapper around the `recv()` call in `ws_feed.py`. Suggested threshold: 60 seconds. On timeout, log "recv timeout — forcing reconnect" and close/reopen the connection.

### Fix 4: Log stderr from watchdog (nice-to-have)
The watchdog runs with stdout to a log file, but if it crashes with a Python exception, that traceback may go nowhere. 

**Spec:** Redirect stderr to a `watchdog-error.log` file (or append to `watchdog.log`) in the Task Scheduler config, so crash tracebacks are captured.

---

## Impact Assessment

- **15m crypto decisions:** Gap from 11:31 to at least 13:16 PDT (~105 minutes, ~7 decision windows missed)
- **Open positions at time of freeze:** 4 positions in 1445-45 window (KXETH, KXBTC, KXDOGE, KXXRP) — WS exit monitor was also down during this period. Positions expired naturally at 14:45 PDT.
- **Capital at risk:** Unknown — requires cross-checking 1445-45 window outcomes against position tracker

---

## Files Examined

- `environments/demo/logs/watchdog.log` — watchdog died overnight 2026-03-29
- `environments/demo/logs/activity_2026-03-30.log` — last WS activity at 11:33, freeze confirmed
- `environments/demo/logs/ws_feed_heartbeat.json` — last heartbeat `2026-03-30T11:33:24`
- `environments/demo/scripts/ws_feed_watchdog.py` — source reviewed, no self-supervision
- PID 56364 — confirmed not running
