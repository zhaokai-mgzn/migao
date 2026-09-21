# 订单下发加工全链路 —— 按两条在飞重构的最终落地方案对齐

> **状态**：设计稿（待裁定）。**不改任何代码**，先对齐再动手。
> **被测基线**：`origin/main @ab54b7de`（P2a 合入后为 `b41a6242` 之后）。
> **两条在飞重构的最终落地方案**（本节是**口径上限**，与下文冲突以本节为准）：
> - 工序路线模型：issue **#4423**（母单）+ 会话 `session-297ee1ee`（P1 #4427 / P2a #4460 已完成）
> - 订单侧：会话 `session-3cd77f70`（#4420 / #4426 / #4421 / #4434 / #4444 已合，#4406 在飞）
>
> 本文**不重复**既有设计文档的口径，只写**全链路**这一层（两份既有文档各管一段）：
> `position-instance-routing-model.md`（工序/路线/部位领域模型）·
> `order-craft-spec-design.md`（订单工艺规格）· `processing-order-design.md`（加工单）·
> 真值源 `docs/curtain-production-rules.md` §1~§5。

---

## 0. 一句话结论

**全链路有一个共同上游：工序实例化（`ProcessingOrderService`）。**
P2b 切换它的**数据来源**（旧「9 条展开路线」→ 新「主线 + 规则表 + 部位价目」），
下游三件事**全部从它取值**：① 加工单工序实例（`processing_position_operations`）→
② 报工计件金额（`production_work_logs.unit_price/factor` 快照）→ ③ 工人扫码端看到的工序清单。

⇒ **P2b 是所有下游优化的共同前置**，必须先做；且它的判据不是「看起来对」，而是
**9/9 逐字重建 + 计件金额逐字不变**（详见 §5 判据 1~2）。

---

## 1. 现状核查（每条可复核）

### 1.1 工序路线模型（#4423）—— P1/P2a 已合，P2b 未开工

| 阶段 | 状态 | 证据 |
|---|---|---|
| **P1** #4427 | ✅ 已合 | `origin/main` 有 `V71__normalize_routing_model_structure.sql`（建 `production_operation_positions` / `production_route_templates` / `production_route_rules`）；`routing.py` 有 `ROUTE_MAINLINE_STEPS` / `ROUTE_RULES` / `OPERATION_POSITION_PRICES` |
| **P2a** #4460 | ✅ 已合（PR #4462） | `origin/main` 有 `V72__switch_routing_model_consumers.sql` + 4 实体（`ProductionCraft` / `ProductionOperationPosition` / `ProductionRouteRule` / `ProductionRouteTemplate`）+ 4 mapper |
| **P2b** #4459 | ❌ **未开工** | 见 §3.1 |
| **P3** #4433 | ❌ 未开工 | 前端部位价目矩阵 + 具名路线 + 规则区 |
| #4452 | ❌ 未开工 | **必须等 P2b**（同撞 `ProcessingOrderService` + `ProductionController`） |

**目标模型（冻结）**：`工序(30 逻辑) + 部位价目(120 行) + 具名主线(窗帘 10 道 / 布料 2 道) + 规则表(26 条) + 商户级默认工艺`
—— 由 **9/9 逐字重建**证明是**纯表示法收敛**（不发明工序、不改单价）：

```
布帘×韩褶 11/11 ✅   布帘×打孔 10/10 ✅   布帘×四爪钩 8/8 ✅   布帘×穿杆 7/7 ✅
纱帘×韩褶  6/6  ✅   纱帘×打孔  6/6  ✅   纱帘×四爪钩 6/6 ✅   纱帘×穿杆 5/5 ✅
帘头×平幔  7/7  ✅                逐字一致 9/9
```

### 1.2 订单侧 —— 除 #4406 外全部已合

