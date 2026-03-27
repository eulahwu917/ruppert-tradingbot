# Architect Proposal: End-to-End Testing & Code Quality Framework

**Date:** 2026-03-27
**Author:** Architect Agent (Opus)
**Status:** PROPOSAL — awaiting David's review

---

## Executive Summary

Ruppert has shipped ~15 bugs in 2 weeks. The existing QA infrastructure (17 static checks in qa_self_test.py, monthly cadence) catches none of the bug classes that actually cost money: API contract violations, behavioral edge cases, mode handling, and architectural drift. This proposal designs a 4-layer testing framework that would have caught every bug found to date — and prevents future classes.

**The core problem:** Each module evolved independently with no shared contract enforcement. Testing is manual (Opus reads files) rather than automated (code tests code). The system has no pre-deploy gate.

---

## Bug Taxonomy & Test Coverage Matrix

| Bug Class | Examples | Current Coverage | Proposed Layer |
|-----------|----------|-----------------|----------------|
| API Contract | yes_ask=null from list endpoint, missing orderbook enrichment | NONE | Layer 1: Contract Tests |
| Behavioral/Logic | Mode fallthrough, Kelly div-by-zero, dedup in-memory only | NONE | Layer 2: Unit/Behavioral Tests |
| Architectural Drift | Modules bypassing strategy.py, raw requests vs KalshiClient | NONE | Layer 3: Static Analysis |
| Integration | Wrong data flowing end-to-end, position reconciliation | NONE | Layer 4: Integration Tests |
| Config/Secrets | Missing NOAA token, missing GHCND stations | Partial (qa_self_test) | Layer 1 (enhanced) |

---

## Layer 1: Contract & Invariant Tests

**File:** `tests/test_contracts.py`
**When:** Pre-deploy (every commit), scheduled daily
**Dependencies:** None (no API calls)

### 1.1 Kalshi Price Contract

Every module that touches Kalshi market data MUST get prices via `KalshiClient.get_markets()` or `KalshiClient.get_market()` — never raw `requests.get()` to the list endpoint.

```python
def test_no_raw_kalshi_market_fetch():
    """
    STATIC: Scan all scanner modules for raw requests.get() calls to
    the Kalshi markets endpoint. Only kalshi_client.py may do this.

    Catches: Crypto/Econ/Geo using raw requests (March 26-27 bugs)
    """
    KALSHI_URL_PATTERN = r'api\.elections\.kalshi\.com.*?/markets'
    ALLOWED_FILES = {'kalshi_client.py', 'kalshi_market_search.py'}
    # Scan all .py files, flag any that hit the Kalshi API directly

def test_orderbook_enrichment_present():
    """
    For every code path that reads yes_ask/no_ask from a market dict,
    verify the market was fetched via a method that enriches orderbook.

    Catches: yes_ask always null from list endpoint
    """

def test_price_fields_never_none_after_fetch():
    """
    After KalshiClient.get_markets() returns, every market dict must have
    yes_ask and no_ask as integers (not None). Markets with null prices
    must be filtered out before reaching scanners.
    """
```

### 1.2 Signal Contract

Every module must produce signals matching the strategy.py contract.

```python
REQUIRED_SIGNAL_FIELDS = {
    'edge': float, 'win_prob': float, 'confidence': float,
    'hours_to_settlement': float, 'module': str, 'vol_ratio': float,
}

def test_weather_signal_contract():
    """Verify _opp_to_signal() output has all required fields with correct types."""

def test_crypto_signal_contract():
    """Verify crypto signal dict before should_enter() has all required fields."""

def test_econ_signal_contract():
    """Verify econ signal dict has all required fields."""

def test_geo_signal_contract():
    """Verify geo opportunity dict can be converted to valid signal."""
```

### 1.3 Config Invariants

