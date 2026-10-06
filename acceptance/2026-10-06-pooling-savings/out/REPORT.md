# 智能派单「是否真省料」验证报告（300 单实测）

> 时间：**2026-10-06 10:30 ~ 11:05（Asia/Shanghai）**
> 用户逐字要求：「验证智能派单功能是否真正智能的可以节省用料……模拟用户批量下有一批 300 个订单，
> 然后验证智能派单功能和生成的加工单工序和配置的工艺路线是否能匹配上，且是否真正的能节省生产原材料布料」
> 协议：`migao-acceptance`（四态 + 红证 + 证据链）／任务书：`BRIEF.md`
> **本报告只产读数与判定，不下「验收通过」结论**；独立复核见 §7。

---

## 一、一句话结论

**算法能省料，而且省得很实；但「智能派单」这个页面拿不到这个省料。**

同一批 75 张可并排的订单：

| 派单方式 | 公式米数 | 实际领料 | **省** |
|---|---|---|---|
| 「智能派单」页一键成批派单（界面真实请求体） | 0 | 0 | **0**（连扣料台账都没有） |
| 同一个端点 + 逐行指派批次 + `pooled:true` | 105.00 | 60.00 | **45.00 米 / 1800.00 元** |
| 同指派但 `pooled:false`（逐单） | 105.00 | 105.00 | **0** |
| 订单页「生成加工单」（一次一张 + 选批次） | 105.00 | 105.00 | **0** |

300 张加工单的**工序与配置的工艺路线 300/300 逐字全序相等**（含条件工序），坐标、红证、残留见下。

---

## 二、被测对象与坐标（无 SHA 的活环境结论不可复核）

| 项 | 值 | 证据 |
|---|---|---|
| 部署 sha（被测） | **`73327161f`** | `gh run list --workflow=deploy-admin-api.yml`：run `37393520704`，`2026-10-06T00:20:53Z` = **08:20 +08**，`completed/success` |
| 结论适用性自证 | 该 sha → 当前 `origin/main`（`7b39e5550`）在**派单/省料面 5 个文件零 diff** | `git diff --stat 73327161f..origin/main -- ProcessingOrderService.java StockBatchConsumptionService.java CuttingPlanCalculator.java pool-board.ts pool/page.tsx` = **空** |
| 环境 | 云 dev：admin-api `https://api.migaozn.com`／admin-web `https://merchant.migaozn.com` | `out/recon.json` 六个读端点全 200 |
| 租户 | `tenant_id=25`（`shop-8yn7`，管理员 `13800138000`） | `out/recon.json` |
| 数据库 | 云 dev RDS（`psql` 直读；写面**只碰**本轮 `SD06省料` 前缀的探针对象） | `harness/steps.mjs::cleanup` |
| 起点读数 | orders=2 / processing_orders=0 / stock_batch_consumptions=0 / route_templates=2 / route_rules=27 / operations=41 | `out/recon.json::psql.counts` |

---

## 三、实验设计（单变量）

造 **300 张几何完全相同**的订单（探针商品 1 个 × SKU 1 个（门幅 2.8）× 入库批次 1 个（6000 米 / 40 元每米）），
逐张 `PUT /api/admin/orders/{id}/payment` 确认收款，分 4 臂各 75 张。**唯一变量 = 派单请求体**。

几何（`CuttingPlanCalculator` 类注释里的「定宽买高 P=1 窄窗互补」受益场景）：
窗宽 0.7 × 褶倍 2 = **1.4 米** ≤ 门幅 **2.8 米** ⇒ 1 幅；窗高 1.1 + 卷边 0.3 = **1.4 米**
⇒ 每行占门幅 1.4 米、沿卷长 1.4 米 ⇒ **两行并排 = 1 行（领 1.4 米），分开 = 2 行（领 2.8 米）**。

