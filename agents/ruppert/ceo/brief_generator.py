"""
brief_generator.py — CEO Daily Brief Generator.
Owner: CEO agent. Runs at 8PM daily via Task Scheduler.

Synthesizes the day's events, trades, P&L, and alerts into a concise
daily brief for David. Reads from truth files and raw logs.

Writes to: reports/daily_brief_YYYY-MM-DD.md
Sends via: Telegram

Coexists with daily_progress_report.py — both may be active.

Usage:
  python -m agents.ruppert.ceo.brief_generator
  python agents/ceo/brief_generator.py
"""

"""
HARDENED ROLE:
- Generates trading briefs ONLY
- Does not respond to general queries
- Does not execute arbitrary tasks
- Reports to David via Telegram at 8PM daily
"""

import sys
import json
from datetime import date, datetime, timedelta
from pathlib import Path

CEO_ALLOWED_TASKS = [
    'generate_brief',
    'send_brief',
    'summarize_trades',
    'report_pnl',
    'alert_anomaly',
]

# All known trading modules — used to backfill zero-trade entries in the brief
KNOWN_MODULES = ['crypto', 'weather', 'geo', 'fed', 'econ', 'crypto_15m']


def check_role_boundary(task: str):
    """
    Enforce CEO role boundary.
    CEO only handles trading-related tasks.
    """
    if task not in CEO_ALLOWED_TASKS:
        raise ValueError(
            f"CEO role violation: '{task}' is not a trading task. "
            f"CEO is hardened to trading-only. Use Ruppert main session for general tasks."
        )


# Resolve environment root via env_config (workspace-level agents)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents/ruppert → workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths  # noqa: E402

# -----------------------------------------------------------------------
# Path constants (environment-aware via env_config)
# -----------------------------------------------------------------------
_env_paths = _get_paths()
LOGS_DIR = _env_paths['logs']
TRUTH_DIR = _env_paths['truth']
RAW_DIR = _env_paths['raw']
TRADES_DIR = _env_paths['trades']
REPORTS_DIR = _env_paths['reports']


# -----------------------------------------------------------------------
# Readers
# -----------------------------------------------------------------------

def _read_json(path: Path, default=None):
    """Safely read a JSON file. Returns default on error."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list. Skips bad lines."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            pass
    return records


def _load_today_events() -> list[dict]:
    """Load all events from today's raw event log."""
    path = RAW_DIR / f'events_{date.today().isoformat()}.jsonl'
    return _read_jsonl(path)


def _load_today_trades() -> list[dict]:
    """Load all trades from today's trade log."""
    path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
    return _read_jsonl(path)


def _load_all_trades_for_pnl() -> list[dict]:
    """Load trades from last 7 days for rolling P&L."""
    trades = []
    for i in range(7):
        day = (date.today() - timedelta(days=i)).isoformat()
        path = TRADES_DIR / f'trades_{day}.jsonl'
        trades.extend(_read_jsonl(path))
    return trades


# -----------------------------------------------------------------------
# Analyzers
# -----------------------------------------------------------------------

def _compute_pnl_from_trades(trades: list[dict]) -> dict:
    """
    Compute P&L summary from trade records.
    Returns: {closed_pnl, open_cost, wins, losses, total_trades}
    """
    closed_pnl = 0.0
    open_cost = 0.0
    wins = 0
    losses = 0
    open_positions = {}

    for t in trades:
        action = t.get('action', 'buy')
        size = float(t.get('size_dollars', 0) or 0)
        ticker = t.get('ticker', '')

        if action in ('buy', 'open'):
            open_positions[ticker] = open_positions.get(ticker, 0) + size
            open_cost += size
        elif action in ('exit', 'settle'):
            # Remove from open if present
            open_cost -= open_positions.pop(ticker, 0)
            # Try 'pnl' first (current field name), fall back to 'realized_pnl' for older records
            pnl_raw = t.get('pnl') if t.get('pnl') is not None else t.get('realized_pnl')
            if pnl_raw is not None:
                pnl_val = float(pnl_raw)
                closed_pnl += pnl_val
                if pnl_val >= 0:
                    wins += 1
                else:
                    losses += 1
            else:
                # Fallback: use settlement_result field if available
                result = t.get('settlement_result')
                if result == 'yes':
                    wins += 1
                elif result == 'no':
                    losses += 1
                elif size > 0:
                    wins += 1  # last resort estimate

    return {
        'closed_pnl': round(closed_pnl, 2),
        'open_cost': round(open_cost, 2),
        'wins': wins,
        'losses': losses,
        'total_trades': len(trades),
    }


