"""
Ruppert Autonomous Trading Cycle
Runs on schedule via Windows Task Scheduler.
Modes:
  full   — scan + positions + smart money + execute (7am, 3pm)
  check  — positions only (12pm, 10pm)
  smart  — smart money refresh only (lightweight)
"""
import sys, json, time, math, requests
from pathlib import Path
from datetime import date, datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')

MODE = sys.argv[1] if len(sys.argv) > 1 else 'full'
LOGS = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)
ALERTS_FILE = LOGS / 'pending_alerts.json'
ALERT_LOG   = LOGS / 'cycle_log.jsonl'

import config
from kalshi_client import KalshiClient
from logger import log_trade, log_activity, get_daily_exposure, get_computed_capital
from bot.strategy import check_daily_cap

DRY_RUN = True  # Flip to False when going live

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def push_alert(level, message, ticker=None, pnl=None):
    """Write alert for heartbeat to pick up and forward to David."""
    alerts = []
    if ALERTS_FILE.exists():
        try: alerts = json.loads(ALERTS_FILE.read_text(encoding='utf-8'))
        except: pass
    alerts.append({
        'level': level, 'message': message,
        'ticker': ticker, 'pnl': pnl,
        'timestamp': ts(),
    })
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding='utf-8')

def log_cycle(event, data=None):
    entry = {'ts': ts(), 'mode': MODE, 'event': event}
    if data: entry.update(data)
    with open(ALERT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

def norm_cdf(x):
    t = 1 / (1 + 0.2316419 * abs(x))
    p = 1 - (0.31938153*t - 0.356563782*t**2 + 1.781477937*t**3
             - 1.821255978*t**4 + 1.330274429*t**5) * math.exp(-x*x/2) / math.sqrt(2*math.pi)
    return p if x >= 0 else 1 - p

def band_prob(spot, band_mid, half_w, sigma, drift=0.0):
    mu = math.log(spot) + drift
    lo, hi = band_mid - half_w, band_mid + half_w
    if lo <= 0: return 0.0
    return max(0, min(1, norm_cdf((math.log(hi)-mu)/sigma) - norm_cdf((math.log(lo)-mu)/sigma)))

# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RUPPERT CYCLE  mode={MODE.upper()}  {ts()}")
print(f"{'='*60}")
log_cycle('start')

client = KalshiClient()
BASE   = "https://api.elections.kalshi.com/trade-api/v2/markets"
HDR    = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
traded_tickers = set()

# ── STEP 1: POSITION CHECK (every run) ───────────────────────────────────────
print("\n[1] Position check...")
try:
    from openmeteo_client import get_full_weather_signal
    from edge_detector import parse_date_from_ticker, parse_threshold_from_ticker

    trade_log = LOGS / f"trades_{date.today().isoformat()}.jsonl"
    open_positions = []
    if trade_log.exists():
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            try: open_positions.append(json.loads(line))
            except: pass
    open_positions = [p for p in open_positions if p.get('action') != 'exit']

    print(f"  {len(open_positions)} open position(s)")
    actions_taken = []

    for pos in open_positions:
        ticker = pos.get('ticker', '')
        source = pos.get('source', 'bot')
        if source not in ('weather', 'bot'): continue
        if ticker in traded_tickers: continue

        # Get current market price
        try:
            r = requests.get(f'{BASE}/{ticker}', timeout=5)
            if r.status_code != 200: continue
            m = r.json().get('market', {})
            status = m.get('status', '')
            if status in ('finalized', 'settled'): continue

            yes_ask = m.get('yes_ask', 50) or 50
            no_ask  = m.get('no_ask', 50) or 50
            side    = pos.get('side', 'no')
            entry_p = pos.get('entry_price') or (100 - round(pos.get('market_prob',0.5)*100))
            cur_p   = no_ask if side == 'no' else yes_ask
            contracts = pos.get('contracts', 0)
            pnl     = round((cur_p - entry_p) * contracts / 100, 2)

            # Weather: check ensemble if close to expiry
            alert_msg = None
            if 'KXHIGH' in ticker:
                try:
                    # Derive correct args for get_full_weather_signal from the ticker
                    series_ticker = ticker.split('-')[0].upper()  # e.g. KXHIGHMIA
                    threshold_f = parse_threshold_from_ticker(ticker)   # e.g. 85.5
                    target_date = parse_date_from_ticker(ticker)        # e.g. date(2026,3,12)
                    if threshold_f is not None:
                        sig = get_full_weather_signal(series_ticker, threshold_f, target_date)
                        # forecast: use tomorrow_high if not same-day, else today_high
                        conditions = sig.get('conditions', {})
                        if sig.get('is_same_day'):
                            forecast = conditions.get('today_high_f') or 0
                        else:
                            forecast = conditions.get('tomorrow_high_f') or 0
                        margin = abs(forecast - threshold_f) if forecast else 999
                        ens_prob = sig.get('final_prob', 0.5) or 0.5

                        if side == 'no':
                            # NO wins if forecast OUTSIDE band — check if forecast moved inside
                            if margin < 1.0:
                                alert_msg = f'WARNING: {ticker} forecast {forecast:.1f}F only {margin:.1f}F from band edge {threshold_f}F | P&L ${pnl:+.2f}'
                                push_alert('warning', alert_msg, ticker=ticker, pnl=pnl)
                            elif ens_prob > 0.80:
                                alert_msg = f'EXIT SIGNAL: {ticker} ensemble {ens_prob:.0%} against NO position | P&L ${pnl:+.2f}'
                                push_alert('exit', alert_msg, ticker=ticker, pnl=pnl)

                            # Auto-exit if gain > $4 and margin tight
                            if pnl > 4.0 and margin < 2.0:
                                print(f'  AUTO-EXIT: {ticker} P&L=${pnl:+.2f} margin={margin:.1f}F')
                                actions_taken.append(('exit', ticker, side, cur_p, contracts, pnl))
                                traded_tickers.add(ticker)
                except Exception as e:
                    print(f'  Weather check error for {ticker}: {e}')

            print(f'  {ticker:38} {side.upper()} entry={entry_p}c cur={cur_p}c P&L=${pnl:+.2f}' +
                  (f' [ALERT]' if alert_msg else ''))
        except Exception as e:
            print(f'  Error checking {ticker}: {e}')

    # Execute auto-exits
    if actions_taken:
        for action, ticker, side, price, contracts, pnl in actions_taken:
            opp = {'ticker': ticker, 'title': ticker, 'side': side, 'action': 'exit',
                   'yes_price': price if side=='yes' else 100-price,
                   'market_prob': price/100, 'noaa_prob': None, 'edge': None,
                   'size_dollars': round(contracts*price/100, 2), 'contracts': contracts,
                   'source': 'weather', 'timestamp': ts(), 'date': str(date.today())}
            if DRY_RUN:
                log_trade(opp, opp['size_dollars'], contracts, {'dry_run': True})
                log_activity(f'[AUTO-EXIT] {ticker} {side.upper()} @ {price}c P&L=${pnl:+.2f}')
                print(f'  [DEMO] AUTO-EXIT logged: {ticker}')
            else:
                try:
                    result = client.sell_position(ticker, side, price, contracts)
                    log_trade(opp, opp['size_dollars'], contracts, result)
                    print(f'  [LIVE] AUTO-EXIT executed: {ticker}')
                except Exception as e:
                    print(f'  EXIT ERROR {ticker}: {e}')

except Exception as e:
    print(f'  Position check error: {e}')
    import traceback; traceback.print_exc()

if MODE == 'check':
    log_cycle('done', {'actions': len(actions_taken) if 'actions_taken' in dir() else 0})
    print(f"\nCheck-only cycle done. {ts()}")
    sys.exit(0)

# ── REPORT MODE: 7am P&L summary + loss detection ────────────────────────────
if MODE == 'report':
    print("\n[7AM REPORT] P&L Summary + Loss Detection...")
    from datetime import timedelta

    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    # ── Load all trades: today + yesterday ───────────────────────────────────
    all_records: list = []
    for day_str in [yesterday_str, today_str]:
        log_path = LOGS / f'trades_{day_str}.jsonl'
        if log_path.exists():
            for line in log_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    all_records.append(json.loads(line))
                except Exception:
                    pass

    print(f"  Loaded {len(all_records)} record(s) from today + yesterday")

    # ── Group records: latest entry per ticker, all exits ────────────────────
    entries_by_ticker: dict = {}
    exit_records: list = []

    for rec in all_records:
        action = rec.get('action', 'buy')
        ticker = rec.get('ticker')
        if not ticker:
            continue
        if action in ('buy', 'open'):
            entries_by_ticker[ticker] = rec   # keep latest entry per ticker
        elif action == 'exit':
            exit_records.append(rec)

    # ── Compute high-level P&L summary ───────────────────────────────────────
    total_deployed = sum(
        r.get('size_dollars', 0.0)
        for r in all_records
        if r.get('action') in ('buy', 'open')
    )
    total_exited = sum(r.get('size_dollars', 0.0) for r in exit_records)
    net_pnl_approx = round(total_exited - total_deployed, 2)

    print(f"  Deployed: ${total_deployed:.2f}  "
          f"Exited: ${total_exited:.2f}  "
          f"Net approx: ${net_pnl_approx:+.2f}")

    # ── Scan for losses: explicit exits with negative realized_pnl ───────────
    # A loss = action=="exit" AND realized_pnl < 0.
    # If realized_pnl is not stored in the record, compute it from
    # size_dollars: exit_value - entry_cost (cost basis from the open record).
    losses: list = []

    for exit_rec in exit_records:
        ticker = exit_rec.get('ticker')

        # Prefer a logged realized_pnl field; fall back to size_dollars diff
        realized_pnl = exit_rec.get('realized_pnl')
        if realized_pnl is None:
            entry = entries_by_ticker.get(ticker)
            if entry:
                exit_value   = float(exit_rec.get('size_dollars') or 0.0)
                entry_cost   = float(entry.get('size_dollars') or 0.0)
                realized_pnl = round(exit_value - entry_cost, 2)

        if realized_pnl is not None and realized_pnl < 0:
            entry = entries_by_ticker.get(ticker)
            losses.append({
                'ticker':       ticker,
                'side':         exit_rec.get('side', ''),
                'realized_pnl': realized_pnl,
                'entry_edge':   entry.get('edge') if entry else None,
                'source':       exit_rec.get('source') or (entry.get('source') if entry else ''),
                'timestamp':    exit_rec.get('timestamp', ''),
            })

    print(f"  Losses found: {len(losses)}")

    # ── Write optimizer review file if losses exist ──────────────────────────
    if losses:
        total_loss = round(sum(l['realized_pnl'] for l in losses), 2)

        review_file = LOGS / 'pending_optimizer_review.json'
        review_data = {
            'date':       today_str,
            'losses':     losses,
            'total_loss': total_loss,
        }
        review_file.write_text(json.dumps(review_data, indent=2), encoding='utf-8')
        print(f"  Wrote pending_optimizer_review.json — "
              f"{len(losses)} loss(es) totaling ${total_loss:.2f}")

        # ── Append optimizer alert ────────────────────────────────────────────
        alert_msg = (
            f"Loss review ready: {len(losses)} losing trade(s) totaling "
            f"${abs(total_loss):.2f}. Optimizer review needed."
        )
        push_alert('optimizer', alert_msg)
        print(f"  Alert queued: {alert_msg}")
    else:
        print("  No losses detected — skipping optimizer review file")

    log_cycle('done', {'mode': 'report', 'exit_count': len(exit_records), 'losses': len(losses)})
    print(f"\n7am report complete. {ts()}")
    sys.exit(0)

# ── STEP 1b: WALLET LIST REFRESH (full mode — once daily before scans) ───────
print("\n[1b] Refreshing smart money wallet list from Polymarket leaderboard...")
try:
    from bot.wallet_updater import update_wallet_list as _update_wallets
    _wallets_updated = _update_wallets()
    if not _wallets_updated:
        print("  Wallet refresh skipped — API unavailable, using existing list")
except Exception as e:
    print(f"  Wallet refresh error (non-fatal): {e}")

# ── STEP 2: SMART MONEY REFRESH (full mode only) ─────────────────────────────
print("\n[2] Refreshing smart money signal...")
try:
    import subprocess, sys as _sys
    r = subprocess.run(
        [_sys.executable, 'fetch_smart_money.py'],
        capture_output=True, text=True, timeout=45,
        cwd=str(Path(__file__).parent)
    )
    if r.returncode == 0:
        sm_cache = LOGS / 'crypto_smart_money.json'
        sm = json.loads(sm_cache.read_text(encoding='utf-8')) if sm_cache.exists() else {}
        direction = sm.get('direction', 'neutral')
        bull_pct  = sm.get('bull_pct', 0.5)
        print(f"  Smart money: {direction.upper()} ({bull_pct:.0%} bull)")
    else:
        direction = 'neutral'
        print(f"  Smart money fetch failed — using neutral")
except Exception as e:
    direction = 'neutral'
    print(f"  Smart money error: {e}")

# ── STEP 3: WEATHER OPPORTUNITY SCAN (full mode only) ────────────────────────
print("\n[3] Scanning for new weather opportunities...")
new_weather = []
try:
    from main import run_weather_scan
    new_weather = run_weather_scan(dry_run=DRY_RUN)
    if new_weather:
        print(f"  {len(new_weather)} new weather trade(s) executed")
        for t in new_weather:
            print(f"    {t.get('ticker')} {t.get('side','').upper()} edge={t.get('edge',0)*100:.0f}%")
    else:
        print("  No new weather opportunities above threshold")
except Exception as e:
    print(f"  Weather scan error: {e}")

# ── STEP 4: CRYPTO OPPORTUNITY SCAN (full mode only) ─────────────────────────
print("\n[4] Scanning for new crypto opportunities...")
new_crypto = []
try:
    # Get live prices
    prices = {}
    for sym, key in [('XBTUSD','btc'), ('ETHUSD','eth'), ('XRPUSD','xrp')]:
        try:
            r = requests.get(f'https://api.kraken.com/0/public/Ticker?pair={sym}', timeout=5)
            prices[key] = float(list(r.json()['result'].values())[0]['c'][0])
        except: pass

    btc = prices.get('btc', 70000)
    eth = prices.get('eth', 2000)
    xrp = prices.get('xrp', 1.38)
    print(f"  BTC=${btc:,.0f}  ETH=${eth:,.2f}  XRP=${xrp:.4f}")

    # Bearish block removed (approved 2026-03-12: CEO + David).
    # Direction signal is kept for logging/reporting below, but no longer
    # used to bias the edge model — the NO/high-strike logic runs regardless.
    drift_sigma = 0.0

    SERIES_CFG = [
        ('KXBTC', btc, 250, 0.025, 18),
        ('KXETH', eth, 10, 0.030, 18),
        ('KXXRP', xrp, 0.01, 0.045, 18),
    ]

    for series, spot, half_w, daily_vol, hours in SERIES_CFG:
        if spot == 0: continue
        sigma = daily_vol * math.sqrt(hours / 24)
        drift = drift_sigma * sigma

        r = requests.get(BASE, params={'series_ticker': series, 'status': 'open', 'limit': 50}, timeout=8)
        markets = r.json().get('markets', [])

        for m in markets:
            ticker = m.get('ticker','')
            if ticker in traded_tickers: continue
            ya = m.get('yes_ask') or 0
            na = m.get('no_ask') or 0
            if ya < 5 or ya > 92 or na < 5: continue
            close = m.get('close_time','')
            # Skip markets closing in less than 2 hours
            if close:
                try:
                    ct = datetime.fromisoformat(close.replace('Z','+00:00'))
                    mins_left = (ct - datetime.now(timezone.utc)).total_seconds() / 60
                    if mins_left < 120: continue
                except: pass

            try: band_mid = float(ticker.split('-B')[-1])
            except: continue

            prob_model = band_prob(spot, band_mid, half_w, sigma, drift)
            mkt_yes    = ya / 100
            edge_no    = mkt_yes - prob_model
            edge_yes   = prob_model - mkt_yes

            best_edge  = max(edge_no, edge_yes)
            best_action = 'no' if edge_no >= edge_yes else 'yes'
            best_price  = na if best_action == 'no' else ya

            if best_edge < config.CRYPTO_MIN_EDGE_THRESHOLD: continue
            if best_price > 95: continue  # near-limit orders are risky

            size = min(config.CRYPTO_MAX_POSITION_SIZE, 25)
            contracts = max(1, int(size / best_price * 100))
            actual_cost = round(contracts * best_price / 100, 2)

            new_crypto.append({
                'ticker': ticker, 'title': m.get('title', ticker),
                'side': best_action, 'price': best_price,
                'contracts': contracts, 'cost': actual_cost,
                'edge': round(best_edge, 3), 'series': series,
                'note': f'{series} {direction} | model={prob_model*100:.0f}% mkt={mkt_yes*100:.0f}% edge={best_edge*100:.0f}%',
            })

    # Sort by edge, take top 3 per run max
    new_crypto.sort(key=lambda x: x['edge'], reverse=True)

    # ── Issue 5: Daily cap check before executing crypto trades ───────────────
    try:
        # Use computed capital (deposits + realized P&L) — NOT client.get_balance()
        # which returns a stale Kalshi API demo balance.
        _total_capital  = get_computed_capital()
        _deployed_today = get_daily_exposure()
        _cap_remaining  = check_daily_cap(_total_capital, _deployed_today)
        if _cap_remaining <= 0:
            print(f"  [CapCheck] Daily cap reached (${_deployed_today:.2f} deployed, "
                  f"max ${_total_capital * 0.70:.2f}). Skipping crypto trades this cycle.")
            new_crypto = []
        else:
            print(f"  [CapCheck] Cap OK — ${_cap_remaining:.2f} remaining (${_deployed_today:.2f} deployed)")
    except Exception as e:
        print(f"  [CapCheck] Cap check error: {e} — proceeding with caution")

    for t in new_crypto[:3]:
        opp = {
            'ticker': t['ticker'], 'title': t['title'], 'side': t['side'],
            'action': 'buy', 'yes_price': t['price'] if t['side']=='yes' else 100-t['price'],
            'market_prob': t['price']/100, 'noaa_prob': None,
            'edge': t['edge'], 'size_dollars': t['cost'],
            'contracts': t['contracts'], 'source': 'crypto',
            'note': t['note'], 'timestamp': ts(), 'date': str(date.today()),
        }
        if DRY_RUN:
            log_trade(opp, t['cost'], t['contracts'], {'dry_run': True})
            log_activity(f"[AUTO-CRYPTO] BUY {t['side'].upper()} {t['ticker']} {t['contracts']}@{t['price']}c ${t['cost']:.2f} edge={t['edge']*100:.0f}%")
            print(f"  [DEMO] BUY {t['side'].upper()} {t['ticker']:38} {t['contracts']:3}@{t['price']:3}c ${t['cost']:.2f} edge={t['edge']*100:.0f}%")
        else:
            try:
                result = client.place_order(t['ticker'], t['side'], t['price'], t['contracts'])
                log_trade(opp, t['cost'], t['contracts'], result)
                print(f"  [LIVE] EXECUTED {t['ticker']}")
            except Exception as e:
                print(f"  ERROR {t['ticker']}: {e}")
        traded_tickers.add(t['ticker'])

    print(f"  {min(len(new_crypto),3)} crypto trade(s) executed")

except Exception as e:
    print(f"  Crypto scan error: {e}")
    import traceback; traceback.print_exc()

# ── STEP 4b: FED RATE DECISION SCAN (full mode only) ─────────────────────────
# v1: secondary window (2-7 days before FOMC). Captures structural mispricing.
# Requires: edge > 12% AND confidence > 55% (harder gate than crypto/weather).
# Favorite-longshot bias filter: never trades contracts below 15¢.
print("\n[4b] Scanning for Fed rate decision opportunities...")
new_fed = []
try:
    from fed_client import run_fed_scan, FOMC_DECISION_DATES_2026, is_in_signal_window

    in_window, fed_meeting, fed_days = is_in_signal_window()
    if not in_window:
        print(f"  Fed signal window inactive — next FOMC {fed_meeting} ({fed_days}d away)")
    else:
        fed_signal = run_fed_scan()

        if fed_signal and not fed_signal.get("skip_reason"):
            ticker     = fed_signal.get("ticker", "KXFEDDECISION-?")
            side       = fed_signal.get("direction", "yes")
            edge_pct   = fed_signal.get("edge", 0) * 100
            conf_pct   = fed_signal.get("confidence", 0) * 100
            outcome    = fed_signal.get("outcome", "?")
            mkt_price  = int(fed_signal.get("yes_ask", 50))
            bet_price  = mkt_price if side == "yes" else 100 - mkt_price

            # Size: same formula as other modules — min($25, 2.5% of capital)
            try:
                _fed_capital  = get_computed_capital()
                _fed_deployed = get_daily_exposure()
                _fed_cap_ok   = check_daily_cap(_fed_capital, _fed_deployed)
            except Exception:
                _fed_cap_ok   = 25.0  # conservative fallback

            if _fed_cap_ok <= 0:
                print(f"  [CapCheck] Daily cap reached — skipping Fed trade")
            elif ticker in traded_tickers:
                print(f"  Already traded {ticker} this cycle — skipping")
            else:
                size       = min(25.0, _fed_cap_ok)
                contracts  = max(1, int(size / bet_price * 100))
                actual_cost = round(contracts * bet_price / 100, 2)

                opp = {
                    "ticker":     ticker,
                    "title":      fed_signal.get("title", ticker),
                    "side":       side,
                    "action":     "buy",
                    "yes_price":  mkt_price,
                    "market_prob": fed_signal.get("market_price", 0.5),
                    "noaa_prob":  None,
                    "edge":       fed_signal.get("edge"),
                    "confidence": fed_signal.get("confidence"),
                    "size_dollars": actual_cost,
                    "contracts":  contracts,
                    "source":     "fed",
                    "outcome":    outcome,
                    "meeting_date": fed_signal.get("meeting_date"),
                    "days_to_meeting": fed_signal.get("days_to_meeting"),
                    "fedwatch_prob": fed_signal.get("prob"),
                    "note": (f"FOMC {fed_signal.get('meeting_date')} {outcome.upper()} "
                             f"FedWatch={fed_signal.get('prob', 0):.0%} "
                             f"Kalshi={fed_signal.get('market_price', 0):.0%} "
                             f"edge={edge_pct:.0f}%"),
                    "timestamp":  ts(),
                    "date":       str(date.today()),
                }

                if DRY_RUN:
                    log_trade(opp, actual_cost, contracts, {"dry_run": True})
                    log_activity(
                        f"[AUTO-FED] BUY {side.upper()} {ticker} {contracts}@{bet_price}c "
                        f"${actual_cost:.2f} edge={edge_pct:.0f}% conf={conf_pct:.0f}%"
                    )
                    print(
                        f"  [DEMO] BUY {side.upper()} {ticker:38} "
                        f"{contracts:3}@{bet_price:3}c ${actual_cost:.2f} "
                        f"edge={edge_pct:.0f}% conf={conf_pct:.0f}% [{outcome}]"
                    )
                else:
                    try:
                        result = client.place_order(ticker, side, bet_price, contracts)
                        log_trade(opp, actual_cost, contracts, result)
                        log_activity(
                            f"[AUTO-FED] EXECUTED {ticker} {side.upper()} "
                            f"{contracts}@{bet_price}c edge={edge_pct:.0f}%"
                        )
                        print(f"  [LIVE] EXECUTED Fed trade: {ticker}")
                    except Exception as e:
                        print(f"  ERROR executing Fed trade {ticker}: {e}")

                traded_tickers.add(ticker)
                new_fed.append(opp)

        elif fed_signal and fed_signal.get("skip_reason"):
            print(f"  Fed signal skipped: {fed_signal['skip_reason']}")
        else:
            print(f"  No Fed edge in window ({fed_days}d to {fed_meeting} FOMC)")

except Exception as e:
    print(f"  Fed scan error: {e}")
    import traceback; traceback.print_exc()

# ── STEP 5: SECURITY AUDIT (weekly — Sunday only) ───────────────────────────
if datetime.now().weekday() == 6:  # Sunday
    print("\n[5] Weekly security audit...")
    try:
        import subprocess, sys as _sys
        r = subprocess.run([_sys.executable, 'security_audit.py'],
                          capture_output=True, text=True, timeout=30,
                          cwd=str(Path(__file__).parent))
        if 'WARNING' in r.stdout:
            push_alert('security', 'Security audit found issues — review security_audit output')
            print("  ALERT: issues found — check logs")
        else:
            print("  Clean — no issues found")
    except Exception as e:
        print(f"  Audit error: {e}")

# ── DONE ─────────────────────────────────────────────────────────────────────
summary = {
    'weather_trades': len(new_weather) if new_weather else 0,
    'crypto_trades':  min(len(new_crypto), 3),
    'fed_trades':     len(new_fed) if new_fed else 0,
    'smart_money':    direction,
    'auto_exits':     len(actions_taken) if 'actions_taken' in dir() else 0,
}
log_cycle('done', summary)

print(f"\n{'='*60}")
print(f"  CYCLE COMPLETE  {ts()}")
print(f"  Weather: {summary['weather_trades']} new | Crypto: {summary['crypto_trades']} new | Fed: {summary['fed_trades']} new")
print(f"  Auto-exits: {summary['auto_exits']} | Signal: {direction.upper()}")
print(f"{'='*60}\n")
