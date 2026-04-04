# WS mode retired 2026-03-31. Use ws_feed.py. This module is now polling-only.
"""
position_monitor.py — polling-only position monitor (WS mode retired 2026-03-31)

Architecture:
  - Poll mode: existing logic for settlement, exit, and position checks
  - WS mode stubs remain but raise RuntimeError — use ws_feed.py directly

Usage: python position_monitor.py
"""
import sys
import os
import json
import uuid
import asyncio
import argparse
import logging
import math
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# Windows asyncio fix — must be set before any asyncio calls
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

# Ensure environments/demo is on sys.path so ws.connection is importable
# regardless of the working directory (ws/ lives at environments/demo/ws/)
_DEMO_ENV_ROOT = _WORKSPACE_ROOT / 'environments' / 'demo'
if str(_DEMO_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ENV_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths
LOGS = _get_paths()['logs']
LOGS.mkdir(exist_ok=True)
LOGS_DIR = LOGS
TRADES_DIR = _get_paths()['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)

import config
from scripts.event_logger import log_event
DRY_RUN = getattr(config, 'DRY_RUN', True)  # module-level for smoke test; read fresh at call time inside functions

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import (
    log_trade, log_activity, acquire_exit_lock, release_exit_lock,
    normalize_entry_price, get_daily_exposure
)

logger = logging.getLogger(__name__)

# ─────────────────────────────── Constants ────────────────────────────────────

WS_ENABLED = False                   # WS mode retired 2026-03-31 — polling only
WS_EVENT_LOOP_DURATION = 840         # 14 minutes (Task Scheduler runs every 30 min)
POLL_BACKSTOP_INTERVAL = 300         # 5 min polling backstop inside WS loop

# CRYPTO_15M_SERIES removed — now imported from agents.ruppert.trader.utils (B5-DS-4)

# ─────────────────────────────── Helpers ──────────────────────────────────────

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# push_alert moved to agents.ruppert.trader.utils (2026-03-31)
from agents.ruppert.trader.utils import push_alert, CRYPTO_15M_SERIES  # B5-DS-4: CRYPTO_15M_SERIES canonical


# ─────────────────────────────── Position Loading ─────────────────────────────

def load_open_positions():
    """Load open positions from trade logs, filtering out exits/settlements.

    Scans a 365-day rolling window to capture long-horizon positions
    (monthly, quarterly, annual markets). Most files will not exist and
    are skipped cheaply via exists() check.
    """
    today = date.today()

    # Scan rolling 365-day window to capture long-horizon positions (monthly/annual).
    # Extended from 30 days — a 30-day window silently dropped positions entered
    # more than 30 days ago (e.g. annual markets). Most files don't exist; the
    # exists() check is cheap.
    logs_to_check = []
    for days_back in range(365):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")

    entries_by_key = {}
    exit_keys = set()

    for trade_log in logs_to_check:
        if not trade_log.exists():
            continue
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ticker = rec.get('ticker', '')
            side = rec.get('side', '')
            action = rec.get('action', 'buy')
            key = (ticker, side)
            if action in ('exit', 'settle'):
                exit_keys.add(key)
            else:
                entries_by_key[key] = rec

    return [rec for key, rec in entries_by_key.items() if key not in exit_keys]


# load_traded_tickers moved to agents.ruppert.trader.utils (2026-03-31)
from agents.ruppert.trader.utils import load_traded_tickers


# ─────────────────────────────── Settlement Handler ───────────────────────────

def _settle_single_ticker(ticker: str, result: str, pos: Optional[dict] = None):
    """
    Handle settlement for a single ticker.
    
    Args:
        ticker: Market ticker
        result: 'yes' or 'no' — settlement outcome
        pos: Position record (optional, will be looked up if not provided)
    """
    if pos is None:
        # Look up position from open positions
        positions = load_open_positions()
        for p in positions:
            if p.get('ticker') == ticker:
                pos = p
                break
    
    if pos is None:
        # No open position for this ticker — not an error, just nothing to settle
        return
    
    side = pos.get('side', '')
    entry_price = normalize_entry_price(pos)
    contracts = int(pos.get('contracts', 1) or 1)
    
    # Compute P&L based on settlement
    if side == 'yes':
        if result == 'yes':
            exit_price = 100
            pnl = (100 - entry_price) * contracts / 100
        else:
            exit_price = 1
            pnl = -(entry_price * contracts / 100)
    else:  # side == 'no'
        if result == 'no':
            exit_price = 100
            pnl = (100 - entry_price) * contracts / 100
        else:
            exit_price = 1
            pnl = -(entry_price * contracts / 100)
    
    # Write settle record
    log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
    settle_record = {
        "trade_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "date": str(date.today()),
        "ticker": ticker,
        "title": pos.get("title", ""),
        "side": side,
        "action": "settle",
        "action_detail": f"SETTLE {'WIN' if pnl > 0 else 'LOSS'} @ {exit_price}c",
        "source": "ws_settlement" if WS_ENABLED else "poll_settlement",
        "module": pos.get("module", ""),
        "settlement_result": result,
        "pnl": round(pnl, 2),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "contracts": contracts,
    }
    
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(settle_record) + '\n')
    except Exception as e:
        print(f"  [Settlement] JSONL write error for {ticker}: {e}")
        return
    
    log_event('SETTLEMENT', {
        'ticker': ticker,
        'side': side,
        'result': result,
        'pnl': round(pnl, 2),
        'entry_price': entry_price,
        'exit_price': exit_price,
        'contracts': contracts,
    })
    print(f"  [Settlement] {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}")
    push_alert('settle', f'SETTLED: {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}', ticker=ticker, pnl=pnl)


# ─────────────────────────────── Crypto Entry Evaluator ───────────────────────

def evaluate_crypto_entry(ticker: str, yes_ask: int, yes_bid: int, close_time: str = None):
    """
    Evaluate crypto market for entry based on WebSocket price tick.
    
    Called on each ticker update for crypto markets.
    Uses band_prob model to compute edge vs live price.
    """
    from agents.ruppert.trader.crypto_client import (
        get_btc_signal, get_eth_signal, get_xrp_signal, get_doge_signal,
        _band_probability, _t_cdf, ASSET_CONFIG, compute_composite_confidence
    )
    from agents.ruppert.strategist.strategy import should_enter, calculate_position_size
    from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
    
    # Parse series from ticker (KXBTC, KXETH, etc.)
    series = ticker.split('-')[0].upper()
    
    # Determine asset
    if 'BTC' in series:
        asset = 'BTC'
        signal = get_btc_signal()
    elif 'ETH' in series:
        asset = 'ETH'
        signal = get_eth_signal()
    elif 'XRP' in series:
        asset = 'XRP'
        signal = get_xrp_signal()
    elif 'DOGE' in series:
        asset = 'DOGE'
        signal = get_doge_signal()
    else:
        return  # Unknown asset
    
    current_price = signal['price']
    
    # Parse strike from ticker (e.g., KXBTC-26MAR28-B87500 → 87500)
    parts = ticker.split('-')
    if len(parts) < 3:
        return
    
    strike_part = parts[-1]
    strike_type = 'between'  # Default to band
    strike = None
    
    if strike_part.startswith('B'):
        try:
            strike = float(strike_part[1:])
        except ValueError:
            return
        strike_type = 'between'
    elif strike_part.startswith('T'):
        try:
            strike = float(strike_part[1:])
        except ValueError:
            return
        strike_type = 'greater' if strike > current_price else 'less'
    else:
        return
    
    # Get vol and compute sigma
    cfg = ASSET_CONFIG[asset]
    realized_vol = signal.get('realized_hourly_vol') or (cfg['hourly_vol_pct'] / 100)
    
    # Parse hours to settlement from close_time if provided
    hours_left = 4.0  # Default fallback
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            hours_left = max((close_dt - now).total_seconds() / 3600, 0.1)
        except Exception:
            pass
    
    sigma = current_price * realized_vol * math.sqrt(max(hours_left, 0.1))
    
    # Compute model probability
    if strike_type == 'between':
        band_step = cfg['band_step']
        low = strike - band_step / 2
        high = strike + band_step / 2
        model_prob = _band_probability(low, high, current_price, sigma)
    elif strike_type == 'greater':
        model_prob = 1.0 - _t_cdf(strike, current_price, sigma)
    else:  # less
        model_prob = _t_cdf(strike, current_price, sigma)
    
    # Market probability from ask
    market_prob = yes_ask / 100.0
    
    # Compute edge
    edge = model_prob - market_prob
    side = 'yes' if edge > 0 else 'no'
    
    # Check minimum edge threshold
    min_edge = getattr(config, 'CRYPTO_MIN_EDGE_THRESHOLD', 0.12)
    if abs(edge) < min_edge:
        return
    
    # Check if already traded
    traded_tickers = load_traded_tickers()
    if ticker in traded_tickers:
        return
    
    # Check daily cap
    capital = get_capital()
    daily_cap = capital * config.CRYPTO_DAILY_CAP_PCT
    try:
        current_exposure = get_daily_exposure()
    except Exception as _e:
        logger.error('[position_monitor] get_daily_exposure() failed — skipping entry: %s', _e)
        return

    if current_exposure >= daily_cap:
        logger.debug(f"Crypto daily cap reached: ${current_exposure:.2f} >= ${daily_cap:.2f}")
        return

    # ── Circuit breaker gate (ISSUE-094) ────────────────────────────────────────
    # Mirror the exact _WS_MODULE_MAP from ws_feed.py.
    # NOTE: evaluate_crypto_entry() is currently dead code — fix applied defensively.
    _WS_MODULE_MAP_PM = {
        ('BTC', 'between'): 'crypto_band_daily_btc',
        ('ETH', 'between'): 'crypto_band_daily_eth',
        ('XRP', 'between'): 'crypto_band_daily_xrp',
        ('DOGE', 'between'): 'crypto_band_daily_doge',
        ('SOL', 'between'): 'crypto_band_daily_sol',
        ('BTC', 'greater'): 'crypto_threshold_daily_btc',
        ('BTC', 'less'):    'crypto_threshold_daily_btc',
        ('ETH', 'greater'): 'crypto_threshold_daily_eth',
        ('ETH', 'less'):    'crypto_threshold_daily_eth',
        ('SOL', 'greater'): 'crypto_threshold_daily_sol',
        ('SOL', 'less'):    'crypto_threshold_daily_sol',
    }
    _ws_module = _WS_MODULE_MAP_PM.get((asset, strike_type), f'crypto_band_daily_{asset.lower()}')
    try:
        import agents.ruppert.trader.circuit_breaker as _cb
        _cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N',
                        getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3))
        _cb_advisory = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY', False)
        _cb_losses = _cb.get_consecutive_losses(_ws_module)
        if _cb_losses >= _cb_n:
            if not _cb_advisory:
                logger.warning(
                    '[PositionMonitor] CB TRIPPED: %d consecutive losses for %s — entry blocked',
                    _cb_losses, _ws_module
                )
                return
    except Exception as _cb_err:
        logger.warning('[PositionMonitor] CB gate failed for %s: %s', _ws_module, _cb_err)
    # ── End circuit breaker gate ─────────────────────────────────────────────────

    # Build opportunity dict
    confidence = compute_composite_confidence(edge, yes_ask, yes_bid, hours_left)
    
    opp = {
        'ticker': ticker,
        'title': f'{asset} price band',
        'side': side,
        'edge': round(edge, 4),
        'win_prob': model_prob if side == 'yes' else (1 - model_prob),
        'confidence': confidence,
        'market_prob': market_prob,
        'model_prob': model_prob,
        'source': 'crypto',
        'module': _ws_module,
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'current_price': current_price,
        'hours_to_settlement': hours_left,
    }
    
    # Compute open_position_value for strategy gate (same pattern as main.py)
    _total = get_capital()
    _bp = get_buying_power()
    opp['open_position_value'] = max(0.0, _total - _bp)

    # Check entry via strategy
    try:
        deployed_today = get_daily_exposure()
        _module_deployed = get_daily_exposure('crypto')
    except Exception as _e:
        logger.error('[position_monitor] get_daily_exposure() failed — skipping entry: %s', _e)
        return
    module_deployed_pct = _module_deployed / capital if capital > 0 else 0.0
    decision = should_enter(opp, capital, deployed_today, module='crypto', module_deployed_pct=module_deployed_pct, traded_tickers=None)
    if not decision['enter']:
        reason = decision['reason']
        logger.debug(f"[WS Crypto] {ticker}: entry blocked — {reason}")
        return
    
    # Calculate position size
    size = calculate_position_size(
        edge=abs(edge),
        win_prob=opp['win_prob'],
        capital=capital,
        confidence=confidence,
    )
    size = min(size, daily_cap - current_exposure, 100.0)  # $100 max per trade
    
    if size < 5:
        return
    
    # Execute trade
    client = KalshiClient()
    bet_price = yes_ask if side == 'yes' else (100 - yes_ask)
    contracts = max(1, int(size / (bet_price / 100)))
    
    print(f"  [WS Crypto Entry] {ticker} {side.upper()} | edge={edge:+.1%} | ${size:.2f}")
    
    _dry_run = getattr(config, 'DRY_RUN', True)
    if _dry_run:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        from agents.ruppert.env_config import require_live_enabled
        require_live_enabled()
        try:
            order_result = client.place_order(ticker, side, bet_price, contracts)
        except Exception as e:
            print(f"  [WS Crypto] Order failed: {e}")
            return
    
    opp['action'] = 'buy'
    opp['contracts'] = contracts
    opp['size_dollars'] = size
    opp['timestamp'] = ts()
    opp['date'] = str(date.today())
    opp['scan_price'] = bet_price
    opp['fill_price'] = bet_price
    
    log_trade(opp, size, contracts, order_result)
    log_activity(f'[WS-CRYPTO] Entered {ticker} {side.upper()} @ {bet_price}c | edge={edge:+.1%}')
    log_event('TRADE_EXECUTED', {
        'ticker': ticker,
        'side': side,
        'size': size,
        'contracts': contracts,
        'price': bet_price,
        'dry_run': _dry_run,
    })
    push_alert('trade', f'WS Crypto Entry: {ticker} {side.upper()} @ {bet_price}c', ticker=ticker)

    # ── Track position for WS exit monitoring ──
    try:
        from agents.ruppert.trader import position_tracker
        fill_price = bet_price
        fill_contracts = contracts
        if not _dry_run and order_result and isinstance(order_result, dict):
            fill_price = int(order_result.get('price', order_result.get('yes_price', bet_price)) or bet_price)
            fill_contracts = int(order_result.get('contracts', order_result.get('count', contracts)) or contracts)
        position_tracker.add_position(ticker, fill_contracts, side, fill_price,
                                      module='crypto', title=opp.get('title', ''))
    except Exception as _pt_err:
        logger.warning('[WS-CRYPTO] position_tracker.add_position failed: %s', _pt_err)


