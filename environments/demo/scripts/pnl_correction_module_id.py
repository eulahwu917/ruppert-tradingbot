"""
Migration script: fix module='crypto' → correct per-asset module ID
for 26 trade records in trades_2026-04-01.jsonl and trades_2026-04-02.jsonl.

Usage:
    python -m environments.demo.scripts.pnl_correction_module_id          # dry-run
    python -m environments.demo.scripts.pnl_correction_module_id --apply  # write changes
"""
import json
import os
import re
import sys
import tempfile

TRADES_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs', 'trades')

TARGET_FILES = [
    'trades_2026-04-01.jsonl',
    'trades_2026-04-02.jsonl',
]

# Ticker pattern → correct module
_TICKER_MODULE_PATTERNS = [
    (re.compile(r'^KXBTC-.*-B'),   'crypto_band_daily_btc'),
    (re.compile(r'^KXETH-.*-B'),   'crypto_band_daily_eth'),
    (re.compile(r'^KXXRP-.*-B'),   'crypto_band_daily_xrp'),
    (re.compile(r'^KXDOGE-.*-B'),  'crypto_band_daily_doge'),
    (re.compile(r'^KXSOL-.*-B'),   'crypto_band_daily_sol'),
    (re.compile(r'^KXBTCD-.*-T'),  'crypto_threshold_daily_btc'),
    (re.compile(r'^KXETHD-.*-T'),  'crypto_threshold_daily_eth'),
    (re.compile(r'^KXSOLD-.*-T'),  'crypto_threshold_daily_sol'),
    (re.compile(r'^KXXRPD'),       'crypto_threshold_daily_xrp'),
    (re.compile(r'^KXDOGED'),      'crypto_threshold_daily_doge'),
]


def derive_module(ticker: str) -> str | None:
    """Return correct module for a band/threshold daily ticker, or None if no match."""
    for pattern, module in _TICKER_MODULE_PATTERNS:
        if pattern.match(ticker):
            return module
    return None


def process_file(filepath: str, apply: bool) -> int:
    """Process one JSONL file. Returns count of corrected records."""
    if not os.path.exists(filepath):
        print(f"  SKIP (not found): {filepath}")
        return 0

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    corrected = 0
    new_lines = []
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            new_lines.append(line)
            continue
        try:
            record = json.loads(line_stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        if record.get('module') != 'crypto':
            new_lines.append(line)
            continue

        ticker = record.get('ticker', '')
        correct_module = derive_module(ticker)
        if correct_module is None:
            new_lines.append(line)
            continue

        print(f"  {'APPLY' if apply else 'DRY-RUN'}: line {i+1} | {ticker} | "
              f"module='crypto' -> '{correct_module}'")
        record['module'] = correct_module
        new_lines.append(json.dumps(record) + '\n')
        corrected += 1

    if apply and corrected > 0:
        # Atomic write: tmp file then rename
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(filepath), suffix='.jsonl')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp_f:
                tmp_f.writelines(new_lines)
            os.replace(tmp_path, filepath)
            print(f"  WRITTEN: {filepath} ({corrected} records corrected)")
        except Exception:
            os.unlink(tmp_path)
            raise

    return corrected


def main():
    apply = '--apply' in sys.argv
    mode = 'APPLY' if apply else 'DRY-RUN'
    print(f"=== Module ID Migration ({mode}) ===\n")

    total = 0
    for fname in TARGET_FILES:
        fpath = os.path.normpath(os.path.join(TRADES_DIR, fname))
        print(f"Processing: {fpath}")
        total += process_file(fpath, apply)
        print()

    print(f"Total records {'corrected' if apply else 'to correct'}: {total}")
    if not apply and total > 0:
        print("\nRe-run with --apply to write changes.")


if __name__ == '__main__':
    main()

    # ── CB state refresh ──────────────────────────────────────────────────────
    if '--apply' in sys.argv:
        try:
            from pathlib import Path as _Path
            sys.path.insert(0, str(_Path(__file__).parent.parent.parent.parent))
            import agents.ruppert.trader.circuit_breaker as _cb
            from agents.ruppert.data_scientist.capital import get_capital as _get_capital
            _cb.update_global_state(_get_capital())
            print('[CB] Global state refreshed after module ID migration.')
        except Exception as _cb_refresh_err:
            print(f'[CB] State refresh failed (non-fatal): {_cb_refresh_err}')
    # ── End CB state refresh ──────────────────────────────────────────────────
