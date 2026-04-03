# Module Taxonomy Migration — BEFORE/AFTER Spec
**Date:** 2026-03-30  
**Author:** Ruppert Data Scientist  
**Status:** APPROVED — Ready for Dev implementation  
**References:** `taxonomy-redesign-2026-03-30.md` (rationale & analysis)

---

## 0. Overview

This spec defines every code and data change required to migrate the Ruppert trade log
taxonomy from flat/ambiguous module names to the approved structured taxonomy.

**Scope:** Code changes (5 files) + trade log backfill script (1 file) + dashboard confirmation.

**Total trades affected by backfill:**
- 98 `weather` → split to `weather_band` (66) / `weather_threshold` (32)
- 21 `crypto` → `crypto_1h_band` (all are band-type, confirmed KXETH-B*/KXDOGE-B*)
- 108 `crypto_15m` → `crypto_15m_dir`
- 0 `crypto_1d` in logs (no crypto_1d trades yet, code rename only)
- 0 `econ`, `fed`, `geo` in logs (no trades yet, code rename only)

---

## 1. Approved Taxonomy (Final)

| New Module Value      | Old Module Value | Tickers / Series                                    |
|-----------------------|------------------|-----------------------------------------------------|
| `crypto_15m_dir`      | `crypto_15m`     | KXBTC15M, KXETH15M, KXXRP15M, KXDOGE15M, KXSOL15M |
| `crypto_1h_dir`       | `crypto_1d`      | KXBTCD, KXETHD, KXSOLD                              |
| `crypto_1h_band`      | `crypto`         | KXBTC, KXETH, KXDOGE, KXXRP (band, no D/15M suffix)|
| `weather_band`        | `weather`        | KXHIGH*-B* (ticker contains `-B`)                   |
| `weather_threshold`   | `weather` (new)  | KXHIGH*-T* (ticker contains `-T`)                   |
| `econ_cpi`            | `econ`           | KXCPI*                                              |
| `econ_unemployment`   | `econ`           | KXJOBLESSCLAIMS, KXECONSTATU3, KXUE                 |
| `econ_fed_rate`       | `fed`            | KXFED, KXFOMC                                       |
| `econ_recession`      | `econ`           | KXWRECSS                                            |
| `geo`                 | `geo`            | unchanged                                           |

> **Note on `crypto_1h_dir` naming:** The redesign spec used `crypto_1h`; approved name is
> `crypto_1h_dir` to parallel `crypto_15m_dir` (both are directional binary markets).  
> **Note on `econ_fed_rate`:** The redesign spec used `econ_fed`; approved name is `econ_fed_rate`
> to be more self-documenting.

---

## 2. File-by-File Changes

---

### 2.1 `agents/ruppert/data_scientist/logger.py`

**Single source of truth** — both `classify_module()` and `build_trade_entry()` must change.
`dashboard/api.py` imports `classify_module` from here, so no dashboard code change is needed.

---

#### A. `classify_module(src, ticker)` — BEFORE

```python
def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix.

    Single source of truth - imported by dashboard/api.py to stay in sync.
    """
    t = (ticker or '').upper()
    if src in ('weather',) or (src in ('weather', 'bot') and t.startswith('KXHIGH')):
        return 'weather'
    if src == 'crypto_1d':
        return 'crypto'
    if src == 'crypto' or (src in ('crypto', 'bot') and any(
        t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')
    )):
        return 'crypto'
    if src == 'fed' or t.startswith('KXFED'):
        return 'fed'
    if src == 'econ' or t.startswith('KXCPI'):
        return 'econ'
    if src == 'geo' or any(t.startswith(p) for p in (
        'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
        'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
    )):
        return 'geo'
    if src == 'manual':
        return 'manual'
    if src == 'crypto_15m' or '15M' in (ticker or '').upper():
        return 'crypto'
    return 'other'
```

#### A. `classify_module(src, ticker)` — AFTER

