# 工艺配置去部位化（全链路）设计

> 状态：**实施中** ｜ 日期：2026-09-21 ｜ issue **#4882**（母单）
> 用户裁定逐字（2026-09-21，本会话）：
> 「第三点需要在订单详情/新增订单页面同步增加表单字段」→ 已由 #4876 的展示面补齐；
> 「**工艺配置哪里的 UI&交互都是否重做了？新的工艺不应该配置 布帘、纱帘、帘头这种部位了**」；
> 「**工艺配置（/production/routings）的 UI 与交互本次没重做**」→ 用户选定 **C：连数据模型一起去部位化（大改）**；
> 「**订单要保留，加工需要区分是布还是纱**」；
> 「**连路线层的帘种适用性也去掉**」；
> 合并价取 **布帘价**；
> 「**本会话的需求是除了 Agent 部分，其他全链路都得重新设计&改造，不要偷懒**」。

## 1. 一句话

把「部位（布帘 / 纱帘 / 帘头）」从**配置与生产模型**里彻底拿掉 —— 工序只有一道、价只有一个（取布帘价）、
路线不再按帘种适用性筛选；而**订单行仍记录 `curtainType`**（用户明确「加工需要区分是布还是纱」），
它退化为**加工单上的标识**，**不再参与取价、取路、适用性过滤**。

> ⚠️ 这不是「换个 UI 呈现」，是**数据模型 + 全链路消费面**的改造。凡「按部位分支」的地方都要改。

## 2. 现状：部位落在 5 处（承重面清点，均已核）

| # | 落点 | 形态 | 现状作用 | 目标 |
|---|---|---|---|---|
| 1 | `production_operations.position` + `name` 后缀 | `name` = **变体名**（`韩褶-布` / `韩褶-纱`），`position` = 部位 | 工序库按部位分行 | **一个逻辑工序一行**（`name` = 逻辑名，无后缀）；`position` 列停用 |
| 2 | `production_operation_positions`（V71） | `(tenant, logical_name, position)` → `unit_price` / `applicable` | **计件单价**的唯一来源 + 「该部位做不做」（纱帘不做定型就是 `applicable=false`） | **整表退场**（价回工序库 `unit_price`，取布帘格；`applicable` 约束消失） |
| 3 | `production_route_templates.positions`（JSONB） | 适用帘种集合 | 路线按订单部位筛选 | **停止读写**（列保留、置空） |
| 4 | `production_route_rules.position` | 部位限定 / NULL = 不限 | 条件工序规则按部位生效 | **停止读写**（列保留、置 NULL） |
| 5 | 订单行 `order_items.curtain_type` / 加工单 `processing_position_operations.position_name` | 布帘 / 纱帘 | 取路 × 取价 × 实例化的输入 | ✅ **保留**（用户明确）—— 退化为**标识**，不再参与取价/取路/适用性 |

## 3. 目标模型（口径冻死）

1. **工序**：`production_operations` 一行 = 一道**逻辑工序**（`name` 无部位后缀，如 `韩褶` / `边` / `定型`）。
   `unit` / `group_name` / `is_must_finish` / `is_start_marker` / `scope`（套级 / 件级）/ `unit_price` 全在该行。
2. **价**：`production_operations.unit_price` = **唯一价源**（元/单位）。矩阵不再参与。
   迁移取值规则 = **布帘格价**（用户 2026-09-21 裁定）；布帘格 `applicable=false` 或缺失 ⇒ 用该逻辑工序在库行的既有价；都没有 ⇒ 保留工序库现值（**不猜、不造 0**）。
3. **路线**：`production_route_templates`（默认 + 具名）与 `production_route_rules`（条件工序）**不再按部位筛选**；
   规则的触发维只剩 `craft` / `option` / `processing_item`（`shaped` 仍是预留）。
4. **订单 / 加工单**：`order_items.curtain_type` 原样保留；加工单实例的 `position_name` 原样保留（**加工需区分布/纱**）。
   **明确边界**：部位**不再**影响「做哪些工序」「每道多少钱」。
5. **不追溯**：已生成的加工单与已结算的计件工资**不改**（历史快照即真值）。

## 4. 影响面（全链路清单，逐条都要动）

| 层 | 落点 | 动作 |
|---|---|---|
| DB | 新迁移（V101）：合并价目 → 工序库；变体名塌缩为逻辑名（去重/软删）；`positions` / `position` 列停用（**不 DROP**，可回滚）；登记迁移指纹 | 新增 |
| DB | `docs/sql/schema.sql` bootstrap 终态同步 | 改 |
| Java | `ProcessingOrderService`：取路去部位筛选、取价改读工序库、实例化不再按 `applicable` 过滤（`normalizeOperationName` 的去后缀逻辑改为「名字即逻辑名」） | 改 |
| Java | `ProductionService` / 计件工资 / 部位价目读面（`operation-layers` / `operation-positions` 端点） | 改（读面要么退场要么只读工序库） |
| Java | 路线模板 / 规则的写面校验（部位取值校验 → 去掉） | 改 |
| Python | `app/production/routing.py`：`(部位, 工艺)` 键 → 工艺键；纱帘专属路线/工序镜像退场 | 改 |
| admin-web | 「工艺配置」页**重做**：工艺项 tab 从**矩阵**改为**工序列表**（行 = 工序，列 = 一口价 / 分组 / 单位 / 作用域 / 必完 / 停用）；路线 tab 去「适用帘种」；抽屉去部位限定 | 重做 |
| admin-web | 计件工资 / 生产看板 / 加工单明细：部位列的去留（**显示可留**，配置/取价面不留） | 改 |
| mini-app / bmini-app | 报价卡 / 任务卡的工序展示（若有部位维度） | 改 |
| 用例 / 文档 | 契约账本 + 设计文档 + `cases/*.yml` + 生成物 | 改 |

## 5. 分阶段（每阶段一个 PR，合并串行）

1. **P1 数据库 + Java 域服务**（`ProcessingOrderService` / `ProductionService` / 计件读面 / 端点）——**先落地**，它是契约所有者。
2. **P2 Python 路线数据**（`routing.py` 去部位键 + 其单测）。
3. **P3 admin-web「工艺配置」页重做** + 相关页面去部位列（依赖 P1 的读面口径）。
4. **P4 用例库与文档同步**（含 case-trust burn-down 缴费）。

