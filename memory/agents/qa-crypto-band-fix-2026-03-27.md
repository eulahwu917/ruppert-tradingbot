# QA: Crypto Band Filter Fix — 2026-03-27

## Verdict: PASS

## Change Verified
`main.py:486` — band filter now reads:
```python
if abs(strike - spot) <= spot * 0.10:
```
Confirmed `spot * 0.10`, not `half_w * 4`.

## Logic Check
For BTC at $84,000:
- `spot * 0.10` = $8,400
- Allowed range: $75,600 to $92,400 (±10% of spot)
- Correct.

## Syntax Check
`ast.parse(main.py)` — **OK**

## Test Results
18/18 passed (0.06s), integration tests excluded as instructed.
