"""
crypto_band_daily.py -- Daily crypto band (above/below range) trading module.

Trades KXBTC / KXETH / KXSOL / KXXRP / KXDOGE band markets on Kalshi.
Formerly embedded in main.py as run_crypto_scan().
"""

import math
import sys
import requests
from pathlib import Path
from datetime import date, datetime

# Ensure project root is on sys.path when running standalone
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

_DEMO_ENV_ROOT = _WORKSPACE_ROOT / 'environments' / 'demo'
if str(_DEMO_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ENV_ROOT))

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.trader.trader import Trader
from agents.ruppert.data_scientist.logger import log_activity, log_trade, get_daily_summary, get_daily_exposure
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
from agents.ruppert.strategist.strategy import (
    should_enter, check_daily_cap, check_open_exposure,
)
import config


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


def run_crypto_scan(dry_run=True, direction='neutral', traded_tickers=None, open_position_value=0.0):
    """Run crypto market scan and execute trades. Returns list of executed opp dicts."""
    if traded_tickers is None:
        traded_tickers = set()

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
                        # DS-SETTLE-AUDIT-2026-03-29: skip markets expiring today or already closed
                        from datetime import date as _date
                        if ct.date() <= _date.today():
                            log_activity(f"  [Crypto] Skipping {ticker}: expires today or already closed")
                            continue
                    except Exception:
                        pass

                try:
                    band_mid = float(ticker.split('-B')[-1])
                except Exception:
                    continue

                prob_model = band_prob(spot, band_mid, half_w, sigma, drift)
                mkt_yes    = ya / 100
                edge_no    = mkt_yes - prob_model
                edge_yes   = prob_model - mkt_yes

                best_edge   = max(edge_no, edge_yes)
                best_action = 'no' if edge_no >= edge_yes else 'yes'
                best_price  = na if best_action == 'no' else ya

                if best_edge < config.CRYPTO_MIN_EDGE_THRESHOLD:
                    continue
                if best_price > 95:
                    continue

                _hours_left = 18.0
                if close:
                    try:
                        _ct = datetime.fromisoformat(close.replace('Z', '+00:00'))
                        _hours_left = max(1.0, (_ct - datetime.now(timezone.utc)).total_seconds() / 3600)
                    except Exception:
                        pass

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
                    'prob_model': prob_model,
                    'confidence': _crypto_confidence,
                    'hours_to_settlement': _hours_left,
                    'edge': round(best_edge, 3), 'series': series,
                    'module': _band_module,
                    'note': f'{series} {direction} | model={prob_model*100:.0f}% mkt={mkt_yes*100:.0f}% edge={best_edge*100:.0f}%',
                })

        # Sort by edge, take top 3 per run max
        new_crypto.sort(key=lambda x: x['edge'], reverse=True)

        # Daily cap check before executing
        try:
            _total_capital  = get_capital()
            _deployed_today = get_daily_exposure()
            _cap_remaining  = check_daily_cap(_total_capital, _deployed_today)
            if _cap_remaining <= 0:
                print(f"  [CapCheck] Daily cap reached (${_deployed_today:.2f} deployed, "
                      f"max ${_total_capital * 0.70:.2f}). Skipping crypto trades this cycle.")
                return []
            else:
                print(f"  [CapCheck] Cap OK — ${_cap_remaining:.2f} remaining (${_deployed_today:.2f} deployed)")
        except Exception as e:
            print(f"  [CapCheck] Cap check error: {e} — proceeding with caution")
            _total_capital  = 10000.0
            _deployed_today = 0.0

        _crypto_daily_cap = _total_capital * getattr(config, 'CRYPTO_DAILY_CAP_PCT', 0.07)
        try:
            from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
            # Sum deployed across all per-asset band modules (formerly 'crypto_1h_band')
            _crypto_deployed_this_cycle = sum(
                _get_daily_exp(module=m)
                for m in ('crypto_band_daily_btc', 'crypto_band_daily_eth',
                          'crypto_band_daily_sol', 'crypto_band_daily_xrp',
                          'crypto_band_daily_doge')
            )
        except Exception:
            _crypto_deployed_this_cycle = 0.0

        if _crypto_deployed_this_cycle >= _crypto_daily_cap:
            print(f"  [DailyCap] Crypto daily cap already reached: ${_crypto_deployed_this_cycle:.2f} deployed "
                  f"(cap ${_crypto_daily_cap:.0f}). Skipping scan.")
            return []

        try:
            _api_exposure = max(0.0, _total_capital - get_buying_power())
            _open_exposure = max(_api_exposure, open_position_value)
        except Exception:
            _open_exposure = open_position_value

        # ── 1h Band Circuit Breaker gate (Phase 2 — 2026-03-31) ──────────────
        _cb_1h_n        = getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3)
        _cb_1h_advisory = getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_ADVISORY', False)
        try:
            from agents.ruppert.trader.post_trade_monitor import _read_1h_circuit_breaker_state
            _cb_1h_losses = _read_1h_circuit_breaker_state()
        except Exception:
            _cb_1h_losses = 0

        if _cb_1h_losses >= _cb_1h_n:
            if _cb_1h_advisory:
                print(f'  [1h CB] Advisory: {_cb_1h_losses} consecutive complete-loss windows '
                      f'(threshold={_cb_1h_n}). Continuing in advisory mode.')
            else:
                print(f'  [1h CB] CIRCUIT BREAKER TRIPPED: {_cb_1h_losses} consecutive complete-loss '
                      f'windows (threshold={_cb_1h_n}). Halting crypto_band_daily for today.')
                return []

        trader = Trader(dry_run=dry_run)
        for t in new_crypto[:3]:
            if not check_open_exposure(_total_capital, _open_exposure):
                print(f"  [GlobalCap] STOP: open exposure ${_open_exposure:.2f} >= 70% of capital")
                break

            if _crypto_deployed_this_cycle >= _crypto_daily_cap:
                print(f"  [DailyCap] STOP: crypto budget ${_crypto_daily_cap:.0f} exhausted")
                break

            _t_module = t.get('module', 'crypto_band_daily_btc')  # per-asset band module
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
                signal, _total_capital, _deployed_today,
                module=_t_module,
                module_deployed_pct=_crypto_deployed_this_cycle / _total_capital if _total_capital > 0 else 0.0,
                traded_tickers=traded_tickers,
            )
            if decision.get('warning'):
                log_activity(f"  [Strategy] WARNING: {decision['warning']}")
            if not decision['enter']:
                print(f"  [Strategy] SKIP {t['ticker']}: {decision['reason']}")
                continue
            if _crypto_deployed_this_cycle + decision['size'] > _crypto_daily_cap:
                print(f"  [DailyCap] SKIP {t['ticker']}: would exceed crypto daily cap")
                continue

            size = decision['size']
            best_price = t['price']
            contracts  = max(1, int(size / best_price * 100))
            actual_cost = round(contracts * best_price / 100, 2)

            opp = {
                'ticker': t['ticker'], 'title': t['title'], 'side': t['side'],
                'action': 'buy', 'yes_price': t['price'] if t['side'] == 'yes' else 100 - t['price'],
                'market_prob': t['price'] / 100, 'noaa_prob': None,
                'edge': t['edge'], 'confidence': t.get('confidence', t['edge']),
                'size_dollars': actual_cost,
                'contracts': contracts, 'source': 'crypto',
                'scan_price': t['price'],
                'fill_price': t['price'],
                'scan_contracts': contracts,
                'fill_contracts': contracts,
                'note': t['note'],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date': str(date.today()),
            }
            opp['strategy_size'] = size
            opp['module'] = _t_module
            result = trader.execute_opportunity(opp)
            if not result:
                print(f"  [Crypto] execute_opportunity failed for {t['ticker']} — skipping accounting")
                continue

            # Log Brier prediction at trade entry
            try:
                from brier_tracker import log_prediction
                log_prediction(
                    domain='crypto',
                    ticker=t['ticker'],
                    predicted_prob=t['prob_model'],
                    market_price=t['yes_ask'] / 100,
                    edge=t['edge'],
                    side=t['side'],
                )
            except Exception:
                pass
            # Baseline: log uniform sizing vs actual Kelly sizing
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

    except Exception as e:
        print(f"  Crypto scan error: {e}")
        import traceback
        traceback.print_exc()

    return executed
