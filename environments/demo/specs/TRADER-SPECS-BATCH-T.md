# TRADER SPECS — Batch T

**Author:** Trader (Ruppert)  
**Date:** 2026-03-29  
**Status:** Ready for Dev  
**Priority order:** T1 → T2 → T3 → T4 → T5 → T6

---

## T1: Weather trades never register in position_tracker in DEMO (CRITICAL)

**Files to modify:** `agents/ruppert/trader/trader.py`

**Root cause confirmed:** In `execute_opportunity()`, the inner guard `if not self.dry_run:` (line ~72) is dead code — it is nested inside the `if self.dry_run:` block, so the condition is always `False`. `add_position()` is unreachable in DEMO mode for weather trades. WS exits therefore never fire for weather entries.

**Policy decision (enforce this):** DRY_RUN positions MUST be tracked in position_tracker. The "phantom position guard" comment is wrong and the code implementing it must be removed. This is required for WS exit testing in DEMO.

**Change:**

In `trader.py`, inside the `if self.dry_run:` block, replace:

```python
# CURRENT (broken — dead code)
if not self.dry_run:  # Never track positions in dry-run mode (phantom position guard)
    try:
        from agents.ruppert.trader import position_tracker
        position_tracker.add_position(
            ticker=ticker,
            quantity=contracts,
            side=side,
            entry_price=price_cents,
            module=opportunity.get('module', ''),
            title=opportunity.get('title', ticker),
        )
    except Exception as e:
        log_activity(f"[Trader] Warning: could not register {ticker} in position tracker: {e}")
```

With:

```python
# FIXED — always track positions in dry_run block (WS exit requires it)
try:
    from agents.ruppert.trader import position_tracker
    position_tracker.add_position(
        ticker=ticker,
        quantity=contracts,
        side=side,
        entry_price=price_cents,
        module=opportunity.get('module', ''),
        title=opportunity.get('title', ticker),
    )
except Exception as e:
    log_activity(f"[Trader] Warning: could not register {ticker} in position tracker: {e}")
```

The `if not self.dry_run:` guard and its stale comment are deleted entirely. The `try/except` block is promoted one indent level (now directly inside `if self.dry_run:`).

No other changes to this function. The live path already calls `add_position()` unconditionally (correct).

**Test:** QA steps:
1. Run in DEMO mode (`DRY_RUN=True`). Submit a weather opportunity (KXHIGH ticker) through `execute_opportunity()`.
2. After execution, call `position_tracker.get_tracked()` — the ticker must appear in the returned dict.
3. Simulate a WS tick via `asyncio.run(position_tracker.check_exits(ticker, threshold_price, threshold_price))` where `threshold_price` meets the 95c rule.
4. Confirm exit fires (activity log shows `[WS Exit]` line) and position is removed from tracked dict.
5. Confirm LIVE path (mock `self.dry_run=False`) still registers position as before.

---

## T2: crypto_15m.py bypasses should_enter() — no 70% global cap (CRITICAL)

**Files to modify:** `agents/ruppert/trader/crypto_15m.py`

**Root cause confirmed:** `evaluate_crypto_15m_entry()` performs its own daily cap check (confirmed present) and then jumps directly to the `# ── Execute ──` block. There is no call to `strategy.should_enter()`. The 70% global deployment cap and strategy gate are completely bypassed for all 15-min crypto WS entries.

**Change:**

1. Add the following import at **module level** (top of file, alongside existing imports):

```python
from agents.ruppert.strategist.strategy import should_enter
```

2. Locate the existing daily cap check block (after `# ── Daily cap check ──` comment). It currently ends with `return` on cap hit. Immediately **after** the cap check block and **before** the `# ── Position Sizing: Half-Kelly, capped ──` comment, insert:

```python
    # ── Strategy gate: global 70% deployment cap + strategy filters ──
    _total = capital  # already fetched above
    from agents.ruppert.data_scientist.capital import get_buying_power
    from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_exp
    _deployed_today = _get_exp()
    _crypto_deployed = _get_exp()   # crypto_15m is a crypto module — use total crypto exposure as proxy
    _module_deployed_pct = _crypto_deployed / _total if _total > 0 else 0.0

    _signal_dict = {
        'ticker': ticker,
        'title': f'{asset} 15m direction',
        'side': direction,
        'edge': round(edge, 4),
        'win_prob': round(P_win, 4),
        'confidence': round(abs(raw_score), 3),
        'market_prob': yes_ask / 100.0 if direction == 'yes' else (100 - yes_bid) / 100.0,
        'model_prob': round(P_final, 4),
        'source': 'crypto_15m',
        'module': 'crypto_15m',
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
    }
    _se_decision = should_enter(
        _signal_dict,
        _total,
        _deployed_today,
        module='crypto',
        module_deployed_pct=_module_deployed_pct,
        traded_tickers=None,
    )
    if not _se_decision['enter']:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                      signals, kalshi_info, 'SKIP', f'STRATEGY_GATE:{_se_decision["reason"]}',
                      edge, entry_price, None)
        return
```

Insert point in context:

```python
    # ── Daily cap check ──
    capital = get_capital()
    daily_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
    current_exposure = get_daily_exposure()

    if current_exposure >= daily_cap:
        _log_decision(...)
        return

    # ── Strategy gate: global 70% deployment cap + strategy filters ──   ← INSERT HERE
    ...

    # ── Position Sizing: Half-Kelly, capped ──
    c = entry_price / 100.0
```

**Note:** `signals` and `kalshi_info` dicts are already built above the daily cap check — they are in scope. `direction` and `edge` and `entry_price` are also already computed. No restructuring needed.

**Test:** QA steps:
1. Temporarily set `config.MAX_DEPLOY_PCT = 0.0` (force 70% gate to block everything).
2. Trigger `evaluate_crypto_15m_entry()` with a valid ticker and sufficient edge.
3. Confirm `decisions_15m.jsonl` receives a record with `decision='SKIP'` and `skip_reason` starting with `'STRATEGY_GATE:'`.
4. Confirm no trade is placed and `position_tracker.get_tracked()` has no new entry.
5. Reset `MAX_DEPLOY_PCT` to normal. Trigger again with below-cap exposure — confirm trade executes normally.
6. Confirm the strategy gate block is between the daily cap check and the size calculation by reading the updated function.

---

## T3: position_tracker keys by ticker alone, not (ticker, side) (HIGH)

**Files to modify:** `agents/ruppert/trader/position_tracker.py`

**Root cause confirmed:** `_tracked` dict uses bare `ticker` string as key. Any two positions on the same ticker (e.g. YES then NO, or a re-entry on opposite side) will silently overwrite each other. MEMORY.md specifies `(ticker, side)` keying.

**Changes — ALL in `position_tracker.py`:**

### 1. In-memory dict key change

The `_tracked` dict is unchanged in name, but all internal accesses switch from `ticker` string keys to `(ticker, side)` tuple keys.

### 2. `_persist()` — serialize tuple keys as `"ticker::side"` strings for JSON compatibility

```python
def _persist():
    """Write tracked positions to disk."""
    if get_current_env() == 'live':
        require_live_enabled()
    try:
        TRACKER_FILE.parent.mkdir(exist_ok=True)
        # Serialize tuple keys as "ticker::side" strings for JSON
        serializable = {f'{k[0]}::{k[1]}': v for k, v in _tracked.items()}
        tmp = TRACKER_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(serializable, indent=2), encoding='utf-8')
        tmp.replace(TRACKER_FILE)
    except Exception as e:
        logger.warning('[PositionTracker] Persist failed: %s', e)
```

### 3. `_load()` — deserialize `"ticker::side"` back to tuple keys

```python
def _load():
    """Load tracked positions from disk on startup."""
    global _tracked
    if not TRACKER_FILE.exists():
        return
    try:
        data = json.loads(TRACKER_FILE.read_text(encoding='utf-8'))
        for raw_key, value in data.items():
            if '::' in raw_key:
                ticker_part, side_part = raw_key.split('::', 1)
                _tracked[(ticker_part, side_part)] = value
            else:
                # Legacy format (plain ticker) — migrate by inferring side from data
                side_part = value.get('side', 'yes')
                _tracked[(raw_key, side_part)] = value
        logger.info('[PositionTracker] Loaded %d tracked positions from disk', len(_tracked))
    except Exception as e:
        logger.warning('[PositionTracker] Load failed: %s', e)
```