> P2/P3 可与 P1 并行开发（**按 §3 的冻死口径编码**），但**合并串行**（P1 → P2/P3 → P4）。

## 6. 风险与护栏

- 🔴 **改的是工人工钱**（合并价取布帘价）⇒ 迁移必须**可核对**：迁移脚本内联「合并前 / 合并后」对照（逐工序），并在 PR body 附上种子租户的对照表；**不追溯**已结算数据。
- 🔴 **变体名塌缩有唯一键冲突**（`uk (tenant_id, name)`）：同逻辑名的多行必须**合并**（保留布帘行、软删其余、迁移引用），**不是简单改名**。
- 🔴 **矩阵退场会让「纱帘不做定型」这类约束消失**（用户裁定「连路线层的帘种适用性也去掉」）⇒ 纱帘工序集与布帘**完全一致**；
  这是**用户接受的代价**，但必须在 PR body 与用例里**显式登记**，避免后来人当缺陷修。
- 迁移**不可变**（§18.5）：改已发布迁移走新迁移；新迁移必须 `--write-ledger` 登记。
- 停用的列/表**不 DROP**（可回滚）；读面若不再使用，**先停止读写再另单清理**。

## 7. 验收判据（可执行）

- **L1 机器判据**：迁移前后**逐工序**对照表（布帘价 → 一口价）；`production_operation_positions` 在**新单**链路上**零读**（可用测试断言读面不再调用）；
  `ProcessingOrderService` 的路线派生对**同工艺、不同 `curtainType`** 的订单产出**同一工序序列**（红证：把部位筛选加回 ⇒ 红）；
  计件工资对同一工序**只有一口价**。
- **L1 UI 判据**：工艺配置页**不再出现**布帘/纱帘/帘头（正向断言「工序列表 + 一口价」+ **反向断言**页面无部位列/无适用帘种控件）。
- **§15 真实浏览器走查**：工艺配置页改版后走查（信息层次、几何探针）。
- **用例**：本批改造的每条行为都要有可执行 case（含红证），并缴 case-trust burn-down 预算。

---

## 8. 实施蓝图（2026-09-21 **实测订正** —— 我最初的分包描述在这一段上是错的）

**实测结论**：`backend/ai-agent-service/app/production/routing.py` 里**已经存在**一套 v2 模型
（issue #4423 P1 落地）：`build_route_v2` + `ROUTE_MAINLINE`（**「实际落库的 10 道主线（部位无关）」**，
注释逐字如此）+ `ROUTE_RULES`（工艺/选项触发 insert/remove）+ `OPERATION_POSITION_PRICES`
（由 `_POSITION_PRICE_ROWS` 构造的 **30×4 = 120 行部位价目**）。该 v2 今天**零消费者**
（Java 实例化仍读旧 `production_routings` 与矩阵表）⇒ 它的运行时行为为零。

⇒ 由此订正三件事（**照本节做，不要照 §5 的最初描述做**）：

1. 🔴 **不要去改旧 `ROUTINGS`**（`(部位, 工艺)` 的 9 条展开快照）：它是
   `tests/test_production/test_route_model_v2.py` 的「**9/9 逐字重建**」基线，改它会砸掉那条守卫。
   （本单**一度**按「键收敛为工艺」改过 `ROUTINGS` 并已**回滚** —— 这条弯路如实登记，防后来人重走。）
2. **去部位化的真正落点是 v2 模型**：`_POSITION_PRICE_ROWS` / `OPERATION_POSITION_PRICES`（120 行）
   → **工序级一口价**（取布帘价）；`ROUTE_RULES` 与工序适用性集合
   （如「外帘打卷 / 外帘装袋 / 外帘发货」的 `{布帘, 纱帘, 帘头}`）→ **部位维删除**。
   `ROUTE_MAINLINE` / `build_route_v2` 的取路本身就**部位无关**，无需改。
3. **三源收敛是硬约束**：v2 常量 ↔ `V71__normalize_routing_model_structure.sql` ↔ `docs/sql/schema.sql`
   由 `tests/unit_ci_workflows/test_production_catalog_seed.py` **逐行逐值**守住。而 V71 **已发布、不可改**
   （§18.5 迁移不可变）⇒ 必须：**新迁移把数据改到新终态** ＋ 常量与 `schema.sql` 移到新终态
   ＋ **同步改那条守卫的期望**（它编码的是**旧**终态，属「修好即红」里要改的那一类）。

### 8.1 实际改动清单（按文件所有权分包）

| 包 | 文件 | 动作 | 行为变化 |
|---|---|---|---|
| **A 真值源 + DB** | `backend/ai-agent-service/app/production/routing.py`（`_POSITION_PRICE_ROWS` / `OPERATION_POSITION_PRICES` / 适用性集合）、**新迁移**（`V101+__*`）、`docs/sql/schema.sql`、`tests/unit_ci_workflows/test_production_catalog_seed.py`、`tests/unit_ci_workflows/migration_fingerprints.json` | 价目塌缩为**工序级一口价**（取布帘价）+ 适用性删除 | **零**（v2 仍零消费者）⇒ **可独立安全落地** |
| **B 消费面切换（Java）** | `ProcessingOrderService`（取价改读工序库 `unit_price`、取路不再按部位、实例化不再按 `applicable` 过滤）、`ProductionService`、端点退场（`GET/PUT /operation-positions`、`DELETE /operations/{id}/detach-and-delete`、`POST /operations` 的 `positions`/`skipped_positions`）、`backend/admin-api/src/test/**` | **这才是改运行时行为的包** | **改工人工资** ⇒ 必须带**逐工序对照**＋注入式红证 |
| **C 前端** | `production/routings/page.tsx`（矩阵 → 工序列表一口价；路线 tab 去适用帘种；抽屉去部位限定的「适用条件」）、相关组件与其测试 | 配置面**不再出现**布帘/纱帘/帘头 | 依赖 B 的读面口径 |
| **D 用例 / 文档** | `.github/cases/{processing,processing-order,ui}.yml`（7 条断言 + PG-055 退场）、`CONTRACT-LEDGER`（**已在 P4 分支落**）、`docs/design/**`、生成物 `eval_cases.py` / `mibao-verification-cases.md` | 同步 + **缴 case-trust burn-down 预算** | — |

### 8.2 顺序与两条安全线

```
A（零行为变化，可先合） → B（改钱，必须最小心） → C（依赖 B） → D（用例/文档）
```

