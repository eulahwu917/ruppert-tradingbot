"""
P&L Correction Script - P0 Bug Fix
Re-verify all @ 0c settlement-time exits via Kalshi API
"""
import sys
import json
import os
import re
from datetime import datetime, timezone

sys.path.insert(0, r'C:\Users\David Wu\.openclaw\workspace')
sys.path.insert(0, r'C:\Users\David Wu\.openclaw\workspace\environments\demo')
from agents.ruppert.data_analyst.kalshi_client import KalshiClient

TRADES_DIR = r'C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\trades'
# pnl_cache.json removed — P&L computed live from logs by compute_closed_pnl_from_logs()
REPORT_PATH = r'C:\Users\David Wu\.openclaw\workspace\memory\agents\ds-pnl-correction-2026-03-31.md'

# Settlement minutes
SETTLEMENT_MINUTES = {0, 15, 30, 45}

def parse_ts(ts_str):
    """Parse timestamp string to datetime."""
    for fmt in ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']:
        try:
            return datetime.strptime(ts_str, fmt)
        except:
            pass
    return None

def is_near_settlement(ts_str, within_sec=30):
    """Check if timestamp is within N seconds of a settlement time (XX:00, XX:15, XX:30, XX:45)."""
    dt = parse_ts(ts_str)
    if dt is None:
        return False
    total_seconds = dt.minute * 60 + dt.second
    for sm in SETTLEMENT_MINUTES:
        boundary = sm * 60
        if abs(total_seconds - boundary) <= within_sec:
            return True
        # Handle edge case around hour boundary (XX:59:30+ is within 30s of next XX:00)
        if sm == 0 and (total_seconds >= 3570):  # 59:30+
            return True
    return False

def load_all_trades():
    """Load all trade records from JSONL files."""
    trades = []
    for fname in sorted(os.listdir(TRADES_DIR)):
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(TRADES_DIR, fname)
        date_str = fname.replace('trades_', '').replace('.jsonl', '')
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    rec['_source_file'] = fname
                    rec['_source_date'] = date_str
                    trades.append(rec)
                except:
                    pass
    return trades

LOW_BID_PATTERN = re.compile(r'@ [0-9]c\b')  # matches @ 0c through @ 9c

def find_suspect_exits(trades):
    """Find all low-bid (0c-9c) NO-side exits near settlement time."""
    suspects = []
    for t in trades:
        if t.get('action') != 'exit':
            continue
        ad = t.get('action_detail', '')
        if not LOW_BID_PATTERN.search(ad):
            continue
        ts = t.get('timestamp', '')
        if is_near_settlement(ts):
            suspects.append(t)
    return suspects

