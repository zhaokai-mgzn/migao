# 工序命名统一评估：消灭「逻辑名 vs 变体名」两套键（部位只活在矩阵）

> 状态：**评估 · 待裁定** ｜ 日期：2026-09-19 ｜ issue #4620（评估单，**不动代码**）
> 关联：#4609（下拉列变体名 ⇒ 静默丢工序）· #4587（映射没暴露给前端）· #4614（新增工序成孤儿）
> · #4423 / #4427 / #4432（新路线模型 P1/P2）· #4529（布料路线 + `配料`/`打包`）
> 触发（用户裁定原文）：
> > 「**当然要简化**，现在复杂的我无法理解了」「`production_operations` 这个是什么概念」
>
> - **评估对象**：`production_operations`（工序库）与 `production_operation_positions`（部位价目/适用性矩阵）
> - **本单产出**：本文件（唯一新增文件）。**未改任何生产代码、未改任何数据、未改任何守卫**。
> - **章节**：§0 大白话 · §1 目标模型 · §2 影响面清单 · §3 历史红线 · §4 迁移与回滚 ·
>   §5 分阶段方案 · §6 风险与「不做」· **§7 附问（条件工序规则能不能移除）** ·
>   附录 A 命令速查 · 附录 B 与 issue 假设不符的事实。
> - **本文所有数字都附复算命令**；命令一律在仓库根执行（worktree = `origin/main` 的 `b5a093608`）。
>   **全文无估数**；凡与 issue 原文假设不符处，一律在**附录 B** 照实登记并改口径。

---

## 0. 大白话：今天为什么复杂，改完长什么样

### 今天：同一道活有两个名字，界面上还各说各话

把「工序」想成车间里的一道活。今天这道活在系统里有**两套名字**：

| 你在哪儿看到它 | 它叫什么 |
|---|---|
| 「部位价目」那张表（哪几个部位做、各自多少钱） | **`三边`** |
| 「工序库」那个下拉（往路线里添工序时选的那个） | **`布三边`** |

这两行说的**是同一道活**。`布三边` 这个名字里已经含了「布帘」这个部位，而部位本来应该只写在矩阵里
（矩阵里 `三边 × 布帘` / `三边 × 纱帘` / `三边 × 帘头` 三格才是「哪几个部位做」的答案）。

**后果就是两天内报的 bug 一半以上**：

