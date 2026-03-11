content = open('patch_crypto_tab.py', encoding='utf-8').read()
# Fix all invalid Python escape sequences in template literal strings
import re
# Replace \$ with $ (dollar sign doesn't need escaping in Python strings)
fixed = content.replace('\\$', '$')
open('patch_crypto_tab.py', 'w', encoding='utf-8').write(fixed)
print('Fixed dollar escapes:', content.count('\\$'))
