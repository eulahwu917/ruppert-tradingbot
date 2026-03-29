# Researcher agent package
# Imports are explicit in callers (e.g. research_agent.py imports from market_scanner directly).
# Lazy import pattern avoids triggering module-level side effects on package import.
# To use: from agents.ruppert.researcher.research_agent import run_research
#         from agents.ruppert.researcher.market_scanner import scan_all_candidates, classify_opportunity
