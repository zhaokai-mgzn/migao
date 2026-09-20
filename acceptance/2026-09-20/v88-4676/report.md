# 独立验收报告：V88 迁移 + `GET /operation-layers` + 开租播种同步（issue #4676）

- **验收日期**：2026-09-20
- **验收 agent**：独立验收 agent（**非**实施者；未参与 #4684/#4688 的任何编码）
- **被验收对象**：
  - issue **#4676**（CLOSED）· PR **#4684**（squash `6908122bb`）· PR **#4688**（跟随，squash `f511c0fa0`）
  - **main 现 head = `f511c0fa0`**（验收期间已推进到 `82a6fbcfb`，本报告全部结论锚定 `f511c0fa0`）
- **验收工作区**：`/Users/guangzhen.zk/ai native/migao-wt/acceptance-v88-4676`（分支 `acceptance/v88-4676`）
- **真库环境**：本机 PostgreSQL **16.15**（Homebrew），临时实例 `127.0.0.1:55434`，库 `v88c` / `v88red`
- **未改动任何生产代码 / 迁移 / 测试**：本报告与 artifact 是唯一产出

---

## 0. 结论（一句话）

**不可判「交付完成」** —— 数据层七条动作 + 读面 + 播种同步**全部成立且经真库复现**（迁移语义 100% 可核），
但**用户可见结果未达成**：`GET /operation-layers` **零前端调用点**、两层分区/交付一列价界面未落地（#4677 OPEN），
且用户原始诉求「建不出纯布料路线」的真根因（V79 按租户派生块类型推断报错，#4685）**未修**。

---

## 1. 验收剧本（按商家用户旅程；每点给期望的用户可见结果）

| # | 用户动作 | 期望的用户可见结果（verbatim / 可判定谓词） |
|---|---|---|
| J1 | 进「工艺配置」（`/production/routings`） | 看到工序库列表；**期望**：分「工序」与「打包发货」两层分区 |
| J2 | 看「打包发货」区 | **期望**：`打包` 一列价，显示「未定价」（**不是** ¥0.00） |
| J3 | 给 `裁剪 × 布料` 定价 | **期望**：改价落库、读面回显 |
| J4 | 点「新建路线」，勾「适用帘种 = 布料」 | **期望**：选项里有「布料」；能建成一条**纯布料路线** |
| J5 | 用该路线建一张布料加工单 | **期望**：加工单工序 = **2 道**（`裁剪` + `打包`） |
| J6 | 删除 `配料` 工序 | **期望**：工序库不再有 `配料`；新建布料单不含 `配料` |
| J7 | 看历史加工单 / 历史工资 | **期望**：历史工序快照与计件金额**一字不变** |

---

## 2. 声明矩阵（L1 / L2 / UA）

**L1** = 机器可判（真库读数 / pytest / mvn / 静态断言）；**L2** = 机器结论 + 证据引用；**UA** = AI 用户代理判定。
**无「待人工」项；非全 UA**（L1 占 9/11）。

| 验收点 | 层级 | 判定 | 证据锚点 |
|---|---|---|---|
| J1 两层分区可见 | L2 | ❌ **未达成** | `routings/page.tsx` 零 `operation-layers`；#4677 OPEN |
| J2 未定价 ≠ ¥0.00 | L1 | ✅ 成立（读面层） | 真库：`打包 → unpriced price=null`；`ProductionOperationLayersTest` 7 passed |
| J3 改价落库回显 | L1 | ✅ 成立（既有端点，非本单） | `PUT /operation-positions/{id}` 既有；本单未改 |
| J4 建纯布料路线 | L2 | ⚠️ **部分** | 前端 `positionOptions` 已同源带出 `布料`；真根因 #4685 未修 |
| J5 布料单 2 道工序 | L1 | ✅ 成立 | 真库模拟 buildRoute：`实例化工序数=2` |
| J6 `配料` 退场 | L1 | ✅ 成立（1 号租户 + 按租户语句） | 真库：两租户 `配料` 工序行存活=0；矩阵格存活 0 |
| J7 历史快照/工资不变 | L1 | ✅ 成立 | V88 剥注释后三张快照表 **0 命中**；无 DELETE/TRUNCATE/DROP |
| A1 V88 七条动作 | L1 | ✅ 成立 | 真库逐租户读数（见 §5） |
| A2 幂等 / 显式写列 / 回滚 | L1 | ✅ 成立 | 两次 md5 相同；`SET deleted=1, updated_at=NOW()`；V89 不存在 |
| A3 31 而非 35 | L1 | ✅ 成立（**红证**） | 35 格版 ⇒ 布料单实例化 **1** 道（见 §7） |
| C 读面 4 态 + 不回落 | L1 | ✅ 成立 | 静态守卫 + 注入式红证（见 §7） |

