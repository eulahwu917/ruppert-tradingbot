# Ruppert Trading Bot — Agent Ownership Architecture

**Version:** 2.0  
**Date:** 2026-03-28  
**Author:** Strategist (Opus)  
**Status:** FINAL — Implementation Spec for Dev

---

## Executive Summary

This document defines the complete agent ownership model for the Ruppert trading bot. It replaces the previous architecture document with the final locked structure, provides a complete codebase audit, folder restructure plan, migration steps, and implementation spec.

**Core Principle:** Every script and truth file has exactly one owner agent. Scripts append to raw event logs — never mutate truth files. Agents read logs, synthesize state, and own truth files.

---

## Part 1: Final Locked Organization Structure

```
CEO (Sonnet)
├── Strategist (Opus, on-demand)
├── Data Scientist (Sonnet)
│     ├── Data Analyst (Haiku)
│     └── Researcher (Sonnet)
├── Trader (Sonnet)
├── Dev (Sonnet)
└── QA (Haiku)
```

### Agent Roles

| Agent | Model | Role | Runs As |
|-------|-------|------|---------|
| CEO | Sonnet | Strategic oversight, receives briefs, directs | Main session + heartbeat |
| Strategist | Opus | Architecture, parameter proposals, optimization reviews | On-demand subagent |
| Data Scientist | Sonnet | Data synthesis, P&L computation, dashboard, notifications | Cron (post-cycle) |
| Data Analyst | Haiku | External API calls, data fetching, bias computation | Scripts (cron-triggered) |
| Researcher | Sonnet | Market research, opportunity discovery, reports | Cron (weekly) |
| Trader | Sonnet | Trade execution, position monitoring, entry/exit | Cron (cycle modes) |
| Dev | Sonnet | Code implementation, takes specs, produces code | Pipeline (spawned) |
| QA | Haiku | Code review, test execution, validation | Pipeline (spawned) |

---

## Part 2: Final Ownership Map

### 2.1 Agent → Scripts Ownership

| Agent | Scripts Owned |
|-------|---------------|
| **CEO** | `ruppert_cycle.py` (orchestration only — delegates to Trader) |
| **Strategist** | `bot/strategy.py`, `edge_detector.py`, `optimizer.py` |
| **Data Scientist** | `data_agent.py`, `capital.py`, `dashboard/api.py`, `logger.py` |
| **Data Analyst** | `ghcnd_client.py`, `openmeteo_client.py`, `kalshi_client.py`, `ws_feed.py`, `fetch_smart_money.py`, `bot/wallet_updater.py` |
| **Researcher** | `research_agent.py` (NEW), `market_scanner.py` (NEW) |
| **Trader** | `trader.py`, `post_trade_monitor.py`, `position_monitor.py`, `position_tracker.py`, `main.py`, `crypto_15m.py`, `crypto_client.py`, `crypto_long_horizon.py` |
| **Dev** | Pipeline only — no persistent scripts |
| **QA** | Pipeline only — no persistent scripts |

### 2.2 Agent → Truth Files Ownership

| Agent | Truth Files (Exclusive Write) | Other Agents' Access |
|-------|-------------------------------|---------------------|
| **CEO** | `state.json` | Read: all |
| **Strategist** | `config.py` params (via proposals), `logs/optimizer_proposals_*.md` | Read: CEO |
| **Data Scientist** | `pnl_cache.json`, `pending_alerts.json`, `data_audit_state.json`, `deposits.json`, `trades_*.jsonl` (via logger), `logs/dashboard/`, notifications | Read: CEO, Trader, dashboard |
| **Data Analyst** | `price_cache.json`, `ghcnd_bias_cache.json`, `crypto_smart_money.json`, `smart_money_wallets.json` | Read: Trader, Data Scientist |
| **Researcher** | `research_reports/`, `opportunities_backlog.json` | Read: CEO, Strategist |
| **Trader** | `tracked_positions.json`, `logs/executions/` | Read: Data Scientist |
| **Dev** | None | N/A |
| **QA** | None | N/A |

---

## Part 3: Core Architectural Rules

1. **Scripts append to raw event logs only — never mutate truth files**
   - Scripts produce facts: "trade executed", "price fetched", "exit triggered"
   - Agent synthesizes facts into truth

2. **Each truth file has exactly one owner agent — no shared writes**
   - Race conditions eliminated by design
   - Clear accountability

3. **Dashboard is read-only — Data Scientist owns it, never writes truth files**
   - Dashboard renders Data Scientist's truth files
   - User actions (approve/pass) → event logs → Data Scientist processes

4. **Notifications (`pending_alerts.json`) owned exclusively by Data Scientist**
   - Scripts log events to `events_*.jsonl`
   - Data Scientist synthesizes events → decides what's alertworthy → writes alerts
   - Heartbeat reads alerts → forwards to David

5. **Scripts communicate upward via event logs — agents synthesize**
   - No script ever directly notifies David
   - No script ever computes aggregate state

6. **Agents run as cron jobs — scheduled after their dependent scripts complete**
   - Clear execution order
   - No polling loops

7. **`deposits.json` writes require David's explicit authorization**
   - Only Data Scientist writes, only with David's approval

