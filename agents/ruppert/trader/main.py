"""
Ruppert Kalshi Trading Bot — Full System
Modules: Weather, Economics, Geopolitical (scanning only)

NOTE: Crypto, Fed, and Geo TRADING execution runs via ruppert_cycle.py, not this file.
main.py handles Weather trades + Econ/Geo market scanning (alert-only).
To run crypto/fed/geo trades, use: python ruppert_cycle.py

Usage:
  python main.py --test         # Test API connection
  python main.py                # Run all modules once (dry run)
  python main.py --live         # Run with real trades (demo account)
  python main.py --loop         # Run continuously every 6 hours
  python main.py --weather      # Weather module only
  python main.py --econ         # Economics module only
  python main.py --geo          # Geopolitical scanner only
"""
import os
import sys
import json
import math
import time
import requests
import schedule
from pathlib import Path
from datetime import date, datetime

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.strategist.edge_detector import find_opportunities
from agents.ruppert.trader.trader import Trader
from agents.ruppert.data_scientist.logger import log_activity, log_trade, get_daily_summary, get_daily_exposure
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
# economics_scanner and geopolitical_scanner live in environments/demo/
# Add env root to path if not already present (mirrors ruppert_cycle.py bootstrap)
_DEMO_ENV_ROOT = _WORKSPACE_ROOT / 'environments' / 'demo'
if str(_DEMO_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ENV_ROOT))
from economics_scanner import find_econ_opportunities
from geopolitical_scanner import run_geo_scan, format_geo_brief
import config
from agents.ruppert.strategist.strategy import (
    should_enter, should_add, should_exit,
    check_daily_cap, check_open_exposure, calculate_position_size,
    get_strategy_summary,
)


# ─── STRATEGY HELPERS ────────────────────────────────────────────────────────

from agents.ruppert.env_config import get_paths as _get_paths
_env_paths = _get_paths()
_STRATEGY_EXITS_LOG = str(_env_paths['logs'] / 'strategy_exits.jsonl')
_LOGS_DIR = str(_env_paths['logs'])
_TRADES_DIR = str(_env_paths['trades'])


def _load_trade_record(ticker: str) -> dict | None:
    """
    Search all logs/trades_*.jsonl files and return the most recent trade
    record matching `ticker`, or None if not found.
    Records are returned sorted by timestamp descending (most recent first).
    """
    import glob
    pattern = os.path.join(_TRADES_DIR, 'trades_*.jsonl')
    files = sorted(glob.glob(pattern), reverse=True)  # newest file first

    best = None
    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get('ticker') == ticker:
                        # Keep the most recent by timestamp string (ISO sort)
                        if best is None or record.get('timestamp', '') > best.get('timestamp', ''):
                            best = record
        except OSError:
            continue
    return best


def _opp_to_signal(opp: dict, module: str = 'weather') -> dict:
    """Convert an edge_detector opportunity dict into a strategy signal dict."""
    target_date_str = opp.get('target_date', datetime.now().strftime('%Y-%m-%d'))
    try:
        target_dt = datetime.strptime(target_date_str, '%Y-%m-%d').replace(hour=23, minute=59)
        hours_to_settlement = max(0.0, (target_dt - datetime.now()).total_seconds() / 3600)
    except Exception:
        hours_to_settlement = 24.0  # safe fallback
    return {
        'edge':                opp.get('edge', 0.0),
        'win_prob':            opp.get('win_prob', 0.0),
        'confidence':          opp.get('confidence', 0.0),
        'hours_to_settlement': round(hours_to_settlement, 2),
        'module':              module,
        'vol_ratio':           1.0,
        'side':                opp.get('side', ''),
        'ticker':              opp.get('ticker', ''),
    }


def run_exit_scan(dry_run=True):
    """
    ARCHIVED: This function has been moved to archive/run_exit_scan_archived.py.
    Exits are owned exclusively by ws_feed.py (position_tracker) + post_trade_monitor.py.
    Do not call this function. It will raise in all modes.
    Archived: 2026-03-29 per CEO spec CEO-L3.
    """
    raise RuntimeError(
        "run_exit_scan() is archived. "
        "See archive/run_exit_scan_archived.py for historical reference. "
        "Exits are handled by ws_feed.py / post_trade_monitor.py."
    )


