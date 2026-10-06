#!/usr/bin/env python3
"""gen-map.py —— 从 origin/main 提交对象导出本轮的「路由 × 权限码」与「菜单项」坐标。

口径（沿用 2026-10-02 harness/gen-route-guard-map.py 的「坐标从提交导出」纪律）：
  · 一律 `git show origin/main:<path>` / `git ls-tree`，**禁读工作树**（工作树可能落后/在别的分支）；
  · 输出 out/map.json：{ commit, prefixes:[{prefix,code}], routes:[...], menu:[{key,name,path,permissionCode,adminOnly}] }
"""
import json, os, re, subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DASH = 'frontend/admin-web/src/app/(dashboard)'
OUT = os.path.join(os.path.dirname(__file__), '..', 'out', 'map.json')


def git(*args):
    return subprocess.check_output(['git', '-C', REPO, *args], text=True)


commit = git('rev-parse', 'origin/main').strip()

layout = git('show', f'{commit}:{DASH}/layout.tsx')
body = re.search(r'ROUTE_PERMISSION_MAP[^=]*=\s*\[(.*?)\n\]', layout, re.S).group(1)
prefixes = [{'prefix': p, 'code': c} for p, c in
            re.findall(r"\{\s*prefix:\s*'([^']+)',\s*code:\s*'([^']+)'\s*\}", body)]

routes = []
for path in git('ls-tree', '-r', '--name-only', commit, '--', DASH).splitlines():
    if not path.endswith('page.tsx'):
        continue
    inner = path[len(DASH):].rstrip('/')
    inner = re.sub(r'/page\.tsx$', '', inner)
    inner = inner.replace('page.tsx', '')
    segs = [s for s in inner.split('/') if s and not re.fullmatch(r'\(.*\)', s)]
    route = '/' + '/'.join(re.sub(r'^\[(.*)\]$', r':\1', s) for s in segs)
    routes.append('/' if route == '/' else route.rstrip('/'))

menu_src = git('show', f'{commit}:frontend/admin-web/src/config/menu.ts')
# 只取带 path 的叶节点对象字面量
menu = []
for m in re.finditer(r"\{([^{}]*?path:\s*'([^']+)'[^{}]*?)\}", menu_src, re.S):
    blob, path = m.group(1), m.group(2)
    def field(name):
        mm = re.search(rf"{name}:\s*'([^']*)'", blob)
        return mm.group(1) if mm else None
    menu.append({
        'path': path,
        'key': field('key'),
        'name': field('name'),
        'permissionCode': field('permissionCode'),
        'adminOnly': 'adminOnly: true' in blob,
        'briefingToggle': 'briefingToggle: true' in blob,
    })

data = {'commit': commit, 'prefixes': prefixes, 'routes': sorted(set(routes)), 'menu': menu}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"commit={commit[:9]} routes={len(data['routes'])} prefixes={len(prefixes)} menu={len(menu)}")
print('--- prefixes ---')
for p in prefixes:
    print(f"  {p['prefix']:<28} {p['code']}")
print('--- menu ---')
for m in menu:
    print(f"  {m['path']:<34} {m['name'] or '(无名)':<12} code={m['permissionCode']} adminOnly={m['adminOnly']}")
