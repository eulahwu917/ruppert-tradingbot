# Dev Fix: security_audit.py — Anchor secrets path to __file__

**Date:** 2026-03-27
**Agent:** SA-3 Developer
**File:** `audit/security_audit.py`

## Problem

Line 131 used a bare relative path:
```python
secrets_dir = Path('../../secrets')
```
This breaks when the script is run from any directory other than the repo root.

## Fix Applied

Replaced with a `__file__`-anchored path:
```python
secrets_dir = Path(__file__).resolve().parent.parent / 'secrets'
```

`audit/security_audit.py` → `.parent` = `audit/` → `.parent.parent` = repo root → `/ 'secrets'` = correct absolute path to `secrets/` directory regardless of working directory.

## Status

✅ Applied — single line change only. No commit or push.
