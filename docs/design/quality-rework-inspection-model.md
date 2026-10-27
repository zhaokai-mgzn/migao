# 返工单与质检单：两条独立的质量链，都定位到「一件成品帘」

> 状态：**设计 · 已裁定（2026-10-27）** ｜ 性质：docs-only（本文件不改代码、不改数据、不改契约）
> 审计基线：`origin/main` @ **2e17c1f7f**（2026-10-27；本地主工作区当时落后 68 个提交，本文一律以 `origin/main` 为准）
> 关联：#7377（质量成本与返工单前身）· #7860（任一工序报返工）· #7919（返工报工自动落质检）· #7197（P2 质检深度指标）
> 引用纪律：代码引用一律给**仓库相对全路径 + 符号名**，不写裸行号。

---

## 0. 结论（先给答案）

1. **返工与质检不是同一件事**（用户 2026-10-27 逐字）：
   「返工是因为**布料有质量问题**，而质检是因为**加工厂做工有问题**，两者有区别」⇒
   **返工只记录返工单，不产生质检数据**；质检单也不得由返工自动生成。
2. **两单都必须定位到「一件成品帘」**（用户裁定：定位键 = **套号 × 部位**）：
   件 = `(processing_order_sets.id, order_items.id)`，正好对应**一张水洗唛码**（单号 + 套号 + 部位）=
   `processing_set_part_tokens` 的一行。现状两单都没完整落到这个键上：
   - **质检单**只有 `order_item_id`（部位行），**丢套号** ⇒ 同一订单两樘窗的同一部位无法区分（这正是「像在给订单整体记质检」）；
   - **返工单**只有 `operation_id`（件隐含在工序实例里），**读面/列表没有套号与部位** ⇒ 答不出「返的是哪一件」。
3. **同一件「返工」今天有两条写路径，各记一半**（这是「设计有点问题」的确切形态）：
   - 工人「报返工」块（#7860）→ **建返工单**，不改质检；
   - 报工三态选「返工」（#7919）→ 写报工 + **自动落一条质检记录**，**不建返工单**。
   ⇒ 车间报一次返工，系统里可能只有一张单、也可能只有另一张单；「返工单与质检单」从未真正成对出现。

---

## 1. 现状读数（`origin/main`，2026-10-27）

### 1.1 三条写路径

| # | 入口 | 服务端 | 产出 | 件定位 |
|---|---|---|---|---|
| ① | 工人端报工页「这一件有问题，报返工」块（`frontend/worker-h5` 的 `reworkBlock`） | `ProductionReworkService.report`（`POST /api/worker/production/rework`） | **返工单** `source='worker'`；同时把该工人最近一笔 `normal` 报工**改记为** `rework`、回退 `done_qty` 与计件 | 只存 `operation_id`；`order_item_id` / `set_no` **未落** |
| ② | 报工三态选择器选「返工」（`workTypePicker`） | `ProductionService.applyReport`（`POST /api/worker/scan/complete`，`work_type='rework'`） | 写一条返工报工；**并自动落一条质检记录**（#7919，`ProductionService.recordReworkQuality` → `QualityCheckService.recordReworkReport`） | 质检记录用 `op.order_item_id`（丢套号）；**不建返工单** |
| ③ | 观星台「质检记录」页 / 工人质检端点 | `QualityCheckService.create`（`POST /api/admin/quality-inspections`） | **质检单**（`quality_inspections` 一行） | 只有 `order_item_id`；**丢套号** |

### 1.2 问题清单