### 4. `add_position()` — key by `(ticker, side)`

```python
def add_position(ticker: str, quantity: int, side: str, entry_price: float,
                 module: str = '', title: str = '', holding_type: str = ''):
    ...
    # (all existing threshold logic unchanged)
    ...
    _tracked[(ticker, side)] = {          # ← was: _tracked[ticker] = {
        'quantity': quantity,
        'side': side,
        'entry_price': entry_price,
        'module': module,
        'title': title,
        'added_at': time.time(),
        'exit_thresholds': thresholds,
    }
    _persist()
    logger.info('[PositionTracker] Tracking %s %s @ %dc (%d contracts)', ticker, side, entry_price, quantity)
```

### 5. `remove_position()` — add `side` parameter

```python
def remove_position(ticker: str, side: str):           # ← add side param
    """Call after exit execution."""
    _tracked.pop((ticker, side), None)                 # ← was: _tracked.pop(ticker, None)
    _persist()
```

### 6. `get_tracked()` — return dict with string keys for external consumers

```python
def get_tracked() -> dict:
    """Return copy of tracked positions (for diagnostics). Keys are 'ticker::side' strings."""
    return {f'{k[0]}::{k[1]}': v for k, v in _tracked.items()}
```

### 7. `is_tracked()` — add `side` parameter

```python
def is_tracked(ticker: str, side: str) -> bool:       # ← add side param
    return (ticker, side) in _tracked                  # ← was: ticker in _tracked
```

### 8. `check_exits()` — iterate all matching (ticker, *) entries

The WS feed calls `check_exits(ticker, yes_bid, yes_ask)` without knowing the side. Iterate all keys matching the ticker:

```python
async def check_exits(ticker: str, yes_bid: int | None, yes_ask: int | None):
    """
    Called by WS feed on every tick for tracked tickers.
    Checks all positions (any side) for the given ticker.
    """
    if yes_bid is None:
        return

    matching_keys = [k for k in _tracked if k[0] == ticker]
    for key in matching_keys:
        pos = _tracked.get(key)
        if pos is None:
            continue

        for threshold in pos['exit_thresholds']:
            compare = threshold.get('compare', 'gte')
            price_target = threshold['price']
            triggered = False

            if compare == 'lte':
                triggered = yes_bid <= price_target
            else:
                triggered = yes_bid >= price_target

            if triggered:
                rule = threshold.get('rule', 'threshold')
                log_activity(
                    f'[WS Exit] {ticker} {key[1].upper()} hit {rule} '
                    f'(bid={yes_bid}c, target={price_target}c) — exiting'
                )
                await execute_exit(key, pos, yes_bid, rule)
                break  # one threshold per position per tick
```

### 9. `execute_exit()` — accept `key` tuple instead of bare `ticker`

```python
async def execute_exit(key: tuple, pos: dict, current_bid: int, rule: str):
    """Execute the exit order via REST."""
    from agents.ruppert.data_analyst.kalshi_client import KalshiClient

    ticker, side = key                    # ← unpack tuple
    entry_price = pos['entry_price']
    quantity = pos['quantity']
    module = pos.get('module', '')

    # (P&L and order logic unchanged)
    ...

    remove_position(ticker, side)         # ← pass both args
```

### 10. `recovery_poll_positions()` — iterate with tuple keys

```python
async def recovery_poll_positions():
    ...
    for key in list(_tracked.keys()):
        ticker = key[0]                   # ← was: ticker = key (string)
        try:
            market = client.get_market(ticker)
            ...
            await check_exits(ticker, yes_bid, yes_ask)
        ...
```

### Caller audit — trader.py and position_monitor.py

**trader.py:** Calls `position_tracker.add_position(ticker=..., side=..., ...)` — signature unchanged, no fix needed.  
**trader.py:** Does NOT call `remove_position()` or `is_tracked()` directly. No fix needed.

