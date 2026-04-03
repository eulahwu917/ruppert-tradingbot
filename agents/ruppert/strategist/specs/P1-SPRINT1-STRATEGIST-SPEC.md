# P1 Sprint 1 — Strategist Specs
_Written: 2026-04-03 | Author: Strategist_
_Revised: 2026-04-03 | Revision: 1 (see summary below)_

---

## Revision Summary (v1 → v2)

**Trigger:** Adversarial pre-build review (CEO, 2026-04-03) found ISSUE-116 spec incomplete.

**Problems found and fixed in this revision:**

1. **Missed call site:** Original spec claimed "the fix is fully contained in `_asset_in_title()`" and "no other changes needed." This is wrong. `get_smart_money_signal()` in the same file uses raw `keyword_lower not in title.lower()` with no word-boundary protection — a second independent instance of the same bug. The revised spec addresses this explicitly with a fix in scope.

2. **`_ALIASES_REQUIRING_WORD_BOUNDARY` at wrong scope:** Original spec defined this constant inside `_asset_in_title()`, meaning it's re-created on every call. The revised spec moves it to module level.

3. **stETH test case explanation was wrong:** The original spec stated `"will steth depeg from eth?"` returns `True` because it "contains standalone `\beth\b`" — implying the regex matched "eth" inside "steth". That is incorrect. `\beth\b` does NOT match "eth" inside "steth" (the preceding "t" is a word character). The result is `True` because the title also contains the word "eth" as a standalone token at the end ("from eth?"). The test case accidentally produced the right answer for the wrong reason. The revised spec corrects both the explanation and the test suite to avoid this ambiguity.

---

## ISSUE-116: Fix ETH Alias Word-Boundary Matching in Polymarket Client

### Problem

The `_ASSET_ALIASES` dict in `polymarket_client.py` maps `"ETH"` to `["eth"]`. The comment even flags this:

```python
"ETH":  ["eth"],        # "eth" is a substring of "ethereum" — filter works
```

The assumption is that `"eth"` appearing in `"ethereum"` is acceptable — it is. But the bug runs the other direction: **`"eth"` is also a substring of other tokens that have nothing to do with Ethereum**, including:

- **EtherFi** (`"etherfi"` → contains `"eth"`)
- **Ethena** (`"ethena"` → contains `"eth"`)
- **Lido stETH** (`"steth"` → contains `"eth"`)
- Any market with `"methodology"`, `"synthetic"`, `"ether"` (generic), etc.

When `_asset_in_title("ETH", title_lower)` is called, it checks `"eth" in title_lower`. This returns `True` for any market whose title contains those substrings, causing:

1. **False positive market matches** — EtherFi, Ethena, and stETH markets get included in ETH signal computation.
2. **Corrupted yes_price** — Polymarket's crypto consensus for ETH may return the wrong market (e.g. an EtherFi staking yield market instead of an ETH price direction market), producing a meaningless or inverted signal.
3. **Silent failure** — No error is raised. The code behaves normally but `yes_price` is garbage.

### Root Cause

Simple substring check `alias in title_lower` with no word-boundary enforcement. This manifests in **two independent locations** in `polymarket_client.py`.

---

### Affected Code — All Instances

A full audit of `polymarket_client.py` identified two locations where asset name / keyword matching against market titles is performed:

#### Instance 1: `_asset_in_title()` — PRIMARY BUG (ACTIVE)

```python
def _asset_in_title(asset: str, title_lower: str) -> bool:
    """Return True if any known alias for asset appears in title_lower."""
    aliases = _ASSET_ALIASES.get(asset.upper(), [asset.lower()])
    return any(alias in title_lower for alias in aliases)
```

This function is called by:
- `_fetch_crypto_consensus()` — 15-minute signal pipeline
- `_fetch_crypto_daily_consensus()` — daily signal pipeline (used by `crypto_band_daily.py` and `crypto_threshold_daily.py`)

**This is the primary active bug.** Both callers are in the live signal path. **Requires fix in this sprint.**

#### Instance 2: `get_smart_money_signal()` — LATENT BUG (CURRENTLY UNUSED)