8. **CEO receives briefs — does not monitor scripts or poll logs directly**
   - Sub-agents push briefs to CEO
   - CEO makes strategic decisions, presents to David

---

## Part 4: Complete Codebase Audit

### 4.1 Current File Inventory with Ownership Assignment

| Current Path | New Owner | Violations Found | Notes |
|--------------|-----------|------------------|-------|
| `ruppert_cycle.py` | CEO (orchestration), delegates to Trader | ❌ Writes to `pending_alerts.json`, `state.json` directly | Must delegate to Data Scientist for alerts |
| `trader.py` | Trader | ✅ Clean — uses logger.py | No violations |
| `main.py` | Trader | ✅ Clean — scanner orchestration | No violations |
| `data_agent.py` | Data Scientist | ✅ Clean — proper owner | No violations |
| `capital.py` | Data Scientist | ⚠️ Reads `pnl_cache.json` | Correct — read-only |
| `logger.py` | Data Scientist | ✅ Clean — shared utility | Correct owner for trade logs |
| `bot/strategy.py` | Strategist | ✅ Clean — pure computation | No violations |
| `edge_detector.py` | Strategist | ✅ Clean — pure computation | No violations |
| `optimizer.py` | Strategist | ✅ Clean — writes own proposals | No violations |
| `ghcnd_client.py` | Data Analyst | ✅ Clean — writes own cache | No violations |
| `openmeteo_client.py` | Data Analyst | ✅ Clean — pure computation + cache | No violations |
| `kalshi_client.py` | Data Analyst | ✅ Clean — API wrapper | No violations |
| `ws_feed.py` | Data Analyst | ⚠️ Routes to position_tracker | Correct delegation |
| `fetch_smart_money.py` | Data Analyst | ✅ Writes `crypto_smart_money.json` | No violations |
| `bot/wallet_updater.py` | Data Analyst | ✅ Writes `smart_money_wallets.json` | No violations |
| `post_trade_monitor.py` | Trader | ❌ Writes to `pending_alerts.json`, `pnl_cache.json` | Must log events, not write truth |
| `position_monitor.py` | Trader | ❌ Writes to `pending_alerts.json`, `pnl_cache.json` | Must log events, not write truth |
| `position_tracker.py` | Trader | ✅ Writes `tracked_positions.json` | Correct owner |
| `crypto_15m.py` | Trader | ✅ Writes to trade logs via logger | No violations |
| `crypto_client.py` | Trader | ✅ Pure computation | No violations |
| `crypto_long_horizon.py` | Trader | ✅ Uses logger for trades | No violations |
| `dashboard/api.py` | Data Scientist | ❌ Writes to `highconviction_*.jsonl` | Must be read-only |
| `market_cache.py` | Data Analyst | ✅ In-memory cache | No violations |
| `noaa_client.py` | Data Analyst | ✅ Pure API wrapper | No violations |
| `config.py` | Strategist (proposals) | ⚠️ Static file | Changes via Dev pipeline |

### 4.2 Violations Requiring Fixes

| File | Violation | Fix Required |
|------|-----------|--------------|
| `ruppert_cycle.py` | Directly calls `push_alert()` 15+ times | Replace with `log_event()` |
| `ruppert_cycle.py` | Directly writes `state.json` | Move to Data Scientist |
| `post_trade_monitor.py` | Calls `push_alert()` 5+ times | Replace with `log_event()` |
| `post_trade_monitor.py` | Calls `_update_pnl_cache()` | Replace with event: `TRADE_SETTLED` |
| `position_monitor.py` | Calls `push_alert()` 4+ times | Replace with `log_event()` |
| `position_monitor.py` | Calls `_update_pnl_cache()` | Replace with event: `TRADE_SETTLED` |
| `dashboard/api.py` | Writes `highconviction_*.jsonl` | Replace with `log_event()` |

### 4.3 Files to Create

| File | Owner | Purpose |
|------|-------|---------|
| `research_agent.py` | Researcher | Market research orchestration |
| `market_scanner.py` | Researcher | New opportunity discovery |
| `agents/data_scientist/synthesizer.py` | Data Scientist | Event → truth file synthesis |
| `agents/data_scientist/notifier.py` | Data Scientist | Alert generation logic |
| `agents/trader/executor.py` | Trader | Trade execution wrapper |
| `agents/ceo/brief_generator.py` | CEO | Brief compilation |

---

## Part 5: New Folder Structure Design

### 5.1 Proposed Structure