| # | 问题 | 证据（符号 / 路径） | 后果 |
|---|---|---|---|
| **B1** | 质检单丢套号 | `backend/admin-api/src/main/resources/db/init/schema.sql` 的 `quality_inspections` 无 `set_id/set_no`；`QualityCheckService.targets` 按快照 `items[]` 展开（一行 = 一个部位行，不是一樘） | 两樘窗的「布帘」共用一条当前判定 ⇒ **质检看起来是给订单行/整单记的**（用户原话的现场形态） |
| **B2** | 返工单没有件键 | `ReworkOrder` 只有 `operationId`；`ReworkOrderView` 无 `orderItemId/setNo`；`ReworkOrderService.createWorkerRework` 不接收件 | PC 返工列表只能显示「工序 / 数量 / 报工人」⇒ **哪一件返工了、返完没有**答不出 |
| **B3** | 两条返工路径各记一半 | ①`ProductionReworkService.report` 建单不落质检；②`ProductionService.recordReworkQuality` 落质检不建单 | 同一事实两套账；按「返工单数」与「质检记录数」统计会得到两个不同世界 |
| **B4** | #7919 的因果倒置 | `QualityCheckService.recordReworkReport` 用「返工报工」**自动生成质检判定** `rework`，原因合成「返工报工：<工序>」 | 把「材料问题」记成「做工判定」；质检单不再是独立检验事实，FPY/返工率口径被污染（用户 2026-10-27 裁定要撤销） |
| **B5** | 返工单没有验收/闭环 | `ReworkState` 四态 `draft → in_progress → done`；`complete` 无任何验收证据 | 返工（换布/重做）做没做、做得好不好，系统里没有答案（P1） |
| **B6** | 质检没有检验点 / 轮次 | `QualityCheck` 无 `inspection_type` / `inspection_point_operation_id` / `round_no` | 「做工问题出在哪道工序」「首检还是复检」说不清；多检验点一开，FPY 口径会立刻失真（P1） |
| **B7** | 原因自由文本 | `quality_inspections.reason VARCHAR(500)`；`rework_orders.reason VARCHAR(500)` | 缺陷 Top 分布无意义（#7197 ①） |
| **B8** | 返工工时归不到单 | `QualityCostPolicy.reworkCost` = 全部 `work_type='rework'` 报工；`production_work_logs` 无单据号（冻结契约） | 「这张返工单花了多少工时」答不出（P1，需旁路表） |
| **B9** | 返工单状态唯一性仍按售后单 | `uk_rework_orders_open_per_ticket`（V185）仍是 `(tenant_id, after_sales_ticket_id)`；车间来源无售后单 ⇒ 不受该索引约束 | 同一件可以并发开多张车间返工单；问「这件修完没有」会有多个答案 |
| **B10** | 返工写面权限错位 | `ReworkOrderController` 写面用 `order:refund` | 车间主管/质检员开不了返工；能开的人手上握着退款权限 |

### 1.3 不推翻的既有裁定（新设计必须保留）

| 裁定 | 保留方式 |
|---|---|
| 判定对象是**件**（2026-10-16） | 保留，并补上件键的另一半：**套号 × 部位** |
| 工人端不显示「合格」，只给「返工」（#7749/#7925） | 保留展示口径 |
| 报工是数量事实、质检是判定，互不覆盖；质检不参与计件（#7165/#7186） | 保留；本设计不改计件 |
| 报工明细「不可变」的唯一例外 = 车间报返工时的**改记**（用户 2026-10-26 选 B） | 保留，不动 `ProductionReworkService.report` 的改记与回退逻辑 |
| 未检 ≠ 合格；未知不填 0 | 保留 |

---

## 2. 行业怎么做

- **ISO 9001:2015 §8.7**：不合格输出的处置方式（纠正 / 隔离 / 告知顾客 / 让步接收授权），§8.7.2 要求记录
  **不合格性质、措施、让步、授权人**。
- **ISO 9000:2015 术语**：返工（rework）= 使不合格品**符合原要求**；返修（repair）= 使之**满足预期用途**；
  让步（concession）= 授权放行不合格品。
- **IATF 16949:2016 §8.7.1.4 / §8.7.1.5**：返工/返修必须有文件化过程，**返工/返修后放行前必须再检验**。
- **单件追溯**：一件成品帘 = 一樘窗的一个部位 = 一张水洗唛码（本仓 `docs/design/set-code-and-scan-loop.md`：
  码内容 = 单号 + 套号 + 部位）。质量记录必须挂在这个码上，否则「哪一件」不可追溯。
- **两类不合格来源要分开统计**（本仓业务口径）：**材料/布料**（供应商来料）vs **做工/加工**（加工厂）。
  两者的处置、责任与索赔对象完全不同 ⇒ 不能合成一个「返工率」。

