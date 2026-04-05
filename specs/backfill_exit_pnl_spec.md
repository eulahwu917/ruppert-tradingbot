# Spec: `scripts/backfill_exit_pnl.py` — One-Time PnL Backfill

**Author:** Ruppert DS  
**Date:** 2026-04-04  
**Status:** Awaiting adversarial review  
**Commit context:** Fixes records written on April 4 before commit 748cc1d

---

## Problem

Exit/settle records written on April 4, 2026 are missing the `pnl` field (it is `None` or absent entirely). This is because `build_trade_entry()` was not writing `pnl` before the fix landed in commit 748cc1d. The dashboard reads `cr.get('pnl')` with no fallback, so these records show no PnL.

All records written before April 4 already have `pnl` correctly populated. This script is a **one-time backfill** — it should be safe to re-run but will only touch records where `pnl` is missing.

---

## Target Files

**Directory:** `environments/demo/logs/trades/`  
**Pattern:** `trades_*.jsonl`  
**Format:** JSON Lines — one complete JSON object per line, newline-delimited.

At time of writing the files are:
- `trades_2026-04-02.jsonl` (~701 KB)
- `trades_2026-04-03.jsonl` (~484 KB)
- `trades_2026-04-04.jsonl` (~177 KB)

The script scans all files matching the glob. It will only modify records that need it.

---

## PnL Formula

```
pnl = (exit_price - entry_price) * contracts / 100
```

- Result is rounded to **2 decimal places**
- `exit_price` is always the price of the held side (YES or NO) — no side-conditional logic needed
- Unit: dollars (prices are in cents, dividing by 100 converts to dollars)

---

## Processing Rules

### Which records to update
Apply the backfill to a record **if and only if ALL of these are true**:

1. `action` is `"exit"` or `"settle"`
2. `pnl` is `None` OR the key `"pnl"` is absent from the record
3. `entry_price` is present and not `None`
4. `exit_price` is present and not `None`
5. `contracts` is present and not `None`

### Skip conditions (do NOT modify the record if any of these)
- `action` is not `"exit"` or `"settle"` — skip, preserve as-is
- `pnl` is already set (non-None) — skip, no overwrite
- Any of `entry_price`, `exit_price`, or `contracts` is `None` or missing — skip, no partial calculation

### Field preservation
When writing a record back, **all fields must be preserved exactly as they were**. Only `pnl` is added or updated. Do not reorder keys, strip fields, or change types.

---

## Safe File Update Protocol

To avoid data loss if the script crashes mid-write:

1. Process all lines of a file in memory first
2. Write the updated lines to a **`.tmp` file** in the same directory  
   e.g., `trades_2026-04-04.jsonl.tmp`
3. Only after the `.tmp` file is fully written and closed, **rename** (atomic replace) the `.tmp` over the original  
   e.g., `os.replace('trades_2026-04-04.jsonl.tmp', 'trades_2026-04-04.jsonl')`
4. If any error occurs before the rename, the original file is untouched — the `.tmp` can be deleted safely on cleanup

Never write directly to the original file. Never truncate-and-rewrite in place.

---

## JSONL Handling

- Read the file line by line
- Strip each line of leading/trailing whitespace before parsing
- Skip **blank lines** silently (do not try to parse them, do not count them)
- Parse each non-blank line with `json.loads()`
- If a line **fails to parse** (malformed JSON):
  - Print a warning: `WARN: Could not parse line {line_number} in {filename}: {error}`
  - Write the **original raw line** unchanged to the output
  - Count it as "skipped" in the summary (not updated, not errored out)
  - **Do not abort the file** — continue processing remaining lines
- Write each line back as `json.dumps(record)` (compact, no extra whitespace) followed by `\n`

---

## Command-Line Interface

```
python scripts/backfill_exit_pnl.py [--dry-run]
```

### `--dry-run` mode
- Reads all files and computes what would change
- Prints each record that **would** be updated:
  ```
  [DRY-RUN] trades_2026-04-04.jsonl line 12: trade_id=fd71bb4e pnl would be set to 187.86
  ```
- Does **not** write any files, does not create any `.tmp` files
- Still prints the final summary at the end

### Normal mode
- Applies all changes, writes files atomically
- Prints the final summary

---

## Summary Output

Print at the end (both dry-run and normal modes):

```
=== Backfill Summary ===
Files scanned:    3
Files modified:   1
Records updated:  47
Records skipped:  1203
Parse errors:     0
```

- **Files scanned:** total `.jsonl` files found matching the glob
- **Files modified:** files where at least one record was updated (0 in dry-run mode)
- **Records updated:** records where `pnl` was computed and written
- **Records skipped:** all other records (wrong action, pnl already set, missing fields, blank lines, parse errors)
- **Parse errors:** count of lines that failed `json.loads()`

---

## Error Handling Summary

| Situation | Behavior |
|---|---|
| Directory doesn't exist | Print error, exit with code 1 |
| No matching files found | Print warning, exit cleanly (0 records updated) |
| Line fails to parse | Warn, write raw line unchanged, count as skipped |
| Record missing `pnl` but also missing required fields | Skip silently (counted as skipped) |
| Write failure mid-file | Exception propagates; `.tmp` file left behind; original untouched |
| Rename failure after write | Exception propagates; original still untouched |

---

## Assumptions & Out-of-Scope

- This is a **one-time** script. It does not need to be idempotent beyond the skip-if-already-set logic.
- No database or external system is involved — files only.
- No need to handle concurrent writers — assume the trading system is not writing to these files while the script runs (run it while the system is idle or after market hours).
- The script does not need to handle files outside the `environments/demo/logs/trades/` directory.
- No logging to file required — stdout only.

---

## Example Record — Before and After

**Before (April 4 exit record, pnl missing):**
```json
{"trade_id": "fd71bb4e-7db1-46b7-85bc-e9933b7254fa", "timestamp": "2026-04-04T17:58:23.702718", "date": "2026-04-04", "ticker": "KXBTC-26APR0421-B67150", "side": "yes", "action": "exit", "entry_price": 33.0, "contracts": 303, "exit_price": 95}
```

**After:**
```json
{"trade_id": "fd71bb4e-7db1-46b7-85bc-e9933b7254fa", "timestamp": "2026-04-04T17:58:23.702718", "date": "2026-04-04", "ticker": "KXBTC-26APR0421-B67150", "side": "yes", "action": "exit", "entry_price": 33.0, "contracts": 303, "exit_price": 95, "pnl": 187.86}
```

Calculation: `(95 - 33.0) * 303 / 100 = 62 * 303 / 100 = 18786 / 100 = 187.86`

---

## Dev Notes

- Use `glob.glob()` or `pathlib.Path.glob()` to find files
- Use `os.replace()` for atomic rename (works cross-platform including Windows)
- Use `round(value, 2)` for rounding — do not use string formatting as a substitute
- Python 3.8+ assumed (f-strings, `os.replace`, standard json module — no extra dependencies needed)
- Script should exit with code 0 on success, code 1 on fatal startup error