1. 🔴 **B 未落地前不要合 C**：矩阵仍在取价 ⇒ 只改前端会让商家「在页面上改价，实际不生效」
   —— 那比不做**更糟**（静默失效）。
2. 🔴 **A 与 B 合并前必须各有一份「逐工序对照表」**（合并前价 → 合并后价），
   并在 PR body 附种子的对照（用户裁定取**布帘价**，不追溯已结算数据）。

---

## 9. 再订正（2026-09-21 第二轮实测）：**价目塌缩根本不需要迁移**，唯一改钱的是「适用性」

读 V71 的**种子数据**与它自己的注释后，两条事实推翻了 §8 里「A 包 = 价目塌缩迁移」的判断：

1. **各部位价逐字相同**。`V71__normalize_routing_model_structure.sql` 建表注释逐字写着：
   > `计件单价（元/单位）… 逐条溯源到 production_operations.unit_price（本单实证：**同一逻辑工序的各部位变体单价逐字相同**）⇒ 不发明单价。`
   数据也对得上（`精裁` 布帘 0.4 / 纱帘 0.4；`上车布` 布帘 0.5 / 纱帘 0.5；`打孔` 0.15 × 3 …）。
   不同部位之间的差异**不在价上，而在 `applicable`**（`熨烫`/`定型`/`复烫`/`车边` 等：布帘 TRUE、纱帘 FALSE、`unit_price` 落 NULL）。
   ⇒ **「取布帘价」= 值不变**：`production_operations.unit_price` 与布帘格本来就相等，**回填是无副作用的幂等动作**，
   不需要一条搬数据的迁移，也不需要改 `_POSITION_PRICE_ROWS` 的**数值**（只需去掉**部位维**）。
2. **钱的变化 100% 来自 `applicable` 消失**：塌缩后「纱帘不做定型/复烫」不再成立 ⇒
   **纱帘订单多做 4 道工序**（熨烫 / 定型 / 复烫 / 车被）⇒ **工钱增加**（用户 2026-09-21 已裁定接受）。
   ⚠️ 对账口径：这一项**不是单价变了**，而是**同一单价 × 更多工序数** —— 迁移对照表要按「**多出的工序列表**」列，
   而不是按「单价前后」列（后者会**全表相等**，看着像什么都没改，是**假对照**）。

### 9.1 修订后的分包（pkg A 基本消失）

| 包 | 动作 | 行为变化 |
|---|---|---|
| **A′ 真值源收敛（可选、可后置）** | `routing.py` 的 `_POSITION_PRICE_ROWS` **去部位维**（价不变）+ `schema.sql` 终态 + `test_production_catalog_seed.py` 期望 | **零**（v2 仍零消费者） |
| **B Java 运行时去部位**（唯一改钱包） | `ProcessingOrderService.buildRoute`（`buildRoute`（`private Map<String, Object> buildRoute(...)`））：① **取价改读工序库 `unit_price`**（值相等 ⇒ 不影响钱）；② **删掉 `applicableByLogical` 过滤**（（符号锚点见相邻代码引用））⇒ 纱帘多做 4 道；③ `variantNameOf` 的调用可保留（名字仍要对上工序库行） | **改工钱**（多做的工序） |
| **B 的桥接（解开死结用）** | `PUT /operation-positions/{id}` 改为**写穿**到 `production_operations.unit_price`（同一逻辑工序全部位同价 ⇒ 写一行即全生效） | 保住商家侧行为：页面改价**仍然生效** |
| **C 前端重做** | 工艺项矩阵 → 工序列表一口价；路线 tab 去适用帘种 | 依赖 B |
| **D 用例/文档** | 见 §8.1 D 行 | — |

### 9.2 为什么加「写穿」这一格（**本条解开了 §8.2 的死结**）

§8.2 原先写着「B 未落地前不要合 C」，但**反过来也成立**：只上 B（取价改读工序库 + 删适用性过滤）而 UI 仍编辑矩阵
⇒ 商家**改价不生效**（矩阵不再被读）—— 那是把一个「能用的功能」改成「静默失效的功能」，比不做更糟。
⇒ 桥接方案：让 `PUT /operation-positions/{id}` **同时写** `production_operations.unit_price`。
于是**任意一侧先上都不会坏**：UI 照旧可用（写穿生效），运行时照旧正确（读工序库）；
C（把矩阵换成工序列表）随后做，只是**换个界面**，不再是「必须先修好才能上」的前置。
⚠️ 写穿必须**同一事务**、且**按逻辑工序取全部位同价**一致地写（不许只写一格而让其它部位留着旧价 —— 那会造出「同工序两个价」的第三态）。

### 9.3 🔴 **B 不能只删过滤：必须与「工序库名塌缩」同批**（否则纱帘订单直接 422）

实测 `ProcessingOrderService.buildRoute` 的实例化链（`buildRoute` 的实例化循环里逐逻辑名走）：

```
variantNameOf(logicalName, position, catalog)   // 逻辑名 × 部位 → 该租户工序库里的变体行
meta == null  ⇒  missing.add(logicalName)       // 调用方据此 fail-closed
```

⇒ **只删 `applicableByLogical` 过滤（`applicableByLogical` 的构造 + 实例化循环里的两处 `continue`）而不改工序库命名**时：

- 纱帘订单的序列里会出现 `定型` / `复烫` / `熨烫` / `车被`（原先被 `applicable=false` 滤掉）；
- 而 `variantNameOf('定型', '纱帘', catalog)` 在工序库里**没有** `定型-纱` 这一行（纱帘过去不做它，从未建行）
  ⇒ `meta == null` ⇒ 进 `missing` ⇒ **fail-closed** ⇒ **纱帘订单根本建不出来**（422/抛错），
  而不是"多做几道工序"。

⇒ **B 的最小正确形态 = 三件一起**（缺一即单砸）：
1. **工序库名塌缩**（`X-布` / `X-纱` → 逻辑名 `X`；同逻辑名多行**合并**、**迁移引用**、软删其余）——
   ⚠️ 唯一键 `uk (tenant_id, name)` 会撞，**不是** UPDATE name；且 `裁剪-*` 与 `精裁-*` 是**两道不同逻辑名**，别合。
2. **`buildRoute` 取变体改为按逻辑名直取**（塌缩后逻辑名即库名；`normalizeOperationName` 保留作存量兼容），
   并删除 `applicable` 过滤（不再有"该部位不做"）。
