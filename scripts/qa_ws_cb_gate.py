"""
QA script: WS Feed Circuit Breaker Gate
Tests all 5 pass criteria from ws-cb-gate-qa-2026-04-02.md
"""
import sys
import os
import json
import logging
import inspect
from pathlib import Path
from unittest.mock import patch, MagicMock

# Setup paths
_WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(_WORKSPACE))
_DEMO_ENV = _WORKSPACE / 'environments' / 'demo'
sys.path.insert(0, str(_DEMO_ENV))

# Capture logs
log_records = []

class ListHandler(logging.Handler):
    def emit(self, record):
        log_records.append(record)

root_logger = logging.getLogger()
root_logger.addHandler(ListHandler())
root_logger.setLevel(logging.DEBUG)

import agents.ruppert.trader.circuit_breaker as cb
import agents.ruppert.data_analyst.ws_feed as ws_feed

PASS = []
FAIL = []

def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  ✅ PASS: {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ FAIL: {name}{' — ' + detail if detail else ''}")

# ─── Check 1: Import has circuit_breaker ──────────────────────────────────────
print("\n[1] Import / CB reference check")
check("circuit_breaker imported in ws_feed",
      hasattr(ws_feed, 'circuit_breaker'))

# ─── Check 2: CB tripped → entry blocked ─────────────────────────────────────
print("\n[2] CB tripped → evaluate_crypto_entry() returns without trading")

trade_calls = []

# We need to patch deeply into evaluate_crypto_entry
# Patch: circuit_breaker.get_consecutive_losses → returns 3 (tripped)
# Patch: log_trade to detect if a trade was placed

with patch.object(cb, 'get_consecutive_losses', return_value=3) as mock_cb, \
     patch('agents.ruppert.data_analyst.ws_feed.circuit_breaker.get_consecutive_losses', return_value=3):

    # Patch all the imports inside evaluate_crypto_entry to avoid real calls
    mock_signal = {
        'price': 87000.0,
        'realized_hourly_vol': 0.005,
    }

    log_records.clear()

    with patch('agents.ruppert.trader.crypto_client.get_btc_signal', return_value=mock_signal), \
         patch('agents.ruppert.data_scientist.capital.get_capital', return_value=10000.0), \
         patch('agents.ruppert.data_scientist.capital.get_buying_power', return_value=9500.0), \
         patch('agents.ruppert.data_scientist.logger.get_daily_exposure', return_value=0.0), \
         patch('agents.ruppert.trader.utils.load_traded_tickers', return_value=set()), \
         patch('agents.ruppert.data_scientist.logger.log_trade') as mock_log_trade, \
         patch('agents.ruppert.data_scientist.logger.log_activity'), \
         patch('agents.ruppert.trader.utils.push_alert'):

        import config
        # Ensure threshold and advisory mode
        original_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N', None)
        original_adv = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY', None)
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_N = 3
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY = False

        # Call evaluate_crypto_entry for a BTC threshold ticker (T = threshold)
        # yes_ask=30 → market_prob=0.30, model should compute high prob for price near strike → big edge
        ws_feed.evaluate_crypto_entry('KXBTC-26APR02-T87500', 30, 28, '2026-04-02T18:00:00Z')

        # Restore config
        if original_n is not None:
            config.CRYPTO_DAILY_CIRCUIT_BREAKER_N = original_n
        else:
            del config.CRYPTO_DAILY_CIRCUIT_BREAKER_N
        if original_adv is not None:
            config.CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY = original_adv

    # Check: log_trade was NOT called (no trade placed)
    check("CB tripped: no trade placed", not mock_log_trade.called,
          f"log_trade was called {mock_log_trade.call_count} times")

    # Check: warning log was emitted
    cb_logs = [r for r in log_records if 'CB TRIPPED' in r.getMessage()]
    check("CB tripped: warning log emitted", len(cb_logs) > 0,
          f"Found CB logs: {[r.getMessage() for r in cb_logs]}")

# ─── Check 3: CB clear → entry proceeds normally ──────────────────────────────
print("\n[3] CB clear → entry proceeds to strategy gate")

log_records.clear()
with patch.object(cb, 'get_consecutive_losses', return_value=0), \
     patch('agents.ruppert.data_analyst.ws_feed.circuit_breaker.get_consecutive_losses', return_value=0):

    mock_signal = {
        'price': 87000.0,
        'realized_hourly_vol': 0.005,
    }

    decision_called = []

    def fake_should_enter(opp, *args, **kwargs):
        decision_called.append(True)
        return {'enter': False, 'reason': 'qa_test_block'}

    with patch('agents.ruppert.trader.crypto_client.get_btc_signal', return_value=mock_signal), \
         patch('agents.ruppert.data_scientist.capital.get_capital', return_value=10000.0), \
         patch('agents.ruppert.data_scientist.capital.get_buying_power', return_value=9500.0), \
         patch('agents.ruppert.data_scientist.logger.get_daily_exposure', return_value=0.0), \
         patch('agents.ruppert.trader.utils.load_traded_tickers', return_value=set()), \
         patch('agents.ruppert.strategist.strategy.should_enter', side_effect=fake_should_enter), \
         patch('agents.ruppert.data_scientist.logger.log_activity'):

        import config
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_N = 3
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY = False

        ws_feed.evaluate_crypto_entry('KXBTC-26APR02-T87500', 30, 28, '2026-04-02T18:00:00Z')

    # CB clear → should_enter should have been called (entry reached strategy gate)
    check("CB clear: entry reaches strategy gate (should_enter called)",
          len(decision_called) > 0,
          "should_enter was never called — entry was blocked before strategy gate")

    # No CB TRIPPED log
    cb_logs = [r for r in log_records if 'CB TRIPPED' in r.getMessage()]
    check("CB clear: no CB TRIPPED log", len(cb_logs) == 0)

# ─── Check 4: Exits unaffected by CB ─────────────────────────────────────────
print("\n[4] _safe_check_exits has no CB gate")

source = inspect.getsource(ws_feed._safe_check_exits)
check("_safe_check_exits: no circuit_breaker reference",
      'circuit_breaker' not in source,
      f"Found 'circuit_breaker' in _safe_check_exits source")

# Also check position_tracker is called directly
check("_safe_check_exits: calls position_tracker.check_exits",
      'position_tracker.check_exits' in source)

# ─── Check 5: Per-module isolation ────────────────────────────────────────────
print("\n[5] Per-module isolation: BTC CB tripped should not block ETH")

log_records.clear()
call_log = {}

def fake_get_losses(module):
    # BTC tripped, ETH clear
    if 'btc' in module:
        return 3
    return 0

with patch('agents.ruppert.data_analyst.ws_feed.circuit_breaker.get_consecutive_losses',
           side_effect=fake_get_losses):

    mock_btc_signal = {'price': 87000.0, 'realized_hourly_vol': 0.005}
    mock_eth_signal = {'price': 3500.0, 'realized_hourly_vol': 0.006}

    entered_modules = []

    def fake_should_enter_2(opp, *args, **kwargs):
        entered_modules.append(opp.get('module'))
        return {'enter': False, 'reason': 'qa_isolation_block'}

    with patch('agents.ruppert.trader.crypto_client.get_btc_signal', return_value=mock_btc_signal), \
         patch('agents.ruppert.trader.crypto_client.get_eth_signal', return_value=mock_eth_signal), \
         patch('agents.ruppert.data_scientist.capital.get_capital', return_value=10000.0), \
         patch('agents.ruppert.data_scientist.capital.get_buying_power', return_value=9500.0), \
         patch('agents.ruppert.data_scientist.logger.get_daily_exposure', return_value=0.0), \
         patch('agents.ruppert.trader.utils.load_traded_tickers', return_value=set()), \
         patch('agents.ruppert.strategist.strategy.should_enter', side_effect=fake_should_enter_2), \
         patch('agents.ruppert.data_scientist.logger.log_activity'):

        import config
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_N = 3
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY = False

        # BTC tick (CB tripped) — should be blocked
        ws_feed.evaluate_crypto_entry('KXBTC-26APR02-T87500', 30, 28, '2026-04-02T18:00:00Z')
        # ETH tick (CB clear) — should proceed
        ws_feed.evaluate_crypto_entry('KXETH-26APR02-T3500', 30, 28, '2026-04-02T18:00:00Z')

    btc_blocked = not any('btc' in (m or '') for m in entered_modules)
    eth_passed = any('eth' in (m or '') for m in entered_modules)
    check("Per-module: BTC CB tripped blocks BTC entry", btc_blocked,
          f"entered_modules={entered_modules}")
    check("Per-module: ETH CB clear allows ETH entry", eth_passed,
          f"entered_modules={entered_modules}")

# ─── Check 6: CB gate exception is non-fatal (fail-open) ─────────────────────
print("\n[6] CB gate exception → fail-open, function continues")

log_records.clear()
entered_after_exception = []

def fake_get_losses_raises(module):
    raise ValueError("Simulated CB state read failure")

def fake_should_enter_3(opp, *args, **kwargs):
    entered_after_exception.append(True)
    return {'enter': False, 'reason': 'qa_fail_open_block'}

with patch('agents.ruppert.data_analyst.ws_feed.circuit_breaker.get_consecutive_losses',
           side_effect=fake_get_losses_raises):

    mock_signal = {'price': 87000.0, 'realized_hourly_vol': 0.005}

    with patch('agents.ruppert.trader.crypto_client.get_btc_signal', return_value=mock_signal), \
         patch('agents.ruppert.data_scientist.capital.get_capital', return_value=10000.0), \
         patch('agents.ruppert.data_scientist.capital.get_buying_power', return_value=9500.0), \
         patch('agents.ruppert.data_scientist.logger.get_daily_exposure', return_value=0.0), \
         patch('agents.ruppert.trader.utils.load_traded_tickers', return_value=set()), \
         patch('agents.ruppert.strategist.strategy.should_enter', side_effect=fake_should_enter_3), \
         patch('agents.ruppert.data_scientist.logger.log_activity'):

        import config
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_N = 3
        config.CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY = False

        try:
            ws_feed.evaluate_crypto_entry('KXBTC-26APR02-T87500', 30, 28, '2026-04-02T18:00:00Z')
            crashed = False
        except Exception as e:
            crashed = True
            print(f"    Exception propagated: {e}")

    check("CB exception: function does not crash", not crashed)

    cb_warn_logs = [r for r in log_records if 'CB gate failed' in r.getMessage()]
    check("CB exception: warning log emitted", len(cb_warn_logs) > 0,
          f"Found: {[r.getMessage() for r in cb_warn_logs]}")

    check("CB exception: fail-open (entry reaches strategy gate)",
          len(entered_after_exception) > 0,
          "should_enter was never called — function did not continue past CB exception")

# ─── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"  QA RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
print(f"{'='*55}")
for name in PASS:
    print(f"  ✅ {name}")
for name in FAIL:
    print(f"  ❌ {name}")
print()

sys.exit(0 if not FAIL else 1)