**position_monitor.py:** Calls `position_tracker.add_position(ticker, fill_contracts, side, fill_price, ...)` in two places — positional args, no signature change, no fix needed.  
**position_monitor.py:** Does NOT call `remove_position()` or `is_tracked()` directly. No fix needed.

**Any caller using `is_tracked(ticker)` (e.g. ws_feed.py):** Must be updated to pass `side` as second arg. Dev must grep `is_tracked(` across the codebase and update all call sites to `is_tracked(ticker, side)`.

**Test:** QA steps:
1. Call `add_position('KXBTC-26MAR28-B87500', 5, 'yes', 45)`. Verify `get_tracked()` returns `{'KXBTC-26MAR28-B87500::yes': {...}}`.
2. Call `add_position('KXBTC-26MAR28-B87500', 3, 'no', 60)` on same ticker. Verify `get_tracked()` now has BOTH `::yes` and `::no` entries (not overwritten).
3. Call `remove_position('KXBTC-26MAR28-B87500', 'yes')`. Verify only `::yes` is removed; `::no` remains.
4. Restart the process — verify `_load()` restores both positions correctly from `tracked_positions.json`.
5. Verify `tracked_positions.json` on disk has string keys like `"KXBTC-26MAR28-B87500::yes"`.
6. Simulate a WS tick via `check_exits('KXBTC-26MAR28-B87500', 95, 97)` — confirm exit fires for the correct side(s).

---

## T4: Trade log path mismatch (HIGH)

**Files to modify:**  
- `agents/ruppert/trader/ruppert_cycle.py` (function: `load_traded_tickers`)  
- `agents/ruppert/trader/post_trade_monitor.py` (functions: `load_open_positions`, `check_settlements`)  
- `agents/ruppert/trader/position_monitor.py` (functions: `load_open_positions`, `load_traded_tickers`)

**Flag to CEO:** `brief_generator.py` reads from a `TRADES_DIR` constant — confirm it uses `get_paths()['trades']` (the subdir). If it uses a hand-rolled path or `logs_dir` directly, it has the same bug. CEO should audit before next brief run.

**Root cause confirmed:**

- `logger.py` writes trades to: `get_paths()['trades'] / trades_YYYY-MM-DD.jsonl` → **`logs/trades/`** subdir ✓
- All readers below use `get_paths()['logs']` (flat) — **wrong**.

**Canonical path:** `get_paths()['trades']` = `environments/{env}/logs/trades/`

---

### Fix A — `post_trade_monitor.py`: `load_open_positions()`

Currently uses `LOGS` (= `get_paths()['logs']`). Change to use `TRADES_DIR`.

At module level, `post_trade_monitor.py` does NOT currently define a `TRADES_DIR`. Add it:

```python
# After existing LOGS = _get_paths()['logs'] line:
TRADES_DIR = _get_paths()['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)
```

Then in `load_open_positions()`, replace ALL `LOGS /` references with `TRADES_DIR /`:

```python
# BEFORE (wrong):
logs_to_check = [
    LOGS / f"trades_{yesterday}.jsonl",
    LOGS / f"trades_{today}.jsonl",
]

# AFTER (correct):
logs_to_check = [
    TRADES_DIR / f"trades_{yesterday}.jsonl",
    TRADES_DIR / f"trades_{today}.jsonl",
]
```

### Fix B — `post_trade_monitor.py`: `check_settlements()`

`check_settlements` receives `logs_dir` as a parameter (called with `LOGS_DIR` = `LOGS`). This function:
1. Reads trade logs from `logs_dir / f"trades_{yesterday}.jsonl"` etc. — **wrong path**
2. Writes settle records to `logs_dir / f'trades_{date.today().isoformat()}.jsonl'` — **wrong path**

Change the call site in `run_monitor()`:

```python
# BEFORE:
check_settlements(client, LOGS_DIR)

# AFTER:
check_settlements(client, TRADES_DIR)
```

Also update the `check_settlements` function signature docstring to clarify `logs_dir` is actually the trades subdir. No other logic changes needed inside `check_settlements` — it uses `logs_dir` consistently for both reads and writes.

### Fix C — `position_monitor.py`: `load_open_positions()` and `load_traded_tickers()`