| PR | issue | 状态 |
|---|---|---|
| #4424 | #4420 下单页录入改造 | ✅ 已合 |
| #4429 | #4426 详情页只读重设计 | ✅ 已合 |
| #4435 | #4421 算料褶数法 + 拼色系数 | ✅ 已合 |
| #4438 | #4434 下单页接线算料试算 | ✅ 已合 |
| #4447 | #4444 详情页加工费算式 | ✅ 已合 |
| **#4446** | **#4406 加工费组合消费面** | ⚠️ **OPEN**，`mergeStateStatus=BLOCKED`，**唯一 pending = `admin-web typecheck + unit tests`**（不是死锁，等 CI） |

**关键状态失衡**：`origin/main` 上 **展示契约超前于计价契约** ——
详情页已按 `processingFeeDetail.fee_source` 三态渲染（#4447 已合），
而 `OrderService` **仍是 Σ 加工项**（#4406 未合）。

### 1.3 工人扫码端 —— 功能可用但**信息面极窄**

`frontend/bmini-app/src/pages/production/index/index.tsx`（429 行）：
扫一扫 / 手输单号 → 工序清单（按部位分组，含应做数量/单位/单价/已报/累计计件）→
改数量 → 完成报工 → 进度条 + 本单累计计件 + 本单报工明细。

数据源 = `GET /api/admin/production/orders/{orderId}/operations`
→ `ProductionService.getOperations` → `buildPositions`，**每部位只回 4 个键**：

```java
position.put("position_name", …);   // 展示名
position.put("order_item_id", …);   // 主定位键（V69/#4388）
position.put("position_kind", …);   // 可读定位（哪一件帘）
position.put("operations", …);      // [{operation, unit, unit_price, qty, done_qty, …}]
```

### 1.4 计件链路 —— 金额已固化，但**下钻维度不全**

- 金额**在报工那一刻固化**（V61 / #4351）：`production_work_logs.unit_price` / `factor` 快照，
  聚合只读快照 ⇒ 重新实例化（软删旧实例重插）**不吞钱**。
- 聚合**只有一份**（`ProductionService.aggregate`）：per-order / 期间报表 / 工人计件共用。
- 口径：`Σ(合格数量 × 报工自己的单价快照 × 报工自己的系数快照)`，返工/报废不计件。
- 报表返回：`{period, total, per_worker:[{worker_name, amount, qty}], per_operation:[{operation, amount, qty}]}`。

**⚠️ 真值源 §4 要求的下钻链**是
`报工 → 工序实例 → 部位 → 套 → 加工单 → 订单`，
而**今天的报表只到「人 / 工序 / 期间」** —— 缺**部位**与**套**两维
（数据其实在：实例有 `position_name` / `position_kind` / `order_item_id`）。
⇒ 「这个月这笔钱是哪个窗、哪个部位挣的」**今天答不出来**。

---

## 2. 全链路数据流（P2b 的改动面就是这张图的红线）

```
① 下单（admin-web / 米宝）
   order_items: width/height/craft/curtainType/openCount/cuttingMode/isShaped/fullness/…
   └ processing_info: specialOptions[] / fabric_meters / processingMeters      [算料单一真值=ai-agent]
        │
        ▼  POST /api/admin/processing-orders/generate
② ProcessingOrderService.generate  ── ★ P2b 改这里（数据来源切换）
   buildSnapshot → deriveRouteKey（显式字段 > 加工项推导 > 信号派生）
                 → resolveRoute  ← ★ T1/T2 回落目标：常量「布帘×韩褶」→ 该租户 is_default 路线
                 → buildPositionPayload ← ★ 规则应用语义必须与 routing.py::build_route_v2 逐字一致
                   产出 positions[{position_name, order_item_id, position_kind,
                                   operations:[{operation, unit, unit_price, factor, …}]}]
        │
        ▼  POST /api/admin/production/orders/{orderId}/instantiate
③ ProductionService.instantiate
   → processing_position_operations（unit_price/factor = 生成时快照）
        │
        ├─────────────► ④ 工人扫码端  GET /production/orders/{id}/operations
        │                 今天只回 4 个键（§1.3）⇒ ★ 本方案补规格/用料/部位备注
        │
        ▼  POST /production/orders/{id}/operations/{opId}/report
⑤ ProductionService.report
   → production_work_logs（unit_price/factor = 报工那一刻快照）  ← ★ 不改本表
        │
        ▼
⑥ 计件聚合 ProductionService.aggregate（唯一一份）
   per-order / 期间报表 / 工人计件 → ★ 本方案补「部位 / 套 / 加工单」下钻
```

