#!/usr/bin/env python3
"""验收租户清理（tenant 22 / 23）—— 按 FK 依赖图拓扑排序，单事务执行，跑完自证。

用法：
    python3 harness/cleanup-tenants.py            # dry-run：只打印计划与行数
    python3 harness/cleanup-tenants.py --execute  # 真删（单事务；任一 FK 冲突则整体回滚）

安全口径：
  · 只删 tenants.id ∈ {22, 23} 的行（本次验收自建的租户；22 是首轮脚本中断留下的孤儿）；
  · 依赖顺序由 information_schema 的 FK 图**算出来**，不靠人工记忆；
  · 单事务 ⇒ 失败即回滚，不留半成品；
  · 跑完复核：这些表里这两租户的行数必须为 0，且 tenants 行消失。
"""
import os, subprocess, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TENANTS = (22, 23)
EXECUTE = '--execute' in sys.argv

def env():
    pw = subprocess.run(
        "grep '^RDS_PASSWORD=' backend/admin-api/.env | cut -d= -f2-",
        shell=True, capture_output=True, text=True,
        cwd=os.path.join(ROOT, '..', '..', '..')).stdout.strip()
    e = dict(os.environ); e['PGPASSWORD'] = pw
    return e

E = env()
PG = ['psql', '-h', 'pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com', '-p', '5432',
      '-U', 'migao_admin', '-d', 'ai_customer_service', '-t', '-A', '-v', 'ON_ERROR_STOP=1']

def q(sql, write=False):
    r = subprocess.run(PG + ['-c', sql], capture_output=True, text=True, env=E)
    if r.returncode != 0:
        raise SystemExit(f'SQL 失败：{sql[:120]}\n{r.stderr.strip()[:400]}')
    return r.stdout.strip()

# ── 1. 带 tenant_id 的表 + 表间 FK 图 ──
tables = [t for t in q("select table_name from information_schema.columns "
                       "where column_name='tenant_id' and table_schema='public'").split('\n') if t]
fks = []
for line in q("""
  select tc.table_name || '|' || ccu.table_name
  from information_schema.table_constraints tc
  join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name
  where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public'
  group by 1""").split('\n'):
    if '|' in line:
        a, b = line.split('|')
        if a in tables and b in tables and a != b:
            fks.append((a, b))                     # a 引用 b ⇒ 先删 a

# ── 2. 拓扑排序（Kahn）：被引用者排后面 ──
import collections
indeg = collections.Counter()   # 每个表「还欠多少子表」
adj = collections.defaultdict(list)
for a, b in fks:
    adj[a].append(b); indeg[b] += 1
order, ready = [], [t for t in tables if indeg[t] == 0]
while ready:
    t = ready.pop(0); order.append(t)
    for b in adj[t]:
        indeg[b] -= 1
        if indeg[b] == 0:
            ready.append(b)
leftover = [t for t in tables if t not in order]
if leftover:
    print(f'⚠️ 存在环，剩余 {len(leftover)} 张按字母序兜底：{leftover}')

# ── 3. 计划与行数 ──
plan = []
for t in order + leftover:
    n = int(q(f"select count(*) from {t} where tenant_id in {TENANTS}") or 0)
    if n:
        plan.append((t, n))
total = sum(n for _, n in plan)
print(f'计划删除：{len(plan)} 张表 / {total} 行（租户 {TENANTS}）')
for t, n in plan:
    print(f'  {t:44s} {n:4d}')
if not EXECUTE:
    print('\n（dry-run；加 --execute 才真删）')
    raise SystemExit(0)

# ── 4. 单事务执行 ──
stmts = [f"delete from {t} where tenant_id in {TENANTS};" for t, _ in plan]
stmts.append(f"delete from tenants where id in {TENANTS};")
sql = 'begin;\n' + '\n'.join(stmts) + '\ncommit;'
q(sql, write=True)
print('\n✅ 事务已提交')

# ── 5. 自证 ──
left = [(t, int(q(f"select count(*) from {t} where tenant_id in {TENANTS}") or 0)) for t, _ in plan]
bad = [x for x in left if x[1]]
print('复核租户行数全为 0：', '✅' if not bad else f'❌ {bad}')
print(' tenants 残留：', q(f"select count(*) from tenants where id in {TENANTS}"))
print(' 剩余租户：', q("select id||':'||name from tenants order by id").replace('\n', ' ｜ '))