`position_monitor.py` currently defines only `LOGS = _get_paths()['logs']`. Add `TRADES_DIR`:

```python
# After existing LOGS = _get_paths()['logs'] line:
TRADES_DIR = _get_paths()['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)
```

In `load_open_positions()`, replace `LOGS /` with `TRADES_DIR /`:

```python
# BEFORE (wrong):
logs_to_check = [
    LOGS / f"trades_{yesterday}.jsonl",
    LOGS / f"trades_{today}.jsonl",
]

# AFTER (correct):
logs_to_check = [
    TRADES_DIR / f"trades_{yesterday}.jsonl",
    TRADES_DIR / f"trades_{today}.jsonl",
]
```

In `load_traded_tickers()`, replace `LOGS /` with `TRADES_DIR /`:

```python
# BEFORE (wrong):
trade_log = LOGS / f"trades_{today}.jsonl"

# AFTER (correct):
trade_log = TRADES_DIR / f"trades_{today}.jsonl"
```

Also in `_settle_single_ticker()`, replace `LOGS_DIR /` with `TRADES_DIR /`:

```python
# BEFORE (wrong):
log_path = LOGS_DIR / f'trades_{date.today().isoformat()}.jsonl'

# AFTER (correct):
log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
```

### Fix D — `ruppert_cycle.py`: `load_traded_tickers()`

The issue states this function reads from the flat `logs_dir` directly. Apply the same fix pattern:

```python
# Wherever load_traded_tickers() builds its file path, change from:
log_path = logs_dir / f"trades_{today}.jsonl"     # or equivalent flat reference

# To:
from agents.ruppert.env_config import get_paths as _get_paths
_trades_dir = _get_paths()['trades']
log_path = _trades_dir / f"trades_{today}.jsonl"
```

If `ruppert_cycle.py` already imports `get_paths`, use the existing import. Do not add a duplicate. Dev must read the existing import block before editing.

**Test:** QA steps:
1. Place a DEMO trade via `trader.py` — confirm it writes to `environments/demo/logs/trades/trades_YYYY-MM-DD.jsonl`.
2. Call `post_trade_monitor.load_open_positions()` — confirm it reads from the same subdir and returns the position.
3. Call `position_monitor.load_traded_tickers()` — confirm it reads from the same subdir and includes the traded ticker.
4. Run `ruppert_cycle.load_traded_tickers()` — confirm it finds the ticker and dedup works (same ticker is not re-entered).
5. Verify `environments/demo/logs/` (the flat dir) has NO stray `trades_*.jsonl` files after a full cycle.

---

## T5: crypto_long_horizon.get_daily_exposure() called with positional arg (HIGH)

**Files to modify:**  
- `agents/ruppert/data_scientist/logger.py`

**Root cause confirmed (from reading logger.py):**

```python
def get_daily_exposure():   # ← no parameters
```

In `crypto_long_horizon.py` `run_long_horizon_scan()`:

```python
_crypto_deployed = get_daily_exposure('crypto')   # ← TypeError: takes 0 positional arguments but 1 was given
```

This causes `run_long_horizon_scan()` to raise `TypeError` and abort silently (caught by the outer `try/except`). All long-horizon opportunities are missed.

**Change — `logger.py`: add optional `module` parameter to `get_daily_exposure()`**

```python
def get_daily_exposure(module: str = None) -> float:
    """Calculate total $ exposure from today's open positions.

    Also reads yesterday's log to catch multi-day positions that were entered
    yesterday but not yet exited. Only counts entries (buys) that have no
    corresponding exit across both log files.

    Args:
        module: Optional module name to filter (e.g. 'crypto', 'weather').
                If None, returns total exposure across all modules.
    """
    today_str     = _pdt_today().isoformat()
    yesterday_str = (_pdt_today() - timedelta(days=1)).isoformat()

    entries   = {}   # key: (ticker, side) → size_dollars of the latest entry
    exit_keys = set()

    for day_str in [yesterday_str, today_str]:
        log_path = os.path.join(TRADES_DIR, f"trades_{day_str}.jsonl")
        if not os.path.exists(log_path):
            continue
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ticker = entry.get('ticker', '')
                    side   = entry.get('side', '')
                    action = entry.get('action', 'buy')
                    key    = (ticker, side)
                    if action in ('exit', 'settle'):
                        exit_keys.add(key)
                    else:
                        # Module filter: skip if module specified and doesn't match
                        if module is not None:
                            entry_module = entry.get('module', '')
                            # 'crypto' matches both 'crypto' and 'crypto_15m' and 'crypto_long_horizon'
                            if not (entry_module == module or entry_module.startswith(module + '_') or entry_module.startswith(module)):
                                continue
                        entries[key] = entry.get('size_dollars', 0)
                except:
                    pass

    return sum(size for key, size in entries.items() if key not in exit_keys)
```

