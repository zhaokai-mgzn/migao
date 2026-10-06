# 2026-10-06 智能派单「是否真省料」验证 · 任务书（承载体）

> 用户 2026-10-06 10:30 +08 逐字要求：「我现在要验证智能派单功能是否真正智能的可以节省用料，
> 我要求你现在模拟用户批量下有一批 300 个订单，然后验证智能派单功能和生成的加工单工序和配置的
> 工艺路线是否能匹配上，且是否真正的能节省生产原材料布料」。
>
> 本文件是**执行规格的承载体**（铁律 12(d)：规格不得只活在会话上下文里）。
> 协议 = `migao-acceptance`（四态 + 红证 + 证据链 + 不自我验收）；流程 = `migao-dev-flow`。
> 时间口径：一律 **Asia/Shanghai（+08）**。

## 0. 被测对象与坐标

| 项 | 值 | 证据 |
|---|---|---|
| 被测环境 | 云 dev：admin-api `https://api.migaozn.com` / admin-web `https://merchant.migaozn.com` | `harness/recon.mjs` 全部读端点 200 |
| 被测租户 | `tenant_id = 25`（`code=shop-8yn7`，管理员 `13800138000`） | `out/recon.json` |
| DB | 云 dev RDS（psql 直读/直写，**只写本轮的 `SD06省料` 探针对象**） | `acceptance/2026-10-06/harness/lib.mjs::psql` |
| 被测链路 | `POST /api/admin/production/pool/{preview,dispatch}` → 加工单 + 工序实例 + 批次消耗台账 | 见 §2 |
| 起点读数 | tenant 25：orders=2 / processing_orders=0 / stock_batch_consumptions=0 / production_routings=0 / route_templates=2 / route_rules=27 / operations=41 | `out/recon.json::psql.counts` |

**先例复用（不重造）**：`acceptance/2026-10-03/dispatch-routing-sweep/REPORT.md` 已在 tenant 20 用
44 场景派工矩阵把「工序 × 工艺路线设置」逐字全序验过（93 pass / 6 fail）。本轮**不重跑那张矩阵**，
只针对 300 单批量场景做**回归式**工序比对（§3）。

## 1. 起手侦察钉住的三个事实（决定了实验设计）

来自 `acceptance/2026-10-06-pooling-savings/harness/recon.mjs` + 代码读面：

1. **池化开关是「逐次请求参数」**（`ProcessingOrderService::pooledEnabled` / `POOLED_DEFAULT_ENABLED=false`），
   而**自动成批是服务级配置**（`@Value("${migao.production.auto-batch.enabled:false}")`）。
   ⇒ 实验可以用**同一个端点、同一个租户**做单变量 A/B，**不需要改任何配置、不需要部署**。
2. **排料省料的前置 = 真的指派了批次**：`ProcessingOrderService::buildDesignations` 在 `assignments`
   为空时直接 `return List.of()` ⇒ `StockBatchConsumptionService::plan` 一次都不调 ⇒ 无扣账、无排料、`saved=0`。
3. **界面路径从不指派批次**：`frontend/admin-web/src/lib/pool-board.ts::buildPoolRequest` 恒返回
   `{orderIds, batches: [], assignmentRule: null, pooled}`——「智能派单」页的**一键成批派单**与
   **加急插队派单**都走它。

## 2. 四臂单变量对照（300 单）

造 300 张**几何完全相同**的订单（探针商品 × 1 个 SKU × 1 个入库批次 6000 米），已确认收款，分 4 臂各 75 张：

几何（`CuttingPlanCalculator` 类注释里的「定宽买高 P=1 窄窗互补」受益场景）：
窗宽 0.7 × 褶倍 2 = **1.4 米** ≤ 门幅 **2.8 米** ⇒ 1 幅；窗高 1.1 + 卷边 0.3 = **1.4 米**
⇒ 每行占门幅 1.4 米、沿卷长 1.4 米 ⇒ **两行并排 = 1 行（领 1.4 米），分开 = 2 行（领 2.8 米）**。

