from pathlib import Path
code = Path('dashboard/templates/index.html').read_text(encoding='utf-8', errors='ignore')
idx = code.find('async function loadCrypto')
print(repr(code[idx:idx+600]))