```python
def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix.

    Single source of truth - imported by dashboard/api.py to stay in sync.

    Module taxonomy (2026-03-30):
      weather_band        KXHIGH*-B*  (ticker contains '-B')
      weather_threshold   KXHIGH*-T*  (ticker contains '-T')
      crypto_15m_dir      KXBTC15M, KXETH15M, KXXRP15M, KXDOGE15M, KXSOL15M
      crypto_1h_dir       KXBTCD, KXETHD, KXSOLD  (source=crypto_1d)
      crypto_1h_band      KXBTC, KXETH, KXDOGE, KXXRP (band, no D/15M suffix)
      econ_cpi            KXCPI*
      econ_unemployment   KXJOBLESSCLAIMS, KXECONSTATU3, KXUE
      econ_fed_rate       KXFED, KXFOMC  (was: fed)
      econ_recession      KXWRECSS
      geo                 geopolitical series (unchanged)
    """
    t = (ticker or '').upper()

    # ── Weather ───────────────────────────────────────────────────────────
    if src in ('weather', 'bot') and t.startswith('KXHIGH'):
        if '-T' in t:
            return 'weather_threshold'
        return 'weather_band'  # default: B-type band

    # ── Crypto 15-min direction ───────────────────────────────────────────
    if src == 'crypto_15m' or any(
        t.startswith(p) for p in ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M')
    ):
        return 'crypto_15m_dir'

    # ── Crypto 1h direction (above/below binary) ──────────────────────────
    if src == 'crypto_1d' or any(
        t.startswith(p) for p in ('KXBTCD', 'KXETHD', 'KXSOLD')
    ):
        return 'crypto_1h_dir'

    # ── Crypto 1h band (range prediction) ────────────────────────────────
    if src == 'crypto' or any(
        t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE', 'KXSOL')
    ):
        return 'crypto_1h_band'

    # ── Econ subcategories ────────────────────────────────────────────────
    if t.startswith('KXCPI'):
        return 'econ_cpi'
    if any(t.startswith(p) for p in ('KXJOBLESSCLAIMS', 'KXECONSTATU3', 'KXUE')):
        return 'econ_unemployment'
    if src == 'fed' or any(t.startswith(p) for p in ('KXFED', 'KXFOMC')):
        return 'econ_fed_rate'
    if t.startswith('KXWRECSS'):
        return 'econ_recession'
    if src == 'econ':
        return 'econ_cpi'  # fallback for unknown econ tickers

    # ── Geo ───────────────────────────────────────────────────────────────
    if src == 'geo' or any(t.startswith(p) for p in (
        'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
        'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
    )):
        return 'geo'

    if src == 'manual':
        return 'manual'

    return 'other'
```

> **Decision:** Weather B/T classification uses `-T` in ticker as the discriminator.
> All existing weather trades are B-type (confirmed: 66 B-type, 32 T-type in logs).
> The T-regex checks for `-T` in the uppercase ticker string — safe given no B-type
> tickers ever contain `-T` in this series format.
>
> **Decision:** Crypto ordering matters. 15M prefixes (`KXBTC15M`) must be checked
> **before** the base prefixes (`KXBTC`) to avoid misclassification.
> Same for D-suffix series: `KXBTCD` before `KXBTC`.
>
> **Decision:** `econ` source fallback → `econ_cpi` (most common/highest-volume econ
> series). Explicit ticker prefix checks handle all others before this fallback.
> `fed` source → `econ_fed_rate` (merges the former separate `fed` module).

---

#### B. `build_trade_entry()` — BEFORE (module inference block, ~lines 91–115)

```python
    module = opportunity.get('module', '')
    if not module:
        ticker_upper = (opportunity.get('ticker') or '').upper()
        if src in ('weather',) or (src == 'bot' and ticker_upper.startswith('KXHIGH')):
            module = 'weather'
        elif src == 'crypto' or (src == 'bot' and any(
            ticker_upper.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')
        )):
            module = 'crypto'
        elif src == 'fed' or ticker_upper.startswith('KXFED'):
            module = 'fed'
        elif src == 'econ' or ticker_upper.startswith('KXCPI'):
            module = 'econ'
        elif src == 'geo':
            module = 'geo'
        elif src == 'manual':
            module = 'manual'
        else:
            if src == 'bot':
                module = 'weather' if ticker_upper.startswith('KXHIGH') else 'other'
            else:
                module = src
```

