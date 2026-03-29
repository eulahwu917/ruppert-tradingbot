# MEMORY.md — Strategist Long-Term Memory
_Owned by: Strategist agent. Updated after significant decisions, algo changes, or pattern discoveries._

---

## Algorithm Parameters (current)
- Weather direction filter: **RETIRED 2026-03-28** — both YES and NO now trade based on edge sign
- Fractional Kelly sizing — max tier 16% (80%+ confidence), graded down to 5% (25-40% confidence). Do not change without Optimizer proposal + David approval. See kelly_fraction_for_confidence() in strategy.py for full tier table.
- 95c rule + 70% gain exit — PRIMARY alpha source, do not tune without strong evidence
- Multi-model ensemble: ECMWF 40% + GEFS 40% + ICON 20%
- MIN_CONFIDENCE['weather'] = 0.25

## Optimizer State
- Bonferroni threshold: 0.05/6 = 0.0083
- Min dataset before proposals: 30 trades per module
- Frequency: monthly, or 30+ trades, or 3+ losses in 7 days
- Last run: never (dataset too small as of 2026-03-28)

## Key Decisions
- 2026-03-28: Weather NO-only filter retired. Both directions now allowed based on edge sign (David's decision).
- 2026-03-28: Same-day re-entry blocked in ruppert_cycle.py (Strategist decision)
- OPTIMIZER_* constants in config.py — all tunable thresholds centralized there

## Lessons Learned
- Confidence field was not logged before 2026-03-26 — old win-rate data by confidence tier is invalid
- Mar 13 loss (-$341): direction filter not enforced. Root cause: guard was skipped. Now fixed.

## 🔁 Deferred: Full Optimizer Engine (revisit when data is in)

**Context (2026-03-28):** optimizer.py is ~40% of what's needed as a full algo optimization engine.
Current gaps identified:
- No specific parameter values in proposals (says "raise min_edge" but not "to what")
- No parameter sweep / simulation against historical data
- No proposal → dev spec pipeline
- No proposal history tracking (optimizer_history.jsonl)
- Notification routing now handled via heartbeat ✅

**David's instruction:** Once domains start hitting 30+ scored trades, Strategist should:
1. Pull the actual optimizer_proposals_*.md output
2. Assess quality — are proposals specific enough? actionable?
3. Compare against the gap list above — what still needs to be built?
4. Write a follow-up spec only for what's actually missing based on real data

**Do NOT build the full engine spec preemptively — wait for real data first.**

## Watchlist / Open Questions
- Crypto sigmoid scale (1.0) is uncalibrated — autoresearcher will tune from live data (need 30 trades first)
- Brier score calibration not yet meaningful — need more scored outcomes