---

## 3. 设计方案

### 3.1 P2b —— 切消费路径（#4459，**最高优先，唯一共同前置**）

**为什么必须先做**：它改的 `ProcessingOrderService` / `ProductionController` /
`ProductionOperationQueryService` **正是**订单侧 #4452 与工人端加工链路要改的同一批文件。
并行 = 互相覆盖。

| # | 改动 | 要点 |
|---|---|---|
| 1 | `ProductionOperationQueryService` 新读面 | `routeTemplateFor(position)` / `defaultRouteTemplate` / `defaultCraft` / `operationPositions` / `routeRules` / `variantNameOf` / `normalizeOperationName`；**按 `(priority, id)` 稳定排序**（派生必须确定性，否则同一张单两次生成得到不同工序序列与计件工资） |
| 2 | `ProcessingOrderService` 三方法 | `buildPositionPayload` / `resolveRoute` / `deriveRouteKey` 改读新结构；**规则应用语义与 `routing.py::build_route_v2` 逐字一致**（remove / insert after 锚点 / 锚点不在 ⇒ 追加末尾 / 部位适用性过滤） |
| 3 | 路线写面 | `ProductionRoutingCommandService` + `ProductionController` 改模板表；新增 `DELETE /routings/{id}`；`PUT` body 扩展 `{name?, is_default?, mainline?}` |
| 4 | 开租播种 | `ProductionSeedTemplateService.applyTemplate` 写新三表 + **默认路线 + 默认工艺** |
| 5 | **软删旧规则表** | `production_option_routings` / `production_option_factors` 软删为 0 活跃行；**表不 DROP** |
| 6 | 测试适配 | `findRouting` 24 / `routingView` 3 / `routingKeys` 6 / `optionRoutings` 5 / `optionFactors` 5 / `operationsByName` 4 = **47 处调用点** |

**🔴 铁律：软删必须与消费切换同一 PR。**
Java 此刻仍读旧两表（`ProductionOperationQueryService.optionRoutings` / `optionFactors`
→ `ProcessingOrderService` 插条件工序 + 算计件系数）。若 V72 先软删而消费路径没切
⇒ **条件工序不插、计件系数退回 1.0 ⇒ 少发工人钱**（#4230「静默黑洞」同族）。
P2a 已把软删**移出** V72，承重守卫 = `test_v72_must_not_retire_legacy_rule_tables`。

**红证已备好**：`tests/unit_ci_workflows/test_routing_model_p2_consumers.py` 的 **4 条 xfail
就是 P2b 的红证前置** —— C-1 软删 / C-5 零读取点 / C-6 读新表 / 缺 `craft` 取默认工艺。
P2b 完成的判据 = **这 4 条 xfail 转正**。

### 3.2 订单下发收口 —— #4446（P1，会拒单）

**#4450 的确切机制**（四段，逐段可复核）：

| 段 | 事实 |
|---|---|
| ① 页面本地加工费 = **Σ 加工项** | `orders/new/page.tsx` 的 `processingFee += price * q` |
| ② 页面把**本地总额**当实收款提交 | `actualAmount: actual`（默认 = `totals.total`） |
| ③ 服务端改成**组合取价**，未命中 ⇒ **0 + unpriced**（不回落 Σ 加工项） | #4446 的 `OrderService.createOrder` |
| ④ 服务端校验 `\|应收 − 优惠 − 实收\| ≤ 0.01` | `OrderService` 「实收金额与应收不一致」 |