```python
def test_all_modules_have_min_edge():
    """Every module referenced in strategy.MIN_EDGE must have a config constant."""

def test_config_constants_in_range():
    """
    Extended version of existing qa_self_test range checks.
    - MIN_EDGE values: 0.05 <= x <= 0.50
    - DAILY_CAP_PCT values: 0.01 <= x <= 0.20
    - MAX_POSITION_PCT: 0.005 <= x <= 0.05
    - Kelly tiers: monotonically increasing with confidence
    """

def test_no_hardcoded_fallback_prices():
    """
    Scan for patterns like `or 50`, `or 0`, `yes_ask or 50` that mask
    null API responses with silent defaults. These should raise, not default.

    Catches: yes_ask always defaulting to 50 when API returns null
    """
```

---

## Layer 2: Unit & Behavioral Tests

**File:** `tests/test_strategy.py`, `tests/test_cycle_modes.py`, `tests/test_kelly.py`
**When:** Pre-deploy (every commit)
**Dependencies:** None (pure logic, no API calls)

### 2.1 Kelly Formula Edge Cases (`tests/test_kelly.py`)

```python
def test_kelly_win_prob_1_0():
    """win_prob=1.0 must NOT zero out. Should clamp to 0.999.
    Catches: Kelly divide-by-zero at 100% NOAA confidence."""
    size = calculate_position_size(edge=0.30, win_prob=1.0, capital=1000)
    assert size > 0, "Kelly zeroed on win_prob=1.0 — highest-edge trade killed"

def test_kelly_win_prob_0_999():
    """win_prob=0.999 should produce a valid (large) position."""

def test_kelly_negative_edge():
    """Negative edge must return 0."""

def test_kelly_zero_capital():
    """Zero capital must return 0."""

def test_kelly_fraction_tiers_monotonic():
    """Higher confidence must always yield >= kelly fraction vs lower."""
    fracs = [kelly_fraction_for_confidence(c) for c in [0.30, 0.45, 0.55, 0.65, 0.75, 0.85]]
    assert fracs == sorted(fracs), "Kelly tiers not monotonically increasing"
```

### 2.2 Mode Handling (`tests/test_cycle_modes.py`)

```python
VALID_MODES = {'full', 'check', 'smart', 'econ_prescan', 'weather_only', 'crypto_only', 'report'}

def test_all_modes_have_explicit_handler():
    """
    Parse ruppert_cycle.py and verify every VALID_MODE has an explicit
    `if MODE == 'xxx':` block or falls into 'full' after all early exits.

    Catches: Mode fallthrough — econ_prescan/weather_only/crypto_only
    silently running as full cycles (March 26 bug)
    """
    source = Path('ruppert_cycle.py').read_text()
    for mode in VALID_MODES - {'full'}:  # 'full' is the fallthrough
        assert f"MODE == '{mode}'" in source, f"Mode '{mode}' has no explicit handler"

def test_unknown_mode_raises():
    """An unrecognized mode should fail loudly, not silently run as 'full'."""
    # Parse ruppert_cycle.py for an explicit unknown mode check

def test_mode_exits_before_full_scan():
    """
    econ_prescan, weather_only, crypto_only must sys.exit(0) before
    reaching the full-mode scan steps. Verify via AST or text matching.
    """
```

### 2.3 Dedup Persistence (`tests/test_dedup.py`)

```python
def test_traded_tickers_loaded_from_log():
    """
    traded_tickers must be populated from today's trade log at startup,
    not starting empty. Verify the log-loading code path in ruppert_cycle.py.

    Catches: Cross-cycle dedup failure (March 26 bug)
    """

def test_exit_removes_from_traded_tickers():
    """
    action='exit' must discard ticker from traded_tickers so the bot
    can re-enter after a legitimate exit.
    """
```

### 2.4 Strategy Routing (`tests/test_strategy_routing.py`)

```python
def test_all_scanners_route_through_strategy():
    """
    Every scanner module that places trades must call should_enter()
    from bot/strategy.py. No module may compute its own position size.

    Catches: Crypto/Fed bypassing strategy.py entirely (Audit 5 bug)
    """
    SCANNER_FILES = [
        'main.py',           # run_weather_scan, run_crypto_scan
        'ruppert_cycle.py',  # econ_prescan trades
    ]
    for f in SCANNER_FILES:
        source = Path(f).read_text()
        if 'place_order' in source or 'log_trade' in source:
            assert 'should_enter' in source, f"{f} places trades without strategy gate"
```

---