```
ruppert-tradingbot-demo/
├── agents/
│   ├── ceo/
│   │   ├── __init__.py
│   │   ├── brief_generator.py         # Compiles briefs from sub-agent data
│   │   └── orchestrator.py             # Cycle dispatch logic (thin wrapper)
│   │
│   ├── strategist/
│   │   ├── __init__.py
│   │   ├── strategy.py                 # MOVED from bot/strategy.py
│   │   ├── edge_detector.py            # MOVED from root
│   │   └── optimizer.py                # MOVED from root
│   │
│   ├── data_scientist/
│   │   ├── __init__.py
│   │   ├── data_agent.py               # MOVED from root
│   │   ├── synthesizer.py              # NEW: event → truth synthesis
│   │   ├── notifier.py                 # NEW: alert generation
│   │   ├── capital.py                  # MOVED from root
│   │   └── logger.py                   # MOVED from root
│   │
│   ├── data_analyst/
│   │   ├── __init__.py
│   │   ├── ghcnd_client.py             # MOVED from root
│   │   ├── openmeteo_client.py         # MOVED from root
│   │   ├── kalshi_client.py            # MOVED from root
│   │   ├── noaa_client.py              # MOVED from root (if exists)
│   │   ├── ws_feed.py                  # MOVED from root
│   │   ├── market_cache.py             # MOVED from root
│   │   ├── fetch_smart_money.py        # MOVED from root
│   │   └── wallet_updater.py           # MOVED from bot/
│   │
│   ├── researcher/
│   │   ├── __init__.py
│   │   ├── research_agent.py           # NEW
│   │   └── market_scanner.py           # NEW
│   │
│   └── trader/
│       ├── __init__.py
│       ├── trader.py                   # MOVED from root
│       ├── executor.py                 # NEW: unified execution wrapper
│       ├── post_trade_monitor.py       # MOVED from root
│       ├── position_monitor.py         # MOVED from root
│       ├── position_tracker.py         # MOVED from root
│       ├── main.py                     # MOVED from root (scanner dispatch)
│       ├── crypto_15m.py               # MOVED from root
│       ├── crypto_client.py            # MOVED from root
│       └── crypto_long_horizon.py      # MOVED from root
│
├── config/
│   ├── config.py                       # MOVED from root
│   ├── secrets/                        # MOVED from ../secrets (or symlinked)
│   └── mode.json                       # MOVED from root
│
├── logs/
│   ├── raw/                            # Script-written event logs
│   │   ├── events_YYYY-MM-DD.jsonl     # NEW: unified event log
│   │   ├── cycle_log.jsonl             # MOVED from logs/
│   │   ├── decisions_15m.jsonl         # MOVED from logs/
│   │   └── activity_*.log              # MOVED from logs/
│   │
│   ├── truth/                          # Agent-owned truth files
│   │   ├── state.json                  # CEO owned
│   │   ├── pnl_cache.json              # Data Scientist owned
│   │   ├── pending_alerts.json         # Data Scientist owned
│   │   ├── data_audit_state.json       # Data Scientist owned
│   │   ├── deposits.json               # Data Scientist owned
│   │   ├── tracked_positions.json      # Trader owned
│   │   ├── price_cache.json            # Data Analyst owned
│   │   ├── ghcnd_bias_cache.json       # Data Analyst owned
│   │   ├── crypto_smart_money.json     # Data Analyst owned
│   │   └── smart_money_wallets.json    # Data Analyst owned
│   │
│   ├── trades/                         # Trade logs (Data Scientist writes via logger)
│   │   └── trades_YYYY-MM-DD.jsonl
│   │
│   ├── audits/                         # Audit reports
│   │   └── data_audit_YYYY-MM-DD.json
│   │
│   ├── proposals/                      # Strategist proposals
│   │   └── optimizer_proposals_YYYY-MM-DD.md
│   │
│   ├── executions/                     # Trader execution logs
│   │   └── execution_YYYY-MM-DD.jsonl
│   │
│   └── archive/                        # Rotated old logs
│       └── archive-pre-2026-03-26/
│
├── research/                           # Researcher outputs
│   ├── reports/
│   │   └── report_YYYY-MM-DD.md
│   └── opportunities_backlog.json
│
├── dashboard/
│   ├── api.py                          # MODIFIED: read-only
│   ├── static/
│   └── templates/
│
├── scripts/                            # Shared utilities (no agent owner)
│   ├── __init__.py
│   ├── utils.py                        # Common helpers
│   └── event_logger.py                 # log_event() implementation
│
├── docs/
│   ├── AGENT_OWNERSHIP_ARCHITECTURE.md # This file
│   └── PIPELINE.md                     # Dev/QA pipeline docs
│
├── ruppert_cycle.py                    # Entry point (thin — delegates to agents/)
├── requirements.txt
└── README.md
```

### 5.2 Migration Mapping (Current → New)

| Current Path | New Path |
|--------------|----------|
| `ruppert_cycle.py` | `ruppert_cycle.py` (keep at root as entry point) |
| `trader.py` | `agents/trader/trader.py` |
| `main.py` | `agents/trader/main.py` |
| `post_trade_monitor.py` | `agents/trader/post_trade_monitor.py` |
| `position_monitor.py` | `agents/trader/position_monitor.py` |
| `position_tracker.py` | `agents/trader/position_tracker.py` |
| `crypto_15m.py` | `agents/trader/crypto_15m.py` |
| `crypto_client.py` | `agents/trader/crypto_client.py` |
| `crypto_long_horizon.py` | `agents/trader/crypto_long_horizon.py` |
| `data_agent.py` | `agents/data_scientist/data_agent.py` |
| `capital.py` | `agents/data_scientist/capital.py` |
| `logger.py` | `agents/data_scientist/logger.py` |
| `bot/strategy.py` | `agents/strategist/strategy.py` |
| `edge_detector.py` | `agents/strategist/edge_detector.py` |
| `optimizer.py` | `agents/strategist/optimizer.py` |
| `ghcnd_client.py` | `agents/data_analyst/ghcnd_client.py` |
| `openmeteo_client.py` | `agents/data_analyst/openmeteo_client.py` |
| `kalshi_client.py` | `agents/data_analyst/kalshi_client.py` |
| `ws_feed.py` | `agents/data_analyst/ws_feed.py` |
| `market_cache.py` | `agents/data_analyst/market_cache.py` |
| `fetch_smart_money.py` | `agents/data_analyst/fetch_smart_money.py` |
| `bot/wallet_updater.py` | `agents/data_analyst/wallet_updater.py` |
| `config.py` | `config/config.py` |
| `mode.json` | `config/mode.json` |
| `dashboard/api.py` | `dashboard/api.py` (stays, modified) |
| `logs/*.json` (truth) | `logs/truth/*.json` |
| `logs/trades_*.jsonl` | `logs/trades/trades_*.jsonl` |
| `logs/cycle_log.jsonl` | `logs/raw/cycle_log.jsonl` |