3. **取价改读 `production_operations.unit_price`**（`buildRoute` 里读 `operationPositions` 的那一处取价）＋ §9.2 的 **`PUT` 写穿桥接**。

⇒ 这条也解释了为什么上一轮「先删过滤」的直觉是错的：**它不会多做工序，它会整单失败**。

---

## 10. 🔴 B 的隐藏依赖（2026-09-21 第三轮实测）：**「未定价」这一个真值只活在矩阵里**

盘点 B 的取价改写时，`ProcessingOrderService.buildRoute` 的 step 装配处有一段**判据级注释**（逐字）：

> 🔴 未定价（格价 NULL）**不得**回落工序库行价（issue #4696，P1）：工序库行价是 `NOT NULL DEFAULT 0`
> ⇒ 回落就把「未定价」变成「真 0 元」（工人白干且无人知道），且与「显式定价 0 元」不可区分。

`docs/sql/schema.sql` 亦印证：`production_operations.unit_price NUMERIC(10,2) **NOT NULL DEFAULT 0**`。

⇒ **「未定价」这个状态只存在于 `production_operation_positions.unit_price IS NULL`**。
而本单要做的恰恰是**让矩阵退场** ⇒ 若不先把 NULL 语义搬到工序库侧，
B 会把**每一道未定价工序静默算成 0 元**（工人白干、且与「显式 0 元」不可区分）——
**正是 #4696 修好的形态，换个地方复发**。这是本单**最危险的一格**，比"多做 4 道工序"严重得多。

### 10.1 修订后的 B 第 ③ 件（拆成两步，缺一即静默归零）

**③a 迁移（新迁移，不可改 V71）**
1. `ALTER TABLE production_operations ALTER COLUMN unit_price DROP NOT NULL;`
   （让「未定价」在工序库侧**可表达**；`DROP NOT NULL` 是**放宽**约束，不动既有数据）
2. 把矩阵里**布帘格的 `NULL`**（= 该工序未定价）**（回）填**为工序库对应行的 `NULL`。
   ⚠️ 这一步要 `logical_name ↔ production_operations.name` 的映射，**不许自己切后缀**：
   `裁剪-*` 与 `精裁-*` 是**两道不同逻辑名**；映射的**唯一出处** = `routing.py::_LOGICAL_NAME_PAIRS` /
   `ProductionOperationQueryService.VARIANT_NAMES`（两者有双向守卫）。迁移里内联这张表时，
   **必须同时加一条守卫**（否则它成为第三份会漂的映射）。
3. **幂等**：`NULL → NULL` 重复执行净效果相同；不得把「显式 0 元」写成 NULL（那是反向错误：
   把"定价 0 元"变成"没定价"）。

**③b 代码**：取价 = 工序库 `unit_price`，**NULL 保持 NULL**（未定价仍显式可见、仍进 `unpriced` 提示），
**不得**用 `getOrDefault(..., ZERO)` 之类的兜底 —— 那正是 ③a 要防的静默归零。

### 10.2 一句话总结三次订正（给下一个执行者）

| 直觉做法 | 实测结论 |
|---|---|
| 「价目塌缩 = 搬数值」 | ❌ 各部位价**本来就相同** ⇒ 数值几乎不用搬；**真正要搬的是 NULL 语义（未定价）** |
| 「删掉 `applicable` 过滤就完事」 | ❌ 纱帘序列里的 `定型` 在工序库**没有** `定型-纱` 行 ⇒ `variantNameOf` 返回 null ⇒ **整单 422** |
| 「直接把取价改读工序库」 | ❌ 工序库 `unit_price` 是 `NOT NULL DEFAULT 0` ⇒ **每道未定价工序静默变 0 元（工人白干）** |

⇒ B 的最小正确形态 = **① 工序库可表达 NULL（迁移）＋ NULL 语义回填** ＋
**② 变体解析按逻辑名回落**（消 422） ＋ **③ 取价改读工序库且不兜底** ＋
**④ `PUT /operation-positions/{id}` 写穿**（保住商家侧改价仍然生效，解开 B/C 互锁）。
**四件同批**，缺任意一件都会以「静默」的方式出错（归零 / 422 / 改价不生效），而不是报错。
## 11. 第四轮实测（**落地实测 —— 本节即本批交付形态**，覆盖 §9.1/§9.2/§9.3 与 §10）

> §10 提出的「不换价源、否则未定价静默归零」这条红线，**本批直接照做**：价源仍是矩阵
> （只塌缩成一口价）⇒ 该风险不成立，不需要 ③a 的迁移与 `DROP NOT NULL`（见 §11.4）。
（2026-09-21 夜，**本批实际交付形态**）—— 覆盖 §9.1/§9.2/§9.3

把「删 `applicable` 过滤」真正落地后跑全量单测，**仓库里已有的守卫当场把它判红**。
本节记录实测读数与据此定下的**已交付形态**；§9.1 的 B 行、§9.2 的写穿、§9.3 的三件套**均已被本节覆盖**。

### 11.1 🔴 「删适用性过滤」被三条既有守卫拦下（不是猜测，是红证）

| 判据 | 去掉 `applicable` 过滤后的读数 |
|---|---|
| `ProductionRouteParityTest#skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute` | **变红**。这条用例的名字就是它的判据：**注入式**证明「去掉过滤 ⇒ 纱帘单要么带上布帘专属的 熨烫/定型/复烫/车被、要么整单 fail-closed」，两条路都不是旧结构行为 |
| `ProductionRouteParityTest#allNineCombinationsRebuildTheLegacyRoutesVerbatim` | **变红**：9 条老路线的**逐字重建**不再成立 |
| `ProductionRouteParityTest#instantiationSequenceIsUnchangedForTheCanonicalRuleConfig` | **变红**：同一套规则配置下序列逐项不变也不成立 |
| `ProcessingOrderServiceTest` | **40 条**用例的工序数期望改变。典型读数：`打包` 在**布帘列**本是 `applicable = false` ⇒ 去掉过滤后**布帘单多出「打包」**（11 → 12 道） |

⇒ **结论**：`applicable`（该部位做不做这道工序）是价目矩阵的**数据层**约束，与「商家在配置面上看到部位」是两件事。
它**本批保留**；要把它也去掉，必须**同时裁定退休上面那 3 条守卫**并逐条重写那 40 条期望 —— 那是独立的一单，
不在「工艺配置去部位化」的授权范围内（**登记为开放项**，见 §12）。