| 臂 | 请求体（逐字） | 落点 |
|---|---|---|
| **A** 界面路径 | `{orderIds×75, batches:[], assignmentRule:null, pooled:true}` | `frontend/admin-web/src/lib/pool-board.ts::buildPoolRequest`（**该页 dispatchBatch/dispatchSingle 的唯一请求体构造器**） |
| **B** 直调池化 | `batches:[{orderId,itemId}×75]`（batchNo 留空）+ `assignmentRule:'fifo'` + `pooled:true` | `ProcessingOrderService::generatePooled` |
| **C** 直调逐单 | 同 B 的指派 + `pooled:false` | `ProcessingOrderService::generateOne` |
| **D** 订单页路径 | `POST /api/admin/processing-orders/generate`，一次一张 + 显式 `batchNo` | `ProcessingOrderCard::confirmAssign` 的真实形态 |

300 单派出 **300/300 成功、0 失败**（`out/main.json::arms.*.ok` = 75/75/75/75，`poPerArm` 同值）。

---

## 四、省料读数（落账，非估算）

`stock_batch_consumptions` 逐行 `formula_meters`（行业公式口径）/ `planned_meters`（排料口径）/
`unit_cost`（当时批次均价）——`saved = formula − planned`：

| 臂 | 消耗行 | Σformula | Σplanned | **Σsaved** | 折钱 |
|---|---|---|---|---|---|
| **A** 界面路径 | **0** | 0 | 0 | **0** | 0 |
| **B** 池化 + 指派 | 75 | 105.00 | 60.00 | **45.00** | **1800.00 元** |
| **C** 逐单 + 指派 | 75 | 105.00 | 105.00 | **0** | 0 |
| **D** 订单页逐单 | 75 | 105.00 | 105.00 | **0** | 0 |

读数出处：`out/main.json::arms.{A,B,C,D}.ledger`、`rowInvariants`。

- **J1 成立**：`B.saved = 45 > C.saved = 0` —— 省料**来自池化**（同指派、同批次、同几何，只差 `pooled`）。
- **J3 成立**：225 行消耗全部满足 `planned ≤ formula` 且 `planned > 0`（`rowInvariants.plannedLEformula/plannedPositive = true`）。
- **归一的实测部分**：60.00 / 75 行 = **每行 0.80 米**（实测）；公式侧每行 1.40 米。
  **推断部分（未单独记录，如实标注）**：池级排料若按「75 块两两并排 ⇒ 38 行 × 1.4 米 = 53.2 米」，
  则每行分摊 0.7093 米、落库存前按 0.1 米**向上**归一 ⇒ 0.80 米/行 ⇒ 60.00 米。
  ⇒ 归一吃掉了一部分理论节省（53.2 → 60）。**这是设计口径，不是缺陷**
  （`StockQuantity::toStockScaleByCeiling`，少领比不省料严重）。

### 4.1 成批预览（用户在该页直接看到的数）

| 请求体 | formulaMeters | pooledPlannedMeters | **savedMeters** | perOrderPlannedMeters | poolingGainMeters |
|---|---|---|---|---|---|
| **界面真实请求体**（`batches:[]`） | **0** | **0** | **0** | **0** | **0** |
| 带逐行指派 + fifo | 105 | 60 | **45** | 105 | **45** |

- **J4 成立（预览不说谎）**：带指派时 `preview.savedMeters = 45` 与 B 臂落账 `Σsaved = 45.00` **逐值相等**。
- 但界面路径下**五个米数全是 0** —— 商家在「智能派单」页看到的「预计节省」**恒为 0.00**。

---

## 五、根因（代码级，链条闭合）

1. 界面请求体：`frontend/admin-web/src/lib/pool-board.ts::buildPoolRequest` 恒返回
   `{orderIds, batches: [], assignmentRule: null, pooled}`，`pool-page.tsx` 的
   `dispatchBatch()`（一键成批）与 `dispatchSingle()`（加急插队）**都用它**。
