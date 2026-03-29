# Phase 6 Plan + Post-Build Audit

## Phase 6 Decisions (logged 2026-03-28)
1. Workspace restructure: rename projects/ to nvironments/
   - uppert-tradingbot-demo → nvironments/demo
   - uppert-tradingbot-live → nvironments/live
2. Agents live at .openclaw/workspace/agents/ (NOT inside environments)
   - Agents are environment-agnostic, pointed at env via config flag
   - Data Scientist can see both demo + live
3. Passive income folder: wipe completely
4. Live environment: read-only until David explicitly flips it on
5. CEO role: trading only — no general assistant tasks
6. Have Opus design the full Phase 6 architecture before Dev touches anything

## Post-Phase-6 Full System Audit Plan
Batched across separate sessions to avoid context overflow:

- Session 1 | Strategist (Opus): Architecture integrity audit
  — Does final structure match design principles? Any drift?
- Session 2 | QA: Code correctness audit
  — Imports, paths, syntax, tests across full restructured repo
- Session 3 | Data Scientist: Data integrity audit
  — Truth file ownership, no rogue writers, log paths consistent
- Session 4 | Strategist (Opus): Performance & algo audit
  — Trading parameters correct after all the structural moves?

## Trader Agent Architecture Decision (logged 2026-03-28)
Strategist recommendation: Hybrid (Option C), simplified.

- Trader Agent owns ALL execution code in gents/trader/
- ws_feed.py → persistent process, crypto 15m, event-driven
- trader.py + other scripts → cron-invoked, weather/econ/geo/fed
- Shared xecute_trade() module inside agents/trader/ used by both paths
- Add ws_feed watchdog to Task Scheduler (checks every 5 min, restarts if dead)
- Optional: nssm to run ws_feed as a proper Windows service

No always-on unified Trader process — each path runs independently, both owned by Trader Agent.

## Secrets Rotation Schedule
- **Cadence:** Every 3 months
- **Next rotation due:** 2026-06-28
- **What to rotate:**
  - GitHub token (also expires ~June 2026 — must rotate)
  - Kalshi API key
  - Any other API keys in workspace/secrets/

**Reminder:** CEO should alert David ~1 week before due date.