### 11.2 规则级 `position`（部位限定）同样**保留**

`production_route_rules.position` 与「**路线层的帘种适用性**」（`production_route_templates.positions`）**不是**同一件事：
前者是**单条规则**的部位限定（V71 种子里只有 1 条：`韩褶 × 布帘 → insert 上车布`）。
实测去掉它后：`ProductionRouteParityTest` **3 条判据里 2 条变红**，且该规则开始对**帘头**单生效
⇒ 帘头主线上多出一道它本来不做的 `上车布`（**错发计件工资**）。
⇒ 保留筛选；配置面（「工艺配置」）不再暴露该字段，存量行的值继续生效。

### 11.3 ✅ **不加迁移**：价目塌缩只在代码里做

V71 的矩阵种子是 `routing.py` ↔ `V71` ↔ `docs/sql/schema.sql` **三源收敛**的冻结产物
（守卫：`tests/unit_ci_workflows/test_production_catalog_seed.py`），而 **bootstrap 路径不跑迁移链**
（`docs/sql/schema.sql` 就是全新库的**终态**种子，`deploy/docker-compose.yml` 把它挂成 initdb 脚本）。
⇒ 在迁移里软删种子行会让 **bootstrap 终态**与**迁移链终态**分叉 —— 而那正是既有守卫要防的形态。
⇒ 收敛改在**三个取用侧共用的唯一一处**实现，物理行一字不动：

| 落点 | 改动 |
|---|---|
| `ProductionOperationQueryService#collapseToLogical`（新增，**唯一**收敛实现） | 同一 `logical_name` 的多行收敛为一行：**`applicable = TRUE` 优先** → 其中**布帘列**优先（用户裁定「取布帘价」）→ `position` 字典序 → `id` 升序。**只选行、不回落** |
| `ProductionRoutingReadService#operationPositions`（读面） | 返回**一道逻辑工序一行**（原 120 行 ⇒ 30 行）；`GET /operation-positions` 从此就是「工序一口价」 |
| `ProcessingOrderService#buildRoute`（实例化） | 取价走 `collapseToLogical`；`applicable` 过滤**保留**（见 §11.1） |
| `ProductionInstanceRepricingService`（补价） | 键从 `(部位,逻辑工序)` 塌缩为 `逻辑工序`；`position_kind` 的存在性**仍是前置**（不追溯、不扩大补价射程） |

**值不变**（§9 的读数：同一逻辑工序各部位单价逐字相同）⇒ 本批是**结构性去部位**，不改任何一笔工钱。

### 11.4 §9.2 的「写穿桥接」**不再需要**（更省、且避开 #4696）

§9.2 的桥接成立于「取价改读 `production_operations.unit_price`」这个前提。
本批**不换价源**（价仍取自矩阵，只是塌缩成一口价）⇒ 商家在配置面改的**就是**运行时读的那一行，
**不存在「改价不生效」的窗口** ⇒ 桥接整格取消。
这同时避开 §9.3 第 3 条与 §10 的另一处红线：`production_operations.unit_price` 是 `NOT NULL DEFAULT 0`，
换成它会把**未定价**静默变成 **¥0.00**（工人白干、无人知道，#4696）。

### 11.5 试过又回滚的一处：`variantNameOf` 的「布帘列回落」

为解 §9.3 的「纱帘单 422」曾加过一条「本部位无变体 ⇒ 回落布帘列」的回落。
实测它**直接抵消** `MainlineOperationReferenceTest#droppingACurtainHeadEntryMakesTheCellLevelGuardRed`
（#4777 的逐格守卫：删一条帘头条目必须让该格解析不到）。收窄到「帘头除外」后守卫可保，但：
`applicable` 过滤已保留（§11.1）⇒ 那份 422 风险**不存在**于主线路径，
而它**能**触发的场景是「规则插入的工序在纱帘无变体」（如 `拼1次 × 纱帘`）—— 那是**另一条**既有缺陷，
不该夹在去部位化里**顺手**改掉（会悄悄把布帘变体名泄露进纱帘单）。
⇒ **本批回滚该回落**，把「纱帘 + 选项插入工序 ⇒ 变体解析 422」**登记为开放项**（§12）。

---

## 12. 开放项（本批**未做**，需单独裁定）

| # | 开放项 | 为什么不在本批 | 需要什么才可做 |
|---|---|---|---|
| O1 | 去掉 `applicable`（部位适用性）过滤 ⇒ 纱帘单多做 熨烫/定型/复烫/车被 | 被 3 条守卫拦下（§11.1）；改的是**工钱** | 用户裁定接受该代价值 + 退休 `ProductionRouteParityTest` 那 3 条判据 + 重写 40 条期望 + 补对账口径 |
| O2 | 去掉规则级 `position` 限定 | 会让 `韩褶×布帘 → 上车布` 对帘头单生效（§11.2） | 先把该规则的部位语义改挂到别处（如按部位拆主线/拆模板） |
| O3 | 纱帘单 + 选项插入「纱帘无变体」的工序（如 `拼1次`）⇒ 变体解析 422 | 与去部位化正交的既有缺陷（§11.5） | 单独 issue；修法要在「补纱帘变体行」与「显式列回落」之间裁定 |
| O4 | 矩阵物理行去部位（真删 120 → 30 行） | bootstrap 不跑迁移链 ⇒ 删种子行会造成终态分叉（§11.3） | 先把「种子源」从 V71 迁到一条**新增**迁移 + 同步 `schema.sql` 终态 + 三源守卫改指向新源 |

---

## 13. 第五轮：**彻底版**（2026-09-21，issue #4937 / #4951 —— 本节覆盖 §11 与 §12 的开放项）

> **用户裁定逐字**：「我们移除了部位的设计，**不计成本的改**」（2026-09-21）。
> 本节记录**落地形态**（#4951，分支基点 `7e53078a3`）与它**付出了什么代价、退休了哪些守卫**。
> ⚠️ §11 是**当时的**交付形态（部位退场、`applicable` 保留），**已被本节覆盖**；
> §12 开放项的 O1 / O2 / O4 **本批全部关闭**（O3 仍开，见 §13.5）。

### 13.1 四件（本批实际交付）

