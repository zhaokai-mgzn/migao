# Transcript：V88 迁移独立验收（issue #4676 @ f511c0fa0）

环境：macOS · PostgreSQL 16.15 (Homebrew) · 临时实例 `127.0.0.1:55434` · 库 `v88c`（正确 V88）/ `v88red`（35 格注入）
全部命令由验收 agent 执行，**未改任何生产代码/迁移/测试**。

## R1 · 建验收工作区

```
$ git fetch origin main -q && git branch acceptance/v88-4676 origin/main
$ ./scripts/dev-worktree.sh add acceptance/v88-4676
❌ 目标路径已存在：/Users/guangzhen.zk/ai native/migao/../migao-wt/acceptance-v88-4676
$ git -C .../migao-wt/acceptance-v88-4676 log --oneline -1
82a6fbcfb docs(design): #4687 套号落库 + 二维码粒度 + 扫码报工闭环 (#4691)
$ git merge-base --is-ancestor f511c0fa0 HEAD && echo YES
YES        # 工作区 = f511c0fa0 + 1 条 docs 提交，干净；全部结论锚定 f511c0fa0
```

## R2 · V88 静态核（红线 + 五条 DML）

```
$ grep -v "^\s*--" V88__….sql | grep -c "processing_orders\|processing_position_operations\|production_work_logs"
0                     # 三张快照表零命中（红线成立）
$ grep -c "production_operation_positions" V88__….sql
10                    # 注释自称「= 2」⇒ 注释被自己的回滚示例块撑大（P2-1）
$ grep -c "NULL::numeric" V79__….sql
0                     # V79 两处 VALUES 块均无类型显式化（P0-2 / #4685 根因）
```

## R3 · 真库：V79 → V88 ×2（正确版）

```
### V79（副本仅把 NULL → NULL::numeric，未改 V88 一字节）
OK
t1 grid=36          t2 grid=36
t1 主线=["配料", "打包"]     t2 主线=["配料", "打包"]
t1 配料工序行=1      t2 配料工序行=1
### V88 #1   OK    md5#1=0ed74b92f513697d0f31e235bdec097c
### V88 #2   OK    md5#2=0ed74b92f513697d0f31e235bdec097c
✅ 幂等（指纹含 updated_at::text ⇒ 第二次未重写）
### 终态
t1 退场=31 存活=5         t2 退场=31 存活=5
t1 配料工序行存活=0       t2 配料工序行存活=0
t1 主线=["裁剪", "打包"]   t2 主线=["裁剪", "打包"]
t1 裁剪x布料 applicable=true    t2 裁剪x布料 applicable=true
t1 打包存活=4 scope=set    t2 打包存活=4 scope=set
t1 存活格=打包×布帘,打包×布料,打包×帘头,打包×纱帘,裁剪×布料
t2 存活格=打包×布帘,打包×布料,打包×帘头,打包×纱帘,裁剪×布料
```

## R4 · V79 原样失败（复现 #4685）

```
$ psql -v ON_ERROR_STOP=1 -f V79__….sql        # 未打补丁
psql:…/V79__seed_fabric_route_and_packing_operation.sql:180: ERROR:
  column "unit_price" is of type numeric but expression is of type text
第4行       t.id, v.logical_name, v.position, v.unit_price, v.app…
提示:  You will need to rewrite or cast the expression.
```

## R5 · 真库：35 格注入（红证 A3）

```
$ sed "s/NOT IN ('裁剪', '打包')/NOT IN ('裁剪')/" V88__….sql > v88-wrong35.sql
### 35 格版终态
tenant 1 退场=32 存活=4      tenant 2 退场=32 存活=4
布料主线 = ["裁剪", "打包"]
--- 模拟 buildRoute ---
1. 裁剪 × 布料 → applicable=TRUE  ✅ 实例化
2. 打包 × 布料 → 无格 ⇒ applicable=null ❌ 静默 continue
👉 布料单实际实例化工序数 = 1
### 正确 31 格版
tenant 1 退场=31 存活=5      tenant 2 退场=31 存活=5
1. 裁剪 × 布料 → applicable=TRUE  ✅ 实例化
2. 打包 × 布料 → applicable=TRUE  ✅ 实例化
👉 布料单实际实例化工序数 = 2
```

## R6 · 读面（对 v88c 真库状态，忠实模拟 variantNameOf 裸名兜底）

```
===== 分区（按 scope）=====
operations | 裁剪×布料 scope=null
delivery   | 打包×布帘 scope=set
delivery   | 打包×布料 scope=set
delivery   | 打包×帘头 scope=set
delivery   | 打包×纱帘 scope=set
===== 打包 一列价 =====
打包 delivery 格数=4 / 该工序总格数=4
打包 (cells=4, applicable=4) → unpriced price=null
===== 不回落工序库行价 =====
打包×布帘 格价=NULL | 工序库行价=0.00 (NOT NULL DEFAULT 0)
打包×布料 格价=NULL | 工序库行价=0.00 (NOT NULL DEFAULT 0)
打包×帘头 格价=NULL | 工序库行价=0.00 (NOT NULL DEFAULT 0)
打包×纱帘 格价=NULL | 工序库行价=0.00 (NOT NULL DEFAULT 0)
裁剪×布料 格价=NULL | 工序库行价=无行 (NOT NULL DEFAULT 0)
```

