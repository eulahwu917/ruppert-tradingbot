# SPEC: CRYPTO_15M_DAILY_CAP_PCT Missing + Alert Relabeling
**Date:** 2026-03-30
**Author:** Trader
**Source:** DS investigation → David decision → Trader formal spec
**Status:** Ready for Dev

---

## Problem Statement

Two related issues:

1. **Missing constant:** `data_agent.py::check_daily_cap_violations()` references `CRYPTO_15M_DAILY_CAP_PCT` via `getattr(cfg, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)`. This constant does not exist in `config.py`, so the `getattr` silently falls back to `0.04` (4%). The effective 15m daily cap is therefore **10× lower than intended**, causing routine 15m activity to trigger false cap violation alerts.

2. **Misleading alert label:** The alert fires as `"Daily Cap Violation"` — enforcement language. The 10% threshold is intended as a **canary / early activity flag**, not an actual enforcement cap. The label must be corrected so on-call review is calibrated appropriately. Strategist will tune the threshold after 30 trades.

---

## David's Decision

- Add `CRYPTO_15M_DAILY_CAP_PCT = 0.10` to `config.py` (10% of capital/day)
- Relabel the alert from `"Daily Cap Violation"` to `"Early Activity Flag"` for `crypto_15m` module alerts
- All other module violation alerts retain existing `"Daily Cap Violation"` label

---

## BEFORE

### `environments/demo/config.py` — constant missing

```python
# Daily cap per module — percentage of total capital (scaled dynamically)
WEATHER_DAILY_CAP_PCT = 0.07
CRYPTO_DAILY_CAP_PCT  = 0.07
GEO_DAILY_CAP_PCT     = 0.04
ECON_DAILY_CAP_PCT    = 0.04
FED_DAILY_CAP_PCT     = 0.03
# CRYPTO_15M_DAILY_CAP_PCT is NOT defined here
# LONG_HORIZON_DAILY_CAP_PCT = 0.10  (defined later, in a different section)
```

`data_agent.py` line 299:
```python
'crypto_15m': capital * getattr(cfg, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04),
#                                                                  ^^^^
#                                 silently falls back to 4% — wrong threshold
```

### `agents/ruppert/data_scientist/data_agent.py` — alert label

In `run_post_scan_audit()`, lines 1214–1229:
```python
cap_violations = check_daily_cap_violations(today_trades)
for v in cap_violations:
    flagged += 1
    issues.append({
        'type': 'daily_cap_violation',
        'module': v['module'],
        'total': v['total'],
        'cap': v['cap'],
        'action': 'flagged + ALERT',
    })
    ih = _issue_hash('daily_cap', f'{v["module"]}_{date.today().isoformat()}')
    if _should_alert(state, ih):
        send_telegram(_format_single_alert(
            'Daily Cap Violation',           # <-- enforcement label, wrong for crypto_15m
            '',
            f'{v["module"]}: ${v["total"]:.0f} vs ${v["cap"]:.0f} cap',
            'Flagged. Review position sizes.',
        ))
```

**Behavior:** crypto_15m fires `"Daily Cap Violation"` alerts at 4% of capital (~$400 at $10k), even though there is no enforcement action — it is only an observation canary.

---

## AFTER

### Change 1 — Add constant to `config.py`

**File:** `environments/demo/config.py`

In the `# Daily cap per module` section, add after `FED_DAILY_CAP_PCT`:

```python
# Daily cap per module — percentage of total capital (scaled dynamically)
WEATHER_DAILY_CAP_PCT    = 0.07   # 7% of capital/day
CRYPTO_DAILY_CAP_PCT     = 0.07   # 7% of capital/day
GEO_DAILY_CAP_PCT        = 0.04   # 4% of capital/day
ECON_DAILY_CAP_PCT       = 0.04   # 4% of capital/day
FED_DAILY_CAP_PCT        = 0.03   # 3% of capital/day (fed trades are rare/high-conviction)
CRYPTO_15M_DAILY_CAP_PCT = 0.10   # 10% of capital/day — canary threshold; not enforced
                                   # Strategist to tune after 30 trades
```

**Note:** `LONG_HORIZON_DAILY_CAP_PCT = 0.10` remains in its existing position (the `── Long-Horizon Crypto` section). This new constant is for `crypto_15m` only.