| # | 件 | 落点 | 形态 |
|---|---|---|---|
| **O1** | **适用性退场** | `V102__retire_applicability_flag.sql` + `ProductionOperationPositionCommandService` + `ProcessingOrderService` | 迁移抹掉该旗标，`V104` 把存活行一律置 `applicable = TRUE`；**写面只收 `{unit_price}`** —— body 里出现 `applicable` ⇒ **422 + 可行动 hint**（「部位适用性已退场，不再受理该字段」），**拒绝**而非静默忽略；与 `unit_price` 同传 ⇒ **整份拒绝**（价也不落库）。原「适用性过滤」在取价/实例化路径**整块删除** |
| **O2** | **规则级 `position` 退场** | `V103__clear_route_rule_positions.sql` + 规则读取路径 | `production_route_rules.position` 全 `NULL`、**不再参与筛选**（键仍在读面契约里，配置面早就不暴露它） |
| **O4** | **矩阵物理去部位** | `V104__deposition_matrix_collapse.sql` | `production_operation_positions` 塌缩为**每逻辑工序一行**（120 → 30），幸存行 `position := '通用'`（该列**仅作历史载体**）、`applicable := TRUE`；终态核验内置（存活行不得再有 `applicable IS NOT TRUE`） |
| **P2** | **真值源去部位** | `backend/ai-agent-service/app/production/routing.py` + `V105__add_sheer_variant_operations.sql` | 真值源 `OPERATION_POSITION_PRICES` 去部位；**V105 补 4 行纱帘变体**（`熨烫-纱` / `定型-纱` / `复烫-纱` / `车被-纱`，单价逐字取对应 `-布` 变体）—— 否则纱帘单在 `variantNameOf` 处解析不到变体 ⇒ `missing_operations` ⇒ **一张纱帘单也建不出来** |

### 13.2 连锁形态（取用侧与读面的终态）

- **读面 `GET /operation-positions`**：10 键**一字不变**（`id` / `operation` / `position` / `unit_price` / `applicable` / `variant_operation_id` / `unit` / `group` / `scope` / `is_must_finish`）——
  其中 `position` **恒 `通用`**、`applicable` **恒 `true`**。⇒ **两个键都还在契约里，但都**不再是配置概念**；web 面不得渲染它们。
- **收敛规则**（`ProductionOperationQueryService#collapseToLogical`）：原「`applicable = TRUE` 优先 → 其中**布帘列**优先 → `position` 字典序 → `id` 升序」里的**前两条失去输入**，
  剩下仍可判定的 = **`position` 字典序 → `id` 升序**（且 #4951 之后每个逻辑名本就只有一行）。前端 `pickConvergedCell` 同步收敛为同口径（**只选行、不回落**）。
- **价源仍然不变**：价取自价目行，**没有**改读 `production_operations.unit_price`（那是 `NOT NULL DEFAULT 0` ⇒ 会把「未定价」静默变成 **¥0.00**，#4696 未复发）。
- **`GET /operation-layers` 的 `delivery` 段**：**9 键契约不变**，但第 4 态 `no_applicable_position`（「一格『做』都没有」）**退场** —— 存活行 `applicable` 恒 `TRUE` ⇒ 该状态**不可达**，
  零格与「一格未定价」**同判 `unpriced`**；`applicable_positions` **键保留但恒 `[]`**。

### 13.3 退休了哪些守卫（**逐条留痕，不许静默删**）

| 守卫 / 判据 | 处置 | 理由 |
|---|---|---|
| `ProductionRouteParityTest#skippingApplicabilityFilterWouldLeakClothOnlyOperationsIntoSheerRoute` | **退休**，由新判据取代（同文件有显式注释登记） | 它是「**别去掉 applicable 过滤**」的注入式守卫；用户裁定去掉 ⇒ **判据的前提消失**（不是"修好了所以删掉"） |
| `ProductionOperationPositionCommandService` 的 `variantOperationOf`（#4798「结果态 `applicable=true` 必须解析得到变体」） | **退休**（源码内有显式注释） | 判据的**输入**（`applicable`）不复存在；「能解析出变体」这件事**下沉**到实例化侧 `ProcessingOrderService#buildRoute` 的 `missing_operations` **fail-closed** 兜底（指名报缺、整单中止） |
| `ProductionRouteParityTest` 的「9 条老路线逐字重建」/「序列逐项不变」两条 | **按新口径重写** | 纱帘单**确实**多出 4 道（见 §13.4），旧期望已不是真值 |
| `ProcessingOrderServiceTest` 的 **40 条**工序数期望 | **按新口径重写** | 同上 |
| 用例库 `PG-055`（部位价目矩阵**写面**不变式） | **改判**（未退休、未静默删） | 主体改判为「写面**字段契约**」：只收 `unit_price`、`applicable` 收到即 422（含同传整份拒绝）、价的两态/留痕/校验逐条照旧，并显式登记能力已下沉到实例化侧兜底 |
| 用例库 `PG-054` 判据 2 / `UI-049` 判据 3 / `UI-050` 判据 1·2·4 / `PP-014` 两处 | **改判**（判据面缩小、不放宽） | 三态 ⇒ 两态（`na` 不可达）/ 4 态 ⇒ 3 态 / 收敛规则事实订正；「未定价 ≠ ¥0.00」「真 0 元照显示」与各反向护栏**一字未动** |
| 前端 `OperationPosition.applicable` / `OperationPositionUpdateParams.applicable` / `cellState` 的 `na` 分支 / 「不做」呈现 / `pickConvergedCell` 的两条平局规则 / `applicable_positions` 的逐部位用法 | **删除**（#4939） | 字段已退场且**恒真** ⇒ 判据没有输入、界面没有对象；反向断言「`na` / 『不做』不得出现」补位（**不是**放宽） |

### 13.4 代价（**已发生**，逐条留痕）

- 「**纱帘不做定型/复烫**」这条**部位级**约束消失 ⇒ 纱帘单**多做 4 道**（`熨烫` / `定型` / `复烫` / `车被`）。
  **对账口径**：必须按「**多出的工序列表**」列，**不是**按单价前后（同一逻辑工序各部位单价逐字相同 ⇒ 按单价前后会全表相等 = **假对照**）。
- 存量行的「**当年哪一格是 `applicable = FALSE`**」这一信息**被 V102 抹掉，不可回滚复原**（V104 的回滚注释里如实登记）。

### 13.5 开放项收口（对照 §12）