> 注：第一版模拟 SQL 我漏把 `打包` 纳入变体名 CASE，得到「打包×布料 落 operations」的**假发现**；
> 核对 `variantNameOf` 的裸名兜底（`catalogByName.containsKey(logicalName) ? logicalName : null`）
> 后修正模拟，真结论是 **4/4 格全落 delivery**。此处保留该过程以明示「模拟脚本自身也会骗人」。

## R7 · 守卫注入（6 例，注入前后清 `__pycache__` + sha256 自证）

```
基线（未注入）：24 passed
注入 ⑤ 丢掉 '打包'   133f2a83ad3bac07 → 991a46d2475e469e  ✅生效 ⇒ 5 failed
注入 ④ 改 AND FALSE  133f2a83ad3bac07 → 868f96c0e0cc58b4  ✅生效 ⇒ 4 failed
注入 ③ 配料→配料     133f2a83ad3bac07 → eb92157c734814e5  ✅生效 ⇒ 1 failed
注入 软删丢守卫      133f2a83ad3bac07 → 2a700af16fd86d06  ✅生效 ⇒ 3 failed
注入 tenant_id=1     133f2a83ad3bac07 → 6396a19428c8902a  ✅生效 ⇒ 1 failed
注入 写快照表        133f2a83ad3bac07 → f44356094a71f201  ✅生效 ⇒ 7 failed
```

读面注入（`deliveryView` 内回落工序库行价）：
```
基线（最小副本）2 failed（缺文件 artifact）/ 17 passed
注入 1a9ed9da6bdb9853 → d82b8e017487af8b  ✅生效
⇒ test_delivery_price_rule_reads_only_matrix_cells FAILED
```

## R8 · 全量确定性测试 + Java

```
$ python3 -m pytest tests/unit_ci_workflows/ -q
2292 passed, 4 skipped, 24 warnings in 183.84s (0:03:03)

$ ./mvnw -o -Dtest=ProductionOperationLayersTest test
[INFO] Tests run: 7, Failures: 0, Errors: 0, Skipped: 0 -- in ProductionOperationLayersTest
[INFO] BUILD SUCCESS
```

## R9 · CI 门禁（步骤级 + 产物级，非 skipped）

```
$ gh pr checks 4684
Drift Audit (真相源契约)   fail   19s   run 35481151134
（其余 19 项 pass；PR #4684 仍于 2026-09-20T01:24:40Z MERGED）

$ gh run view 35481151134 --json status,conclusion,jobs
completed / failure
Drift Audit (真相源契约) → failure steps=13        # 步骤级真跑，非 skipped

$ gh run view 35481151134 --log-failed | grep 裸行号
❌ 新增漂移（本 PR 改动面）：tests/unit_ci_workflows/test_public_ops_v88_migration.py
   第 27 行 `ProcessingOrderService.java:1242` 无 `@<sha>` 限定
⇒ DRIFT；❌ [burn-down] 未达标：净消减 0 < 每 PR 最低 1

$ gh pr checks 4688
（20 项全 pass，含 Drift Audit pass）

$ python3 scripts/drift_audit.py          # 本地 @f511c0fa0
本次相对基线的增减：新增漂移 0（面内，阻塞）… ⇒ OK
EXIT=0
```

## R10 · 交付物可达性（`GET /operation-layers`）

```
$ grep -rn "operation-layers" frontend/admin-web/src
（零命中）
$ grep -c "operation-positions" frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx
9
$ grep -n "交付\|两层\|delivery\|打包发货" …/routings/page.tsx
（零命中）
$ gh issue view 4677 --json state -q .state
OPEN          # 「工艺项界面改造（两层布局 + … + 交付环节一列价）」依赖 #4676
```

## R11 · 真值源 / bootstrap 口径分裂

```
$ grep -n "FABRIC_MAINLINE_STEPS: List" backend/ai-agent-service/app/production/routing.py
465:FABRIC_MAINLINE_STEPS: List[str] = ["配料", "打包"]
$ grep -n '"裁剪", "布料"' backend/ai-agent-service/app/production/routing.py
638:    ("裁剪", "布料", None, False)
$ grep -n "配料\|布料工序路线" docs/sql/schema.sql
2190:  ('opp-v79-29', 1, '配料', '布料', NULL, TRUE, 'active'),
2209:  ('rt-v79-01', 1, '布料工序路线', FALSE,
2211:   '["配料", "打包"]'::jsonb,
$ sed -n '96p' backend/ai-agent-service/tests/test_production/test_fabric_route.py
    assert FABRIC_MAINLINE_STEPS == ["配料", "打包"], (
$ grep -rn "build_route_v2" backend/ai-agent-service/app/
（生产代码零消费方；routing.py:448 自述「今天是零消费者（P2 才切）」）
```
