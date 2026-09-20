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
| **B Java 运行时去部位**（唯一改钱包） | `ProcessingOrderService.buildRoute`（第 1185 起）：① **取价改读工序库 `unit_price`**（值相等 ⇒ 不影响钱）；② **删掉 `applicableByLogical` 过滤**（第 1192-1276）⇒ 纱帘多做 4 道；③ `variantNameOf` 的调用可保留（名字仍要对上工序库行） | **改工钱**（多做的工序） |
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