**Important:** The existing no-arg calls `get_daily_exposure()` throughout the codebase remain valid — the new `module` param defaults to `None` (no filter = existing behavior). No other call sites need updating.

**Test:** QA steps:
1. Place one `crypto_15m` trade ($20) and one `weather` trade ($15) in the DEMO log.
2. Call `get_daily_exposure()` — expect `$35.0` (all modules).
3. Call `get_daily_exposure('crypto')` — expect `$20.0` (crypto only).
4. Call `get_daily_exposure('weather')` — expect `$15.0` (weather only).
5. Run `run_long_horizon_scan()` end-to-end in DEMO — confirm it no longer aborts with TypeError (check activity log for `[LongHorizon] Scanning` output reaching the opportunities loop).

---

## T6: crypto_15m.py bare import from position_monitor (MEDIUM)

**Files to modify:** `agents/ruppert/trader/crypto_15m.py`

**Root cause confirmed:** Inside `evaluate_crypto_15m_entry()` function body:

```python
from position_monitor import load_traded_tickers, push_alert   # ← bare import, line ~310
```

This works only by accident when `agents/ruppert/trader/` happens to be on `sys.path`. It will silently break in any context where it's not (cron, Task Scheduler, imports from a different working directory).

**sys.path bootstrap status:** Confirmed present at module level (lines 32–35):

```python
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))
```

Workspace root IS on sys.path — `agents.ruppert.*` imports work. The trader directory itself is NOT added, so bare `position_monitor` is not reliably resolvable.

**Change:**

Locate the bare import inside `evaluate_crypto_15m_entry()` and replace:

```python
# BEFORE (bare import — unreliable):
from position_monitor import load_traded_tickers, push_alert

# AFTER (fully qualified — always works):
from agents.ruppert.trader.position_monitor import load_traded_tickers, push_alert
```

This is a one-line change inside the function body. No other changes needed.

**Test:** QA steps:
1. From a directory that is NOT `agents/ruppert/trader/`, run:  
   `python -c "from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry; print('OK')"`  
   Expected: `OK` with no `ModuleNotFoundError`.
2. Call `evaluate_crypto_15m_entry('KXBTC15M-26MAR281315-15', 55, 48)` in a fresh Python process started from the workspace root — confirm `load_traded_tickers` resolves correctly.
3. Confirm no existing test that ran from the trader directory breaks (the fully qualified path resolves in all contexts).

---

## Summary Table

| ID | Severity | Files | Risk of regression |
|----|----------|-------|--------------------|
| T1 | CRITICAL | trader.py | Low — removes dead guard, adds position tracking in dry_run |
| T2 | CRITICAL | crypto_15m.py | Low — adds gate before execute, no existing logic removed |
| T3 | HIGH | position_tracker.py | Medium — key format changes, requires _load() migration path for existing tracked_positions.json |
| T4 | HIGH | post_trade_monitor.py, position_monitor.py, ruppert_cycle.py | Low — path fix only, behavior unchanged |
| T5 | HIGH | logger.py | Low — backward-compatible param addition |
| T6 | MEDIUM | crypto_15m.py | Low — one-line import fix |

**T3 note for Dev:** After deploying T3, delete or migrate `environments/demo/logs/tracked_positions.json` before restarting. The `_load()` function includes a legacy migration path (reads plain ticker keys and infers side from the stored `side` field), but a clean start avoids edge cases.
