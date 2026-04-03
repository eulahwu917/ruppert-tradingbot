"""
Full trade audit script - checks all crypto exit/settle records from last 24h
against Kalshi API actual results.
"""

import json
import sys
import time
from datetime import datetime

sys.path.insert(0, r'C:\Users\David Wu\.openclaw\workspace\environments\demo')
sys.path.insert(0, r'C:\Users\David Wu\.openclaw\workspace')
from agents.ruppert.data_analyst.kalshi_client import KalshiClient

FILES = [
    r'C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\trades\trades_2026-03-30.jsonl',
    r'C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\trades\trades_2026-03-31.jsonl',
]

OUTPUT_FILE = r'C:\Users\David Wu\.openclaw\workspace\memory\agents\ds-full-audit-all-trades-2026-03-31.md'

def load_records():
    """Load all crypto exit/settle records from trade files."""
    records = []
    for f in FILES:
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get('action') in ('exit', 'settle') and 'crypto' in (rec.get('module') or '').lower():
                    records.append(rec)
    return records

def get_logged_outcome(rec):
    """
    Determine what the logged outcome was for a record.
    Returns: 'win', 'loss', or None
    """
    pnl = rec.get('pnl')
    if pnl is None:
        return None
    if pnl > 0:
        return 'win'
    elif pnl < 0:
        return 'loss'
    else:
        return 'breakeven'

def get_expected_outcome(side, result):
    """
    Given our side and the market result, what should the outcome be?
    - YES side + result='yes' -> win
    - YES side + result='no' -> loss
    - NO side + result='no' -> win
    - NO side + result='yes' -> loss
    """
    if result is None:
        return None
    side = (side or '').lower()
    if side == 'yes':
        return 'win' if result == 'yes' else 'loss'
    elif side == 'no':
        return 'win' if result == 'no' else 'loss'
    return None

