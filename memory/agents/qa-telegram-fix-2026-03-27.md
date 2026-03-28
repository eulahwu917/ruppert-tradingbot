# QA: Telegram Notification Fix — 2026-03-27

## Results

| # | Check | Result |
|---|-------|--------|
| 1 | `send_telegram()` uses `subprocess.run` with `openclaw` CLI, no urllib/Bot API | **PASS** |
| 2 | `config.py` has no `TELEGRAM_CHAT_ID` block or empty-string fallback | **PASS** |
| 3 | openclaw command uses valid CLI pattern | **PASS** (after fix) |
| 4 | Smoke test — message delivered via Telegram | **PASS** (after fix) |
| 5 | Syntax check — `logger.py` and `config.py` parse cleanly | **PASS** |
| 6 | `pytest tests/ --ignore=tests/test_integration.py` — 20/20 passed | **PASS** |

## Bugs Found & Fixed During QA

### Bug 1: Invalid target alias `-t owner` (FIXED)
- **Original code:** `-t`, `'owner'`
- **Problem:** openclaw `-t/--target` expects a Telegram chat ID or @username, not `owner`. `owner` is not a recognized alias.
- **Fix:** Changed to `-t`, `'5003590611'` (David's Telegram chat ID).

### Bug 2: Missing `shell=True` on Windows (FIXED)
- **Original code:** `subprocess.run([...], capture_output=True, text=True, timeout=30)`
- **Problem:** On Windows, `openclaw` is installed as a `.cmd` wrapper via npm. `subprocess.run` with a list argument (no `shell=True`) cannot resolve `.cmd` files — raises `[WinError 2] The system cannot find the file specified`.
- **Fix:** Added `shell=True` to the `subprocess.run` call.

### Final send_telegram() (logger.py:292-309)
```python
def send_telegram(message: str) -> bool:
    """Send a message to David via the openclaw CLI (routes through gateway)."""
    import subprocess
    try:
        result = subprocess.run(
            ['openclaw', 'message', 'send',
             '--channel', 'telegram',
             '-t', '5003590611',
             '-m', message],
            capture_output=True, text=True, timeout=30,
            shell=True,
        )
        if result.returncode != 0:
            print(f"[WARN] send_telegram failed: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"[WARN] send_telegram failed: {e}")
        return False
```

## Verdict: PASS (all 6 checks green after 2 bug fixes)