---

## 3. 待核主张 A~F 逐条判定

### A. 迁移语义（V88 七条动作）

| 主张 | 判定 | 证据引用 |
|---|---|---|
| ① `配料` 工序行软删 | **成立** | 真库 `v88c`：`select count(*) from production_operations where name='配料' and deleted=0` ⇒ 两租户均 **0**；SQL：`UPDATE production_operations o SET deleted = 1, updated_at = NOW() … AND o.name = '配料' AND o.deleted = 0;` |
| ② `配料 × 4 部位` 软删 | **成立** | 同语句 `production_operation_positions … AND p.logical_name = '配料'`；V79 该 4 格（`('配料','布料'|'布帘'|'纱帘'|'帘头')`）全部 `deleted=1` |
| ③ 主线 → `["裁剪","打包"]` | **成立** | 真库 `select mainline from production_route_templates where name='布料工序路线'` ⇒ 两租户均 `["裁剪", "打包"]`；SQL 为手术式元素替换 `CASE WHEN elem = '"配料"'::jsonb THEN '"裁剪"'::jsonb` |
| ④ `裁剪 × 布料` 保命格 TRUE | **成立** | 真库：两租户 `裁剪×布料 applicable=true`（V79 初值 **FALSE**）；SQL `SET applicable = TRUE … AND p.applicable IS DISTINCT FROM TRUE` |
| ⑤ 退场 **31** 格（非 35/36） | **成立** | 真库：两租户 `退场=31 存活=5`；存活格 = `裁剪×布料 + 打包×{布帘,纱帘,帘头,布料}` |
| ⑥ 按租户覆盖（无字面量） | **成立** | 5 条 DML 全含 `FROM tenants t`；剥注释后 `tenant_id\s*=\s*\d` **零命中**；真库 **两个**租户同终态 |
| ⑦ `打包` 4 格 + `scope='set'` 零语句触及 | **成立** | 真库：`打包存活=4 scope=set`（两租户）；V88 含 `'打包'` 的语句 **恰 1 条**（⑤ 的 `NOT IN` 排除列表），无任何 `SET` 目标侧命中 |

### A2. 幂等 / 显式写列 / 回滚

| 主张 | 判定 | 证据引用 |
|---|---|---|
| 幂等（跑两次净效果相同） | **成立** | 真库：`md5#1 = md5#2 = 0ed74b92f513697d0f31e235bdec097c`（指纹含 `updated_at::text` ⇒ 第二次**确实没重写**） |
| 显式写列（#4608，非 `updateById` 形态） | **成立** | 3 条软删语句均为 `SET deleted = 1,\n       updated_at = NOW()`；`test_v88_soft_deletes_write_explicit_columns` 逐条断言 |
| 回滚 = 新迁移 V89（不删 V88） | **成立** | `ls db/migration \| grep -E "V8[89]"` ⇒ 仅 `V88__…`；V88 注释块内登记 V89 回滚 SQL；`test_v88_is_the_next_free_number_and_v79_is_untouched` 断言 V89 文件不存在 |

### A3. 为什么是 31（逐格断言）

| 主张 | 判定 | 证据引用 |
|---|---|---|
| `36 − 1 − 4 = 31`，`31 + 5 = 36` | **成立** | 真库：`退场=31 / 存活=5 / 合计=36`；V79 网格实测 36 行（28 既有 × 布料 + 配料×4 + 打包×4） |
| 按 35 做是错的（删 `打包×布料` ⇒ 布料单静默少一道） | **成立（红证）** | 见 §7 红证 A3：35 格版 ⇒ `打包 × 布料 → 无格 ⇒ applicable=null ❌ 静默 continue`，`布料单实际实例化工序数 = 1`（正确版 = 2） |

### B. 真库核查