---

## Part 6: Implementation Spec for Dev

### Phase 1: Event Logger Foundation (PRIORITY 1)

**Objective:** Create unified event logging that scripts use instead of direct truth file writes.

#### 1.1 Create `scripts/event_logger.py`

```python
"""
event_logger.py — Unified event logging for all scripts.
Scripts call log_event() instead of writing to truth files.
Data Scientist synthesizes events into truth.
"""
import json
from datetime import datetime, date
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / 'logs' / 'raw'

def log_event(event_type: str, data: dict, source: str = None) -> None:
    """
    Append an event to today's event log.
    
    Args:
        event_type: Event category (e.g., 'TRADE_EXECUTED', 'EXIT_TRIGGERED', 'ALERT_CANDIDATE')
        data: Event payload (dict)
        source: Script name that generated the event (auto-detected if None)
    
    Event types:
        TRADE_EXECUTED     - Trade placed (ticker, side, size, contracts)
        EXIT_TRIGGERED     - Exit executed (ticker, side, pnl, rule)
        SETTLEMENT         - Market settled (ticker, result, pnl)
        CIRCUIT_BREAKER    - Circuit breaker tripped (reason, loss_today)
        SCAN_COMPLETE      - Scan cycle finished (mode, counts)
        ANOMALY_DETECTED   - Data issue found (check, detail)
        ALERT_CANDIDATE    - Potential alert (level, message)
        POSITION_UPDATE    - Position state changed (ticker, side, action)
        PRICE_UPDATE       - Significant price move (ticker, old, new)
        HIGHCONVICTION_ACTION - User approve/pass (ticker, action)
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    event = {
        'ts': datetime.now().isoformat(),
        'type': event_type,
        'source': source or _get_caller(),
        **data
    }
    
    log_path = LOGS_DIR / f'events_{date.today().isoformat()}.jsonl'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event) + '\n')


def _get_caller() -> str:
    """Auto-detect calling script name."""
    import inspect
    for frame in inspect.stack():
        filename = frame.filename
        if 'event_logger' not in filename and filename.endswith('.py'):
            return Path(filename).stem
    return 'unknown'
```

#### 1.2 Modify `ruppert_cycle.py` — Replace `push_alert()` calls

**Before:**
```python
def push_alert(level, message, ticker=None, pnl=None):
    alerts = []
    if ALERTS_FILE.exists():
        try: alerts = json.loads(ALERTS_FILE.read_text(encoding='utf-8'))
        except: pass
    alerts.append({...})
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding='utf-8')
```

**After:**
```python
from scripts.event_logger import log_event

def push_alert(level, message, ticker=None, pnl=None):
    """Log alert candidate event. Data Scientist decides if it's alertworthy."""
    log_event('ALERT_CANDIDATE', {
        'level': level,
        'message': message,
        'ticker': ticker,
        'pnl': pnl,
    })
```

**Other changes in `ruppert_cycle.py`:**

| Location | Current | Change To |
|----------|---------|-----------|
| `check_circuit_breaker()` | `push_alert('warning', cb['reason'])` | `log_event('CIRCUIT_BREAKER', {'reason': cb['reason'], 'loss_today': cb['loss_today']})` |
| `run_orphan_reconciliation()` | `push_alert('warning', _msg, ticker=_ticker)` | `log_event('ANOMALY_DETECTED', {'check': 'orphan_position', 'ticker': _ticker, 'detail': _msg})` |
| `run_position_check()` | `push_alert('warning', alert_msg, ...)` | `log_event('ALERT_CANDIDATE', {'level': 'warning', 'message': alert_msg, ...})` |
| `run_report_mode()` | `push_alert('optimizer', alert_msg)` | `log_event('ALERT_CANDIDATE', {'level': 'optimizer', 'message': alert_msg})` |
| `run_full_mode()` (scan notify) | `push_alert('warning', _scan_msg)` | `log_event('SCAN_COMPLETE', {'mode': 'full', 'summary': _scan_msg, ...})` |
| `save_state()` | Direct write to `state.json` | `log_event('STATE_UPDATE', {'traded_tickers': list(...), 'mode': mode})` + Data Scientist synthesizes |

#### 1.3 Modify `post_trade_monitor.py` — Replace direct writes

