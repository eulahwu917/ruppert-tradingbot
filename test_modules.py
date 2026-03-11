"""Quick test of all modules."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from gaming_scout import run_daily_scout
from economics_scanner import find_econ_opportunities
from geopolitical_scanner import run_geo_scan

print("=== GAMING SCOUT ===")
markets = run_daily_scout()
print(f"Found {len(markets)} gaming/tech markets (filtered)")
for m in markets[:8]:
    title = (m['title'] or '').encode('ascii', 'replace').decode()
    prob = f"{m['market_prob']:.0%}" if m['market_prob'] else "?"
    print(f"  [{m['ticker']}] {title[:70]} | {prob}")

print()
print("=== ECONOMICS ===")
opps = find_econ_opportunities()
print(f"Found {len(opps)} economics markets")
for o in opps[:8]:
    title = (o['title'] or '').encode('ascii', 'replace').decode()
    print(f"  [{o['ticker']}] {title[:70]} | {o['market_prob']:.0%}")

print()
print("=== GEOPOLITICAL ===")
geo = run_geo_scan()
print(f"Found {len(geo)} geopolitical markets with news signal")
for g in geo[:5]:
    title = (g['title'] or '').encode('ascii', 'replace').decode()
    print(f"  [{g['ticker']}] {title[:70]} | News: {g['news_signal']}")
