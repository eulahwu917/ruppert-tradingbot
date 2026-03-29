# -*- coding: utf-8 -*-
# report.py — Ruppert Backtest Framework
# Generates plain-text and JSON reports from backtest results.

import json
import os
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def _pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def _dollar(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}${val:.2f}"


def generate_report(results: dict, config: dict, output_path: str = None) -> str:
    """
    Write a plain-text (.txt) and JSON (.json) report.

    Args:
        results:     output from run_backtest()
        config:      strategy config dict used for this run
        output_path: optional base path (without extension); if None, auto-generates
                     a timestamped path in results/

    Returns:
        str: path to the .txt report file
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(RESULTS_DIR / f"{ts}_report")

    txt_path  = output_path + ".txt"
    json_path = output_path + ".json"

    trades         = results.get("trades", [])
    total_pnl      = results.get("total_pnl", 0.0)
    win_rate       = results.get("win_rate", 0.0)
    total_trades   = results.get("total_trades", 0)
    daily_pnl      = results.get("daily_pnl", {})
    by_module      = results.get("by_module", {})
    city_pnl       = results.get("city_pnl", {})
    capital_curve  = results.get("capital_curve", [])
    start_capital  = results.get("starting_capital", 400.0)
    end_capital    = results.get("ending_capital", start_capital)
    start_date     = results.get("start_date", "")
    end_date       = results.get("end_date", "")

    roi = (end_capital - start_capital) / start_capital if start_capital > 0 else 0.0

    lines = []
    sep   = "=" * 60

    # ---- Header ----
    lines.append(sep)
    lines.append("  RUPPERT BACKTEST REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Period:    {start_date} -> {end_date}")
    lines.append(sep)
    lines.append("")

    # ---- Summary ----
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Starting capital : ${start_capital:.2f}")
    lines.append(f"  Ending capital   : ${end_capital:.2f}")
    lines.append(f"  Total P&L        : {_dollar(total_pnl)}")
    lines.append(f"  ROI              : {_pct(roi)}")
    lines.append(f"  Total trades     : {total_trades}")
    lines.append(f"  Win rate         : {_pct(win_rate)}")
    lines.append("")

    # ---- By Module ----
    lines.append("P&L BY MODULE")
    lines.append("-" * 40)
    for mod_name, mod in by_module.items():
        n  = mod.get("trades", 0)
        wr = mod.get("win_rate", 0.0)
        pnl = mod.get("pnl", 0.0)
        lines.append(f"  {mod_name.upper():<10}  trades={n:>4}  win={_pct(wr):<8}  pnl={_dollar(pnl)}")
    lines.append("")

    # ---- By City (weather) ----
    if city_pnl:
        lines.append("P&L BY CITY (weather)")
        lines.append("-" * 40)
        sorted_cities = sorted(city_pnl.items(), key=lambda x: x[1], reverse=True)
        for city, pnl in sorted_cities:
            lines.append(f"  {city:<6}  {_dollar(pnl)}")
        lines.append("")

    # ---- Capital Curve ----
    lines.append("CAPITAL CURVE")
    lines.append("-" * 40)
    for date_str, cap in capital_curve:
        day_p = daily_pnl.get(date_str, 0.0)
        bar_len = max(0, int((cap - start_capital * 0.8) / (start_capital * 0.4) * 20))
        bar = "█" * min(bar_len, 30)
        lines.append(f"  {date_str}  ${cap:>7.2f}  {_dollar(day_p):<10}  {bar}")
    lines.append("")

    # ---- Top 5 Winning Trades ----
    sorted_trades = sorted(trades, key=lambda t: t.get("pnl", 0.0), reverse=True)
    lines.append("TOP 5 WINNING TRADES")
    lines.append("-" * 40)
    for t in sorted_trades[:5]:
        lines.append(
            f"  {t.get('ticker','?'):<30}  {t.get('module','?'):<7}  "
            f"{t.get('side','?'):<3}  entry={t.get('entry_price_cents',0):.0f}¢  "
            f"size=${t.get('size_dollars',0):.2f}  pnl={_dollar(t.get('pnl',0))}"
        )
    if not sorted_trades:
        lines.append("  (no trades)")
    lines.append("")

    # ---- Top 5 Losing Trades ----
    lines.append("TOP 5 LOSING TRADES")
    lines.append("-" * 40)
    for t in sorted_trades[-5:][::-1]:
        if t.get("pnl", 0) >= 0:
            break
        lines.append(
            f"  {t.get('ticker','?'):<30}  {t.get('module','?'):<7}  "
            f"{t.get('side','?'):<3}  entry={t.get('entry_price_cents',0):.0f}¢  "
            f"size=${t.get('size_dollars',0):.2f}  pnl={_dollar(t.get('pnl',0))}"
        )
    if not sorted_trades or sorted_trades[-1].get("pnl", 0) >= 0:
        lines.append("  (no losing trades)")
    lines.append("")

    # ---- Config Used ----
    lines.append("CONFIG")
    lines.append("-" * 40)
    for k, v in config.items():
        lines.append(f"  {k:<30} = {v}")
    lines.append("")
    lines.append(sep)

    report_text = "\n".join(lines)

    # Write text report
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    # Write JSON report (full results + config)
    json_payload = {
        "generated": datetime.now().isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "summary": {
            "starting_capital": start_capital,
            "ending_capital": end_capital,
            "total_pnl": total_pnl,
            "roi": round(roi, 4),
            "total_trades": total_trades,
            "win_rate": win_rate,
        },
        "by_module": by_module,
        "city_pnl": city_pnl,
        "daily_pnl": daily_pnl,
        "capital_curve": capital_curve,
        "top_wins": sorted_trades[:5],
        "top_losses": [t for t in sorted_trades[-5:][::-1] if t.get("pnl", 0) < 0],
        "config": config,
        "all_trades": trades,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2, default=str)

    return txt_path


def generate_accuracy_report(results: dict, config: dict, output_path: str = None) -> str:
    """
    Write a plain-text accuracy report (and JSON) from run_accuracy_backtest() output.

    Args:
        results:     output from run_accuracy_backtest()
        config:      config dict used for the run
        output_path: optional base path (without extension); auto-timestamped if None

    Returns:
        str: path to the .txt report file
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(RESULTS_DIR / f"{ts}_accuracy_report")

    txt_path  = output_path + ".txt"
    json_path = output_path + ".json"

    total_markets   = results.get('total_markets_evaluated', 0)
    total_triggered = results.get('total_triggered', 0)
    total_correct   = results.get('total_correct', 0)
    trigger_rate    = results.get('trigger_rate', 0.0)
    win_rate        = results.get('win_rate', 0.0)
    by_series       = results.get('by_series', {})
    start_date      = results.get('start_date', '')
    end_date        = results.get('end_date', '')

    lines = []
    sep   = "=" * 50

    lines.append(sep)
    lines.append("  RUPPERT BACKTEST -- ACCURACY REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)
    lines.append("")
    lines.append(f"Period:    {start_date} to {end_date}")
    lines.append(f"Markets evaluated: {total_markets}")
    lines.append(f"Triggered: {total_triggered} ({trigger_rate:.1%})")
    lines.append(f"Correct:   {total_correct} ({win_rate:.1%} win rate)")
    lines.append("")

    if by_series:
        lines.append("By city:")
        sorted_series = sorted(
            by_series.items(),
            key=lambda x: x[1]['triggered'],
            reverse=True,
        )
        for series, stats in sorted_series:
            t = stats['triggered']
            c = stats['correct']
            pct = c / t if t else 0.0
            lines.append(f"  {series:<14}  {t} triggered, {c} correct ({pct:.1%})")
        lines.append("")

    lines.append("Config used:")
    lines.append(f"  min_edge_weather:       {config.get('min_edge_weather', 'N/A')}")
    lines.append(f"  min_confidence_weather: {config.get('min_confidence_weather', 'N/A')}")
    lines.append(f"  same_day_skip_hour:     {config.get('same_day_skip_hour', 'N/A')}")
    lines.append("")
    lines.append(sep)

    report_text = "\n".join(lines)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated": datetime.now().isoformat(),
                "start_date": start_date,
                "end_date": end_date,
                "summary": {
                    "total_markets_evaluated": total_markets,
                    "total_triggered": total_triggered,
                    "total_correct": total_correct,
                    "trigger_rate": trigger_rate,
                    "win_rate": win_rate,
                },
                "by_series": by_series,
                "config": config,
                "all_results": results.get('all_results', []),
            },
            f,
            indent=2,
            default=str,
        )

    return txt_path


def print_sweep_summary(sweep_results: list, top_n: int = 10) -> None:
    """
    Print a summary table of parameter sweep results.

    Args:
        sweep_results: list of (config, results) tuples sorted by total_pnl desc
        top_n:         how many configs to show
    """
    sep = "=" * 80
    print(sep)
    print("  PARAMETER SWEEP SUMMARY")
    print(sep)
    print(f"  {'Rank':<5} {'Total P&L':>10} {'Win Rate':>9} {'Trades':>7}  Config highlights")
    print("-" * 80)
    for i, (cfg, res) in enumerate(sweep_results[:top_n], 1):
        pnl    = res.get("total_pnl", 0.0)
        wr     = res.get("win_rate", 0.0)
        n      = res.get("total_trades", 0)
        highlights = (
            f"edge_w={cfg.get('min_edge_weather')} "
            f"edge_c={cfg.get('min_edge_crypto')} "
            f"conf_w={cfg.get('min_confidence_weather')} "
            f"skip_h={cfg.get('same_day_skip_hour')}"
        )
        print(f"  {i:<5} {_dollar(pnl):>10} {_pct(wr):>9} {n:>7}  {highlights}")
    print(sep)
