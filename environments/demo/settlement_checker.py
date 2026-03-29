"""
Settlement Checker — resolves all unsettled positions against Kalshi API.

For every open buy trade in the trade logs, checks if the market has settled
on Kalshi. If yes, records a settle event to the original trade date's log.

Idempotent: safe to run multiple times — skips tickers that already have
a settle or exit record.

Usage:
    python -m environments.demo.settlement_checker
    python environments/demo/settlement_checker.py

Scheduled via Task Scheduler as Ruppert-SettlementChecker:
    - 11:00 PM PDT (after all markets close)
    - 8:00 AM PDT  (catch overnight settlements)
"""
import sys
import json
import uuid
import time
from pathlib import Path
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# Ensure workspace root is on sys.path
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from agents.ruppert.env_config import get_paths as _get_paths
from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from scripts.event_logger import log_event

_PDT = ZoneInfo('America/Los_Angeles')
_paths = _get_paths()
TRADES_DIR = _paths['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)


def load_all_unsettled():
    """Read all trade logs and return unsettled buy positions.

    Returns:
        dict: {(ticker, side): record} for buys without a matching settle/exit
    """
    entries_by_key = {}
    closed_keys = set()

    for trade_log in sorted(TRADES_DIR.glob('trades_*.jsonl')):
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
                closed_keys.add(key)
            elif action in ('buy', 'open'):
                entries_by_key[key] = rec

    return {k: v for k, v in entries_by_key.items() if k not in closed_keys}


def compute_pnl(pos, result, side):
    """Compute settlement P&L using size_dollars as cost basis.

    For dry_run simulated trades at 1c, the contracts field is inflated
    (e.g. 10000 contracts at 1c = $100 cost). Use size_dollars as the
    authoritative cost basis and entry_price / exit_price for P&L calc.

    Returns:
        (pnl, exit_price, entry_price) where prices are in cents
    """
    # Determine entry price in cents
    entry_price = None
    for field in ('fill_price', 'scan_price'):
        val = pos.get(field)
        if val is not None:
            try:
                entry_price = float(val)
                break
            except (TypeError, ValueError):
                pass
    if entry_price is None:
        mp = pos.get('market_prob')
        if mp is not None:
            try:
                entry_price = float(mp) * 100
            except (TypeError, ValueError):
                pass
    if entry_price is None:
        entry_price = 50.0

    size_dollars = float(pos.get('size_dollars', 0) or 0)
    contracts = int(pos.get('contracts', 1) or 1)

    # Determine if our side won
    side_won = (side == 'yes' and result == 'yes') or (side == 'no' and result == 'no')

    if side_won:
        exit_price = 99
        # P&L = (exit - entry) per contract, in dollars
        pnl = (99 - entry_price) * contracts / 100
    else:
        exit_price = 1
        # Loss = cost basis
        pnl = -size_dollars

    return round(pnl, 2), exit_price, entry_price


def check_settlements():
    """Main settlement checker logic."""
    print(f"\n{'='*60}")
    print(f"  SETTLEMENT CHECKER  {datetime.now(_PDT).strftime('%Y-%m-%d %H:%M:%S PDT')}")
    print(f"{'='*60}")

    unsettled = load_all_unsettled()
    if not unsettled:
        print("  No unsettled positions found.")
        return

    print(f"  {len(unsettled)} unsettled position(s) to check\n")

    client = KalshiClient()
    settled_count = 0
    skipped_count = 0
    error_count = 0

    for (ticker, side), pos in unsettled.items():
        if not ticker or not side:
            skipped_count += 1
            continue

        # Fetch market from Kalshi
        try:
            market = client.get_market(ticker)
        except Exception as e:
            print(f"  [ERROR] API error for {ticker}: {e}")
            error_count += 1
            continue

        if not market:
            print(f"  [SKIP] {ticker}: not found on Kalshi")
            skipped_count += 1
            continue

        # Determine if market is resolved
        result = market.get('result', '')
        status = market.get('status', '')
        yes_bid = market.get('yes_bid', 50)

        if result in ('yes', 'no'):
            pass  # resolved via result field
        elif status in ('settled', 'finalized'):
            # Infer result from yes_bid
            result = 'yes' if (yes_bid or 0) >= 99 else 'no'
        elif (yes_bid or 0) >= 99:
            result = 'yes'
        elif (yes_bid or 0) <= 1:
            result = 'no'
        else:
            # Check if market is active but close_time has passed (expiring today)
            close_time = market.get('close_time', '')
            if close_time and status == 'active':
                try:
                    ct = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    if ct < datetime.now(timezone.utc):
                        # Market expired but not yet settled — will settle overnight
                        print(f"  [PENDING] {ticker}: expired but not yet settled")
                except Exception:
                    pass
            # Not yet resolved
            continue

        # Compute P&L
        pnl, exit_price, entry_price = compute_pnl(pos, result, side)

        # Determine hold duration
        hold_hours = None
        try:
            entry_dt = datetime.fromisoformat(
                pos.get('timestamp', '').replace('Z', '+00:00').split('+')[0]
            )
            hold_hours = round((datetime.now() - entry_dt).total_seconds() / 3600, 2)
        except Exception:
            pass

        # Build settle record matching spec schema
        original_date = pos.get('date', date.today().isoformat())
        settle_record = {
            "trade_id": str(uuid.uuid4()),
            "timestamp": datetime.now(_PDT).isoformat(),
            "date": original_date,
            "ticker": ticker,
            "title": pos.get("title", ""),
            "side": side,
            "action": "settle",
            "action_detail": f"SETTLE {'WIN' if pnl > 0 else 'LOSS'} @ {exit_price}c",
            "source": "settlement_checker",
            "module": pos.get("module", ""),
            "settlement_result": result,
            "pnl": pnl,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "contracts": int(pos.get("contracts", 0) or 0),
            "size_dollars": float(pos.get("size_dollars", 0) or 0),
            "fill_price": exit_price,
            "entry_edge": pos.get("edge"),
            "confidence": pos.get("confidence"),
            "hold_duration_hours": hold_hours,
            "order_result": {"dry_run": True, "status": "settled"},
        }

        # Write to original trade date's log file
        log_path = TRADES_DIR / f'trades_{original_date}.jsonl'
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(settle_record) + '\n')
        except Exception as e:
            print(f"  [ERROR] Write failed for {ticker}: {e}")
            error_count += 1
            continue

        # Log event for Data Scientist synthesis
        log_event('SETTLEMENT', {
            'ticker': ticker,
            'side': side,
            'result': result,
            'pnl': pnl,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'contracts': settle_record['contracts'],
            'module': settle_record['module'],
        })

        win_loss = 'WIN' if pnl > 0 else 'LOSS'
        print(f"  [SETTLE] {ticker} {side.upper()} → {result.upper()} {win_loss} | P&L=${pnl:+.2f}")
        settled_count += 1

        # Rate limit: be kind to Kalshi API
        time.sleep(0.1)

    # Score new settlements for calibration analysis
    try:
        from environments.demo.prediction_scorer import score_new_settlements
        score_new_settlements()
    except Exception as e:
        print(f"  [WARN] prediction_scorer failed: {e}")

    # Summary
    print(f"\n{'─'*60}")
    print(f"  Settlement Checker: {settled_count} settled, {skipped_count} skipped, {error_count} errors")
    print(f"  Done. {datetime.now(_PDT).strftime('%Y-%m-%d %H:%M:%S PDT')}")


if __name__ == '__main__':
    check_settlements()