**Remove:**
- `_update_pnl_cache()` function (delete entirely)
- All calls to `push_alert()`

**Add:**
```python
from scripts.event_logger import log_event

# In check_settlements():
# Instead of: _update_pnl_cache(round(pnl, 2))
log_event('SETTLEMENT', {
    'ticker': ticker,
    'side': side,
    'result': result,
    'pnl': round(pnl, 2),
    'entry_price': entry_price,
    'exit_price': exit_price,
    'contracts': contracts,
})

# Instead of: push_alert('exit', f'...', ticker=ticker, pnl=pnl)
log_event('EXIT_TRIGGERED', {
    'ticker': ticker,
    'side': side,
    'rule': rule,
    'pnl': pnl,
    'price': cur_price,
    'contracts': pos_contracts,
})
```

#### 1.4 Modify `position_monitor.py` — Same pattern

Replace all `push_alert()` and `_update_pnl_cache()` calls with `log_event()`.

#### 1.5 Modify `dashboard/api.py` — Read-only

**Remove these endpoints' write operations:**

```python
# BEFORE (line ~400):
@app.post("/api/highconviction/approve")
async def approve_highconviction(req: Request):
    ...
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps({...}) + '\n')  # REMOVE THIS

# AFTER:
@app.post("/api/highconviction/approve")
async def approve_highconviction(req: Request):
    from scripts.event_logger import log_event
    body = await req.json()
    ticker = body.get('ticker', '')
    log_event('HIGHCONVICTION_ACTION', {'ticker': ticker, 'action': 'approve'})
    return {'status': 'pending', 'ticker': ticker}
```

Same for `/api/highconviction/pass`.

---

### Phase 2: Data Scientist Synthesizer (PRIORITY 2)

**Objective:** Data Scientist reads event logs and synthesizes truth files.

#### 2.1 Create `agents/data_scientist/synthesizer.py`

```python
"""
synthesizer.py — Reads event logs, synthesizes truth files.
Called by data_agent.py after each scan cycle.
"""
import json
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

LOGS_DIR = Path(__file__).parent.parent.parent / 'logs'
RAW_DIR = LOGS_DIR / 'raw'
TRUTH_DIR = LOGS_DIR / 'truth'

def read_today_events() -> list[dict]:
    """Read all events from today's event log."""
    events = []
    event_log = RAW_DIR / f'events_{date.today().isoformat()}.jsonl'
    if event_log.exists():
        for line in event_log.read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except:
                    pass
    return events


def synthesize_pnl_cache():
    """Recompute pnl_cache.json from trade logs."""
    trades_dir = LOGS_DIR / 'trades'
    closed_pnl = 0.0
    
    for path in sorted(trades_dir.glob('trades_*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                trade = json.loads(line)
                if trade.get('action') in ('exit', 'settle'):
                    pnl = trade.get('pnl') or trade.get('realized_pnl') or 0
                    closed_pnl += float(pnl)
            except:
                pass
    
    cache = {'closed_pnl': round(closed_pnl, 2)}
    _write_truth('pnl_cache.json', cache)
    return cache


def synthesize_alerts():
    """Process ALERT_CANDIDATE events → decide what goes to pending_alerts.json."""
    events = read_today_events()
    alert_events = [e for e in events if e.get('type') == 'ALERT_CANDIDATE']
    
    # Load existing alerts (avoid duplicates)
    alerts_file = TRUTH_DIR / 'pending_alerts.json'
    existing = []
    if alerts_file.exists():
        try:
            existing = json.loads(alerts_file.read_text(encoding='utf-8'))
        except:
            pass
    
    existing_keys = {(a.get('message', ''), a.get('ticker', '')) for a in existing}
    
    new_alerts = []
    for event in alert_events:
        key = (event.get('message', ''), event.get('ticker', ''))
        if key not in existing_keys:
            new_alerts.append({
                'level': event.get('level', 'info'),
                'message': event.get('message', ''),
                'ticker': event.get('ticker'),
                'pnl': event.get('pnl'),
                'timestamp': event.get('ts'),
            })
    
    if new_alerts:
        combined = existing + new_alerts
        _write_truth('pending_alerts.json', combined)
    
    return new_alerts


def synthesize_state():
    """Build state.json from STATE_UPDATE events."""
    events = read_today_events()
    state_events = [e for e in events if e.get('type') == 'STATE_UPDATE']
    
    if not state_events:
        return None
    
    # Use most recent state update
    latest = state_events[-1]
    state = {
        'traded_tickers': latest.get('traded_tickers', []),
        'last_cycle_ts': latest.get('ts'),
        'last_cycle_mode': latest.get('mode'),
    }
    _write_truth('state.json', state)
    return state


def synthesize_highconviction_state():
    """Process HIGHCONVICTION_ACTION events."""
    events = read_today_events()
    hc_events = [e for e in events if e.get('type') == 'HIGHCONVICTION_ACTION']
    
    approved = set()
    passed = set()
    
    # Load existing state
    approved_file = TRUTH_DIR / 'highconviction_approved.json'
    passed_file = TRUTH_DIR / 'highconviction_passed.json'
    
    if approved_file.exists():
        try:
            approved = set(json.loads(approved_file.read_text(encoding='utf-8')))
        except:
            pass
    
    if passed_file.exists():
        try:
            passed = set(json.loads(passed_file.read_text(encoding='utf-8')))
        except:
            pass
    
    for event in hc_events:
        ticker = event.get('ticker')
        action = event.get('action')
        if action == 'approve':
            approved.add(ticker)
        elif action == 'pass':
            passed.add(ticker)
    
    _write_truth('highconviction_approved.json', list(approved))
    _write_truth('highconviction_passed.json', list(passed))


def run_synthesis():
    """Run all synthesis operations. Called after each scan cycle."""
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    
    pnl = synthesize_pnl_cache()
    alerts = synthesize_alerts()
    state = synthesize_state()
    synthesize_highconviction_state()
    
    return {
        'pnl_cache': pnl,
        'new_alerts': len(alerts),
        'state_updated': state is not None,
    }


def _write_truth(filename: str, data):
    """Atomic write to truth file."""
    path = TRUTH_DIR / filename
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(path)
```

