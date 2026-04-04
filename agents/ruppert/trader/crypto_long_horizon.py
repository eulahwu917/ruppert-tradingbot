"""
crypto_long_horizon.py — Long-horizon crypto module (monthly/annual Kalshi markets)

Target series: KXBTCMAXM, KXBTCMAXY, KXBTCMINY, KXBTC2026250, KXBTCMAX100,
               KXETHMAXM, KXETHMINY, KXETHMAXY

Uses Fear & Greed regime + log-normal touch probability model.
DEMO only — $50 hard cap per trade, 1/6 Kelly sizing.
"""

import json
import math
import re
import sys
import logging
import requests
from datetime import datetime, timezone, date
from pathlib import Path
from scipy.stats import norm

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import config
import agents.ruppert.data_analyst.market_cache as market_cache
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
from agents.ruppert.data_scientist.logger import log_trade, log_activity, get_daily_exposure

from agents.ruppert.env_config import get_paths as _get_paths

logger = logging.getLogger(__name__)

LOGS_DIR = _get_paths()['logs']
DECISION_LOG = LOGS_DIR / 'decisions_long_horizon.jsonl'

TARGET_SERIES = [
    'KXBTCMAXM', 'KXBTCMAXY', 'KXBTCMINY', 'KXBTC2026250',
    'KXBTCMAX100', 'KXETHMAXM', 'KXETHMINY', 'KXETHMAXY',
]


# ─────────────────────────────── On-Chain Data ────────────────────────────────

def fetch_fear_greed() -> dict:
    """Returns {value: int, classification: str, avg_7d, avg_30d, trend}."""
    resp = requests.get('https://api.alternative.me/fng/?limit=30', timeout=10)
    data = resp.json()['data']
    current = int(data[0]['value'])
    avg_7d = sum(int(d['value']) for d in data[:7]) / 7
    avg_30d = sum(int(d['value']) for d in data[:30]) / 30
    return {
        'value': current,
        'classification': data[0]['value_classification'],
        'avg_7d': round(avg_7d, 1),
        'avg_30d': round(avg_30d, 1),
        'trend': 'rising' if avg_7d > avg_30d else 'falling',
    }


def classify_regime(fg: dict) -> str:
    """Returns 'bull' | 'neutral' | 'bear'."""
    v = fg['value']
    if v <= 25:   return 'bear'
    elif v >= 75: return 'bull'
    else:         return 'neutral'


# ─────────────────────────────── Price Model ──────────────────────────────────

def touch_probability(
    spot: float,
    strike: float,
    days_to_expiry: float,
    annualized_vol: float,
    regime: str,
) -> float:
    """
    P(BTC touches `strike` at least once before expiry).
    Uses log-normal with regime-adjusted vol + fat-tail correction.
    """
    vol_mult = {
        'bull':    getattr(config, 'LONG_HORIZON_VOL_MULT_BULL',    1.2),
        'neutral': getattr(config, 'LONG_HORIZON_VOL_MULT_NEUTRAL', 1.0),
        'bear':    getattr(config, 'LONG_HORIZON_VOL_MULT_BEAR',    1.4),
    }.get(regime, 1.0)
    sigma = annualized_vol * vol_mult * math.sqrt(days_to_expiry / 365)

    if sigma <= 0:
        return 0.0

    log_ratio = math.log(strike / spot)
    z = abs(log_ratio) / sigma

    if strike > spot:
        # Barrier approximation: P(price touches strike) ≈ 2 * P(terminal > strike) for GBM.
        # This is the standard reflection principle result. Cap the boost at the reflection bound.
        p_terminal = norm.cdf(-log_ratio / sigma)
        barrier_boost = getattr(config, 'LONG_HORIZON_BARRIER_BOOST', 1.5)  # reflection principle upper bound (2x) capped at 1.5x
        p = min(p_terminal * barrier_boost, 0.99)
    else:
        p_terminal = norm.cdf(log_ratio / sigma)
        # Downside barrier: slightly more conservative (1.2x, reflection principle with vol skew)
        p = min(p_terminal * 1.2, 0.99)

    p = min(max(p, 0.0), 0.99)

    # Fat-tail correction for extreme strikes (>2 sigma) — additive nudge, not multiplicative
    if z > 2.0:
        fat_tail_addend = getattr(config, 'LONG_HORIZON_FAT_TAIL_ADDEND', 0.03)  # +3 percentage points for fat tail, not 35% multiplicative boost
        p = min(p + fat_tail_addend, 0.99)

    return round(min(p, 0.99), 4)


