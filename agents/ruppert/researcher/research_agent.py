"""
research_agent.py — Researcher agent for Ruppert trading bot.
Owner: Researcher (Sonnet). Runs weekly (Sunday 8AM via Ruppert-Research-Weekly Task Scheduler task).

Discovers new Kalshi market opportunities and new data sources.
- Scans Kalshi API for market categories not currently traded
- Checks economic calendar coverage gaps
- Surfaces hypotheses about new signal sources

Writes findings to:
  - logs/truth/opportunities_backlog.json   (Researcher owns)
  - reports/research/report_YYYY-MM-DD.md   (Researcher owns)

Usage:
  python -m agents.ruppert.researcher.research_agent
  python agents/ruppert/researcher/research_agent.py
"""

import sys
import json
from datetime import date, datetime
from pathlib import Path

# Ensure project root on path
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.researcher.market_scanner import (
    scan_all_candidates,
    classify_opportunity,
    check_economic_calendar_gaps,
    generate_signal_hypotheses,
    CANDIDATE_SERIES_TO_SCAN,
    CA_RESTRICTED_SERIES,
)

# Output paths (as per architecture spec) — env-aware via env_config
from agents.ruppert.env_config import get_paths as _get_paths
_env_paths = _get_paths()
TRUTH_DIR = _env_paths['truth']
REPORTS_DIR = _env_paths['reports'] / 'research'
BACKLOG_FILE = TRUTH_DIR / 'opportunities_backlog.json'


def _write_opportunities_backlog(opportunities: list[dict]) -> None:
    """Write opportunities to truth file. Researcher owns this file."""
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing backlog to preserve all existing entries
    existing = []
    if BACKLOG_FILE.exists():
        try:
            existing = json.loads(BACKLOG_FILE.read_text(encoding='utf-8'))
        except Exception:
            existing = []

    # Merge: update existing entries, add new ones
    # .get('series') guard: silently skip any corrupt/legacy entries missing the series key
    # Filter out CA-restricted entries that may have been written by pre-patch scans
    updated = {e['series']: e for e in existing if e.get('series') and e.get('series') not in CA_RESTRICTED_SERIES}
    for opp in opportunities:
        series = opp.get('series')
        if series:
            opp['last_scanned'] = date.today().isoformat()
            updated[series] = opp

    # Sort by priority descending, then series name
    merged = sorted(updated.values(), key=lambda x: (-x.get('priority', 0), x.get('series', '')))

    tmp = BACKLOG_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(merged, indent=2), encoding='utf-8')
    tmp.replace(BACKLOG_FILE)
    print(f"[Researcher] Wrote {len(merged)} opportunities to {BACKLOG_FILE}")