# ─────────────────────────────── Polling Logic ────────────────────────────────

def get_market_data(ticker: str) -> dict | None:
    """Fetch current market data from Kalshi API. Returns dict or None."""
    try:
        _client = KalshiClient()
        result = _client.get_market(ticker)
        return result if result else None
    except Exception:
        return None


def run_polling_scan(client: KalshiClient, run_settlement_check: bool = True):
    """
    Run the existing poll-based position check.
    Reuses check logic from post_trade_monitor.
    """
    # Import position check functions from existing module
    from agents.ruppert.trader.post_trade_monitor import (
        check_settlements, check_crypto_position,
    )
    
    print(f"  [Polling Scan] Starting at {ts()}")
    
    # Settlement check
    if run_settlement_check:
        try:
            check_settlements(client)
        except Exception as e:
            print(f"  [Settlement Checker] ERROR: {e}")
    
    # Position monitoring
    positions = load_open_positions()
    if not positions:
        print("  [Polling] No open positions")
        return
    
    print(f"  [Polling] Checking {len(positions)} positions")
    
    for pos in positions:
        ticker = pos.get('ticker', '')
        side = pos.get('side', '')
        source = pos.get('source', pos.get('module', 'bot'))
        
        if not ticker or not side:
            continue
        
        market = get_market_data(ticker)
        if market is None:
            continue
        
        # Skip settled markets
        if market.get('status') in ('finalized', 'settled'):
            continue
        
        # Route to appropriate checker
        action = None
        reason = None
        
        try:
            if source in ('bot', 'crypto') or any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')):
                action, reason, cur_price, contracts, pnl = check_crypto_position(pos, market)
            else:
                print(f"  [Polling] SKIP: {ticker} unsupported source '{source}'")
                continue
        except Exception as e:
            print(f"  [Polling] Error checking {ticker}: {e}")
            continue
        
        if action == 'auto_exit':
            print(f"  [Polling] AUTO-EXIT: {ticker} — {reason}")
            # ISSUE-033: Execute inline — do NOT call run_monitor() (fanout risk).
            # run_monitor() rescans ALL positions, causing N full rescans for N exits
            # and near-certain double-settlement at scale.
            # NOTE: run_polling_scan() is currently dead code — fix applied defensively.
            _pm_side = pos.get('side', '')
            _pm_contracts = int(pos.get('contracts', 1) or 1)
            _pm_price = cur_price  # cur_price is set by the check_* functions
            if not acquire_exit_lock(ticker, _pm_side):
                print(f"  [Polling] SKIP: {ticker} exit lock held — another process exiting")
                continue
            try:
                _dry_run = getattr(config, 'DRY_RUN', True)
                if _dry_run:
                    _pm_result = {'dry_run': True, 'status': 'simulated'}
                else:
                    from agents.ruppert.env_config import require_live_enabled
                    require_live_enabled()
                    # Use place_order() with 'sell' action — KalshiClient has no sell_position() method
                    _pm_result = client.place_order(ticker, _pm_side, _pm_price, _pm_contracts, action='sell')
                _pm_entry_price = normalize_entry_price(pos)
                _pm_pnl = round(((_pm_price - _pm_entry_price) if _pm_side == 'yes'
                                 else (_pm_entry_price - _pm_price)) * _pm_contracts / 100, 2)
                _pm_opp = {
                    'ticker': ticker, 'title': pos.get('title', ticker),
                    'side': _pm_side, 'action': 'exit',
                    'yes_price': _pm_price if _pm_side == 'yes' else 100 - _pm_price,
                    'market_prob': _pm_price / 100, 'edge': None,
                    'size_dollars': round(_pm_contracts * _pm_price / 100, 2),
                    'contracts': _pm_contracts, 'source': pos.get('source', 'monitor'),
                    'module': pos.get('module', ''), 'timestamp': ts(), 'date': str(date.today()),
                    'pnl': _pm_pnl,
                    'entry_price': _pm_entry_price,
                    'exit_price': _pm_price,
                    'scan_price': _pm_price,
                    'fill_price': _pm_price,
                }
                log_trade(_pm_opp, _pm_opp['size_dollars'], _pm_contracts, _pm_result)
                log_activity(f'[PositionMonitor] AUTO-EXIT {ticker} {_pm_side.upper()} @ {_pm_price}c — {reason}')
                # Notify position tracker
                try:
                    from agents.ruppert.trader import position_tracker as _pt
                    _pt.remove_position(ticker, _pm_side)
                except Exception as _pte:
                    log_activity(f'[PositionMonitor] WARNING: could not remove {ticker} from tracker: {_pte}')
            except Exception as _exit_err:
                print(f"  [Polling] AUTO-EXIT error for {ticker}: {_exit_err}")
            finally:
                release_exit_lock(ticker, _pm_side)
        elif action and 'alert' in action:
            push_alert('warning', f'{ticker}: {reason}', ticker=ticker)
        elif action:
            print(f"  [Polling] {ticker}: {action} — {reason}")


