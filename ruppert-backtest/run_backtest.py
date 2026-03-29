"""
Ruppert Backtest Runner — per-domain autoresearch trigger.

Reads scored predictions from logs/scored_predictions.jsonl and triggers
autoresearch only for domains that have >= 30 scored trades.
"""

import json
from pathlib import Path

_SCORED_FILE = Path(__file__).resolve().parent.parent / "logs" / "scored_predictions.jsonl"
THRESHOLD = 30


def get_domain_trade_counts(scored_predictions_path=None) -> dict:
    """
    Read scored_predictions.jsonl and return per-domain trade counts.

    Returns:
        {weather: N, crypto: N, fed: N, geo: N, econ: N}
    """
    path = Path(scored_predictions_path) if scored_predictions_path else _SCORED_FILE
    counts = {"weather": 0, "crypto": 0, "fed": 0, "geo": 0, "econ": 0}

    if not path.exists():
        return counts

    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines:
            try:
                entry = json.loads(line)
                domain = entry.get("domain", "unknown")
                if domain in counts:
                    counts[domain] += 1
            except Exception:
                continue
    except Exception:
        pass

    return counts


def get_eligible_domains(scored_predictions_path=None) -> list:
    """Return list of domains that have >= THRESHOLD scored trades."""
    counts = get_domain_trade_counts(scored_predictions_path)
    return [domain for domain, count in counts.items() if count >= THRESHOLD]


if __name__ == "__main__":
    counts = get_domain_trade_counts()
    print("Per-domain scored trade counts:")
    for domain, count in counts.items():
        status = "ELIGIBLE" if count >= THRESHOLD else f"{count}/{THRESHOLD}"
        print(f"  {domain}: {status}")

    eligible = get_eligible_domains()
    if eligible:
        print(f"\nDomains eligible for autoresearch: {', '.join(eligible)}")
    else:
        print(f"\nNo domain has reached {THRESHOLD} scored trades yet.")
