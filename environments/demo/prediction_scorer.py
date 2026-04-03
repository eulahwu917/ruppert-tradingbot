"""
Prediction Scorer -- extracts scored predictions from settlement records.

Reads settle/exit records from logs/trades/ and writes standardized
prediction accuracy records to logs/scored_predictions.jsonl.

Idempotent: tracks processed settlements to avoid duplicates.

Usage:
    python -m environments.demo.prediction_scorer           # Standalone
    from environments.demo.prediction_scorer import score_new_settlements  # Called by settlement_checker
"""
import sys
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Ensure workspace root is on sys.path
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from agents.ruppert.env_config import get_paths as _get_paths

_paths = _get_paths()
TRADES_DIR = _paths['trades']
LOGS_DIR = _paths['logs']
OUTPUT_FILE = LOGS_DIR / 'scored_predictions.jsonl'

# Ticker prefix -> city name mapping for weather module
TICKER_CITY_MAP = {
    "KXHIGHMIA":   "Miami",
    "KXHIGHLAX":   "Los Angeles",
    "KXHIGHLA":    "Los Angeles",
    "KXHIGHCHI":   "Chicago",
    "KXHIGHHOU":   "Houston",
    "KXHIGHPHX":   "Phoenix",
    "KXHIGHNY":    "New York",
    "KXHIGHTDC":   "Washington DC",
    "KXHIGHPHIL":  "Philadelphia",
    "KXHIGHDEN":   "Denver",
    "KXHIGHTMIN":  "Minneapolis",
    "KXHIGHTLV":   "Las Vegas",
    "KXHIGHTNOU":  "New Orleans",
    "KXHIGHTOKC":  "Oklahoma City",
    "KXHIGHTSEA":  "Seattle",
    "KXHIGHTSATX": "San Antonio",
    "KXHIGHTATL":  "Atlanta",
    "KXHIGHAUS":   "Austin",
    "KXHIGHSFO":   "San Francisco",
}


def _extract_city(ticker: str, title: str) -> str | None:
    """Extract city name from ticker prefix or title for weather module."""
    series = ticker.split('-')[0].upper() if ticker else ''
    for prefix, city in TICKER_CITY_MAP.items():
        if series.startswith(prefix):
            return city
    # Fallback: parse from title
    if title:
        title_lower = title.lower()
        for city in TICKER_CITY_MAP.values():
            if city.lower() in title_lower:
                return city
    return None


def _load_processed_keys() -> set:
    """Load set of (ticker, date) tuples already in scored_predictions.jsonl."""
    processed = set()
    if OUTPUT_FILE.exists():
        for line in OUTPUT_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                processed.add((rec.get('ticker', ''), rec.get('date', '')))
            except Exception:
                continue
    return processed