def _write_markdown_report(
    scan_results: list[dict],
    opportunities: list[dict],
    econ_gaps: list[dict],
    hypotheses: list[dict],
) -> Path:
    """Write human-readable research report to reports/research/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    report_path = REPORTS_DIR / f'report_{today_str}.md'

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Sort opportunities by recommendation priority
    rec_order = {'PURSUE': 0, 'MONITOR': 1, 'PASS': 2, 'SKIP': 3}
    sorted_opps = sorted(opportunities, key=lambda x: rec_order.get(x.get('recommendation', 'SKIP'), 3))

    pursue = [o for o in sorted_opps if o.get('recommendation') == 'PURSUE']
    monitor = [o for o in sorted_opps if o.get('recommendation') == 'MONITOR']
    skip = [o for o in sorted_opps if o.get('recommendation') in ('PASS', 'SKIP')]

    lines = [
        f"# Ruppert Research Report — {today_str}",
        f"",
        f"**Generated:** {now_str}  ",
        f"**Agent:** Researcher (Sonnet)  ",
        f"**Candidates scanned:** {len(scan_results)}  ",
        f"",
        f"---",
        f"",
        f"## Executive Summary",
        f"",
        f"- **PURSUE:** {len(pursue)} series ready for immediate scanner development",
        f"- **MONITOR:** {len(monitor)} series worth watching",
        f"- **PASS/SKIP:** {len(skip)} series not worth pursuing now",
        f"- **Economic calendar gaps:** {len(econ_gaps)} uncovered series found",
        f"- **Signal hypotheses:** {len(hypotheses)} new ideas surfaced",
        f"",
        f"---",
        f"",
        f"## 🟢 PURSUE — Build Scanners Now",
        f"",
    ]

    if pursue:
        for opp in pursue:
            lines += [
                f"### {opp['series']}",
                f"- **Markets open:** {opp.get('count', 'N/A')}",
                f"- **Volume estimate:** ${opp.get('volume', 0):,.0f}",
                f"- **Score:** {opp.get('score', 0)}/7",
                f"- **Reasons:** {', '.join(opp.get('reasons', []))}",
            ]
            if opp.get('sample_titles'):
                lines.append(f"- **Sample markets:** {opp['sample_titles'][0]}")
            lines.append("")
    else:
        lines.append("_No series scored PURSUE in this scan._\n")

    lines += [
        f"## 🟡 MONITOR — Watch for Edge Development",
        f"",
    ]

    if monitor:
        for opp in monitor:
            lines += [
                f"### {opp['series']}",
                f"- {opp.get('count', 'N/A')} markets | ${opp.get('volume', 0):,.0f} vol | Score {opp.get('score', 0)}/7",
                f"- Reasons: {', '.join(opp.get('reasons', []))}",
                f"",
            ]
    else:
        lines.append("_No series scored MONITOR in this scan._\n")

    lines += [
        f"---",
        f"",
        f"## 📊 Economic Calendar Coverage Gaps",
        f"",
    ]

    if econ_gaps:
        for gap in econ_gaps:
            lines += [
                f"### {gap['series']} — {gap['description']}",
                f"- **Hypothesis:** {gap['hypothesis']}",
                f"",
            ]
    else:
        lines.append("_No coverage gaps found._\n")

    lines += [
        f"---",
        f"",
        f"## 💡 New Signal Source Hypotheses",
        f"",
    ]

    for h in hypotheses:
        effort_emoji = {'low': '🟢', 'medium': '🟡', 'high': '🔴'}.get(h.get('effort', 'medium'), '⚪')
        priority_emoji = {'high': '🔥', 'medium': '⚡', 'low': '💤'}.get(h.get('priority', 'medium'), '⚪')
        lines += [
            f"### {h['category']}",
            f"- **Effort:** {effort_emoji} {h.get('effort', 'unknown')}  | **Priority:** {priority_emoji} {h.get('priority', 'unknown')}",
            f"- **Hypothesis:** {h['hypothesis']}",
            f"- **Data needed:** {h.get('data_source_needed', 'TBD')}",
            f"- **Signals:** {', '.join(h.get('signal_sources', []))}",
            f"",
        ]

    # RESTRICTED section
    restricted = [o for o in opportunities if o.get('recommendation') == 'RESTRICTED']
    if restricted:
        lines.append('\n## 🚫 RESTRICTED — California Geo\n')
        for opp in restricted:
            lines.append(f"- **{opp['series']}** — {', '.join(opp.get('reasons', []))}")

    lines += [
        f"---",
        f"",
        f"## 📋 Full Scan Results",
        f"",
        f"| Series | Status | Markets | Volume Est |",
        f"|--------|--------|---------|------------|",
    ]

    for r in scan_results:
        status_emoji = {'found': '✅', 'no_open_markets': '⬜', 'unreachable': '❌'}.get(r.get('status', ''), '❓')
        lines.append(
            f"| {r['series']} | {status_emoji} {r.get('status', 'unknown')} | "
            f"{r.get('count', 0)} | ${r.get('volume_estimate', 0):,.0f} |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"_Report auto-generated by Researcher agent. Review PURSUE items and assign to Dev for scanner implementation._",
    ]

    report_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"[Researcher] Wrote report to {report_path}")
    return report_path


def run_research() -> dict:
    """
    Main research run. Called weekly by Task Scheduler.
    Returns summary dict.
    """
    print(f"\n{'='*60}")
    print(f"[Researcher] Starting weekly research scan — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 1. Scan Kalshi API for candidate series
    print("[Researcher] Step 1/4: Scanning Kalshi API for candidate series...")
    scan_results = scan_all_candidates(CANDIDATE_SERIES_TO_SCAN)

    # 2. Classify each result as opportunity
    print("\n[Researcher] Step 2/4: Classifying opportunities...")
    opportunities = [classify_opportunity(r) for r in scan_results]

    # 3. Check economic calendar gaps
    print("\n[Researcher] Step 3/4: Checking economic calendar coverage gaps...")
    econ_gaps = check_economic_calendar_gaps()
    print(f"  Found {len(econ_gaps)} uncovered economic series")

    # 4. Generate signal hypotheses
    print("\n[Researcher] Step 4/4: Generating signal hypotheses...")
    hypotheses = generate_signal_hypotheses()
    print(f"  Generated {len(hypotheses)} hypotheses")

    # Write outputs
    print("\n[Researcher] Writing outputs...")
    _write_opportunities_backlog(opportunities)
    report_path = _write_markdown_report(scan_results, opportunities, econ_gaps, hypotheses)

    # Summary
    pursue_count = sum(1 for o in opportunities if o.get('recommendation') == 'PURSUE')
    monitor_count = sum(1 for o in opportunities if o.get('recommendation') == 'MONITOR')

    summary = {
        'date': date.today().isoformat(),
        'completed_at': datetime.now().isoformat(),
        'series_scanned': len(scan_results),
        'pursue': pursue_count,
        'monitor': monitor_count,
        'econ_gaps': len(econ_gaps),
        'hypotheses': len(hypotheses),
        'report_path': str(report_path),
        'backlog_path': str(BACKLOG_FILE),
    }

    print(f"\n[Researcher] Research complete.")
    print(f"  PURSUE: {pursue_count} | MONITOR: {monitor_count} | Gaps: {len(econ_gaps)} | Hypotheses: {len(hypotheses)}")
    print(f"  Report: {report_path}")
    print(f"  Backlog: {BACKLOG_FILE}")

    return summary


if __name__ == '__main__':
    result = run_research()
    print(f"\nFinal summary: {json.dumps(result, indent=2)}")