⇒ 抽成四条本仓不变式：

| # | 不变式 |
|---|---|
| **I1** | 每一条质量事实都定位到**件** = 套号 × 部位（与扫码码同一把钥匙） |
| **I2** | **返工单只记材料质量问题，质检单只记做工质量问题**；两者不互相自动生成 |
| **I3** | 已发生的报工/计件不回退，**除**车间报返工的既有改记口径（用户 2026-10-26 已裁） |
| **I4** | 缺套号/缺件定位的存量记录**不猜**：不折算到任一樘，统计里单列「未定位」 |

---

## 3. 目标模型

### 3.1 两条链

```
材料质量问题（布料）：
  工人/车间发现 → 【返工单】（件 + 工序 + 数量 + 原因）→ 返工处理 →（P1：验收）→ 关闭

做工质量问题（加工）：
  质检员在检验点 → 【质检单】（件 + 判定 pass/nonconforming）→（P1：检验点/复检/轮次）→ 结论
```

两条链的**唯一交集是「件」**（`set_id + order_item_id`），不互相造数据。

### 3.2 件定位键

```
件 = (processing_order_sets.id, order_items.id)
   ≈ processing_set_part_tokens 的一行（token / short_code = 水洗唛码）
   ≈ processing_position_operations 的一行里的 (set_id, order_item_id)（那道工序属于这件的这一道）
```

- 新单：`processing_order_sets` 由 `ProcessingOrderSetAllocator` 分配（已落码）；
- 存量单：套号可能为 NULL ⇒ 记录不猜、统计单列「未定位」。

### 3.3 返工单（在 V185 + V199 上加法改造）

| 列 | 变化 | 说明 |
|---|---|---|
| `order_item_id` | 新增 `VARCHAR(36)` | 部位行（`order_items.id`） |
| `set_id` / `set_no` | 新增 `VARCHAR(64)` | 套（樘）；车间来源从工序实例取 |
| `position_name` | 新增 `VARCHAR(128)` | 部位展示名快照（读面不 join 猜） |
| `source` | 已有（V199） | `after_sales` / `worker`；**默认仍是售后，按来源显式写** |
| 状态机 | **不变**（P0） | `draft → in_progress → done / cancelled`；验收/复检放 P1 |
| 件级唯一性 | 新增部分唯一索引 | 同一件**最多一张未完结**车间返工单：`(tenant_id, set_no, order_item_id) WHERE source='worker' AND status IN ('draft','in_progress') AND deleted=0` |

**写面**：`createWorkerRework` 增 `orderItemId / setId / setNo / positionName`（来自 `ProductionReworkService.report` 的 `op`），
**不再**产生任何 `quality_inspections` 行。

### 3.4 质检单（`quality_inspections` 加法改造）

| 列 | 变化 | 说明 |
|---|---|---|
| `set_id` / `set_no` | 新增 `VARCHAR(64)` | 件键的另一半；存量行留空（不猜） |
| `inspection_type` / `inspection_point_operation_id` / `round_no` | **P1** | 检验点/首检/复检；P0 不加，避免半套口径 |
| `recordReworkReport` | **删除** | #7919 的「返工报工自动落质检」按用户裁定撤销 |

**写面（2026-10-27 追加裁定）**：质检判定**只在手机端**录入（质检员扫码 → 做工判定），PC 不再提供录入口
（用户逐字：「质检单的这个区域都可以移除了，应该从手机端去判定」）。手机端扫码面已知套号 ⇒ 判定随请求带
`set_no`；服务端仍按同一套规则校验（`create` 的 `set_no` 可选）：
- 显式给了套号 ⇒ 校验该套的 `position_item_ids` **包含**这件（不跨件）；
- 未给且**恰好一套** ⇒ 取该套（无歧义）；
- 未给且**多套** ⇒ 422 并列出候选套号（**不猜第 1 套**）。
无套（存量单）⇒ `set_no` 为 NULL。

**读面**：`targets` 从「快照 `items[]` 一行一个部位」改为「**live 套 × 该套的部位**一行一件」；
没有套的存量单回落到快照行（`set_no=null`）。`stats` 的首检/最新折叠键从 `order_item_id` 改为
`order_item_id + set_no`（否则多樘仍混）。`targets` 端点**保留**（后续手机端待检队列可复用），
但 PC 页面自 2026-10-27 起不再渲染它。