#### B. `build_trade_entry()` — AFTER (module inference block)

```python
    module = opportunity.get('module', '')
    if not module:
        # Delegate to classify_module — single source of truth
        module = classify_module(source, opportunity.get('ticker', ''))
```

> **Decision:** Collapse the duplicated inline logic in `build_trade_entry()` to a
> single `classify_module()` call. This eliminates the dual-maintenance risk where
> `build_trade_entry()` and `classify_module()` diverge again.
> `classify_module` is already defined in the same file — no import needed.

---

### 2.2 `agents/ruppert/trader/crypto_15m.py`

Two hardcoded `module='crypto_15m'` assignments (lines 1095, 1266).

#### BEFORE (both occurrences)
```python
module='crypto_15m',
```

#### AFTER (both occurrences)
```python
module='crypto_15m_dir',
```

Additionally, all `get_daily_exposure(module='crypto_15m')` calls and
`get_daily_wager(module='crypto_15m')` calls must be updated to match.

**Search pattern:** `module='crypto_15m'` or `module="crypto_15m"`  
**Replace with:** `module='crypto_15m_dir'` or `module="crypto_15m_dir"`

> **Note:** The `source` field can remain `'crypto_15m'` for traceability — it represents
> the scanner origin, not the taxonomy bucket. Only the `module` field changes.

---

### 2.3 `agents/ruppert/trader/crypto_1d.py`

Three `module='crypto_1d'` or `module='crypto_1d'` usages confirmed (lines 772, 987, 988).
Also three `get_daily_exposure(module='crypto_1d')` calls (lines 850, 854, 865).

#### Code assignments — BEFORE
```python
'module': 'crypto_1d',   # line 772
'module': 'crypto_1d',   # line 987 (decision log)
'module': 'crypto_1d',   # line 988 (opportunity dict)
```

#### Code assignments — AFTER
```python
'module': 'crypto_1h_dir',   # line 772
'module': 'crypto_1h_dir',   # line 987
'module': 'crypto_1h_dir',   # line 988
```

#### Exposure guard calls — BEFORE
```python
get_daily_exposure(module='crypto_1d', asset=asset)   # line 850
get_daily_exposure(module='crypto_1d')                # line 854
get_daily_exposure(module='crypto_1d')                # line 865
```

#### Exposure guard calls — AFTER
```python
get_daily_exposure(module='crypto_1h_dir', asset=asset)
get_daily_exposure(module='crypto_1d')   # ← KEEP for now (module prefix matching)
get_daily_exposure(module='crypto_1h_dir')
```

> **Decision on line 854:** The exposure check on line 854 appears to be a full-module
> daily cap. After backfill and code deploy, all new trades will write `crypto_1h_dir`.
> **All three** calls should be updated to `crypto_1h_dir` in the same PR.
>
> **Decision on module comparison (line 673):** The guard `if pos.get('module') != 'crypto_1d'`
> must be updated to `!= 'crypto_1h_dir'`. After backfill this is safe; during transition
> the old check would skip positions logged with the new name.
>
> Line 705 uses `rec.get('module', rec.get('source', ''))` — this reads from logs,
> so it will work correctly once the backfill script runs.

---

### 2.4 `agents/ruppert/trader/main.py`

Seven `module=` assignments confirmed across weather, crypto, fed, geo scan functions.

#### Weather scanner (~lines 257, 290, 294) — BEFORE
```python
_weather_deployed_this_cycle = _get_daily_exp(module='weather')   # line 257
signal = _opp_to_signal(opp, module='weather')                    # line 290
module='weather',                                                  # line 294
```

#### Weather scanner — AFTER