# ─────────────────────────────── Strike Parser ────────────────────────────────

def parse_strike(ticker: str) -> float | None:
    """Extract numeric strike from ticker string.

    Examples:
        KXBTCMAXY-26MAR28-B120000  -> 120000.0
        KXBTCMINY-26-B50000        -> 50000.0
        KXBTCMAX100-26MAR28-B100000 -> 100000.0
        KXETHMAXM-26MAR-B5000      -> 5000.0
    """
    # Match the last numeric group after -B or -T or just trailing digits after last dash
    m = re.search(r'-[BT](\d+(?:\.\d+)?)', ticker)
    if m:
        return float(m.group(1))
    # Fallback: last group of digits
    parts = ticker.split('-')
    for part in reversed(parts):
        digits = re.sub(r'[^\d.]', '', part)
        if digits and len(digits) >= 3:
            try:
                return float(digits)
            except ValueError:
                pass
    return None


# ─────────────────────────────── Position Sizing ──────────────────────────────

def size_long_horizon(edge: float, win_prob: float, capital: float, days: int) -> float:
    """More conservative sizing for long-duration holds."""
    c = win_prob - edge  # approximate entry price
    if c <= 0 or c >= 1:
        return 0.0
    kelly = (win_prob - c) / (c * (1 - c))
    # More conservative: 1/6 Kelly for long horizon (vs 1/4 for intraday)
    sized = (kelly / 6) * capital
    # Hard caps
    max_pos = capital * config.LONG_HORIZON_MAX_POSITION_PCT
    _max_pos_usd = getattr(config, 'LONG_HORIZON_MAX_POSITION_USD', 50.0)
    return round(min(sized, max_pos, _max_pos_usd), 2)  # hard cap per long-horizon trade


# ─────────────────────────────── Decision Logger ──────────────────────────────

