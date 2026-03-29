# SA-3 Developer — P&L % Fix Session 2
_Date: 2026-03-12_
_Session label: developer-pnl-pct2_

---

## Task
Fix two dashboard bugs in the P&L section:
1. N/A showing for bot and manual P&L %
2. "This Month" closed P&L showing $60.52 instead of $80.63

---

## Root Cause Analysis

### Bug 1 — N/A for bot/manual P&L % (`bot_cost_basis` / `man_cost_basis`)

**Root cause:** In `get_pnl_history()`, the variables `src`, `is_manual`, and cost basis accumulation were placed **after** the `if ticker in exit_records: ... else: ... (API call with `continue`)` block. Any API-path ticker that triggered a `continue` (non-200 response or market not yet priced) would bypass the cost basis accumulation entirely.

Additionally, the running server was on an older code version that didn't return `bot_cost_basis`/`man_cost_basis` keys at all — confirmed by calling the live `/api/pnl` endpoint and seeing those keys absent.

**Fix:** Moved `src`, `is_manual`, and cost basis accumulation to **before** the if/else block — now they always execute for every ticker in `settled_tickers`, regardless of API success or failure. Removed the now-duplicate `src`/`is_manual` re-computation that followed the if/else block.

### Bug 2 — Month bucket 20.11 short ($60.52 vs $80.63)

**Root cause:** `settlement_date_from_ticker()` used regex `r'^(\d{2})([A-Z]{3})(\d{2})$'` which requires exactly 7 chars (YYMONDD). Tickers with a **date+hour** suffix like `KXETH-26MAR1117-B2030` (9 chars: `26MAR1117` = day=11, hour=17) didn't match and returned `None`. This meant those tickers' P&L was added to `closed_pnl_total` and `closed_by_source['bot']` (unconditional), but `if sdate:` was False — so they were **excluded from `closed_by_period['month']`** and `closed_by_src_period['bot']['month']`.

The two affected tickers (`KXETH-26MAR1117-B2030` and `KXETH-26MAR1117-B2070`) contributed exactly the 20.11 gap.

**Fix:** Updated regex to `r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$'` with optional hour group, and switched from `m.groups()` (4-tuple) to `m.group(1/2/3)` to safely ignore the hour. After fix: `settlement_date_from_ticker('KXETH-26MAR1117-B2030')` → `date(2026, 3, 11)`.

---

## Files Changed

| File | Change |
|------|--------|
| `dashboard/api.py` | `settlement_date_from_ticker` regex fix + cost basis moved before API call |

**No changes to `dashboard/templates/index.html`** — `setSplitPnl()` logic is correct. N/A only showed because `pnl.bot_cost_basis` was `undefined` (key absent from API). Once server restarts with fixed code, it will show correct values (~$297.82 bot, ~$74.18 manual).

---

## Commit

```
1e80343  fix: P&L % N/A and month bucket gap (api.py)
```

---

## Post-Deploy Verification

After CEO restarts the dashboard server, the `/api/pnl` endpoint should return:
- `bot_cost_basis: ~297.82`
- `man_cost_basis: ~74.18`
- `closed_pnl_month` ≈ `closed_pnl` ≈ `80.63` (no gap)
- Bot P&L % card shows e.g. `+29.3%` instead of `N/A`
- Manual P&L % card shows e.g. `-9.0%` instead of `N/A`

---

## Known Remaining Issue

Server is running old code. **CEO must restart the dashboard process** for these fixes to take effect. Server does NOT appear to be running `uvicorn --reload`.

---

## Bugs Outside Scope (Reported Only)

None identified beyond the two assigned.