Weather module assignment in the opportunity dict (line 294) should **not** hardcode
`weather_band` here — the correct subcategory depends on the ticker, and `classify_module()`
handles it. The `module=` field should be omitted here or computed from the ticker:

```python
# Option A (preferred): omit module= here, let logger.classify_module() derive it
# Option B: compute from ticker
module=classify_module('weather', opp['ticker']),   # line 294
```

The exposure guard call should use the parent prefix:
```python
_weather_deployed_this_cycle = _get_daily_exp(module='weather_band')  # line 257
# OR: use parent-prefix matching (weather_ prefix matches both weather_band + weather_threshold)
# get_daily_exposure already supports startswith matching for 'weather' → matches both subcategories
# Recommendation: keep as module='weather' in exposure guard — prefix logic in get_daily_exposure
# will match weather_band and weather_threshold automatically.
```

> **Decision:** `get_daily_exposure(module='weather')` uses `startswith('weather_')` matching
> (confirmed in logger.py get_daily_exposure: `entry_module.startswith(module + '_')`).
> This means `module='weather'` as a filter argument correctly aggregates BOTH
> `weather_band` AND `weather_threshold` exposure. **Keep exposure guard calls as `'weather'`.**
>
> Only the **opportunity dict assignment** `module='weather'` (line 294) needs to change —
> it should either be removed (let `classify_module()` infer from ticker) or computed
> dynamically. **Preferred: remove explicit module= from the opp dict**, rely on `build_trade_entry()`.

#### Crypto band scanner (~lines 610, 649) — BEFORE
```python
_crypto_deployed_this_cycle = _get_daily_exp(module='crypto')   # line 610
module='crypto',                                                  # line 649
```

#### Crypto band scanner — AFTER
```python
_crypto_deployed_this_cycle = _get_daily_exp(module='crypto_1h_band')  # line 610
module='crypto_1h_band',                                                 # line 649
```

> **Decision:** Unlike weather, there is no `crypto_1h` parent that aggregates both band
> and directional. The band scanner only trades `crypto_1h_band` markets. The `crypto_1h_dir`
> scanner has its own separate deployment caps in `crypto_1d.py`. Use specific module name.

#### Fed scanner (~lines 847, 906) — BEFORE
```python
_fed_deployed_this_cycle = _get_daily_exp(module='fed')   # line 847
module='fed',                                               # line 906
```

#### Fed scanner — AFTER
```python
_fed_deployed_this_cycle = _get_daily_exp(module='econ_fed_rate')   # line 847
module='econ_fed_rate',                                               # line 906
```

#### Geo scanner (~lines 1040, 1101) — BEFORE
```python
_geo_deployed_this_cycle = _get_daily_exp(module='geo')   # line 1040
module='geo',                                               # line 1101
```

#### Geo scanner — AFTER
```python
_geo_deployed_this_cycle = _get_daily_exp(module='geo')   # UNCHANGED
module='geo',                                               # UNCHANGED
```

> **Decision:** `geo` module name is unchanged per approved taxonomy. No edit needed.

---

### 2.5 `agents/ruppert/strategist/edge_detector.py`

Audit result: **No `module=` field assignments found** in edge_detector.py.

The file sets `market_type` (values: `B_band`, `T_upper`, `T_lower`) and returns it
in the opportunity dict as `'market_type': market_type`. It does **not** set `module=`.
The `module` is assigned downstream by `main.py` and `logger.classify_module()`.

**Decision:** No changes needed in `edge_detector.py` for this migration.

However, note for the record: `market_type` values (`B_band`, `T_upper`, `T_lower`) map
to the new `weather_band` / `weather_threshold` taxonomy distinction. Future work could
use `market_type` directly in `classify_module()` if passed through:

```python
# Future enhancement (out of scope for this migration):
if opportunity.get('market_type') in ('T_upper', 'T_lower'):
    module = 'weather_threshold'
else:
    module = 'weather_band'
```

For now, the ticker-based `-T` / `-B` check in `classify_module()` is sufficient.

---

### 2.6 `environments/demo/dashboard/api.py`