def _summarize_trades_by_module(trades: list[dict]) -> dict:
    """Aggregate trade counts and sizes by module."""
    by_module = {}
    for t in trades:
        module = t.get('module') or t.get('source', 'unknown')
        action = t.get('action', 'buy')
        size = float(t.get('size_dollars', 0) or 0)
        edge = float(t.get('edge', 0) or 0)

        if module not in by_module:
            by_module[module] = {'count': 0, 'total_size': 0.0, 'edges': [], 'exits': 0}

        if action in ('buy', 'open'):
            by_module[module]['count'] += 1
            by_module[module]['total_size'] += size
            if edge:
                by_module[module]['edges'].append(edge)
        elif action in ('exit', 'settle'):
            by_module[module]['exits'] += 1

    # Compute avg edge
    for mod in by_module:
        edges = by_module[mod].pop('edges', [])
        by_module[mod]['avg_edge_pct'] = round(sum(edges) / len(edges) * 100, 1) if edges else 0.0

    return by_module


def _get_open_positions_summary(today_trades: list[dict]) -> dict:  # noqa: ARG001
    """Compute open positions from last 7 days of trade activity.

    today_trades parameter is retained for signature compatibility but ignored;
    the function now reads the full 7-day lookback to catch multi-day positions.
    """
    all_trades = _load_all_trades_for_pnl()  # 7-day lookback
    # Sort by timestamp ascending so later records override earlier ones
    all_trades_sorted = sorted(all_trades, key=lambda t: t.get('timestamp', ''))
    open_pos = {}
    for t in all_trades_sorted:
        action = t.get('action', 'buy')
        ticker = t.get('ticker', '')
        size = float(t.get('size_dollars', 0) or 0)
        module = t.get('module') or t.get('source', 'unknown')

        if action in ('buy', 'open'):
            prev_size = open_pos.get(ticker, {}).get('size', 0)
            open_pos[ticker] = {'size': prev_size + size, 'module': module}
        elif action in ('exit', 'settle'):
            open_pos.pop(ticker, None)

    return {
        'count': len(open_pos),
        'total_deployed': round(sum(v['size'] for v in open_pos.values()), 2),
        'positions': list(open_pos.keys()),
    }


def _summarize_events(events: list[dict]) -> dict:
    """Summarize key event types from today's event log."""
    summary = {
        'circuit_breaker_trips': 0,
        'anomalies': [],
        'scan_modes': [],
        'alert_candidates': 0,
        'trade_failures': 0,
        'settlements': [],
    }

    for e in events:
        etype = e.get('type', '')

        if etype == 'CIRCUIT_BREAKER':
            summary['circuit_breaker_trips'] += 1

        elif etype == 'ANOMALY_DETECTED':
            summary['anomalies'].append({
                'check': e.get('check', ''),
                'detail': e.get('detail', ''),
            })

        elif etype == 'SCAN_COMPLETE':
            summary['scan_modes'].append(e.get('mode', 'unknown'))

        elif etype == 'ALERT_CANDIDATE':
            summary['alert_candidates'] += 1

        elif etype == 'TRADE_FAILED':
            summary['trade_failures'] += 1

        elif etype == 'SETTLEMENT':
            summary['settlements'].append({
                'ticker': e.get('ticker', ''),
                'pnl': e.get('pnl', 0),
            })

    return summary


def _get_capital_summary() -> dict:
    """Get capital info from Data Scientist's truth file + capital module."""
    pnl_cache = _read_json(TRUTH_DIR / 'pnl_cache.json', {})
    closed_pnl = pnl_cache.get('closed_pnl', 0.0)

    try:
        from agents.ruppert.data_scientist.capital import get_capital
        capital = get_capital()
    except Exception:
        capital = None

    return {
        'closed_pnl': closed_pnl,
        'current_capital': capital,
    }