#### 2.2 Integrate into `data_agent.py`

Add to `run_post_scan_audit()`:

```python
# At the end of run_post_scan_audit():
try:
    from agents.data_scientist.synthesizer import run_synthesis
    synth_result = run_synthesis()
    log_activity(f'[DataAgent] Synthesis complete: {synth_result}')
except Exception as e:
    log_activity(f'[DataAgent] Synthesis failed: {e}')
```

---

### Phase 3: Directory Migration (PRIORITY 3)

**Objective:** Move files to new folder structure.

#### 3.1 Create Directory Structure

```bash
mkdir -p agents/{ceo,strategist,data_scientist,data_analyst,researcher,trader}
mkdir -p config
mkdir -p logs/{raw,truth,trades,audits,proposals,executions,archive}
mkdir -p research/reports
mkdir -p scripts
```

#### 3.2 Move Files

```bash
# Trader agent
mv trader.py agents/trader/
mv main.py agents/trader/
mv post_trade_monitor.py agents/trader/
mv position_monitor.py agents/trader/
mv position_tracker.py agents/trader/
mv crypto_15m.py agents/trader/
mv crypto_client.py agents/trader/
mv crypto_long_horizon.py agents/trader/

# Data Scientist agent
mv data_agent.py agents/data_scientist/
mv capital.py agents/data_scientist/
mv logger.py agents/data_scientist/

# Strategist agent
mv bot/strategy.py agents/strategist/
mv edge_detector.py agents/strategist/
mv optimizer.py agents/strategist/

# Data Analyst agent
mv ghcnd_client.py agents/data_analyst/
mv openmeteo_client.py agents/data_analyst/
mv kalshi_client.py agents/data_analyst/
mv ws_feed.py agents/data_analyst/
mv market_cache.py agents/data_analyst/
mv fetch_smart_money.py agents/data_analyst/
mv bot/wallet_updater.py agents/data_analyst/

# Config
mv config.py config/
mv mode.json config/

# Logs restructure
mv logs/*.json logs/truth/
mv logs/trades_*.jsonl logs/trades/
mv logs/cycle_log.jsonl logs/raw/
mv logs/decisions_15m.jsonl logs/raw/
mv logs/activity_*.log logs/raw/
mv logs/data_audit_*.json logs/audits/
mv logs/optimizer_proposals_*.md logs/proposals/
```

#### 3.3 Create `__init__.py` Files

Each agent directory needs an `__init__.py`:

```python
# agents/trader/__init__.py
from .trader import Trader
from .executor import execute_trade  # NEW
```

Similar for other agent directories.

#### 3.4 Update Import Paths

All files need import path updates. Pattern:

**Before:**
```python
from logger import log_trade, log_activity
from bot.strategy import should_enter
import config
```

**After:**
```python
from agents.data_scientist.logger import log_trade, log_activity
from agents.strategist.strategy import should_enter
from config import config
```

---

### Phase 4: Task Scheduler Updates

**Current Tasks (must update paths):**

| Task Name | Current Command | New Command |
|-----------|-----------------|-------------|
| Ruppert-Full-7AM | `python ruppert_cycle.py full` | Same (entry point unchanged) |
| Ruppert-Full-3PM | `python ruppert_cycle.py full` | Same |
| Ruppert-Check-10PM | `python ruppert_cycle.py check` | Same |
| Ruppert-Report-7AM | `python ruppert_cycle.py report` | Same |
| Ruppert-PostMonitor | `python post_trade_monitor.py` | `python -m agents.trader.post_trade_monitor` |
| Ruppert-PositionMonitor | `python position_monitor.py --persistent` | `python -m agents.trader.position_monitor --persistent` |
| Ruppert-WSFeed | `python ws_feed.py` | `python -m agents.data_analyst.ws_feed` |

**New Tasks to Add:**

| Task Name | Command | Schedule |
|-----------|---------|----------|
| Ruppert-Synthesize | `python -m agents.data_scientist.synthesizer` | After each cycle |
| Ruppert-Research | `python -m agents.researcher.research_agent` | Weekly (Sunday 8AM) |

---

### Phase 5: New Files to Create

#### 5.1 `scripts/utils.py`

