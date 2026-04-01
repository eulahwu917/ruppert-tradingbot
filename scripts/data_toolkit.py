"""
data_toolkit.py - Agent Data Analysis CLI
==========================================
Pre-built data access layer for Ruppert trading bot agents.
Eliminates the need for agents to read raw JSONL files.

Usage:
    python scripts/data_toolkit.py trades --module crypto_15m_dir --days 7 --output json
    python scripts/data_toolkit.py signals --days 7 --output json
    python scripts/data_toolkit.py capital --output json
    python scripts/data_toolkit.py winrate --module crypto_15m_dir --days 7 --by asset,hour,side,entry_price
    python scripts/data_toolkit.py positions --output json
    python scripts/data_toolkit.py decisions --module crypto_15m_dir --days 3 --output json

Author: DS (Data Scientist subagent)
Date: 2026-03-31
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Path Setup ───────────────────────────────────────────────────────────────
# Resolve paths relative to workspace root (where the script is called from)
_SCRIPT_DIR = Path(__file__).parent
_WORKSPACE = _SCRIPT_DIR.parent
_DEMO_ENV = _WORKSPACE / "environments" / "demo"
_LOGS = _DEMO_ENV / "logs"
_TRADES_DIR = _LOGS / "trades"
_DECISIONS_FILE = _LOGS / "decisions_15m.jsonl"
_DEPOSITS_FILE = _LOGS / "demo_deposits.jsonl"
_POSITIONS_FILE = _LOGS / "tracked_positions.json"


# ─── Utilities ────────────────────────────────────────────────────────────────

def _date_cutoff(days: int) -> str:
    """Return ISO date string for N days ago (UTC)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d")


def _parse_date(record: dict) -> str:
    """Extract date string from a record (normalized)."""
    # Try 'date' field first, then parse from 'timestamp'
    d = record.get("date") or record.get("ts") or ""
    if d and len(d) >= 10:
        return d[:10]
    ts = record.get("timestamp") or ""
    if ts and len(ts) >= 10:
        return ts[:10]
    return ""


def _extract_asset(ticker: str) -> str:
    """Extract asset name from Kalshi ticker (e.g. KXBTC15M-... -> BTC)."""
    if not ticker:
        return "UNKNOWN"
    # Remove KX prefix, then grab up to first digit
    t = ticker.upper()
    if t.startswith("KX"):
        t = t[2:]
    # Strip everything from first digit onward
    asset = ""
    for ch in t:
        if ch.isdigit() or ch == "-":
            break
        asset += ch
    return asset or ticker.split("-")[0]


def _load_jsonl(path: Path) -> list:
    """Load all valid JSON lines from a file. Returns [] if missing."""
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except (IOError, OSError):
        pass
    return records


def _load_trades(days: int = None, date: str = None, module: str = None, action: str = None) -> list:
    """
    Load and normalize trade records from daily JSONL files.
    Applies optional filters: days (lookback), date (exact), module, action.
    """
    if not _TRADES_DIR.exists():
        return []

    # Determine date cutoff
    if date:
        cutoff = date
    elif days is not None:
        cutoff = _date_cutoff(days)
    else:
        cutoff = "1970-01-01"

    records = []
    for p in sorted(_TRADES_DIR.glob("trades_*.jsonl")):
        file_date = p.stem.replace("trades_", "")
        if file_date < cutoff:
            continue
        for r in _load_jsonl(p):
            r["_file_date"] = file_date
            records.append(r)

    # Filter by date (exact match)
    if date:
        records = [r for r in records if _parse_date(r) == date]

    # Filter by module
    if module:
        records = [r for r in records if r.get("module") == module or r.get("_module_corrected_from") == module]

    # Filter by action
    if action:
        records = [r for r in records if r.get("action") == action]

    return records


# ─── Command: trades ──────────────────────────────────────────────────────────

def cmd_trades(args) -> list:
    """
    Load and normalize trade records.
    Returns list of dicts with consistent field names.
    """
    records = _load_trades(
        days=args.days,
        date=args.date,
        module=args.module,
        action=args.action,
    )

    normalized = []
    for r in records:
        normalized.append({
            "trade_id": r.get("trade_id", ""),
            "timestamp": r.get("timestamp", ""),
            "date": _parse_date(r),
            "ticker": r.get("ticker", ""),
            "title": r.get("title", ""),
            "asset": _extract_asset(r.get("ticker", "")),
            "side": r.get("side", ""),
            "action": r.get("action", ""),
            "action_detail": r.get("action_detail", ""),
            "module": r.get("module", ""),
            "source": r.get("source", ""),
            "entry_price": r.get("entry_price"),
            "exit_price": r.get("exit_price"),
            "fill_price": r.get("fill_price"),
            "size_dollars": r.get("size_dollars"),
            "contracts": r.get("contracts"),
            "edge": r.get("edge"),
            "confidence": r.get("confidence"),
            "market_prob": r.get("market_prob"),
            "pnl": r.get("pnl"),
            "pnl_correction": r.get("pnl_correction"),
        })
    return normalized