```python
def get_smart_money_signal(wallet_addresses: list[str], keyword: str) -> dict:
    ...
    keyword_lower = keyword.lower()
    ...
    for pos in positions:
        title = pos.get("title", "")
        if keyword_lower not in title.lower():
            continue
```

This is a raw substring match with no word-boundary protection. If called with `keyword="eth"`, it would match "steth", "etherfi", "ethena", etc. — the same class of false positives as Instance 1.

**Current status:** As of 2026-04-03, `get_smart_money_signal()` has zero callers anywhere in the active codebase. The live smart-money path uses `get_polymarket_smart_money()` in `crypto_client.py`, which calls `get_wallet_positions()` directly and does its own matching logic. `get_smart_money_signal()` is a public API that is currently dead code.

**Decision:** Fix this instance in the same PR. Rationale: we are already touching this file, the fix is trivial (one `re.search` call), and leaving an unfixed word-boundary bug in a public function invites the same false-positive bug the moment any caller is added. The cost of fixing now is near-zero; the cost of missing it when it becomes active is high.

---

### Fix Required (for Dev)

Two changes are required in `polymarket_client.py`.

#### Change 1: Add `re` import and module-level constant

At the top of `polymarket_client.py`, add:

```python
import re
```

Verify `re` is not already imported — it is not present in the current file.

Add this constant at **module level** (not inside any function), near the `_ASSET_ALIASES` dict:

```python
# Aliases that need word-boundary enforcement (short, collision-prone tickers)
_ALIASES_REQUIRING_WORD_BOUNDARY = {"eth", "sol", "xrp", "btc"}
```

This must be at module level so it is defined once, not re-created on every function call.

#### Change 2: Replace `_asset_in_title()` body (Instance 1)

Replace the body of `_asset_in_title` with:

```python
def _asset_in_title(asset: str, title_lower: str) -> bool:
    """Return True if any known alias for asset appears in title_lower.

    Short tickers (eth, sol, xrp, btc) use word-boundary regex matching to
    avoid false positives (e.g. "eth" matching "steth", "etherfi", "ethena").
    Longer aliases (bitcoin, ethereum, dogecoin, ripple, solana) use plain
    substring matching — they are unique enough to be unambiguous.
    """
    aliases = _ASSET_ALIASES.get(asset.upper(), [asset.lower()])
    for alias in aliases:
        if alias in _ALIASES_REQUIRING_WORD_BOUNDARY:
            # Word-boundary match: alias must not be surrounded by word characters
            if re.search(r'\b' + re.escape(alias) + r'\b', title_lower):
                return True
        else:
            # Longer aliases are safe for plain substring match
            if alias in title_lower:
                return True
    return False
```

#### Change 3: Replace raw substring match in `get_smart_money_signal()` (Instance 2)

Locate this block inside `get_smart_money_signal()`:

```python
for pos in positions:
    title = pos.get("title", "")
    if keyword_lower not in title.lower():
        continue
```

Replace with:

```python
for pos in positions:
    title = pos.get("title", "")
    title_lower_pos = title.lower()
    # Apply word-boundary matching for short keywords (e.g. "eth", "btc")
    # to avoid false positives against substrings like "steth", "etherfi".
    if len(keyword_lower) <= 4:
        if not re.search(r'\b' + re.escape(keyword_lower) + r'\b', title_lower_pos):
            continue
    else:
        if keyword_lower not in title_lower_pos:
            continue
```

**Rationale for `len <= 4` threshold:** This matches the `_ALIASES_REQUIRING_WORD_BOUNDARY` set exactly (eth=3, sol=3, xrp=3, btc=3 — all ≤ 4 chars). Longer keywords like "bitcoin" (7), "ethereum" (8), "solana" (6) pass through plain matching. The threshold is intentionally conservative: any keyword ≤ 4 chars gets boundary protection regardless of whether it's in `_ALIASES_REQUIRING_WORD_BOUNDARY`, because short keywords are always collision-prone.

---

### Test Cases for QA

After the fix, QA should verify both instances.

#### Instance 1: `_asset_in_title()` tests