Audit result: `api.py` imports `classify_module` from `agents.ruppert.data_scientist.logger`
(line 20: `from agents.ruppert.data_scientist.logger import classify_module`).

It does **not** have its own local copy of `classify_module()`.

**Decision:** No changes needed in `api.py`. All 14 `classify_module(...)` call sites
(lines 447, 516, 589, 921, 950, 959, 981, 1026, 1216, 1335, 1362, 1368) will automatically
use the updated function after `logger.py` is patched.

---

## 3. Trade Log Backfill Migration Script

**Path:** `environments/demo/scripts/migrate_module_taxonomy.py`

### Target Records

| Old Module   | New Module         | Ticker Pattern       | Count (confirmed) |
|--------------|--------------------|----------------------|-------------------|
| `weather`    | `weather_band`     | ticker contains `-B` | 66                |
| `weather`    | `weather_threshold`| ticker contains `-T` | 32                |
| `crypto`     | `crypto_1h_band`   | any (all confirmed band-type: KXETH-B*, KXDOGE-B*) | 21 |
| `crypto_15m` | `crypto_15m_dir`   | KXBTC15M/KXETH15M/etc | 108             |

> **Verification note:** Weather B/T count discrepancy vs task brief (108 weather total
> confirmed; 66+32=98 matches confirmed log count; brief says 108 weather — brief may
> include future trades not yet logged as of spec time). Script processes whatever is present.

### Script Spec

