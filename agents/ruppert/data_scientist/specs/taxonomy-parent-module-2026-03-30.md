# Spec: Taxonomy parent_module — Single Source of Truth
**Date:** 2026-03-30  
**Author:** Data Scientist  
**Status:** Ready for Dev  
**Priority:** P1 — maintenance trap, no functional defect today but will break on every taxonomy change

---

## Problem Statement

### Problem 1: Frontend has its own hardcoded taxonomy (wrong pattern)

`index.html` contains two JS functions that duplicate backend classification logic:

```js
// index.html ~line 1094 — CEO quick-fix, pipeline violation
function classifyModule(ticker, source) { ... }  // knows old names: weather, crypto, fed
function moduleTag(module, ticker, source) {
  const mod = module || classifyModule(ticker, source);  // falls back to its own classify
  if (mod === 'weather' || mod === 'weather_band' || mod === 'weather_threshold') ...
  if (mod === 'crypto' || mod === 'crypto_15m_dir' || mod === 'crypto_1h_dir' || mod === 'crypto_1h_band') ...
  if (mod === 'fed' || mod === 'econ_fed_rate' || ...) ...
```

This is a maintenance trap. Every taxonomy change requires updating **both** `logger.py` AND `index.html`. The CEO had to patch the frontend directly (pipeline violation) just to get the new subcategory names rendering correctly.

### Problem 2: API doesn't expose parent_module

`api.py` already calls `classify_module()` (imported from `logger.py`) and sets the detailed `module` field on every position/trade dict. But it does not set a `parent_module` field — the display category needed for badge rendering.

The frontend currently handles this by checking all subcategory names itself — which is exactly the pattern we want to eliminate.

---

## Correct Pattern

```
logger.py        → classify_module()     → detailed subcategory  (e.g. crypto_15m_dir)
logger.py        → get_parent_module()   → display category      (e.g. crypto)
api.py           → sets module + parent_module on every dict
index.html       → moduleTag() uses ONLY parent_module           (never classifies itself)
```

Taxonomy changes flow: `logger.py` only → `api.py` picks it up automatically → `index.html` never touched.

---

## File-by-File Changes

### 1. `agents/ruppert/data_scientist/logger.py`

**Add after `classify_module()`:**

```python
def get_parent_module(module_name: str) -> str:
    """Map detailed subcategory → display parent category.

    Single source of truth for display grouping. Used by api.py to populate
    the parent_module field on every position/trade dict so the frontend
    never needs its own classification logic.

    Mapping:
        weather_band, weather_threshold          → 'weather'
        crypto_15m_dir, crypto_1h_dir,
          crypto_1h_band                         → 'crypto'
        econ_cpi, econ_unemployment,
          econ_fed_rate, econ_recession          → 'econ'
        geo                                      → 'geo'
        manual, other                            → 'other'
    """
    m = (module_name or '').lower()
    if m.startswith('weather'):
        return 'weather'
    if m.startswith('crypto'):
        return 'crypto'
    if m.startswith('econ'):
        return 'econ'
    if m == 'geo':
        return 'geo'
    return 'other'
```

