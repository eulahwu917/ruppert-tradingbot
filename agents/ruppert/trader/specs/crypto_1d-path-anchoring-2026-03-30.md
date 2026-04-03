# Spec: crypto_1d — CWD-Relative Path Anchoring

**File:** `agents/ruppert/trader/crypto_1d.py`
**Date:** 2026-03-30
**Author:** Ruppert (Trader)
**Status:** Ready for Dev

---

## Problem

`OI_SNAPSHOT_PATH` and `DECISION_LOG_PATH` are defined as bare relative `Path(...)` strings:

```python
OI_SNAPSHOT_PATH = Path('environments/demo/logs/oi_1d_snapshot.json')
DECISION_LOG_PATH = Path('environments/demo/logs/decisions_1d.jsonl')
```

These resolve relative to the **current working directory at runtime**, not relative to the module file. If the process is launched from any directory other than workspace root (e.g. the `agents/` directory, a Task Scheduler working dir mismatch, or a test runner), these paths silently resolve to the wrong location — causing silent read misses on OI snapshots and lost decision log entries.

---

## Reference Pattern

`crypto_15m.py` uses the correct pattern:

```python
from agents.ruppert.env_config import get_paths as _get_paths

LOGS_DIR = _get_paths()['logs']
LOGS_DIR.mkdir(exist_ok=True)
DECISION_LOG = LOGS_DIR / 'decisions_15m.jsonl'
```

`get_paths()` resolves the environment root using `ENVIRONMENTS_DIR` (anchored via `Path(__file__)` inside `env_config.py`), so the result is always absolute regardless of CWD.

---

## BEFORE

```python
OI_SNAPSHOT_PATH = Path('environments/demo/logs/oi_1d_snapshot.json')
DECISION_LOG_PATH = Path('environments/demo/logs/decisions_1d.jsonl')
```

No import of `env_config` at the constants block.

---

## AFTER

Add import at the top of the constants block (after existing imports):

```python
from agents.ruppert.env_config import get_paths as _get_paths

_LOGS_DIR = _get_paths()['logs']
_LOGS_DIR.mkdir(exist_ok=True)

OI_SNAPSHOT_PATH = _LOGS_DIR / 'oi_1d_snapshot.json'
DECISION_LOG_PATH = _LOGS_DIR / 'decisions_1d.jsonl'
```

**Note:** `_get_paths()` reads `config.ENV` (defaulting to `'demo'`) at import time — same behaviour as the old hard-coded `environments/demo/logs/` path, but now anchored absolutely.

---

## Acceptance Criteria

1. Both paths resolve to an **absolute path** when `crypto_1d.py` is imported from any working directory.
2. Running `python -c "import agents.ruppert.trader.crypto_1d as m; print(m.OI_SNAPSHOT_PATH)"` from workspace root, `agents/`, and `agents/ruppert/trader/` all print the same absolute path.
3. No change to file names (`oi_1d_snapshot.json`, `decisions_1d.jsonl`) or the environment the path resolves to.
4. `_LOGS_DIR.mkdir(exist_ok=True)` is called so the directory is auto-created if absent (matches `crypto_15m.py` behaviour).
5. Existing callers that read/write via `OI_SNAPSHOT_PATH` and `DECISION_LOG_PATH` require no other changes.

---

## Risk

**Low.** Pure path arithmetic change. No logic altered. Produces identical resolved paths when CWD is workspace root (existing deployment). Fixes silent failures when CWD differs.