def main():
    client = KalshiClient()
    records = load_records()
    
    print(f"Loaded {len(records)} crypto exit/settle records")
    
    # Deduplicate by ticker, but keep ALL records for reporting
    # We check each unique ticker once against the API
    
    # First pass: collect unique tickers
    unique_tickers = []
    seen = set()
    for rec in records:
        t = rec.get('ticker')
        if t and t not in seen:
            seen.add(t)
            unique_tickers.append(t)
    
    print(f"Unique tickers to check: {len(unique_tickers)}")
    
    # Fetch market data for all unique tickers
    market_cache = {}
    for i, ticker in enumerate(unique_tickers):
        try:
            m = client.get_market(ticker)
            raw_result = m.get('result')
            # Kalshi returns '' for active/not-yet-settled markets; normalize to None
            normalized_result = raw_result if raw_result else None
            market_cache[ticker] = {
                'result': normalized_result,
                'status': m.get('status'),
                'ticker': ticker
            }
            if (i + 1) % 20 == 0:
                print(f"  Fetched {i+1}/{len(unique_tickers)} markets...")
            time.sleep(0.1)  # small delay to be nice to the API
        except Exception as e:
            print(f"  ERROR fetching {ticker}: {e}")
            market_cache[ticker] = {'result': 'ERROR', 'status': 'ERROR', 'ticker': ticker}
    
    print(f"Market data fetched. Building audit results...")
    
    # Audit each record
    results = []
    
    for rec in records:
        ticker = rec.get('ticker')
        side = (rec.get('side') or '').lower()
        action = rec.get('action')
        pnl = rec.get('pnl', 0)
        logged_settlement = rec.get('settlement_result')  # only on settle records
        
        market = market_cache.get(ticker, {})
        kalshi_result = market.get('result')
        kalshi_status = market.get('status')
        
        logged_outcome = get_logged_outcome(rec)
        expected_outcome = get_expected_outcome(side, kalshi_result)
        
        # Determine audit status
        if kalshi_result == 'ERROR':
            audit_status = 'ERROR'
            note = 'Failed to fetch market data'
        elif kalshi_result is None:
            audit_status = 'OPEN'
            note = f'Market not yet settled (status={kalshi_status})'
        elif action == 'settle':
            # For settle records: compare logged settlement_result to Kalshi result
            if logged_settlement and logged_settlement != kalshi_result:
                audit_status = 'WRONG'
                note = f'Logged settlement_result={logged_settlement} but Kalshi says result={kalshi_result}'
            elif logged_outcome != expected_outcome and logged_outcome is not None:
                audit_status = 'WRONG'
                note = f'P&L sign mismatch: logged={logged_outcome} (pnl={pnl}), expected={expected_outcome} (side={side}, result={kalshi_result})'
            else:
                audit_status = 'CORRECT'
                note = f'Settlement matches: side={side}, result={kalshi_result}, pnl={pnl}'
        elif action == 'exit':
            # For exit records: P&L was locked at exit price (may differ from settlement)
            # Check if P&L sign is consistent with the market direction at time of exit
            # For early profitable exits, market may have resolved against us — this is fine
            # Flag true mismatches: if pnl > 0 but the settlement went against us (or vice versa)
            if logged_outcome == expected_outcome:
                audit_status = 'CORRECT'
                note = f'Early exit matches settlement direction: side={side}, result={kalshi_result}, pnl={pnl}'
            else:
                # Early exit went against settlement - could be valid (exited before resolution)
                exit_price = rec.get('exit_price', 0)
                entry_price = rec.get('entry_price', 0)
                
                # Check if exit was at a "winning" price level (close to 100 for YES wins)
                if side == 'yes' and kalshi_result == 'yes' and pnl < 0:
                    # Resolved YES but we logged a loss?
                    audit_status = 'WRONG'
                    note = f'Resolved YES (we win on YES side) but logged loss pnl={pnl}. exit_price={exit_price}, entry_price={entry_price}'
                elif side == 'yes' and kalshi_result == 'no' and pnl > 0:
                    # Resolved NO (against YES side) but we logged a profit
                    # This CAN be valid if we exited profitably before resolution
                    audit_status = 'CORRECT'
                    note = f'Early profitable exit (exit_price={exit_price} > entry_price={entry_price}) before market resolved NO. OK.'
                elif side == 'no' and kalshi_result == 'no' and pnl < 0:
                    # Resolved NO (we win on NO side) but logged a loss?
                    audit_status = 'WRONG'
                    note = f'Resolved NO (we win on NO side) but logged loss pnl={pnl}. exit_price={exit_price}, entry_price={entry_price}'
                elif side == 'no' and kalshi_result == 'yes' and pnl > 0:
                    # Resolved YES (against NO side) but we logged a profit
                    # This CAN be valid if we exited profitably before resolution
                    audit_status = 'CORRECT'
                    note = f'Early profitable exit before market resolved YES (against NO side). OK.'
                else:
                    audit_status = 'MISMATCH'
                    note = f'Direction mismatch: side={side}, result={kalshi_result}, pnl={pnl}, exit_price={exit_price}'
        else:
            audit_status = 'UNKNOWN'
            note = f'Unknown action: {action}'
        
        results.append({
            'ticker': ticker,
            'action': action,
            'side': side,
            'pnl': pnl,
            'entry_price': rec.get('entry_price'),
            'exit_price': rec.get('exit_price'),
            'contracts': rec.get('contracts'),
            'module': rec.get('module'),
            'timestamp': rec.get('timestamp'),
            'logged_settlement': logged_settlement,
            'kalshi_result': kalshi_result,
            'kalshi_status': kalshi_status,
            'logged_outcome': logged_outcome,
            'expected_outcome': expected_outcome,
            'audit_status': audit_status,
            'note': note,
            'action_detail': rec.get('action_detail', ''),
        })
    
    # Summary stats
    total = len(results)
    correct = sum(1 for r in results if r['audit_status'] == 'CORRECT')
    wrong = [r for r in results if r['audit_status'] == 'WRONG']
    open_markets = [r for r in results if r['audit_status'] == 'OPEN']
    mismatch = [r for r in results if r['audit_status'] == 'MISMATCH']
    errors = [r for r in results if r['audit_status'] == 'ERROR']
    
    # Market-level stats (by unique ticker)
    ticker_results = {}
    for r in results:
        t = r['ticker']
        if t not in ticker_results:
            ticker_results[t] = r
    
    open_unique = len([v for v in ticker_results.values() if v['kalshi_result'] is None])
    resolved_yes_unique = len([v for v in ticker_results.values() if v['kalshi_result'] == 'yes'])
    resolved_no_unique = len([v for v in ticker_results.values() if v['kalshi_result'] == 'no'])
    
    # Generate markdown report
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S PDT')
    
    lines = []
    lines.append(f"# Full Trade Audit — Crypto Exits/Settlements")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Scope:** trades_2026-03-30.jsonl + trades_2026-03-31.jsonl")
    lines.append(f"**Action filter:** exit, settle | **Module filter:** crypto")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total records checked | {total} |")
    lines.append(f"| Unique tickers | {len(unique_tickers)} |")
    lines.append(f"| ✅ CORRECT | {correct} |")
    lines.append(f"| ❌ WRONG (real errors) | {len(wrong)} |")
    lines.append(f"| ⚠️ MISMATCH (early exit vs settlement) | {len(mismatch)} |")
    lines.append(f"| 🔄 OPEN (not yet settled) | {len(open_markets)} |")
    lines.append(f"| 🔴 API ERROR | {len(errors)} |")
    lines.append("")
    lines.append(f"### Unique Ticker Resolution Status")
    lines.append(f"| Status | Unique Tickers |")
    lines.append(f"|--------|----------------|")
    lines.append(f"| Resolved YES | {resolved_yes_unique} |")
    lines.append(f"| Resolved NO | {resolved_no_unique} |")
    lines.append(f"| Still Open | {open_unique} |")
    lines.append("")
    
    if wrong:
        lines.append("---")
        lines.append("")
        lines.append("## ❌ WRONG Records (Real Errors)")
        lines.append("")
        for r in wrong:
            lines.append(f"### {r['ticker']}")
            lines.append(f"- **Action:** {r['action']} | **Side:** {r['side']} | **Module:** {r['module']}")
            lines.append(f"- **Timestamp:** {r['timestamp']}")
            lines.append(f"- **Logged P&L:** {r['pnl']}")
            lines.append(f"- **Kalshi Result:** {r['kalshi_result']} | **Status:** {r['kalshi_status']}")
            lines.append(f"- **Logged Settlement:** {r['logged_settlement']}")
            lines.append(f"- **Issue:** {r['note']}")
            lines.append("")
    else:
        lines.append("## ❌ WRONG Records")
        lines.append("")
        lines.append("**None found. All settled trades match Kalshi results.**")
        lines.append("")
    
    if mismatch:
        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ MISMATCH Records (Early Exit vs Settlement Direction)")
        lines.append("")
        lines.append("*These are not accounting errors — they represent trades where we exited early in a direction opposite to the final settlement. Investigate if patterns suggest systematic mispricing.*")
        lines.append("")
        for r in mismatch:
            lines.append(f"- **{r['ticker']}** | side={r['side']}, pnl={r['pnl']}, result={r['kalshi_result']} | {r['note']}")
        lines.append("")
    
    if open_markets:
        lines.append("---")
        lines.append("")
        lines.append("## 🔄 OPEN / Pending Settlement")
        lines.append("")
        lines.append(f"*{len(open_markets)} records across markets not yet settled.*")
        lines.append("")
        # Group by unique ticker
        open_tickers_seen = set()
        for r in open_markets:
            if r['ticker'] not in open_tickers_seen:
                open_tickers_seen.add(r['ticker'])
                lines.append(f"- **{r['ticker']}** | status={r['kalshi_status']} | side={r['side']}, pnl={r['pnl']}")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("## Full Record-by-Record Results")
    lines.append("")
    lines.append("| Timestamp | Ticker | Action | Side | Entry | Exit | Contracts | P&L | Kalshi Result | Audit |")
    lines.append("|-----------|--------|--------|------|-------|------|-----------|-----|---------------|-------|")
    
    for r in results:
        ts_short = (r['timestamp'] or '')[:16]
        lines.append(
            f"| {ts_short} | {r['ticker']} | {r['action']} | {r['side']} | "
            f"{r['entry_price']}c | {r['exit_price']}c | {r['contracts']} | "
            f"${r['pnl']:.2f} | {r['kalshi_result']} | {r['audit_status']} |"
        )
    
    lines.append("")
    lines.append("---")
    lines.append("*Audit complete. Data sourced from Kalshi API.*")
    
    report = '\n'.join(lines)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE")
    print(f"{'='*60}")
    print(f"Total records: {total}")
    print(f"Unique tickers: {len(unique_tickers)}")
    print(f"CORRECT: {correct}")
    print(f"WRONG: {len(wrong)}")
    print(f"MISMATCH (early exit): {len(mismatch)}")
    print(f"OPEN: {len(open_markets)}")
    print(f"ERRORS: {len(errors)}")
    print(f"\nReport saved to: {OUTPUT_FILE}")
    
    if wrong:
        print(f"\n❌ WRONG RECORDS:")
        for r in wrong:
            print(f"  {r['ticker']}: {r['note']}")
    
    if mismatch:
        print(f"\n⚠️ MISMATCH RECORDS (early exits going against settlement):")
        for r in mismatch:
            print(f"  {r['ticker']}: side={r['side']}, pnl={r['pnl']}, result={r['kalshi_result']}")

if __name__ == '__main__':
    main()
