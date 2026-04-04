"""
Brier Score Tracker — per-domain prediction calibration logging.

Logs every trade prediction at entry time, then scores it when the contract resolves.
Brier score = (outcome - predicted_prob)^2, range 0-1, lower is better.

Files:
  logs/predictions.jsonl     — one entry per trade at entry time
  logs/scored_predictions.jsonl — one entry per resolved prediction
"""

import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_brier_paths():
    """
    Lazy path resolution — called at function scope, not import scope.
    Resolves env-config paths each time it's called so RUPPERT_ENV changes
    after import are respected (important for test isolation).
    Returns (logs_dir, pred_file, scored_file).
    """
    workspace_root = Path(__file__).resolve().parent.parent.parent
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))
    from agents.ruppert.env_config import get_paths
    paths = get_paths()
    logs_dir = paths['logs']
    return logs_dir, logs_dir / "predictions.jsonl", logs_dir / "scored_predictions.jsonl"


def log_prediction(domain: str, ticker: str, predicted_prob: float,
                   market_price: float, edge: float, side: str = "",
                   extra: dict = None):
    """
    Log a prediction at trade entry time.
    Call this immediately when a trade is placed.

    Args:
        domain:         'crypto' (or sub-domain like 'crypto_band_daily')
        ticker:         Kalshi market ticker
        predicted_prob: Model's estimated WIN probability (0-1)
        market_price:   Market price at time of entry (0-1)
        edge:           Predicted_prob - market_price
        side:           'yes' or 'no'
        extra:          Optional additional fields to log
    """
    try:
        _logs_dir, _pred_file, _scored_file = _get_brier_paths()
        _logs_dir.mkdir(exist_ok=True)
        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "domain":         domain,
            "ticker":         ticker,
            "predicted_prob": round(predicted_prob, 4),
            "market_price":   round(market_price, 4),
            "edge":           round(edge, 4),
            "side":           side,
            "outcome":        None,   # filled in on resolution
            "brier_score":    None,   # filled in on resolution
        }
        if extra:
            entry.update(extra)
        with open(_pred_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.debug(f"[Brier] Logged prediction: {ticker} domain={domain} prob={predicted_prob:.2%}")
    except Exception as e:
        logger.warning(f"[Brier] log_prediction failed for {ticker}: {e}")


def score_prediction(ticker: str, outcome: int):
    """
    Score a prediction when its contract resolves.
    Call this when Step 1 position check detects a resolution.

    Args:
        ticker:  Kalshi market ticker
        outcome: 1 if our side won (profitable), 0 if lost
    """
    try:
        _logs_dir, _pred_file, _scored_file = _get_brier_paths()
        # Find the matching prediction
        if not _pred_file.exists():
            return
        prediction = None
        lines = _pred_file.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("ticker") == ticker and entry.get("outcome") is None:
                    prediction = entry
                    break
            except Exception:
                continue

        if prediction is None:
            logger.debug(f"[Brier] No unscored prediction found for {ticker}")
            return

        # Dedup: skip if (ticker, date) already appears in scored file.
        # date is derived from the prediction's ts field (entry time), not score time.
        # Dedup keys on existence only — null-outcome records in scored file still block re-scoring.
        prediction_date = str(prediction.get("ts", ""))[:10]  # "YYYY-MM-DD" from ISO timestamp (entry date)
        if _scored_file.exists():
            for existing_line in _scored_file.read_text(encoding="utf-8").strip().splitlines():
                try:
                    existing_rec = json.loads(existing_line)
                    # ISSUE-101 fix: use prediction entry date (ts[:10]) on both sides.
                    # resolved_at is set at score-time and can differ from entry date for
                    # afternoon PDT positions that settle past midnight UTC.
                    existing_entry_date = str(existing_rec.get("ts", ""))[:10]
                    if (existing_rec.get("ticker") == ticker
                            and existing_entry_date == prediction_date):
                        logger.debug(
                            f"[Brier] Duplicate score suppressed for {ticker} "
                            f"on {prediction_date} -- already in scored file"
                        )
                        return
                except Exception:
                    continue

        predicted_prob = prediction.get("predicted_prob", 0.5)
        brier_score = round((outcome - predicted_prob) ** 2, 4)

        scored_entry = {
            **prediction,
            "outcome":       outcome,
            "brier_score":   brier_score,
            "resolved_at":   datetime.now(timezone.utc).isoformat(),
        }

        _logs_dir.mkdir(exist_ok=True)
        with open(_scored_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(scored_entry) + "\n")

        logger.info(
            f"[Brier] Scored: {ticker} domain={prediction.get('domain')} "
            f"prob={predicted_prob:.2%} outcome={outcome} brier={brier_score:.4f}"
        )
    except Exception as e:
        logger.warning(f"[Brier] score_prediction failed for {ticker}: {e}")


def get_domain_brier_summary() -> dict:
    """
    Compute per-domain Brier score summary from scored_predictions.jsonl.

    Returns:
        {
          'crypto':  {'count': 5,  'brier_mean': 0.22, 'threshold_pct': 17},
          ...
        }
        threshold_pct = percentage toward the 30-trade autoresearch threshold
    """
    THRESHOLD = 30
    summary = {}
    _logs_dir, _pred_file, _scored_file = _get_brier_paths()
    if not _scored_file.exists():
        return summary
    try:
        lines = _scored_file.read_text(encoding="utf-8").strip().splitlines()
        domain_data: dict = {}
        for line in lines:
            try:
                entry = json.loads(line)
                domain = entry.get("domain", "unknown")
                brier = entry.get("brier_score")
                if brier is None:
                    continue
                if domain not in domain_data:
                    domain_data[domain] = []
                domain_data[domain].append(brier)
            except Exception:
                continue

        for domain, scores in domain_data.items():
            count = len(scores)
            summary[domain] = {
                "count":          count,
                "brier_mean":     round(sum(scores) / count, 4) if count else None,
                "threshold_pct":  round(count / THRESHOLD * 100),
            }
    except Exception as e:
        logger.warning(f"[Brier] get_domain_brier_summary failed: {e}")
    return summary