| 主张 | 判定 | 证据引用 |
|---|---|---|
| V79 → V88 ×2，两次 md5 相同、31/5/36 每租户 | **成立（已独立复现）** | 本机 PG 16.15，`/tmp/pgv88/repro.sh`；两次 md5 相同、两租户 31/5/36（见 §5 transcript） |
| S1/S3/S4/S6 全绿 | **成立（静态层）** | `pytest tests/unit_ci_workflows/test_public_ops_v88_migration.py` ⇒ **24 passed**；6 条停止条件逐条为空 |
| ⚠️ 复现必须打的一处补丁 | **如实登记** | V79 按租户派生块**原样跑不通**（见 §6 P0-2 / #4685），复现时对 V79 副本只补 `NULL::numeric` 类型显式化，**未改 V88 一个字节** |

### C. 读面（`GET /operation-layers`）

| 主张 | 判定 | 证据引用 |
|---|---|---|
| 分区判据 = 既有 `scope`（`'set'` ⇒ delivery；其余含 `null` ⇒ operations） | **成立** | `ProductionRoutingReadService.operationLayers`：`if (SCOPE_SET.equals(row.get("scope"))) { deliveryCells… } else { operations.add(row); }`；`SCOPE_SET = "set"`。真库：4 格 `打包` 全落 delivery，`裁剪×布料`（scope=`position`）落 operations |
| 一列价 4 态 | **成立** | `priced` / `unpriced`（`price=null`）/ `multiple_prices` + `different_price_count` / `no_applicable_position` 四分支齐全；`ProductionOperationLayersTest` **7 passed** 逐态覆盖 |
| 未定价 ≠ ¥0.00 | **成立** | 真库：`打包 (cells=4, applicable=4) → unpriced price=null`，而 `production_operations.unit_price` 行价 = `0.00`（`NOT NULL DEFAULT 0`）—— 读面**未**回落 |
| 不回落工序库行价 | **成立** | `deliveryView` 方法体内 **无** `productionOperationMapper` / `operationsByName` / `production_operations`（静态守卫 + 注入式红证，见 §7） |

### D. 口径分裂与真值源（**这两条确实不成立**）

| 主张 | 判定 | 证据引用 |
|---|---|---|
| 8. `docs/sql/schema.sql` 仍是旧口径 | **成立（口径分裂属实）** | `schema.sql`：`('opp-v79-29', 1, '配料', '布料', NULL, TRUE, 'active')`、`'["配料", "打包"]'::jsonb`（`rt-v79-01`）；#4690 OPEN |
| 9. 真值源未收敛 | **成立（口径分裂属实）** | `routing.py:465 FABRIC_MAINLINE_STEPS: List[str] = ["配料", "打包"]`；`routing.py:638 ("裁剪", "布料", None, False)`；`seed.json` `operations: 37`（description 逐字「37 道工序」）；`routing.py` OPERATION_CATALOG 实测 **37** 道 |

### E. 红线（三张快照表一字不动）

| 主张 | 判定 | 证据引用 |
|---|---|---|
| `processing_orders.items_snapshot` / `processing_position_operations` / `production_work_logs.unit_price`+`factor` 零触及 | **成立** | `grep -v "^\s*--" V88 \| grep -c "processing_orders\|processing_position_operations\|production_work_logs"` ⇒ **0**；`test_red_line_never_touches_snapshot_tables` 双向断言；`production_work_logs` DDL 中 `unit_price NUMERIC(10,2)` / `factor NUMERIC(10,2)` 未被任何语句引用 |

### F. 用户可见结果

| 主张 | 判定 | 证据引用 |
|---|---|---|
| 11. 用户可见地解决了？ | **❌ 未达成** | 见 §8「未达成清单」 |

---

## 4. 复核抽验（独立于实施包自述）

| 抽验项 | 方法 | 结果 |
|---|---|---|
| V88 指纹 | `sha256sum V88` vs `migration_fingerprints.json['V88__…']` | ✅ 逐字节相同 `133f2a83ad3bac07…`；条目数 86（含 V88） |
| CI 门禁（空跑三查） | `gh pr checks 4684 / 4688` | #4684：**Drift Audit = fail**（步骤级 13 steps 真跑，非 skipped）；#4688：**全绿** |
| Drift Audit 终态 | 本地 `python3 scripts/drift_audit.py` @`f511c0fa0` | ✅ `exit 0`，「新增漂移 0 ⇒ OK」 |
| #4684 的 Drift 失败根因 | `gh run view 35481151134 --log-failed` | 逐字：`tests/unit_ci_workflows/test_public_ops_v88_migration.py 第 27 行 ProcessingOrderService.java:1242 无 @<sha> 限定` ⇒ 正是 #4688 修掉的裸行号 |
| 全量确定性测试 | `pytest tests/unit_ci_workflows/` | ✅ **2292 passed, 4 skipped**（183.84s） |
| Java 单测 | `mvnw -Dtest=ProductionOperationLayersTest test` | ✅ `Tests run: 7, Failures: 0, Errors: 0` |