| Title | Asset | Expected result | Reason |
|---|---|---|---|
| `"will etherfi tvl exceed $10b?"` | ETH | `False` | "eth" in "etherfi" — word-boundary blocks it |
| `"will ethena usd depeg?"` | ETH | `False` | "eth" in "ethena" — word-boundary blocks it |
| `"will steth lose its peg?"` | ETH | `False` | "eth" in "steth" — word-boundary blocks it; NO standalone "eth" in title |
| `"will steth depeg from eth?"` | ETH | `True` | Matches standalone " eth" at end of title, NOT "eth" inside "steth" |
| `"will eth price be above $2000?"` | ETH | `True` | "eth" is a standalone word |
| `"will ethereum price be above $2000?"` | ETH | `True` | "ethereum" alias, plain match, no word-boundary needed |
| `"will btc dominance exceed 60%?"` | BTC | `True` | "btc" is standalone |
| `"will bitcoin be above $100k?"` | BTC | `True` | "bitcoin" alias, plain match |
| `"will xrp price double?"` | XRP | `True` | "xrp" is standalone |
| `"will solana price surge?"` | SOL | `True` | "solana" alias, plain match |

**Critical stETH disambiguation:**

The title `"will steth lose its peg?"` must return `False`.

- `re.search(r'\beth\b', "will steth lose its peg?")` — in "steth", the "eth" is preceded by "t" (a word character), so `\b` before "eth" does NOT fire. No standalone "eth" appears elsewhere in the title. Result: no match → `False`. ✓

The title `"will steth depeg from eth?"` must return `True`.

- `re.search(r'\beth\b', "will steth depeg from eth?")` — in "steth", same as above, no match. But at " eth?" at the end, "eth" is preceded by space (non-word char) and followed by "?" (non-word char), so `\beth\b` matches. Result: match → `True`. ✓

QA must run both stETH titles to confirm word-boundary is working correctly, not just accidentally producing the right output.

#### Instance 2: `get_smart_money_signal()` tests

These require mock wallet position data. QA should construct test wallets with known positions:

| keyword | Position title | Expected: position matched? | Reason |
|---|---|---|---|
| `"eth"` | `"Will stETH lose its peg?"` | No | "eth" in "steth" — blocked by word-boundary |
| `"eth"` | `"Will EtherFi TVL exceed $10B?"` | No | "eth" in "etherfi" — blocked |
| `"eth"` | `"Will ETH price be above $2000?"` | Yes | Standalone "eth" |
| `"bitcoin"` | `"Will Bitcoin be above $100k?"` | Yes | Long keyword, plain match |
| `"sol"` | `"Will Solana price surge?"` | No | "sol" is ≤ 4 chars, "sol" in "solana" — word-boundary blocks it |
| `"sol"` | `"Will SOL/USD exceed $200?"` | Yes | Standalone "sol" |

---

### Notes

- The `"ethereum"` alias is unaffected — it's long enough to be unambiguous. No word-boundary needed.
- `"btc"`, `"sol"`, `"xrp"` are also short and collision-prone. They receive the same word-boundary treatment through `_ALIASES_REQUIRING_WORD_BOUNDARY`.
- `"doge"` (4 chars) and `"dogecoin"` are included in `_ALIASES_REQUIRING_WORD_BOUNDARY` via the `len <= 4` rule in `get_smart_money_signal()`. In `_asset_in_title()`, "doge" is not in `_ALIASES_REQUIRING_WORD_BOUNDARY` — Dev should consider adding it for consistency. It's low risk either way (no known tokens starting with "doge"), but consistent is better.
- `re` import: confirm not already present in `polymarket_client.py` before adding. As of the code reviewed 2026-04-03, it is absent.
- `_ALIASES_REQUIRING_WORD_BOUNDARY` at module level: important for performance. Do not define inside `_asset_in_title()`.

### Priority

**High.** The ETH daily signal feeds both `crypto_band_daily` and `crypto_threshold_daily`. If Polymarket ETH consensus is corrupted by false-positive EtherFi/Ethena/stETH market matches, it silently poisons the S5 signal and the shadow log data we're trying to collect. Fix before the shadow analysis data starts accumulating.

`get_smart_money_signal()` fix is low-urgency (dead code) but included in the same PR since the file is already being modified.

---