| # | 状态 |
|---|---|
| O1（去掉 `applicable` 过滤） | ✅ **已关闭**（本批；代价值已由用户裁定接受，见 §13.4） |
| O2（去掉规则级 `position` 限定） | ⚠️ **关闭已撤回**（2026-09-21 后续裁定，见 §14.2）—— #4962 恢复规则级部位语义、V103 随 #4936 重写包删除 |
| O3（纱帘 + 选项插入「纱帘无变体」的工序 ⇒ 变体解析 422） | ⚠️ **仍开**（与去部位化正交的既有缺陷，需单独 issue；V105 只补了那 4 道，未覆盖该路径） |
| O4（矩阵物理行去部位） | ✅ **已关闭**（本批 V104；终态核验内置） |

### 13.6 仍开 / 如实登记（不粉饰）

- **`applicable` 列本身仍在库里**（只是恒 `TRUE`）—— `DELETE /operations/{id}` 的**护栏③**与 `…/detach-and-delete`（一键「设为不做并删除」）**本批未退休、照旧可用**：
  判据 `matchingCells × applicable` 里 applicable 恒真 ⇒ 实际退化为「该工序在价目表里还有存活行」；§11 O1 原先「一键端点随之退场」的**预期不成立**。
- **前端仍写「设为不做」文案**：那是后端同一事务里的**内部动作**（把该列置 false），前端自 #4939 起**不持有**该字段、也不据此判路径。
- **`position` 键仍留在两处读面契约里**（`operation-positions` 的 10 键 / `operation-layers` 的 `operations` 段同形）—— 值为 `通用`，
  属**历史载体**；删键是独立的一次契约变更（会同时影响 `tests/unit_ci_workflows/test_routing_read_endpoints.py` 的冻结键集与多处测试），**本批不做**。

## 14. 第六轮：商家写面收口（2026-09-21，issue #4960 / #4961）

> 与 §13 **正交**的一面：§13 去的是**部位维**，本轮去的是商家写面上的**两个配置项**（作用域 / 必完）。
> 两者都不动 DB 语义、不动冻结键集 —— 与 §13「列保留、值恒定、读面不消费」是**同一套退场范式**。

### 14.1 交付形态

| 面 | 处置 | 判据（可核） |
|---|---|---|
| 抽屉「作用域」控件（`variant-scope-*`） | **退场**（`SCOPE_META` / `SCOPE_ORDER` / `scopeOf` 一并删；引言不再解释「按套 / 按件」） | `tests/unit/components/OperationsScopeColumn.test.tsx` #4960-②/③ + `tests/unit/pages/production-routings.test.tsx` #4960-①（负态断言 + **写请求里没有 `scope` 键**） |
| 后端 `scope` 语义 | **一字未动**（#4960 那一个提交里 `backend/` 文件计数 = 0） | `ProductionOperationCommandService` 仍受理 `scope`；`ProcessingOrderService#keepsSetLevel` 未动（动它 = 布+纱一樘双付工钱） |
| 「必完」（`is_must_finish`） | **概念整体退场**：完工判据 = **全部活跃工序实例 `isDone`** | Java `ProductionServiceTest#unfinishedNonMustFinishOperationBlocksCompletion`（含绿侧配对）+ Python `test_is_production_done_rejects_unfinished_non_must_finish_operation`（改前实测 `assert True is False`，含绿侧配对） |
| 主线护栏「至少 1 道必完工序」 | **删除**（五条 ⇒ **四条**） | `ProductionRoutingCommandServiceTest`「护栏 4 退场 ⇒ 照常保存成功」+ 反向「退场后**不得**回退成零校验」 |
| 写面 `is_must_finish` | **出现即 422 + 可行动 hint**（POST + PUT） | 沿用 #4641 `name` 的「出现即拒」范式，**不静默落库** |
| 列与读面键 | **保留**（`POSITION_KEYS` 10 键 / `DELIVERY_KEYS` 9 键相对 `origin/main` **零 diff**），`is_must_finish` **值恒 `false`** | `tests/unit_ci_workflows/test_routing_read_endpoints.py` 零 diff |
| 数据收敛 | **新增 `V107`**（显式事务 + 幂等谓词 `IS DISTINCT FROM FALSE` + 终态对账 `DO $$` + 回滚与不可复原项登记）；**不碰**三张快照表与软删行 | `tests/unit_ci_workflows/test_must_finish_retire_migration.py` + `migration_fingerprints.json` |
| 文档真值源 | `docs/wiki/CONTRACT-LEDGER.md` **六处锚点**同步（护栏五⇒四、两个写面 body、三处读面键的「值恒 false」） | 本节 + 账本对应行 |

### 14.2 O2 的状态撤回（本轮唯一的「开放项反悔」，逐条留痕）

§13.5 里那行「O2 ✅ 已关闭（本批 V103）」**不再成立**：用户 2026-09-21 后续裁定把口径改成
「**DB 层的改造需要彻底，结合新的需求适用条件增加部位选项，统一考量**」⇒ **规则级** `position`（部位限定）
**保留并升格**为「什么时候做」的第四个维度（issue #4962 承接），V103 随 #4936 的 V102 重写包**删除**。
⇒ 读到 §13.5 那一行的执行者请以本节为准。**这不回滚 §13 的去部位化**：矩阵一口价、`applicable` 退场、
价目行 `position` 恒 `通用` 三件照旧；回来的只有**规则级**的部位语义（它从来不在矩阵里）。

### 14.3 如实登记（不粉饰）

- `V107` 的 issue 正文写「按租户循环」，实现用**全局一条 UPDATE**：该列是**全局目录属性**、终态对全部租户同构
  ⇒ 全局写法覆盖面**严格更大**（含未来租户与 `tenants` 表缺席的行）；理由写在迁移文件头，覆盖面由文末**终态对账**机械核验。
- 「实例显示 `逻辑名 · 部位`」本轮只核了**加工单页**；工人端 / bmini / mini-app 的**面级**一致性未全量核查 ⇒ 跟随单 **#4963**（登记，不谎报闭环）。
- `is_must_finish` / `applicable` / `position` 的**物理删列**仍不做（=「值恒定 + 读面不消费」的已退场语义），留待统一审计批次。

---

## 14.4 落码形态订正：O2 的**部分**回退（2026-09-21，issue #4962）