---

## 5. 真库 transcript（V79 → V88 ×2，独立复现）

```
### V79（副本仅补 NULL::numeric 类型显式化）
OK
t1 grid=36      t2 grid=36
t1 主线=["配料", "打包"]      t2 主线=["配料", "打包"]
t1 配料工序行=1  t2 配料工序行=1
### V88 #1  OK        md5#1=0ed74b92f513697d0f31e235bdec097c
### V88 #2  OK        md5#2=0ed74b92f513697d0f31e235bdec097c
✅ 幂等
### 终态
t1 退场=31 存活=5        t2 退场=31 存活=5
t1 配料工序行存活=0      t2 配料工序行存活=0
t1 主线=["裁剪", "打包"]  t2 主线=["裁剪", "打包"]
t1 裁剪x布料 applicable=true   t2 裁剪x布料 applicable=true
t1 打包存活=4 scope=set   t2 打包存活=4 scope=set
t1 存活格=打包×布帘,打包×布料,打包×帘头,打包×纱帘,裁剪×布料
t2 存活格=打包×布帘,打包×布料,打包×帘头,打包×纱帘,裁剪×布料
```

读面（对 `v88c` 真库状态，忠实模拟 `variantNameOf` 裸名兜底 + `operationLayers` 分区）：

```
===== 分区（按 scope）=====
operations | 裁剪×布料 scope=null          ← 变体查不到 ⇒ 安全方向落 operations
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

---

## 6. 问题清单（P0/P1/P2 + 证据 + 归因）

### P0-1 · `GET /operation-layers` **零发射点/零前端调用** ⇒ 能力类交付物**未交付**

- **证据引用**：
  - `grep -rn "operation-layers" frontend/admin-web/src` ⇒ **零命中**
  - 全仓 `operation-layers` 仅 3 处：`ProductionController.java`（端点定义）、`test_routing_read_endpoints.py`（静态判据）、`ProductionController.java:565`（注释）
  - 真实界面页 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx`（4340 行）**9 处**调用 `operation-positions`，**0 处**调用 `operation-layers`
  - 同页无「两层 / 交付 / delivery / 打包发货」任何 UI 标记（`grep` 零命中）
  - issue **#4677**（工艺项界面改造）状态 = **OPEN**，标题逐字含「依赖 #4676」
- **交付物可达性三问**：**谁发射** = 无前端调用点；**哪个入口可达** = 无；**有无测试钉住** = 有（服务层 7 项 + 静态判据，但**只钉服务层，不钉 HTTP/前端**）
- **归因（机制级）**：本次交付按 PR 标题自述「**界面另单**」刻意不含 UI ⇒ 端点被建出来但**无消费者**。
  与 `migao-acceptance` v1.11 的 #4016 形态同族（`payment` / `production_progress` 组件在 main 却零发射点）。
- **分级理由**：不是实现缺陷，而是**交付范围缺口**；但它使「用户可见结果」不成立 ⇒ P0。

### P0-2 · 用户原始诉求「建不出纯布料路线」的真根因**未修**（#4685）

- **证据引用**：本验收在**独立最小库**上复现，V79 按租户派生块**原样报错**：
  ```
  psql:…/V79__seed_fabric_route_and_packing_operation.sql:180: ERROR:  column "unit_price" is of type numeric but expression is of type text
  第4行       t.id, v.logical_name, v.position, v.unit_price, v.app…
  ```
  V79 该 `JOIN (VALUES …)` 块用 `NULL`（无类型）作 `unit_price` 列首值 ⇒ PG 把该列推成 `text` ⇒ 插入 `numeric` 列报错 ⇒ **整个 V79 文件回滚** ⇒ 非 1 号租户的布料工序/矩阵/路线**从未种上**。
  `grep -c "NULL::numeric" V79__…sql` ⇒ **0**（对照：1 号租户的 `VALUES` 语句是显式列插入，不受影响）。
  与 issue **#4685**（OPEN）标题逐字一致：「V79 按租户派生块类型推断报错（NULL 列被推成 text）⇒ **非 1 号租户的布料工序/矩阵/路线可能从未种上**（很可能就是「建不出纯布料路线」的真根因）」
