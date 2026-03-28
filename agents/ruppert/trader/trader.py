"""
Trade Executor
Handles order placement with pre-trade checks.
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import log_trade, log_activity, send_telegram
from agents.ruppert.env_config import require_live_enabled, get_current_env
import config


def contracts_from_size(size_dollars: float, price_cents: float) -> int:
    """Convert a dollar size into a contract count at the given price in cents."""
    if price_cents <= 0:
        return 0
    price_dollars = price_cents / 100
    contracts = int(size_dollars / price_dollars)
    return max(1, contracts)


class Trader:
    def __init__(self, dry_run=True):
        self.client = KalshiClient()
        self.dry_run = dry_run  # If True, simulate trades without placing
        self.bankroll = self.client.get_balance()
        log_activity(f"Trader initialized. Balance: ${self.bankroll:.2f} | Dry run: {dry_run}")

    def refresh_balance(self):
        self.bankroll = self.client.get_balance()

    def execute_opportunity(self, opportunity):
        """
        Evaluate and execute a single trade opportunity.
        Returns True if trade was placed, False otherwise.
        """
        if get_current_env() == 'live':
            require_live_enabled()  # Raises RuntimeError if enabled=false in mode.json

        ticker = opportunity['ticker']
        side = opportunity['side']
        edge = opportunity['edge']

        log_activity(f"Evaluating: {ticker} | Edge: {edge:.1%} | Action: {opportunity['action']}")

        strategy_size = opportunity.get('strategy_size')
        if not strategy_size or strategy_size <= 0:
            log_activity(f"[Trader] ERROR: strategy_size missing or zero for {ticker} — skipping trade. Scanner did not route through strategy.py.")
            send_telegram(f"🚨 Trade skipped: {ticker} had no strategy_size. Scanner output broken — investigate immediately.")
            return False

        price_cents = opportunity['yes_price'] if side == 'yes' else (100 - opportunity['yes_price'])
        contracts = contracts_from_size(strategy_size, price_cents)
        if contracts <= 0:
            log_activity(f"  Skipped: strategy_size ${strategy_size:.2f} too small for {price_cents}¢ contract")
            return False
        size = strategy_size

        log_activity(f"  Placing {side.upper()} order: {contracts} contracts @ {price_cents}¢ (${size:.2f})")

        if self.dry_run:
            log_activity(f"  [DRY RUN] Would have placed order — skipping actual execution")
            opportunity['scan_contracts'] = contracts
            opportunity['fill_contracts'] = contracts
            opportunity['scan_price'] = price_cents
            opportunity['fill_price'] = price_cents
            log_trade(opportunity, size, contracts, {'dry_run': True, 'status': 'simulated'})
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
            return True

        try:
            result = self.client.place_order(
                ticker=ticker,
                side=side,
                price_cents=price_cents,
                count=contracts,
            )
            log_activity(f"  Order placed successfully: {result}")

            # Extract actual fill count from order result if available
            opportunity['scan_contracts'] = contracts
            filled = None
            if isinstance(result, dict):
                filled = result.get('filled_count') or result.get('count') or result.get('contracts_filled')
            fill_contracts = filled if filled is not None else contracts
            opportunity['fill_contracts'] = fill_contracts

            # Extract actual fill price from order result if available
            opportunity['scan_price'] = price_cents
            fill_price = None
            if isinstance(result, dict):
                fill_price = result.get('yes_price') or result.get('price') or result.get('fill_price')
            opportunity['fill_price'] = fill_price if fill_price is not None else price_cents

            log_trade(opportunity, size, fill_contracts, result)
            try:
                from agents.ruppert.trader import position_tracker
                position_tracker.add_position(
                    ticker=ticker,
                    quantity=fill_contracts,
                    side=side,
                    entry_price=opportunity['fill_price'],
                    module=opportunity.get('module', ''),
                    title=opportunity.get('title', ticker),
                )
            except Exception as e:
                log_activity(f"[Trader] Warning: could not register {ticker} in position tracker: {e}")
            self.bankroll -= size  # Update local balance tracking
            return True

        except Exception as e:
            log_activity(f"  Order failed: {e}")
            # Log the trade attempt even on failure so the exchange-side fill
            # is not invisible to the system (exception-safe trade logging).
            try:
                opportunity['scan_contracts'] = contracts
                opportunity['fill_contracts'] = 0
                opportunity['scan_price'] = price_cents
                opportunity['fill_price'] = price_cents
                log_trade(opportunity, size, 0, {'error': str(e), 'status': 'failed'})
            except Exception as log_err:
                log_activity(f"  [Trader] WARNING: log_trade also failed after order error: {log_err}")
            return False

    def execute_all(self, opportunities):
        """Execute all opportunities in order of edge size."""
        if not opportunities:
            log_activity("No opportunities to execute.")
            return 0

        executed = 0
        for opp in opportunities:
            if self.execute_opportunity(opp):
                executed += 1

        log_activity(f"Executed {executed}/{len(opportunities)} opportunities.")
        return executed
