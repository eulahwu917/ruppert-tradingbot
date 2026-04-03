"""
migrate_module_taxonomy.py
Trade log backfill: rename module tags per taxonomy-migration-2026-03-30.md

IDEMPOTENT: safe to run multiple times. Uses new module names as guard —
records already updated will not be reprocessed.

Usage:
    python environments/demo/scripts/migrate_module_taxonomy.py
    python environments/demo/scripts/migrate_module_taxonomy.py --dry-run
"""
import argparse
import json
import shutil
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent  # → workspace/
TRADES_DIR = WORKSPACE_ROOT / 'environments' / 'demo' / 'logs' / 'trades'
BACKUP_DIR = WORKSPACE_ROOT / 'environments' / 'demo' / 'logs' / 'trades_backup_pre_taxonomy_migration'


def reclassify(record: dict) -> dict | None:
    """
    Returns updated record if module needs to change, else None (no-op).
    Idempotent: new module names are already correct — returns None if module
    already matches a new taxonomy value.
    """
    old_module = record.get('module', '')
    ticker = (record.get('ticker') or '').upper()

    # ── Already migrated ────────────────────────────────────────────────────
    FINAL_MODULES = {
        'weather_band', 'weather_threshold',
        'crypto_dir_15m_btc', 'crypto_dir_15m_eth', 'crypto_dir_15m_sol',
        'crypto_dir_15m_xrp', 'crypto_dir_15m_doge',
        'crypto_threshold_daily_btc', 'crypto_threshold_daily_eth',
        'crypto_band_daily_btc', 'crypto_band_daily_eth',
        'crypto_band_daily_sol', 'crypto_band_daily_xrp', 'crypto_band_daily_doge',
        'econ_cpi', 'econ_unemployment', 'econ_fed_rate', 'econ_recession',
        'geo', 'manual', 'other',
    }
    if old_module in FINAL_MODULES:
        return None  # already migrated, skip

    # ── weather → weather_band / weather_threshold ──────────────────────────
    if old_module == 'weather':
        if '-T' in ticker:
            new_module = 'weather_threshold'
        else:
            new_module = 'weather_band'  # -B type (default)
        updated = dict(record)
        updated['module'] = new_module
        return updated

    # ── crypto → crypto_band_daily_* (formerly crypto_1h_band) ─────────────
    if old_module in ('crypto', 'crypto_1h_band'):
        if 'ETH' in ticker:
            new_module = 'crypto_band_daily_eth'
        else:
            new_module = 'crypto_band_daily_btc'  # default
        updated = dict(record)
        updated['module'] = new_module
        return updated

    # ── crypto_15m / crypto_15m_dir → crypto_dir_15m_* ──────────────────────
    if old_module in ('crypto_15m', 'crypto_15m_dir'):
        if 'ETH' in ticker:
            new_module = 'crypto_dir_15m_eth'
        elif 'SOL' in ticker:
            new_module = 'crypto_dir_15m_sol'
        elif 'XRP' in ticker:
            new_module = 'crypto_dir_15m_xrp'
        elif 'DOGE' in ticker:
            new_module = 'crypto_dir_15m_doge'
        else:
            new_module = 'crypto_dir_15m_btc'  # default
        updated = dict(record)
        updated['module'] = new_module
        return updated

    # ── crypto_1d / crypto_1h_dir → crypto_threshold_daily_* ────────────────
    if old_module in ('crypto_1d', 'crypto_1h_dir'):
        if 'ETH' in ticker:
            new_module = 'crypto_threshold_daily_eth'
        else:
            new_module = 'crypto_threshold_daily_btc'  # default
        updated = dict(record)
        updated['module'] = new_module
        return updated

    # ── fed → econ_fed_rate ──────────────────────────────────────────────────
    if old_module == 'fed':
        updated = dict(record)
        updated['module'] = 'econ_fed_rate'
        return updated

    # ── econ → subcategory ───────────────────────────────────────────────────
    if old_module == 'econ':
        if ticker.startswith('KXCPI'):
            new_module = 'econ_cpi'
        elif any(ticker.startswith(p) for p in ('KXJOBLESSCLAIMS', 'KXECONSTATU3', 'KXUE')):
            new_module = 'econ_unemployment'
        elif ticker.startswith('KXWRECSS'):
            new_module = 'econ_recession'
        else:
            new_module = 'econ_cpi'  # fallback (same as classify_module default)
        updated = dict(record)
        updated['module'] = new_module
        return updated

    return None  # no mapping found — leave unchanged


def migrate_file(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Process a single trades_YYYY-MM-DD.jsonl file.
    Returns (total_records, records_changed).
    """
    lines = path.read_text(encoding='utf-8').splitlines()
    updated_lines = []
    changed = 0

    for line in lines:
        line = line.strip()
        if not line:
            updated_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            updated_lines.append(line)
            continue

        new_record = reclassify(record)
        if new_record is not None:
            changed += 1
            updated_lines.append(json.dumps(new_record))
        else:
            updated_lines.append(line)

    if not dry_run and changed > 0:
        path.write_text('\n'.join(updated_lines) + '\n', encoding='utf-8')

    return len(lines), changed


def main():
    parser = argparse.ArgumentParser(description='Migrate module taxonomy in trade logs')
    parser.add_argument('--dry-run', action='store_true', help='Print changes without writing')
    args = parser.parse_args()

    if not TRADES_DIR.exists():
        print(f'[ERROR] Trades directory not found: {TRADES_DIR}')
        return

    # ── Backup first (idempotent: skip if backup already exists) ───────────
    if not args.dry_run:
        if not BACKUP_DIR.exists():
            shutil.copytree(TRADES_DIR, BACKUP_DIR)
            print(f'[Backup] Created: {BACKUP_DIR}')
        else:
            print(f'[Backup] Already exists (idempotent run): {BACKUP_DIR}')

    total_records = 0
    total_changed = 0

    for trade_file in sorted(TRADES_DIR.glob('trades_*.jsonl')):
        records, changed = migrate_file(trade_file, dry_run=args.dry_run)
        total_records += records
        if changed:
            print(f'  {"[DRY]" if args.dry_run else "[UPDATED]"} {trade_file.name}: '
                  f'{changed}/{records} records changed')
        else:
            print(f'  [SKIP] {trade_file.name}: already up to date ({records} records)')
        total_changed += changed

    print(f'\n[Done] {total_changed} records updated across {total_records} total records.')
    if args.dry_run:
        print('[DRY RUN] No files were modified.')


if __name__ == '__main__':
    main()

    # ── CB state refresh ──────────────────────────────────────────────────────
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        import agents.ruppert.trader.circuit_breaker as _cb
        from agents.ruppert.data_scientist.capital import get_capital as _get_capital
        _cb.update_global_state(_get_capital())
        print('[CB] Global state refreshed after taxonomy migration.')
    except Exception as _cb_refresh_err:
        print(f'[CB] State refresh failed (non-fatal): {_cb_refresh_err}')
    # ── End CB state refresh ──────────────────────────────────────────────────