- **归因（机制级）**：V79 的按租户 `VALUES` 列类型由首行字面量推断；`NULL` 无类型 ⇒ 推断为 `text`。V88 只在**已被种上**的格上做软删/改适用性 ⇒ **无法补救 V79 没种上的租户**。
- **为什么不是本单缺陷**：V79 是已发布迁移（改它必红指纹守卫 #4235）；本单在其后追加 V88 是正确做法。但**用户可见症状因此仍在**。

### P1-1 · `routing.py` 真值源与「钉住它的测试」**共同**与 V88 终态冲突（口径分裂 + 测试陷阱）

- **证据引用**：
  - `routing.py:465`：`FABRIC_MAINLINE_STEPS: List[str] = ["配料", "打包"]`
  - `backend/ai-agent-service/tests/test_production/test_fabric_route.py:96`：
    `assert FABRIC_MAINLINE_STEPS == ["配料", "打包"], (f"布料主线漂移：{FABRIC_MAINLINE_STEPS}（裁定 = 配料 → 打包）")`
  - `test_fabric_route.py:108`：`assert build_route_v2({"curtain_type": FABRIC_POSITION, "craft": craft}) == ["配料", "打包"]`
  - `routing.py:638`：`("裁剪", "布料", None, False)`（`裁剪×布料` 仍 FALSE）
  - `routing.py:448` 逐字：「`build_route_v2` 今天是**零消费者**：Java 实例化仍读旧 `production_routings`（P2 才切）」
  - 本验收复核：`grep -rn "build_route_v2" app/` ⇒ **生产代码零消费方**（仅测试与注释）
- **归因（机制级）**：该断言与 `routing.py` 值**同源**（都写 `配料`），因此**改一处不改另一处必红**。
  更关键：断言文案把 **`配料`** 称作「**裁定**」，而 #4673 的裁定恰恰是**改判**为 `裁剪`（V88 已按裁定落码）
  ⇒ 该测试文案是**过期裁定**，会把人**指回 V88 已推翻的方向**（`migao-acceptance`「注释漂移 = 假绿来源」同族）。
- **当前影响**：零（`build_route_v2` 无生产消费方；加工单建单走 admin-api `ProcessingOrderService.buildRoute` 读 DB）⇒ 非 P0。
- **未来影响**：ai-agent P2 切到新模型时必须**同时**改 `routing.py` 与该测试；漏一处即假红。

### P2-1 · V88 文件头自检注释的 grep 计数**被自己的注释块撑大**

- **证据引用**：注释逐字「核验命令（本文件里这三张表名必须**零命中**，`production_operation_positions` 的命中数 = 2）」；
  实测 `grep -c "production_operation_positions" V88__…sql` ⇒ **10**（其中 3 条是可执行 DML 目标，其余 7 处在注释/回滚示例块内）。
  注释里的 `grep -c "processing_orders\|processing_position_operations\|production_work_logs"` 自称 ⇒ 0，实测（全文）**5**（全部在注释块）。
- **归因（存在性→值级）**：注释把**全文 grep** 当成**可执行 SQL** 的核验命令 ⇒ 命令与其声称的读数不自洽。
  正确形态已在同单的守卫里落地（`_strip_comments` 后计数）—— 即**判据对、注释里的命令错**。
- **影响**：读者按注释命令复核会得到 10/5 而非 2/0 ⇒ 误判「迁移写错表」。

### P2-2 · 设计稿仍写「35 格」，V88 落 **31** ⇒ 口径冲突未在文档层收敛

- **证据引用**：
  - `docs/design/public-operations-and-craft-ui.md:415`：`| ⑤ | **其余 35 格软删**（§2.4 的 36 − 1） | production_operation_positions（position='布料' AND logical_name <> '裁剪'） |`
  - 同文件 `:474`：`| ⑤ | 其余 35 格 deleted=0 复原 |`；`:599` F6：`实际退场 35 格`
  - V88 实测落 **31**；`tests/unit_ci_workflows/test_public_ops_v88_migration.py` 把 31 逐格断言
- **归因（机制级）**：设计 §5.2 ⑤ 的谓词 `logical_name <> '裁剪'` 与**同一份设计** ⑦「`打包` 4 格不动」不能同时成立
  （36−1=35 含 `打包×布料`；删它 ⇒ 布料单只剩 1 道）。V88 选了 ⑦+S1+F1 为准（**技术判断正确**），
  但**文档层未同步**，且 V88 文件头只以「口径冲突，照实登记」注明 ⇒ 未走「改设计稿 / 登记订正」的正式路径。