# ─────────────────────────────── WebSocket Mode ───────────────────────────────

async def run_ws_mode(client: KalshiClient):
    """WS mode retired 2026-03-31. Use ws_feed.py directly."""
    raise RuntimeError("WS mode retired — use ws_feed.py directly")



# ─────────────────────────────── Polling Mode (Fallback) ──────────────────────

def run_polling_mode(client: KalshiClient):
    """
    Thin wrapper around existing polling logic.
    Used when WebSocket is disabled or unavailable.
    """
    from agents.ruppert.trader.post_trade_monitor import run_monitor
    
    print(f"\n{'='*60}")
    print(f"  POSITION MONITOR (Polling Mode)  {ts()}")
    print(f"{'='*60}")
    
    # Delegate to existing run_monitor() which handles everything
    run_monitor()
    
    print(f"\nPolling monitor complete. {ts()}")


# ─────────────────────────────── Main Entry Point ─────────────────────────────

def main():
    """
    Main entry point for position monitor.

    Modes:
      --persistent   Continuous WS session during market hours (6AM-11PM).
                     Separate from the polling task — run as its own scheduled task.
      (default)      14-min WS event loop, used by the 15-min polling task.
    """
    parser = argparse.ArgumentParser(description='Ruppert Position Monitor')
    parser.add_argument('--persistent', action='store_true',
                        help='Run persistent WS session (market hours only)')
    args = parser.parse_args()

    if args.persistent:
        # Delegate to ws_feed.py — the WS-first architecture.
        # ws_feed.py handles: market_cache, position_tracker, crypto entry routing.
        try:
            from agents.ruppert.data_analyst.ws_feed import run
            logger.info('[Monitor] Starting ws_feed (WS-first architecture) via --persistent')
            run()
            return
        except Exception as e:
            logger.error(
                '[Monitor] ws_feed failed to start (%s: %s) — no fallback available, exiting',
                type(e).__name__, e
            )
            sys.exit(1)

    client = KalshiClient()

    # Check if WebSocket is available and enabled
    ws_available = False
    if WS_ENABLED:
        try:
            from ws.connection import KalshiWebSocket, WS_AVAILABLE
            ws_available = WS_AVAILABLE
        except ImportError:
            print("  [Monitor] WebSocket module not available — using polling mode")

    if ws_available:
        # Run async WebSocket mode
        print("  [Monitor] Starting WebSocket mode...")
        asyncio.run(run_ws_mode(client))
    else:
        # Fallback to polling
        print("  [Monitor] WebSocket not available — using polling mode")
        run_polling_mode(client)


if __name__ == '__main__':
    main()