```python
"""
migrate_module_taxonomy.py
Trade log backfill: rename module tags per taxonomy-migration-2026-03-30.md

IDEMPOTENT: safe to run multiple times. Uses new module names as guard —
records already updated will not be reprocessed.

Usage:
    python environments/demo/scripts/migrate_module_taxonomy.py
    python environments/demo/scripts/migrate_module_taxonomy.py --dry-run
"""
import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent  # → workspace/
TRADES_DIR = WORKSPACE_ROOT / 'environments' / 'demo' / 'logs' / 'trades'
BACKUP_DIR = WORKSPACE_ROOT / 'environments' / 'demo' / 'logs' / 'trades_backup_pre_taxonomy_migration'


def reclassify(record: dict) -> dict | None:
    """
    Returns updated record if module needs to change, else None (no-op).
    Idempotent: new module names are already correct — returns None if module
    already matches a new taxonomy value.
    """
    old_module = record.get('module', '')
    ticker = (record.get('ticker') or '').upper()

    # ── Already migrated ────────────────────────────────────────────────────
    FINAL_MODULES = {
        'weather_band', 'weather_threshold',
        'crypto_15m_dir', 'crypto_1h_dir', 'crypto_1h_band',
        'econ_cpi', 'econ_unemployment', 'econ_fed_rate', 'econ_recession',
        'geo', 'manual', 'other',
    }
    if old_module in FINAL_MODULES:
        return None  # already migrated, skip

    # ── weather → weather_band / weather_threshold ──────────────────────────
    if old_module == 'weather':
        if '-T' in ticker:
            new_module = 'weather_threshold'
        else:
            new_module = 'weather_band'  # -B type (default)
        updated = dict(record)
        updated['module'] = new_module
        return updated

    # ── crypto → crypto_1h_band ─────────────────────────────────────────────
    if old_module == 'crypto':
        updated = dict(record)
        updated['module'] = 'crypto_1h_band'
        return updated

    # ── crypto_15m → crypto_15m_dir ─────────────────────────────────────────
    if old_module == 'crypto_15m':
        updated = dict(record)
        updated['module'] = 'crypto_15m_dir'
        return updated

    # ── crypto_1d → crypto_1h_dir ────────────────────────────────────────────
    if old_module == 'crypto_1d':
        updated = dict(record)
        updated['module'] = 'crypto_1h_dir'
        return updated

    # ── fed → econ_fed_rate ──────────────────────────────────────────────────
    if old_module == 'fed':
        updated = dict(record)
        updated['module'] = 'econ_fed_rate'
        return updated

    # ── econ → subcategory ───────────────────────────────────────────────────
    if old_module == 'econ':
        if ticker.startswith('KXCPI'):
            new_module = 'econ_cpi'
        elif any(ticker.startswith(p) for p in ('KXJOBLESSCLAIMS', 'KXECONSTATU3', 'KXUE')):
            new_module = 'econ_unemployment'
        elif ticker.startswith('KXWRECSS'):
            new_module = 'econ_recession'
        else:
            new_module = 'econ_cpi'  # fallback (same as classify_module default)
        updated = dict(record)
        updated['module'] = new_module
        return updated

    return None  # no mapping found — leave unchanged


def migrate_file(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Process a single trades_YYYY-MM-DD.jsonl file.
    Returns (total_records, records_changed).
    """
    lines = path.read_text(encoding='utf-8').splitlines()
    updated_lines = []
    changed = 0

    for line in lines:
        line = line.strip()
        if not line:
            updated_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            updated_lines.append(line)
            continue

        new_record = reclassify(record)
        if new_record is not None:
            changed += 1
            updated_lines.append(json.dumps(new_record))
        else:
            updated_lines.append(line)

    if not dry_run and changed > 0:
        path.write_text('\n'.join(updated_lines) + '\n', encoding='utf-8')

    return len(lines), changed


def main():
    parser = argparse.ArgumentParser(description='Migrate module taxonomy in trade logs')
    parser.add_argument('--dry-run', action='store_true', help='Print changes without writing')
    args = parser.parse_args()

    if not TRADES_DIR.exists():
        print(f'[ERROR] Trades directory not found: {TRADES_DIR}')
        return

    # ── Backup first (idempotent: skip if backup already exists) ───────────
    if not args.dry_run:
        if not BACKUP_DIR.exists():
            shutil.copytree(TRADES_DIR, BACKUP_DIR)
            print(f'[Backup] Created: {BACKUP_DIR}')
        else:
            print(f'[Backup] Already exists (idempotent run): {BACKUP_DIR}')

    total_records = 0
    total_changed = 0

    for trade_file in sorted(TRADES_DIR.glob('trades_*.jsonl')):
        records, changed = migrate_file(trade_file, dry_run=args.dry_run)
        total_records += records
        if changed:
            print(f'  {"[DRY]" if args.dry_run else "[UPDATED]"} {trade_file.name}: '
                  f'{changed}/{records} records changed')
        else:
            print(f'  [SKIP] {trade_file.name}: already up to date ({records} records)')
        total_changed += changed

    print(f'\n[Done] {total_changed} records updated across {total_records} total records.')
    if args.dry_run:
        print('[DRY RUN] No files were modified.')


if __name__ == '__main__':
    main()
```

### Idempotency Design

- New module names are listed in `FINAL_MODULES` — any record already carrying a new-taxonomy
  name is skipped unconditionally.
- Backup directory uses a fixed path; second run detects it already exists and skips copy.
- File writes only occur if `changed > 0`, avoiding unnecessary disk I/O on already-clean files.

### Expected Output (first run)

```
[Backup] Created: .../logs/trades_backup_pre_taxonomy_migration
  [UPDATED] trades_2026-03-26.jsonl: N/M records changed
  [UPDATED] trades_2026-03-27.jsonl: N/M records changed
  ...
[Done] ~227 records updated across ~227 total records.
```

### Expected Output (second run — idempotent)

```
[Backup] Already exists (idempotent run): ...
  [SKIP] trades_2026-03-26.jsonl: already up to date (M records)
  ...
[Done] 0 records updated across ~227 total records.
```

---

## 4. Summary of All Changed `module=` Values

### Code Changes Summary

