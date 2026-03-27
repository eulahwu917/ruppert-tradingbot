"""
Baseline Comparisons — track naive strategy performance for alpha validation.

Three baselines logged alongside every real trade decision:
  1. always_no_weather: always bet NO on weather, ignore model
  2. follow_cme_fed:    use CME probability directly, no Polymarket blend
  3. uniform_sizing:    flat $10 on every trade that passes edge gate

File: logs/baselines.jsonl
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
_BASELINES_FILE = Path(__file__).parent / "logs" / "baselines.jsonl"


def _log_baseline(baseline_type: str, ticker: str, domain: str,
                  baseline_action: str, baseline_price: float,
                  actual_action: str, actual_price: float,
                  outcome: int = None, extra: dict = None):
    """Internal: append one baseline entry."""
    try:
        _BASELINES_FILE.parent.mkdir(exist_ok=True)
        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "baseline_type":  baseline_type,
            "domain":         domain,
            "ticker":         ticker,
            "baseline_action": baseline_action,
            "baseline_price":  round(baseline_price, 4),
            "actual_action":   actual_action,
            "actual_price":    round(actual_price, 4),
            "outcome":         outcome,  # filled in on resolution
        }
        if extra:
            entry.update(extra)
        with open(_BASELINES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"[Baselines] log failed for {ticker}: {e}")


def log_always_no_weather(ticker: str, no_price: float,
                          actual_action: str, actual_price: float):
    """
    Log what the always-NO baseline would have done on a weather market.
    Call for every weather market that passes the edge gate (regardless of direction filter).
    """
    _log_baseline(
        baseline_type="always_no_weather",
        ticker=ticker, domain="weather",
        baseline_action="no", baseline_price=no_price,
        actual_action=actual_action, actual_price=actual_price,
    )


def log_follow_cme_fed(ticker: str, cme_prob: float, market_price: float,
                       actual_action: str, actual_price: float,
                       ensemble_prob: float = None):
    """
    Log what pure CME-follow strategy would have done on a Fed market.
    Call for every Fed scan that has CME data available.
    """
    cme_edge = cme_prob - market_price
    baseline_action = "yes" if cme_edge > 0 else "no"
    _log_baseline(
        baseline_type="follow_cme_fed",
        ticker=ticker, domain="fed",
        baseline_action=baseline_action, baseline_price=market_price,
        actual_action=actual_action, actual_price=actual_price,
        extra={"cme_prob": round(cme_prob, 4), "ensemble_prob": ensemble_prob,
               "cme_edge": round(cme_edge, 4)},
    )


def log_uniform_sizing(ticker: str, domain: str, actual_action: str,
                       actual_price: float, actual_size: float,
                       uniform_size: float = 10.0):
    """
    Log what flat $10 uniform sizing would have deployed vs actual Kelly sizing.
    Call for every trade that is approved by strategy.py (should_enter returns True).
    """
    _log_baseline(
        baseline_type="uniform_sizing",
        ticker=ticker, domain=domain,
        baseline_action=actual_action, baseline_price=actual_price,
        actual_action=actual_action, actual_price=actual_price,
        extra={"baseline_size": uniform_size, "actual_size": round(actual_size, 2)},
    )
