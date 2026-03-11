"""
Comprehensive dashboard fix:
1. Remove duplicate Crypto tabs/panes/JS (keep exactly 1)
2. Fix swS() to include s-crypto
3. Fix duplicate _kalshiBalance assignments
4. Verify clean result
"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')

path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

print(f"Before: {len(content)} bytes")
print(f"  Crypto tabs: {content.count('swS(\'crypto\'')}")
print(f"  Crypto panes: {content.count('id=\"s-crypto\"')}")
print(f"  loadCrypto defs: {content.count('async function loadCrypto')}")

# ── 1. Remove duplicate Crypto tab BUTTONS (keep 1) ─────────────────────────
CRYPTO_BTN = "      <button class=\"tab\" onclick=\"swS('crypto',this)\">&#x20BF; Crypto</button>"
count = content.count(CRYPTO_BTN)
print(f"\nCrypto buttons found: {count}")
# Keep first, remove rest
if count > 1:
    first = content.find(CRYPTO_BTN)
    rest = content[first + len(CRYPTO_BTN):]
    rest = rest.replace(CRYPTO_BTN, '')
    content = content[:first + len(CRYPTO_BTN)] + rest
print(f"  After removal: {content.count(CRYPTO_BTN)}")

# ── 2. Remove duplicate Crypto PANES (keep first) ────────────────────────────
PANE_MARKER = '    <!-- Crypto -->'
count = content.count(PANE_MARKER)
print(f"\nCrypto pane markers found: {count}")
if count > 1:
    # Find all occurrences
    positions = [m.start() for m in re.finditer(re.escape(PANE_MARKER), content)]
    # For each duplicate (2nd+), find the end of that pane div and remove it
    # Process from back to front to preserve indices
    for start_pos in reversed(positions[1:]):
        # Find end of the <!-- Crypto --> pane div
        # It ends before the next \n\n  </div> (closing of scout card)
        # or before another pane marker
        end_search = content[start_pos:]
        # Find next pane or end of scout section
        next_pane = end_search.find('\n    <!-- ', 5)  # next HTML comment
        if next_pane > 0:
            remove_end = start_pos + next_pane
        else:
            # Find end of containing div
            next_section = end_search.find('\n\n  </div>', 5)
            remove_end = start_pos + next_section if next_section > 0 else start_pos + 3000
        print(f"  Removing pane at {start_pos}:{remove_end}")
        content = content[:start_pos] + content[remove_end:]

print(f"  After removal: {content.count(PANE_MARKER)}")

# ── 3. Remove duplicate loadCrypto JS functions (keep last = most complete) ──
FUNC_MARKER = '// ── Crypto Tab ────'
count = content.count(FUNC_MARKER)
print(f"\nloadCrypto JS blocks found: {count}")
if count > 1:
    positions = [m.start() for m in re.finditer(re.escape(FUNC_MARKER), content)]
    # Remove all but the last one
    for start_pos in reversed(positions[:-1]):
        next_func = content.find('\n// ──', start_pos + 10)
        if next_func < 0:
            next_func = content.find('\n</script>', start_pos)
        print(f"  Removing JS block at {start_pos}:{next_func}")
        content = content[:start_pos] + content[next_func:]

print(f"  After removal: {content.count(FUNC_MARKER)}")

# ── 4. Fix swS() — add s-crypto to pane list ─────────────────────────────────
old_sws = "  ['s-weather','s-bestbets','s-geo'].forEach(id=>$(id).classList.remove('on'));"
new_sws = "  ['s-weather','s-bestbets','s-geo','s-crypto'].forEach(id=>$(id).classList.remove('on'));"
if old_sws in content:
    content = content.replace(old_sws, new_sws)
    print("\nswS() fixed: added s-crypto")
else:
    print("\nWARNING: swS old pattern not found")

# ── 5. Fix duplicate _kalshiBalance assignments ───────────────────────────────
# Remove the stale old one (|| 0 version), keep the new (|| 400 version)
OLD_BAL_LINE = "  window._kalshiBalance = acct.kalshi_balance || 0;\n"
NEW_BAL_LINE = "  window._kalshiBalance = acct.kalshi_balance || 400;  // 400 = demo starting capital\n"
count_old = content.count(OLD_BAL_LINE)
count_new = content.count(NEW_BAL_LINE)
print(f"\n_kalshiBalance old (||0): {count_old}, new (||400): {count_new}")
if count_old > 0:
    content = content.replace(OLD_BAL_LINE, '')
    print("  Removed old _kalshiBalance assignment")

# ── 6. Final verification ──────────────────────────────────────────────────────
print(f"\nFinal state:")
ct = content.count("swS('crypto'")
print(f"  Crypto tabs: {ct}")
print(f"  Crypto panes: {content.count('id=\"s-crypto\"')}")
print(f"  loadCrypto defs: {content.count('async function loadCrypto')}")
print(f"  _kalshiBalance lines: {content.count('_kalshiBalance')}")
print(f"  swS has s-crypto: {'s-crypto' in content[:content.find('// ── Account')]}")
print(f"  File size: {len(content)}")

open(path, 'w', encoding='utf-8').write(content)
print("\nSaved successfully.")