def _get_pending_alerts() -> list[dict]:
    """Load pending alerts from Data Scientist's truth file."""
    return _read_json(TRUTH_DIR / 'pending_alerts.json', [])


def _get_research_opportunities() -> dict:
    """Load latest research opportunities backlog summary."""
    backlog = _read_json(TRUTH_DIR / 'opportunities_backlog.json', [])
    if not backlog:
        return {'total': 0, 'pursue': 0, 'monitor': 0}

    pursue = sum(1 for o in backlog if o.get('recommendation') == 'PURSUE')
    monitor = sum(1 for o in backlog if o.get('recommendation') == 'MONITOR')
    return {'total': len(backlog), 'pursue': pursue, 'monitor': monitor}


# -----------------------------------------------------------------------
# Report builder
# -----------------------------------------------------------------------

def build_brief() -> str:
    """
    Synthesize all data into a concise markdown daily brief.
    Returns markdown string.
    """
    today_str = date.today().isoformat()
    import time as _time
    _tz_abbr = 'PDT' if _time.localtime().tm_isdst > 0 else 'PST'
    now_str = datetime.now().strftime(f'%H:%M {_tz_abbr}')

    # Load all data
    events = _load_today_events()
    today_trades = _load_today_trades()
    weekly_trades = _load_all_trades_for_pnl()

    pnl_today = _compute_pnl_from_trades(today_trades)
    pnl_week = _compute_pnl_from_trades(weekly_trades)
    module_stats = _summarize_trades_by_module(today_trades)
    # Backfill zero-trade entries so all known modules always appear
    for _mod in KNOWN_MODULES:
        if _mod not in module_stats:
            module_stats[_mod] = {'count': 0, 'total_size': 0.0, 'avg_edge_pct': 0.0, 'exits': 0}
    open_pos = _get_open_positions_summary(today_trades)
    event_summary = _summarize_events(events)
    capital_info = _get_capital_summary()
    alerts = _get_pending_alerts()
    research = _get_research_opportunities()

    # -----------------------------------------------------------------------
    # Build markdown
    # -----------------------------------------------------------------------
    lines = [
        f"# 📊 Ruppert Daily Brief — {today_str}",
        f"",
        f"**Generated:** {now_str}  ",
        f"**Mode:** {'LIVE' if _is_live_mode() else 'DEMO (DRY RUN)'}",
        f"",
        f"---",
        f"",
        f"## 💰 P&L Summary",
        f"",
        f"| Period | P&L | Wins | Losses | Trades |",
        f"|--------|-----|------|--------|--------|",
        f"| Today | ${pnl_today['closed_pnl']:+.2f} | {pnl_today['wins']}W | {pnl_today['losses']}L | {pnl_today['total_trades']} |",
        f"| Last 7 Days | ${pnl_week['closed_pnl']:+.2f} | {pnl_week['wins']}W | {pnl_week['losses']}L | {pnl_week['total_trades']} |",
        f"",
    ]

    # Capital
    if capital_info.get('current_capital') is not None:
        lines += [
            f"**Account capital:** ${capital_info['current_capital']:,.2f}  ",
        ]
    lines += [
        f"**Closed P&L (truth file):** ${capital_info.get('closed_pnl', 0):+.2f}",
        f"",
    ]

    # Open positions
    lines += [
        f"## 📈 Open Positions",
        f"",
        f"**Count:** {open_pos['count']} positions  ",
        f"**Deployed:** ${open_pos['total_deployed']:,.2f}",
        f"",
    ]
    if open_pos['positions']:
        lines.append("**Tickers:**")
        for ticker in open_pos['positions'][:10]:  # show up to 10
            lines.append(f"- {ticker}")
        if len(open_pos['positions']) > 10:
            lines.append(f"- _...and {len(open_pos['positions']) - 10} more_")
        lines.append("")

    # Module performance
    if module_stats:
        lines += [
            f"## 🔧 Module Performance (Today)",
            f"",
            f"| Module | Trades | Deployed | Avg Edge | Exits |",
            f"|--------|--------|----------|----------|-------|",
        ]
        for module, stats in sorted(module_stats.items()):
            lines.append(
                f"| {module.capitalize()} | {stats['count']} | "
                f"${stats['total_size']:,.0f} | {stats['avg_edge_pct']}% | {stats['exits']} |"
            )
        lines.append("")

    # Scan activity
    if event_summary['scan_modes']:
        lines += [
            f"## 🔄 Scan Activity",
            f"",
            f"**Cycles completed:** {len(event_summary['scan_modes'])}  ",
            f"**Modes:** {', '.join(set(event_summary['scan_modes']))}",
            f"",
        ]

    # Settlements
    if event_summary['settlements']:
        lines += [
            f"## ✅ Settlements Today",
            f"",
        ]
        total_settled_pnl = sum(s.get('pnl', 0) or 0 for s in event_summary['settlements'])
        lines.append(f"**{len(event_summary['settlements'])} positions settled | Net P&L: ${total_settled_pnl:+.2f}**")
        lines.append("")
        for s in event_summary['settlements'][:5]:
            pnl_val = s.get('pnl', 0) or 0
            emoji = '✅' if pnl_val >= 0 else '❌'
            lines.append(f"- {emoji} {s['ticker']} | P&L: ${pnl_val:+.2f}")
        if len(event_summary['settlements']) > 5:
            lines.append(f"- _...and {len(event_summary['settlements']) - 5} more_")
        lines.append("")

    # Alerts
    if alerts:
        lines += [
            f"## 🚨 Pending Alerts ({len(alerts)})",
            f"",
        ]
        for alert in alerts[-5:]:  # show last 5 (most recent)
            level = alert.get('level', 'info').upper()
            msg = alert.get('message', '')[:120]  # truncate long messages
            lines.append(f"- **[{level}]** {msg}")
        lines.append("")

    # Anomalies / circuit breakers
    if event_summary['circuit_breaker_trips'] > 0:
        lines += [
            f"## ⛔ Circuit Breaker",
            f"",
            f"**{event_summary['circuit_breaker_trips']} circuit breaker trip(s) today.**",
            f"",
        ]

    if event_summary['anomalies']:
        lines += [
            f"## ⚠️ Anomalies Detected",
            f"",
        ]
        for anomaly in event_summary['anomalies'][:5]:
            lines.append(f"- **{anomaly['check']}:** {anomaly['detail']}")
        lines.append("")

    if event_summary['trade_failures'] > 0:
        lines += [
            f"## ❌ Trade Failures",
            f"",
            f"**{event_summary['trade_failures']} trade failure(s) today.** Check logs/raw/events_*.jsonl.",
            f"",
        ]

    # Research backlog teaser
    if research['total'] > 0:
        lines += [
            f"## 🔬 Research Pipeline",
            f"",
            f"**Opportunities backlog:** {research['total']} total | "
            f"{research['pursue']} PURSUE | {research['monitor']} MONITOR",
            f"",
        ]

    # Footer
    lines += [
        f"---",
        f"",
        f"_Brief auto-generated by CEO agent. Source: logs/truth/ + logs/raw/events_{today_str}.jsonl_",
        f"",
        f"**Next actions for David:**",
        f"1. Review any CIRCUIT BREAKER or anomaly items above",
        f"2. Check PURSUE items in research backlog for scanner development",
        f"3. Approve any pending high-conviction trades in dashboard",
    ]

    return '\n'.join(lines)