⇒ ③ 与 ① 口径不同 ⇒ ④ 必抛 `validationError` ⇒ **拒单**。租户没配过组合时最严重。

**解闸条件（已在 PR #4446 内完成）**：
① `POST /api/admin/orders/fee-preview`（不落库，**只调 `ProcessingFeeCalculator.feesFor`** —— 与创建订单**同一个**取价实现）；
② 下单页改用 `feePreviewApi` ⇒ 页面显示 === 落库；
③ 页面写 `processingMeters`（`ProcessingFeeCalculator.METER_KEYS` 的键之一）。

**动作**：等 CI 终绿 ⇒ auto-merge ⇒ 复核 §5 判据 3。**若转红 ⇒ 按提交序二分，不掩盖。**

### 3.3 工人扫码加工链路 —— 按参考软件截图对齐

**与 P2b 的文件关系**：工人端 UI（`frontend/bmini-app/**`）**不撞** P2b；
后端 payload 扩展在 `ProductionService.getOperations`（P2b **不碰** `ProductionService`）
⇒ **本项可与 P2b 并行**。

**数据来源已就位，缺的是接线**（这是本项最小的证据）：

| 截图元素 | 今天在哪 | 动作 |
|---|---|---|
| 加工单号 / 第N套/共M套 | `processing_orders` + `order_items` | 接线 |
| 客户 / 收货人 / 物流 / 地址 / 打包区域 / 项目名称 | `orders` / `order_logistics` | 接线 |
| **加工信息网格**：套数·打开方式·安装工艺·加工类型·褶倍·下单日期·**宽高**·部位定型·单号·用料 | `order_items`（`openCount`/`craft`/`cuttingMode`/`isShaped`/`fullness`/`width`/`height`）+ 算料输出 | 接线 |
| 部位行：主布 型号 用料 / 褶数 / 幅数 / 未配料 / 未采购 | 算料输出 + 加工项 | 接线 |
| **部位备注（含公式）** | `order_items` 备注 / `processing_info` | 接线 |
| **精裁输出** | **无任何存储**（全仓只有 `精裁-布` 工序名） | **需裁定**（见 §4 决策 5） |
| **操作记录**（确认/操作员/时间戳） | `production_work_logs`（服务端有）；工人端只有本机明细 | 接线 |
| 打印标签 / 打包 / 发货 / 整套配料 / 面料加工单 | `TaskCardPrint.tsx` 部分有；#4347 登记「发货下放/打包语义」待落码 | **需裁定**（见 §4 决策 6） |

**⚠️ 已登记的既有缺口**：`#4403` —— 宽/高在**工人任务卡 `TaskCardPrint.tsx`** 与 C 端报价单
**不显示**；根因是「入口从不写」（#4424 已补录入端），渲染端仍未修。

### 3.4 计件链路 —— 做到「可核对」（不加审批环节）

**判据来源**：真值源 §4「工资报表 = 报工事件聚合（按人/按期/按单下钻：
报工 → 工序实例 → 部位 → 套 → 加工单 → 订单）」+「单价 = 工序 × 部位定价，版本化，逐笔可追溯」。

**今天缺两维**（部位 / 套），**数据都在**（实例的 `position_name` / `position_kind` / `order_item_id`）。
⇒ 在 `aggregate` 的**同一份实现**上加下钻维度（**不新增第二份聚合**，这是既有纪律）。

**硬边界**：
- **不改 `production_work_logs`**（P2b 明列「不做」；V61 快照口径已冻结）。
- **不回算历史工资**（快照冻结，真值源 §4）。
- **不加审批环节**（用户裁定：先做到可核对；审批需另立状态机与权限，会引入「确认后改价」的回算边界）。

