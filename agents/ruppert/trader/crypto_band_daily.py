"""
crypto_band_daily.py -- Daily crypto band (above/below range) trading module.

Trades KXBTC / KXETH / KXSOL / KXXRP / KXDOGE band markets on Kalshi.
Formerly embedded in main.py as run_crypto_scan().
"""

import logging
import math
import sys
import requests
from pathlib import Path
from datetime import date, datetime, timezone

# Ensure project root is on sys.path when running standalone
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

_DEMO_ENV_ROOT = _WORKSPACE_ROOT / 'environments' / 'demo'
if str(_DEMO_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ENV_ROOT))

import json
from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.trader.trader import Trader
from agents.ruppert.data_scientist.logger import log_activity, log_trade, get_daily_summary, get_daily_exposure
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
from agents.ruppert.strategist.strategy import (
    should_enter, check_daily_cap, check_open_exposure,
)
from agents.ruppert.data_analyst.polymarket_client import get_crypto_daily_consensus
from agents.ruppert.env_config import get_paths as _get_bd_paths
from agents.ruppert.trader.utils import _today_pdt
import config

# ISSUE-053: portalocker for cross-process daily cap race protection
try:
    import portalocker as _portalocker
    _HAS_PORTALOCKER = True
except ImportError:
    _HAS_PORTALOCKER = False

logger = logging.getLogger(__name__)

# Calibrated hourly sigma from empirical settlement displacement analysis (Band Model v2)
# Source: 48 resolved Kalshi band contracts, April 2026
# Formula: sigma(hours) = _SIGMA_HOURLY[series] * sqrt(max(1.0, hours_to_settlement))
_SIGMA_HOURLY = {
    'KXBTC': 0.000577,
    'KXETH': 0.001020,
    'default': 0.001530,  # conservative fallback for KXDOGE, KXSOL, KXXRP etc.
}

_BD_LOGS_DIR = _get_bd_paths()['logs']
_BD_LOGS_DIR.mkdir(exist_ok=True)
BAND_DECISION_LOG_PATH = _BD_LOGS_DIR / 'decisions_band.jsonl'


def band_prob(spot, band_mid, half_w, sigma, drift=0.0):
    """Log-normal probability that price ends inside [band_mid-half_w, band_mid+half_w]."""
    import math
    from scipy.stats import norm
    lo = band_mid - half_w
    hi = band_mid + half_w
    if spot <= 0 or sigma <= 0:
        return 0.5
    mu = math.log(spot) + drift
    s = sigma
    p_hi = norm.cdf((math.log(hi) - mu) / s) if hi > 0 else 1.0
    p_lo = norm.cdf((math.log(lo) - mu) / s) if lo > 0 else 0.0
    return max(0.001, min(0.999, p_hi - p_lo))


def _log_band_decision(
    ticker: str,
    series: str,
    spot: float,
    band_mid: float,
    sigma: float,
    prob_model: float,
    mkt_yes: float,
    edge_yes: float,
    edge_no: float,
    decision: str,
    skip_reason: str = None,
    side: str = None,
    edge: float = None,
    confidence: float = None,
    size_usd: float = None,
    hours_to_settlement: float = None,
    poly_daily_yes_price: float = None,
    poly_daily_market_title: str = None,
    poly_daily_fetched_at: str = None,
):
    """Append one evaluation record to decisions_band.jsonl."""
    entry = {
        'ts':         datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'ticker':     ticker,
        'series':     series,
        'decision':   decision,
        'skip_reason': skip_reason,
        # Market state
        'spot':       spot,
        'band_mid':   band_mid,
        'sigma':      round(sigma, 6) if sigma is not None else None,
        # Model
        'model_prob':   round(prob_model, 4) if prob_model is not None else None,
        'model_source': 'log_normal_band',
        # Market prices
        'mkt_yes':  round(mkt_yes, 4) if mkt_yes is not None else None,
        'edge_yes': round(edge_yes, 4) if edge_yes is not None else None,
        'edge_no':  round(edge_no, 4) if edge_no is not None else None,
        # ENTER fields
        'side':       side,
        'edge':       round(edge, 4) if edge is not None else None,
        'confidence': round(confidence, 4) if confidence is not None else None,
        'size_usd':   size_usd,
        'hours_to_settlement': hours_to_settlement,
        # Shadow: Polymarket
        'poly_daily_yes_price':    poly_daily_yes_price,
        'poly_daily_market_title': poly_daily_market_title,
        'poly_daily_fetched_at':   poly_daily_fetched_at,
    }
    try:
        BAND_DECISION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BAND_DECISION_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        print(f'  [BandDecision] log failed for {ticker}: {e}')


