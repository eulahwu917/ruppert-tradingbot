import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Remove width:100% from title th
c = c.replace(
    '<th class="l" style="width:100%">Position</th>',
    '<th class="l">Position</th>'
)
c = c.replace(
    '<th class="l" style="width:100%">Trade</th>',
    '<th class="l">Trade</th>'
)
print("th width removed: OK")

# 2. Remove max-width:0 from title td, let it be natural width
c = c.replace(
    '<td class="l col-title" style="max-width:0;">',
    '<td class="l col-title">'
)
print("td max-width removed: OK")

# 3. Make <a> NOT grow (flex: 0 0 auto) — takes only content width, no empty space after
c = c.replace(
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1;">${name}</a>',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto;max-width:420px;">${name}</a>'
)
c = c.replace(
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1;">${q}</a>',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto;max-width:420px;">${q}</a>'
)
print("a flex: OK")

# 4. Add min-width to signal column so it doesn't get too cramped
c = c.replace(
    '<th class="ra shrink">Signal</th>',
    '<th class="ra shrink" style="min-width:80px">Signal</th>'
)
c = c.replace(
    '<th class="ra shrink">Edge</th>',
    '<th class="ra shrink" style="min-width:45px">Edge</th>'
)
print("signal min-width: OK")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