---

## 4. 待裁定（**需你逐条给口径**）

> 前 4 条是**在飞会话已登记但未获你确认**的；后 2 条是**本方案新暴露**的。

| # | 决策 | 选项 | 影响面 |
|---|---|---|---|
| **1** | **`variantNameOf` 查找规则**（新结构用逻辑名 `精裁`，`production_operations` 仍是旧名 `精裁-布`） | **A** 逆映射（P2a 已实证可逐条复现全部 35 条旧名，但是「同一映射的第二向」）／ **B** 给 `production_operations` 加 `logical_name` 列（**规格里没有的列**，需新迁移） | 决定 P2b 的迁移号与「单一真值源」强度 |
| **2** | **`routingGaps.signal_keys_without_route` 是否纳入「工艺无规则」缺口** | P2a 暂取**不纳入**（未获确认） | 影响缺口报表语义；**语义必须与 `resolveRoute` / `deriveRouteKey` 同源**，否则「用的路线」与「记下来的键」漂移 |
| **3** | **回填价目取 P1 规范矩阵 vs 该租户 `unit_price`** | P2a 暂取**规范矩阵**（避免在 SQL 重写第三份归一映射） | **动工人工资** —— 若取租户旧价，需在 SQL 重写 35 条归一映射 |
| **4** | **#4403 宽/高渲染修法** | **A** 收敛到 `craftSpecRows` 单一来源 + 删各处重复渲染／ **B** 只在缺的两面（工人任务卡 / C 端报价单）单独补 | 影响工人端与 C 端；**A 需先核实 C 端 `curtain_calc.build_quote` 是否回显窗宽/窗高** |
| **5** | **「精裁输出」要不要做** | **A** 不做（YAGNI：它只是把「精裁」工序的用料米数换个地方显示）／ **B** 做（需定义它是**输入**还是**输出**、存哪、谁写） | 新增字段 = 新增真值源，**必须避免第二份口径** |
| **6** | **打包 / 发货 / 整套配料 / 面料加工单要不要下放到工人端** | **A** 本轮不做（#4347 已登记待落码）／ **B** 做（需先裁定打包语义 + 发货权限） | 工人端权限模型（当前工人端只有报工） |

---

## 5. 验收判据（每条必须能红 —— 不会红的断言 = 空断言）

| # | 判据 | 红证 |
|---|---|---|
| **1** | **实例化逐字一致**：9 个 `(部位,工艺)` 组合的工序实例与切换前**逐字相同**（含顺序） | 任一漂移 ⇒ 红（P2a 已备 4 条 xfail） |
| **2** | **计件金额逐字不变**：切换后同一张单的 `Σ(数量 × 单价 × 系数)` 与切换前**逐分相同** | 新结构单价与旧 `unit_price` 不等 ⇒ 红（**这是「少发工人钱」的直接判据**） |
| **3** | **页面显示 === 落库**：`fee-preview` 的总额 === `createOrder` 落库的加工费（同一次选配） | 两者不等 ⇒ 红（#4450 的形态） |
| **4** | **旧两表活跃行 = 0 且代码零读取点**；三个消费服务确实读**新**规则表 | 仍有读取点 ⇒ 红（C-5 / C-6 xfail 转正） |
| **5** | **缺 `craft` 取商户级默认工艺**（可配）；改默认工艺 ⇒ 后续订单插入的工序与系数随之变 | 写死常量 `韩褶` ⇒ 红 |
| **6** | **回落链**：默认路线改为另一条 ⇒ 无信号订单实际使用键随之变、`route_source='default'`；默认不存在 ⇒ **仍 fail-closed 422** | 写死 `布帘×韩褶` ⇒ 红 |
| **7** | **开租播种**：`applyTemplate` 后**恰有一条默认路线** ∧ 规则齐全 | 缺 ⇒ 新租户建单全 fail-closed ⇒ 红（**P0**） |
| **8** | **既有实例与历史报工不受影响**（快照冻结） | 改配置回算历史 ⇒ 红 |
| **9** | **工人端规格可见**：扫码后能看到 宽/高/开数/工艺/加工类型/褶倍/部位定型/用料 | 缺任一 ⇒ 红 |
| **10** | **计件可下钻**：报表可按 部位 / 套 / 加工单 下钻，且**下钻合计 === 总额** | 合计不等 ⇒ 红 |
| **11** | 三源收敛：`routing.py` ↔ 新迁移 ↔ `schema.sql` 逐行逐值 | 漂移 ⇒ 红 |
| **12** | 跨模块：`./contract-check.sh` + `./verify-all.sh gate` + `./check-ui-regression.sh` 全绿 | — |