> ⚠️ §14.2 里那句「**V103 随 #4936 的 V102 重写包删除**」**不是实际形态** —— 定稿时 V103 已发布并被
> `tests/unit_ci_workflows/migration_fingerprints.json` 按 sha256 **逐字节冻结**，**不可改、不可删**
> （`MigrationRunner` 按**文件名**记账、已应用文件整份跳过 ⇒ 改它只对全新库生效 = 「CI 全绿、功能静默缺失」，
> issue #4235 同族）。本节记录**真正落地的形态**，读完以本节为准（§14.2 保留为**当时的裁定记录**，不删）。

### 14.4.1 交付形态（逐件可核）

| # | 件 | 落点 | 形态 |
|---|---|---|---|
| **1** | **存量库写回**（新迁移，不改 V103） | `backend/admin-api/src/main/resources/db/migration/V108__restore_route_rule_positions.sql` | 把 `V71` 种子里**唯一**那条部位限定写回：`韩褶 → insert 上车布`，`position='布帘'`。显式 `BEGIN/COMMIT` + **按租户循环** + 幂等谓词（只写 `position IS NULL` 的行）+ 终态对账 `DO $$` + 回滚 SQL 与不可复原项登记；**只写** `position` / `updated_at`（`customer_unit_price` 一字不动、规则行数不变）。**净效果**：`V103`（清空）→ `V108`（写回那一条）= 对 `V71` 字面量**恒等** |
| **2** | **触发类型闭词表放开**（新迁移） | `backend/admin-api/src/main/resources/db/migration/V109__allow_position_trigger_kind.sql` | `V71` 的内联 `CHECK (trigger_kind IN ('craft','option','shaped','processing_item'))` **不含** `position` ⇒ 第 4 维在**界面上选得动、提交必 500**（`23514`）。本迁移按 `pg_get_constraintdef` 定位并重建该约束（幂等：已含 `position` ⇒ 空操作），**只改约束、不碰任何数据**（无 `INSERT/UPDATE/DELETE`）。**不复用 `shaped`** —— 它是「是否定型」，是另一件事，且 `buildRoute` / `routing.py::_rule_triggers` 对它的口径是「未实现 ⇒ 显式 422」，复用会抹掉这条纪律的载体 |
| **3** | **实例化侧恢复筛选** | `ProcessingOrderService#buildRoute` / `#insertConditionalOperations`（新增 `#rulePositionMatches`）+ 真值源 `backend/ai-agent-service/app/production/routing.py::_rule_position_matches` | `position` 为空 / `NULL` / 缺键 = **不限部位**；否则**逐字**匹配当前实例化部位。**排除点必须在触发类型分派之后** ⇒ 未知/未实现触发类型照旧 **422 显式失败**（不因部位不匹配就静默跳过）；`insertConditionalOperations` 的触发判定同时补上**对未知类型的显式失败**（此前它对未知 kind 静默返回 `false` = 规则落库但永不生效的黑洞），并**保留 `craft` 档返回 false** 的既有语义（craft 由 `buildRoute` 统一处理，在此处返回 false 是「不重复插入」而非「未实现」—— 搞错这一点会让**每一张单实例化都 422**，本单实测踩到过） |
| **4** | **配置面加回部位维** | `POST /route-rules`（`ProductionRoutingCommandService`）+ `GET /route-rule-options`（`ProductionRoutingReadService#triggerOptions`）+ 前端 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` | `trigger_kind` 闭词表加第 4 档 `position`；`trigger_value` 与 body 的 `position` 键都过**部位闭词表**（`ProductionOperationQueryService.POSITION_LIMIT_VOCABULARY` = 基线三部位 ∪ 第 4 个部位 `布料`，**同一份常量**、不另抄）；`trigger_kind='position'` 时 `position` 由 `trigger_value` **镜像**（不一致 ⇒ 422）；读面 `positions` 键把闭词表交给前端（**不得**硬编码） |
| **5** | **开租种子同值** | `ProductionSeedTemplateService#CRAFT_RULES` | 新租户播种的 `韩褶 → 上车布` 也写成 `position='布帘'`（与迁移链终态同值；**不得**只改迁移链而让新租户拿到「不限部位」的另一套语义） |
| **6** | **三源收敛判据改判** | `tests/unit_ci_workflows/test_production_catalog_seed.py` / `test_routing_model_p2_consumers.py` / `test_routing_read_endpoints.py` | 比对键**含** `position`（#4937 期间那条「归一掉该维」的投影**撤销** —— 它会让判据对「部位限定存不存在」零判别力）；`test_rule_positions_are_cleared_in_every_terminal_source` 改判为 `..._restored_...`（四方：真值源 / `schema.sql` / `V71` 字面量 / **`V108` 迁移**） |

### 14.4.2 代价与边界（**如实登记**）

- **不再有「同一工艺在任何帘种上同一套工序」这条不变量**（#4937 的判据之一）：纱帘 / 帘头 × 韩褶
  **少一道 `上车布`**（部位限定的规则不生效）。⇒ `ProductionRouteParityTest` 的
  `sheerAndClothOrdersHaveTheSameOperationSet` **改判**为「带 `position` 的规则只在自己部位生效 +
  空 `position` 不筛」＋「分叉面**只有**那一条」，并**补一条注入式红证**（抹掉 `position` ⇒ 纱帘立刻多出
  `上车布`）；Python 侧同款（`test_route_model_v2.py` 的 `test_rules_carry_no_position_key` /
  `test_same_craft_is_identical_across_every_curtain_type` / 两条注入红证**全部改判**，改前实测 **10 条红**）。
- **两个「同名不同义」的 `上车布` 规则**：`韩褶 → 上车布`（限 `布帘`）与 `四爪钩 → 上车布`
  （`position` 为空 = 不限）。判据必须**分别**覆盖「限定的要筛掉」与「空值不筛」（只测前者会让
  「把所有规则都按某部位筛」这种错实现**假绿**）。
- **`V103` 与 `V109` 都不删、不改**：`V108` 是**第三条**迁移，不是「把 V103 改回去」。
  三者叠加的终态 = `V71` 字面量（由 §14.4.1 表格第 6 行的守卫机械核验）。
- **未做（登记，不谎报闭环）**：`production_route_rules.position` 的**读面键**本来就在
  （`ruleView` 一直回显它），本单**不改键集**；`GET /route-rules` 的 `position` 语义变化
  只影响**消费方式**（前端重新据它渲染 + 实例化侧据它筛）。矩阵 / 取价侧的 `position`
  （`production_operation_positions.position` 恒 `通用`）**一字未动**。