# ─── Command: signals ─────────────────────────────────────────────────────────

def cmd_signals(args) -> list:
    """
    Load decisions_15m.jsonl with signal components.
    Returns list of decision records.
    """
    cutoff = _date_cutoff(args.days)
    records = []

    for r in _load_jsonl(_DECISIONS_FILE):
        # Get timestamp
        ts = r.get("ts") or r.get("timestamp") or ""
        rec_date = ts[:10] if ts else ""
        if rec_date < cutoff:
            continue

        # Filter by decision
        if args.decision and r.get("decision") != args.decision.upper():
            continue

        # Filter by ticker
        if args.ticker:
            if args.ticker.upper() not in r.get("market_id", "").upper():
                continue

        sigs = r.get("signals", {})
        kal = r.get("kalshi", {})

        records.append({
            "ts": ts,
            "date": rec_date,
            "market_id": r.get("market_id", ""),
            "asset": _extract_asset(r.get("market_id", "")),
            "decision": r.get("decision", ""),
            "skip_reason": r.get("skip_reason"),
            "edge": r.get("edge"),
            "entry_price": r.get("entry_price"),
            "position_usd": r.get("position_usd"),
            # Signal components
            "tfi_z": sigs.get("tfi_z"),
            "obi_z": sigs.get("obi_z"),
            "macd_z": sigs.get("macd_z"),
            "oi_conviction_z": sigs.get("oi_conviction_z"),
            "raw_score": sigs.get("raw_score"),
            "P_final": sigs.get("P_final"),
            # Kalshi book state
            "yes_ask": kal.get("yes_ask"),
            "yes_bid": kal.get("yes_bid"),
            "spread": kal.get("spread"),
            "book_depth_usd": kal.get("book_depth_usd"),
        })

    return records


# ─── Command: capital ─────────────────────────────────────────────────────────

def cmd_capital(args) -> dict:
    """
    Compute current true capital.
    Replicates compute_closed_pnl_from_logs() logic.
    Returns {capital, closed_pnl, deposits, as_of}.
    """
    # Load all trade records (no date filter — capital is cumulative)
    all_records = _load_trades()

    # Compute closed P&L
    exit_pnl = 0.0
    settle_pnl = 0.0
    correction_pnl = 0.0

    # Deduplicate exit_corrections by (original_trade_id, pnl_correction)
    seen_corrections = set()

    for r in all_records:
        action = r.get("action", "")
        if action == "exit" and r.get("pnl") is not None:
            exit_pnl += float(r["pnl"])
        elif action == "settle" and r.get("pnl") is not None:
            settle_pnl += float(r["pnl"])
        elif action == "exit_correction":
            pnl_corr = r.get("pnl_correction")
            if pnl_corr is not None:
                orig_id = r.get("original_trade_id", r.get("trade_id", ""))
                key = (orig_id, float(pnl_corr))
                if key not in seen_corrections:
                    seen_corrections.add(key)
                    correction_pnl += float(pnl_corr)

    closed_pnl = round(exit_pnl + settle_pnl + correction_pnl, 2)

    # Load deposits
    deposits = []
    for r in _load_jsonl(_DEPOSITS_FILE):
        deposits.append({
            "date": r.get("date", ""),
            "amount": float(r.get("amount", 0)),
            "note": r.get("note", ""),
        })
    total_deposits = sum(d["amount"] for d in deposits)

    capital = round(total_deposits + closed_pnl, 2)

    return {
        "capital": capital,
        "closed_pnl": closed_pnl,
        "deposits": total_deposits,
        "deposit_records": deposits,
        "breakdown": {
            "exit_pnl": round(exit_pnl, 2),
            "settle_pnl": round(settle_pnl, 2),
            "correction_pnl": round(correction_pnl, 2),
        },
        "as_of": datetime.now().isoformat(),
    }


# ─── Command: winrate ─────────────────────────────────────────────────────────

