# QA Report — Batch 1 Bug Fixes (2026-03-27)

**Reviewer:** QA Agent (Claude)
**Date:** 2026-03-27
**Scope:** Fix 1 (cross-cycle dedup) + Fix 2 (Kelly win_prob cap)

---

## Fix 1 — Cross-cycle dedup (`ruppert_cycle.py:88-110`)

### Checklist

| Check | Result |
|-------|--------|
| Code exists after `traded_tickers = set()` init (line 88) | PASS — lines 90-110 |
| Located before Step 1 position check | PASS — position loop begins at ~line 194 |
| buy/open actions → `add()` | PASS — line 103-104: `if _action in ('buy', 'open'): traded_tickers.add(_tk)` |
| exit actions → `remove()` | PASS — line 105-106: `elif _action == 'exit': traded_tickers.discard(_tk)` (uses `discard`, safe if not present) |
| File-not-found edge case | PASS — line 92: `if _trade_log_path.exists():` guards the entire block |
| JSON parse errors | PASS — wrapped in `try/except Exception` (line 93, 109-110), non-blocking |
| Empty lines handled | PASS — line 96-97: `if not _line: continue` |
| Missing ticker handled | PASS — line 101-102: `if not _tk: continue` |
| `json` and `LOGS` available | PASS — imported at line 9 (`json`) and line 16 (`LOGS`) |
| `date` available | PASS — imported at line 11 |
| Log path correct | PASS — `LOGS / f'trades_{date.today().isoformat()}.jsonl'` matches log_trade output convention |
| Reads normalized `action` field | PASS — compatible with commit 7f88883 (action normalization) |
| Syntax valid | PASS — no syntax errors detected |

**Verdict: QA PASS**

---

## Fix 2 — Kelly win_prob cap (`bot/strategy.py:161-167`)

### Checklist

| Check | Result |
|-------|--------|
| Old `>= 1.0` → return 0.0 guard removed | PASS — no code path returns 0 for win_prob >= 1.0 (grep confirmed) |
| win_prob capped at 0.999 | PASS — lines 166-167: `if win_prob >= 0.999: win_prob = 0.999` |
| Cap applied before Kelly math | PASS — cap at line 166, Kelly formula at line 170: `f = edge / (1.0 - win_prob)` |
| Division-by-zero prevented | PASS — `1.0 - 0.999 = 0.001`, safe denominator |
| Located in `calculate_position_size` | PASS — function at line 136 |
| Zero/negative guards preserved | PASS — line 161: `if win_prob <= 0 or edge <= 0 or capital <= 0: return 0.0` |
| No other code paths reject win_prob=1.0 | PASS — grep for `win_prob.*>= *1` returns no matches |
| Comment explains rationale | PASS — "avoid division-by-zero... when NOAA gives 100% probability" |
| Syntax valid | PASS — no syntax errors detected |

**Verdict: QA PASS**

---

## Summary

| Fix | Verdict |
|-----|---------|
| Fix 1 — Cross-cycle dedup | **QA PASS** |
| Fix 2 — Kelly win_prob cap | **QA PASS** |

Both fixes are correctly implemented, handle edge cases, and have valid syntax.