def _execute_band_trades(new_crypto, trader, total_capital, crypto_daily_cap,
                         deployed_today, open_position_value, band_poly_cache, traded_tickers):
    """
    ISSUE-053: Extracted helper for cap-check + circuit-breaker + trade-execution loop.
    Called inside a portalocker cap lock so BTC and ETH evaluations are mutually exclusive.

    Returns list of executed opp dicts.
    """
    executed = []

    # Read deployed amount from disk (inside lock — this is the race-critical read)
    try:
        from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
        _crypto_deployed_this_cycle = sum(
            _get_daily_exp(module=m)
            for m in ('crypto_band_daily_btc', 'crypto_band_daily_eth',
                      'crypto_band_daily_sol', 'crypto_band_daily_xrp',
                      'crypto_band_daily_doge')
        )
    except Exception as _e:
        import logging as _logging
        _logging.getLogger(__name__).error(
            '[crypto_band_daily] get_daily_exposure() failed in cap lock — skipping entry batch: %s', _e
        )
        return []

    if _crypto_deployed_this_cycle >= crypto_daily_cap:
        print(f"  [DailyCap] Crypto daily cap already reached: ${_crypto_deployed_this_cycle:.2f} deployed "
              f"(cap ${crypto_daily_cap:.0f}). Skipping scan.")
        return []

    try:
        _api_exposure = max(0.0, total_capital - get_buying_power())
        _open_exposure = max(_api_exposure, open_position_value)
    except Exception:
        _open_exposure = open_position_value

    # ── Daily Band Circuit Breaker gate ──────────────────────────────────────
    _cb_1h_n        = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N',
                              getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3))
    _cb_1h_advisory = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY',
                              getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_ADVISORY', False))
    try:
        from agents.ruppert.trader import circuit_breaker as _cb_mod
        _cb_1h_losses = max(
            _cb_mod.get_consecutive_losses('crypto_band_daily_btc'),
            _cb_mod.get_consecutive_losses('crypto_band_daily_eth'),
        )
    except Exception as _cb_read_err:
        logger.warning('[crypto_band_daily] CB read failed, defaulting to 0: %s', _cb_read_err)
        _cb_1h_losses = 0

    if _cb_1h_losses >= _cb_1h_n:
        if _cb_1h_advisory:
            print(f'  [daily CB] Advisory: {_cb_1h_losses} consecutive losses '
                  f'(threshold={_cb_1h_n}). Continuing in advisory mode.')
        else:
            print(f'  [daily CB] CIRCUIT BREAKER TRIPPED: {_cb_1h_losses} consecutive losses '
                  f'(threshold={_cb_1h_n}). Halting crypto_band_daily for today.')
            return []

    _deployed_today = deployed_today
    for t in new_crypto[:3]:
        if not check_open_exposure(total_capital, _open_exposure):
            print(f"  [GlobalCap] STOP: open exposure ${_open_exposure:.2f} >= 70% of capital")
            break

        if _crypto_deployed_this_cycle >= crypto_daily_cap:
            print(f"  [DailyCap] STOP: crypto budget ${crypto_daily_cap:.0f} exhausted")
            break

        _t_module = t.get('module', 'crypto_band_daily_btc')
        signal = {
            'edge': t['edge'],
            'win_prob': t['prob_model'],
            'confidence': t.get('confidence', t['edge']),
            'hours_to_settlement': t.get('hours_to_settlement', 24.0),
            'module': _t_module,
            'vol_ratio': 1.0,
            'side': t['side'],
            'yes_ask': t['yes_ask'],
            'yes_bid': t.get('yes_bid', t['yes_ask']),
            'open_position_value': _open_exposure,
        }
        decision = should_enter(
            signal, total_capital, _deployed_today,
            module=_t_module,
            module_deployed_pct=_crypto_deployed_this_cycle / total_capital if total_capital > 0 else 0.0,
            traded_tickers=traded_tickers,
        )
        if decision.get('warning'):
            log_activity(f"  [Strategy] WARNING: {decision['warning']}")
        if not decision['enter']:
            print(f"  [Strategy] SKIP {t['ticker']}: {decision['reason']}")
            continue
        if _crypto_deployed_this_cycle + decision['size'] > crypto_daily_cap:
            print(f"  [DailyCap] SKIP {t['ticker']}: would exceed crypto daily cap")
            continue

        size = decision['size']
        best_price = t['price']
        contracts  = max(1, int(size / best_price * 100))
        actual_cost = round(contracts * best_price / 100, 2)

        _band_asset = 'BTC' if 'BTC' in t.get('series', '') else 'ETH'
        _bp_data = band_poly_cache.get(_band_asset, {})

        opp = {
            'ticker': t['ticker'], 'title': t['title'], 'side': t['side'],
            'action': 'buy', 'yes_price': t['price'] if t['side'] == 'yes' else 100 - t['price'],
            'no_ask': t.get('no_ask'),               # ISSUE-017: explicit no_ask (robustness)
            'market_prob': t['price'] / 100,
            'edge': t['edge'], 'confidence': t.get('confidence', t['edge']),
            'model_prob':   t['prob_model'],
            'model_source': 'log_normal_band',
            'hours_to_settlement': t.get('hours_to_settlement', 18.0),
            'size_dollars': actual_cost,
            'contracts': contracts, 'source': 'crypto',
            'scan_price': t['price'],
            'fill_price': t['price'],
            'scan_contracts': contracts,
            'fill_contracts': contracts,
            'note': t['note'],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'date': _today_pdt(),
            'poly_daily_yes_price':    _bp_data.get('yes_price'),
            'poly_daily_market_title': _bp_data.get('market_title'),
            'poly_daily_volume_24h':   _bp_data.get('volume_24h'),
            'poly_daily_fetched_at':   _bp_data.get('fetched_at'),
        }
        opp['strategy_size'] = size
        opp['module'] = _t_module
        result = trader.execute_opportunity(opp)
        if not result:
            print(f"  [Crypto] execute_opportunity failed for {t['ticker']} — skipping accounting")
            continue

        try:
            from brier_tracker import log_prediction
            _brier_prob_band = t['prob_model'] if t['side'] == 'yes' else (1.0 - t['prob_model'])
            log_prediction(
                domain='crypto_band_daily',
                ticker=t['ticker'],
                predicted_prob=_brier_prob_band,
                market_price=t['price'] / 100,
                edge=t['edge'],
                side=t['side'],
                extra={
                    'series':       t.get('series'),
                    'prob_model':   t['prob_model'],
                    'model_source': 'log_normal_band',
                    'module':       t.get('module'),
                },
            )
        except Exception:
            pass

        _log_band_decision(
            ticker=t['ticker'], series=t.get('series', ''),
            spot=t.get('spot'), band_mid=t.get('band_mid'),
            sigma=t.get('sigma'),
            prob_model=t['prob_model'],
            mkt_yes=t['yes_ask'] / 100,
            edge_yes=t.get('edge_yes', 0.0),
            edge_no=t.get('edge_no', 0.0),
            decision='ENTER',
            side=t['side'],
            edge=t['edge'],
            confidence=t.get('confidence'),
            size_usd=actual_cost,
            hours_to_settlement=t.get('hours_to_settlement'),
            poly_daily_yes_price=_bp_data.get('yes_price'),
            poly_daily_market_title=_bp_data.get('market_title'),
            poly_daily_fetched_at=_bp_data.get('fetched_at'),
        )
        try:
            from baselines import log_uniform_sizing
            log_uniform_sizing(
                ticker=t['ticker'],
                domain='crypto',
                actual_action=t['side'],
                actual_price=t['price'] / 100,
                actual_size=actual_cost,
            )
        except Exception:
            pass

        traded_tickers.add(t['ticker'])
        _crypto_deployed_this_cycle += actual_cost
        _open_exposure += actual_cost
        _deployed_today += actual_cost
        executed.append(opp)

    return executed