### 3.5 统计口径（区分两条链）

| 指标 | 口径 |
|---|---|
| 返工率（材料） | 返工单件数 ÷ 已产出件数；**不**把质检的 `rework` 判定算进来 |
| 质检不合格率（做工） | 质检非 pass 件数 ÷ 已检件数；**不**把返工单算进来 |
| 首检合格率 | 仍按件（套×部位）折叠第一条记录（P0 不加检验类型） |
| 未定位 | 返工单无套号 / 质检记录无套号 ⇒ 单列「未定位」；不并入任一件 |

### 3.6 权限

- 读：`after_sales:view`（返工列表，兼容）+ `production:inspect`（质检）；
- 车间报返工：工人 session（既有）；PC 上开/改返工单建议 `production:inspect` 或新码（P1 裁定），
  本批**不改**权限码（避免出现没人持有的新码 —— #4203 同族）。

---

## 4. 迁移与兼容

### 4.1 DDL（一份迁移 V202）

```sql
ALTER TABLE rework_orders
  ADD COLUMN IF NOT EXISTS order_item_id VARCHAR(36),
  ADD COLUMN IF NOT EXISTS set_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS set_no VARCHAR(64),
  ADD COLUMN IF NOT EXISTS position_name VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS uk_rework_orders_open_per_piece
  ON rework_orders (tenant_id, set_no, order_item_id)
  WHERE source = 'worker' AND status IN ('draft','in_progress') AND deleted = 0;

ALTER TABLE quality_inspections
  ADD COLUMN IF NOT EXISTS set_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS set_no VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_quality_inspections_piece
  ON quality_inspections (tenant_id, set_no, order_item_id, inspected_at) WHERE deleted = 0;
```

同步 `backend/admin-api/src/main/resources/db/init/schema.sql`（新建库不跑迁移链，V185/V199 已有此约定）。

### 4.2 存量

- 存量返工单：`order_item_id/set_no` 为空 ⇒ 读面显示「未定位到件」，**不补、不猜**；统计单列。
- 存量的 #7919 自动质检记录：**保留**（已发生的事实），但读面可凭 `reason` 前缀
  「返工报工：」识别为「报工触发的记录」；不做数据清洗（清洗 = 改写历史）。
- 删除自动落库后，质量成本的「返工工时」仍走 `work_type='rework'`（不变）。

### 4.3 API 兼容

| 端点 | 策略 |
|---|---|
| `POST /api/worker/production/rework` | 响应加 `set_no` / `order_item_id` / `position_name`；写面不变 |
| `POST /api/admin/quality-inspections` | 新增可选 `set_no`；旧调用（无套号）行为不变（仅一套时自动取；多套 422） |
| `GET /api/admin/quality-inspections/targets` | 行增加 `set_no` / `set_id` / `piece_label`；存量单行为不变 |
| `GET /api/admin/rework-orders` | 行增加 `order_item_id` / `set_no` / `position_name` |
| `POST /api/admin/rework-orders`（售后开单） | 不变；件字段可空 |

### 4.4 前端影响

1. `frontend/admin-web/src/app/(dashboard)/rework-orders/page.tsx`：列表加「套号 / 部位」两列（缺失显示「未定位」）。
2. `frontend/admin-web/src/app/(dashboard)/quality-inspections/page.tsx`：**移除**「待检成品帘 + 录入判定」区
   （判定只在手机端），只留指标 + 质检流水；页面写明入口在手机端。
3. `frontend/admin-web/src/types/rework.ts` / `types/index.ts`：补字段（与后端 View 逐字对齐）。
4. `frontend/worker-h5`：**恢复质检区块**（`inspect` 页面集可见，标题「质检（做工）」），判定提交带
   `set_no`（扫码面已知）；返工区块改文案「布料有问题，报返工」，两条链语义分开。

---

## 5. 分期