- **影响**：下一个按设计稿实现的人会重犯 35 格错误（正是本单 P0 红证要挡的形态）。

### P2-3 · `test_v88_is_the_next_free_number_and_v79_is_untouched` 在新增 V89 时**自毁**

- **证据引用**：`tests/unit_ci_workflows/test_public_ops_v88_migration.py`：
  `assert max(versions) == 88, (f"V88 不是最大迁移号（实测最大 = V{max(versions)}）—— 后续单若新增 V89+，本判据会红，请把回滚迁移（V89）与「新增迁移」区分开")`
- **归因（值级）**：这是 `migao-acceptance`「真值主张（自毁式）」形态 —— 报错指向的**行动**与真实原因不符
  （真实原因是「有更新的迁移了，请把本判据的下一个自由号 +1」；文案却说「请区分回滚与新增」）。
- **影响**：下一次合法新增迁移（V89/V90…）会让本测试红，读者按文案排查会查错方向。修法：断言改为「V88 存在且 ≤ max」或把「下一个自由号」提为显式常量。

### P2-4 · 前端 `routings/page.tsx:1071` 注释已过期（仍称「V79 只留 `配料`/`打包` 对布料适用」）

- **证据引用**：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1071`：
  `* ⇒ 被适用性矩阵滤掉 ⇒ **丢工序**（V79 只留 `配料`/`打包` 对布料适用）。`
- **归因（机制级）**：V88 之后布料适用格 = `裁剪×布料` + `打包×布料`（`配料×布料` 已退场）⇒
  该注释给出的**跨形态勾选风险提示**依据已变；文案本身正是「注释漂移 = 假绿来源」形态。
- **影响**：影响的是提示文案的准确性（不改变行为）；但会让下一位读者按旧口径判断风险。

### P2-5 · 红证类里有一条**恒真空断言**（`or True`）

- **证据引用**：`tests/unit_ci_workflows/test_public_ops_v88_migration.py:529`：
  `assert _s1_violations(broken) == [] or True  # 主线仍 2 道（配料+打包）⇒ S1 不一定红`
- **归因（值级）**：`X or True` 恒为真 ⇒ 该行**不构成断言**（`migao-acceptance`「空断言」形态）。
  同测试的下一条（`assert _s6_violations(broken)`）是真断言，故红证**未失效**；但这一行应删或改成有判别力的形态。
- **影响**：低（不掩盖任何失败）；属断言卫生问题。

---

## 7. 红证（负向夹具 + 实测输出）

**卫生纪律**：全部注入在 `/tmp` 的**最小副本**上进行（**未改生产代码**）；
注入前后**清 `__pycache__`** + 用 **sha256 内容指纹**自证注入生效（**禁 mtime/size**）；
锚点为**逐字节内联片段 + `@f511c0fa0` 出处**（不读 `origin/main` 这类移动靶）。

### 红证 A3（本单最关键）· 把 ⑤ 做成设计稿的 35 格

| 项 | 值 |
|---|---|
| 夹具 | `sed "s/NOT IN ('裁剪', '打包')/NOT IN ('裁剪')/" V88__…sql` |
| 内容指纹 | `sha256` 前 16 位 `133f2a83ad3bac07` → `991a46d2475e469e`（✅ 生效） |
| 真库结果（35 格版） | `退场=32 存活=4`；`打包 × 布料 → 无格 ⇒ applicable=null ❌ 静默 continue`；**`布料单实际实例化工序数 = 1`** |
| 真库结果（正确 31 格） | `退场=31 存活=5`；`裁剪×布料` 与 `打包×布料` 均 `applicable=TRUE ✅`；**`实例化工序数 = 2`** |
| 判据 | **31 成立，35 会让布料单静默少一道工序**（正是 S1 停止条件） |

### 守卫注入（6 例，逐条证明「改坏即红」）

