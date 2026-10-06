## 现象（2026-10-06 实测，300 单四臂对照）

「智能派单」页（`/production/pool`）**一键成批派单**与**加急插队派单**发出的请求体恒为
`{orderIds, batches: [], assignmentRule: null, pooled: true}`（构造点唯一：
`frontend/admin-web/src/lib/pool-board.ts::buildPoolRequest`，页内 `dispatchBatch` / `dispatchSingle` 都调它）。

服务端 `ProcessingOrderService::buildDesignations` 在 `assignments` 为空时直接返回 `List.of()`
⇒ 没有 `Designation` ⇒ `generatePooled` 里 `pooledLines` 为空 ⇒ `StockBatchConsumptionService::plan`
（排料求解器）**一次都不调** ⇒ **不落 `stock_batch_consumptions`、不排料、`saved = 0`**。

⇒ **「智能派单」页拿不到 #5169 的核心收益（跨订单一起排料）；页面上「预计节省」恒为 0.00。**

## 实测读数（云 dev，tenant 25，部署 sha `73327161f`）

造 300 张**几何完全相同**的可并排订单（窗宽 0.7×褶倍 2 = 1.4 米 ≤ 门幅 2.8；窗高 1.1+卷边 0.3 = 1.4 米
⇒ 两行并排 = 领 1.4 米，分开 = 领 2.8 米），已确认收款，分 4 臂各 75 张，**唯一变量 = 派单请求体**：

| 臂 | 请求体 | 消耗行 | Σformula | Σplanned | **Σsaved** |
|---|---|---|---|---|---|
| A | 界面真实请求体（`batches:[]`，`pooled:true`） | **0** | 0 | 0 | **0** |
| B | 逐行指派 + `assignmentRule:'fifo'` + `pooled:true` | 75 | 105.00 | 60.00 | **45.00 米 / 1800.00 元** |
| C | 同 B 指派 + `pooled:false` | 75 | 105.00 | 105.00 | **0** |
| D | 订单页「生成加工单」（一次一张 + 显式 batchNo） | 75 | 105.00 | 105.00 | **0** |

300 单派出 300/300 成功、0 失败。

成批预览（用户在页面上直接看到的数）：

| 请求体 | formulaMeters | pooledPlannedMeters | savedMeters | perOrderPlannedMeters | poolingGainMeters |
|---|---|---|---|---|---|
| **界面真实请求体** | **0** | **0** | **0** | **0** | **0** |
| 带逐行指派 + fifo | 105 | 60 | **45** | 105 | **45** |

⇒ 算法的省料是真的（B 臂 42.9%，预览与落账逐值相等 45 == 45），**但界面路径连一次扣料都不产生**。

## 影响

- 商家在「智能派单」页点「一键成批派单」→ 加工单建出来了、工序也对，**但一张单都没领料**：
  批次账面不动、省料看板不涨、`saved_meters` 全 0。
- #5169 明写的收益场景（「两张单各一扇 1.1 米高的矮窗 ⇒ 从 2 行 6 米变成 1 行 3 米」）
  **从界面不可达**。
- 唯一会自动指派 + 池化的路径是**自动成批**（`assignmentsOf` 造「有行、batchNo 留空」的指派 +
  `pooled=true`），但它由服务级配置 `migao.production.auto-batch.enabled` 控制、**缺省关**
  ⇒ 缺省配置下，界面用户拿不到任何跨订单省料。

## 根因链（代码符号，行号不写）

1. `frontend/admin-web/src/lib/pool-board.ts::buildPoolRequest` → `batches: []` / `assignmentRule: null`；
2. `ProcessingOrderService::prepare` → `buildDesignations(items, snapshot, assignments, …)`；
3. `ProcessingOrderService::buildDesignations` 开头 `assignments == null || isEmpty ⇒ return List.of()`；
4. `ProcessingOrderService::generatePooled` 里 `pooledLines.isEmpty() ? Map.of() : …` ⇒ 不调 `plan`；
5. `ProcessingOrderService::preview` 同一条准备链 ⇒ 预览五个米数全 0。

## 复算命令（零成本）

```bash
cd acceptance/2026-10-06-pooling-savings/harness && N=300 node main.mjs   # 全量四臂复跑（云 dev，收尾自动清理）
node judge-selftest.mjs                                                   # 判据自证（期望序列来自配置表，不读实得行）
```
读数与证据：`acceptance/2026-10-06-pooling-savings/out/REPORT.md`、`out/main.json`。

## 冻结判据（应会红）

- A 臂：`stock_batch_consumptions` 中该批订单的行数 = **0**（红证 = 换成 B 体 ⇒ 立刻 75 行）；
- 界面体的 `POST /production/pool/preview` ⇒ `savedMeters == 0`（红证 = 带指派 ⇒ 45）；
- 修好之后：界面一键成批派单必须**产生扣料行**，且 `preview.savedMeters == Σ(saved_meters)`（这两条既有判据 PR-070/PR-071 已经钉住，缺的只是「界面把指派带上」）。

## 待裁定（业务口径，需人答）

**「池化派单该不该替商家自动挑批次？」** 这条决定修法方向，三种选项与代价：

| 选项 | 形态 | 代价 / 风险 |
|---|---|---|
| **① 池化派单带 `assignmentRule`（推荐）** | 界面在 `pooled:true` 时带 `assignmentRule:'fifo'`（缺省策略）+ 空 batchNo，由服务端按规则补位 | 改变了「派单即领料」的既有语义（现在界面派单**不**领料）；`#5145` 记录期基线「不指派 ⇒ 不扣」的**界面默认**被改；错挑批次会被 SKU 护栏拦（`#5174`），但仍需商家认可「自动挑批次」 |
| ② 页面加批次选择 | 勾单后逐行选批次（像订单页那样） | 300 单要选 300 次，与「一键成批」的卖点冲突；只解决一半（还是逐单视角） |
| ③ 保持现状 | 省料只在「订单页逐单 + 指定批次」发生 | #5169 的跨订单收益继续不可达；页面「预计节省」应改成显示「未领料 ⇒ 无节省」而不是 0.00（否则是静默误导） |

**不裁时的安全默认动作**：维持现状（不改行为），但先修**读数误导**那一半 ——
页面上「预计节省 0.00」在**没有指派**时属于「未测量」而非「省了 0」，应按本仓既有口径
（`#5159`「没有数据就写『无数据』，不写 0」）显示为**未领料/未测量**。

## 边界（如实登记）

- 本轮为**云 dev 活环境**单租户/单商品/单批次/单几何对照实验，不构成「所有几何都省 42.9%」的结论；
- 未覆盖：省料看板对该笔省料的页面级核对、自动成批开启后的实测、加急/到货日排序本轮未重测
  （既有 `acceptance/2026-10-03/dispatch-routing-sweep` 44 场景矩阵在前）。