| 期 | 范围 | 依赖 |
|---|---|---|
| **P0**（本单） | 撤销 #7919 自动落质检；两表加件键并落库；QC targets/stats 按件；返工列表加套号/部位；**PC 质检页移除录入区（判定迁到手机端并恢复质检区块）**；用例与 CHANGELOG | 本文裁定 |
| **P1** | 质检检验点/类型/轮次；缺陷字典（与 #7197 ① 合并）；返工工时旁路归集；返工验收；统一两条返工写路径（三态 vs 报返工） | P0；R2 已裁（不计件） |
| **P2** | 返修/让步/降级/退货入口 + 授权人；AQL 抽样；材料索赔与供应商维度 | 业务规模 |

---

## 6. 已裁定（2026-10-27 用户逐轮确认）

| # | 问题 | 裁定 |
|---|---|---|
| R1 | 返工单是否必须挂售后单 | **不挂钩**：「现在的返工单都是车间自检发现的…不需要和售后单挂钩」 |
| R2 | 返工工时是否计件 | **不计件**，只按返工明细归集成本工时（P1） |
| R3 | 「一件成品帘」的定位键 | **套号 × 部位**（推荐项） |
| R4 | 质检单与返工单的因果 | **返工只记录返工单，不产生质检数据**：「返工是因为布料有质量问题，而质检是因为加工厂做工有问题，两者有区别」 |
| R5 | 落地节奏 | 开 issue + 按推荐默认落 P0 |
| R6 | 质检判定在哪录 | **手机端**：「质检单的这个区域都可以移除了，应该从手机端去判定」⇒ PC 质检页撤掉待检清单 + 录入判定，工人端恢复质检（做工）区块 |

> R4 直接推翻 #7919 的「返工报工自动落质检记录」：该行为在 P0 撤销（不是藏起来）。

---

## 7. P0 判据（会红）

1. **返工不再造质检**：走 `POST /api/worker/production/rework` 后，`quality_inspections` 行数**逐值不变**；
   走 `scan/complete` + `work_type='rework'` 同样**不新增**质检行（当前 #7919 会新增 ⇒ 改前必红）。
2. **件键落库**：车间返工单 `order_item_id` = 工序实例的 `order_item_id`，`set_no` = 工序实例的 `set_no`；
   注入一条缺 `set_no` 的工序实例 ⇒ 返工单 `set_no` 为 NULL（不猜），不是空串。
3. **件级唯一**：同一 `(set_no, order_item_id)` 并发开两张未完结车间返工单 ⇒ 唯一索引拒（可读文案，不是 5xx）。
4. **质检按件**：同一加工单两套、同一部位各录一次判定 ⇒ `targets` 出**两行**，两行的 `state` 互不影响；
   只录其中一件 ⇒ 另一件仍 `pending`（改前共用一个 `order_item_id` 会串）。
5. **多套未选套 ⇒ 422**：质检提交不带 `set_no` 且该单有多套 ⇒ 具名报错并列出候选；只有一套 ⇒ 自动取该套。
   手机端扫码面**总是带 `set_no`** ⇒ 正常路径不触发。
6. **跨件拒**：`set_no` 与 `order_item_id` 不属于同一套 ⇒ 422，不落半行。
7. **不猜存量**：存量返工单（无件键）在列表里显示「未定位」，统计不并入任何一件。
8. **PC 不再录入**：质检记录页零调用 `targets`、无「待检成品帘 / 录入判定」，只留指标 + 流水；
   手机端 `inspect` 页面集才渲染质检（做工）区块，提交体带 `set_no`。
9. **反证（负控）**：`normal` / `scrap` 报工不产生返工单，也不产生质检记录；返工写路径不持有任何
   `QualityCheck*` 依赖（类级守卫，想接回质检先加依赖 ⇒ 红）。

---

## 8. 参考

- ISO 9001:2015 §8.7 / §8.7.2；ISO 9000:2015 术语（返工 / 返修 / 让步）。
- IATF 16949:2016 §8.7.1.4（返工）/ §8.7.1.5（返修）。
- 本仓：`docs/design/set-code-and-scan-loop.md`（套号 + 一部位一码 + 扫码闭环）；
  `docs/curtain-production-process-standard.md` §2.3（质检贯穿全过程；成品质检是检验点不是固定工序）。
