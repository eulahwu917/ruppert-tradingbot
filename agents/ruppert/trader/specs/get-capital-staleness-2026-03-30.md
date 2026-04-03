# SPEC: get_capital() Staleness — pnl_cache Divergence Fix
**Date:** 2026-03-30
**Author:** Trader
**Source:** DS investigation → Trader formal spec
**Status:** Ready for Dev

---

## Problem Statement

`get_capital()` in `capital.py` and the dashboard's Closed P&L display read from **two different sources**, causing Account Value and Closed P&L to show inconsistent numbers during the gap between a settlement/exit landing in trade logs and the synthesizer next running.

---

## Root Cause

### Path A — `get_capital()` (used by bot, risk checks, buying power)
```
capital.py :: get_capital()
  └─> get_pnl()
        └─> reads pnl_cache.json   ← written by synthesizer.py, may be stale
              └─> returns closed_pnl
```

### Path B — Dashboard Closed P&L (used by /api/pnl, /api/state)
```
dashboard/api.py :: get_pnl_history() / _build_state()
  └─> scans all trades_*.jsonl
        └─> sums pnl field from action=exit/settle records   ← always live
```

### Divergence Window
When a settle or exit record lands in `logs/trades/trades_YYYY-MM-DD.jsonl` but before `synthesizer.py` next runs:
- **Path B (dashboard)** immediately reflects the new closed P&L.
- **Path A (`get_capital()`)** still reads the stale value from `pnl_cache.json`.

This causes `Account Value` (which calls `get_capital()`) and the dashboard `Closed P&L` panel to disagree until the next synthesis cycle.

---

## BEFORE

**File:** `agents/ruppert/data_scientist/capital.py`

```python
def get_capital() -> float:
    # ... (DEMO mode path)
    # Add realized P&L from pnl_cache
    closed_pnl = get_pnl().get('closed', 0.0)   # <-- reads pnl_cache.json (stale)
    return round(total + closed_pnl, 2)


def get_pnl() -> dict:
    """Reads from pnl_cache.json (written by synthesizer.py)."""
    result = {'closed': 0.0, 'open': 0.0, 'total': 0.0}
    try:
        if _PNL_CACHE_FILE.exists():
            data = json.loads(_PNL_CACHE_FILE.read_text(encoding='utf-8'))
            result['closed'] = round(float(data.get('closed_pnl', 0.0)), 2)
            result['open']   = round(float(data.get('open_pnl', 0.0)), 2)
            result['total']  = round(result['closed'] + result['open'], 2)
    except Exception as e:
        logger.warning(f'[Capital] get_pnl() failed: {e}')
    return result
```

**Behavior:** Closed P&L read from `pnl_cache.json`. Stale between synthesizer runs.

---

## AFTER

### Change 1 — Add `compute_closed_pnl_from_logs()` to `logger.py`

Extract the live log-scan logic here (not in `data_agent.py`) to avoid circular imports: `data_agent.py` already imports `get_capital` from `capital.py`, so `capital.py` cannot import from `data_agent.py`.

**File:** `agents/ruppert/data_scientist/logger.py`

Add at the bottom (after existing helpers):

```python
def compute_closed_pnl_from_logs() -> float:
    """Compute closed P&L by scanning all trade log files live.
    Sums the pnl field from all action=exit and action=settle records.
    This is the same logic used by the dashboard — eliminates pnl_cache staleness.
    """
    from agents.ruppert.env_config import get_paths as _get_paths
    import json
    from pathlib import Path
    from datetime import date

    try:
        _paths = _get_paths()
        trades_dir = _paths['trades']
        total_pnl = 0.0
        since = '2026-03-26'
        for p in sorted(trades_dir.glob('trades_*.jsonl')):
            try:
                file_date = p.stem.replace('trades_', '')
                if file_date < since:
                    continue
            except Exception:
                continue
            for line in p.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                    if t.get('action') in ('exit', 'settle') and t.get('pnl') is not None:
                        total_pnl += float(t['pnl'])
                except Exception:
                    pass
        return round(total_pnl, 2)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[Logger] compute_closed_pnl_from_logs() failed: {e}')
        return 0.0
```

