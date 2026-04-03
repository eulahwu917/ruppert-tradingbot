#!/usr/bin/env python3
"""
Run self-improving agent for each persistent Ruppert agent.

Persistent agents: Strategist, Data Analyst, Trader
Each gets their own improvement_log.md in their role directory.

Usage:
    python scripts/run_self_improvement.py              # run all agents
    python scripts/run_self_improvement.py --agent trader  # run one agent
    python scripts/run_self_improvement.py --report     # weekly report for all
"""

import sys
import argparse
from pathlib import Path

# Add workspace skills to path
WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE / "skills" / "xiucheng-self-improving-agent"))

from self_improving import SelfImprovingAgent

PERSISTENT_AGENTS = {
    "strategist": WORKSPACE / "agents" / "ruppert" / "strategist",
    "data_analyst": WORKSPACE / "agents" / "ruppert" / "data_analyst",
    "data_scientist": WORKSPACE / "agents" / "ruppert" / "data_scientist",
    "trader": WORKSPACE / "agents" / "ruppert" / "trader",
}

SHARED_MEMORY = WORKSPACE / "MEMORY.md"


def read_shared_memory() -> str:
    """Read shared MEMORY.md for system-wide context."""
    if SHARED_MEMORY.exists():
        return SHARED_MEMORY.read_text(encoding="utf-8")
    return ""


def run_for_agent(name: str, agent_dir: Path, report: bool = False):
    """Run self-improvement analysis for a single agent."""
    print(f"\n{'='*50}")
    print(f"Agent: {name.upper()}")
    print(f"Dir: {agent_dir}")
    print('='*50)

    # Point SIA at this agent's directory
    sia = SelfImprovingAgent(workspace=str(agent_dir))
    sia.improvement_log = agent_dir / "improvement_log.md"
    sia.soul_file = agent_dir / "ROLE.md"  # ROLE.md is this agent's personality anchor

    # Include shared memory context in analysis
    shared_context = read_shared_memory()
    if shared_context:
        print(f"[Shared MEMORY.md loaded: {len(shared_context)} chars]")

    stats = sia.get_improvement_stats()
    print(f"Stats: {stats}")

    if report:
        # Analyze both agent-specific log and shared memory
        report_text = sia.generate_weekly_report()
        if shared_context:
            report_text += "\n\n## 📌 Shared System Context (from MEMORY.md)\n"
            report_text += "_Key system decisions relevant to this agent — see MEMORY.md for full details._\n"
        print(report_text)
    else:
        suggestions = sia.suggest_soul_updates()
        if suggestions and suggestions[0] != "Start logging improvements to generate suggestions":
            print(f"ROLE.md suggestions:")
            for s in suggestions:
                print(f"  - {s}")
        else:
            print("No ROLE.md suggestions at this time.")


def main():
    parser = argparse.ArgumentParser(description="Run self-improvement for Ruppert agents")
    parser.add_argument("--agent", choices=list(PERSISTENT_AGENTS.keys()),
                        help="Run for a specific agent only")
    parser.add_argument("--report", "-r", action="store_true",
                        help="Generate weekly report for each agent")
    parser.add_argument("--log", "-l", help="Log an improvement insight")
    parser.add_argument("--category", "-c", default="general", help="Insight category")

    args = parser.parse_args()

    agents_to_run = (
        {args.agent: PERSISTENT_AGENTS[args.agent]}
        if args.agent
        else PERSISTENT_AGENTS
    )

    for name, agent_dir in agents_to_run.items():
        if args.log:
            sia = SelfImprovingAgent(workspace=str(agent_dir))
            sia.improvement_log = agent_dir / "improvement_log.md"
            sia.log_improvement(args.log, args.category)
            print(f"✅ [{name}] Logged: {args.log}")
        else:
            run_for_agent(name, agent_dir, report=args.report)


if __name__ == "__main__":
    main()