| 注入 | 指纹变化 | 变红的测试 |
|---|---|---|
| ⑤ 丢掉 `'打包'`（= 35 格） | `133f2a83…`→`991a46d2…` | `test_step5_retires_31_cells_not_35`、`test_step7_packing_cells_and_scope_set_are_untouched`、`test_six_stop_conditions_are_clean_on_the_real_migration`、`TestInjectedDrift::test_s1_red_when_keep_alive_cell_is_dropped`、`::test_s4_red_when_packing_is_included_in_the_delete_predicate`（**5 failed**） |
| ④ 保命格改 `AND FALSE` | `→868f96c0…` | `test_step4_…keep_alive_cell`、`test_v88_is_idempotent`、`test_six_stop_conditions…`、`TestInjectedDrift::test_s1_red_when_keep_alive_cell_is_dropped`（**4 failed**） |
| ③ 主线替换改成 `配料→配料` | `→eb92157c…` | `test_step3_fabric_mainline_switches_to_cutting`（**1 failed**） |
| 软删丢 `deleted = 0` 守卫 | `→2a700af1…` | `test_step1_…`、`test_step5_…`、`test_v88_is_idempotent`（**3 failed**） |
| ① 加 `tenant_id = 1` 字面量 | `→6396a194…` | `test_step6_every_statement_covers_all_tenants`（**1 failed**） |
| 追加写 `production_work_logs` | `→f4435609…` | `test_six_stop_conditions…`、`test_v88_soft_deletes_write_explicit_columns`、`TestInjectedDrift::test_s5_red_when_a_snapshot_table_is_written`、`::test_s4_…`、`test_step6_…`（**7 failed**） |

### 读面注入（F4 红线）

| 项 | 值 |
|---|---|
| 夹具 | 在 `deliveryView` 的 `if (price == null)` 分支里插入 `price = productionOperationMapper.selectById("x") == null ? null : BigDecimal.ZERO;` |
| 内容指纹 | `1a9ed9da6bdb9853` → `d82b8e017487af8b`（✅ 生效） |
| 结果 | `test_delivery_price_rule_reads_only_matrix_cells` **FAILED**（其余 2 条失败是**最小副本缺文件**的 artifact，非判据问题） |
| 判据 | 「一列价不回落工序库行价」**会红** ⇒ 非空断言 |

---

## 8. 未达成 / 未交付清单（照实）

1. **用户可见结果未达成**：
   - 「**工艺项要有公共工序分区**」⇒ 两层分区（`operations` / `delivery`）**界面不可见**（#4677 OPEN）。
   - 「**建不出纯布料路线**」⇒ V88 让布料路线**建单**路径正确（真库实测 2 道），但**真根因 #4685 未修**（非 1 号租户的 V79 播种整文件回滚）。
2. **`GET /operation-layers` 属未交付**（按交付物可达性判据：零发射点、零可达入口）—— 服务层与静态判据已就绪，**HTTP/前端零测试**。
3. **`docs/sql/schema.sql`（bootstrap-first 栈）未收敛**（#4690 OPEN）：仍是 `配料` + `36 格` + 旧主线口径。
4. **真值源未收敛**（`routing.py` / `seed.json` 仍 37 道 + `配料` 主线 + `裁剪×布料` FALSE），且其**测试把旧值钉死**。
5. **V88 未修 V79 的按租户缺陷**（设计上正确：已发布迁移只增不改）⇒ 存量非 1 号租户需另单修（#4685）。

---

## 9. 我避开了哪些假绿 / 假红形态（逐条）

| 形态 | 本验收的处置 |
|---|---|
| **空跑（步骤 skipped / artifact 0 / 整体 success）** | 引用 #4684 CI 前核了**步骤级**：`gh run view 35481151134 --json jobs` ⇒ `steps=13`、结论 `failure`（**非 skipped**）；本地 `verify-all.sh gate` 报「无变更 ⇒ 未执行任何检查（这不是通过）」时**没有**把它读成通过，而是改用 CI 步骤级证据 + 本地独立跑 `drift_audit.py` |
| **陈旧产物** | 真库复现**现跑**（非引用实施包记录）；指纹以**当前文件 sha256** 与 `migration_fingerprints.json` 对账；测试全部在 `f511c0fa0` 树上跑 |
| **基线取晚（假红）** | 注入式红证全部在**注入前**取基线（`pytest` 基线 24 passed 先跑），再注入后跑；不用「跑两次比较」这类易取晚基线的写法 |
| **测试自行重建被测系统的产物路径（假红）** | 未按名字拼任何路径；真库/测试路径均来自被测系统自身（`pytest` 直接跑仓内文件、`psql -f` 直接读仓内迁移文件） |
| **重放未复现缺陷前置条件（假绿）** | 红证 A3 **显式复现了 35 格前置条件**（改谓词后真库读数 `存活=4`）并给出观测值（`实例化工序数=1`）；未把「跑过了」当「测到了」 |
| **注释漂移** | 不引用注释当判据：V88 的 grep 自检注释（自称 2/0）**实测 10/5** 已作为 P2-1 记录；前端 `routings/page.tsx:1071` 过期注释作为 P2-4 记录 |
| **红证锚点读可变引用（判据自红）** | 全部锚点为**逐字节内联片段 + `@f511c0fa0`**；**未**引用 `origin/main`（验收期间 origin/main 已从 `f511c0fa0` 推进到 `82a6fbcfb`，正是移动靶实证） |
| **红证缓存卫生（#4260）** | 每次注入前后 `find … -name __pycache__ -exec rm -rf {} +`，并以 **sha256 前 16 位**自证注入生效（**禁 mtime/size**） |
| **证据过渡帧 / 失败即丢证据** | 真库读数取**终态稳定值**（V88 #2 之后再读）；md5 指纹含 `updated_at::text` ⇒ 能判「第二次是否重写」而不只是「行数相同」 |
| **关系式断言在空集上恒真** | `_retired_cells` 的 31 格断言**非空**（实测 31）；`31+5=36` 的算术断言非空；空断言 `or True`（P2-5）已**主动报出**而非放过 |
| **「文件在 main」当交付** | 对 `GET /operation-layers` 按**交付物可达性三问**判为**未交付**（不是「已合并」） |

