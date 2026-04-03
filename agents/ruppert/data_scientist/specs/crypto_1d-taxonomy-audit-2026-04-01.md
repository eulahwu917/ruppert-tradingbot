# Spec: `crypto_1d` Taxonomy Audit

**Date:** 2026-04-01
**Author:** Data Scientist
**Status:** AUDIT ONLY — no code changes

---

## 1. Background

The `crypto_1d` module trades KXBTCD/KXETHD/KXSOLD (hourly above/below binaries on Kalshi). Despite the name "1d" (implying daily), these contracts settle **hourly**. A taxonomy migration was partially completed:

- **logger.py** `classify_module()` now returns `crypto_1h_dir` for these tickers
- **crypto_1d.py** now writes `module='crypto_1h_dir'` on trades
- **Dashboard** shows separate cards for `crypto_1h_dir` and `crypto_1h_band`
- **But** the filename, config keys, CLI mode, scheduler, and many comments still say `crypto_1d`

This audit catalogs every occurrence to assess inconsistency risk.

---

## 2. Occurrence Table — Production Code

| # | File | Line(s) | Usage | Current Value | Expected (New Taxonomy) | Risk |
|---|------|---------|-------|---------------|------------------------|------|
| 1 | `trader/crypto_1d.py` | L1037 | `source` field on trade log | `'crypto_1d'` | `'crypto_1d'` (keep — origin traceability) | None |
| 2 | `trader/crypto_1d.py` | L1038 | `module` field on trade log | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 3 | `trader/crypto_1d.py` | L818 | `module` on decision log | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 4 | `trader/crypto_1d.py` | L896, 900, 911 | `get_daily_exposure(module=...)` | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 5 | `trader/crypto_1d.py` | L718 | cross-module guard comparison | `!= 'crypto_1h_dir'` | `!= 'crypto_1h_dir'` | **DONE** |
| 6 | `trader/crypto_1d.py` | L709 | **Comment** still says `module != 'crypto_1d'` | stale comment | Should say `crypto_1h_dir` | Low (cosmetic) |
| 7 | `trader/crypto_1d.py` | L1044 | `note` field string | `f"crypto_1d {asset}..."` | Cosmetic — log readability only | None |
| 8 | `trader/main.py` | L749 | Function name `run_crypto_1d_scan` | `crypto_1d` in name | Rename would break callers | Low |
| 9 | `trader/main.py` | L798 | `get_daily_exposure(module='crypto_1h_dir')` | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 10 | `trader/main.py` | L829 | `module: 'crypto_1h_dir'` | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 11 | `data_scientist/logger.py` | L470 | Comment: `crypto_1h_dir KXBTCD (source=crypto_1d)` | Accurate | Accurate | None |
| 12 | `data_scientist/logger.py` | L494-498 | `classify_module()` returns `'crypto_1h_dir'` for KXBTCD | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 13 | `data_scientist/data_agent.py` | L75-76 | ticker→module map | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |
| 14 | `data_scientist/data_agent.py` | L328 | cap config key | `'CRYPTO_1H_DIR_DAILY_CAP_PCT'` | Correct | **DONE** |
| 15 | `strategist/strategy.py` | L46, 609 | MIN_EDGE key | `'crypto_1h_dir'` | `'crypto_1h_dir'` | **DONE** |

### Positions with **BUG RISK**:

| # | File | Line(s) | Usage | Current Value | Bug? |
|---|------|---------|-------|---------------|------|
| **B1** | `trader/position_tracker.py` | L400 | Time-decay stop-loss guard | `module in ('crypto', 'crypto_1d')` | **YES — ACTIVE BUG** |
| **B2** | `trader/position_monitor.py` | L340-341 | WS exit `source`/`module` | `'crypto'` / `'crypto'` | **YES — stale label** |
| **B3** | `data_analyst/ws_feed.py` | L413-414 | WS entry `source`/`module` | `'crypto'` / `'crypto'` | **YES — stale label** |
| **B4** | `environments/live/logger.py` | L35-38 | classify_module fallback | returns `'crypto'` | Stale — live env |

---

## 3. Bug Detail: B1 — position_tracker.py:400 (P0)