2. 服务端：`ProcessingOrderService::prepare` → `buildDesignations(items, snapshot, assignments, …)`，
   而该方法开头即 `if (assignments == null || assignments.isEmpty()) return List.of();`
   ⇒ **无指派 = 无 Designation**。
3. 于是 `generatePooled` 里 `pooledLines` 为空 ⇒ `deductionsByItemId(...)` 走
   `pooledLines.isEmpty() ? Map.of() : …` ⇒ **`plan`（排料求解器）一次都不调**。
4. ⇒ 不落 `stock_batch_consumptions`、不排料、`saved = 0`；加工单照常生成（工序正常）。
   这也是 `preview` 五个米数全 0 的原因（预览与派单共用同一条准备链）。

**唯一会自动指派 + 池化的路径是「自动成批」**（`ProcessingOrderService::assignmentsOf` 造「有行、batchNo 留空」
的指派交给规则补位 + `pooled=true`），但它由**服务级配置** `migao.production.auto-batch.enabled` 控制，
**缺省关**（`AUTO_BATCH_DEFAULT_ENABLED = false`）。本轮实测：300 单确认支付后**全部滞留在池里**未被自动派走，
说明 dev 环境该开关为关（`out/main.json::pool.orderCount = 300`）。

---

## 六、工序 × 工艺路线（300/300）

**判据**：把「配置」展开成期望序列，再与实得逐字全序比较 —— 期望**不是**从实得结果反推的。

期望来源：租户默认模板 `production_route_templates`（`is_default=true`）的 `mainline`
＋ 命中的条件工序 `production_route_rules`（`craft='韩褶'` ⇒ `韩褶` 插在锚点「三边」后、`上车布` 插在锚点「韩褶」后，
规则级 `position='布帘'` 限定）。

| 判据 | 读数 |
|---|---|
| 期望序列（配置展开） | `精裁 > 三边 > 韩褶 > 上车布 > 熨烫 > 定型 > 复烫 > 车被 > 外帘打卷 > 打包 > 外帘装袋 > 外帘发货` |
| 实得序列（300 张单**唯一签名**） | `精裁-布 > 布三边 > 韩褶-布 > 上车布-布 > 熨烫-布 > 定型-布 > 复烫-布 > 布帘车被 > 外帘打卷 > 打包 > 外帘装袋 > 外帘发货` |
| **判据 R1~R6** | **300 / 300 pass，0 fail** |
| R7 签名唯一性 | `seqSignatureSet` 长度 = **1**（300 张单工序逐字一致，无随机） |
| `route_key` / `route_source` | 全为 **`窗帘工序路线（默认）`** / **`direct`**（= 请求的两维直读命中） |
| 工序行总数 | **3600** 行（300 × 12），全部命中工序库活跃行、`group_name`/`unit` 与工序库逐字相等、部位内 `seq` 连续 1..12 |
| **判别力自证（红证）** | 注入式：把主线里的「打包」摘掉重算期望 ⇒ **同一判据 300/300 报红**（`redProof.poFlagged=300/300`） |

**判据自证（为什么不是自我循环）**：`harness/judge-selftest.mjs` 先用**已落盘的真实签名**把期望函数跑通
（`missing=[] / extra=[]`、锚点插入后**全序相等**），再去跑主实验；期望函数只读 `production_route_templates` /
`production_route_rules` / `production_operations` 三张配置表，不读实得行。
逐字口径的权威判据是仓内冻结快照测试（见 §7），本判据是**结构**层。

---

## 七、确定性层（真库，非 mock）

`cd backend/admin-api && ./mvnw -Dtest='PooledDispatchRealDbTest,BatchConsumptionCuttingPlanRealDbTest,ProductionRouteParityTest' test`

