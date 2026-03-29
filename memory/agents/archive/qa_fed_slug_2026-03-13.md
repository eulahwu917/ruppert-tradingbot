# QA REPORT — Fed Module Polymarket Slug Fix
_SA-4 QA | Date: 2026-03-13_

## Status: FAIL

---

✅ **Checks passed:**
- `_FOMC_SLUGS_FILE` correctly points to `Path(__file__).parent / "config" / "fomc_slugs.json"` (not `logs/`)
- `fomc_slugs.json` has March 18 slug set (`fed-decision-in-march-885`), all other entries are `null`
- API endpoint is correct: `https://gamma-api.polymarket.com/events` with `params={"slug": slug}`
- `outcomePrices[0]` parsed correctly for the "no change" market (explicit check before general classifier; try/except guards parse errors)
- `slug_unknown` skip path calls `_save_scan_result(no_signal)` before returning sentinel → `fed_scan_latest.json` is written ✅
- `polymarket_unavailable` path intact: API exceptions in `get_polymarket_fomc_probabilities` return `None`, which triggers the guard in `get_fed_signal()` and saves `skip_reason: "polymarket_unavailable"` ✅
- All strategy thresholds unchanged: `FED_MIN_EDGE = 0.12`, `FED_MIN_CONFIDENCE = 0.55`, `FED_WINDOW_MIN_DAYS = 2`, `FED_WINDOW_MAX_DAYS = 7` ✅
- No hardcoded API keys anywhere in the file ✅
- File encoding: `open(_FOMC_SLUGS_FILE, encoding="utf-8")` ✅
- Error handling: all file/network operations wrapped in try/except with proper logging ✅

---

❌ **Issues (must fix before CEO approval):**

**CRITICAL — Date key mismatch between `FOMC_DECISION_DATES_2026` and `fomc_slugs.json`:**
The slug lookup key is `meeting_date.isoformat()` derived from `FOMC_DECISION_DATES_2026` in `fed_client.py`. The dates in `fomc_slugs.json` do NOT match for the majority of 2026 meetings:

| Meeting (fed_client.py) | Key in fomc_slugs.json | Match? |
|-------------------------|------------------------|--------|
| 2026-01-29              | _(not in file)_        | ❌ missing |
| 2026-03-18              | 2026-03-18             | ✅ |
| 2026-04-29              | 2026-05-07             | ❌ mismatch |
| 2026-06-10              | 2026-06-17             | ❌ mismatch |
| 2026-07-29              | 2026-07-29             | ✅ |
| 2026-09-16              | 2026-09-16             | ✅ |
| 2026-10-28              | 2026-11-04             | ❌ mismatch |
| 2026-12-09              | 2026-12-16             | ❌ mismatch |

Result: 4 of 8 meetings will always return `slug_unknown` even after real slugs are filled in, because the lookup key will never find the right JSON key. One of the two calendars is wrong — either `FOMC_DECISION_DATES_2026` in `fed_client.py` or the keys in `fomc_slugs.json`. Developer must reconcile against the official Fed calendar before this can ship.

---

⚠️ **Warnings (discretionary):**

1. **Stale log messages** — two logger.info calls still reference the old `logs/fomc_slugs.json` path after the CEO-directed relocation to `config/`:
   - `get_polymarket_fomc_probabilities()`: `"update logs/fomc_slugs.json when slug becomes available"`
   - `get_fed_signal()`: `"update logs/fomc_slugs.json when slug becomes available"`
   These won't break anything but will mislead anyone reading the logs. Easy one-line fixes.

2. **2026-01-29 (January meeting) absent from `fomc_slugs.json`** — presumably past, but worth confirming it's intentionally omitted rather than an oversight in the file template.

---

**Verdict:** The `_FOMC_SLUGS_FILE` path fix is correct and all logic gates (slug_unknown, polymarket_unavailable, thresholds, no hardcoded keys) check out. However, the **date-key mismatch between `FOMC_DECISION_DATES_2026` and `fomc_slugs.json`** is a correctness bug that will cause silent `slug_unknown` failures for most future FOMC meetings. Send back to Developer to align both calendars against the official Fed schedule, and to fix the two stale log-message path references.

---

## Re-Verification — SA-4 QA | 2026-03-13 (post-fix)

## Status: PASS ✅ (with one minor documentation note)

**Fix 1 — `FOMC_DECISION_DATES_2026` in `fed_client.py`:** All 7 future FOMC dates now match the official Fed schedule exactly: 2026-03-18 ✅, 2026-05-07 ✅, 2026-06-17 ✅, 2026-07-29 ✅, 2026-09-16 ✅, 2026-10-28 ✅, 2026-12-16 ✅. The January 2026 date (2026-01-29) remains in the list as a past meeting — correct and intentional. No wrong dates remain.

**Fix 2 — `config/fomc_slugs.json` keys:** All 7 keys (2026-03-18, 2026-05-07, 2026-06-17, 2026-07-29, 2026-09-16, 2026-10-28, 2026-12-16) exactly match the dates in `FOMC_DECISION_DATES_2026`. The slug lookup will resolve correctly for all future meetings once slugs are populated. The prior 4-of-8 mismatch is fully resolved.

**`logs/fomc_slugs.json` references:** The two stale `logger.info` calls ("update logs/fomc_slugs.json") flagged in the prior report have been removed — no `logger.info` or runtime references to `logs/fomc_slugs.json` remain. `_FOMC_SLUGS_FILE` correctly points to `Path(__file__).parent / "config" / "fomc_slugs.json"`. One cosmetic occurrence remains: a **docstring comment** at line 167 still reads "logs/fomc_slugs.json keyed by FOMC decision date" — this is non-functional (docs only) and does not affect runtime behavior, but should be corrected opportunistically.

**Scope check:** No other files were modified beyond the two targeted fixes. All strategy thresholds, API endpoints, error handling, and guard logic remain unchanged from the prior passing checks.

**Verdict:** Both critical fixes from the FAIL are confirmed correct. The date-key mismatch is fully resolved and the `config/fomc_slugs.json` path is the sole runtime reference. Ready for CEO approval, with an optional cleanup note: update the stale docstring at `fed_client.py:167` to reference `config/fomc_slugs.json`.