def log_decision(entry: dict):
    """Append decision to decisions_long_horizon.jsonl."""
    LOGS_DIR.mkdir(exist_ok=True)
    entry['ts'] = datetime.now(timezone.utc).isoformat()
    with open(DECISION_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


# ─────────────────────────────── Market Scanner ───────────────────────────────

def scan_long_horizon_markets(client) -> list[dict]:
    """Fetch and evaluate all open long-horizon crypto markets."""
    opportunities = []
    capital = get_capital()
    fg = fetch_fear_greed()
    regime = classify_regime(fg)

    # Get spot prices (reuse existing crypto_client signals)
    from agents.ruppert.trader.crypto_client import get_btc_signal, get_eth_signal
    btc_signal = get_btc_signal()
    eth_signal = get_eth_signal()
    spot_prices = {'BTC': btc_signal['price'], 'ETH': eth_signal['price']}
    vols = {
        'BTC': btc_signal.get('realized_hourly_vol', 0.015) * math.sqrt(24 * 365),
        'ETH': eth_signal.get('realized_hourly_vol', 0.020) * math.sqrt(24 * 365),
    }

    for series in TARGET_SERIES:
        asset = 'ETH' if 'ETH' in series else 'BTC'
        spot = spot_prices[asset]
        vol = vols[asset]

        try:
            markets = client.get_markets(series_ticker=series, status='open', limit=10)
        except Exception as e:
            logger.warning('[LongHorizon] Failed to fetch markets for %s: %s', series, e)
            continue

        for m in markets:
            ticker = m.get('ticker', '')
            close_time = m.get('close_time', '')
            if not close_time:
                continue

            # Days to expiry — skip markets that have already closed
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            days_raw = (close_dt - datetime.now(timezone.utc)).days
            if days_raw < 0:
                log_decision({
                    'ticker': ticker, 'asset': asset, 'strike': None,
                    'decision': 'SKIP', 'skip_reason': 'market_already_closed',
                    'regime': regime, 'fear_greed': fg['value'],
                    'fear_greed_trend': fg['trend'],
                })
                continue
            days = max(days_raw, 1)

            # Parse strike from ticker
            strike = parse_strike(ticker)
            if not strike:
                log_decision({
                    'ticker': ticker, 'asset': asset, 'strike': None,
                    'decision': 'SKIP', 'skip_reason': 'no_strike_parsed',
                    'regime': regime, 'fear_greed': fg['value'],
                    'fear_greed_trend': fg['trend'],
                })
                continue

            # Model probability
            model_prob = touch_probability(spot, strike, days, vol, regime)

            # Market price from WS cache
            prices_cached = market_cache.get_market_price(ticker)
            if prices_cached:
                yes_ask = prices_cached['yes_ask']
                yes_bid = prices_cached['yes_bid']
            else:
                # REST fallback
                try:
                    raw = client.get_market(ticker)
                    yes_ask = raw.get('yes_ask')   # cents integer
                    yes_bid = raw.get('yes_bid')   # cents integer
                    if yes_ask is None:
                        yes_ask = round(0.5 * 100)
                    if yes_bid is None:
                        yes_bid = round(0.4 * 100)
                except Exception:
                    log_decision({
                        'ticker': ticker, 'asset': asset, 'strike': strike,
                        'days_to_expiry': days, 'spot': spot,
                        'decision': 'SKIP', 'skip_reason': 'no_price_data',
                        'regime': regime, 'fear_greed': fg['value'],
                        'fear_greed_trend': fg['trend'],
                    })
                    continue

            if not yes_ask:
                log_decision({
                    'ticker': ticker, 'asset': asset, 'strike': strike,
                    'days_to_expiry': days, 'spot': spot,
                    'model_prob': model_prob, 'market_prob': 0,
                    'decision': 'SKIP', 'skip_reason': 'no_ask',
                    'regime': regime, 'fear_greed': fg['value'],
                    'fear_greed_trend': fg['trend'],
                })
                continue

            # Edge calculation
            market_prob = yes_ask / 100
            edge = model_prob - market_prob
            side = 'yes' if edge > 0 else 'no'

            # Spread filter
            spread = yes_ask - yes_bid if yes_bid else 99

            decision_entry = {
                'ticker': ticker, 'asset': asset, 'strike': strike,
                'days_to_expiry': days, 'spot': spot,
                'model_prob': model_prob, 'market_prob': round(market_prob, 4),
                'edge': round(edge, 4), 'side': side,
                'yes_ask': yes_ask, 'yes_bid': yes_bid,
                'spread': spread, 'regime': regime,
                'fear_greed': fg['value'], 'fear_greed_trend': fg['trend'],
                'series': series,
            }

            if abs(edge) < config.LONG_HORIZON_MIN_EDGE:
                decision_entry['decision'] = 'SKIP'
                decision_entry['skip_reason'] = 'insufficient_edge'
                decision_entry['position_usd'] = None
                log_decision(decision_entry)
                continue

            if spread > config.LONG_HORIZON_MAX_SPREAD:
                decision_entry['decision'] = 'SKIP'
                decision_entry['skip_reason'] = 'spread_too_wide'
                decision_entry['position_usd'] = None
                log_decision(decision_entry)
                continue

            # Position sizing
            win_prob = model_prob if side == 'yes' else (1 - model_prob)
            pos_size = size_long_horizon(abs(edge), win_prob, capital, days)

            decision_entry['decision'] = 'TRADE'
            decision_entry['position_usd'] = pos_size
            log_decision(decision_entry)

            opportunities.append({
                'ticker': ticker,
                'asset': asset,
                'strike': strike,
                'days_to_expiry': days,
                'spot': spot,
                'model_prob': model_prob,
                'market_prob': round(market_prob, 4),
                'edge': round(edge, 4),
                'side': side,
                'yes_ask': yes_ask,
                'yes_bid': yes_bid,
                'spread': spread,
                'regime': regime,
                'fear_greed': fg['value'],
                'fear_greed_trend': fg['trend'],
                'series': series,
                'position_usd': pos_size,
            })

    return sorted(opportunities, key=lambda x: abs(x['edge']), reverse=True)


# ─────────────────────────────── Execution ────────────────────────────────────

def run_long_horizon_scan(client, dry_run: bool = True, traded_tickers: set = None,
                          open_position_value: float = 0.0) -> list[dict]:
    """Top-level scan + execute for long-horizon crypto markets.

    Called by ruppert_cycle.py in 'full' mode at 7AM.
    Returns list of executed trade dicts.
    """
    from agents.ruppert.strategist.strategy import should_enter

    if traded_tickers is None:
        traded_tickers = set()

    capital = get_capital()
    daily_cap = capital * config.LONG_HORIZON_DAILY_CAP_PCT
    spent = 0.0

    # Check if daily cap already hit
    try:
        existing_exposure = get_daily_exposure()
    except Exception as _e:
        logger.error('[crypto_long_horizon] get_daily_exposure() failed — skipping scan: %s', _e)
        return []
    if existing_exposure >= daily_cap:
        log_activity('[LongHorizon] Daily cap already hit — skipping scan')
        return []

    print(f"\n[LongHorizon] Scanning long-horizon crypto markets...")
    print(f"  Regime-based model | Capital: ${capital:.2f} | Daily cap: ${daily_cap:.2f}")

    try:
        opportunities = scan_long_horizon_markets(client)
    except Exception as e:
        logger.error('[LongHorizon] Scan failed: %s', e)
        print(f"  Scan error: {e}")
        return []

    print(f"  {len(opportunities)} opportunity(ies) found")
    executed = []

    for opp in opportunities:
        ticker = opp['ticker']
        if ticker in traded_tickers:
            print(f"  SKIP {ticker}: already traded today")
            continue

        pos_size = opp['position_usd']
        if pos_size <= 0:
            continue
        if spent + pos_size > daily_cap:
            print(f"  SKIP {ticker}: would exceed daily cap (${spent:.2f} + ${pos_size:.2f} > ${daily_cap:.2f})")
            continue

        # Compute open_position_value and apply global 70% exposure gate
        _total = get_capital()
        _bp = get_buying_power()
        opp['open_position_value'] = max(0.0, _total - _bp)
        try:
            _deployed_today = get_daily_exposure()
            _crypto_long_deployed = get_daily_exposure('crypto_long_horizon')
        except Exception as _e:
            logger.error('[crypto_long_horizon] get_daily_exposure() failed — skipping opportunity: %s', _e)
            continue
        _module_deployed_pct = _crypto_long_deployed / _total if _total > 0 else 0.0
        se_decision = should_enter(opp, _total, _deployed_today, module='crypto_long_horizon', module_deployed_pct=_module_deployed_pct, traded_tickers=None)
        if not se_decision['enter']:
            print(f"  SKIP {ticker}: strategy gate — {se_decision['reason']}")
            log_activity(f'[LongHorizon] SKIP {ticker}: {se_decision["reason"]}')
            continue

        side = opp['side']
        bet_price = opp['yes_ask'] if side == 'yes' else (100 - opp['yes_ask'])
        if bet_price <= 0:
            continue
        contracts = max(1, int(pos_size / bet_price * 100))
        actual_cost = round(contracts * bet_price / 100, 2)

        trade = {
            'ticker': ticker,
            'title': ticker,
            'side': side,
            'action': 'buy',
            'yes_price': opp['yes_ask'],
            'market_prob': opp['market_prob'],
            'edge': opp['edge'],
            'size_dollars': actual_cost,
            'contracts': contracts,
            'source': 'crypto_long_horizon',
            'holding_type': 'long_horizon',
            'note': f"regime={opp['regime']} fg={opp['fear_greed']} strike={opp['strike']} days={opp['days_to_expiry']}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'date': str(date.today()),
            'scan_price': bet_price,
            'fill_price': bet_price,
        }

        if dry_run or config.DRY_RUN:
            log_trade(trade, actual_cost, contracts, {'dry_run': True})
            log_activity(f"[LongHorizon] BUY {side.upper()} {ticker} {contracts}@{bet_price}c ${actual_cost:.2f} edge={opp['edge']:.0%}")
            print(f"  [DEMO] BUY {side.upper()} {ticker} {contracts}@{bet_price}c ${actual_cost:.2f}")
        else:
            from agents.ruppert.env_config import require_live_enabled
            require_live_enabled()
            try:
                result = client.place_order(ticker, side, bet_price, contracts)
                log_trade(trade, actual_cost, contracts, result)
                log_activity(f"[LongHorizon] EXECUTED {ticker} {side.upper()} {contracts}@{bet_price}c")
                print(f"  [LIVE] EXECUTED: {ticker}")
            except Exception as e:
                print(f"  ERROR executing {ticker}: {e}")
                continue

        # Track position with long_horizon holding_type (skips 70% gain exit)
        try:
            from agents.ruppert.trader import position_tracker
            position_tracker.add_position(
                ticker, contracts, side,
                entry_price=bet_price,
                module='crypto_long_horizon',
                title=ticker,
                holding_type='long_horizon',
            )
        except Exception as e:
            logger.warning('[LongHorizon] Could not track position %s: %s', ticker, e)

        traded_tickers.add(ticker)
        spent += actual_cost
        executed.append(trade)

    print(f"  Long-horizon scan complete: {len(executed)} trade(s), ${spent:.2f} deployed")
    return executed