```python
if pos.get('module') in ('crypto', 'crypto_1d') and pos.get('added_at'):
```

**Problem:** Trades are now logged as `module='crypto_1h_dir'`. This guard checks for `'crypto'` or `'crypto_1d'` — **neither matches**. The time-decay stop-loss for daily crypto positions **will never fire** for any trade placed after the taxonomy migration.

**Impact:** Positions in KXBTCD/KXETHD that should be stopped out near settlement (the 20-min / 30-min decay rules) will hold through expiry instead, potentially settling at $0.

**Fix:** Change to `module in ('crypto_1h_dir', 'crypto_1h_band', 'crypto', 'crypto_1d')` or use `module.startswith('crypto')`.

---

## 4. Occurrence Table — Config & Infrastructure

| # | File | Line(s) | Usage | Current Value | Risk |
|---|------|---------|-------|---------------|------|
| C1 | `environments/demo/config.py` | L216 | Section comment | `crypto_1d: KXBTCD / KXETHD` | Cosmetic |
| C2 | `environments/demo/config.py` | L219 | `CRYPTO_1D_DAILY_CAP_PCT` | `0.15` | **Potential orphan** — code now uses `CRYPTO_1H_DIR_DAILY_CAP_PCT` via data_agent.py:328 |
| C3 | `environments/demo/config.py` | L135 | stop-trade cutoff | `'crypto_1h_dir': 2.0` | **DONE** |
| C4 | `environments/demo/config.py` | L142-143 | min-confidence | `'crypto_1h_band': 0.50, 'crypto_1h_dir': 0.50` | **DONE** |
| C5 | `environments/demo/ruppert_cycle.py` | L11 | CLI help docstring | `crypto_1d — daily crypto...` | Cosmetic |
| C6 | `environments/demo/ruppert_cycle.py` | L741-801 | `run_crypto_1d_mode()` function | Function named `crypto_1d` | Low — internal |
| C7 | `environments/demo/ruppert_cycle.py` | L1254-1255 | mode dispatch | `elif mode == 'crypto_1d':` | **Functional** — CLI `python ruppert_cycle.py crypto_1d` |
| C8 | `setup_crypto_1d_scheduler.ps1` | entire file | Task scheduler registration | `crypto_1d` throughout | Cosmetic (infra) |
| C9 | `Ruppert-Crypto1D.xml` | L7 | Task description | `crypto_1d scanner` | Cosmetic (infra) |

---

## 5. Occurrence Table — Dashboard

| # | File | Line(s) | Usage | Current Value | Notes |
|---|------|---------|-------|---------------|-------|
| D1 | `dashboard/templates/index.html` | L606-635 | HTML element IDs | `crypto_1d-open-pnl`, `crypto_1d-pnl`, etc. | Functional — JS references these |
| D2 | `dashboard/templates/index.html` | L704, 710 | JS MODULE_ID / modulePeriod | `crypto_1d: 'crypto_1d'` | Functional — drives data fetch |
| D3 | `dashboard/templates/index.html` | L1353, 1468 | forEach module list | includes `'crypto_1d'` | Functional |
| D4 | `dashboard/api.py` | L945, 1361 | module_keys | Does NOT include `'crypto_1d'` | **Mismatch** — frontend requests `crypto_1d` data, backend doesn't produce it |

**Dashboard note:** The frontend has `crypto_1d` as a separate card/tab, but `api.py` `_build_state()` only returns `crypto_1h_dir` data. The dashboard-layout-reshuffle spec (2026-04-01) proposes adding `modules_out['crypto_1d'] = modules_out['crypto_1h_dir']` as an alias — **this has not been implemented yet**, meaning the `crypto_1d` card likely shows `--` for all metrics.

---

## 6. Occurrence Table — Specs & Proposals (read-only, no code risk)

These are documentation/specs. Noted for completeness but zero runtime risk:

- `taxonomy-migration-2026-03-30.md` — 50+ occurrences (the migration plan itself)
- `taxonomy-redesign-2026-03-30.md` — 20+ occurrences (original redesign proposal)
- `crypto_1d_implementation_2026-03-30.md` — 30+ occurrences (implementation spec)
- `crypto_1d_architecture_2026-03-30.md` — 40+ occurrences (architecture proposal)
- `crypto_1d_x_sentiment_2026-03-30.md` — 10+ occurrences (sentiment signal proposal)
- `classify-module-crypto_1d-2026-03-30.md` — 15+ occurrences (classify_module fix spec)
- `dashboard-layout-reshuffle-2026-04-01.md` — 15+ occurrences
- `crypto-subcards-2026-04-01.md` — 5+ occurrences
- `crypto-card-4col-2026-04-01.md` — 3 occurrences

---

## 7. Summary of Label Usage by Layer

| Layer | Label Used | Notes |
|-------|-----------|-------|
| **Trade execution** (`crypto_1d.py`) | `source='crypto_1d'`, `module='crypto_1h_dir'` | Split: source=origin, module=taxonomy |
| **Logger classification** (`logger.py`) | Returns `'crypto_1h_dir'` for KXBTCD tickers | Correct |
| **Exposure queries** (`get_daily_exposure`) | `module='crypto_1h_dir'` | Correct |
| **Position tracker** stop-loss | Checks `'crypto'` or `'crypto_1d'` | **BROKEN** — misses `crypto_1h_dir` |
| **Config keys** | Mix of `CRYPTO_1D_*` and `CRYPTO_1H_DIR_*` | Orphaned old keys possible |
| **CLI / scheduler** | `crypto_1d` mode name | Functional, not a data bug |
| **Dashboard frontend** | `crypto_1d` as card key | Expects backend alias that doesn't exist |
| **Dashboard backend** | `crypto_1h_dir` only | No `crypto_1d` alias — card broken |
| **WS feeds** (`ws_feed.py`, `position_monitor.py`) | Still writes `module='crypto'` | Pre-migration, stale |

---

## 8. Recommendation

### What to standardize on

**Keep `crypto_1h_dir` as the canonical `module` value.** The migration is 80% done. Rolling back to `crypto_1d` would undo completed work in logger, data_agent, strategy, main.py, and crypto_1d.py itself.

**Keep `crypto_1d` as the `source` value** — it identifies the originating scanner file, which is useful for traceability.

**Keep `crypto_1d` as the CLI mode name** — renaming would break scheduled tasks, scripts, and user muscle memory. The mode name is an operational label, not a data field.

### Least disruptive path (4 changes)

| Priority | Fix | Files | Effort |
|----------|-----|-------|--------|
| **P0** | Fix position_tracker.py:400 stop-loss guard to include `crypto_1h_dir` | 1 file, 1 line | 2 min |
| **P1** | Add `crypto_1d` alias in `api.py _build_state()` so dashboard card works | 1 file, 1 line | 2 min |
| **P2** | Update `ws_feed.py` and `position_monitor.py` to write `module='crypto_1h_band'` instead of `module='crypto'` | 2 files, ~4 lines | 10 min |
| **P3** | Verify `CRYPTO_1D_DAILY_CAP_PCT` in config.py is still read anywhere; if not, add comment marking it deprecated | 1 file | 5 min |

### Do NOT rename (low value, high churn)

- `crypto_1d.py` filename — would break imports across 5+ files
- `run_crypto_1d_scan()` / `run_crypto_1d_mode()` — would break CLI dispatch, scheduler XML, and setup scripts
- Spec filenames — they are historical records
- The `source='crypto_1d'` field — this is correct (identifies the scanner)

---

## 9. Open Questions for David

1. **B1 (position_tracker stop-loss):** Should the fix be `module.startswith('crypto')` (catches all crypto modules) or explicit list `('crypto_1h_dir', 'crypto_1h_band', 'crypto', 'crypto_1d')` (defensive but brittle)?

2. **Dashboard:** The `crypto_1d` card in the frontend — should it remain as a separate card labeled "1D" (showing `crypto_1h_dir` data via alias), or should the frontend key be renamed to `crypto_1h_dir` to match the backend directly?

3. **Strategist recommendation (2026-04-01):** The strategist has recommended halting both `crypto_1h_dir` and `crypto_1h_band`. If these modules are being paused, should the taxonomy cleanup wait, or should we fix P0 (stop-loss bug) immediately regardless?