```python
"""
utils.py — Shared utility functions.
No agent owner — pure utility.
"""
from datetime import datetime, date
from pathlib import Path

def ts() -> str:
    """Return current timestamp string."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def today_str() -> str:
    """Return today's date as ISO string."""
    return date.today().isoformat()

def get_project_root() -> Path:
    """Return project root directory."""
    return Path(__file__).parent.parent
```

#### 5.2 `agents/trader/executor.py`

```python
"""
executor.py — Unified trade execution wrapper.
All trade execution flows through here.
"""
from scripts.event_logger import log_event
from agents.data_scientist.logger import log_trade, log_activity
from agents.data_analyst.kalshi_client import KalshiClient
from config import config

DRY_RUN = getattr(config, 'DRY_RUN', True)


def execute_trade(opportunity: dict) -> dict:
    """
    Execute a trade and log appropriate events.
    
    Returns:
        {'success': bool, 'result': dict, 'error': str or None}
    """
    ticker = opportunity.get('ticker')
    side = opportunity.get('side')
    contracts = opportunity.get('contracts', 1)
    price = opportunity.get('scan_price') or opportunity.get('fill_price')
    size = opportunity.get('size_dollars', 0)
    
    if DRY_RUN:
        result = {'dry_run': True, 'status': 'simulated'}
        log_trade(opportunity, size, contracts, result)
        log_event('TRADE_EXECUTED', {
            'ticker': ticker,
            'side': side,
            'size': size,
            'contracts': contracts,
            'price': price,
            'dry_run': True,
        })
        return {'success': True, 'result': result, 'error': None}
    
    try:
        client = KalshiClient()
        result = client.place_order(ticker, side, price, contracts)
        log_trade(opportunity, size, contracts, result)
        log_event('TRADE_EXECUTED', {
            'ticker': ticker,
            'side': side,
            'size': size,
            'contracts': contracts,
            'price': price,
            'fill_price': result.get('fill_price'),
        })
        return {'success': True, 'result': result, 'error': None}
    except Exception as e:
        log_activity(f'[Executor] Trade failed for {ticker}: {e}')
        log_event('TRADE_FAILED', {
            'ticker': ticker,
            'side': side,
            'error': str(e),
        })
        return {'success': False, 'result': None, 'error': str(e)}
```

#### 5.3 `agents/ceo/brief_generator.py`

```python
"""
brief_generator.py — Compiles briefs for CEO from sub-agent data.
"""
import json
from datetime import date, datetime
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent.parent / 'logs'


def generate_morning_brief() -> dict:
    """Generate 7AM morning brief."""
    # Read P&L cache
    pnl_cache = LOGS_DIR / 'truth' / 'pnl_cache.json'
    pnl_data = {}
    if pnl_cache.exists():
        pnl_data = json.loads(pnl_cache.read_text(encoding='utf-8'))
    
    # Read today's trades
    trades_file = LOGS_DIR / 'trades' / f'trades_{date.today().isoformat()}.jsonl'
    trades = []
    if trades_file.exists():
        for line in trades_file.read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    trades.append(json.loads(line))
                except:
                    pass
    
    # Count by module
    by_module = {}
    for t in trades:
        mod = t.get('module', 'other')
        by_module[mod] = by_module.get(mod, 0) + 1
    
    return {
        'type': 'morning_brief',
        'date': date.today().isoformat(),
        'generated_at': datetime.now().isoformat(),
        'pnl': {
            'closed': pnl_data.get('closed_pnl', 0),
        },
        'trades_today': len(trades),
        'trades_by_module': by_module,
    }


def generate_scan_brief(mode: str, results: dict) -> dict:
    """Generate post-scan brief."""
    return {
        'type': 'scan_brief',
        'mode': mode,
        'generated_at': datetime.now().isoformat(),
        **results,
    }
```

#### 5.4 `agents/researcher/research_agent.py`

```python
"""
research_agent.py — Market research and opportunity discovery.
Runs weekly to find new trading opportunities.
"""
import json
from datetime import date, datetime
from pathlib import Path

RESEARCH_DIR = Path(__file__).parent.parent.parent / 'research'


def run_weekly_research():
    """Run weekly research scan for new opportunities."""
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    
    # TODO: Implement opportunity scanning
    # - Scan for new Kalshi series
    # - Analyze underserved markets
    # - Identify edge opportunities
    
    report = {
        'date': date.today().isoformat(),
        'generated_at': datetime.now().isoformat(),
        'new_opportunities': [],
        'market_analysis': {},
        'recommendations': [],
    }
    
    report_path = RESEARCH_DIR / 'reports' / f'report_{date.today().isoformat()}.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    
    return report


if __name__ == '__main__':
    result = run_weekly_research()
    print(f'Research complete: {result}')
```

---

## Part 7: Testing & Validation

### 7.1 Unit Tests for Event Logger

