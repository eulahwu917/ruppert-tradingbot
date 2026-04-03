"""
ISSUE-042 Part B: Insert exit_correction records for NO-side entry price flip bug.
Finds all 115 affected trades from trade logs and inserts correction records.
"""
import sys
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '.')
sys.path.insert(0, 'environments/demo')

WORKSPACE = Path('.')
TRADES_DIR = WORKSPACE / 'environments/demo/logs/trades'

def find_affected_trades():
    """Find all NO-side trades where entry_price < 50 (affected by flip bug)."""
    # Collect buys (actual entry prices)
    buys = {}  # ticker -> {date, actual_ep, contracts, module}
    exits = {}  # ticker -> {date, exit_price, stored_ep, logged_pnl}

    for date_str in ['2026-04-02', '2026-04-03']:
        fname = TRADES_DIR / f'trades_{date_str}.jsonl'
        if not fname.exists():
            print(f'WARNING: {fname} not found')
            continue
        with open(fname, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('side') != 'no':
                    continue
                ticker = rec.get('ticker')
                action = rec.get('action', '')
                if action == 'buy':
                    ep = rec.get('entry_price', 0)
                    if ep < 50 and ticker not in buys:
                        buys[ticker] = {
                            'date': date_str,
                            'actual_ep': ep,
                            'contracts': rec.get('contracts', 0),
                            'module': rec.get('module', '')
                        }
                elif action in ('exit', 'settle'):
                    exits[ticker] = {
                        'date': date_str,
                        'exit_price': rec.get('exit_price', 0),
                        'stored_ep': rec.get('entry_price', 0),
                        'logged_pnl': rec.get('pnl', 0)
                    }

    # Verify and compute deltas
    corrections = []
    skipped = []
    for ticker, buy in buys.items():
        if ticker not in exits:
            skipped.append(ticker)
            continue
        ex = exits[ticker]
        actual_ep = buy['actual_ep']
        stored_ep = ex['stored_ep']
        expected_stored = 100 - actual_ep

        # Confirm flip was applied
        if stored_ep != expected_stored:
            print(f'ANOMALY: {ticker} - actual_ep={actual_ep}, expected_stored={expected_stored}, actual_stored={stored_ep}')
            # Still proceed with correction using the actual stored value
        
        exit_price = ex['exit_price']
        contracts = buy['contracts']
        logged_pnl = ex['logged_pnl']
        correct_pnl = (exit_price - actual_ep) * contracts / 100
        delta = round(correct_pnl - logged_pnl, 2)

        corrections.append({
            'date': buy['date'],
            'ticker': ticker,
            'module': buy['module'],
            'actual_ep': actual_ep,
            'stored_ep': stored_ep,
            'contracts': contracts,
            'exit_price': exit_price,
            'logged_pnl': round(logged_pnl, 2),
            'correct_pnl': round(correct_pnl, 2),
            'delta': delta
        })

    if skipped:
        print(f'WARNING: {len(skipped)} trades had no matching exit: {skipped}')

    return corrections


def insert_corrections(corrections):
    """Insert exit_correction records into the trade log files."""
    now_iso = datetime.now(timezone.utc).isoformat()
    by_date = {'2026-04-02': [], '2026-04-03': []}

    for c in corrections:
        rec = {
            'trade_id': str(uuid.uuid4()),
            'timestamp': now_iso,
            'date': c['date'],
            'ticker': c['ticker'],
            'side': 'no',
            'action': 'exit_correction',
            'source': 'ds_no_side_audit_2026-04-03',
            'module': c['module'],
            'pnl': c['delta'],
            'pnl_correction': c['delta'],
            'note': f"ISSUE-042 NO-side flip correction: actual_ep={int(c['actual_ep'])}c, stored_ep={int(c['stored_ep'])}c"
        }
        by_date[c['date']].append(rec)

    inserted = 0
    for date_str, records in by_date.items():
        if not records:
            continue
        fname = TRADES_DIR / f'trades_{date_str}.jsonl'
        with open(fname, 'a', encoding='utf-8') as f:
            for rec in records:
                f.write(json.dumps(rec) + '\n')
                inserted += 1
        print(f'  Inserted {len(records)} records into trades_{date_str}.jsonl')

    return inserted


def main():
    print('=== ISSUE-042 Part B: NO-Side P&L Correction ===\n')

    # Get pre-correction capital
    from agents.ruppert.data_scientist.capital import get_capital
    pre_cap = get_capital()
    print(f'Pre-correction capital: ${pre_cap:.2f}')

    # Check for existing corrections
    existing = 0
    for date_str in ['2026-04-02', '2026-04-03']:
        fname = TRADES_DIR / f'trades_{date_str}.jsonl'
        if fname.exists():
            with open(fname, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            if rec.get('action') == 'exit_correction' and rec.get('source') == 'ds_no_side_audit_2026-04-03':
                                existing += 1
                        except Exception:
                            pass
    if existing > 0:
        print(f'WARNING: {existing} correction records from this audit already exist! Aborting to prevent duplicates.')
        sys.exit(1)

    # Find affected trades
    print('\nFinding affected trades...')
    corrections = find_affected_trades()
    print(f'Found {len(corrections)} affected trades to correct')

    total_delta = sum(c['delta'] for c in corrections)
    print(f'Total P&L correction: +${total_delta:.2f}')

    by_date_count = {}
    for c in corrections:
        by_date_count[c['date']] = by_date_count.get(c['date'], 0) + 1
    for d, cnt in sorted(by_date_count.items()):
        print(f'  {d}: {cnt} records')

    # Insert corrections
    print('\nInserting correction records...')
    inserted = insert_corrections(corrections)
    print(f'Total inserted: {inserted}')

    # Refresh CB global state
    print('\nRefreshing circuit breaker global state...')
    from agents.ruppert.trader import circuit_breaker
    post_cap = get_capital()
    circuit_breaker.update_global_state(post_cap)
    print(f'CB global state updated. Post-correction capital: ${post_cap:.2f}')

    print(f'\nSummary:')
    print(f'  Pre-correction capital:  ${pre_cap:.2f}')
    print(f'  Post-correction capital: ${post_cap:.2f}')
    print(f'  Difference:              +${post_cap - pre_cap:.2f}')
    print(f'  Expected target:         ~$21,009.61')
    diff_from_target = abs(post_cap - 21009.61)
    print(f'  Diff from target:        ${diff_from_target:.2f}')

    return pre_cap, post_cap, inserted, by_date_count


if __name__ == '__main__':
    main()