| 臂 | 请求体（唯一变量） | 期望 |
|---|---|---|
| **A 界面路径** | `{orderIds×75, batches:[], assignmentRule:null, pooled:true}`（逐字 = `buildPoolRequest`） | 建加工单；**零消耗行、saved=0** |
| **B 直调池化** | `batches:[{orderId,itemId}×75]`（batchNo 留空）+ `assignmentRule:'fifo'` + `pooled:true` | 跨订单并排 ⇒ **saved > 0** |
| **C 直调逐单** | 同 B 的指派 + `pooled:false` | 逐单各排一次 ⇒ **saved = 0** |
| **D 订单页路径** | `POST /api/admin/processing-orders/generate`，**一次一张** + 显式 `batchNo`（= `ProcessingOrderBlock::confirmAssign` 形态） | 单订单内无可并排 ⇒ **saved = 0** |

**判据（每条都会红）**：
- J1 池化省料真实存在：`B.saved > 0` **且** `B.saved > C.saved`（红证 = 把 `pooled` 置 false，省料消失 = C 臂）。
- J2 界面路径拿不到省料：`A.ledger.rows == 0` 且 `A.saved == 0`（红证 = 同一批单换 B 体 ⇒ 立刻有行）。
- J3 省料不虚报：`Σplanned ≤ Σformula` 逐行成立、`planned > 0`（DB 约束 `ck_batch_consumption_plan_meters`）。
- J4 预览不说谎：`preview.savedMeters == B 落账 Σsaved`。

## 3. 工序 × 工艺路线 比对（300 张加工单全覆盖）

对每张派出的加工单，读 `processing_position_operations` 逐行，与租户**配置的默认路线模板**
（`production_route_templates` where `is_default`）比对：

| 判据 | 内容 | 红证 |
|---|---|---|
| R1 | 每张单至少 1 道工序 | 空行 ⇒ 红 |
| R2 | 同部位内 `seq` 连续 1..N | 断号 ⇒ 红 |
| R3 | 每道工序名必须在 `production_operations`（工序库）里有活跃行（无幽灵工序） | 注入假工序名 ⇒ 红 |
| R4 | 工序行的 `group_name` / `unit` 与工序库**逐字相等** | 改单位 ⇒ 红 |
| R5 | 默认路线模板 `mainline` 的每个逻辑工序都必须落到工序行（同名或其 `-布`/`布` 变体） | 注入「缺一道」的模板 ⇒ 同一判据**必须报红**（判别力自证） |
| R6 | `route_key` = 配置的模板名；`route_source` ∈ 四态合法集 | — |
| R7 | 300 张单的工序序列**逐字一致**（同输入同输出，无随机） | — |

## 4. 纪律

1. **不自我验收**：本轮只产**读数 + 判定 + 证据**，不写「验收通过」；结论由独立复核 AI 交叉验证。
2. **四态口径**：`pass` / `fail(产品)` / `skip(未覆盖)` / `假红(判据缺陷)`；skip 永不折算成 pass。
3. **写面只碰自己造的探针对象**（统一前缀 `SD06省料`），收尾 `cleanup()` 删净并给**残留现取读数**。
4. **不落活 token**：产物一律脱敏。
5. **不跑** `verify-all.sh gate` / 全量 pytest（机器级重活锁，§27）。
6. **归因强度匹配证据强度**：本轮是**云 dev 活环境**读数，不构成对 main 的确定性结论；
   确定性层引用既有 RealDb 判据（`PooledDispatchRealDbTest` 等，见 §5）。

## 5. 产物

- `harness/recon.mjs`（只读侦察）、`harness/steps.mjs`（探针步骤库）、`harness/pilot.mjs`（6 单试跑）、
  `harness/main.mjs`（300 单四臂主实验）
- `out/recon.json` / `out/pilot.json` / `out/main.json` / `out/main.log` / `out/REPORT.md`