def cmd_winrate(args) -> dict:
    """
    Pre-compute win rate breakdowns by matching buy records to exit/settle records.

    Win = trade closed with pnl > 0
    Loss = trade closed with pnl < 0
    Ties (pnl == 0) are excluded from win rate.

    Breakdown dimensions: asset, hour, side, entry_price, day
    """
    by_dims = [b.strip() for b in (args.by or "asset,hour,side").split(",")]

    # Load buy records
    buys = _load_trades(days=args.days, module=args.module, action="buy")

    # Load close records (exit + settle)
    closes_raw = _load_trades(days=args.days, module=args.module)
    closes = [r for r in closes_raw if r.get("action") in ("exit", "settle") and r.get("pnl") is not None]

    # Build lookup: ticker -> list of close records
    # Match buys to closes by ticker (and side where available)
    close_by_ticker_side = defaultdict(list)
    for c in closes:
        key = (c.get("ticker", ""), c.get("side", ""))
        close_by_ticker_side[key].append(c)

    # Build closed trade list: enrich closes with buy-side metadata
    # Strategy: for each close, find the corresponding buy and annotate
    matched_trades = []
    used_buy_ids = set()

    # Build buy lookup by ticker+side
    buy_by_ticker_side = defaultdict(list)
    for b in buys:
        key = (b.get("ticker", ""), b.get("side", ""))
        buy_by_ticker_side[key].append(b)

    for c in closes:
        pnl = c.get("pnl")
        if pnl is None:
            continue
        pnl = float(pnl)

        ticker = c.get("ticker", "")
        side = c.get("side", "")
        asset = _extract_asset(ticker)
        entry_price = c.get("entry_price")
        hour = None

        # Try to find matching buy for entry metadata
        key = (ticker, side)
        buy_candidates = buy_by_ticker_side.get(key, [])
        matched_buy = None
        for b in buy_candidates:
            bid = b.get("trade_id", "")
            if bid not in used_buy_ids:
                matched_buy = b
                used_buy_ids.add(bid)
                break

        if matched_buy:
            if entry_price is None:
                entry_price = matched_buy.get("entry_price") or matched_buy.get("fill_price")
            # Get hour from buy timestamp
            ts = matched_buy.get("timestamp", "")
            try:
                if "T" in ts:
                    hour = int(ts.split("T")[1][:2])
                elif " " in ts:
                    hour = int(ts.split(" ")[1][:2])
            except (IndexError, ValueError):
                hour = None

        # Entry price bucket
        ep_bucket = None
        if entry_price is not None:
            ep = float(entry_price)
            if ep < 20:
                ep_bucket = "<20c"
            elif ep < 40:
                ep_bucket = "20-40c"
            elif ep < 55:
                ep_bucket = "40-55c"
            elif ep < 70:
                ep_bucket = "55-70c"
            elif ep < 80:
                ep_bucket = "70-80c"
            else:
                ep_bucket = ">80c"

        matched_trades.append({
            "ticker": ticker,
            "asset": asset,
            "side": side,
            "pnl": pnl,
            "win": pnl > 0,
            "loss": pnl < 0,
            "date": _parse_date(c),
            "hour": hour,
            "entry_price_bucket": ep_bucket,
            "module": c.get("module", ""),
        })

    # ── Overall stats ──
    total_trades = len(matched_trades)
    wins = [t for t in matched_trades if t["win"]]
    losses = [t for t in matched_trades if t["loss"]]
    decisive = len(wins) + len(losses)
    overall_wr = round(len(wins) / decisive * 100, 1) if decisive > 0 else None
    overall_pnl = round(sum(t["pnl"] for t in matched_trades), 2)

    result = {
        "summary": {
            "total_closed": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "ties": total_trades - decisive,
            "win_rate_pct": overall_wr,
            "total_pnl": overall_pnl,
        },
        "breakdowns": {},
    }

    # ── Dimension breakdowns ──
    def make_breakdown(key_fn, label):
        groups = defaultdict(list)
        for t in matched_trades:
            k = key_fn(t)
            if k is not None:
                groups[k].append(t)
        breakdown = {}
        for k, trades in sorted(groups.items(), key=lambda x: str(x[0])):
            w = sum(1 for t in trades if t["win"])
            l = sum(1 for t in trades if t["loss"])
            d = w + l
            pnl = round(sum(t["pnl"] for t in trades), 2)
            breakdown[str(k)] = {
                "trades": len(trades),
                "wins": w,
                "losses": l,
                "win_rate_pct": round(w / d * 100, 1) if d > 0 else None,
                "total_pnl": pnl,
                "avg_pnl": round(pnl / len(trades), 2) if trades else None,
            }
        return breakdown

    for dim in by_dims:
        if dim == "asset":
            result["breakdowns"]["asset"] = make_breakdown(lambda t: t["asset"], "asset")
        elif dim == "hour":
            result["breakdowns"]["hour"] = make_breakdown(
                lambda t: f"{t['hour']:02d}:00" if t["hour"] is not None else None, "hour"
            )
        elif dim == "side":
            result["breakdowns"]["side"] = make_breakdown(lambda t: t["side"], "side")
        elif dim == "entry_price":
            result["breakdowns"]["entry_price"] = make_breakdown(
                lambda t: t["entry_price_bucket"], "entry_price"
            )
        elif dim == "day":
            result["breakdowns"]["day"] = make_breakdown(lambda t: t["date"], "day")

    return result


# ─── Command: positions ───────────────────────────────────────────────────────

