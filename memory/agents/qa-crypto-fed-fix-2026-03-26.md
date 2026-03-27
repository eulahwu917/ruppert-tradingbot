# QA Report: Crypto + Fed Strategy Wiring
**Date:** 2026-03-26  
**Agent:** SA-4 QA  
**File verified:** `ruppert_cycle.py`  
**Scope:** Checks 1–5 (no crash ref, crypto routing, fed routing, syntax, imports)

---

## Check 1 — No crash reference (`config.CRYPTO_MAX_POSITION_SIZE`)

**PASS**

`Select-String` on `ruppert_cycle.py` for `CRYPTO_MAX_POSITION_SIZE` returned **zero hits**.  
The removed reference does not appear anywhere in the file.

---

## Check 2 — Crypto routes through `should_enter()`

**PASS**

Evidence (all line numbers verified via `Select-String`):

| Sub-check | Line(s) | Evidence |
|-----------|---------|----------|
| `should_enter()` called with signal dict | 479–491 | `signal = { 'edge': ..., 'win_prob': ..., 'confidence': ..., 'hours_to_settlement': ..., 'module': 'crypto', 'vol_ratio': 1.0, 'side': ..., 'yes_ask': ..., 'yes_bid': ..., 'open_position_value': ... }` → `decision = should_enter(signal, ...)` (line 491) |
| `check_open_exposure()` called before trades | 470 | `if not check_open_exposure(_total_capital, _open_exposure): break` |
| Per-module daily cap uses `CRYPTO_DAILY_CAP_PCT` | 460 | `_crypto_daily_cap = _total_capital * getattr(config, 'CRYPTO_DAILY_CAP_PCT', 0.07)` |
| `decision['size']` used for sizing | 495, 499 | Line 495: `if _crypto_deployed_this_cycle + decision['size'] > _crypto_daily_cap:` — Line 499: `size = decision['size']` (no hardcoded $25) |
| `opp` dict includes `confidence` field | 508 | `'edge': t['edge'], 'confidence': t.get('confidence', t['edge']),` in `opp = {` block at line 504 |

---

## Check 3 — Fed routes through `should_enter()`

**PASS**

Evidence:

| Sub-check | Line(s) | Evidence |
|-----------|---------|----------|
| `should_enter()` called with `module='fed'` | 583–597 | `_fed_signal_dict = { ..., 'module': 'fed', ... }` → `_fed_decision = should_enter(_fed_signal_dict, ...)` (line 597) |
| Kelly sizing via `decision['size']` | 600, 603 | Line 600: `elif _fed_decision['size'] > _fed_daily_cap:` — Line 603: `size = min(_fed_decision['size'], _fed_cap_ok)` — No hardcoded `min(25.0, ...)` anywhere |
| Fed daily cap uses `ECON_DAILY_CAP_PCT` | 569 | `_fed_daily_cap = _fed_capital * getattr(config, 'ECON_DAILY_CAP_PCT', 0.04)` |

---

## Check 4 — Syntax

**PASS**

Command run:
```
python -c "import ast; ast.parse(open('ruppert_cycle.py', encoding='utf-8-sig').read()); print('SYNTAX OK')"
```

Output: `SYNTAX OK`

Note: The file has a UTF-8 BOM (`\ufeff`), so `encoding='utf-8-sig'` is required (not plain `utf-8`). The original check command in the task spec uses `encoding='utf-8'` which would raise a `SyntaxError: invalid non-printable character U+FEFF`. Using `utf-8-sig` (which strips the BOM) yields a clean parse. The file itself is syntactically valid Python.

**⚠️ Minor note for main agent:** The task spec's check command uses `encoding='utf-8'` — update it to `encoding='utf-8-sig'` to avoid false-positive syntax errors caused by the BOM.

---

## Check 5 — Import check

**PASS**

Line 24:
```python
from bot.strategy import check_daily_cap, check_open_exposure, should_enter
```

Both `should_enter` and `check_open_exposure` are imported from `bot.strategy`. ✅

---

## Final Verdict: ✅ QA PASS

All 5 checks passed. The crypto and fed execution paths are correctly wired through `should_enter()` and `check_open_exposure()`, use config-driven caps and Kelly sizing, and the `config.CRYPTO_MAX_POSITION_SIZE` crash reference is fully removed. Syntax is clean.