| 测试类 | 读数 | 钉住的不变式 |
|---|---|---|
| `PooledDispatchRealDbTest` | **Tests run: 4, Failures: 0** | 跨订单并排 ⇒ Σ(−delta)=3（对照逐单=6）/ 跨批次不成组 / 幂等闸 23505 + 注入式红证 |
| `BatchConsumptionCuttingPlanRealDbTest` | **Tests run: 5, Failures: 0** | 并排扣 3 不扣 6 / 不可并排逐值守公式 / 快照均价 / 两聚合逐值相等 |
| `ProductionRouteParityTest` | **Tests run: 6, Failures: 0** | 9 组合逐字 = 冻结快照 `RoutingModelFixture::DEPOSITIONED_ROUTINGS` / 规则级 position 承重 / priority 序敏感 |

⇒ 「省料算法」与「工序 × 路线展开」在**确定性层**本来就被钉住；本轮活环境读数是它的**端到端印证**，
两者不冲突：**算法对、接线断**。

---

## 八、问题清单

| # | 级别 | 问题 | 证据 | 归因 |
|---|---|---|---|---|
| **P0** | 产品缺陷（用户可见） | 「智能派单」页一键成批派单**不指派批次** ⇒ 零扣减、零排料、零省料；页面「预计节省」恒 0.00；#5169 的核心收益（跨订单并排）**从界面不可达** | A 臂：`consumptions` 0 行、`saved=0`；`previewUI` 五个米数全 0 | 界面请求体 `batches:[]`（`pool-board.ts::buildPoolRequest`）× 服务端 `buildDesignations` 空指派早返回 —— **两侧各自都「符合自己的契约」，接起来就断了** |
| P1 | 观察项（非缺陷） | 每行按 0.1 米向上归一，使 75 单的实际节省 45 米 < 理论 51.8 米 | B 臂 60.00 = 75×0.80 | 设计口径（少领 = 裁床切不出货），**有意接受** |
| P2 | 观察项（非缺陷） | 「自动成批」是唯一自动指派 + 池化的路径，但服务级缺省关 | `AUTO_BATCH_DEFAULT_ENABLED=false`；本轮 300 单未被自动派走 | 缺省关是有意（记录期基线）；**但 UI 路径断链后，它成了省料的唯一入口** ⇒ 与 P0 合并看 |

**已开单**：P0 → issue **#6408**（含逐条读数、根因链、复算命令、应会红的冻结判据、三个修法选项与代价；
「池化派单该不该替商家自动挑批次」属**业务口径**，交人工裁定；不裁时的安全默认动作 = 维持行为、
先修「0.00 是未测量而非省了 0」的读数误导）。

### 边界（如实登记，不粉饰）

- 本轮是**云 dev 活环境**读数（坐标 `73327161f`，与 `origin/main` 派单面零 diff）——
  它是**单租户、单商品、单批次、单几何**的对照实验，不构成「所有几何都能省 42.9%」的结论。
- **未覆盖**：省料看板（`savingBoard`）对这笔 45 米/1800 元的读数未做页面级核对；
  自动成批路径（服务级开关）未开启实测；加急插队 / 到货日排序未在本轮重测（有既有判据与
  `acceptance/2026-10-03/dispatch-routing-sweep` 的 44 场景矩阵在前）。
- A/B/C/D 各 75 单是**分组对照**（几何同分布），不是同一批单跑两遍（同一批单只能派一次）。

---

## 九、残留与清理

`cleanup('SD06省料')` 后**现取读数全 0**：
`orders=0 / processing_orders=0 / stock_batch_consumptions=0 / product_skus=0 / stock_batches=0 /
products=0 / categories=0 / processing_position_operations=0`（`out/main.json::residue`）。
清理顺序按 FK 实测确定（先 `worker_report_audits` / `production_work_logs` / `processing_order_sets` 等子表）。

---

## 十、产物

- `BRIEF.md` 任务书 · `harness/recon.mjs` 只读侦察 · `harness/steps.mjs` 探针步骤库 ·
  `harness/judge-selftest.mjs` 判据自证 · `harness/pilot.mjs` 6 单试跑 · `harness/main.mjs` 300 单四臂主实验
- `out/recon.json` / `out/main.json` / `out/main4.log` / `out/pilot.json`