def cmd_positions(args) -> list:
    """
    Load current open positions from tracked_positions.json.
    Returns list of open positions with age and basic metadata.
    """
    if not _POSITIONS_FILE.exists():
        return []

    try:
        data = json.loads(_POSITIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []

    if not isinstance(data, dict):
        return []

    now = datetime.now(timezone.utc).timestamp()
    positions = []

    for key, pos in data.items():
        added_at = pos.get("added_at")
        age_hours = None
        if added_at:
            try:
                age_hours = round((now - float(added_at)) / 3600, 1)
            except (TypeError, ValueError):
                pass

        entry_price = pos.get("entry_price")
        qty = pos.get("quantity", 0)

        positions.append({
            "key": key,
            "ticker": key.split("::")[0] if "::" in key else key,
            "side": key.split("::")[1] if "::" in key else pos.get("side", ""),
            "asset": _extract_asset(key.split("::")[0] if "::" in key else key),
            "quantity": qty,
            "entry_price": entry_price,
            "module": pos.get("module", ""),
            "title": pos.get("title", ""),
            "added_at": added_at,
            "age_hours": age_hours,
            "exit_thresholds": pos.get("exit_thresholds", []),
            # Rough cost basis
            "cost_basis_usd": round(float(entry_price or 0) * int(qty or 0) / 100, 2),
        })

    return positions


# ─── Command: decisions ───────────────────────────────────────────────────────

def cmd_decisions(args) -> dict:
    """
    Load decisions_15m.jsonl — like signals but more complete,
    includes SKIP reason breakdown.
    """
    # Reuse signals logic but also provide skip_reason breakdown
    records = cmd_signals(args)

    # SKIP reason breakdown
    skip_reasons = defaultdict(int)
    enter_count = 0
    skip_count = 0

    for r in records:
        if r["decision"] == "ENTER":
            enter_count += 1
        elif r["decision"] == "SKIP":
            skip_count += 1
            reason = r.get("skip_reason") or "UNKNOWN"
            skip_reasons[reason] += 1

    return {
        "records": records,
        "summary": {
            "total": len(records),
            "enter": enter_count,
            "skip": skip_count,
            "enter_rate_pct": round(enter_count / len(records) * 100, 1) if records else None,
        },
        "skip_reasons": dict(sorted(skip_reasons.items(), key=lambda x: -x[1])),
    }


# ─── Dispatch ─────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route to the correct command handler."""
    handlers = {
        "trades": cmd_trades,
        "signals": cmd_signals,
        "capital": cmd_capital,
        "winrate": cmd_winrate,
        "positions": cmd_positions,
        "decisions": cmd_decisions,
    }
    fn = handlers.get(args.command)
    if fn is None:
        return {"error": f"Unknown command: {args.command}"}
    return fn(args)


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Ruppert data toolkit — agent-friendly CLI for trade data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/data_toolkit.py trades --module crypto_15m_dir --days 7
  python scripts/data_toolkit.py signals --days 7 --decision ENTER
  python scripts/data_toolkit.py capital
  python scripts/data_toolkit.py winrate --module crypto_15m_dir --days 7 --by asset,hour,side,entry_price
  python scripts/data_toolkit.py positions
  python scripts/data_toolkit.py decisions --days 3 --decision SKIP
""",
    )
    parser.add_argument(
        "command",
        choices=["trades", "signals", "capital", "winrate", "positions", "decisions"],
        help="What data to load",
    )
    parser.add_argument("--module", default=None, help="Filter by module name (e.g. crypto_15m_dir)")
    parser.add_argument("--days", type=int, default=7, help="Load last N days (default: 7)")
    parser.add_argument("--date", default=None, help="Load specific date YYYY-MM-DD")
    parser.add_argument("--action", default=None, help="Filter by action (buy/exit/settle/exit_correction)")
    parser.add_argument("--decision", default=None, help="Filter by decision (ENTER/SKIP)")
    parser.add_argument("--ticker", default=None, help="Filter by ticker substring")
    parser.add_argument(
        "--by",
        default="asset,hour,side",
        help="Winrate breakdown dimensions, comma-separated: asset,hour,side,entry_price,day",
    )
    parser.add_argument(
        "--output",
        default="json",
        choices=["json", "table", "summary"],
        help="Output format (default: json)",
    )

    args = parser.parse_args()

    result = dispatch(args)

    # Output formatting
    if args.output == "summary" and isinstance(result, dict) and "summary" in result:
        # Print summary block only
        print(json.dumps(result.get("summary", result), indent=2, default=str))
    elif args.output == "table" and isinstance(result, list) and result:
        # Simple TSV table
        keys = list(result[0].keys())
        print("\t".join(keys))
        for row in result:
            print("\t".join(str(row.get(k, "")) for k in keys))
    else:
        print(json.dumps(result, indent=2, default=str))