def run_crypto_scan(dry_run=True, direction='neutral', traded_tickers=None, open_position_value=0.0):
    """Run crypto market scan and execute trades. Returns list of executed opp dicts."""
    if traded_tickers is None:
        traded_tickers = set()

    # Code-level disable guard
    if not getattr(config, 'CRYPTO_BAND_DAILY_ENABLED', False):
        raise RuntimeError(
            'crypto_band_daily is DISABLED (config.CRYPTO_BAND_DAILY_ENABLED=False). '
            'Set CRYPTO_BAND_DAILY_ENABLED=True in config.py to enable.'
        )

    client = KalshiClient()
    executed = []

    try:
        # Get live prices
        prices = {}
        for sym, key in [('XBTUSD', 'btc'), ('ETHUSD', 'eth'), ('XRPUSD', 'xrp'),
                         ('SOLUSD', 'sol'), ('DOGEUSD', 'doge')]:
            try:
                r = requests.get(f'https://api.kraken.com/0/public/Ticker?pair={sym}', timeout=5)
                prices[key] = float(list(r.json()['result'].values())[0]['c'][0])
            except Exception:
                pass

        btc  = prices.get('btc', 70000)
        eth  = prices.get('eth', 2000)
        xrp  = prices.get('xrp', 1.38)
        sol  = prices.get('sol', 0)
        doge = prices.get('doge', 0)
        print(f"  BTC=${btc:,.0f}  ETH=${eth:,.2f}  XRP=${xrp:.4f}  SOL=${sol:.2f}  DOGE=${doge:.5f}")

        drift_sigma = 0.0

        # Pre-initialize poly cache — populated after new_crypto scan, referenced in SKIP logs
        _band_poly_cache = {}

        SERIES_CFG = [
            ('KXBTC',  btc,  250,   0.025, 18),
            ('KXETH',  eth,  10,    0.030, 18),
            ('KXXRP',  xrp,  0.01,  0.045, 18),
            ('KXSOL',  sol,  5.0,   0.045, 18),
            ('KXDOGE', doge, 0.005, 0.050, 18),
        ]

        new_crypto = []
        for series, spot, half_w, daily_vol, hours in SERIES_CFG:
            if spot == 0:
                continue
            sigma = daily_vol * math.sqrt(hours / 24)
            drift = drift_sigma * sigma

            # Price-targeted fetching: get ALL market metadata (cheap paginated list),
            # filter to markets near current price, then enrich only those with orderbook.
            all_meta = client.get_markets_metadata(series, status='open')
            print(f"  [{series}] {len(all_meta)} total markets found")

            # Filter to markets near spot price using floor_strike
            near_price = []
            for m in all_meta:
                try:
                    strike = float(m.get('floor_strike', 0))
                except (TypeError, ValueError):
                    continue
                # Keep markets within ±10% of current spot price
                if abs(strike - spot) <= spot * 0.10:
                    near_price.append(m)

            # Also include markets with list-endpoint yes_ask in tradeable range
            # (catches markets whose floor_strike is 0 or missing)
            near_tickers = {m.get('ticker') for m in near_price}
            for m in all_meta:
                if m.get('ticker') in near_tickers:
                    continue
                ya_d = float(m.get('yes_ask_dollars') or 0)
                if 0.05 <= ya_d <= 0.92:
                    near_price.append(m)

            print(f"  [{series}] {len(near_price)} markets near spot (${spot:,.2f}), enriching orderbooks...")

            # Enrich near-price markets in parallel (10 workers → ~15-20s vs ~2min serial)
            import concurrent.futures
            def _enrich_market(m, _client=client):
                _client.enrich_orderbook(m)
                return m
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as _pool:
                list(_pool.map(_enrich_market, near_price, timeout=30))

            from datetime import timezone
            for m in near_price:
                ticker = m.get('ticker', '')
                if ticker in traded_tickers:
                    continue
                ya = m.get('yes_ask') or 0
                na = m.get('no_ask') or 0
                if ya < 5 or ya > 92 or na < 5:
                    continue
                close = m.get('close_time', '')
                if close:
                    try:
                        ct = datetime.fromisoformat(close.replace('Z', '+00:00'))
                        mins_left = (ct - datetime.now(timezone.utc)).total_seconds() / 60
                        if mins_left < 120:
                            continue
                        # ISSUE-016: only skip markets whose close_time has already passed.
                        # Previously skipped all same-day contracts (ct.date() <= today),
                        # which blocked valid band contracts settling at 21:00 UTC.
                        if ct <= datetime.now(timezone.utc):
                            log_activity(f"  [Crypto] Skipping {ticker}: already closed ({ct.isoformat()})")
                            continue
                    except Exception:
                        pass

                try:
                    band_mid = float(ticker.split('-B')[-1])
                except Exception:
                    continue

                # Compute per-market hours-left for sigma (fix: use actual contract horizon)
                _hours_left = 18.0
                if close:
                    try:
                        _ct = datetime.fromisoformat(close.replace('Z', '+00:00'))
                        _hours_left = max(1.0, (_ct - datetime.now(timezone.utc)).total_seconds() / 3600)
                    except Exception:
                        pass

                # Per-market sigma: calibrated per-sqrt-hour constant * sqrt(hours) [Band Model v2]
                # Source: 48 resolved Kalshi band contracts, April 2026
                # Formula: sigma = _SIGMA_HOURLY[series] * sqrt(max(1.0, hours_to_settlement))
                sigma_hourly = _SIGMA_HOURLY.get(series, _SIGMA_HOURLY['default'])
                sigma_m = sigma_hourly * math.sqrt(max(1.0, _hours_left))
                prob_model = band_prob(spot, band_mid, half_w, sigma_m, drift)
                mkt_yes    = ya / 100
                edge_no    = mkt_yes - prob_model
                edge_yes   = prob_model - mkt_yes

                best_edge   = max(edge_no, edge_yes)
                best_action = 'no' if edge_no >= edge_yes else 'yes'
                best_price  = na if best_action == 'no' else ya

                if best_edge < config.CRYPTO_MIN_EDGE_THRESHOLD:
                    _bp_skip = _band_poly_cache.get(
                        'BTC' if 'BTC' in series else ('ETH' if 'ETH' in series else ''), {}
                    )
                    _log_band_decision(
                        ticker=ticker, series=series, spot=spot, band_mid=band_mid,
                        sigma=sigma_m, prob_model=prob_model, mkt_yes=mkt_yes,
                        edge_yes=round(edge_yes, 4), edge_no=round(edge_no, 4),
                        decision='SKIP', skip_reason='edge_below_threshold',
                        poly_daily_yes_price=_bp_skip.get('yes_price'),
                        poly_daily_market_title=_bp_skip.get('market_title'),
                        poly_daily_fetched_at=_bp_skip.get('fetched_at'),
                    )
                    continue
                if best_price > 95:
                    _log_band_decision(
                        ticker=ticker, series=series, spot=spot, band_mid=band_mid,
                        sigma=sigma_m, prob_model=prob_model, mkt_yes=mkt_yes,
                        edge_yes=round(edge_yes, 4), edge_no=round(edge_no, 4),
                        decision='SKIP', skip_reason='price_too_high',
                    )
                    continue

                from agents.ruppert.trader.crypto_client import compute_composite_confidence
                _crypto_confidence = compute_composite_confidence(best_edge, ya, m.get('yes_bid') or ya, _hours_left)

                # Map series to new per-asset band module name (formerly 'crypto_1h_band')
                _SERIES_TO_BAND_MODULE = {
                    'KXBTC':  'crypto_band_daily_btc',
                    'KXETH':  'crypto_band_daily_eth',
                    'KXSOL':  'crypto_band_daily_sol',
                    'KXXRP':  'crypto_band_daily_xrp',
                    'KXDOGE': 'crypto_band_daily_doge',
                }
                _band_module = _SERIES_TO_BAND_MODULE.get(series, 'crypto_band_daily_btc')
                new_crypto.append({
                    'ticker': ticker, 'title': m.get('title', ticker),
                    'side': best_action, 'price': best_price,
                    'yes_ask': ya, 'yes_bid': m.get('yes_bid') or ya,
                    'no_ask': m.get('no_ask'),   # ISSUE-017: explicit no_ask for forward-looking robustness
                    'prob_model': prob_model,
                    'confidence': _crypto_confidence,
                    'hours_to_settlement': _hours_left,
                    'edge': round(best_edge, 3), 'series': series,
                    'module': _band_module,
                    'spot': spot,
                    'band_mid': band_mid,
                    'sigma': sigma_m,
                    'edge_yes': round(edge_yes, 4),
                    'edge_no': round(edge_no, 4),
                    'note': f'{series} {direction} | model={prob_model*100:.0f}% mkt={mkt_yes*100:.0f}% edge={best_edge*100:.0f}%',
                })

        # Sort by edge, take top 3 per run max
        new_crypto.sort(key=lambda x: x['edge'], reverse=True)

        # ── Shadow: Polymarket daily consensus for band module (logging only) ──
        # _band_poly_cache initialized earlier; populate now that scan is complete.
        for _bp_asset in ('BTC', 'ETH'):
            try:
                _bp_result = get_crypto_daily_consensus(_bp_asset)
                if _bp_result:
                    _band_poly_cache[_bp_asset] = {
                        'yes_price':    _bp_result.get('yes_price'),
                        'market_title': _bp_result.get('market_title'),
                        'volume_24h':   _bp_result.get('volume_24h'),
                        'fetched_at':   datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    }
            except Exception as _bp_err:
                logger.warning('[crypto_band_daily] Polymarket band shadow fetch failed for %s: %s', _bp_asset, _bp_err)
        # ── End Polymarket shadow ──

        # Daily cap check before executing
        try:
            try:
                _total_capital  = get_capital()
            except RuntimeError as e:
                logger.warning("crypto_band_daily: get_capital() failed — aborting scan: %s", e)
                return []
            _deployed_today = get_daily_exposure()
            _cap_remaining  = check_daily_cap(_total_capital, _deployed_today)
            if _cap_remaining <= 0:
                print(f"  [CapCheck] Daily cap reached (${_deployed_today:.2f} deployed, "
                      f"max ${_total_capital * 0.70:.2f}). Skipping crypto trades this cycle.")
                return []
            else:
                print(f"  [CapCheck] Cap OK — ${_cap_remaining:.2f} remaining (${_deployed_today:.2f} deployed)")
        except Exception as e:
            print(f"  [CapCheck] get_daily_exposure() failed — halting cycle: {e}")
            import logging as _logging
            _logging.getLogger(__name__).error(
                '[crypto_band_daily] get_daily_exposure() failed in main entry loop — halting cycle: %s', e
            )
            return []

        _crypto_daily_cap = _total_capital * getattr(config, 'CRYPTO_DAILY_CAP_PCT', 0.07)

        # ISSUE-053: acquire cross-process cap lock before disk read of deployed amount.
        # Prevents race where concurrent asset evals both pass cap before either logs a trade.
        _cap_lock_path = _BD_LOGS_DIR / 'crypto_1d_cap.lock'
        if not _HAS_PORTALOCKER:
            print('[crypto_band_daily] portalocker unavailable — cap race not protected')
        _cap_lock_f = open(_cap_lock_path, 'w') if _HAS_PORTALOCKER else None
        if _cap_lock_f:
            _portalocker.lock(_cap_lock_f, _portalocker.LOCK_EX)

        try:
            _executed_in_lock = _execute_band_trades(
                new_crypto=new_crypto,
                trader=Trader(dry_run=dry_run),
                total_capital=_total_capital,
                crypto_daily_cap=_crypto_daily_cap,
                deployed_today=_deployed_today,
                open_position_value=open_position_value,
                band_poly_cache=_band_poly_cache,
                traded_tickers=traded_tickers,
            )
            executed.extend(_executed_in_lock)
        finally:
            if _cap_lock_f:
                try:
                    _portalocker.unlock(_cap_lock_f)
                    _cap_lock_f.close()
                except Exception:
                    pass

    except Exception as e:
        print(f"  Crypto scan error: {e}")
        import traceback
        traceback.print_exc()

    return executed