## Layer 3: Static Analysis & Pattern Enforcement

**File:** `tests/test_patterns.py`
**When:** Pre-deploy (every commit)
**Dependencies:** None (AST/text analysis only)

### 3.1 Kalshi Client Monopoly

```python
def test_no_direct_kalshi_api_calls():
    """
    Only kalshi_client.py may import requests and hit api.elections.kalshi.com.
    All other files must use KalshiClient.

    Exception: kalshi_market_search.py (search helper that wraps KalshiClient).

    Catches: crypto_scanner.py using raw requests (found March 27)
    """
    ALLOWED = {'kalshi_client.py', 'kalshi_market_search.py'}
    for py_file in Path('.').glob('*.py'):
        if py_file.name in ALLOWED:
            continue
        source = py_file.read_text()
        assert 'api.elections.kalshi.com' not in source, \
            f"{py_file.name} makes direct Kalshi API calls — must use KalshiClient"
```

### 3.2 Direction Filter Enforcement

```python
def test_direction_filter_applied_before_trade():
    """
    Every trade execution path must check direction (YES/NO) matches the
    market analysis. No trade should go through with an unchecked direction.

    Catches: direction filter not enforced (caused loss on Mar 13)
    """
```

### 3.3 No Bare Exception Swallowing

```python
def test_no_bare_except_pass():
    """
    `except: pass` and `except Exception: pass` in trade-critical paths
    must be flagged. Silent failures in scanners mask broken API calls.
    """
    CRITICAL_FILES = ['ruppert_cycle.py', 'main.py', 'kalshi_client.py']
    for f in CRITICAL_FILES:
        source = Path(f).read_text()
        # Flag `except.*:\n\s+pass` patterns in trade/order code blocks
```

### 3.4 Confidence Field Propagation

```python
def test_confidence_field_reaches_logger():
    """
    From signal creation to log_trade(), the confidence field must be
    preserved. Verify log_trade's trade dict includes 'confidence'.

    Catches: confidence field silently dropped by logger (Audit finding)
    """
```

---

## Layer 4: Integration Tests (Live API, Sandboxed)

**File:** `tests/test_integration.py`
**When:** Daily scheduled run (not pre-deploy — requires API access)
**Dependencies:** Kalshi DEMO API credentials, network access

### 4.1 Kalshi Price Sanity

```python
def test_kalshi_orderbook_returns_prices():
    """
    Fetch a known active market via KalshiClient.get_markets().
    Verify yes_ask and no_ask are integers > 0.

    Catches: Orderbook enrichment regression
    """
    client = KalshiClient()
    markets = client.get_markets('KXBTC', status='open', limit=5)
    assert len(markets) > 0, "No BTC markets found"
    for m in markets:
        assert isinstance(m.get('yes_ask'), int) and m['yes_ask'] > 0
        assert isinstance(m.get('no_ask'), int) and m['no_ask'] > 0

def test_kalshi_balance_accessible():
    """Verify API authentication works and balance is readable."""

def test_kalshi_positions_parseable():
    """
    Verify get_positions() returns parseable objects (not SDK Pydantic errors).
    Catches: SDK deserialization failures that trigger raw HTTP fallback.
    """
```

### 4.2 End-to-End Scan (Dry Run)

```python
def test_weather_scan_dry_run():
    """
    Run full weather scan in dry-run mode. Verify:
    - No exceptions
    - Opportunities have valid price fields
    - Strategy decisions logged
    """

def test_crypto_scan_dry_run():
    """
    Run full crypto scan in dry-run mode. Verify:
    - Uses KalshiClient (not raw requests)
    - Prices are enriched (yes_ask > 0)
    - strategy.should_enter() called for each opportunity
    """

def test_econ_scan_dry_run():
    """Run econ scan, verify BLS/FRED data fetched and markets analyzed."""

def test_geo_scan_dry_run():
    """
    Run geo scan, verify market-first flow:
    1. Markets fetched first
    2. GDELT queried per market
    3. Stage 1 -> Stage 2 pipeline
    """
```

### 4.3 Cross-Module Consistency