**Design notes:**
- Uses `startswith` prefix matching — naturally handles any future `weather_*`, `crypto_*`, `econ_*` subcategories without code changes.
- `geo` is an exact match (there's only one geo category; no subclasses planned).
- `manual` and `other` both fall through to `'other'` — correct display behavior.
- No imports needed; pure function.

**Also update the import line in `api.py`** (see below): add `get_parent_module` to the import.

---

### 2. `environments/demo/dashboard/api.py`

**Change the import line** (currently line ~11):

```python
# Before
from agents.ruppert.data_scientist.logger import classify_module

# After
from agents.ruppert.data_scientist.logger import classify_module, get_parent_module
```

**In `get_active_positions()` — DEMO mode path (~line 340):**

```python
# Before
"module":      classify_module(source, ticker),

# After
"module":      classify_module(source, ticker),
"parent_module": get_parent_module(classify_module(source, ticker)),
```

**In `get_active_positions()` — LIVE mode path (~line 290):**

```python
# Before
"module":      classify_module('live', ticker),

# After
"module":      classify_module('live', ticker),
"parent_module": get_parent_module(classify_module('live', ticker)),
```

**In `get_trades()` — closed trades path (~line 415):**

```python
# Before
t['module'] = classify_module(t.get('source', 'bot'), ticker)

# After
_mod = classify_module(t.get('source', 'bot'), ticker)
t['module'] = _mod
t['parent_module'] = get_parent_module(_mod)
```

**In `_build_state()` — positions list builder (~line 580):**

```python
# Before
'module':      mod,

# After
'module':      mod,
'parent_module': get_parent_module(mod),
```

**Note:** `mod` is already the result of `classify_module()` in `_build_state()` — no double-call needed.

**Note:** The `/api/pnl` endpoint does NOT return per-trade position dicts to the frontend — it only returns aggregate P&L numbers and `modules_out` stats dict. No change needed there.

---

### 3. `environments/demo/dashboard/templates/index.html`

**Remove `classifyModule()` entirely** (lines ~1094–1101):

```js
// DELETE this entire function:
function classifyModule(ticker, source) {
  const t = (ticker || '').toUpperCase();
  const src = (source || '');
  if ((src === 'weather' || src === 'bot') && t.startsWith('KXHIGH')) return 'weather';
  if (src === 'crypto' || ['KXBTC','KXETH','KXXRP','KXDOGE'].some(p => t.startsWith(p))) return 'crypto';
  if (src === 'fed' || t.startsWith('KXFED') || t.startsWith('KXCPI')) return 'fed';
  return 'other';
}
```

**Replace `moduleTag()` function** (lines ~1102–1113):

```js
// Before (CEO quick-fix — knows all subcategory names, maintenance trap)
function moduleTag(module, ticker, source) {
  const mod = module || classifyModule(ticker, source);
  if (mod === 'weather' || mod === 'weather_band' || mod === 'weather_threshold')
    return '<span style="...">Weather</span>';
  if (mod === 'crypto' || mod === 'crypto_15m_dir' || mod === 'crypto_1h_dir' || mod === 'crypto_1h_band')
    return '<span style="...">Crypto</span>';
  if (mod === 'fed' || mod === 'econ_fed_rate' || mod === 'econ_cpi' || mod === 'econ_unemployment' || mod === 'econ_recession')
    return '<span style="...">Econ</span>';
  if (mod === 'geo')
    return '<span style="...">Geo</span>';
  return '<span style="...">Other</span>';
}

// After (clean — only knows 4 parent categories, never touches subcategories)
function moduleTag(parent_module) {
  switch (parent_module) {
    case 'weather':
      return '<span style="background:#0d1f0d;color:#4ade80;border:1px solid #1a3d1a;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.3px;flex-shrink:0;">Weather</span>';
    case 'crypto':
      return '<span style="background:#1a0d2e;color:#a78bfa;border:1px solid #2d1a4a;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.3px;flex-shrink:0;">Crypto</span>';
    case 'econ':
      return '<span style="background:#0d1a2e;color:#60a5fa;border:1px solid #1a2d4a;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.3px;flex-shrink:0;">Econ</span>';
    case 'geo':
      return '<span style="background:#1a1a0d;color:#facc15;border:1px solid #3d3a1a;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.3px;flex-shrink:0;">Geo</span>';
    default:
      return '<span style="color:#666;padding:2px 7px;border-radius:3px;font-size:9px;flex-shrink:0;">Other</span>';
  }
}
```

**Update all three call sites** in the template:

| Location | Before | After |
|---|---|---|
| Open positions row (~line 808) | `${moduleTag(p.module, p.ticker, p.source)}` | `${moduleTag(p.parent_module)}` |
| Closed trades row (~line 947) | `${moduleTag(t.module, t.ticker, t.source)}` | `${moduleTag(t.parent_module)}` |
| State positions row (~line 1224) | `${moduleTag(p.module, p.ticker, p.source)}` | `${moduleTag(p.parent_module)}` |

---

## Verification Checklist

Dev should verify after implementing:

- [ ] `get_parent_module('weather_band')` → `'weather'`
- [ ] `get_parent_module('weather_threshold')` → `'weather'`
- [ ] `get_parent_module('crypto_15m_dir')` → `'crypto'`
- [ ] `get_parent_module('crypto_1h_dir')` → `'crypto'`
- [ ] `get_parent_module('crypto_1h_band')` → `'crypto'`
- [ ] `get_parent_module('econ_cpi')` → `'econ'`
- [ ] `get_parent_module('econ_fed_rate')` → `'econ'`
- [ ] `get_parent_module('econ_unemployment')` → `'econ'`
- [ ] `get_parent_module('econ_recession')` → `'econ'`
- [ ] `get_parent_module('geo')` → `'geo'`
- [ ] `get_parent_module('other')` → `'other'`
- [ ] `get_parent_module('manual')` → `'other'`
- [ ] `/api/positions/active` response includes `parent_module` on every item
- [ ] `/api/trades` response includes `parent_module` on every item
- [ ] `/api/state` response positions include `parent_module` on every item
- [ ] Dashboard renders correct color badge for all 4 parent categories
- [ ] `classifyModule()` JS function is gone from index.html
- [ ] `moduleTag()` signature is `moduleTag(parent_module)` — single arg

---

## Why Not Use the Existing `module` Field Directly?

The `module` field returns detailed subcategories (`crypto_15m_dir`, `weather_band`, etc.) — these are valuable for analytics, filtering, and per-subtype stats. Replacing the field with parent categories would lose that granularity. The correct answer is **both**: `module` for analytics, `parent_module` for display. The display layer (frontend) should only know about 4 badges — not the internal taxonomy.

---

## Future-Proofing

When a new subcategory is added (e.g. `econ_pce`), the workflow is:
1. Add pattern to `classify_module()` in `logger.py` — returns `'econ_pce'`
2. `get_parent_module('econ_pce')` returns `'econ'` automatically (prefix match)
3. Frontend badge renders `Econ` — **zero frontend changes needed**

This is the correct maintenance pattern.