1. **加一道工序，系统像没加**（issue #4609）：你在「工艺路线」里从下拉选工序，下拉给的是 `布三边`；
   你点「加入」，主线里存下 `布三边`；保存**成功**；可一到生成加工单，系统按**逻辑名** `三边`
   去矩阵里查「这个部位做不做」——查 `布三边` 查不到 ⇒ **这道工序被静默丢掉**。
   页面上既不报错也不标红：`knownOps`（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:885-888`）把「工序库名 ∪ 矩阵行键」
   并成一份「已知」，`布三边` 两处都「认识」⇒ 前端预检的 `missingSteps`
   （`:1090`，渲染于 `:2083-2091`）**恒为空数组、红字永不出现**。
2. **界面不敢显示单位/单价/必完**（issue #4587）：`三边`（矩阵）↔ `布三边`（工序库）的对应关系
   此前**没有暴露给前端** ⇒ 前端「不猜」，只显示工序名，不显示单位/必完。
3. **新增工序成了孤儿**（issue #4614）：`POST /operations` 只往工序库写一行，
   **不建矩阵行** ⇒ 一边（工序库）看得到、另一边（矩阵）看不到。

### 改完：一道工序只有一个名字，部位只活在矩阵里

- 工序库里那道活就叫 **`三边`**（一个名字，不带部位后缀）；
- 「哪几个部位做、各自多少钱」**只在矩阵里**（`三边 × 布帘` / `三边 × 纱帘` / `三边 × 帘头`）；
- 工人端要看得懂「这道活做在哪件帘上」，展示时**拼**出来：**`三边` · 布帘** —— 拼是**展示层**的事，
  库里**不再存** `布三边` 这个名字；
- 历史（已经报过工、已经算过钱的）**一个字都不动**：当时的名字照旧是 `布三边`。

一句话：**今天「部位」被写了两遍（名字后缀 + 矩阵列），改完只写一遍（矩阵）。**

---

## 1. 目标模型（before / after 数据示例）

### 1.1 Before（今天的真实数据）

`production_operations`（工序库）—— 1 号租户实测 **37 行**：

```bash
grep -oE "\('[^']+',\s*[0-9]+,\s*'[^']+'" backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql | wc -l
# → 30（V54）
grep -cE "^\s*\('op-v56-" backend/admin-api/src/main/resources/db/migration/V56__seed_special_option_operations.sql
# → 5（V56）
grep -cE "^\s*\('op-v79-" backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql
# → 2（V79）  ⇒ 30 + 5 + 2 = 37
```

```
id          name        position  unit  unit_price  group
op-v54-05   布三边       NULL      米    0.40        车位     ┐
op-v54-06   纱三边       NULL      米    0.40        车位     ├ 同一道活「三边」
op-v54-07   韩褶-布      布帘      折    0.40        车位     │  （名字里带部位）
op-v54-08   韩褶-纱      纱帘      折    0.40        车位     ┘
op-v54-01   精裁-布      布帘      米    0.40        裁剪
op-v54-02   精裁-纱      纱帘      米    0.40        裁剪
op-v54-19   帘头制作      帘头      个    2.00        车位     ← 部位无关（名字里没部位）
```

`production_operation_positions`（部位价目 + 适用性矩阵）—— 实测 **120 行 = 30 逻辑工序 × 4 部位**：

```bash
python3 -c "
import re;src=open('docs/sql/schema.sql',encoding='utf-8').read()
b=re.findall(r'INSERT INTO production_operation_positions\b(.*?);',src,re.S)
r=re.findall(r\"\('[^']+',\s*\d+,\s*'([^']+)',\s*'([^']+)'\",''.join(b))
print('rows',len(r),'distinct logical',len(set(x[0] for x in r)))"
# → rows 120 distinct logical 30
```

```
id          logical_name  position  unit_price  applicable
opp-v70-07  三边          布帘      0.40        true       ← 这三个格 = 「三边 做在哪些部位」
opp-v70-08  三边          纱帘      0.40        true
opp-v70-09  三边          帘头      0.40        true
```

「逻辑名 ↔ 变体名」的映射表 —— 实测 **35 条**（`grep -c '^    ("' ` 于 `_LOGICAL_NAME_PAIRS` 段）：

```
布三边 → 三边     纱三边 → 三边     韩褶-布 → 韩褶    韩褶-纱 → 韩褶
精裁-布 → 精裁    精裁-纱 → 精裁    布帘车被 → 车被   帘头制作 → 帘头制作（不变）
…共 35 条，其中 **7 组**是同组 2 个变体（35 − 7 = **28** 个逻辑名，即 V71 冻结的 28）
```

> ⚠️ **与 issue 假设不符的事实（照实登记）**：V71 冻结的是 **28** 个逻辑名，但今天实际是 **30** 个
> （V79 / #4529 追加 `配料` / `打包`）。所以本单的「合并」目标是 **35 个旧名 → 30 个逻辑名**，
> 不是 28。复算：`python3 -c` 上面那条 → `distinct logical 30`。

### 1.2 After（目标数据）

`production_operations`（工序库）—— **30 行**，`name` = 逻辑名，**`position` 列退场**：

```
id          name    unit  unit_price  group
op-v54-05   三边    米    0.40        车位     ← 只剩一行（原来 布三边 + 纱三边 两行）
op-v54-01   精裁    米    0.40        裁剪     ← 只剩一行（原来 精裁-布 + 精裁-纱 两行）
op-v54-19   帘头制作 个    2.00        车位
```

`production_operation_positions`（**不变**，120 行）—— 部位只活在这里：

```
opp-v70-07  三边  布帘  0.40  true     ← 「三边 做在布帘，0.40 元/米」
opp-v70-08  三边  纱帘  0.40  true
opp-v70-09  三边  帘头  0.40  true
```

工人端 / 加工单展示：**展示层拼**（库里不存）：

```
矩阵格 (三边, 布帘)  →  展示 "三边 · 布帘"
矩阵格 (韩褶, 纱帘)  →  展示 "韩褶 · 纱帘"
部位无关的 (帘头制作, 帘头) → 展示 "帘头制作 · 帘头"（或按部位省略后缀，见 §6「不做」）
```

### 1.3 目标模型的四条硬约束

| # | 约束 | 理由 |
|---|---|---|
| T1 | `production_operations.name` 只存**逻辑名** | 一个名字一把尺，消除两套键 |
| T2 | 部位**只在** `production_operation_positions` | 部位写第二遍就是漂移源 |
| T3 | 展示层**拼**名字，不落库 | 工人需要「哪件帘」，但那是展示需求，不是数据需求 |
| T4 | 历史快照（实例/报工）**一字不动** | 那是当时算钱的证据（§3） |

---

## 2. 影响面清单（逐文件、逐端，全部实测 grep）

### 2.1 Java（admin-api）

#### 2.1.1 「旧名 ↔ 逻辑名」映射表 —— **实测有 4 份副本**（不是 2 份）

| # | 位置 | 形态 | 复算命令 | 命中 |
|---|---|---|---|---|
| 1 | `backend/ai-agent-service/app/production/routing.py:494` `_LOGICAL_NAME_PAIRS` | **真值源**，35 条有序对 | `grep -rl '_LOGICAL_NAME_PAIRS' backend \| wc -l` | `3` |
| 2 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java:637` `logicalNamePairs()` | 生产代码副本（35 条） | `grep -rl 'VARIANT_NAMES' backend \| wc -l` | `1` |
| 3 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:283` `logicalNames()` | 生产代码副本（35 条） | `grep -rn 'private static Map<String, String> logicalName' backend/admin-api/src/main --include=*.java` | `2` 行（`QueryService:637` + `SeedTemplateService:283`） |
| 4 | `backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture.java:564` `LOGICAL` | **测试夹具副本**（35 条） | `grep -rl 'OPERATION_LOGICAL_NAMES' backend \| wc -l` | `12` |

> 🔎 **与 issue 假设不符的事实（照实登记）**：issue 只点了「`VARIANT_NAMES` / `normalizeOperationName`」
> 一处，实测生产代码里有 **2 份**（`QueryService` + `SeedTemplateService`），测试夹具里还有 **1 份**
> （`backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture`）。**统一时必须三份一起退场**，否则「改了生产、测试夹具还在按旧口径造数据」。

**`VARIANT_NAMES` / `variantNameOf`（逻辑名 → 该部位变体名）的消费者**：

```bash
grep -rl 'variantNameOf' backend/admin-api/src/main | wc -l   # → 6
grep -rl 'variantNameOf' backend/admin-api/src/test | wc -l   # → 8
```

| 文件:行 | 角色 | 统一后 |
|---|---|---|
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java:108`（`VARIANT_NAMES` 定义）、`:338-380`（`variantNameOf` 四步查找）、`:678-760`（`variantNames()` 显式表） | 把逻辑名换回库里变体名 | **整体退场**（T1 后库里就是逻辑名，不需要翻译） |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1255` `buildRoute` 内 `variantNameOf(logicalName, position, catalog)` | 实例化时取库口径元数据 | 改直读 `catalog.get(logicalName)` |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationCommandService.java:294` `delete` 护栏③（矩阵行引用检查） | 删工序前查「还挂在哪些格」 | 改按 `row.getLogicalName()` 直接比 |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java:116-118` `variantName` | 矩阵读面的 6 键变体元数据 | 键仍在（`variant_name`），值 = 逻辑名自身（或整体退场，见 §5 P1） |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:877-887`（比较前归一） | 实例名 ↔ 主线锚点比较 | 名字统一后不需要归一 |

**`normalizeOperationName`（旧名 → 逻辑名）的消费者**：

```bash
grep -rl 'normalizeOperationName' backend | wc -l   # → 9
```

| 文件:行 | 角色 | 统一后 |
|---|---|---|
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java:333`（定义） | `OPERATION_LOGICAL_NAMES.getOrDefault(name, name)` | **退场**（或降级为「只读历史」） |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationCommandService.java:266`（删工序时归一） | 旧名/逻辑名两态 | 退场 |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:539`（实例化归一）、`:887`（锚点比较归一） | 两态归一 | 退场 |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java:438-446`（主线判重归一）、`:534-549`（**判重键 = 归一后逻辑名**，issue #4520「同一道工序按两遍单价拿钱」的护栏） | **这条护栏的语义在统一后变成「同一名字出现两次」** —— 判据要改判，**不能直接删**（见 §2.5） | 改判：去掉归一、保留「同名字不得重复」 |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:700` `logicalName()` | 播种时归一 | 退场（模板 JSON 改逻辑名后不需要） |

#### 2.1.2 工序库 CRUD

| 文件 | 关键行 | 说明 | 统一后 |
|---|---|---|---|
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationCommandService.java` | `:175-250` `create`（声明在 `:175`） | 只写 `production_operations` + 价格版本行；**不建矩阵行** ⇒ **issue #4614 的孤儿**根因 | **必须同时建矩阵行**（P1 可先做，见 §5） |
| 同上 | `:201` `.position(optionalText(body.get("position")))` | 写 `position` 列 | **退场**（T2） |
| 同上 | `:254-315` `delete`（声明在 `:254`） | 三道护栏（主线/规则/矩阵行） | 护栏③ 改按逻辑名比 |
| 同上 | `:77-160` `update`（声明在 `:77`） | 改单价 → 写 `production_operation_price_versions` | 保留（价格版本账与命名无关） |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java` | `:135-155` `catalog()`（`GET /operations-catalog`，声明在 `:135`）、`:569-590` `operationView` | 目录读面；`:574` `view.put("position", op.getPosition())` | 去掉 `position` 键（或保留为 null 一个版本周期） |
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationPositionCommandService.java` | `:117` 改矩阵格 → 写 `production_operation_position_price_versions` | 矩阵写面 + 价格版本账 | **保留**（这是目标模型的核心写面） |

> `production_operations.position` 的消费者实测只有 1 处（读面暴露）：
> ```bash
> grep -rn "op.getPosition\|operation.getPosition" backend/admin-api/src/main/java --include=*.java
> # → 只有 ProductionOperationQueryService.java:574
> ```
> ⇒ **`position` 列退场是低风险的**（没有实例化/计件逻辑读它；部位的真值源是矩阵的 `position`）。

#### 2.1.3 实例化（`ProcessingOrderService.buildRoute`）

```bash
grep -n "buildRoute\|variantNameOf\|normalizeOperationName" backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java
# → :539 / :779 / :816 / :853 / :877 / :887 / :1134 / :1172 / :1180 / :1255
```

`buildRoute`（`:1180-1265`）是**「静默丢工序」的发生地**，也是本单最关键的一段：

```java
// :1233-1236（今天）
for (String logicalName : sequence) {
    if (!Boolean.TRUE.equals(applicableByLogical.get(logicalName))) {
        continue;   // ← 主线里若是变体名（布三边），这里拿到 null ⇒ 静默 continue
    }
```

复现路径（issue #4609）：主线存 `布三边` → `applicableByLogical` 只有逻辑名键（`三边`/`精裁`…）
→ `get("布三边") == null` → `continue` → **工序消失、无异常、无 missing 记录**。

| 行 | 内容 | 统一后 |
|---|---|---|
| `:1186-1194` | 按 `(row.position == 该部位)` 建 `priceByLogical` / `applicableByLogical` | **保留**（矩阵是唯一适用性真值源） |
| `:1210-1230` | 规则应用（`craft` / `option` / `processing_item`；`shaped` 显式抛错） | 保留 |
| `:1255` | `variantNameOf(...)` → `catalog.get(variant)` | 改直读 |
| `:1256-1259` | `meta == null ⇒ missing.add(logicalName); continue`（fail-closed 指名报缺） | 保留（但要保证「主线里存的必须是逻辑名」） |
| `:1264` | `step.put("operation", variant)` —— **实例快照写的是变体名** | 见 §3（历史红线） |

#### 2.1.4 报工与计件读面（`ProductionService`）

```bash
grep -n "getOperationName\|operation_name" backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java
# → :158 / :243-252 / :277 / :307-313 / :371 / :450-452 / :596 / :625 / :683-689 / :844 / :888-890 / :1196
```

| 行 | 读的是什么 | 统一后 |
|---|---|---|
| `:277` `specsOf` | **工序实例快照** `op.getOperationName()` | **不动**（历史证据） |
| `:371` 报工明细读面 | `production_work_logs.operation_name` 快照 | **不动** |
| `:450-452` `pending` / `current`（进度） | 实例快照 | **不动** |
| `:596` 报工写快照 | `op.getOperationName()` | **不动** |
| `:683-689` 越站护栏文案 | 前道/本道**实例快照**名 | **不动**（但**文案**会继续显示旧名，见 §3.3） |
| `:888-890` 计件聚合 | 优先 `log.operationName`，缺值回落实例 | **不动**（金额口径） |
| `:1196` `view.put("operation", op.getOperationName())` | Agent 冻结契约键 | **不动**（键名冻结） |

> **结论**：报工与计件**完全不依赖工序库的名字** —— 它们读的是**实例快照**。
> 这正是「改名不影响历史金额」的结构性保证（§3.2 给验证方式）。

#### 2.1.5 种子与模板套用

| 文件/迁移 | 内容 | 统一后 |
|---|---|---|
| `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java` | `:109` `LOGICAL_NAMES`、`:283-320` `logicalNames()`、`:473-500` 矩阵播种、`:517-560` 规则播种、`:659-690` `logicalNamesOf` | 副本退场；播种直接用逻辑名 |
| `production-templates/curtain/seed.json` | `operation_name` 实测 14 个不同取值，**全部是变体名** | 改逻辑名（或播种时归一后落库） |
| `V54__seed_production_operations.sql` | 30 行工序种子（旧名） | **已发布迁移不可改**（`MigrationRunner` 按文件名记账，改了对存量库无效）⇒ 走**新迁移** |
| `V56__seed_special_option_operations.sql` | 5 行（含 `绑带-纱`） | 同上 |
| `V71__normalize_routing_model_structure.sql` | 新结构三表 + **84 行**矩阵（28×3）；`:158` 等处规则已用逻辑名 | 矩阵行**已是逻辑名** ⇒ 基本不动 |
| `V72__switch_routing_model_consumers.sql` | 按租户回填三表；`:153-166` / `:228-240` 有**内联的旧名归一 `CASE`**（`布三边→三边` 等） | 回填产物已是逻辑名；`CASE` 在新迁移里**复用同一形态**（见 §4 SQL 草案） |
| `V76__redo_v72_with_sort_order_fix.sql` | V72 重做版，同款 `CASE` | 同上 |
| `V79__seed_fabric_route_and_packing_operation.sql` | `配料`/`打包` 两行（`:52-53`，**已经是逻辑名**）+ 36 格布料价目 | 这两行**已经是目标形态** ⇒ 可作迁移的「已完成」样板 |
| `V83__seed_processing_item_catalog.sql` | 加工项目录（16 项），**与工序库命名无关** | 不动 |
| `V84__seed_processing_item_route_rules.sql` | 加工项触发的路线规则 | 不动（规则 `operation` 已是逻辑名） |

复算：

```bash
grep -rln "INSERT INTO production_operations" backend/admin-api/src/main/resources/db/migration/
# → V54 / V56 / V79（共 3 个文件）
grep -rl "production_operations" backend/admin-api/src/main/resources/db/migration | wc -l   # → 15
```

#### 2.1.6 数据与迁移（唯一键冲突 —— 本单最硬的约束）

```bash
grep -n "uk_production_operations_tenant_name" docs/sql/schema.sql
# → :806
sed -n '806,808p' docs/sql/schema.sql
# CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operations_tenant_name
#     ON production_operations (tenant_id, name)
#     WHERE deleted = 0;
```

**冲突必然发生**：把 `布三边` 与 `纱三边` 都改名成 `三边` ⇒ 同一 `(tenant_id, name)` 两行 ⇒
撞 `uk_production_operations_tenant_name` ⇒ 迁移报错、事务回滚。

实测有 **7 组**这样的重复（复算命令见下），即 **14 行 → 7 行**（净减 7 行，37 → 30）：

```bash
grep -c '^    ("' <(sed -n '/^_LOGICAL_NAME_PAIRS/,/^\]/p' backend/ai-agent-service/app/production/routing.py)
# → 35（旧名对数）
grep -n "test_variant_groups_are_exactly_the_seven" -A 8 backend/ai-agent-service/tests/test_production/backend/ai-agent-service/tests/test_production/test_route_model_v2.py
# → 断言 multi 恰为 7 组、每组 2 个变体（VARIANT_GROUPS 冻结）
```

7 组实测（V54 含 6 组 + V56 含 1 组）：

| 逻辑名 | 变体 A | 变体 B | group | unit | unit_price | 两行是否逐值相同 |
|---|---|---|---|---|---|---|
| 精裁 | `精裁-布` | `精裁-纱` | 裁剪 | 米 | 0.40 | ✅ |
| 裁剪 | `裁剪-布` | `裁剪-纱` | 裁剪 | 米 | 0.40 | ✅ |
| 三边 | `布三边` | `纱三边` | 车位 | 米 | 0.40 | ✅ |
| 韩褶 | `韩褶-布` | `韩褶-纱` | 车位 | 折 | 0.40 | ✅ |
| 上车布 | `上车布-布` | `上车布-纱` | 车位 | 米 | 0.50 | ✅ |
| 打孔 | `打孔-布` | `打孔-纱` | 车位 | 孔 | 0.15 | ✅ |
| 绑带 | `绑带-布`（V54） | `绑带-纱`（V56） | 其他 | 套 | 0.50 | ✅ |

> 「两行逐值相同」由既有守卫**已经钉住**：`test_variant_group_shares_group_and_unit`
> （`backend/ai-agent-service/tests/test_production/backend/ai-agent-service/tests/test_production/test_route_model_v2.py:305`）断言同组
> `group`/`unit` 一致；`tests/unit_ci_workflows/test_production_catalog_seed.py:1332`
> `test_position_variant_groups_share_group_unit_and_scope` 断言含 `scope` 在内一致。
> ⇒ **合并掉哪一行都不改语义**（这是「可合并」的判据，不是推测）。

**除唯一键之外，还有两处「按名字引用」需要一起处理**：

```bash
grep -rn "REFERENCES production_operations" docs/sql/schema.sql backend/admin-api/src/main/resources/db/migration/*.sql
# → docs/sql/schema.sql:1125 + V55__create_production_operation_price_versions.sql:23
#   （production_operation_price_versions.operation_id → production_operations(id)）
```

| 引用方 | 引用键 | 合并时的处理 |
|---|---|---|
| `production_operation_price_versions.operation_id` | **`id`（主键）**，不是名字 | 保留**存活行**的 id；被合并行的版本行**改指存活行**（或保留原样 —— 它们仍是「那次改价的证据」；见 §4 SQL 草案的两种选项与判据） |
| `processing_position_operations.operation_name` | **名字（快照）** | **一字不动**（§3 红线） |
| `production_work_logs.operation_name` | **名字（快照）** | **一字不动**（§3 红线） |
| `production_route_templates.mainline`（JSONB 数组） | **名字** | 存量行**已经是逻辑名**（V71/V72 回填时归一过）⇒ 只需处理「商家后来手改过、存了变体名」的行 |
| `production_route_rules.operation` / `after_operation` | **名字** | V71/V72 种子已是逻辑名 ⇒ 同上 |
| `production_operation_positions.logical_name` | **名字（已是逻辑名）** | **不动** |
| `production_routings.operations`（**旧表**，P2 后零消费者） | 名字 | 不动（历史表） |

### 2.2 Python（ai-agent-service）

```bash
grep -rl 'production_operations' backend/ai-agent-service | wc -l   # → 2
grep -rl 'operation_name' backend/ai-agent-service | wc -l          # → 3
```

| 位置 | 内容 | 统一后 |
|---|---|---|
| `backend/ai-agent-service/app/production/routing.py:14-70` `OPERATION_CATALOG` | 35 条工序（旧名 + 分组/单位/单价） | **退场或改逻辑名**（真值源要跟着走，否则三源收敛守卫必红） |
| `backend/ai-agent-service/app/production/routing.py:69` `ROUTINGS` | 9 条展开路线（工序名带部位） | **保留为历史真值**（`test_old_route_truth_source_is_untouched` 已钉住它不许动） |
| `backend/ai-agent-service/app/production/routing.py:132` `SPECIAL_OPTION_ROUTINGS` | 特殊选项条件工序（旧名） | 保留（`backend/ai-agent-service/tests/test_production/test_craft_calc.py`（引用 `SPECIAL_OPTION_ROUTINGS`） 仍在消费）；新模型走 `ROUTE_RULES` |
| `backend/ai-agent-service/app/production/routing.py:328-400` `build_routing`（旧） | 旧模型展开路线 | 保留（`test_old_build_routing_is_untouched` 钉住）；**它仍产出变体名** ⇒ 若仍被实例化消费，是统一后的残留分歧点 |
| `backend/ai-agent-service/app/production/routing.py:494-531` `_LOGICAL_NAME_PAIRS` | **真值源**，35 条 | P3 退场（届时「无旧名可映射」） |
| `backend/ai-agent-service/app/production/routing.py:533` `OPERATION_LOGICAL_NAMES` | 派生 dict | 同 P3 |
| `backend/ai-agent-service/app/production/routing.py:783-816` `build_route_v2` | **新模型**：主线 + 规则 + 适用性 → **逻辑名序列** | **已经是目标形态**（零改动） |
| `backend/ai-agent-service/app/production/routing.py:301-320` `qty_and_source(operation, calc_info)` | 按工序名取单位 | 名字统一后**入参从变体名变成逻辑名** ⇒ 调用链要同步（见下） |
| `backend/ai-agent-service/app/api/internal.py:20,309` | `qty_and_source(operation, ...)` 的唯一生产调用点 | 入参来源是 Java 实例化 payload 的 `operation` ⇒ P2 改数据后自动变成逻辑名 |
| `backend/ai-agent-service/app/production/piecework.py`（全文 91 行） | 计件 = `Σ(合格数量 × 实例单价 × 实例 factor)` | **与工序库命名完全无关**（只按 `instances`/`work_logs` 的 `operation` 字段配对）⇒ **零改动** |
| `tests/test_production/backend/ai-agent-service/tests/test_production/test_routing.py` / `backend/ai-agent-service/tests/test_production/test_operation_qty.py` / `backend/ai-agent-service/tests/test_production/test_special_options.py` / `backend/ai-agent-service/tests/test_production/test_fabric_route.py` | 用旧名做断言（`grep -rl '布三边' backend/ai-agent-service` 命中 5 个文件） | 逐个改判（见 §2.5） |

复算：

```bash
grep -rl '布三边' backend/ai-agent-service | wc -l   # → 5
```

### 2.3 前端（admin-web）

```bash
grep -rl 'operation-positions' frontend/admin-web/src | wc -l   # → 3
grep -rl 'operation_name' frontend | grep -v node_modules | wc -l   # → 3
grep -rl 'production_operations\|operations-catalog\|operation-positions' frontend/admin-web/src | wc -l   # → 3
```

| 文件 | 关键行 | 角色 | 统一后 |
|---|---|---|---|
| `src/app/(dashboard)/production/frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx`（唯一入口，**3117 行**） | `:867` `libraryOps = (catalog?.groups ?? []).flatMap(g => g.operations)`；`:868-872` `libraryByName` | **issue #4609 的前端源头**：取值域 = `operations-catalog` 的 `name`（= `production_operations.name` = **变体名**；后端 `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:241` → `QueryService:463` `entry.put("name", op.getName())`） | 改列**逻辑名**（本页已有：`:954` `logicalOps = matrixRows.map(r => r.operation)`，来源 = 矩阵行键） |
| 同上 | `:2096-2109` `<select data-testid={routing-add-select-${id}}>` → `<option value={op.name}>{op.name}</option>` | **下拉项 = 变体名** | 改用 `logicalOps` |
| 同上 | `:1101-1105` `addFromPalette(name)` → `setDraft(d => [...d, name])` | 变体名**原样**进主线草稿（**无任何转换**） | 只收逻辑名 |
| 同上 | `:1131` `await productionApi.updateRouting(editing.id, { mainline: draft })` | **变体名落库为 `mainline`** | 落库前必为逻辑名 |
| 同上 | `:884-888` `matrixOps` / `knownOps`（library ∪ matrix） | **让预检失效**（见 §0 第 1 条） | 删并集 ⇒ `missingSteps` 真能变红 |
| 同上 | `:1056-1067` `stepView`：`resolved: !!libraryByName.get(name)`、`missing: !knownOps.has(name)` | 变体名 ⇒ `resolved=true` / `missing=false` | 判据改按 `matrixOps` |
| 同上 | `:954` `logicalOps`；`:3039-3071` 规则下拉（目标工序 + 插入锚点） | **规则侧已经是逻辑名（正确的一侧）** | **不动** —— 这正说明「同一屏内两套取值域」（规则=逻辑名、主线=变体名）是分叉证据 |
| 同上 | `:878-882` `libraryById` + `:1016` `libraryById.get(id)?.source` | 变体 id → provenance（唯一按 id 查库处） | 可退场（变体实体消失后 provenance 归工序库行） |
| 同上 | `:997-1022` `variantsOf`（6 键去重）+ `:2723-2900` 管理抽屉 | 变体元数据消费点 | 可退场/收归工序库行 |
| 同上 | `:1781-1813` 矩阵表头/行（行头 `:1804 {row.operation}`、副行 `:1794,1805-1811 variant_name`、列 `:1782`） | **部位来自 `cell.position`**（矩阵） | **不动**（目标形态已如此）；行头副行可改拼「逻辑名 · 部位」 |
| 同上 | `:962-966` `cellState()` 三态（`na`/`unpriced`/`priced`）；`:1384-1399` 改价/切「做不做」（寻址用 `cell.id`） | 矩阵写面 | **不动**（目标模型核心） |
| 同上 | `:1035-1038` 空壳路线、`:1953-1961` 适用帘种/主线道数、`:2205-2225` 主线 chip、`:2296` 规则表、`:2596-2635` 新建路线部位勾选 | 展示 | 逐处核（chip 显示逻辑名） |
| `frontend/admin-web/src/lib/api.ts` | `:483` `operations-catalog`、`:486` `routings`、`:501/:507/:559` operations CRUD、`:514/:520` `operation-positions`、`:523-555` rules / routings、`:564` `route-signals`、`:577` `routing-gaps` | 端点与类型 | 端点保留；`operation-positions` 的 6 键中 `variant_*` 系列语义变化。**⚠️ `getRoutingGaps`（`:576-577`）+ `frontend/admin-web/src/types/index.ts:1045-1080` `RoutingGap*` 实测已无页面消费方（死代码）** —— 可独立清理，不在本单 |
| `frontend/admin-web/src/types/index.ts` | `:754-773` `CatalogOperation`（`:757 name`、`:761 position?`）、`:890-909` `OperationPosition` + 6 键（`:898/:900/:902/:904/:906/:908`）、`:793-804` `Routing.mainline`（`:802` 注释明写「**逻辑工序名**的有序序列」） | 类型 | `CatalogOperation.position` 可退场；**`:802` 的注释与前端实际写入的变体名矛盾**（#4609 的契约层裂缝）⇒ 注释/口径必须一起改 |
| `src/app/(dashboard)/production/operations/page.tsx` | 全文 **19 行**，`:18 redirect('/production/routings')`（issue #4416） | 已合并入口 | **不动** |
| `src/app/(dashboard)/orders/**` | `grep -rn "operation" …/orders/ \| wc -l` → **`0`** | **下单页零工序名引用**：只通过 `curtainType`（部位）间接决定取哪条路线 | **不动**（§2.5 的「下单页」一行由此**删除**——实测无影响面） |
| `src/app/(dashboard)/production/piecework/page.tsx` | `:280/:292/:296` `per_operation` 聚合展示 | 计件明细 | 读快照 ⇒ 不动 |

**矩阵读面 6 键（issue #4587 ①）**：`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java:162-180` 产出
`variant_operation_id` / `variant_name` / `unit` / `group` / `scope` / `is_must_finish`。
统一后 `variant_name` 的值 = 逻辑名自身（或整体退场）—— 这是**契约变更**，前端类型与
`frontend/admin-web/tests/unit/pages/production-routings.test.tsx:149-160` 同步改判。

### 2.4 工人端 / 顾客端展示（「拼」的发生地）

```bash
grep -rn "operation_name\|operationName" frontend/ | wc -l
# → 14（**admin-web 0 条**；全部在 bmini-app）
grep -rn "operation_name" frontend/bmini-app/src | wc -l   # → 3
grep -rn "operation_name" frontend/mini-app/src | wc -l    # → 0
grep -rn "operations-catalog\|operation-positions\|/routings\|route-rules" frontend/bmini-app/src frontend/mini-app/src | wc -l
# → 0（两个小程序都**不读**工序库 / 矩阵 / 路线）
```

| 端 / 文件:行 | 读的是什么 | 判定 | 统一后 |
|---|---|---|---|
| `frontend/bmini-app/src/services/productionService.ts:72`（`WorkLogRow` 接口的 `operation_name` 字段） | **报工流水快照**（表 `production_work_logs` 的同名列） | 快照 | **不动**（历史红线）；**新**报工按新名字落 |
| `frontend/bmini-app/src/services/productionService.ts:246` | `GET /orders/{orderId}/operations`（与 admin-web 同端点） | 快照 | 不动 |
| `frontend/bmini-app/src/pages/production/index/index.tsx:69,71` | 报工明细行 `row.operation_name` | 快照 | 不动 |
| `frontend/bmini-app/src/pages/production/index/index.tsx:100-102` `pieceworkOf` | `summary.per_operation.find(item => item.operation === operationName)` **按名字字符串相等配对** | 快照 ↔ 快照 | **不动**（同一来源，必然配得上） |
| `frontend/bmini-app/src/utils/productionOffline.ts:38-39,55,117,151,157` | 离线补传队列 `operationId` / `operationName` | 快照 | 不动 |
| `frontend/admin-web/src/components/production/ProductionProgressTable.tsx:51,84` | `position_name` / `op.operation` | 快照 | **「拼」的候选点之一** |
| `frontend/admin-web/src/components/production/TaskCardPrint.tsx:183,186` | 打印卡片 `positionName` / `op.operation` | 快照 | 同上 |
| `frontend/admin-web/src/components/production/PieceworkTable.tsx:23,57-61` | `per_operation[].operation` | 快照（后端 `ProductionService:888-890`） | 不动 |
| `frontend/admin-web/src/components/chat/ProductionProgressCard.tsx:53-56` | `current_operation` / `pending_operations[]` | **字符串快照**（AI 卡片载荷） | 不动 |
| `frontend/mini-app/src/components/cards/ProductionProgressCard.tsx:26-29,84` | `current_operation` 等 | **ai-agent 下发的快照字符串** | 不动 |

> **关键结论**：工人端与顾客端今天读的**全是快照**，**没有任何一处读工序库**
> （`grep -rn "operations-catalog\|operation-positions\|/routings" frontend/bmini-app/src frontend/mini-app/src | wc -l` → `0`）。
> 所以「改名」对它们的影响面 = **只有新生成的实例**，历史报工列表**逐字不变**。
> ⇒ **要看到 `三边 · 布帘` 这个拼接形态，要改的是实例化写入端（`buildRoute` 的
> `step.put("operation", ...)`）或展示端，而不是工序库。**

### 2.4.1 前端**从未**写过「变体名 → 逻辑名」的转换（实测）

```bash
grep -rn "replace(/-(布|纱)\$/\|endsWith('-布')\|slice(0, -2)" frontend/admin-web/src | wc -l
# → 0（前端没有剥后缀/拼名的推导）
```

唯一一份推导在后端：`backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java:333-335`（`normalizeOperationName`）
与 `:337-352`（`variantNameOf`）。⇒ 前端在统一后**可删的只有「两把尺的查表与并集」**，
且**全部集中在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` 一个文件内**（`libraryByName:868-872` / `knownOps:885-888` /
`libraryById:878-882` / `variantsOf:997-1022` / 管理抽屉 `2723-2900` / 下拉 `2096-2124`）。

**不能删的**（前端必须保留）：`matrixRows:936-943`、`logicalOps:954`、`cellState:962-966`、
`saveCellPrice/toggleCellApplicable:1384-1399`、`frontend/admin-web/src/types/index.ts:890-922` 矩阵读写面契约、
两个小程序的展示组件（它们与命名口径解耦）。

### 2.5 守卫与用例：逐个判定「退场 / 改判 / 保留」

#### 会**退场**的（判据的前提消失）

| 文件 | 判据 | 退场理由 |
|---|---|---|
| `backend/ai-agent-service/tests/test_production/backend/ai-agent-service/tests/test_production/test_route_model_v2.py:282` `test_mapping_is_frozen_verbatim` | 35 条映射逐字冻结 | 旧名不存在了 |
| 同上 `:286` `test_mapping_covers_old_catalog_exactly` | 映射覆盖旧目录 | 同上 |
| 同上 `:300` `test_variant_group_members_map_to_the_group_name` | 变体 → 组名 | 同上 |
| 同上 `:315` `test_variant_groups_are_exactly_the_seven` | 恰 7 组 × 2 变体 | 同上 |
| 同上 `:583` `test_logical_name_mapping_drift_is_detected` | 映射漂移注入红证 | 同上 |
| `backend/admin-api/src/test/.../ProductionOperationQueryServiceTest.java:341` `variantNameOfRoundTripsAllLegacyNames` | 35 条旧名往返可逆 | 同上 |
| 同上 `:371` `variantNameOfReturnsNullWhenVariantAbsent`、`:379` `...FallsBackToClothVariantForCurtainHead`、`:390` `...FallsBackToBareLogicalName` | `variantNameOf` 四步规则 | 函数退场则判据退场 |
| 同上 `:399-404` `normalizeOperationNameIsIdentityForUnknownNames` | 归一函数行为 | 函数退场 |
| `tests/unit_ci_workflows/test_production_catalog_seed.py:449` `test_seed_has_no_duplicate_operation_names` | 种子无重名 | **改判**：统一后重名才是**正确**形态的前身 —— 该判据的**新形态**是「合并后每个逻辑名恰好一行」（见下） |

#### 要**改判**的（判据仍必要，但口径变了）

| 文件 | 判据 | 新口径 |
|---|---|---|
| `backend/ai-agent-service/tests/test_production/test_route_model_v2.py:305` `test_variant_group_shares_group_and_unit` | 同组 group/unit 一致 | 改成「合并判据」：**合并前**同组逐值相同（保留为迁移前置断言）；合并后改成「每个逻辑名恰一行」 |
| `backend/ai-agent-service/tests/test_production/test_route_model_v2.py:328` `test_matrix_is_30_by_4` | 矩阵 30×4=120 | **保留原样**（矩阵不动） |
| `backend/ai-agent-service/tests/test_production/test_route_model_v2.py:453` `test_old_route_truth_source_is_untouched`、`:461` `test_old_build_routing_is_untouched`、`:467` `test_new_truth_source_is_a_second_source_not_a_replacement` | 旧真值源不许动 | **保留**（历史真值），但「second source not a replacement」这句**在新模型下已不成立**（`build_route_v2` 已被 Java 消费）⇒ 需改判措辞 |
| `tests/unit_ci_workflows/test_production_catalog_seed.py:424` `test_seed_matches_python_catalog`、`:490` `test_schema_sql_matches_seed_sources`、`:524` `test_template_matches_python_catalog` | 四源逐行逐值收敛 | **保留**，但**四源的名字全部改成逻辑名**（这是迁移的核心工作量） |
| 同上 `:1332` `test_position_variant_groups_share_group_unit_and_scope` | 同组 scope 一致 | 改判为「合并前置断言」 |
| 同上 `:1232` `test_position_prices_converge_across_three_sources`、`:1249` `test_route_template_converges_across_three_sources`、`:1297` `test_route_rules_converge_across_three_sources` | 新结构三表三源收敛 | **保留**（矩阵/模板/规则不动或只改引用名） |
| `backend/admin-api/src/test/.../ProductionOperationQueryServiceTest.java:418` `logicalNameTableMatchesTruthSource` | Java 表 ↔ `routing.py::_LOGICAL_NAME_PAIRS` 双向一致 | P3 退场（前提消失）；P1/P2 期间**保留**（它是两副本不漂移的唯一护栏） |
| `backend/admin-api/src/test/.../ProductionRoutingCommandServiceTest.java:299` | 「归一口径复用 `normalizeOperationName`」 | 改判为「按名字判重」 |
| `tests/unit_ci_workflows/test_routing_model_p2_consumers.py:419-457`（`test_seed_service_canonical_matrix_matches_truth_source` / `..._mainline_...` / `..._craft_rules_...`） | 播种服务 ↔ 真值源收敛 | **保留**（播种服务仍在），但名字改逻辑名 |
| `tests/unit_ci_workflows/test_fabric_route_seed.py:232` `test_new_operations_are_seeded_for_every_tenant`、`:259` `test_new_operations_carry_unit_price_and_pending_provenance` | 每租户新工序 + 单价/来源 | **保留**（`配料`/`打包` 已是逻辑名，是迁移的样板） |
| `frontend/admin-web/tests/unit/pages/production-routings.test.tsx:149-160` | 6 键变体元数据形态 | 改判（`variant_name` 语义变化） |
| `frontend/admin-web/tests/unit/components/OperationsScopeColumn.test.tsx`、`OperationsProvenance.test.tsx` | 矩阵格 6 键取 scope / provenance | **保留**（矩阵不动），但 `variant_*` 键改判 |

#### 必须**保留**（与命名无关的护栏，一条都不许砍）

| 文件 | 判据 | 为什么必须留 |
|---|---|---|
| `tests/unit_ci_workflows/test_migration_immutability.py` + `migration_fingerprints.json` | 已发布迁移不可改 | 本单要新增迁移 ⇒ **新迁移必须同 PR `--write-ledger` 登记** |
| `tests/unit_ci_workflows/test_migration_references_exist_in_schema.py` | 迁移引用的表/列在 `schema.sql` 里存在 | 改 `position` 列退场时必须同步 `schema.sql` |
| `tests/unit_ci_workflows/test_production_catalog_seed.py:724` `test_seed_sql_is_idempotent`、`:744` `test_price_version_backfill_is_idempotent` | 迁移幂等 | **本单迁移的硬要求**（§4） |
| `tests/unit_ci_workflows/test_production_catalog_seed.py:1596` `test_factor_rules_are_soft_deleted_not_dropped`、`:1626` `test_bootstrap_schema_also_retires_factor_rows` | 软删不物理删 | 同款口径适用本单（**不物理删 `position` 列**，见 §6） |
| `tests/unit_ci_workflows/test_routing_read_endpoints.py` | 矩阵读面键集 | 契约面，改判需同步前端 |
| `backend/admin-api/src/test/.../ProductionOperationDeleteGuardTest.java` | 删工序三道护栏 | 护栏语义保留（改按逻辑名比） |
| `backend/admin-api/src/test/.../ProductionOperationPositionCommandServiceTest.java` | 矩阵写面 + 价格版本账 | **保留**（目标模型核心） |
| `backend/ai-agent-service/tests/test_production/backend/ai-agent-service/tests/test_production/test_piecework.py` | 计件公式 | **保留**（与命名无关） |
| `tests/unit_ci_workflows/test_declaration_truth_guards.py:9` | 注释里的数字不许腐烂 | **保留**（改注释时别写死数字） |

---

## 3. 历史可回溯（红线）

### 3.1 红线内容

| 表.列 | 存的是什么 | 本单动作 |
|---|---|---|
| `processing_position_operations.operation_name` | 实例化那一刻的工序名（今天是 `布三边`） | **一字不动** |
| `production_work_logs.operation_name` | 报工那一刻的工序名快照 | **一字不动** |
| `processing_position_operations.unit_price` / `factor` | 当时单价/系数快照（V61 / #4589 口径） | **一字不动** |
| `production_work_logs.unit_price` / `factor` | 报工时的单价/系数快照（V61） | **一字不动** |
| `production_operation_price_versions.unit_price` | 每次改价的历史 | **一字不动** |
| `production_operation_position_price_versions.unit_price` | 矩阵每格改价的历史（V86） | **一字不动** |

判据（DDL 出处）：

```bash
awk '/CREATE TABLE IF NOT EXISTS processing_position_operations/,/^\);/' docs/sql/schema.sql | grep -n "operation_name"
# → operation_name VARCHAR(64) NOT NULL,
awk '/CREATE TABLE IF NOT EXISTS production_work_logs/,/^\);/' docs/sql/schema.sql | grep -n "operation_name"
# → operation_name VARCHAR(64) NOT NULL,
```

### 3.2 为什么改名不会让历史金额/工序清单漂移（结构性论证）

```
报工/计件读面（ProductionService.aggregate:888-890）
   → 优先 production_work_logs.operation_name（快照）
   → 缺值才回落 processing_position_operations.operation_name（快照）
   → 单价取快照 unit_price，系数取快照 factor
   ⇒ 全链路不查 production_operations、不查矩阵
```

```bash
grep -n "getOperationName\|getUnitPrice\|getFactor" backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java | sed -n '1,20p'
grep -rl "production_operations" backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java
# → 无输出（ProductionService 完全不碰工序库表）
```

Python 侧同款（`piecework.py` 91 行全文只读入参 `instances` / `work_logs`）：

```bash
grep -c "production_operations\|production_operation_positions" backend/ai-agent-service/app/production/piecework.py
# → 0
```

### 3.3 历史可回溯的**验证方式**（可执行）

**V1 —— 行数与金额逐值不变（迁移前后对比）**

```sql
-- 迁移前保存基线（在迁移 PR 的执行说明里附上这两条的输出）
SELECT count(*) AS inst_rows, count(DISTINCT operation_name) AS distinct_names
  FROM processing_position_operations WHERE deleted = 0;
SELECT count(*) AS log_rows, round(sum(qualified_qty * unit_price * COALESCE(factor,1)), 2) AS total
  FROM production_work_logs WHERE deleted = 0 AND work_type = 'normal';
-- 迁移后：两条必须逐值相同（数字不得变、distinct_names 不得变）
```

**V2 —— 历史名字**没有**被改写（这是「一字不动」的判据）**

```sql
-- 迁移后仍必须能查到旧名（若为 0，说明有人顺手 UPDATE 了快照 ⇒ 违约）
SELECT count(*) FROM processing_position_operations
 WHERE deleted = 0 AND operation_name IN ('布三边','纱三边','韩褶-布','精裁-布','布帘车被');
SELECT count(*) FROM production_work_logs
 WHERE deleted = 0 AND operation_name IN ('布三边','纱三边','韩褶-布','精裁-布','布帘车被');
```

> ⚠️ **判据的正确读法**：这两条在**没有历史数据的新库**上返回 0 是正常的（不是违约）。
> 判据形态必须是「**迁移前的值 == 迁移后的值**」（对比，不是绝对值）—— 单看绝对值会假绿。

**V3 —— 单张加工单端到端重放（历史单不变）**

```bash
# 取一张迁移前已完工的加工单，比对迁移前后的「工序清单 + 计件合计」
curl -s "$API/api/admin/production/orders/$ORDER_ID" -H "Authorization: ..." > before.json
# …跑迁移…
curl -s "$API/api/admin/production/orders/$ORDER_ID" -H "Authorization: ..." > after.json
diff <(jq -S '.data.positions' before.json) <(jq -S '.data.positions' after.json)   # 必须空 diff
curl -s "$API/api/admin/production/orders/$ORDER_ID/piecework" | jq '.data.total'    # 必须逐值相同
```

**V4 —— 已落码的确定性断言**（不需要真实 LLM）

| 断言 | 位置 | 判什么 |
|---|---|---|
| `variantNameOfRoundTripsAllLegacyNames` | `backend/admin-api/src/test/java/com/migao/admin/service/ProductionOperationQueryServiceTest.java:341` | 35 条旧名往返可逆（**P3 退场前**是护栏） |
| `test_mapping_is_frozen_verbatim` | `backend/ai-agent-service/tests/test_production/test_route_model_v2.py:282` | 映射逐字冻结 |
| `test_rebuild_matches_frozen_expectation` | `backend/ai-agent-service/tests/test_production/test_route_model_v2.py:224` | 9/9 组合逐字重建 |
| `test_seed_matches_python_catalog` | `tests/unit_ci_workflows/test_production_catalog_seed.py:424` | 四源逐行逐值 |

---

## 4. 迁移与回滚方案

### 4.1 总体口径

| 项 | 口径 |
|---|---|
| 迁移号 | **V88**（当前最大 = V87，复算：`ls backend/admin-api/src/main/resources/db/migration/ \| sort -V \| tail -1`） |
| 不可改已发布迁移 | `MigrationRunner` 按**文件名**记账、已应用整份跳过 ⇒ 一切增量走新文件（`tests/unit_ci_workflows/test_migration_immutability.py` 钉住） |
| 幂等 | `CREATE ... IF NOT EXISTS` / `ON CONFLICT DO NOTHING` / `NOT EXISTS` 业务键去重；**可重复执行**（`bootstrap-first` 栈会在终态库上再跑一遍） |
| 可重入 | 中途失败可重跑；**不依赖「只跑一次」** |
| 两条路径 | ① **存量租户**：新迁移按 `FROM tenants` 循环；② **新建租户**：`docs/sql/schema.sql` 同步终态（bootstrap 栈**不跑迁移链**） |
| 账本 | 新增迁移必须同 PR 跑 `--write-ledger` 登记 `tests/unit_ci_workflows/migration_fingerprints.json`（`tests/unit_ci_workflows/test_migration_immutability.py`） |
| 顺序 | **先处理重复行 → 再改名 → 最后动唯一键口径**（顺序颠倒必撞索引） |

### 4.2 SQL 草案（存量租户）

```sql
-- ═══ V88__unify_operation_names.sql ═══
-- 目标：production_operations.name 从「变体名」统一为「逻辑名」；position 列不再写入（不 DROP）。
-- 幂等 + 可重入：全部 ON CONFLICT DO NOTHING / NOT EXISTS / UPDATE ... WHERE（重复执行为 no-op）。

-- ── ① 旧名 → 逻辑名 映射（**逐条显式写出，不用字符串规则**）──
-- 真值源 = routing.py::_LOGICAL_NAME_PAIRS（35 条）。为何不用 LIKE '%-布' 规则：
--   布三边 / 纱三边（无 - 分隔）、布帘车被（前缀而非后缀）用规则会漏（#4423 §一② 已实证）。
CREATE TEMP TABLE IF NOT EXISTS tmp_op_rename (old_name TEXT PRIMARY KEY, logical_name TEXT NOT NULL);
TRUNCATE tmp_op_rename;
INSERT INTO tmp_op_rename (old_name, logical_name) VALUES
  ('精裁-布','精裁'), ('精裁-纱','精裁'), ('裁剪-布','裁剪'), ('裁剪-纱','裁剪'),
  ('布三边','三边'), ('纱三边','三边'), ('韩褶-布','韩褶'), ('韩褶-纱','韩褶'),
  ('上车布-布','上车布'), ('上车布-纱','上车布'), ('打孔-布','打孔'), ('打孔-纱','打孔'),
  ('拼1次-布','拼1次'), ('拼2次-布','拼2次'), ('拼3次-布','拼3次'),
  ('花边-布','花边'), ('铅坠-布','铅坠'), ('接高-布','接高'),
  ('帘头制作','帘头制作'), ('熨烫-布','熨烫'), ('定型-布','定型'), ('复烫-布','复烫'),
  ('布帘车被','车被'), ('外帘打卷','外帘打卷'), ('外帘装袋','外帘装袋'),
  ('质检','质检'), ('外帘发货','外帘发货'), ('绑带-布','绑带'), ('抱枕','抱枕'), ('腰靠垫','腰靠垫'),
  ('绑带-纱','绑带'), ('logo条-布','logo条'), ('立边-布','立边'), ('扣环-布','扣环'), ('防翘扣-布','防翘扣');

-- ── ② 冲突预检（**先诊断、后改名**；有重复而无法判定存活行 ⇒ 显式中止，不静默挑一行）──
-- 判据（存活行选择顺序，四条依次）：
--   1. 有 processing_position_operations / production_work_logs 快照引用其名字的 → 名字本来就要改，
--      不构成存活判据（快照一字不动）；**存活判据看库内引用**：
--   2. 被 production_route_templates.mainline / production_route_rules.operation 以**该变体名**引用的行优先；
--   3. 其次：production_operation_price_versions 最新版本行最多的（改价史更完整）；
--   4. 再次：id 字典序最小（确定性，可复现）。
-- ⚠️ 实测 7 组内两行 group/unit/unit_price/scope 逐值相同（守卫已钉）⇒ 判据 3/4 只是确定性 tie-break，
--    **不改语义**。
SELECT t.tenant_id, t.logical_name, count(*) AS dup_rows,
       array_agg(t.name ORDER BY t.id) AS names
  FROM (SELECT o.tenant_id, o.name, r.logical_name
          FROM production_operations o
          JOIN tmp_op_rename r ON r.old_name = o.name
         WHERE o.deleted = 0) t
 GROUP BY t.tenant_id, t.logical_name
HAVING count(*) > 1;
-- 预期：7 组 × 每租户（1 号租户 = 7 组）。**空集 ⇒ 该租户已完成本迁移**（幂等）。

-- ── ③ 两阶段改名（**避开 uk_production_operations_tenant_name 的瞬时冲突**）──
-- 阶段 A：全部先挪到临时名（带 'tmp-v88-' 前缀，绝不会与真名冲突）
UPDATE production_operations o
   SET name = 'tmp-v88-' || o.id, updated_at = NOW()
  FROM tmp_op_rename r
 WHERE r.old_name = o.name AND o.deleted = 0;

-- 阶段 B：临时名 → 逻辑名；**同一逻辑名只保留一行**（存活行按 ② 的判据，这里用 id 序确定性实现）
WITH ranked AS (
  SELECT o.id, r.logical_name,
         row_number() OVER (PARTITION BY o.tenant_id, r.logical_name ORDER BY o.id) AS rn
    FROM production_operations o
    JOIN tmp_op_rename r ON r.old_name = replace(o.name, 'tmp-v88-', '')  -- 反查原名的更稳做法见下
   WHERE o.deleted = 0 AND o.name LIKE 'tmp-v88-%'
)
SELECT 1;  -- ← 占位：真实实现必须**先**把「临时 id → 原名」落进一张临时表（见下方「实现注意」）

-- 实现注意（**必须遵守，否则 row_number 的 JOIN 会退化成全表笛卡尔**）：
--   阶段 A 之前先把 (id, old_name, logical_name) 落进 tmp_op_stage，
--   阶段 B 用 tmp_op_stage 而非 replace() 反查。本文件给的是**口径草案**，不是可直接执行的成品。

-- 阶段 C：被合并掉的重复行**软删**（不物理删 —— 与 V72/V73 的软删口径一致，可回滚）
UPDATE production_operations SET deleted = 1, updated_at = NOW()
 WHERE deleted = 0 AND name LIKE 'tmp-v88-%';

-- 阶段 D：存活行写逻辑名
UPDATE production_operations o
   SET name = s.logical_name, updated_at = NOW()
  FROM tmp_op_stage s
 WHERE o.id = s.surviving_id AND o.deleted = 0;

-- ── ④ position 列退场（**不 DROP**，只停写 + 注释登记）──
-- 判据：唯一读点是 ProductionOperationQueryService.operationView（view.put("position", ...)）。
-- 先让读面不再返回该键（一个版本周期），确认无消费者后再考虑 DROP（留待独立迁移）。
COMMENT ON COLUMN production_operations.position IS
    '【已退场，issue #4620】部位只活在 production_operation_positions.position。'
    '本列自 V88 起不再写入；保留仅为回滚与历史可读。';

-- ── ⑤ 存量数据里「被商家手改成变体名」的主线 / 规则也要归一 ──
-- 复现命令：见 §2.1.6 的引用方表。V71/V72 回填产物已是逻辑名，此处只兜「商家后来手改过」的行。
UPDATE production_route_templates t
   SET mainline = COALESCE((
         SELECT jsonb_agg(COALESCE(r.logical_name, e.value) ORDER BY e.ordinality)
           FROM jsonb_array_elements_text(t.mainline) WITH ORDINALITY AS e(value, ordinality)
           LEFT JOIN tmp_op_rename r ON r.old_name = e.value), '[]'::jsonb),
       updated_at = NOW()
 WHERE t.deleted = 0
   AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(t.mainline) e(value)
                JOIN tmp_op_rename r ON r.old_name = e.value);

UPDATE production_route_rules
   SET operation = (SELECT r.logical_name FROM tmp_op_rename r WHERE r.old_name = operation)
 WHERE deleted = 0 AND operation IN (SELECT old_name FROM tmp_op_rename);
UPDATE production_route_rules
   SET after_operation = (SELECT r.logical_name FROM tmp_op_rename r WHERE r.old_name = after_operation)
 WHERE deleted = 0 AND after_operation IN (SELECT old_name FROM tmp_op_rename);
```

### 4.3 SQL 草案（新建租户 / bootstrap 路径）

```bash
grep -n "INSERT INTO production_operations" docs/sql/schema.sql   # → :1947（1 个 INSERT，37 行）
grep -n "INSERT INTO production_operation_positions" docs/sql/schema.sql  # → 2 个 INSERT，120 行
```

**`docs/sql/schema.sql` 必须同步**（bootstrap 栈由 `docker-entrypoint-initdb.d` 执行，
**不跑迁移链** ⇒ 只写迁移 = 全新库仍是旧名，同 #3270 形态）：

1. `:1947` 的 37 行种子改为 **30 行**（`name` = 逻辑名，去掉 `position` 列的值或整列保留 NULL）；
2. 矩阵 120 行**不变**；
3. `:806` 的唯一索引**保持** `(tenant_id, name) WHERE deleted = 0`（统一后它才真正表达「一道工序一个名字」）；
4. `production_operations.position` 列**保留**（不 DROP）+ 注释登记退场；
5. `production-templates/curtain/seed.json` 的 `operation_name` 改逻辑名（与 `schema.sql` 收敛守卫同源）。

### 4.4 回滚方案

| 层 | 回滚动作 | 判据 |
|---|---|---|
| 数据（工序库） | 把软删的 7 行恢复（`deleted = 0`）+ 存活行的 `name` 改回变体名 | 恢复后 `SELECT count(*) FROM production_operations WHERE deleted = 0` 回到 37 |
| 数据（主线/规则） | 反向映射（逻辑名 → 变体名）**不可唯一确定**（`三边` 对应 2 个旧名）⇒ 回滚时**统一改回「布帘变体」**（`三边`→`布三边`、`韩褶`→`韩褶-布`、`车被`→`布帘车被`） | 与 V71/V72 的「帘头回落布帘变体」口径一致 |
| 代码 | 回滚到迁移前 commit（`git revert`） | 新旧名字两态都由 `normalizeOperationName` / `variantNameOf` 兜住 ⇒ **P1 之后才允许 P2 迁数据**（§5） |
| 快照 | **不需要回滚**（从未改动） | §3.3 V2 |

> 🔴 **回滚的前提**：**P1（读面/写面口径统一，不改数据）必须先合并且稳定**。
> P1 期间系统同时容忍两态；P2 迁完数据后，回滚只需恢复数据（代码仍容忍两态）。
> 若跳过 P1 直接迁数据，回滚时**代码已经不认识旧名** ⇒ 只能回滚代码。

### 4.5 `--write-ledger` 登记提醒

```bash
# 新增迁移必须同 PR 登记指纹（否则 tests/unit_ci_workflows/test_migration_immutability.py 红）
python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger   # 实际入口以该文件 --help 为准
# ⚠️ 已登记文件被改 ⇒ exit 1 拒绝重生成（只新增可写）
```

---

## 5. 分阶段落地建议（每阶段可独立合并、可随时停下）

### 阶段总览

| 阶段 | 一句话 | 动数据？ | 动生产代码？ | 可独立合并 | 停止条件 |
|---|---|---|---|---|---|
| **P1** | 统一**读面/写面口径**（不改数据） | ❌ | ✅ | ✅ | 前端不再能把变体名写进主线 |
| **P2** | 迁数据（工序库改名 + 合并 + 引用归一） | ✅ | 少量 | ✅ | 迁移幂等 + 历史逐值不变 |
| **P3** | 删旧名映射与守卫 | ❌ | ✅（净删） | ✅ | 旧名在代码里零引用 |

### P1 —— 先统一口径（**不改数据**）

**做什么**：

1. **前端主线下拉改列逻辑名**（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx`：`:867` `libraryOps` → `:954` `logicalOps`；
   `:2096-2109` 下拉项；`:1101-1105` `addFromPalette`；`:1131` 落库）。
   这是 **issue #4609 的直接修复**（下拉不再给出变体名 ⇒ 不可能写进主线）。
2. **删前端 `knownOps` 并集**（`:884-888`）并让 `missingSteps`（`:1090` → 渲染于 `:2083-2091`）
   真能变红 —— 今天它恒空，正是「预检失效」的机制（§0 第 1 条）。
3. **写面归一并拒收未知名**（`ProductionRoutingCommandService.validateMainline`，`:514-560`）：
   今天的「两态都接受」改成「**只接受逻辑名**，变体名**归一后接受并落库为逻辑名**，未知名 422」。
   ⇒ 存量已存了变体名的主线**不需要数据迁移**也能被正确实例化（新值归一出新名，旧值靠
   `normalizeOperationName` 读时兼容）。
4. **`POST /operations` 同时建矩阵行**（`ProductionOperationCommandService.create`，`:171-226`）：
   修 **issue #4614 的孤儿**。矩阵行的 `applicable` 需商家显式选（**不发明默认**），
   与 `unit_price` 同口径。
5. **矩阵读面 6 键的 `variant_name` 语义**：P1 期间**保持不变**（仍是变体名），
   避免前端与后端契约同时改；P2 后再改判。
6. **`frontend/admin-web/src/types/index.ts:802` 的 `mainline` 注释改口径** —— 它现在写「逻辑工序名的有序序列」
   而前端实际写入的是变体名，这条契约裂缝要随 P1 一起补上（否则 P3 又有人照注释写回旧口径）。

**验收判据（可执行）**：

```bash
# ① 前端：主线草稿里不可能出现变体名（组件测试）
cd frontend/admin-web && npx vitest run tests/unit/pages/production-routings.test.tsx -t "主线"
# 断言：下拉选项集合 == matrixRows 的 operation 集合；addFromPalette 推进的是逻辑名

# ② 后端：变体名写进主线 ⇒ 归一后落库为逻辑名（不 422、不静默丢）
cd backend/admin-api && ./mvnw -q test -Dtest=ProductionRoutingCommandServiceTest
# ③ 后端：变体名在库中不存在对应逻辑名 ⇒ 422 且指名报缺（fail-closed）
# ④ 新增工序后，矩阵读面立刻能看到该逻辑名的行
cd backend/admin-api && ./mvnw -q test -Dtest=ProductionOperationCommandServiceTest

# ⑤ 端到端：主线存变体名 → 实例化不再丢工序（issue #4609 的红证）
cd backend/admin-api && ./mvnw -q test -Dtest=ProcessingOrderServiceTest -Dtest.method="*VariantInMainline*"
```

**停止条件（满足任一条即停下、不开 P2）**：

- 判据 ②/⑤ 出现「静默丢工序」仍无法消除（说明还有第二个丢点）；
- 商家面实测出现「原来能存的主线现在 422」（**回归**）—— 说明归一口径漏了某条旧名；
- `backend/admin-api/src/test/java/com/migao/admin/service/ProductionOperationQueryServiceTest#logicalNameTableMatchesTruthSource` 红（两副本漂移）。

### P2 —— 迁数据（唯一动数据的一步）

**做什么**：§4.2 的 V88 迁移 + §4.3 的 `schema.sql` 同步 + 前端 6 键改判 + 工人端展示拼接（若产品裁定要拼）。

**验收判据**：

```bash
# ① 迁移幂等：连跑两遍结果一致（tests/unit_ci_workflows/test_migration_idempotency.py 会跑）
cd backend/admin-api && ./mvnw -q test -Dtest=MigrationRunnerTest
pytest tests/unit_ci_workflows/test_migration_idempotency.py tests/unit_ci_workflows/test_production_catalog_seed.py -q

# ② 历史逐值不变（§3.3 V1/V2/V3）
# ③ 每租户工序库行数 = 该租户的逻辑名集合（37 → 30 for tenant 1）
psql "$DB" -c "SELECT tenant_id, count(*) FROM production_operations WHERE deleted=0 GROUP BY 1 ORDER BY 1;"
# ④ 无重名（唯一索引仍然有效）
psql "$DB" -c "SELECT tenant_id, name, count(*) FROM production_operations WHERE deleted=0 GROUP BY 1,2 HAVING count(*)>1;"
# → 必须空集

# ⑤ 矩阵 120 行不变
psql "$DB" -c "SELECT count(*), count(DISTINCT logical_name) FROM production_operation_positions WHERE deleted=0;"
# → 120 | 30
```

**停止条件**：

- 判据 ③ 出现「某租户行数不是 30 的倍数/不是 30」（说明该租户有自建工序 —— **这是正常的**，
  判据要改成「该租户活跃工序名集合 == 逻辑名 ∪ 自建名」，**不得**把自建工序当异常）；
- 判据 ④ 非空（唯一键被绕过 ⇒ 停下，不许用「临时改名绕索引」的写法）；
- 判据 ② 任一值变化（**立即回滚**，历史红线）。

### P3 —— 删旧名映射与守卫（净删）

**做什么**：

1. 删 `VARIANT_NAMES` / `variantNameOf` / `normalizeOperationName` / `logicalNamePairs()`（`QueryService`）；
2. 删 `ProductionSeedTemplateService.logicalNames()` + `LOGICAL_NAMES`；
3. 删 `routing.py::_LOGICAL_NAME_PAIRS` / `OPERATION_LOGICAL_NAMES`；
4. 删 `backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture.LOGICAL`（测试夹具副本）；
5. 退场 §2.5「会退场」清单里的判据；改判「要改判」清单里的判据；
6. `buildRoute` 的 `step.put("operation", variant)` 改为逻辑名（**这一步会改新实例的名字**，
   必须在 P2 数据就位后 —— 否则新旧实例名字不一致）。

**验收判据**：

```bash
# ① 旧名在代码里零引用（除历史真值源与文档）
grep -rn "variantNameOf\|normalizeOperationName\|VARIANT_NAMES\|_LOGICAL_NAME_PAIRS\|OPERATION_LOGICAL_NAMES" \
  backend/admin-api/src/main backend/ai-agent-service/app
# → 必须无输出
# ② 旧的 ROUTINGS / build_routing / SPECIAL_OPTION_ROUTINGS 仍保留（历史真值，不许动）
grep -n "^ROUTINGS\|^SPECIAL_OPTION_ROUTINGS\|def build_routing" backend/ai-agent-service/app/production/routing.py
# → 3 行（原样）
# ③ 全套守卫
./verify-all.sh gate && ./contract-check.sh
```

**停止条件**：

- 判据 ① 仍有命中（说明还有消费者）⇒ 停下，补 P2 的引用归一，**不许**用 `@Deprecated` 假装退场；
- 判据 ② 少一行（说明有人顺手删了历史真值源）⇒ 立即恢复。

---

## 6. 风险与「不做」清单

### 6.1 明确**不做**（以及为什么）

| # | 不做 | 为什么 |
|---|---|---|
| N1 | **不回溯历史快照**（不改 `processing_position_operations.operation_name` / `production_work_logs.operation_name`） | 那是当时算钱的证据。改了 ⇒ 历史工资对不上账、审计断链（§3 红线）。**代价**：历史报工列表继续显示 `布三边`（如实登记，不是 bug） |
| N2 | **不物理删 `production_operations.position` 列** | 与 V72/V73/V87 的「软删不 DROP」口径一致；DROP 会挡住回滚，且 `schema.sql` 与迁移链要同时改（`tests/unit_ci_workflows/test_migration_references_exist_in_schema.py` 会红）。先停写 + 注释登记，DROP 留待确认零消费者后的独立迁移 |
| N3 | **不物理删被合并的 7 行** | 软删（`deleted = 1`）保留回滚能力；且 `production_operation_price_versions.operation_id` 可能仍指向它们 |
| N4 | **不删旧真值源 `ROUTINGS` / `build_routing` / `SPECIAL_OPTION_ROUTINGS`** | 它们仍是历史口径的真值（`test_old_route_truth_source_is_untouched` 等已钉住）。删了 = 历史路线无法解释 |
| N5 | **不改 `production_operation_positions` 的 120 行** | 矩阵**已经是目标形态**（逻辑名 + 部位 + 价 + 适用性）。改它 = 白改 |
| N6 | **不给 `POST /operations` 发明默认 `applicable`** | 「该部位做不做」是商家的业务判断；发明默认 = 猜单价/猜工序（issue #4261 同款禁令）。P1 只要求「同时建行 + 必须显式给 applicable」 |
| N7 | **不在本单改任何生产代码/数据/守卫** | 本单是**评估单**（issue 验收判据最后一条） |
| N8 | **不改 `.github/workflows/**` 与 `.agent-presets/**`** | 仓库红线（本机 token 无 `workflow` scope） |
| N9 | **不在 `docs/wiki/INDEX.md` 加索引行** | 实测该索引**不含任何 `docs/design/**` 条目**（`grep -c "design/" docs/wiki/INDEX.md` → `0`）⇒ 加一行是**新造约定**，且会让「design 文档要不要都登记」变成新的漂移面。**最小改动 = 只新增 1 个文件** |
| N10 | **不删 `production_routings`（旧路线表）** | P2 后零消费者，但它是历史路线的载体（与 N4 同款） |

### 6.2 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **唯一键冲突**（7 组重复行） | 迁移报错回滚 | §4.2 的两阶段改名（先挪临时名）+ 冲突预检 |
| R2 | **合并选错存活行** | 价格版本账挂到被软删的行上 | 实测同组逐值相同（守卫已钉）⇒ 选哪行不改语义；判据落成确定性 tie-break |
| R3 | **商家自建工序**（不在 35 条表里） | `normalizeOperationName` 原样返回是**有意设计**（自建工序不得 500）；统一后自建工序名**没有部位后缀**，天然符合目标模型 | 迁移只处理 35 条已登记旧名；自建工序**零动作**。判据：迁移后自建工序行数与名字逐值不变 |
| R4 | **`position` 列停写但仍有读点** | 读面返回 null ⇒ 前端渲染空 | 实测唯一读点 `QueryService:574`；P1 先让读面不再返回该键（前端 `CatalogOperation.position?` 已可选） |
| R5 | **历史报工列表显示旧名**（`布三边`） | 用户观感「怎么还是旧名」 | **有意保留**（N1）。展示层可选择「按当前映射显示」—— 但**只读展示、不写回**；本单不做，登记为后续产品裁定 |
| R6 | **四源收敛守卫同时变红**（`routing.py` ↔ 迁移 ↔ `schema.sql` ↔ 模板 JSON） | 迁移 PR 巨大、易漏一源 | P2 一次性改四源（守卫会逐行逐值报缺）；先跑守卫拿「缺哪一行」清单再改 |
| R7 | **`qty_and_source` 入参名字变化** | 算料数量口径错 | 它按名字查 `OPERATION_CATALOG` 的 `unit`；四源同改后入参自动变逻辑名（`backend/ai-agent-service/app/api/internal.py:309` 唯一调用点，P2 后核一次） |
| R8 | **P1 与 P2 之间的窗口** | 主线里可能同时存在逻辑名与变体名 | P1 的写面归一把新写入统一；P2 的 ⑤ 兜住存量手改行；**P1 必须先合并并稳定**（§4.4 回滚前提） |
| R9 | **前端 `variant_name` 契约变更** | 前端类型/测试同时红 | P2 内一起改；`production-routings.test.tsx:149-160` 与 `frontend/admin-web/src/types/index.ts:880-915` 同步 |
| R10 | **迁移不可变**（改已发布迁移 = 静默缺失） | 存量环境永远拿不到 | 只新增 V88；同 PR `--write-ledger` 登记 |

---

## 7. 附问：统一之后，产品层面最后能「移除条件工序规则」吗？

> 用户原话（2026-09-19）：
> > 「这样改的话**产品层面最后能移除条件工序规则**吧？」

### 7.1 先把两种「移除」拆开（**结论不同**）

| 形态 | 问的是什么 | 结论 |
|---|---|---|
| **A. 移除「产品概念」** | 商家不再看到一张独立的「条件工序规则」表 —— 条件挂到**工序自己身上** | **可行**（本文 §7.4 推荐方案 ②） |
| **B. 移除「能力」** | 彻底不要「按工艺/选项增删工序」这件事 | **不可行** —— 工艺差异（韩褶/打孔/四爪钩/穿杆/平幔）与特殊选项（拼 N 次/花边/铅坠/绑带…）确实会让工序清单不同，**没有别的载体**能表达它。除非把条件改成「每道工序自带适用条件」= **换载体，不是删能力**（与 A 是同一件事的两面） |

⇒ **答案：A 可行，B 不行。**「能移除」指的是**那张表从商家视野里消失**（条件收归工序），
**不是**「不再有条件这回事」。

### 7.2 实测分布（**自己复现，不抄二手数**）

```bash
python3 - <<'PYEOF'
import re, collections
src = open('backend/ai-agent-service/app/production/routing.py', encoding='utf-8').read()
i = src.index('ROUTE_RULES: List'); seg = src[i:]; seg = seg[:seg.index('\n]')+2]
rows = [dict(trigger_kind=m.group(1), trigger_value=m.group(2),
             position=None if m.group(3)=='None' else m.group(3).strip('"'),
             action=m.group(4), operation=m.group(5),
             after_operation=None if m.group(6)=='None' else m.group(6).strip('"'),
             priority=int(m.group(7)))
        for m in re.finditer(r'\{"trigger_kind":\s*"([^"]+)",\s*"trigger_value":\s*"([^"]+)",\s*"position":\s*(None|"[^"]*"),\s*"action":\s*"([^"]+)",\s*"operation":\s*"([^"]+)",\s*"after_operation":\s*(None|"[^"]*"),\s*"priority":\s*(\d+)\}', seg)]
print("total:", len(rows))
print("action:", dict(collections.Counter(r['action'] for r in rows)))
print("(kind, action):", dict(collections.Counter((r['trigger_kind'], r['action']) for r in rows)))
PYEOF
```

**实测输出**（`backend/ai-agent-service/app/production/routing.py` 的 `ROUTE_RULES`）：

```
total: 26
action: {'insert': 21, 'remove': 5}
(kind, action): {('craft', 'insert'): 5, ('craft', 'remove'): 5, ('option', 'insert'): 16}
```

**5 条 `remove` 逐条**（全部是**工艺**触发，没有一条来自特殊选项）：

```
craft=四爪钩 → remove 定型 (priority 50)
craft=四爪钩 → remove 复烫 (priority 60)
craft=穿杆   → remove 定型 (priority 70)
craft=穿杆   → remove 复烫 (priority 80)
craft=平幔   → remove 复烫 (priority 100)
```

⇒ 排除条件只涉及**两道**工序：`定型`（除 四爪钩/穿杆 外都做）、`复烫`（除 四爪钩/穿杆/平幔 外都做）。
`remove` 全为工艺触发 = `True`；`option` 触发的 16 条**全为 `insert`** = `True`。
`insert` 与 `remove` 的目标工序**交集为空** = `None`（即不存在「同一道工序既被插又被删」）。

### 7.3 21 条 `insert`「天然等价于适用条件」吗？—— **基本成立，但有一处不能丢**

**成立的部分**：把 `insert` 挂到工序上就是「这道工序在什么条件下出现」—— 16 个目标工序各有明确条件集：

```
韩褶   ← 工艺=韩褶（插在「三边」之后）
打孔   ← 工艺=打孔（插在「三边」之后）
上车布 ← 工艺=韩褶（插在「韩褶」之后）∪ 工艺=四爪钩（插在「三边」之后）
帘头制作 ← 工艺=平幔（插在「三边」之后）∪ 选项=余料做帘头（插在「三边」之后）
接高   ← 选项=接高 ∪ 选项=双眼皮接高（都插在「精裁」之后）
绑带   ← 选项=余料做绑带 ∪ 布绑带 ∪ 纱绑带（都插在「车被」之后）
拼1次/拼2次/拼3次/花边/铅坠/立边/扣环/防翘扣/logo条/抱枕 ← 各 1 条选项条件
```

**🔴 不能丢的部分（与「挂到工序上」的判断不符的事实，照实写）**：
规则**不只表达「做不做」，还表达「插在哪一道之后」**（`after_operation`）。
而且**同一道工序在不同条件下锚点不同**：

- `上车布`：`韩褶` 条件下插在 **`韩褶`** 之后（priority 20）；`四爪钩` 条件下插在 **`三边`** 之后（priority 40）。
- `接高`：两条都在 `精裁` 之后（一致）；`绑带`：三条都在 `车被` 之后（一致）。
- `帘头制作`：两条都在 `三边` 之后（一致）。

⇒ 「挂到工序上」的等价载体**必须同时带「插入锚点」**（否则 `上车布` 的两种条件会落到同一位置 ⇒
车间按错顺序干；`build_route_v2` 的 docstring 已把「锚点不存在 ⇒ 追加末尾」标为顺序敏感）。
这不是反对 A，而是**A 的必备字段清单里多一列**。

**另一处事实（与「条件只在规则表里」不符）**：触发类型有**第三条路** ——
`processing_item`（加工项触发，issue #4577）的种子行**不在** `ROUTE_RULES` 里，
而在 `backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql`
（`routing.py` 的注释自陈：「`processing_item` 的**种子行不在本表**」）。
复算：`grep -c "processing_item" backend/ai-agent-service/app/production/routing.py` → `5`（全是注释/分支，非种子行）。
⇒ 任何「把规则收归工序」的方案，**必须同时覆盖第三条路的种子**，否则会漏掉加工项触发的一批。

### 7.4 三个可选方案与代价

| # | 方案 | 商家看到什么 | 代价 / 风险 | 可独立合并 |
|---|---|---|---|---|
| **①** | **只改呈现**（数据模型不动） | 「条件工序规则」表**改名/重组**为「工序的适用条件」，仍读同一张 `production_route_rules` | 最小改动；但**表还在**、概念仍分两处（工序库 + 规则表）⇒ 用户问的「移除」**没实现**，只是换了块牌子 | ✅ |
| **②** | **条件变成工序的一列**（推荐方向） | 工序库每道工序自带「适用条件」+「插入锚点」；**独立的规则表从商家视野消失** | 需要：`operation` 侧承载 `trigger_kind/trigger_value/position/action/after_operation`；**必须显式裁定「新增工艺时默认做还是不做」**（见 §7.5）；`processing_item` 第三条路要一起收 | ✅（可分两步：先呈现后承载） |
| **③** | **保留规则表，呈现挂到工序上** | 商家在工序上看到条件（读规则表的投影），底层表仍是唯一真值源 | 概念上「一张表 + 一个投影」；风险最小、可逆；但**表没消失**（对商家是「移除」，对数据模型是「改名」） | ✅ |

**推荐**：**先 ③、再视情况 ②**。
理由：③ 用「呈现层挂到工序」先回答用户的**体验诉求**（商家视野里不再有第二张表），
而**数据模型一字不动** ⇒ 零迁移风险、零历史影响、可随时回退；
② 是 ③ 的自然延续，但它**必须先把 §7.5 的默认值裁定掉**，否则会用「静默少两道工序」换掉一张表。

**为什么现在不做**（范围边界）：

- 本单是**命名统一评估**（#4620），§7 只回答「可不可行」；**不做**规则收敛的实施设计（另一次评估）；
- 本单**不含数据迁移**（§4 的 V88 只做「工序库改名/合并」，**不碰** `production_route_rules` 的行语义）；
- 本单**不含 agent**（不改 ai-agent 的任何行为）；
- ② 的落地必须等 §7.5 的裁定 —— **裁定没下来之前动手 = 猜业务**（与「不发明单价」同一条纪律）。

**什么时候做**：命名统一 P1~P3 走完（工序库一个名字、部位只活在矩阵）**之后** ——
那时「工序」这一侧已经有稳定的一等身份（逻辑名 + 部位矩阵 + 条件），
把条件挂到它身上才有落点；在此之前挂 = 挂在两套键的旧地基上，会重演 #4609。

### 7.5 ② 的**必须显式裁定**项（不能由研发替业务猜）

5 条 `remove` 是**否定条件**（「除 X 外都做」）。挂到工序上之后，会**必然**遇到一个问题：

> **新增一个工艺（如第 6 个工艺词）时，`定型`/`复烫` 默认做还是不做？**

| 口径 | 语义 | 后果 |
|---|---|---|
| **黑名单**（默认做） | 主线里有 ⇒ 默认做；被 `remove` 命中才不做 | **安全**：新工艺拿到完整工序；漏配 = 多两道（可发现、可报工、钱多给一点） |
| **白名单**（默认不做） | 没被条件显式命中就不做 | **危险**：新工艺**静默少两道工序**（工人少干、工资少发，且**不报错**）—— 与 #4609「静默丢工序」同族 |

⇒ **必须裁定**，且本文**推荐黑名单**（与今天 `build_route_v2` 的实际语义一致：
主线全做 → 按规则 `remove` 过滤）。这条裁定**不属于本单**，但它是 ② 的前置。

### 7.6 与上文判断的差异（照实登记）

| 上文判断 | 实测 | 差异 |
|---|---|---|
| 26 条 = 21 `insert` + 5 `remove`；5 条 remove 全是工艺触发 | ✅ **逐值一致**（见 §7.2） | 无差异 |
| 21 条 `insert` 天然等价于「这道工序的适用条件」，挂到工序上**无损失** | ⚠️ **有损失**：规则还带 `after_operation`（插入锚点），且 `上车布` 在不同条件下锚点不同（`韩褶` 后 vs `三边` 后） | **必须多带一列「锚点」**，否则顺序错 |
| 「条件只在规则表里」 | ⚠️ `processing_item` 触发（issue #4577）的种子行**不在** `routing.py::ROUTE_RULES`，而在 `V84__seed_processing_item_route_rules.sql` | 收敛时必须覆盖第三条路 |

---

## 附录 A：一页速查（所有实测命令与数字）

```bash
# 工序库行数（1 号租户）
grep -oE "\('[^']+',\s*[0-9]+,\s*'[^']+'" backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql | wc -l  # 30
grep -cE "^\s*\('op-v56-" backend/admin-api/src/main/resources/db/migration/V56__seed_special_option_operations.sql  # 5
grep -cE "^\s*\('op-v79-" backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql  # 2
# ⇒ 37

# 矩阵行数 / 逻辑名数
grep -cE "^\s*\('opp-v70-" backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql  # 84
grep -cE "^\s*\('opp-v79-" backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql  # 36
# ⇒ 120；distinct logical = 30（python3 复算见 §1.1）

# 旧名对数
sed -n '/^_LOGICAL_NAME_PAIRS/,/^\]/p' backend/ai-agent-service/app/production/routing.py | grep -c '^    ("'  # 35

# 映射表副本数
grep -rn 'private static Map<String, String> logicalName' backend/admin-api/src/main --include=*.java   # 2（生产代码）
grep -rl 'OPERATION_LOGICAL_NAMES' backend | wc -l    # 12（含测试/守卫/文档）
grep -rl 'VARIANT_NAMES' backend | wc -l              # 1

# 旧名在仓库里的足迹
grep -rl '布三边' . 2>/dev/null | grep -v node_modules | wc -l   # 49

# 各端引用面
grep -rl 'production_operations' backend/admin-api/src/main/java | wc -l                       # 15
grep -rl 'production_operations' backend/admin-api/src/main/resources/db/migration | wc -l    # 15
grep -rl 'production_operation_positions' backend | wc -l                                     # 16
grep -rl 'variantNameOf' backend/admin-api/src/main | wc -l                                   # 6
grep -rl 'normalizeOperationName' backend | wc -l                                             # 9
grep -rl 'production_operations' backend/ai-agent-service | wc -l                             # 2
grep -rl 'operation-positions' frontend/admin-web/src | wc -l                                 # 3
grep -rl 'operation_name' frontend | grep -v node_modules | wc -l                             # 3

# 唯一键
grep -n 'uk_production_operations_tenant_name' docs/sql/schema.sql   # :806

# 最大迁移号（新迁移 = V88）
ls backend/admin-api/src/main/resources/db/migration/ | sort -V | tail -1   # V87__retire_factor_route_rules.sql

# §7 附问：条件工序规则分布（自己复现，不抄二手数）
# ROUTE_RULES 实测 total=26 → action={'insert': 21, 'remove': 5}
#   (trigger_kind, action) = {('craft','insert'): 5, ('craft','remove'): 5, ('option','insert'): 16}
#   remove 全为工艺触发；涉及工序恰为 {定型, 复烫}；insert∩remove = 空
grep -c "processing_item" backend/ai-agent-service/app/production/routing.py   # 5（全为注释/分支，非种子行）
```

## 附录 B：与 issue #4620 原文假设不符的事实（逐条照实登记）

| # | issue 原文 | 实测 | 处置 |
|---|---|---|---|
| F1 | 「`production_operations`（36 行）」 | **37 行**（V54 30 + V56 5 + V79 2） | 本文件按 37 |
| F2 | 「`production_operation_positions`（120 行）」 | **120 行** ✅（V71 84 + V79 36） | 一致 |
| F3 | 「35 → 28 合并」 | 35 旧名 → **30** 逻辑名（V71 冻结 28，V79 追加 `配料`/`打包`） | 本文件按 30；V71 的「28」是 V79 之前的快照 |
| F4 | 映射表只有「`VARIANT_NAMES` / `normalizeOperationName`」一处 | 生产代码 **2 份**（`QueryService` + `SeedTemplateService`），测试夹具 **1 份**（`backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture`），真值源 1 份（`routing.py`）= **共 4 份** | §2.1.1 单列；P3 必须四份一起退场 |
| F5 | 「写面拒收逻辑名（编辑主线直接保存 422）」（#4609） | 读码实测 `validateMainline`（`ProductionRoutingCommandService:514-560`）**已同时接受两态**（原样查库 → 查不到按 `variantNameOf` 反查）。⇒ **今天的失效形态是「接受变体名但存下来」**，然后在 `buildRoute:1233-1236` **静默丢工序** | §0 与 §2.1.3 按实测口径写；**#4609 的 422 分支需另行复现确认**（本单未跑商家面） |
| F6 | 工人端要显示「`三边` · 布帘」 | 工人端（bmini-app）与顾客端（mini-app）**读的全是快照**；实测两者对工序库/矩阵/路线端点的引用数 = **0**（`grep -rn "operations-catalog\|operation-positions\|/routings\|route-rules" frontend/bmini-app/src frontend/mini-app/src \| wc -l`）⇒ 拼接只能发生在**实例化写入端**或**展示端** | §2.4 + §6 R5 |
| F7 | 建议在 `docs/wiki/INDEX.md` 加一行 | 该索引 `design/` 条目数 = **0** ⇒ 加行是新造约定 | §6 N9：**不加**，只新增 1 个文件 |
| F8 | 「`position` 列退场」 | 实测唯一读点 = `ProductionOperationQueryService:574`（读面暴露），实例化/计件**不读**它 | §2.1.2：退场低风险，但走「停写 + 注释」而非 DROP（N2） |
| F9 | 「影响面包含下单页」 | `grep -rn "operation" "frontend/admin-web/src/app/(dashboard)/orders/" \| wc -l` → **`0`** | 下单页**零工序名引用**（只通过 `curtainType` 间接决定路线）⇒ §2.3 表内该行已删 |
| F10 | 「前端要改转换逻辑」 | 前端**从未**写过「变体名 → 逻辑名」的推导（`grep -rn "endsWith('-布')\|slice(0, -2)" frontend/admin-web/src` → 0）；唯一实现是后端 `normalizeOperationName:333-335` | 前端可删的只有「两把尺的查表与并集」，全在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` 一个文件（§2.4.1） |
| F11 | — | `frontend/admin-web/src/types/index.ts:802` 的 `mainline` 注释写「**逻辑工序名**的有序序列」，而前端实际写入变体名 ⇒ **契约注释与实现矛盾** | §5 P1 第 6 条：注释与口径必须一起改 |
| F12 | — | `frontend/admin-web/src/lib/api.ts:576-577 getRoutingGaps` + `frontend/admin-web/src/types/index.ts:1045-1080 RoutingGap*` **已无页面消费方**（死代码，实测） | §2.3 表内登记；**不在本单清理**（独立小单） |
| F13 | 附问「21 条 `insert` 挂到工序上**无损失**」 | ⚠️ **有损失**：`ROUTE_RULES` 的行还带 `after_operation`（插入锚点），且**同一道工序在不同条件下锚点不同** —— `上车布` 在 `韩褶` 条件下插在 `韩褶` 之后（priority 20），在 `四爪钩` 条件下插在 `三边` 之后（priority 40） | §7.3：收归工序时**必须多带一列「插入锚点」**，否则顺序错（车间按错顺序干） |
| F14 | 附问「条件只在规则表里」 | ⚠️ `processing_item` 触发（issue #4577）的种子行**不在** `backend/ai-agent-service/app/production/routing.py::ROUTE_RULES`，而在 `backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql`（`routing.py` 注释自陈：「`processing_item` 的**种子行不在本表**」） | §7.3：任何「条件收归工序」的方案必须**同时覆盖第三条路** |
