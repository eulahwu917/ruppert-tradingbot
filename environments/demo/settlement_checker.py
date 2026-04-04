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

from agents.ruppert.env_config import get_paths as _get_paths, is_live_enabled as _is_live_enabled
from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import _append_jsonl, _pdt_today
from scripts.event_logger import log_event
from terminal_signal_logger import backfill_outcome

_PDT = ZoneInfo('America/Los_Angeles')
_paths = _get_paths()
TRADES_DIR = _paths['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)


def load_all_unsettled():
    """Read all trade logs and return unsettled buy positions.

    Returns:
        dict: {(ticker, side, idx): record} for buy legs without a matching settle/exit.
              Multiple buy legs for the same (ticker, side) are each included with a
              unique index suffix so they don't collide. The consumer in
              check_settlements() extracts ticker/side from the record directly.

    Exit/settle counting (FIFO):
        Instead of a binary "any exit = skip all legs" approach, counts the number
        of exit/settle records per (ticker, side). The first N buy legs (where N =
        exit count) are skipped (FIFO order). Remaining legs are returned as unsettled.
        This ensures multi-buy positions where only some legs have been WS-exited
        still receive settle records for their remaining legs.
    """
    entries_by_key = {}     # (ticker, side) → list of buy records (chronological)
    exit_count_by_key = {}  # (ticker, side) → count of exit/settle records

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
                exit_count_by_key[key] = exit_count_by_key.get(key, 0) + 1
            elif action in ('buy', 'open'):
                if key not in entries_by_key:
                    entries_by_key[key] = []
                entries_by_key[key].append(rec)

    # Flatten: skip first N buy legs equal to the exit count (FIFO matching).
    # Remaining legs are unsettled and each becomes its own result entry.
    # check_settlements() reads ticker/side from the record, not the key.
    result = {}
    for key, recs in entries_by_key.items():
        exits = exit_count_by_key.get(key, 0)
        # Skip legs that already have a matching exit record (FIFO: oldest legs first)
        unsettled_recs = recs[exits:]
        for idx, rec in enumerate(unsettled_recs):
            result[(key[0], key[1], exits + idx)] = rec
    return result


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
        exit_price = 100
        # P&L = (exit - entry) per contract, in dollars
        pnl = (100 - entry_price) * contracts / 100
    else:
        exit_price = 1
        # Loss = entry cost basis (contract-based math, consistent with win formula)
        pnl = -(entry_price * contracts / 100)

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

    for _key, pos in unsettled.items():
        # Keys are (ticker, side, idx) — read ticker/side from the record itself
        ticker = pos.get('ticker', '')
        side = pos.get('side', '')
        if not ticker or not side:
            skipped_count += 1
            continue

        # Fetch market from Kalshi (with retry on transient errors)
        MAX_RETRIES = 3
        market = None
        for attempt in range(MAX_RETRIES):
            try:
                market = client.get_market(ticker)
                break
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt  # attempt=0 → 1s, attempt=1 → 2s
                    print(f"  [WARN] API error for {ticker} (attempt {attempt+1}/{MAX_RETRIES}): {e} — retrying in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"  [ERROR] API error for {ticker} after {MAX_RETRIES} attempts: {e} — skipping")
                    error_count += 1
        if market is None:
            continue

        if not market:
            print(f"  [SKIP] {ticker}: not found on Kalshi")
            skipped_count += 1
            continue

        # Determine if market is resolved
        result = market.get('result', '')
        status = market.get('status', '')
        yes_bid = market.get('yes_bid', 50)

        if result not in ('yes', 'no'):
            if status in ('settled', 'finalized'):
                # Status confirms settlement — infer from bid only when unambiguous
                if (yes_bid or 0) >= 99:
                    result = 'yes'
                elif (yes_bid or 0) <= 1:
                    result = 'no'
                else:
                    # Finalized but bid is ambiguous (e.g. 50c) — cannot safely infer
                    print(f"  [WARN] {ticker}: status={status} but yes_bid={yes_bid} is ambiguous — skipping")
                    continue
            else:
                # Check if market is active but close_time has passed (expiring today)
                close_time = market.get('close_time', '')
                if close_time and status == 'active':
                    try:
                        ct = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                        if ct < datetime.now(timezone.utc):
                            print(f"  [PENDING] {ticker}: expired but not yet settled")
                    except Exception:
                        pass
                continue  # Not resolved — skip

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
        original_date = pos.get('date', _pdt_today().isoformat())
        today_date = _pdt_today().isoformat()
        settle_record = {
            "trade_id": str(uuid.uuid4()),
            "timestamp": datetime.now(_PDT).isoformat(),
            "date": today_date,
            "entry_date": original_date,
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
            "order_result": {"dry_run": not _is_live_enabled(), "status": "settled"},
        }

        # Write to today's log file (not entry date's) so get_daily_exposure() can find it
        log_path = TRADES_DIR / f'trades_{today_date}.jsonl'
        try:
            _append_jsonl(log_path, settle_record)
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

        # Backfill terminal signal logger with outcome
        try:
            backfill_outcome(ticker, side, win_loss)
        except Exception as _bf_err:
            print(f"  [WARN] terminal signal backfill failed for {ticker}: {_bf_err}")

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

    # pnl_cache.json removed — P&L computed live by compute_closed_pnl_from_logs()


if __name__ == '__main__':
    check_settlements()
