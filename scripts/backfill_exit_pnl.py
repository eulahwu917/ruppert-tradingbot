#!/usr/bin/env python3
"""One-time backfill: populate missing pnl field on exit/settle trade records.

Formula: pnl = round((exit_price - entry_price) * contracts / 100, 2)
Applies to: action in ('exit', 'settle') where pnl is None/absent
Safe to re-run: skips records where pnl is already set (including pnl=0.0)
"""
import argparse
import json
import os
from pathlib import Path


def backfill_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Returns (updated, skipped)."""
    lines = path.read_text(encoding='utf-8').splitlines()
    updated = 0
    skipped = 0
    out_lines = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            out_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            print(f"  WARN: bad JSON line {i+1} in {path.name} — preserved as-is")
            out_lines.append(line)
            continue

        action = record.get('action', '')
        if action in ('exit', 'settle') and record.get('pnl') is None:
            ep = record.get('entry_price')
            xp = record.get('exit_price')
            ct = record.get('contracts')
            if ep is not None and xp is not None and ct is not None:
                pnl = round((float(xp) - float(ep)) * float(ct) / 100, 2)
                if dry_run:
                    print(f"  DRY-RUN: {record.get('ticker')} pnl would be set to {pnl}")
                else:
                    record['pnl'] = pnl
                updated += 1
            else:
                skipped += 1
        else:
            skipped += 1

        out_lines.append(json.dumps(record, separators=(',', ':')))

    if not dry_run and updated > 0:
        tmp = path.with_suffix('.jsonl.tmp')
        tmp.write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
        os.replace(tmp, path)

    return updated, skipped


def main():
    parser = argparse.ArgumentParser(description='Backfill missing pnl on exit/settle records')
    parser.add_argument('--dry-run', action='store_true', help='Print changes without writing')
    args = parser.parse_args()

    trades_dir = Path('environments/demo/logs/trades')
    files = sorted(trades_dir.glob('trades_*.jsonl'))

    total_updated = 0
    total_skipped = 0
    files_modified = 0

    print(f"Scanning {len(files)} trade files{' (DRY RUN)' if args.dry_run else ''}...")
    for f in files:
        updated, skipped = backfill_file(f, args.dry_run)
        if updated > 0:
            files_modified += 1
            print(f"  {f.name}: {updated} updated, {skipped} skipped")
        total_updated += updated
        total_skipped += skipped

    print(f"\nDone. Files scanned: {len(files)} | Files modified: {files_modified} | Records updated: {total_updated} | Records skipped: {total_skipped}")


if __name__ == '__main__':
    main()