```python
# tests/test_event_logger.py
import tempfile
import json
from pathlib import Path
from scripts.event_logger import log_event

def test_log_event_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch LOGS_DIR
        import scripts.event_logger as el
        original_dir = el.LOGS_DIR
        el.LOGS_DIR = Path(tmpdir) / 'raw'
        
        try:
            log_event('TEST_EVENT', {'key': 'value'}, source='test')
            
            log_files = list(el.LOGS_DIR.glob('events_*.jsonl'))
            assert len(log_files) == 1
            
            content = log_files[0].read_text()
            event = json.loads(content.strip())
            assert event['type'] == 'TEST_EVENT'
            assert event['key'] == 'value'
        finally:
            el.LOGS_DIR = original_dir
```

### 7.2 Integration Test Checklist

| Test | Validates |
|------|-----------|
| Run `ruppert_cycle.py full` | Events logged to `events_*.jsonl` |
| Check `logs/truth/pending_alerts.json` | Data Scientist synthesized alerts |
| Check `logs/truth/state.json` | State updated by Data Scientist |
| Dashboard approve action | Event logged, not direct write |
| P&L accuracy | `pnl_cache.json` matches computed from trades |

---

## Part 8: Rollout Plan

### Week 1: Foundation
- [ ] Create `scripts/event_logger.py`
- [ ] Create directory structure
- [ ] Move files to new locations
- [ ] Update all import paths
- [ ] Create `__init__.py` files

### Week 2: Event Migration
- [ ] Modify `ruppert_cycle.py` — replace `push_alert()`
- [ ] Modify `post_trade_monitor.py` — replace direct writes
- [ ] Modify `position_monitor.py` — replace direct writes
- [ ] Create `agents/data_scientist/synthesizer.py`
- [ ] Test event → truth flow

### Week 3: Dashboard & Polish
- [ ] Modify `dashboard/api.py` — read-only
- [ ] Update Task Scheduler
- [ ] End-to-end testing
- [ ] Documentation update

### Week 4: New Agents
- [ ] Create `agents/researcher/research_agent.py`
- [ ] Create `agents/ceo/brief_generator.py`
- [ ] Create brief delivery pipeline
- [ ] Final validation

---

## Appendix A: Complete Event Types

| Event Type | Source | Data Fields |
|------------|--------|-------------|
| `TRADE_EXECUTED` | trader.py, crypto_15m.py | ticker, side, size, contracts, price, dry_run |
| `EXIT_TRIGGERED` | position_tracker.py, post_trade_monitor.py | ticker, side, rule, pnl, price |
| `SETTLEMENT` | post_trade_monitor.py, position_monitor.py | ticker, side, result, pnl, entry_price, exit_price |
| `CIRCUIT_BREAKER` | ruppert_cycle.py | reason, loss_today |
| `SCAN_COMPLETE` | ruppert_cycle.py | mode, weather_trades, crypto_trades, fed_trades |
| `ANOMALY_DETECTED` | data_agent.py, ruppert_cycle.py | check, detail, action |
| `ALERT_CANDIDATE` | any script | level, message, ticker, pnl |
| `STATE_UPDATE` | ruppert_cycle.py | traded_tickers, mode |
| `POSITION_UPDATE` | position_tracker.py | ticker, side, action, contracts |
| `PRICE_UPDATE` | ws_feed.py | ticker, old_price, new_price |
| `HIGHCONVICTION_ACTION` | dashboard/api.py | ticker, action |
| `TRADE_FAILED` | executor.py | ticker, side, error |

---

## Appendix B: Truth File Schemas

### `state.json` (CEO)
```json
{
  "traded_tickers": ["KXBTC-...", "KXHIGH-..."],
  "last_cycle_ts": "2026-03-28 15:00:00",
  "last_cycle_mode": "full"
}
```

### `pnl_cache.json` (Data Scientist)
```json
{
  "closed_pnl": 125.50,
  "open_pnl": 15.00
}
```

### `pending_alerts.json` (Data Scientist)
```json
[
  {
    "level": "warning",
    "message": "Circuit breaker tripped: daily loss limit",
    "ticker": null,
    "pnl": null,
    "timestamp": "2026-03-28T15:30:00"
  }
]
```

### `tracked_positions.json` (Trader)
```json
{
  "KXBTC-26MAR28-B87500": {
    "quantity": 10,
    "side": "yes",
    "entry_price": 45,
    "module": "crypto",
    "title": "BTC price band",
    "added_at": 1711648800,
    "exit_thresholds": [
      {"price": 95, "action": "sell_all", "rule": "95c_rule"}
    ]
  }
}
```

---

## Appendix C: Import Path Cheat Sheet

| Old Import | New Import |
|------------|------------|
| `from logger import log_trade` | `from agents.data_scientist.logger import log_trade` |
| `from bot.strategy import should_enter` | `from agents.strategist.strategy import should_enter` |
| `from kalshi_client import KalshiClient` | `from agents.data_analyst.kalshi_client import KalshiClient` |
| `from capital import get_capital` | `from agents.data_scientist.capital import get_capital` |
| `import config` | `from config import config` |
| `from edge_detector import analyze_market` | `from agents.strategist.edge_detector import analyze_market` |
| `from post_trade_monitor import load_open_positions` | `from agents.trader.post_trade_monitor import load_open_positions` |
| `import position_tracker` | `from agents.trader import position_tracker` |
| `from ws_feed import run` | `from agents.data_analyst.ws_feed import run` |

---

*Document complete. Dev: build from this spec. No follow-up questions should be needed.*