def test_connection():
    """Test Kalshi API connection and show available markets."""
    print("\n=== Testing Kalshi Connection ===")
    client = KalshiClient()
    print(f"Environment: {config.get_environment().upper()}")
    balance = client.get_balance()
    print(f"Balance: ${balance:.2f}")
    print("\nSearching for weather markets...")
    markets = client.search_markets('temperature')
    print(f"Found {len(markets)} weather markets:")
    for m in markets[:5]:
        yes_ask = m.get('yes_ask', '?')
        print(f"  [{m.get('ticker')}] {m.get('title')} | YES: {yes_ask}c")
    print("\n[OK] Connection test complete!")


# ─── WEATHER MODULE ───────────────────────────────────────────────────────────

def run_weather_scan(dry_run=True, traded_tickers=None, open_position_value=0.0):
    """Run weather market scan and execute trades."""
    log_activity("[Weather] Starting scan...")
    try:
        client = KalshiClient()

        # ── Daily cap check ───────────────────────────────────────────────────
        # Use computed capital (deposits + realized P&L) — NOT client.get_balance()
        # which returns a stale Kalshi API demo balance.
        try:  # W3: guard against get_capital() raising an exception
            total_capital = get_capital()
        except Exception as _cap_err:
            import sys as _sys
            print(
                f"[WARNING] run_weather_scan: get_capital() failed: {_cap_err} "
                "— using $10,000.00 fallback.",
                file=_sys.stderr,
            )
            total_capital = getattr(config, 'CAPITAL_FALLBACK', 10000.0)  # fallback when get_capital() fails
        deployed_today = get_daily_exposure()
        cap_remaining  = check_daily_cap(total_capital, deployed_today)
        log_activity(
            f"[Weather] Capital: ${total_capital:.2f} | Deployed today: ${deployed_today:.2f} "
            f"| Remaining: ${cap_remaining:.2f}"
        )
        if cap_remaining <= 0:
            log_activity(
                f"[Weather] Daily cap reached (${deployed_today:.2f} deployed, "
                f"max ${total_capital * 0.70:.2f}). Skipping new entries this cycle."
            )
            return []

        markets = client.search_markets('temperature')
        log_activity(f"[Weather] Fetched {len(markets)} markets")

        # Filter: skip markets with less than MIN_HOURS_TO_CLOSE hours remaining
        # Uses close_time from Kalshi API directly — no timezone math needed
        import datetime as _dt
        _now_utc = _dt.datetime.now(_dt.timezone.utc)
        _min_hours = getattr(config, 'MIN_HOURS_TO_CLOSE', 4.0)
        _all_before = len(markets)
        filtered_markets = []
        for m in markets:
            close_str = m.get('close_time', '')
            if close_str:
                try:
                    close_dt = _dt.datetime.fromisoformat(close_str.replace('Z', '+00:00'))
                    hours_left = (close_dt - _now_utc).total_seconds() / 3600
                    if hours_left < _min_hours:
                        log_activity(f'[WeatherScan] Skipping {m.get("ticker","?")} — only {hours_left:.1f}h to close (min {_min_hours}h)')
                        continue
                except Exception:
                    pass
            filtered_markets.append(m)
        markets = filtered_markets
        log_activity(f"[Weather] Filtered to {len(markets)} markets ({_all_before - len(markets)} removed, <{_min_hours}h to close)")

        opportunities = find_opportunities(markets)

        # ── Dedup: keep only highest-edge opp per (city, settlement_date) pair ──
        opportunities = sorted(opportunities, key=lambda o: o.get('edge', 0), reverse=True)
        _seen_city_date = {}
        _deduped_opps = []
        for opp in opportunities:
            _city = opp.get('city') or opp.get('ticker', '').split('-')[0]
            _date = opp.get('target_date')
            _key = (_city, _date)
            if _key in _seen_city_date:
                _winner_ticker = _seen_city_date[_key]
                log_activity(f"[Weather] DEDUP skip {opp.get('ticker')} — city={_city} date={_date} already covered by {_winner_ticker}")
            else:
                _seen_city_date[_key] = opp.get('ticker')
                _deduped_opps.append(opp)
        opportunities = _deduped_opps

        log_activity(f"[Weather] Found {len(opportunities)} opportunities above {config.MIN_EDGE_THRESHOLD:.0%} threshold")

        for opp in opportunities:
            log_activity(f"  >> {opp['ticker']}: {opp['action']} | NOAA: {opp['noaa_prob']:.1%} vs Market: {opp['market_prob']:.1%} | Edge: {opp['edge']:+.1%}")

        # ── Baseline: log always-NO for every opportunity above edge gate ───
        for opp in opportunities:
            try:
                from baselines import log_always_no_weather
                no_price = opp.get('no_ask', 100 - opp.get('yes_ask', 50)) / 100
                actual_action = opp.get('side', 'no')
                actual_price = opp.get('yes_ask', 50) / 100 if actual_action == 'yes' else no_price
                log_always_no_weather(
                    ticker=opp.get('ticker', ''),
                    no_price=no_price,
                    actual_action=actual_action,
                    actual_price=actual_price,
                )
            except Exception:
                pass

        # ── Strategy gate: filter opportunities through should_enter() ────────
        # Compute weather daily cap and open exposure dynamically
        _weather_daily_cap = total_capital * getattr(config, 'WEATHER_DAILY_CAP_PCT', 0.07)
        if open_position_value > 0.0:
            _open_exposure = open_position_value
        else:
            try:
                _open_exposure = max(0.0, total_capital - get_buying_power())
            except Exception:
                _open_exposure = 0.0

        approved_opps = []
        try:
            from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
            _weather_deployed_this_cycle = _get_daily_exp(module='weather')
        except Exception:
            _weather_deployed_this_cycle = 0.0

        if _weather_deployed_this_cycle >= _weather_daily_cap:
            log_activity(
                f"[Weather] Daily cap already reached: ${_weather_deployed_this_cycle:.2f} deployed "
                f"(cap ${_weather_daily_cap:.0f}). Skipping scan."
            )
            return []

        for opp in opportunities:
            # ── Global 70% open exposure check ──
            if not check_open_exposure(total_capital, _open_exposure):
                log_activity(f"  [GlobalCap] STOP: open exposure ${_open_exposure:.2f} >= 70% of capital ${total_capital:.2f}")
                break

            # ── Per-module daily cap: weather budget scales with capital ──
            if _weather_deployed_this_cycle >= _weather_daily_cap:
                log_activity(
                    f"  [DailyCap] STOP: weather budget ${_weather_daily_cap:.0f} "
                    f"exhausted (${_weather_deployed_this_cycle:.2f} deployed this cycle)"
                )
                break

            signal = _opp_to_signal(opp, module='weather')
            signal['open_position_value'] = _open_exposure
            decision = should_enter(
                signal, total_capital, deployed_today,
                module='weather',
                module_deployed_pct=_weather_deployed_this_cycle / total_capital if total_capital > 0 else 0.0,
                traded_tickers=traded_tickers,
            )
            if decision.get('warning'):
                log_activity(f"  [Strategy] WARNING: {decision['warning']}")
            if decision['enter']:
                # Check weather-specific budget before approving
                if _weather_deployed_this_cycle + decision['size'] > _weather_daily_cap:
                    log_activity(
                        f"  [DailyCap] SKIP {opp['ticker']}: would exceed weather daily cap "
                        f"(${_weather_deployed_this_cycle:.2f} + ${decision['size']:.2f} > "
                        f"${_weather_daily_cap:.0f})"
                    )
                    continue
                # Pass strategy-computed size so Trader skips redundant risk.py sizing
                opp['strategy_size'] = decision['size']
                approved_opps.append(opp)
                # W14: refresh deployed_today so subsequent opportunities in this cycle
                # see the updated cap (prevents over-deployment if multiple trades fire)
                deployed_today += decision['size']
                _weather_deployed_this_cycle += decision['size']
                _open_exposure += decision['size']
                log_activity(f"  [Strategy] ENTER {opp['ticker']}: {decision['reason']}")
            else:
                log_activity(f"  [Strategy] SKIP  {opp['ticker']}: {decision['reason']}")

        executed: list = []
        if approved_opps:
            try:
                # Phase 7c: add signal provenance to weather trade logs
                for opp in approved_opps:
                    opp['data_sources'] = {
                        'nws_temp': opp.get('nws_official_f'),
                        'openmeteo_prob': opp.get('ensemble_prob'),
                        'model': 'open_meteo_multi_model',
                    }
                trader = Trader(dry_run=dry_run)
                for opp in approved_opps:
                    try:
                        result = trader.execute_opportunity(opp)
                        if not result:
                            log_activity(f"[Weather] execute_opportunity returned falsy for {opp.get('ticker')} — skipping post-trade logging")
                            continue
                        executed.append(opp)
                    except Exception as _opp_err:
                        log_activity(f"[Weather] execute_opportunity failed for {opp.get('ticker')}: {_opp_err}")
                        continue
                    # Log Brier predictions for each executed weather trade
                    try:
                        from brier_tracker import log_prediction
                        log_prediction(
                            domain='weather',
                            ticker=opp.get('ticker', ''),
                            predicted_prob=opp.get('win_prob', opp.get('prob', 0.5)),
                            market_price=opp.get('market_price', opp.get('yes_ask', 50) / 100),
                            edge=opp.get('edge', 0),
                            side=opp.get('side', '')
                        )
                    except Exception:
                        pass
                    # Baseline: uniform sizing vs Kelly
                    try:
                        from baselines import log_uniform_sizing
                        _actual_price_f = opp.get('yes_ask', 50) / 100 if opp.get('side') == 'yes' \
                                          else (100 - opp.get('yes_ask', 50)) / 100
                        log_uniform_sizing(
                            ticker=opp.get('ticker', ''),
                            domain='weather',
                            actual_action=opp.get('side', 'no'),
                            actual_price=_actual_price_f,
                            actual_size=opp.get('strategy_size', opp.get('size_dollars', 0)),
                        )
                    except Exception:
                        pass
                    # Position tracker registration is handled inside trader.py execute_opportunity().
                    # Do not call position_tracker.add_position() here — would double-register.
            except Exception as exec_err:
                log_activity(f"[Weather] Execution error (trades may be partially logged): {exec_err}")
                import traceback
                traceback.print_exc()
        else:
            log_activity("[Weather] No opportunities approved by strategy layer.")

        return executed

    except Exception as e:
        log_activity(f"[Weather] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return []


# ─── CRYPTO / FED HELPERS ────────────────────────────────────────────────────

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


# ─── CRYPTO MODULE ────────────────────────────────────────────────────────────

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

                new_crypto.append({
                    'ticker': ticker, 'title': m.get('title', ticker),
                    'side': best_action, 'price': best_price,
                    'yes_ask': ya, 'yes_bid': m.get('yes_bid') or ya,
                    'prob_model': prob_model,
                    'confidence': _crypto_confidence,
                    'hours_to_settlement': _hours_left,
                    'edge': round(best_edge, 3), 'series': series,
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
            _crypto_deployed_this_cycle = _get_daily_exp(module='crypto')
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

        trader = Trader(dry_run=dry_run)
        for t in new_crypto[:3]:
            if not check_open_exposure(_total_capital, _open_exposure):
                print(f"  [GlobalCap] STOP: open exposure ${_open_exposure:.2f} >= 70% of capital")
                break

            if _crypto_deployed_this_cycle >= _crypto_daily_cap:
                print(f"  [DailyCap] STOP: crypto budget ${_crypto_daily_cap:.0f} exhausted")
                break

            signal = {
                'edge': t['edge'],
                'win_prob': t['prob_model'],
                'confidence': t.get('confidence', t['edge']),
                'hours_to_settlement': t.get('hours_to_settlement', 24.0),
                'module': 'crypto',
                'vol_ratio': 1.0,
                'side': t['side'],
                'yes_ask': t['yes_ask'],
                'yes_bid': t.get('yes_bid', t['yes_ask']),
                'open_position_value': _open_exposure,
            }
            decision = should_enter(
                signal, _total_capital, _deployed_today,
                module='crypto',
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
            opp['module'] = 'crypto'
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


# ─── FED MODULE ───────────────────────────────────────────────────────────────

def run_fed_scan(dry_run=True, traded_tickers=None, open_position_value=0.0):
    """Run Fed rate decision scan and execute trades. Returns list of executed opp dicts."""
    if traded_tickers is None:
        traded_tickers = set()

    client = KalshiClient()
    executed = []

    try:
        from fed_client import run_fed_scan as _run_fed_scan_inner, FOMC_DECISION_DATES_2026, is_in_signal_window

        in_window, fed_meeting, fed_days = is_in_signal_window()
        if not in_window:
            print(f"  Fed signal window inactive — next FOMC {fed_meeting} ({fed_days}d away)")
            return []

        fed_signal = _run_fed_scan_inner()
        try:
            from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
            _fed_deployed_this_cycle = _get_daily_exp(module='fed')
        except Exception:
            _fed_deployed_this_cycle = 0.0

        if fed_signal and not fed_signal.get("skip_reason"):
            ticker    = fed_signal.get("ticker", "KXFEDDECISION-?")
            side      = fed_signal.get("direction", "yes")
            edge_pct  = fed_signal.get("edge", 0) * 100
            conf_pct  = fed_signal.get("confidence", 0) * 100
            outcome   = fed_signal.get("outcome", "?")
            mkt_price = int(fed_signal.get("yes_ask", 50))
            bet_price = mkt_price if side == "yes" else 100 - mkt_price

            try:
                _fed_capital  = get_capital()
                _fed_deployed = get_daily_exposure()
                _fed_cap_ok   = check_daily_cap(_fed_capital, _fed_deployed)
            except Exception:
                _fed_capital  = 10000.0
                _fed_deployed = 0.0
                _fed_cap_ok   = 25.0

            _fed_daily_cap   = _fed_capital * getattr(config, 'FED_DAILY_CAP_PCT', 0.03)

            if _fed_deployed_this_cycle >= _fed_daily_cap:
                print(f"  [DailyCap] Fed daily cap already reached: ${_fed_deployed_this_cycle:.2f} deployed "
                      f"(cap ${_fed_daily_cap:.0f}). Skipping scan.")
                return []

            _days_to_meeting = fed_signal.get('days_to_meeting', 5)
            _fed_hours       = max(1.0, _days_to_meeting * 24)

            try:
                _fed_open_exposure = max(0.0, _fed_capital - get_buying_power())
            except Exception:
                _fed_open_exposure = open_position_value

            if _fed_cap_ok <= 0:
                print(f"  [CapCheck] Daily cap reached — skipping Fed trade")
            elif ticker in traded_tickers:
                print(f"  Already traded {ticker} this cycle — skipping")
            elif not check_open_exposure(_fed_capital, _fed_open_exposure):
                print(f"  [GlobalCap] STOP: open exposure ${_fed_open_exposure:.2f} >= 70% of capital")
            else:
                _fed_signal_dict = {
                    'edge': fed_signal.get('edge', 0),
                    'win_prob': fed_signal.get('prob', 0.5),
                    'confidence': fed_signal.get('confidence', 0),
                    'hours_to_settlement': _fed_hours,
                    'module': 'fed',
                    'vol_ratio': 1.0,
                    'side': side,
                    'yes_ask': mkt_price,
                    'yes_bid': mkt_price,
                    'open_position_value': _fed_open_exposure,
                }
                _fed_deployed_pct = _fed_deployed_this_cycle / _fed_capital if _fed_capital > 0 else 0.0
                _fed_decision = should_enter(
                    _fed_signal_dict, _fed_capital, _fed_deployed,
                    module='fed',
                    module_deployed_pct=_fed_deployed_pct,
                    traded_tickers=traded_tickers,
                )
                if _fed_decision.get('warning'):
                    log_activity(f"  [Strategy] WARNING: {_fed_decision['warning']}")
                if not _fed_decision['enter']:
                    print(f"  [Strategy] SKIP {ticker}: {_fed_decision['reason']}")
                elif _fed_decision['size'] > _fed_daily_cap:
                    print(f"  [DailyCap] SKIP {ticker}: would exceed fed/econ daily cap")
                else:
                    size        = min(_fed_decision['size'], _fed_cap_ok)
                    contracts   = max(1, int(size / bet_price * 100))
                    actual_cost = round(contracts * bet_price / 100, 2)

                    opp = {
                        "ticker":      ticker,
                        "title":       fed_signal.get("title", ticker),
                        "side":        side,
                        "action":      "buy",
                        "yes_price":   mkt_price,
                        "market_prob": fed_signal.get("market_price", 0.5),
                        "noaa_prob":   None,
                        "edge":        fed_signal.get("edge"),
                        "confidence":  fed_signal.get("confidence"),
                        "size_dollars": actual_cost,
                        "contracts":   contracts,
                        "source":      "fed",
                        "outcome":     outcome,
                        "meeting_date": fed_signal.get("meeting_date"),
                        "days_to_meeting": fed_signal.get("days_to_meeting"),
                        "polymarket_prob": fed_signal.get("prob"),
                        "note": (f"FOMC {fed_signal.get('meeting_date')} {outcome.upper()} "
                                 f"FedWatch={fed_signal.get('prob', 0):.0%} "
                                 f"Kalshi={fed_signal.get('market_price', 0):.0%} "
                                 f"edge={edge_pct:.0f}%"),
                        "timestamp":   datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "date":        str(date.today()),
                    }
                    opp['strategy_size'] = size
                    opp['module'] = 'fed'
                    opp['scan_price'] = mkt_price
                    opp['fill_price'] = mkt_price
                    result = Trader(dry_run=dry_run).execute_opportunity(opp)
                    if result:
                        _fed_deployed_this_cycle += _fed_decision.get('size', 0)
                        traded_tickers.add(ticker)
                        executed.append(opp)

                        # Baseline: log what pure CME-follow would have done
                        try:
                            from baselines import log_follow_cme_fed, log_uniform_sizing
                            _cme_prob = fed_signal.get('prob', 0.5)
                            _mkt_price_f = fed_signal.get('market_price', 0.5)
                            log_follow_cme_fed(
                                ticker=ticker,
                                cme_prob=_cme_prob,
                                market_price=_mkt_price_f,
                                actual_action=side,
                                actual_price=bet_price / 100,
                                ensemble_prob=fed_signal.get('ensemble_prob'),
                            )
                            # Baseline: uniform sizing vs Kelly
                            log_uniform_sizing(
                                ticker=ticker,
                                domain='fed',
                                actual_action=side,
                                actual_price=bet_price / 100,
                                actual_size=actual_cost,
                            )
                        except Exception:
                            pass
                        # Log Brier prediction at trade entry
                        try:
                            from brier_tracker import log_prediction
                            log_prediction(
                                domain='fed',
                                ticker=ticker,
                                predicted_prob=fed_signal.get('prob', 0.5),
                                market_price=fed_signal.get('market_price', 0.5),
                                edge=fed_signal.get('edge', 0.0),
                                side=side,
                            )
                        except Exception:
                            pass
                    else:
                        log_activity(f"  [Fed] execute_opportunity failed for {ticker} — not deduped, may retry next cycle")

        elif fed_signal and fed_signal.get("skip_reason"):
            print(f"  Fed signal skipped: {fed_signal['skip_reason']}")
        else:
            print(f"  No Fed edge in window ({fed_days}d to {fed_meeting} FOMC)")

    except Exception as e:
        print(f"  Fed scan error: {e}")
        import traceback
        traceback.print_exc()

    return executed


# ─── GEOPOLITICAL TRADES MODULE ───────────────────────────────────────────────

def run_geo_trades(dry_run=True, traded_tickers=None, open_position_value=0.0):
    """Run geopolitical market scan and execute trades. Returns list of executed opp dicts."""
    if traded_tickers is None:
        traded_tickers = set()

    executed = []

    if not getattr(config, 'GEO_AUTO_TRADE', False):
        log_activity("[Geo] GEO_AUTO_TRADE=False — skipping")
        return executed

    log_activity("[Geo] Starting geopolitical trade scan...")

    try:
        geo_markets = run_geo_scan()
        if not geo_markets:
            log_activity("[Geo] No geo opportunities returned by scanner")
            return executed

        log_activity(f"[Geo] Scanner returned {len(geo_markets)} market(s)")

        try:
            _geo_capital  = get_capital()
            _geo_deployed = get_daily_exposure()
        except Exception:
            _geo_capital  = 10000.0
            _geo_deployed = 0.0

        _geo_daily_cap = _geo_capital * getattr(config, 'GEO_DAILY_CAP_PCT', 0.04)
        try:
            from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
            _geo_deployed_this_cycle = _get_daily_exp(module='geo')
        except Exception:
            _geo_deployed_this_cycle = 0.0

        if _geo_deployed_this_cycle >= _geo_daily_cap:
            log_activity(
                f"[Geo] Daily cap already reached: ${_geo_deployed_this_cycle:.2f} deployed "
                f"(cap ${_geo_daily_cap:.0f}). Skipping scan."
            )
            return executed

        try:
            _geo_open_exposure = max(0.0, _geo_capital - get_buying_power())
        except Exception:
            _geo_open_exposure = open_position_value

        trader = Trader(dry_run=dry_run)

        for opp in geo_markets:
            ticker = opp.get('ticker', '')
            if not ticker:
                continue
            if ticker in traded_tickers:
                log_activity(f"  [Geo] Already traded {ticker} — skipping")
                continue

            if not check_open_exposure(_geo_capital, _geo_open_exposure):
                log_activity(f"  [GlobalCap] STOP: open exposure ${_geo_open_exposure:.2f} >= 70% of capital")
                break

            if _geo_deployed_this_cycle >= _geo_daily_cap:
                log_activity(f"  [DailyCap] STOP: geo budget ${_geo_daily_cap:.0f} exhausted")
                break

            side = opp.get('side', opp.get('direction', 'yes')).lower()
            _estimated_prob = opp.get('estimated_prob', 0.5)
            _geo_win_prob = _estimated_prob if side == 'yes' else (1.0 - _estimated_prob)
            yes_ask = int(opp.get('yes_ask', 50))
            yes_bid = int(opp.get('yes_bid', yes_ask))
            bet_price = yes_ask if side == 'yes' else 100 - yes_ask

            # Geo: hours_to_settlement from opp or fallback to GEO_MIN_DAYS_TO_EXPIRY
            _geo_days = opp.get('days_to_expiry') or getattr(config, 'GEO_MIN_DAYS_TO_EXPIRY', 1)
            _geo_hours = max(24.0, float(_geo_days) * 24)

            signal = {
                'edge':                opp.get('edge', 0.0),
                'win_prob':            _geo_win_prob,
                'confidence':          min(opp.get('confidence', 0.0),
                                          getattr(config, 'GEO_MAX_CONFIDENCE', 0.85)),
                'hours_to_settlement': _geo_hours,
                'module':              'geo',
                'vol_ratio':           1.0,
                'side':                side,
                'yes_ask':             yes_ask,
                'yes_bid':             yes_bid,
                'open_position_value': _geo_open_exposure,
            }

            decision = should_enter(
                signal, _geo_capital, _geo_deployed,
                module='geo',
                module_deployed_pct=_geo_deployed_this_cycle / _geo_capital if _geo_capital > 0 else 0.0,
                traded_tickers=traded_tickers,
            )
            if decision.get('warning'):
                log_activity(f"  [Strategy] WARNING: {decision['warning']}")

            if not decision['enter']:
                log_activity(f"  [Strategy] SKIP {ticker}: {decision['reason']}")
                continue

            if _geo_deployed_this_cycle + decision['size'] > _geo_daily_cap:
                log_activity(f"  [DailyCap] SKIP {ticker}: would exceed geo daily cap")
                continue

            size = min(decision['size'], check_daily_cap(_geo_capital, _geo_deployed))
            contracts = max(1, int(size / bet_price * 100))
            actual_cost = round(contracts * bet_price / 100, 2)

            trade_opp = {
                'ticker':       ticker,
                'title':        opp.get('title', ticker),
                'side':         side,
                'action':       'buy',
                'yes_price':    yes_ask,
                'market_prob':  yes_ask / 100,
                'noaa_prob':    None,
                'edge':         opp.get('edge'),
                'confidence':   opp.get('confidence'),
                'size_dollars': actual_cost,
                'contracts':    contracts,
                'source':       'geo',
                'module':       'geo',
                'scan_price':   bet_price,
                'fill_price':   bet_price,
                'scan_contracts': contracts,
                'fill_contracts': contracts,
                'note':         opp.get('reasoning', '')[:200],
                'timestamp':    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date':         str(date.today()),
            }
            trade_opp['strategy_size'] = size

            result = trader.execute_opportunity(trade_opp)
            if not result:
                log_activity(f"  [Geo] execute_opportunity failed for {ticker} — skipping accounting")
                continue

            # Log Brier prediction at trade entry
            try:
                from brier_tracker import log_prediction
                log_prediction(
                    domain='geo',
                    ticker=ticker,
                    predicted_prob=_geo_win_prob,
                    market_price=yes_ask / 100,
                    edge=opp.get('edge', 0.0),
                    side=side,
                )
            except Exception:
                pass

            try:
                from baselines import log_uniform_sizing
                log_uniform_sizing(
                    ticker=ticker,
                    domain='geo',
                    actual_action=side,
                    actual_price=bet_price / 100,
                    actual_size=actual_cost,
                )
            except Exception:
                pass

            traded_tickers.add(ticker)
            _geo_deployed_this_cycle += actual_cost
            _geo_deployed += actual_cost
            _geo_open_exposure += actual_cost
            executed.append(trade_opp)
            log_activity(f"  [Geo] ENTERED {ticker} {side.upper()} {contracts}@{bet_price}c ${actual_cost:.2f}")

    except Exception as e:
        log_activity(f"[Geo] ERROR: {e}")
        import traceback
        traceback.print_exc()

    log_activity(f"[Geo] Done — {len(executed)} trade(s) executed")
    return executed


# ─── ECONOMICS MODULE ─────────────────────────────────────────────────────────

def run_econ_scan(dry_run=True):
    """Run economics market scan."""
    log_activity("[Econ] Starting scan...")
    try:
        opportunities = find_econ_opportunities()
        log_activity(f"[Econ] Found {len(opportunities)} markets to review")
        for opp in opportunities[:5]:
            flag = " [REVIEW]" if opp.get('requires_human_review') else ""
            log_activity(f"  >> {opp['ticker']}: {opp['market_prob']:.0%} | {opp.get('note', '')}{flag}")
    except Exception as e:
        log_activity(f"[Econ] ERROR: {e}")


# ─── GEOPOLITICAL MODULE ──────────────────────────────────────────────────────

def run_geo_scan_module():
    """Run geopolitical market scanner."""
    log_activity("[Geo] Starting geopolitical scan...")
    try:
        markets = run_geo_scan()
        brief = format_geo_brief(markets)
        log_activity(f"[Geo] Flagged {len(markets)} markets with news activity")
        for line in brief.split('\n'):
            if line.strip():
                log_activity(f"  {line}")
    except Exception as e:
        log_activity(f"[Geo] ERROR: {e}")


# ─── FULL SCAN ────────────────────────────────────────────────────────────────

def run_full_scan(dry_run=True):
    """Run all modules in sequence."""
    log_activity("=" * 60)
    log_activity(f"FULL SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_activity(f"Mode: {'DRY RUN (simulated)' if dry_run else 'LIVE TRADING'}")
    log_activity("=" * 60)

    # Exit scan removed: exits are owned exclusively by post_trade_monitor + WS feed.
    # run_exit_scan() has a # TODO: live mode stub and is dead code — do not call here.

    run_weather_scan(dry_run=dry_run)
    run_econ_scan(dry_run=dry_run)
    run_geo_scan_module()

    summary = get_daily_summary()
    log_activity(f"\nDaily summary: {summary['trades']} trades | ${summary['total_exposure']:.2f} exposure")
    log_activity("=" * 60)


def run_loop(dry_run=True):
    """Run the full bot on a schedule."""
    interval = config.CHECK_INTERVAL_HOURS
    log_activity(f"Starting bot loop — scanning every {interval} hours")
    run_full_scan(dry_run=dry_run)
    schedule.every(interval).hours.do(run_full_scan, dry_run=dry_run)
    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    # ── Log strategy summary at every startup ─────────────────────────────────
    _summary = get_strategy_summary()
    log_activity("[Strategy] Parameters in effect:")
    for _k, _v in _summary.items():
        log_activity(f"  {_k:<35} = {_v}")

    if '--test' in args:
        test_connection()
    elif '--weather' in args:
        run_weather_scan(dry_run='--live' not in args)
    elif '--econ' in args:
        run_econ_scan(dry_run='--live' not in args)
    elif '--geo' in args:
        run_geo_scan_module()
    elif '--loop' in args:
        run_loop(dry_run='--live' not in args)
    else:
        run_full_scan(dry_run='--live' not in args)