```python
def test_all_modules_same_capital_source():
    """
    Every module must use get_capital() or get_computed_capital() for capital.
    No module should use client.get_balance() for sizing decisions.
    """

def test_exposure_reconciliation():
    """
    After a dry-run cycle, log-computed exposure and API-computed exposure
    must agree within 5% tolerance.
    """
```

---

## Layer 5: Pre-Deploy Gate

**File:** `pre_deploy_check.py`
**When:** Before every deployment (manually or via hook)
**Purpose:** Single script that runs all critical checks and blocks deploy on failure

```python
#!/usr/bin/env python
"""
Pre-deploy gate for Ruppert trading bot.
Exit 0 = safe to deploy, Exit 1 = BLOCKED.

Usage: python pre_deploy_check.py
"""

def run_gate():
    checks = [
        # Layer 1: Contract tests
        ("contract_tests", run_contract_tests),
        # Layer 2: Behavioral tests
        ("behavioral_tests", run_behavioral_tests),
        # Layer 3: Pattern enforcement
        ("pattern_enforcement", run_pattern_tests),
        # Quick smoke: import all modules
        ("import_smoke", run_import_smoke),
        # Syntax check all .py files
        ("syntax_check", run_syntax_check),
    ]

    failed = []
    for name, fn in checks:
        try:
            result = fn()
            if not result:
                failed.append(name)
        except Exception as e:
            failed.append(f"{name}: {e}")

    if failed:
        print(f"DEPLOY BLOCKED: {len(failed)} check(s) failed")
        for f in failed:
            print(f"  FAIL: {f}")
        sys.exit(1)

    print(f"ALL CLEAR: {len(checks)} checks passed")
    sys.exit(0)
```

---

## Additional Architectural Risks Identified

### Risk 1: crypto_scanner.py Still Uses Raw Requests

**Current state:** `crypto_scanner.py` (the standalone file, separate from `main.py:run_crypto_scan`) uses `requests.get()` directly to fetch Kalshi markets. While `main.py:run_crypto_scan()` was fixed to use `KalshiClient.get_markets()`, the standalone `crypto_scanner.py` file may still have the old pattern.

**Recommendation:** Delete `crypto_scanner.py` if it's dead code, or migrate it to KalshiClient. The pattern test (Layer 3) will catch this.

### Risk 2: best_bets_scanner.py Uses Raw Requests

**Current state:** `best_bets_scanner.py` uses raw `requests.get()` — same pattern that broke crypto/econ. If this scanner is ever connected to trade execution, it will have null prices.

**Recommendation:** Migrate to KalshiClient or mark as read-only/non-trading.

### Risk 3: Position Reconciliation Relies on Log File

**Current state:** `ruppert_cycle.py` loads `traded_tickers` from today's trade log. If the log file is corrupted, rotated, or the process crashes mid-write, dedup state is lost.

**Recommendation:** Add a persistent `state.json` file for cross-cycle state (traded_tickers, last_cycle_time, etc.) with atomic writes.

### Risk 4: No Type Safety on Market Dicts

**Current state:** Market data flows as untyped `dict` throughout the system. A field rename in Kalshi's API (e.g., `yes_ask` -> `yes_price`) would silently break everything with `None` defaults.

**Recommendation:** Define a `@dataclass Market` with required fields. Parse API responses into it at the boundary (kalshi_client.py). Fails fast on schema changes.

### Risk 5: timezone Inconsistency

**Current state:** `openmeteo_client` had a UTC vs local timezone bug (found in audit). Settlement time calculations use `datetime.now()` (local) in some places and `datetime.now(timezone.utc)` in others.

**Recommendation:** Add a pattern test: all `datetime.now()` calls must use `timezone.utc`. Local time only at display boundaries.

### Risk 6: ruppert_cycle.py Is a 655-Line Script, Not a Module

**Current state:** All cycle logic runs at module level (not in functions). This makes it impossible to unit test individual steps. The `if MODE == 'xxx':` blocks can't be invoked in isolation.

**Recommendation:** Refactor into `def run_cycle(mode: str)` with per-step functions. This unlocks testability for Layer 2 tests.

### Risk 7: No Circuit Breaker on Total Daily Loss

