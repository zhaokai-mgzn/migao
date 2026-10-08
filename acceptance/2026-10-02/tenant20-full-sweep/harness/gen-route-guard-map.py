#!/usr/bin/env python3
# gen-route-guard-map.py — 从 origin/main 提交对象导出 s8 需要的前端路由守卫坐标（同 gen-permission-surface.py 的「坐标从提交导出」口径）
# 输出 out/route-guard-map-main.json: { commit, prefixes:[{prefix,code}], routes:['orders/:id', ...] }
# - prefixes：解析 frontend/admin-web/src/app/(dashboard)/layout.tsx 的 ROUTE_PERMISSION_MAP
# - routes：枚举 (dashboard) 下全部 page.tsx（含动态段 [id]→:id，剔除 (xxx) 路由组段）
# 2026-10-03 修复：此前 prefixes/routes 实际读的是**工作区文件**（主检出常驻 feat 分支 ⇒ 坐标
# 被 feat 分支的旧 layout 污染，曾丢 #5976/#5977 的 /inbound-orders、/agent-workspace 前缀），
# 却挂着 origin/main 的 commit 号。现改为 git show / git ls-tree 从提交对象读，口径名实一致。
import json, os, re, subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
DASH = 'frontend/admin-web/src/app/(dashboard)'

def git(*args):
    return subprocess.check_output(['git', '-C', REPO, *args], text=True)

commit = git('rev-parse', 'origin/main').strip()

# prefixes：从提交对象的 layout.tsx 解析 ROUTE_PERMISSION_MAP
layout = git('show', f'{commit}:{DASH}/layout.tsx')
body = re.search(r'ROUTE_PERMISSION_MAP[^=]*=\s*\[(.*?)\n\]', layout, re.S).group(1)
prefixes = [{'prefix': p, 'code': c} for p, c in
            re.findall(r"\{\s*prefix:\s*'([^']+)',\s*code:\s*'([^']+)'\s*\}", body)]

# routes：从提交对象枚举 (dashboard) 下全部 page.tsx
routes = []
for path in git('ls-tree', '-r', '--name-only', commit, '--', DASH).splitlines():
    if not path.endswith('page.tsx'):
        continue
    inner = path[len(DASH):].rstrip('/')
    parts = [re.sub(r'^\[.+\]$', ':id', p) for p in inner.split('/')
             if p and not re.match(r'^\(.*\)$', p)]
    routes.append('/'.join(parts))

# 2026-10-03 固化（验收 §六 #1/#8）：① 直写 sweep 根的 out/（与 s7/s8 消费路径同源），消除
# 「gen 写 harness/out、消费者读 sweep/out」双目录陷阱（曾靠人工 cp 兜底，静默读旧坐标 ⇒ 全矩阵假绿）；
# ② 产物加 format 契约字段 + commit（已有），消费侧 fail-fast 校验。
out = os.path.join(os.path.dirname(__file__), '..', 'out')
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'route-guard-map-main.json'), 'w', encoding='utf-8').write(
    json.dumps({'format': 'ls-tree-fullpath-page-tsx', 'commit': commit, 'prefixes': prefixes, 'routes': routes}, ensure_ascii=False, indent=1))
print(f'坐标 origin/main@{commit[:9]} | prefixes {len(prefixes)} | routes {len(routes)}')