def _is_live_mode() -> bool:
    """Check if running in live mode."""
    try:
        from agents.ruppert.env_config import is_live_enabled
        return is_live_enabled()
    except Exception:
        return False


# -----------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------

def write_brief_to_file(content: str) -> Path:
    """Write brief to reports/daily_brief_YYYY-MM-DD.md."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today_str = date.today().isoformat()
    path = REPORTS_DIR / f'daily_brief_{today_str}.md'
    path.write_text(content, encoding='utf-8')
    print(f"[CEO] Brief written to {path}")
    return path


def send_brief_telegram(telegram_summary: str) -> bool:
    """Send brief summary via Telegram. Pass the result of _build_telegram_summary()."""
    try:
        from agents.ruppert.data_scientist.logger import send_telegram
        return send_telegram(telegram_summary)
    except Exception as e:
        print(f"[CEO] Telegram send failed: {e}")
        return False


def _build_telegram_summary() -> str:
    """
    Build a concise Telegram-friendly summary (no markdown tables).
    Telegram doesn't render MD tables, so we use bullets.
    """
    today_str = date.today().isoformat()
    import time as _time
    _tz_abbr = 'PDT' if _time.localtime().tm_isdst > 0 else 'PST'
    now_str = datetime.now().strftime(f'%H:%M {_tz_abbr}')

    events = _load_today_events()
    today_trades = _load_today_trades()

    pnl_today = _compute_pnl_from_trades(today_trades)
    pnl_week = _compute_pnl_from_trades(_load_all_trades_for_pnl())
    open_pos = _get_open_positions_summary(today_trades)
    event_summary = _summarize_events(events)
    capital_info = _get_capital_summary()
    alerts = _get_pending_alerts()
    module_stats = _summarize_trades_by_module(today_trades)
    # Backfill zero-trade entries so all known modules always appear
    for _mod in KNOWN_MODULES:
        if _mod not in module_stats:
            module_stats[_mod] = {'count': 0, 'total_size': 0.0, 'avg_edge_pct': 0.0, 'exits': 0}

    mode_tag = '🔴 LIVE' if _is_live_mode() else '🔵 DEMO'
    circuit_tag = '⛔ CIRCUIT BREAKER TRIPPED\n' if event_summary['circuit_breaker_trips'] > 0 else ''

    lines = [
        f"📊 Ruppert Daily Brief — {today_str} {now_str}",
        f"{mode_tag} | {circuit_tag}",
        f"",
        f"💰 P&L Today: ${pnl_today['closed_pnl']:+.2f} ({pnl_today['wins']}W/{pnl_today['losses']}L, {pnl_today['total_trades']} trades)",
        f"💰 P&L 7-Day: ${pnl_week['closed_pnl']:+.2f}",
    ]

    if capital_info.get('current_capital') is not None:
        lines.append(f"💼 Capital: ${capital_info['current_capital']:,.2f}")

    lines += [
        f"📈 Open: {open_pos['count']} positions (${open_pos['total_deployed']:,.2f} deployed)",
        f"",
    ]

    # Module breakdown
    if module_stats:
        lines.append("MODULES:")
        for module, stats in sorted(module_stats.items()):
            lines.append(
                f"  {module.capitalize()}: {stats['count']} trades | "
                f"${stats['total_size']:,.0f} | edge {stats['avg_edge_pct']}%"
            )
        lines.append("")

    # Scans
    if event_summary['scan_modes']:
        lines.append(f"🔄 {len(event_summary['scan_modes'])} scan cycle(s): {', '.join(set(event_summary['scan_modes']))}")

    # Settlements
    if event_summary['settlements']:
        total_settled = sum(s.get('pnl', 0) or 0 for s in event_summary['settlements'])
        lines.append(f"✅ {len(event_summary['settlements'])} settlement(s) | Net: ${total_settled:+.2f}")

    # Alerts
    if alerts:
        lines.append(f"🚨 {len(alerts)} pending alert(s)")

    # Anomalies
    if event_summary['anomalies']:
        lines.append(f"⚠️ {len(event_summary['anomalies'])} anomaly/anomalies detected")

    # Trade failures
    if event_summary['trade_failures']:
        lines.append(f"❌ {event_summary['trade_failures']} trade failure(s)")

    return '\n'.join(lines)


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

def main():
    """Main entry point. Generate brief, write file, send Telegram."""
    print(f"\n{'='*60}")
    print(f"[CEO] Generating daily brief — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # Build full markdown brief
    brief_content = build_brief()

    # Write to file
    brief_path = write_brief_to_file(brief_content)
    print(f"[CEO] Brief saved: {brief_path}")

    # Print to stdout
    print(f"\n--- BRIEF PREVIEW ---")
    print(brief_content[:500] + '...' if len(brief_content) > 500 else brief_content)
    print(f"--- END PREVIEW ---\n")

    # Send via Telegram
    telegram_content = _build_telegram_summary()
    ok = send_brief_telegram(telegram_content)
    if ok:
        print('[CEO] Daily brief sent via Telegram.')
    else:
        print('[CEO] Telegram send failed — brief saved to file only.')

    return {'status': 'ok', 'path': str(brief_path), 'telegram_sent': ok}


if __name__ == '__main__':
    result = main()
    sys.exit(0 if result.get('status') == 'ok' else 1)
