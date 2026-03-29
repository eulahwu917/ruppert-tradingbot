"""
Autoresearch — per-domain experiment runner.

Only runs experiments for domains that have >= 30 scored trades.
Uses get_domain_trade_counts() from run_backtest.py.
"""

import sys
from pathlib import Path

# Ensure parent directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_backtest import get_domain_trade_counts, get_eligible_domains, THRESHOLD


def run_autoresearch():
    """Run autoresearch for eligible domains."""
    counts = get_domain_trade_counts()

    # Print per-domain status
    print("Autoresearch — per-domain status:")
    for domain in ["weather", "crypto", "crypto_15m", "fed", "geo", "econ"]:
        count = counts.get(domain, 0)
        print(f"  {domain.capitalize()}: {count}/{THRESHOLD}")

    # Determine eligible domains
    eligible = get_eligible_domains()

    if not eligible:
        print("\nAutoresearch blocked: no domain has reached 30 scored trades yet.")
        return

    print(f"\nRunning experiments for: {', '.join(eligible)}")

    for domain in eligible:
        print(f"\n--- Autoresearch: {domain} ({counts[domain]} scored trades) ---")
        # TODO: plug in domain-specific experiment logic
        print(f"  [placeholder] {domain} experiments would run here")


if __name__ == "__main__":
    run_autoresearch()