def main():
    print("Loading trades...")
    trades = load_all_trades()
    print(f"Total records: {len(trades)}")
    
    suspects = find_suspect_exits(trades)
    print(f"Suspect low-bid (0-9c) settlement exits: {len(suspects)}")
    
    # Get unique tickers
    unique_tickers = list(set(t['ticker'] for t in suspects))
    print(f"Unique tickers: {len(unique_tickers)}")
    
    # Query Kalshi API for each ticker
    print("\nQuerying Kalshi API...")
    client = KalshiClient()
    ticker_results = {}
    failed_tickers = []
    
    for ticker in sorted(unique_tickers):
        try:
            m = client.get_market(ticker)
            result = m.get('result')
            ticker_results[ticker] = result
            print(f"  {ticker}: result={result}")
        except Exception as e:
            print(f"  {ticker}: ERROR - {e}")
            ticker_results[ticker] = 'ERROR'
            failed_tickers.append(ticker)
    
    # Build idempotency guard: collect original_trade_ids already corrected in any log file
    already_corrected = set()
    for fname in sorted(os.listdir(TRADES_DIR)):
        if not fname.endswith('.jsonl'):
            continue
        fpath = os.path.join(TRADES_DIR, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get('action') == 'exit_correction' and rec.get('original_trade_id'):
                        already_corrected.add(rec['original_trade_id'])
                except:
                    pass
    if already_corrected:
        print(f"Idempotency: {len(already_corrected)} trade(s) already have correction records — will skip.")

    # Classify each suspect exit
    correction_records = []
    corrected_exits = []
    
    for t in suspects:
        ticker = t['ticker']
        original_trade_id = t.get('trade_id', '')

        # Idempotency check: skip if correction already written
        if original_trade_id in already_corrected:
            print(f"[SKIP] Already corrected: {ticker}")
            continue

        result = ticker_results.get(ticker, 'UNKNOWN')
        logged_pnl = t.get('pnl', 0) or 0
        
        if result == 'yes':
            # WE LOST. True P&L = -logged_pnl
            true_pnl = -abs(logged_pnl)
            pnl_delta = true_pnl - logged_pnl  # = -2 * logged_pnl
            
            correction_rec = {
                'trade_id': t.get('trade_id', '') + '_correction',
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f'),
                'date': t.get('date') or t.get('_source_date', ''),
                'ticker': ticker,
                'title': t.get('title', ''),
                'side': t.get('side', ''),
                'action': 'exit_correction',
                'action_detail': f"CORRECTION for {t.get('action_detail', '')}",
                'source': 'pnl_correction_script',
                'module': t.get('module', ''),
                'contracts': t.get('contracts', 0),
                'entry_price': t.get('entry_price', 0),
                'exit_price': t.get('exit_price', 0),
                'logged_pnl': logged_pnl,
                'true_pnl': round(true_pnl, 2),
                'pnl_correction': round(pnl_delta, 2),
                'pnl': round(pnl_delta, 2),
                'reason': 'kalshi_settlement_yes_win_correction',
                'original_trade_id': t.get('trade_id', ''),
                'original_timestamp': t.get('timestamp', ''),
                'kalshi_result': result
            }
            correction_records.append(correction_rec)
            corrected_exits.append({
                'trade': t,
                'result': result,
                'logged_pnl': logged_pnl,
                'true_pnl': true_pnl,
                'pnl_delta': pnl_delta
            })
        elif result == 'no':
            # WE WON, logged P&L is correct
            corrected_exits.append({
                'trade': t,
                'result': result,
                'logged_pnl': logged_pnl,
                'true_pnl': logged_pnl,
                'pnl_delta': 0
            })
        else:
            # Unknown/error
            corrected_exits.append({
                'trade': t,
                'result': result,
                'logged_pnl': logged_pnl,
                'true_pnl': logged_pnl,  # Assume correct if unknown
                'pnl_delta': 0
            })
    
    # Write correction records to appropriate trade log files
    print(f"\nWriting {len(correction_records)} correction records...")
    corrections_by_date = {}
    for rec in correction_records:
        d = rec.get('date', 'unknown')
        # The original exit might be on a different date than source file
        # Use the source file date of the original trade
        orig_id = rec['original_trade_id']
        orig_trade = next((t for t in suspects if t.get('trade_id') == orig_id), None)
        if orig_trade:
            d = orig_trade.get('_source_date', d)
        corrections_by_date.setdefault(d, []).append(rec)
    
    for date_str, recs in corrections_by_date.items():
        fpath = os.path.join(TRADES_DIR, f'trades_{date_str}.jsonl')
        with open(fpath, 'a', encoding='utf-8') as f:
            for rec in recs:
                f.write(json.dumps(rec) + '\n')
        print(f"  Appended {len(recs)} corrections to trades_{date_str}.jsonl")
    
    # Compute corrected P&L
    # Load all trades again to include corrections
    print("\nComputing corrected P&L...")
    
    # All exit records (excluding correction records which are already deltas)
    all_exits = [t for t in trades if t.get('action') == 'exit']
    
    # Sum of logged P&L (all exits)
    total_logged_pnl = sum(t.get('pnl') or 0 for t in all_exits)
    
    # Total correction delta
    total_correction = sum(r['pnl_correction'] for r in correction_records)
    
    # True total P&L
    total_true_pnl = total_logged_pnl + total_correction
    
    print(f"  Total logged P&L: ${total_logged_pnl:.2f}")
    print(f"  Total correction: ${total_correction:.2f}")
    print(f"  True total P&L:   ${total_true_pnl:.2f}")
    
    # P&L by date
    pnl_by_date_logged = {}
    pnl_by_date_true = {}
    
    for t in all_exits:
        d = t.get('date') or t.get('_source_date', 'unknown')
        pnl_by_date_logged[d] = pnl_by_date_logged.get(d, 0) + (t.get('pnl') or 0)
        pnl_by_date_true[d] = pnl_by_date_true.get(d, 0) + (t.get('pnl') or 0)
    
    for rec in correction_records:
        orig_id = rec['original_trade_id']
        orig_trade = next((t for t in suspects if t.get('trade_id') == orig_id), None)
        d = orig_trade.get('_source_date', rec.get('date', 'unknown')) if orig_trade else rec.get('date', 'unknown')
        pnl_by_date_true[d] = pnl_by_date_true.get(d, 0) + rec['pnl_correction']
    
    # Win/loss rates by module
    # For non-corrected exits, determine win/loss based on pnl > 0
    # For suspect exits, use actual API result
    
    def classify_exit_for_module(t, corrected_exits_map):
        """Returns (module, is_win, logged_pnl, true_pnl)"""
        module_raw = t.get('module', 'unknown')
        # Normalize module names
        if 'crypto_15m' in module_raw or module_raw == 'crypto_15m':
            module = 'crypto_15m_dir'
        elif 'crypto_1h' in module_raw or module_raw in ('crypto', 'crypto_1h_band'):
            module = 'crypto_1h_band'
        elif 'weather' in module_raw:
            module = 'weather'
        else:
            module = module_raw
        
        trade_id = t.get('trade_id', '')
        if trade_id in corrected_exits_map:
            ce = corrected_exits_map[trade_id]
            logged_pnl = ce['logged_pnl']
            true_pnl = ce['true_pnl']
            is_win_logged = logged_pnl > 0
            is_win_true = true_pnl > 0
        else:
            logged_pnl = t.get('pnl') or 0
            true_pnl = logged_pnl
            is_win_logged = logged_pnl > 0
            is_win_true = logged_pnl > 0
        
        return module, is_win_logged, is_win_true, logged_pnl, true_pnl
    
    corrected_exits_map = {ce['trade'].get('trade_id'): ce for ce in corrected_exits}
    
    module_stats = {}
    for t in all_exits:
        module, iw_logged, iw_true, lpnl, tpnl = classify_exit_for_module(t, corrected_exits_map)
        if module not in module_stats:
            module_stats[module] = {
                'wins_logged': 0, 'losses_logged': 0,
                'wins_true': 0, 'losses_true': 0,
                'pnl_logged': 0, 'pnl_true': 0
            }
        s = module_stats[module]
        if iw_logged: s['wins_logged'] += 1
        else: s['losses_logged'] += 1
        if iw_true: s['wins_true'] += 1
        else: s['losses_true'] += 1
        s['pnl_logged'] += lpnl
        s['pnl_true'] += tpnl
    
    # P&L is now computed live from logs by compute_closed_pnl_from_logs().
    # No pnl_cache.json write — correction records in .jsonl are the source of truth.
    print(f"\nCorrection records written to .jsonl logs (no pnl_cache.json — live compute).")
    
    # Generate report
    print("\nGenerating report...")
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S PDT')
    
    report_lines = [
        "# P&L Correction Report — P0 Bug: NO-side low-bid (0-9c) Settlement Exits",
        f"**Generated:** {now_str}",
        "",
        "## Summary",
        "",
        "**Bug:** `WS_EXIT 95c_rule_no @ 0-9c` triggered when Kalshi orderbook thins at settlement.",
        "The code fired assuming NO was winning (yes_bid low), but low bids near settlement can indicate",
        "orderbook clearing regardless of winner. All confirmed suspect trades verified via Kalshi API.",
        "",
        f"- Suspect exits identified: **{len(suspects)}**",
        f"- API-confirmed losses (result=yes): **{len([c for c in corrected_exits if c['result'] == 'yes'])}**",
        f"- Confirmed wins (result=no): **{len([c for c in corrected_exits if c['result'] == 'no'])}**",
        f"- API errors/unknown: **{len([c for c in corrected_exits if c['result'] not in ('yes', 'no')])}**",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Logged P&L (all time) | ${total_logged_pnl:,.2f} |",
        f"| Total correction delta | ${total_correction:,.2f} |",
        f"| **True P&L (all time)** | **${total_true_pnl:,.2f}** |",
        "",
        "---",
        "",
        "## Date-by-Date P&L Table",
        "",
        "| Date | Logged P&L | Corrected P&L | Delta |",
        "|------|-----------|---------------|-------|",
    ]
    
    for d in sorted(pnl_by_date_logged.keys()):
        lp = pnl_by_date_logged.get(d, 0)
        tp = pnl_by_date_true.get(d, 0)
        delta = tp - lp
        delta_str = f"${delta:,.2f}" if delta == 0 else f"**${delta:,.2f}**"
        report_lines.append(f"| {d} | ${lp:,.2f} | ${tp:,.2f} | {delta_str} |")
    
    report_lines += [
        "",
        "---",
        "",
        "## Module Win/Loss Rates",
        "",
        "| Module | Logged Wins | Logged Losses | Logged Win% | True Wins | True Losses | True Win% | Logged P&L | True P&L |",
        "|--------|-------------|---------------|-------------|-----------|-------------|-----------|------------|----------|",
    ]
    
    for mod in sorted(module_stats.keys()):
        s = module_stats[mod]
        total_l = s['wins_logged'] + s['losses_logged']
        total_t = s['wins_true'] + s['losses_true']
        winpct_l = (s['wins_logged'] / total_l * 100) if total_l > 0 else 0
        winpct_t = (s['wins_true'] / total_t * 100) if total_t > 0 else 0
        report_lines.append(
            f"| {mod} | {s['wins_logged']} | {s['losses_logged']} | {winpct_l:.1f}% | "
            f"{s['wins_true']} | {s['losses_true']} | {winpct_t:.1f}% | "
            f"${s['pnl_logged']:,.2f} | ${s['pnl_true']:,.2f} |"
        )
    
    report_lines += [
        "",
        "---",
        "",
        "## All Correction Records Written",
        "",
        f"Total corrections appended: **{len(correction_records)}**",
        "",
        "| # | Ticker | Date | Module | Logged P&L | True P&L | Delta | File |",
        "|---|--------|------|--------|-----------|---------|-------|------|",
    ]
    
    for i, rec in enumerate(correction_records, 1):
        orig_id = rec['original_trade_id']
        orig_trade = next((t for t in suspects if t.get('trade_id') == orig_id), None)
        src_file = orig_trade.get('_source_file', '?') if orig_trade else '?'
        report_lines.append(
            f"| {i} | {rec['ticker']} | {rec['date']} | {rec['module']} | "
            f"${rec['logged_pnl']:,.2f} | ${rec['true_pnl']:,.2f} | ${rec['pnl_correction']:,.2f} | {src_file} |"
        )
    
    report_lines += [
        "",
        "---",
        "",
        "## Suspect Exits Detail (All)",
        "",
        "| Ticker | Timestamp | Module | Side | Qty | Entry | Logged P&L | Kalshi Result | True P&L |",
        "|--------|-----------|--------|------|-----|-------|-----------|---------------|---------|",
    ]
    
    for ce in corrected_exits:
        t = ce['trade']
        result_str = ce['result']
        result_display = f"**{result_str}**" if result_str == 'yes' else result_str
        report_lines.append(
            f"| {t['ticker']} | {t['timestamp']} | {t.get('module','')} | {t.get('side','')} | "
            f"{t.get('contracts','')} | {t.get('entry_price','')}c | ${ce['logged_pnl']:.2f} | "
            f"{result_display} | ${ce['true_pnl']:.2f} |"
        )
    
    report_lines += [
        "",
        "---",
        "",
        "## Methodology",
        "",
        "1. Scanned all `.jsonl` trade logs for records where `action='exit'` and `action_detail` contains `@ 0-9c`",
        "2. Filtered to exits within ±30 seconds of settlement time (XX:00, XX:15, XX:30, XX:45)",
        "3. Called `KalshiClient.get_market(ticker)` for each unique ticker to get `result` field",
        "4. For `result='yes'`: true P&L = -(logged P&L), pnl_delta = -2 * logged_pnl",
        "5. For `result='no'`: P&L is correct, no correction needed",
        "6. Appended correction records (action='exit_correction') to original trade log files",
        "7. P&L recomputed live from logs (no pnl_cache.json)",
    ]
    
    report_content = '\n'.join(report_lines)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"\nReport saved to: {REPORT_PATH}")
    
    # Print summary
    print("\n" + "="*60)
    print("CORRECTION SUMMARY")
    print("="*60)
    print(f"Suspects analyzed:  {len(suspects)}")
    print(f"Confirmed losses:   {len([c for c in corrected_exits if c['result'] == 'yes'])}")
    print(f"Confirmed wins:     {len([c for c in corrected_exits if c['result'] == 'no'])}")
    print(f"Logged P&L:         ${total_logged_pnl:,.2f}")
    print(f"True P&L:           ${total_true_pnl:,.2f}")
    print(f"Total correction:   ${total_correction:,.2f}")
    print(f"Corrections written: {len(correction_records)}")
    
    return {
        'suspects': len(suspects),
        'confirmed_losses': len([c for c in corrected_exits if c['result'] == 'yes']),
        'total_logged_pnl': total_logged_pnl,
        'total_true_pnl': total_true_pnl,
        'total_correction': total_correction,
        'corrections_written': len(correction_records)
    }

if __name__ == '__main__':
    main()