### Change 2 — Update `get_capital()` to use live log scan

**File:** `agents/ruppert/data_scientist/capital.py`

```python
def get_capital() -> float:
    """
    Return total available capital.
    DEMO: sum of demo_deposits.jsonl + realized P&L computed live from trade logs.
    LIVE: Kalshi API balance (falls back to deposits if API unavailable)
    """
    try:
        # ... (Kalshi LIVE path unchanged) ...

        # DEMO mode: sum deposits
        total = 0.0
        if _DEPOSITS_FILE.exists():
            for line in _DEPOSITS_FILE.read_text(encoding='utf-8').strip().splitlines():
                try:
                    total += json.loads(line).get('amount', 0)
                except Exception:
                    continue

        if total <= 0:
            logger.warning(f'[Capital] deposits file empty or missing — using ${_DEFAULT_CAPITAL:.0f} default')
            return _DEFAULT_CAPITAL

        # Add realized P&L — read LIVE from trade logs (same path as dashboard display)
        # Do NOT use pnl_cache.json here: it lags behind trade logs until synthesizer runs,
        # causing Account Value to diverge from the dashboard Closed P&L panel.
        from agents.ruppert.data_scientist.logger import compute_closed_pnl_from_logs
        closed_pnl = compute_closed_pnl_from_logs()
        return round(total + closed_pnl, 2)

    except Exception as e:
        logger.warning(f'[Capital] get_capital() failed: {e} — using ${_DEFAULT_CAPITAL:.0f} default')
        return _DEFAULT_CAPITAL
```

### `get_pnl()` — no change required

`get_pnl()` in `capital.py` continues to read from `pnl_cache.json` and is used by callers that need open P&L (which only the synthesizer can compute from live prices). Its signature and callers are unchanged.

---

## Scope

| File | Change |
|---|---|
| `agents/ruppert/data_scientist/logger.py` | Add `compute_closed_pnl_from_logs()` |
| `agents/ruppert/data_scientist/capital.py` | Replace `get_pnl().get('closed')` with `compute_closed_pnl_from_logs()` in `get_capital()` |
| `agents/ruppert/data_scientist/data_agent.py` | No change — `compute_pnl_from_logs()` still lives here for the audit path |

---

## Invariants (must not change)

- `get_capital()` public signature unchanged — returns `float`
- `get_pnl()` public signature unchanged — callers of open P&L unaffected
- `pnl_cache.json` still written by synthesizer — other consumers unaffected
- No circular imports: `logger.py` ← `capital.py` ← `data_agent.py` (chain unchanged)

---

## QA Checklist

- [ ] Force a settle record into trade logs before running synthesizer. Confirm `get_capital()` reflects updated closed P&L immediately.
- [ ] Confirm dashboard `Closed P&L` and `Account Value` agree before and after synthesizer run.
- [ ] Run `python -c "from agents.ruppert.data_scientist.capital import get_capital; print(get_capital())"` — no import error.
- [ ] Confirm no circular import: `data_agent.py → capital.py → logger.py` chain is clean (logger.py must not import capital.py or data_agent.py).
- [ ] Run existing post-scan audit — no regressions in `check_pnl_consistency()`.

---

## Notes

- The synthesizer continues to write `pnl_cache.json` — it is still the authoritative file for **open P&L** (which requires live prices that only the synthesizer fetches). This fix only eliminates the staleness on the **closed** component.
- After this fix, `get_capital()` will make a fast file-scan on each call. This is acceptable — the function already does file I/O (reads `demo_deposits.jsonl`). The scan is bounded to `logs/trades/` files since `2026-03-26`.
