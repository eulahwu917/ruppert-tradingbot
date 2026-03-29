# QA Report — Source Misclassification Fix
_SA-4 QA — 2026-03-12_

**Status: FAIL**

```
QA REPORT — source-misclassification-fix
Status: FAIL

✅ Checks passed:
- loadTrades() line 836: MANUAL source list is exactly ['economics','geo','manual'] ✅
  'crypto' and 'gaming' correctly removed; 'economics' correctly added.
- loadPositions() line 704: badge display correctly uses ['economics','geo','manual'] ✅
  'gaming' removed, 'economics' added.
- BOT fallback comment in both functions confirms intent: "// BOT: bot, weather, crypto" ✅
- No out-of-scope files modified (only index.html touched) ✅

❌ Issues (must fix):
- index.html line 792 (inside loadPositions(), open P&L accumulation loop):
    if (p.source && ['geo','gaming','manual'].includes(p.source)) manPnl += pnl;
  This list was NOT updated to match the fix. It still contains 'gaming' and is missing 'economics'.
  Result: economics open positions are silently counted as BOT P&L (incorrect split in
  the Bot/Manual P&L dashboard cards), and any residual 'gaming' source would still
  accumulate to manPnl. The visual badge was fixed but the underlying P&L split logic
  in the same function was missed. Fix: change to ['economics','geo','manual'] on line 792.

⚠️ Warnings (discretionary):
- index.html line 905 (High Conviction Bets catMap, out of scope for this PR):
    Crypto: '<span class="b-manual">Crypto</span>'
  Crypto category in the scouts panel renders a MANUAL-styled badge (amber). If this is
  intentional styling it's fine, but it conflicts visually with the 'crypto' source routing
  to BOT in positions/trades. Worth a follow-up review, but not blocking.
```

**Verdict:** The Developer correctly fixed the source classification in two of three locations — `loadTrades()` and the `loadPositions()` display badge both now use `['economics','geo','manual']` as intended. However, a third occurrence of the same pattern on line 792 (the open P&L accumulator inside `loadPositions()`) was not updated and still uses the stale `['geo','gaming','manual']` list. This will cause economics open positions to be misattributed to the BOT P&L column in the dashboard split cards, which is a functional correctness failure. Must fix line 792 before CEO approval.

---

## Re-Verification — 2026-03-12 (SA-4 QA)

**Status: PASS**

Line 792 inside `loadPositions()` now correctly reads `['economics','geo','manual']` (confirming the stale `['geo','gaming','manual']` has been replaced), and no other changes were observed in the surrounding context.