**Current state:** The bot checks daily deployment cap (70%) but has no loss-based circuit breaker. If every trade in a cycle loses, the next cycle will deploy the same amount.

**Recommendation:** Add a loss circuit breaker: if realized losses today exceed X% of capital, halt all trading until manual review.

---

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 hours)
- **`tests/test_patterns.py`** — Static analysis checks (Layers 1.1, 3.1, 3.2)
  - No raw Kalshi API calls outside kalshi_client.py
  - All scanners route through strategy.py
  - No hardcoded fallback prices in trade paths
- **`tests/test_kelly.py`** — Kelly edge cases (Layer 2.1)
  - win_prob=1.0, negative edge, zero capital
  - Tier monotonicity
- **`pre_deploy_check.py`** — Wire up as single entry point
- **Effort:** ~200 lines of test code

### Phase 2: Behavioral Tests (2-3 hours)
- **`tests/test_cycle_modes.py`** — Mode handling (Layer 2.2)
  - All modes have explicit handlers
  - Modes exit before full scan
  - Unknown mode fails loudly
- **`tests/test_contracts.py`** — Signal and config contracts (Layer 1.2, 1.3)
- **`tests/test_dedup.py`** — Dedup persistence (Layer 2.3)
- **Effort:** ~300 lines of test code

### Phase 3: Integration Tests (3-4 hours)
- **`tests/test_integration.py`** — Live API tests (Layer 4)
  - Kalshi price sanity
  - End-to-end dry-run scans
  - Cross-module consistency
- **Scheduled via Task Scheduler** — daily at 4am (before first trading cycle)
- **Effort:** ~250 lines of test code + Task Scheduler config

### Phase 4: Architectural Hardening (4-6 hours)
- **Refactor ruppert_cycle.py** into testable functions (Risk 6)
- **Add Market dataclass** in kalshi_client.py (Risk 4)
- **Migrate crypto_scanner.py** to KalshiClient (Risk 1)
- **Add state.json** for persistent cross-cycle state (Risk 3)
- **Effort:** Significant refactor, but unblocks all future testing

---

## File Structure

```
ruppert-tradingbot-demo/
  tests/
    __init__.py
    test_contracts.py      # Layer 1: API & signal contracts
    test_kelly.py          # Layer 2: Kelly formula edge cases
    test_cycle_modes.py    # Layer 2: Mode handling
    test_dedup.py          # Layer 2: Dedup persistence
    test_strategy_routing.py  # Layer 2: All trades go through strategy
    test_patterns.py       # Layer 3: Static pattern enforcement
    test_integration.py    # Layer 4: Live API integration
    conftest.py            # Shared fixtures (mock market dicts, signals)
  pre_deploy_check.py      # Layer 5: Single gate script
```

## Running

```bash
# Quick pre-deploy (Layers 1-3, no API):
python -m pytest tests/ -k "not integration" --tb=short

# Full suite including integration:
python -m pytest tests/ --tb=short

# Pre-deploy gate (pass/fail):
python pre_deploy_check.py
```

---

## Success Metrics

After implementation, every bug found this week would be caught:

| Bug | Caught By | When |
|-----|-----------|------|
| Raw requests to Kalshi list endpoint | test_no_direct_kalshi_api_calls | Pre-deploy |
| yes_ask=null from list endpoint | test_kalshi_orderbook_returns_prices | Daily integration |
| Mode fallthrough | test_all_modes_have_explicit_handler | Pre-deploy |
| Cross-cycle dedup | test_traded_tickers_loaded_from_log | Pre-deploy |
| Kelly div-by-zero at 1.0 | test_kelly_win_prob_1_0 | Pre-deploy |
| Geo backwards flow | test_geo_scan_dry_run (market-first) | Daily integration |
| Crypto bypassing strategy | test_all_scanners_route_through_strategy | Pre-deploy |
| Confidence dropped by logger | test_confidence_field_reaches_logger | Pre-deploy |
| NOAA token missing | test_config_constants_in_range (enhanced) | Pre-deploy |
| Direction filter not enforced | test_direction_filter_applied_before_trade | Pre-deploy |

**Target:** Zero production bugs from known classes. New classes get a regression test added within 24 hours.