---

## 10. 沉淀记录（问题 → case / issue）

| 问题 | 建议沉淀（断言必须可执行） | 关联 |
|---|---|---|
| P0-1 端点零发射点 | 新增静态判据：`grep -rn "operation-layers" frontend/admin-web/src` **非空**（或断言 `routings/page.tsx` 调用该端点）—— 与 #4016 同款「零发射点」守卫 | #4677 |
| P0-2 V79 按租户类型推断 | 真库守卫：V79 的按租户 `VALUES` 块首列必须 `NULL::numeric`（`assert "NULL::numeric" in V79`）+ 双租户播种复现（本报告 §5 harness 可直接入 CI） | #4685 |
| P1-1 routing.py 测试陷阱 | 在 `test_fabric_route.py` 把「裁定」文案改为指向 V88 终态；并加跨栈一致性判据（`routing.py` 布料主线 ≡ V88 终态）**在收敛时**启用 | ai-agent 单 |
| P2-1 V88 自检注释 | 把注释里的 grep 命令改成守卫同款 `_strip_comments` 后计数，或直接引用守卫名 | #4676 |
| P2-2 设计稿 35 vs 代码 31 | 在设计 §5.2 ⑤ / §6 F6 登记「订正为 31（依据 ⑦+S1+F1）」，并加文档一致性判据 | #4675 |
| P2-3 自毁式真值断言 | `assert max(versions) == 88` → 改为「V88 存在」+ 显式「下一个自由号」常量 | #4676 |
| P2-4 前端过期注释 | 更新 `routings/page.tsx:1071` 的适用格口径（`裁剪`+`打包`） | #4677 |
| P2-5 恒真空断言 | 删除 `or True` 行（或改成有判别力形态） | #4676 |

**case 有效性验证（本报告的负向夹具即可作为重放基线）**：
- 旧失败会话/坏夹具重放 ⇒ **必 fail**：§7 的 6 例注入 + 读面注入均已实测红。
- 修复后重放 ⇒ **必 pass**：未注入态 `pytest` 24 passed / `mvnw` 7 passed / `drift_audit.py` exit 0。

---

## 11. 验收边界与未能核验项（如实）

1. **未跑真实 LLM 评测**（按 #4262 用户裁定：默认不派发，仅显式要求时集中跑一次）。本单为数据迁移 + 读面，**不涉及 ai-agent 行为**，无需 LLM 档。
2. **`build_route_v2` 的运行时行为未核**：`backend/ai-agent-service` 缺 `fastapi` 依赖，无法在本机跑其 pytest（`ImportError: No module named 'fastapi'`）。因此 P1-1 的判定依据是**源码级**（函数零生产消费方 + 断言逐字），**非运行级** ⇒ 归因强度标为「存在性/值级」，未升到「机制级运行时」。
3. **双 AI 交叉验证未执行**：本会话未派发独立复核模型（GLM-5.3-Flash）。按协议 §1.5/§1.7，**主验收结论已引证据**，但「双裁判一致性」一项**未做** ⇒ 记为**未达成项**，供上级决定是否补跑。
4. **未在真实云测试环境（SWAS）打活环境判定**：按 v1.9，活环境判定需先断言「无部署在飞」并记录被测 SHA；本次验收对象是**仓库/迁移/真库**，未触活环境。