**无 Agent 行为改动**（`routing.py` 是确定性核心、零 LLM）⇒ 按 #4262 **不派发真实 LLM 评测**。

---

## 6. 落地顺序（按依赖，**不并行开工**）

```
P2b（#4459）  ──┬─► 工人端加工链路（§3.3，可并行：文件不撞）
                │      └─► #4403 宽/高渲染（待裁定 4）
                ├─► 计件可核对下钻（§3.4，可并行：只改 ProductionService）
                └─► #4452 消灭信号映射（**必须等 P2b 合并**）
#4446 收口（§3.2）—— 等 CI，不阻塞上面
P3（#4433）前端 —— P2b 之后
```

**并行安全边界**（零共享写路径）：

| 工作项 | 独占文件 |
|---|---|
| P2b | `ProductionOperationQueryService` / `ProcessingOrderService` / `ProductionRoutingCommandService` / `ProductionController` / `ProductionSeedTemplateService` + 新迁移 |
| 工人端 | `frontend/bmini-app/**` + `ProductionService.getOperations`（payload 扩展） |
| 计件下钻 | `ProductionService.aggregate`（**与工人端同文件 ⇒ 两者必须同包或串行**） |

⚠️ 工人端 payload 扩展与计件下钻**同在 `ProductionService`** ⇒ 二者**同包**（同分支同 PR 或严格串行）。

---

## 7. 明确不做（防范围蔓延）

- **不发明工序与单价**（#4261 的 5 项待客户确认**原样保留**；客户回复后只是**调数据**）。
- **不合并** `精裁` 与 `裁剪`（两道，待确认）；**不合并** 布帘车被 与 纱帘车被（按 `applicable` 表达）。
- **不改**「1 订单 1 加工单」与快照机制（`domain-model-review` §2.1 判定动它是净损失）。
- **不改** `production_work_logs`；**不删** `production_route_signals`（#4385 存量单兜底）。
- **不 DROP** 旧两表（另单，须先确认零消费者）。
- **不做**拼色**计价**（#4341 待客户裁定；动它 = 改钱）。
- **不做**订单详情页明细行编辑（引入编辑契约，与「加工单快照不可变」相邻，需单独设计）。
- **不做**路线跨租户复制 / 拖拽编排（#4308 YAGNI 清单不变）。
- **不加计件审批环节**（本轮裁定：先做到可核对）。

---

## 8. 未验证风险（照实登记，不粉饰）

1. **V72 的按租户回填从未在真库执行过**（本机 RDS 不可达，同 #4399）。
   静态守卫只覆盖「有 `FROM tenants` 且按租户循环」这一**形态**，**不能**替代真库验证。
   ⇒ 部署到云测试环境后，**对至少一个非 1 号租户建单成功**是必查项。
2. **#4446 的最终合并结果未记录**（等 CI 期间会话结束）⇒ 本轮需复核 §5 判据 3。
3. **工人端与计件下钻**：两条在飞会话的 transcript **零次**提到「扫码」/ `ProductionService`
   ⇒ **本节（§3.3 / §3.4）是新设计，没有历史裁定可继承**，需你确认口径。
