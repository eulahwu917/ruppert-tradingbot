# QA Report — Polymarket Wallet Auto-Refresh
_SA-4 QA | 2026-03-12 | Reviewing commit: 6b91777_

---

## Status: PASS WITH WARNINGS

---

✅ **Checks passed:**
- `fetch_top_crypto_wallets()`: API URL is correct (`https://data-api.polymarket.com/v1/leaderboard`), params `category=CRYPTO`, `timePeriod=MONTH`, `orderBy=PNL`, `limit=50` all verified. Filters are `pnl <= 0.0 → skip` and `volume <= 1000.0 → skip`, correctly enforcing PnL > 0 AND volume > $1,000. Graceful error handling via `requests.RequestException` catch + generic `Exception` catch, both returning `[]`. Non-list response type checked and handled.
- `update_wallet_list()`: `if not wallets: return False` — file is left completely untouched when API returns nothing. JSON structure `{"wallets": [...], "updated_at": "<ISO>", "source": "polymarket_leaderboard"}` matches spec. `WALLETS_FILE.write_text(..., encoding="utf-8")` correct.
- `_load_wallets()` in `crypto_client.py`: fallback correctly filters `{k: v for k, v in TOP_TRADER_WALLETS.items() if not k.startswith('0xTODO')}` — all 5 placeholder entries (`0xTODO_wallet_placeholder_4` through `_8`) are excluded. JSON load uses `encoding='utf-8'` and wraps in try/except with fallback on parse failure.
- `wallet_source` field: present in `get_polymarket_smart_money()` result as `'dynamic' if _WALLETS_FILE.exists() else 'hardcoded_fallback'`. ✅
- Step 1b non-fatal: `try/except Exception` wraps the entire call; `print(f"  Wallet refresh error (non-fatal): {e}")` and cycle continues. ✅
- No API keys hardcoded anywhere. No `secrets/` directory accessed. All file opens verified `encoding='utf-8'` or `encoding="utf-8"`.

---

⚠️ **Warnings (discretionary):**

1. **`wallet_updater.py` line ~22 — Step 1b reaches 'smart' mode too.** The developer stated Step 1b runs "full mode only," but the code has no `if MODE == 'full':` guard — it runs for any mode that isn't `check` or `report` (both of which `sys.exit(0)` before Step 1b). The undocumented `smart` mode (listed in the module docstring) would also execute the wallet refresh. Low risk (wallet refresh is harmless and non-fatal), but behavior differs from spec. Recommend adding `if MODE == 'full':` guard or updating the docstring.

2. **`crypto_client.py` `get_polymarket_smart_money()` ~line 338 — `wallet_source` determined by file existence, not actual load path.** If `smart_money_wallets.json` exists but is corrupt/unparseable, `_load_wallets()` silently falls back to the hardcoded list while `wallet_source` reports `'dynamic'`. This is a minor observability gap — the field could be misleading in a corrupted-file scenario. Low impact since `_load_wallets()` logs the fallback at DEBUG level.

---

**One-paragraph verdict:** The wallet auto-refresh build is solid and production-ready with minor caveats. All critical requirements are met: the API URL and filter logic (`pnl > 0`, `volume > $1000`) are correctly implemented with graceful empty-result and HTTP-error handling; `update_wallet_list()` correctly preserves the existing file on failure; `_load_wallets()` properly excludes all `0xTODO` placeholders from the hardcoded fallback; `wallet_source` is present in the smart money result dict; Step 1b is non-fatal via try/except; and there are no hardcoded secrets, no `secrets/` access, and all file I/O uses `encoding='utf-8'`. Two warnings warrant attention before the next full deploy: (1) Step 1b lacks an explicit `MODE == 'full'` guard and will also fire in `smart` mode — harmless but inconsistent with the developer's stated design intent; and (2) the `wallet_source` field reflects file existence rather than actual load path, which could mislead debugging in a rare corrupt-file scenario. Neither is a blocking issue. **Recommend: PASS — CEO may approve with awareness of the two warnings.**