def _load_all_trades() -> list:
    """Load all trade records from all log files."""
    records = []
    for trade_log in sorted(TRADES_DIR.glob('trades_*.jsonl')):
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def score_new_settlements():
    """Main scoring function. Finds new settle/exit records and writes scored predictions."""
    processed = _load_processed_keys()
    all_trades = _load_all_trades()

    # Primary index: (ticker, date) — exact match for same-day trades
    buy_index: dict[tuple, dict] = {}
    # Fallback index: (ticker, side) — for multi-day positions where settle date != buy date.
    # Keyed on side to prevent returning the wrong buy record when a ticker is re-traded from
    # the opposite side on a different date. If (ticker, side) doesn't match, return None —
    # do NOT fall through to a stale or wrong-side buy record.
    buy_index_by_ticker_side: dict[tuple, dict] = {}
    for rec in all_trades:
        action = rec.get('action', '')
        if action in ('buy', 'open'):
            primary_key = (rec.get('ticker', ''), rec.get('date', ''))
            if primary_key not in buy_index:
                buy_index[primary_key] = rec
            ts_key = (rec.get('ticker', ''), rec.get('side', 'yes'))
            if ts_key not in buy_index_by_ticker_side:
                buy_index_by_ticker_side[ts_key] = rec

    # Find new settle/exit records
    new_scored = []
    for rec in all_trades:
        action = rec.get('action', '')
        if action not in ('settle', 'exit'):
            continue

        ticker = rec.get('ticker', '')
        trade_date = rec.get('date', '')
        key = (ticker, trade_date)

        if key in processed:
            continue

        # Look up original buy record — primary by (ticker, date), fallback by (ticker, side)
        settle_side = rec.get('side', 'yes')
        buy_rec = buy_index.get(key) or buy_index_by_ticker_side.get((ticker, settle_side))
        # If neither lookup succeeds, buy_rec is None.
        # Warn on fallback paths.
        if not buy_index.get(key):
            if buy_rec:
                logger.warning(
                    f"[Scorer] {ticker}: date mismatch -- using (ticker, side) fallback "
                    f"buy record (buy date={buy_rec.get('date', '?')}, settle date={trade_date})"
                )
            else:
                logger.warning(
                    f"[Scorer] {ticker}: no matching buy record found for "
                    f"(ticker={ticker}, side={settle_side}) -- predicted_prob will be null"
                )

        module = rec.get('module') or (buy_rec.get('module', '') if buy_rec else '')
        city = None
        if module == 'weather':
            city = _extract_city(ticker, rec.get('title') or (buy_rec.get('title', '') if buy_rec else ''))

        # Extract predicted probability: prefer noaa_prob from buy record, fall back to model_prob.
        # If buy_rec is None (no matching buy found), predicted_prob stays None — do NOT corrupt.
        predicted_prob = buy_rec.get('noaa_prob') if buy_rec else None
        if predicted_prob is None:
            predicted_prob = buy_rec.get('model_prob') if buy_rec else None
        if predicted_prob is None:
            predicted_prob = buy_rec.get('market_prob') if buy_rec else None

        # Derive outcome (int 0/1) from settlement_result
        _settlement_result = rec.get('settlement_result')
        if _settlement_result is not None:
            _sr_str = str(_settlement_result).strip().lower()
            if _sr_str in ('yes', '1', 'true'):
                _outcome = 1
            elif _sr_str in ('no', '0', 'false'):
                _outcome = 0
            else:
                _outcome = None
        else:
            _outcome = None

        # For NO-side trades: flip outcome and predicted_prob into the bettor's frame.
        # outcome=1 must mean "bettor won" regardless of side.
        # predicted_prob must represent the bettor's win probability for Brier to be meaningful.
        # NOTE: If predicted_prob is None, only _outcome is flipped. Brier stays None (correct).
        # NOTE: edge is NOT flipped — it is already signed from the bettor's perspective.
        side = rec.get('side') or (buy_rec.get('side', 'yes') if buy_rec else 'yes')
        if side == 'no' and _outcome is not None:
            _outcome = 1 - _outcome
            if predicted_prob is not None:
                predicted_prob = round(1.0 - float(predicted_prob), 4)

        # Compute Brier score
        _brier = None
        if _outcome is not None and predicted_prob is not None:
            _brier = round((_outcome - float(predicted_prob)) ** 2, 4)

        scored = {
            "domain":          module or None,
            "ticker":          ticker,
            "predicted_prob":  round(float(predicted_prob), 4) if predicted_prob is not None else None,
            "outcome":         _outcome,
            "brier_score":     _brier,
            "edge":            round(float(buy_rec.get('edge', 0)), 4) if buy_rec and buy_rec.get('edge') is not None else None,
            "confidence":      round(float(buy_rec.get('confidence', 0)), 4) if buy_rec and buy_rec.get('confidence') is not None else None,
            "date":            trade_date,
            "settlement_date": rec.get('date', trade_date),
            "pnl":             round(float(rec.get('pnl', 0)), 2) if rec.get('pnl') is not None else None,
        }
        new_scored.append(scored)
        processed.add(key)

    if not new_scored:
        print(f"  [Scorer] No new settlements to score.")
        return

    # Append to output file
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        for rec in new_scored:
            f.write(json.dumps(rec) + '\n')

    print(f"  [Scorer] Wrote {len(new_scored)} scored prediction(s) to {OUTPUT_FILE.name}")


if __name__ == '__main__':
    score_new_settlements()
