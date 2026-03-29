# -*- coding: utf-8 -*-
# backtest_engine.py — Ruppert Backtest Framework
# Core replay loop: iterates dates/hours, simulates signals, applies strategy, records P&L.

import re
from datetime import datetime, timedelta
from data_loader import (
    load_kalshi_weather,
    load_kalshi_crypto,
    load_openmeteo_forecasts,
    load_kraken_ohlc,
)
from signal_simulator import simulate_weather_signal, simulate_crypto_signal
from strategy_simulator import DEFAULT_CONFIG, should_trade, compute_pnl

# Known Kraken pairs for crypto markets
_KNOWN_PAIRS = ["XBTUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "XRPUSD"]

# Month abbreviation -> month number
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,  "MAY": 5,  "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Series -> fallback threshold_f (used when threshold can't be parsed from ticker)
_DEFAULT_THRESHOLDS = {
    "KXHIGHCHI":  46.5,
    "KXHIGHNY":   50.0,
    "KXHIGHLAX":  65.0,
    "KXHIGHMIA":  75.0,
    "KXHIGHTDAL": 60.0,
    "KXHIGHDEN":  48.0,
    "KXHIGHTSEA": 52.0,
    "KXHIGHPHIL": 50.0,
    "KXHIGHPHX":  72.0,
    "KXHIGHTATL": 58.0,
    "KXHIGHTDC":  55.0,
    "KXHIGHTMIN": 40.0,
    "KXHIGHTLV":  68.0,
    "KXHIGHTOKC": 55.0,
    "KXHIGHTSATX":60.0,
    "KXHIGHTSFO": 60.0,
    "KXHIGHAUS":  68.0,
    "KXHIGHTHOU": 65.0,
    "KXHIGHHOU":  65.0,
}


def _parse_ticker_date(date_code: str) -> str:
    """
    Parse date code from Kalshi ticker format: '26MAR12' -> '2026-03-12'
    Format: YY + MON + DD  (e.g. 26MAR12)
    """
    m = re.match(r"(\d{2})([A-Z]{3})(\d{2})", date_code)
    if not m:
        return ""
    yy, mon, dd = m.group(1), m.group(2), m.group(3)
    month_num = _MONTH_MAP.get(mon, 0)
    if not month_num:
        return ""
    return f"20{yy}-{month_num:02d}-{int(dd):02d}"


def _parse_market_fields(market: dict) -> dict:
    """
    Enrich a market dict with derived fields: series, settle_date, threshold_f, direction.

    Kalshi ticker format: KXHIGHNY-26MAR12-T71
      - series:      KXHIGHNY
      - settle_date: 2026-03-12  (from date code)
      - threshold part: T71 -> threshold_f=71.0, above=True
                        B70.5 -> threshold_f=70.5, above=False

    Crypto: KXBTC-26MAR1321-T78999.99
      - series:      KXBTC
      - settle_date: 2026-03-13
    """
    ticker = market.get("ticker", "")
    parts = ticker.split("-")

    m = dict(market)  # copy

    # Series
    m.setdefault("series", parts[0] if parts else "")

    # settle_date from date code (second segment: e.g. 26MAR12 or 26MAR1321)
    if len(parts) >= 2:
        # Handle both 26MAR12 (6 chars) and 26MAR1321 (crypto has time too)
        date_code = re.match(r"(\d{2}[A-Z]{3}\d{2})", parts[1])
        if date_code:
            m.setdefault("settle_date", _parse_ticker_date(date_code.group(1)))
        else:
            m.setdefault("settle_date", "")
    else:
        m.setdefault("settle_date", "")

    # threshold_f and is_above from third segment
    if len(parts) >= 3:
        thresh_part = parts[-1]  # e.g. T71 or B70.5
        tp_match = re.match(r"([TB])([\d.]+)", thresh_part)
        if tp_match:
            direction_char = tp_match.group(1)
            try:
                m.setdefault("threshold_f", float(tp_match.group(2)))
            except ValueError:
                m.setdefault("threshold_f",
                             _DEFAULT_THRESHOLDS.get(m["series"], 50.0))
            m["is_above"] = (direction_char == "T")  # T = above, B = below
        else:
            m.setdefault("threshold_f",
                         _DEFAULT_THRESHOLDS.get(m["series"], 50.0))
            m.setdefault("is_above", True)
    else:
        m.setdefault("threshold_f", _DEFAULT_THRESHOLDS.get(m.get("series",""), 50.0))
        m.setdefault("is_above", True)

    return m


def _date_range(start_date: str, end_date: str):
    """Yield ISO date strings from start_date to end_date inclusive."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end   = datetime.strptime(end_date,   "%Y-%m-%d")
    current = start
    while current <= end:
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=1)


def _classify_market(market: dict) -> str:
    """Return 'weather', 'crypto', or 'unknown'."""
    series = market.get("series", "")
    ticker = market.get("ticker", "")
    title  = (market.get("title") or "").lower()

    if "KXHIGH" in series or "KXLOW" in series or "temperature" in title or "weather" in title:
        return "weather"
    if any(c in series for c in ("BTC", "ETH", "SOL", "DOGE", "BNB", "XBT")) or "KXBTC" in series or "KXETH" in series:
        return "crypto"
    # Fallback: guess from ticker patterns
    if any(k in ticker.upper() for k in ("BTC", "ETH", "SOL", "DOGE", "BNB")):
        return "crypto"
    if any(k in ticker.upper() for k in ("HIGH", "LOW", "TEMP")):
        return "weather"
    return "unknown"


def run_backtest(
    start_date: str = "2026-02-27",
    end_date: str   = "2026-03-13",
    scan_hours_utc: list = None,
    config: dict = None,
    starting_capital: float = 400.0,
) -> dict:
    """
    Replay all Kalshi settled markets between start_date and end_date.
    For each date × scan_hour, simulate signals and apply strategy filter.
    Compute P&L using settlement prices.

    Returns a results dict suitable for report.py.
    """
    if scan_hours_utc is None:
        scan_hours_utc = [7, 12, 15, 22]
    if config is None:
        config = dict(DEFAULT_CONFIG)

    # ---- Load all data upfront ----
    weather_markets = load_kalshi_weather()
    crypto_markets  = load_kalshi_crypto()
    forecasts       = load_openmeteo_forecasts()

    kraken_candles = {}
    for pair in _KNOWN_PAIRS:
        candles = load_kraken_ohlc(pair)
        if candles:
            kraken_candles[pair] = candles

    # Parse and index markets by settle_date
    weather_by_date: dict = {}
    for m in weather_markets:
        pm = _parse_market_fields(m)
        d = pm.get("settle_date", "")
        if d:
            weather_by_date.setdefault(d, []).append(pm)

    crypto_by_date: dict = {}
    for m in crypto_markets:
        pm = _parse_market_fields(m)
        d = pm.get("settle_date", "")
        if d:
            crypto_by_date.setdefault(d, []).append(pm)

    # ---- State ----
    capital = starting_capital
    trades = []
    daily_pnl: dict = {}
    capital_curve = []
    seen_tickers: set = set()   # avoid double-trading same ticker across scan hours

    module_stats = {
        "weather": {"trades": 0, "wins": 0, "pnl": 0.0},
        "crypto":  {"trades": 0, "wins": 0, "pnl": 0.0},
    }
    city_pnl: dict = {}

    # ---- Replay loop ----
    for date_str in _date_range(start_date, end_date):
        day_trades = []
        daily_deployed = 0.0
        daily_cap_limit = capital * config["daily_cap_pct"]
        seen_tickers_today: set = set()

        for scan_hour in sorted(scan_hours_utc):
            # ---- Weather markets ----
            for market in weather_by_date.get(date_str, []):
                ticker = market.get("ticker", "")
                if ticker in seen_tickers_today:
                    continue

                # Only process settled/finalized markets
                if market.get('status') not in ('settled', 'finalized'):
                    continue

                # Skip bracket (B) markets — signal direction not yet implemented; T-only for initial backtest
                if '-B' in ticker:
                    continue

                # Fields already parsed by _parse_market_fields above
                series = market.get("series", "")
                threshold_f = float(market.get("threshold_f",
                                    _DEFAULT_THRESHOLDS.get(series, 50.0)))
                is_above = market.get("is_above", True)

                signal = simulate_weather_signal(
                    series=series,
                    target_date=date_str,
                    threshold_f=threshold_f,
                    scan_hour_utc=scan_hour,
                    forecasts=forecasts,
                )

                # Inject market_prob from yes_ask
                # yes_ask and last_price from Kalshi API are in dollars (0.01-1.0), not cents
                yes_ask = market.get("yes_ask")
                last_price = market.get("last_price", 0.50)
                if yes_ask is None or yes_ask <= 0:
                    yes_ask = 1.0 - last_price if last_price else 0.50
                signal["market_prob"] = float(yes_ask)   # already 0-1 (dollars)

                available_capital = min(capital, daily_cap_limit - daily_deployed)
                if available_capital <= 0:
                    break

                decision = should_trade(
                    signal=signal,
                    market=market,
                    capital=available_capital,
                    config=config,
                    module="weather",
                )

                if decision["trade"]:
                    size = decision["size"]
                    side = signal["direction"]
                    # yes_ask in dollars -> convert to cents for entry price
                    entry_cents = (yes_ask * 100.0 if side == "YES" else (1.0 - yes_ask) * 100.0)

                    trade_record = {
                        "ticker":             ticker,
                        "series":             series,
                        "settle_date":        date_str,
                        "scan_hour_utc":      scan_hour,
                        "module":             "weather",
                        "side":               side,
                        "entry_price_cents":  entry_cents,
                        "size_dollars":       size,
                        "contracts":          round(size / (entry_cents / 100.0), 2) if entry_cents > 0 else 0,
                        "signal_prob":        signal.get("prob"),
                        "market_prob":        signal.get("market_prob"),
                        "edge":               signal.get("edge"),
                        "confidence":         signal.get("confidence"),
                        "threshold_f":        threshold_f,
                        "last_price":         last_price,
                        "reason":             decision["reason"],
                    }

                    pnl = compute_pnl(trade_record, market)
                    trade_record["pnl"] = pnl
                    trade_record["won"] = pnl > 0

                    day_trades.append(trade_record)
                    seen_tickers_today.add(ticker)
                    daily_deployed += size

                    # City tracking
                    city = re.sub(r"^KX(HIGH|LOW|HIGHT)", "", series)
                    city_pnl[city] = city_pnl.get(city, 0.0) + pnl

                    mod = module_stats["weather"]
                    mod["trades"] += 1
                    mod["pnl"] += pnl
                    if pnl > 0:
                        mod["wins"] += 1

            # ---- Crypto markets ----
            for market in crypto_by_date.get(date_str, []):
                ticker = market.get("ticker", "")
                if ticker in seen_tickers_today:
                    continue

                # Only process settled/finalized markets
                if market.get('status') not in ('settled', 'finalized'):
                    continue

                series = market.get("series", "")
                signal = simulate_crypto_signal(
                    series=series,
                    target_date=date_str,
                    scan_hour_utc=scan_hour,
                    kraken_candles=kraken_candles,
                )

                # yes_ask and last_price from Kalshi API are in dollars (0.01-1.0), not cents
                yes_ask = market.get("yes_ask")
                last_price = market.get("last_price", 0.50)
                if yes_ask is None or yes_ask <= 0:
                    yes_ask = 1.0 - last_price if last_price else 0.50
                signal["market_prob"] = float(yes_ask)   # already 0-1 (dollars)

                available_capital = min(capital, daily_cap_limit - daily_deployed)
                if available_capital <= 0:
                    break

                decision = should_trade(
                    signal=signal,
                    market=market,
                    capital=available_capital,
                    config=config,
                    module="crypto",
                )

                if decision["trade"]:
                    size = decision["size"]
                    side = signal["direction"]
                    # yes_ask in dollars -> convert to cents for entry price
                    entry_cents = (yes_ask * 100.0 if side == "YES" else (1.0 - yes_ask) * 100.0)

                    trade_record = {
                        "ticker":             ticker,
                        "series":             series,
                        "settle_date":        date_str,
                        "scan_hour_utc":      scan_hour,
                        "module":             "crypto",
                        "side":               side,
                        "entry_price_cents":  entry_cents,
                        "size_dollars":       size,
                        "contracts":          round(size / (entry_cents / 100.0), 2) if entry_cents > 0 else 0,
                        "signal_prob":        signal.get("prob"),
                        "market_prob":        signal.get("market_prob"),
                        "edge":               signal.get("edge"),
                        "confidence":         signal.get("confidence"),
                        "change_24h":         signal.get("change_24h"),
                        "last_price":         last_price,
                        "reason":             decision["reason"],
                    }

                    pnl = compute_pnl(trade_record, market)
                    trade_record["pnl"] = pnl
                    trade_record["won"] = pnl > 0

                    day_trades.append(trade_record)
                    seen_tickers_today.add(ticker)
                    daily_deployed += size

                    mod = module_stats["crypto"]
                    mod["trades"] += 1
                    mod["pnl"] += pnl
                    if pnl > 0:
                        mod["wins"] += 1

        # ---- End of day ----
        day_total_pnl = sum(t["pnl"] for t in day_trades)
        daily_pnl[date_str] = round(day_total_pnl, 4)
        capital = max(0.0, capital + day_total_pnl)
        capital_curve.append((date_str, round(capital, 2)))
        trades.extend(day_trades)

    # ---- Aggregate results ----
    total_pnl = sum(t["pnl"] for t in trades)
    total_trades = len(trades)
    wins = sum(1 for t in trades if t.get("won", False))
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    # Module win rates
    for mod_name, mod in module_stats.items():
        n = mod["trades"]
        mod["win_rate"] = round(mod["wins"] / n, 4) if n > 0 else 0.0
        mod["pnl"] = round(mod["pnl"], 4)

    return {
        "trades":         trades,
        "total_pnl":      round(total_pnl, 4),
        "win_rate":       round(win_rate, 4),
        "total_trades":   total_trades,
        "daily_pnl":      {d: round(v, 4) for d, v in daily_pnl.items()},
        "by_module":      module_stats,
        "city_pnl":       {c: round(v, 4) for c, v in city_pnl.items()},
        "capital_curve":  capital_curve,
        "starting_capital": starting_capital,
        "ending_capital":   round(capital, 2),
        "config":         config,
        "start_date":     start_date,
        "end_date":       end_date,
    }


def run_accuracy_backtest(
    start_date: str,
    end_date: str,
    scan_hours_utc: list = None,
    config: dict = None,
    starting_capital: float = 400.0,
) -> dict:
    """
    For each settled T-market in date range:
      1. Simulate signal using historical forecast data
      2. Check if signal would have triggered (edge >= min_edge, confidence >= min_confidence)
      3. Check if direction was correct (YES signal + YES won, or NO signal + NO won)

    Returns accuracy report -- NO P&L calculations.
    """
    import datetime as dt
    from data_loader import load_kalshi_weather, load_openmeteo_forecasts
    from signal_simulator import simulate_weather_signal

    if scan_hours_utc is None:
        scan_hours_utc = [7, 12, 15, 22]
    if config is None:
        from strategy_simulator import DEFAULT_CONFIG
        config = dict(DEFAULT_CONFIG)

    markets = load_kalshi_weather()
    forecasts = load_openmeteo_forecasts()

    results = []
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)

    for market in markets:
        ticker = market.get('ticker', '')

        # T-only filter
        if '-B' in ticker or '-T' not in ticker:
            continue

        # Parse settlement date from close_time
        close_time = market.get('close_time', '')
        try:
            settle_date = dt.datetime.fromisoformat(
                close_time.replace('Z', '+00:00')
            ).date()
        except Exception:
            continue

        if not (start <= settle_date <= end):
            continue

        # Need settlement outcome
        last_price = market.get('last_price')
        if last_price is None:
            continue
        yes_won = last_price >= 0.50

        # Parse series + threshold from ticker
        # e.g. KXHIGHNY-26MAR12-T71 -> series=KXHIGHNY, threshold=71.0
        parts = ticker.split('-')
        if len(parts) < 3:
            continue
        series = parts[0]
        threshold_str = parts[2].replace('T', '').replace('B', '')
        try:
            threshold_f = float(threshold_str)
        except ValueError:
            continue

        # Try each scan hour; record the first one that produces a signal
        for scan_hour in scan_hours_utc:
            # Skip same-day markets after cutoff
            if settle_date == dt.datetime.utcnow().date() and scan_hour >= config.get('same_day_skip_hour', 14):
                continue

            # Simulate signal
            signal = simulate_weather_signal(
                series=series,
                target_date=settle_date.isoformat(),
                threshold_f=threshold_f,
                scan_hour_utc=scan_hour,
                forecasts=forecasts,
            )

            if signal is None:
                continue

            prob = signal.get('prob', 0)
            confidence = signal.get('confidence', 0)

            # Determine direction
            direction = 'YES' if prob >= 0.5 else 'NO'

            # Edge = how far signal is from 50/50 (no market price available)
            edge = abs(prob - 0.5)

            # Did signal trigger?
            triggered = (
                edge >= config.get('min_edge_weather', 0.15)
                and confidence >= config.get('min_confidence_weather', 0.55)
            )

            # Was it correct?
            correct = None
            if triggered:
                correct = (
                    (direction == 'YES' and yes_won)
                    or (direction == 'NO' and not yes_won)
                )

            results.append({
                'ticker':      ticker,
                'series':      series,
                'settle_date': settle_date.isoformat(),
                'scan_hour':   scan_hour,
                'threshold_f': threshold_f,
                'prob':        round(prob, 3),
                'confidence':  round(confidence, 3),
                'edge':        round(edge, 3),
                'direction':   direction,
                'yes_won':     yes_won,
                'triggered':   triggered,
                'correct':     correct,
            })
            break  # only simulate first valid scan hour per market

    # ---- Aggregate ----
    triggered_results = [r for r in results if r['triggered']]
    correct_results   = [r for r in triggered_results if r['correct']]

    total_markets  = len(results)
    total_triggered = len(triggered_results)
    total_correct   = len(correct_results)
    trigger_rate    = total_triggered / total_markets if total_markets else 0
    win_rate        = total_correct / total_triggered if total_triggered else 0

    # By series
    by_series: dict = {}
    for r in triggered_results:
        s = r['series']
        if s not in by_series:
            by_series[s] = {'triggered': 0, 'correct': 0}
        by_series[s]['triggered'] += 1
        if r['correct']:
            by_series[s]['correct'] += 1

    return {
        'total_markets_evaluated': total_markets,
        'total_triggered':         total_triggered,
        'total_correct':           total_correct,
        'trigger_rate':            round(trigger_rate, 3),
        'win_rate':                round(win_rate, 3),
        'by_series':               by_series,
        'all_results':             results,
        'start_date':              start_date,
        'end_date':                end_date,
        'config':                  config,
    }
