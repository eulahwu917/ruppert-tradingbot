# Trader Review: Crypto 15m Cap Redesign
**Spec reviewed:** `agents/ruppert/strategist/specs/crypto-15m-cap-redesign-spec-2026-03-30.md`
**Date:** 2026-03-30
**Author:** Ruppert (Trader)
**Status:** REVIEW COMPLETE — issues found, see Q5 especially (critical)

---

## Q1: Is the check ordering correct?

- **Order (CB → Tier 2 → Tier 1), all inside `threading.Lock`: correct.**
- CB fires first (most severe), daily backstop second, per-window cap third — logical precedence.
- Advisory mode fallthrough is correct: warning logged, `_skip_reason` not set, Tier 2 + Tier 1 still run.
- One edge case: in non-advisory CB block, `win_key` is never assigned, but that's fine — capacity never reserved so no release needed. No bug.
- **No structural ordering issue.**

---

## Q2: Can `_rehydrate_state()` reconstruct circuit breaker state from settlements log?

- **CB state is NOT reconstructed from the settlements log.** It's read from the state FILE (`agents/ruppert/state/crypto_15m_circuit_breaker.json`), written by `settlement_checker.py`. Rehydration just reads that file.
- If state file is missing/corrupt on startup, `_cb_consecutive_losses` defaults to 0 — CB resets silently. No warning or fallback to log reconstruction.
- **Fields in the settlements log** that could theoretically reconstruct CB state: the spec only shows `{'payout': float, 'ticker': str}` per settlement record. **`window_open_ts` is NOT confirmed as a settlements log field.** Without `window_open_ts` in the settlements log, you cannot group by window to identify "complete loss windows." You'd need to join against the trade log.
- Bottom line: if state file is lost, CB state is NOT reconstructable from settlements alone with the current schema.

---

## Q3: Does `settlement_checker.py` have access to write the circuit breaker state file?

- State path is a **relative path**: `agents/ruppert/state/crypto_15m_circuit_breaker.json`. Settlement checker uses `os.makedirs(..., exist_ok=True)` so directory creation is safe.
- **Structural risk:** if `settlement_checker.py` runs from a different working directory than `crypto_15m.py` reads from, the file is written to one location and read from another. No absolute path or shared constant anchors both sides.
- **Import dependency:** `_update_circuit_breaker_state()` references `config.CRYPTO_15M_CIRCUIT_BREAKER_N` — confirm `settlement_checker.py` already imports `config`. If not, that import must be added.
- Atomic write (`.tmp` + `os.replace()`) is correctly specced. No concurrency issue on the file itself.

---

## Q4: Does the Strategist's in-memory lock design match the Trader's race condition spec?

- **Structure matches:** CB + Tier 2 + Tier 1 + atomic reservation all inside one `with _window_lock:`. Release on order failure uses a second `with _window_lock:`. Consistent with Trader's spec.
- **Gap — missing `global` declarations:** The Trader's spec explicitly shows `global _daily_wager, _daily_wager_date` inside `evaluate_crypto_15m_entry()`. The Strategist's Section 3c code block **omits** `global` declarations for `_cb_consecutive_losses`, `_window_exposure`, `_daily_wager`, and `_daily_wager_date`. Dev following Strategist's code verbatim will get a Python `UnboundLocalError` on assignment inside the function.
- Dev must follow Trader's companion spec for the actual code — Strategist correctly defers to it, but the conceptual code in Section 3c is incomplete in this regard.

---

## Q5: Critical gotcha — circuit breaker never fires during live operation

- **The in-memory `_cb_consecutive_losses` is only loaded at startup.** `settlement_checker.py` updates the state FILE after each settled window, but there is NO mechanism to push that update into `crypto_15m.py`'s in-memory variable during a live session.
- Result: if 3 consecutive complete-loss windows occur mid-session, the file is updated correctly, but `_cb_consecutive_losses` in memory stays at whatever value it was on startup. **The circuit breaker never actually fires during a running session — only as a startup gate on the next restart.**
- **Fix required:** `evaluate_crypto_15m_entry()` must re-read the CB state file on each call (or per-window), OR `settlement_checker.py` must call a function/signal in `crypto_15m.py` to update the in-memory counter. The state file approach is simpler: read `_read_circuit_breaker_state()` once per window key change (i.e., when `window_open_ts` changes) inside the lock, before the CB check. Low I/O cost since it's once per 15-minute window.

---

*End of review.*