| File | Location | BEFORE | AFTER |
|------|----------|--------|-------|
| `logger.py` | `classify_module()` — weather branch | `'weather'` | `'weather_band'` / `'weather_threshold'` |
| `logger.py` | `classify_module()` — crypto_1d branch | `'crypto'` | `'crypto_1h_dir'` |
| `logger.py` | `classify_module()` — crypto branch | `'crypto'` | `'crypto_1h_band'` |
| `logger.py` | `classify_module()` — crypto_15m branch | `'crypto'` | `'crypto_15m_dir'` |
| `logger.py` | `classify_module()` — fed branch | `'fed'` | `'econ_fed_rate'` |
| `logger.py` | `classify_module()` — econ branch | `'econ'` | `'econ_cpi'` / `'econ_unemployment'` / `'econ_recession'` |
| `logger.py` | `build_trade_entry()` — inline inference | full inline block | `classify_module(source, ticker)` |
| `crypto_15m.py` | lines 1095, 1266 | `module='crypto_15m'` | `module='crypto_15m_dir'` |
| `crypto_1d.py` | lines 772, 987, 988 | `module='crypto_1d'` | `module='crypto_1h_dir'` |
| `crypto_1d.py` | lines 850, 854, 865 | `module='crypto_1d'` | `module='crypto_1h_dir'` |
| `crypto_1d.py` | line 673 | `!= 'crypto_1d'` | `!= 'crypto_1h_dir'` |
| `main.py` | line 649 | `module='crypto'` | `module='crypto_1h_band'` |
| `main.py` | line 610 | `module='crypto'` (exposure guard) | `module='crypto_1h_band'` |
| `main.py` | line 294 | `module='weather'` | remove or compute via `classify_module()` |
| `main.py` | line 906 | `module='fed'` | `module='econ_fed_rate'` |
| `main.py` | line 847 | `module='fed'` (exposure guard) | `module='econ_fed_rate'` |

### No-Change Confirmations

| File | Reason |
|------|--------|
| `main.py` lines 1040, 1101 | `geo` module name unchanged |
| `main.py` lines 257, 290 | Weather exposure guards — `module='weather'` still works via prefix matching |
| `edge_detector.py` | No `module=` assignments; sets `market_type` only |
| `dashboard/api.py` | Imports `classify_module` from logger; no local copy |

---

## 5. Deployment Order

**Recommended sequence (single PR, atomic deploy):**

1. **Run backfill script first** (`--dry-run` pass, then live pass)
   - Validates all records get updated correctly before code deploys
   - Old code + new logs = broken; new code + old logs = broken; backfill resolves this
2. **Deploy code changes** (logger.py, crypto_15m.py, crypto_1d.py, main.py) atomically
3. **Verify** with a dashboard reload — all trades should show new module names
4. **Monitor** first new trades post-deploy to confirm module values in JSONL

> **Do not deploy code changes before running backfill.** After code deploy, `classify_module()`
> will write new names for all incoming trades. Historical records still carry old names.
> The dashboard would then show mixed old/new names in module filters.

---

## 6. Rollback Plan

- Backfill script creates `trades_backup_pre_taxonomy_migration/` before any writes.
- To rollback: delete `logs/trades/` directory, copy backup back.
- Code rollback: revert the PR (all changes in one PR for clean revert).

---

## 7. Open Items (for David's awareness)

1. **`econ_gdp`, `econ_pce`, `econ_ppi`** — listed in redesign spec as future candidates.
   Not in approved taxonomy; will fall through to `other` if traded before taxonomy update.
   Add to `classify_module()` when those scanners go live.

2. **Weather exposure guard granularity** — `get_daily_exposure(module='weather')` currently
   aggregates all weather subcategories (prefix match). If separate per-subcategory exposure
   caps are needed (e.g., band vs threshold limits), that's a future enhancement requiring
   new `MIN_CONFIDENCE` keys and separate guard calls.

3. **`KXSOL15M` in `crypto_15m_dir`** — Series is in the approved taxonomy but not observed
   in current trade logs. Verify it's trading before adding to exchange-specific signal config.

4. **`KXXRP` in `crypto_1h_band`** — Listed in approved taxonomy. Confirmed in `classify_module()`
   AFTER block via `KXXRP` prefix. Not in current 21 `crypto` log trades (only KXETH+KXDOGE seen).
   Should work correctly once live.