---

### Change 2 — Relabel alert in `data_agent.py`

**File:** `agents/ruppert/data_scientist/data_agent.py`

In `run_post_scan_audit()`, modify the `send_telegram` call for cap violations to use a module-aware label:

#### BEFORE:
```python
        ih = _issue_hash('daily_cap', f'{v["module"]}_{date.today().isoformat()}')
        if _should_alert(state, ih):
            send_telegram(_format_single_alert(
                'Daily Cap Violation',
                '',
                f'{v["module"]}: ${v["total"]:.0f} vs ${v["cap"]:.0f} cap',
                'Flagged. Review position sizes.',
            ))
            _mark_alerted(state, ih)
            state['cumulative_stats']['alerts_sent'] = state['cumulative_stats'].get('alerts_sent', 0) + 1
```

#### AFTER:
```python
        ih = _issue_hash('daily_cap', f'{v["module"]}_{date.today().isoformat()}')
        if _should_alert(state, ih):
            # crypto_15m threshold is a canary (early activity flag), not an enforcement cap.
            # Strategist will tune the 10% threshold after 30 trades.
            if v['module'] == 'crypto_15m':
                alert_label  = 'Early Activity Flag'
                alert_action = 'Canary threshold reached. No action required — Strategist tracking.'
            else:
                alert_label  = 'Daily Cap Violation'
                alert_action = 'Flagged. Review position sizes.'
            send_telegram(_format_single_alert(
                alert_label,
                '',
                f'{v["module"]}: ${v["total"]:.0f} vs ${v["cap"]:.0f} threshold',
                alert_action,
            ))
            _mark_alerted(state, ih)
            state['cumulative_stats']['alerts_sent'] = state['cumulative_stats'].get('alerts_sent', 0) + 1
```

---

## Scope

| File | Change |
|---|---|
| `environments/demo/config.py` | Add `CRYPTO_15M_DAILY_CAP_PCT = 0.10` in the daily cap section |
| `agents/ruppert/data_scientist/data_agent.py` | Relabel `crypto_15m` cap alert from `"Daily Cap Violation"` → `"Early Activity Flag"` with canary-appropriate action text |

---

## Invariants (must not change)

- `check_daily_cap_violations()` signature unchanged — returns `list[dict]`
- All other modules (`weather`, `crypto`, `econ`, `fed`, `geo`, `crypto_long`) continue to fire `"Daily Cap Violation"` alerts and use their existing thresholds
- The `getattr` fallback in `check_daily_cap_violations()` remains as a safety net; the constant being present means it will now resolve to `0.10` correctly
- `issue_type='daily_cap_violation'` in the audit report is unchanged (internal type key; only the Telegram display label changes)

---

## QA Checklist

- [ ] Confirm `CRYPTO_15M_DAILY_CAP_PCT` resolves to `0.10` when loaded via `importlib.util` in `check_daily_cap_violations()` — add `print(getattr(cfg, 'CRYPTO_15M_DAILY_CAP_PCT', 'MISSING'))` in a scratch test.
- [ ] Simulate a crypto_15m cap breach: confirm Telegram alert reads `"Early Activity Flag"` not `"Daily Cap Violation"`.
- [ ] Simulate a weather cap breach: confirm Telegram alert still reads `"Daily Cap Violation"`.
- [ ] Confirm no other modules are affected by the label change.
- [ ] Run `run_post_scan_audit(mode='full')` with today's trades — no regressions in issue reporting or alert dedup.

---

## Notes

- The fallback value `0.04` in the `getattr` call is a safety net for missing constants. Now that `CRYPTO_15M_DAILY_CAP_PCT` is defined, the fallback will never activate in normal operation. Dev may optionally change the fallback from `0.04` to `0.10` to match, but this is not required.
- Strategist owns threshold tuning after the 30-trade data collection milestone. No further changes needed until then.
- The `CRYPTO_15M_WINDOW_CAP_PCT` (per-window cap, currently `0.02`) and `CRYPTO_15M_DAILY_WAGER_CAP_PCT` (backstop, `0.40`) in `config.py` are separate controls and are **not** affected by this fix.
