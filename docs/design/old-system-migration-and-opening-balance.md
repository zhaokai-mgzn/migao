# 旧系统 → MIGAO 数据导入能力盘点 + 期初批次导入口径

> **本页定位**：issue #5149 的交付物。**只调研 + 设计，不含任何代码改动、不含迁移文件**。
> **上游口径**（已记档，本页只消费不重开）：#5145（批次消耗台账 + 余量读面 + 剩余量分布）、#5063（库存米数小数化）、#5045（入库单模块）。
> **用户原话**（本单的存在理由）：「未来从旧系统切到新系统时需要把数据导入到 migao，并且从 migao 系统录入库单」。

---

## 0. 本页的读法（引用纪律 + 事实分级）

- **引用一律给仓库相对全路径 + 可检索符号名（函数名 / 类名 / 端点 / 常量 / 可 grep 的中文原文）**。
- 🔴 **本页不写任何行号**。活跃文件的行号几分钟就失效；`Drift Audit` 的 `ref-freshness` 与 `Case Trust` 的规则 G（实现见 `.github/case_trust_gate.py` 的 `check_reference_freshness_in_diff`，引用扫描器见 `.github/assertion_taxonomy.py` 的 `find_path_line_refs`）都会判红。
- **事实分级**：本页每一行标 `【核】`（我在当前工作区检出上**实际读到**的代码/SQL/文档）或 `【推】`（我的推断/建议，未经执行验证）。
  第 6 节把两者再集中列一遍。
- **基线**：本页所有 `【核】` 基于分支 `docs/migration-import-inventory`，其基线为 `origin/main` 的 `0a7c183af`（`fix(inbound): #5141 多行入库单过账批次号逐行生成`）。

---

## 1. 结论摘要（TL;DR）

1. **【核】MIGAO 目前没有任何一条"能把旧系统数据整批搬进来"的产品化通路。** 全仓可检索的批量导入入口 = **0 个**；`frontend/admin-web/src` 里 `导入` 二字**只出现在一处注释**里（`frontend/admin-web/src/app/(dashboard)/production/page.tsx`，且是"迁入"的历史说明，不是功能）。导出侧相反：商品导出是**有端点、有前端按钮**的完整链路。
2. **【核】唯一的"看起来像商品导入"的实现是死代码。** `backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java` 的 `importProducts`（POI 解析 Excel 批量建商品）、`generateImportTemplate`（下载导入模板）、`parseProductFromRow`（逐行解析）**都没有 HTTP 入口** —— `backend/admin-api/src/main/java/com/migao/admin/controller/ProductController.java` 只有 `@GetMapping("/export")`（→ `exportProducts`），**没有** import 相关 `@*Mapping`；全仓 `importProducts` 的引用只剩定义自身与 DTO 单测 `backend/admin-api/src/test/java/com/migao/admin/dto/DtoTest.java`。**它不是"可复用的既有能力"，是"没接线的半成品"。**
3. **【核】期初批次有唯一合规载体：入库单。** `backend/admin-api/src/main/resources/db/migration/V111__create_inbound_orders_and_batches.sql` 定死「批次只能由入库产生；批次行**不可改**；冲销走新单据，不删批次行」。⇒ 期初批次**必须**由一张**期初入库单**（`inbound_orders` 的 `source='opening'` 形态）承载，落地序列 = `POST /api/admin/inbound-orders`（建草稿）→ `PATCH /api/admin/inbound-orders/{id}`（过账）。**这条路完全不需要破坏 V111**，因为期初批次本来就是"切换那一刻收货"。
4. **🔴【核】当前代码**无法**承载期初批次的两个必需要素**：
   - **旧系统批次号无处落**：`InboundOrderService` 的批次号是**服务端生成**的 `PC-yyyyMMdd-NNNN`（`generateBatchNo` / `nextFreeBatchNo`），请求 DTO `backend/admin-api/src/main/java/com/migao/admin/dto/InboundOrderCreateRequest.java` 的 `Item` **没有 `batchNo` 字段** ⇒ 旧系统批次号只能被塞进 `dye_lot` 或 `remark`（借用语义 / 无唯一索引）。
   - **小数米进不来**：`inbound_order_items.quantity` / `stock_batches.quantity` / `product_skus.stock` 三层全 `INT`，且 `InboundOrderCreateRequest.Item.quantity` 是 `Integer`、服务端**显式拒绝**非整数（`InboundOrderService` 的校验 + 翻译文案「小数会被显式拒绝」）。
5. **🔴【核】任务书里「库存已改 1 位小数」这个前提，在当前 `origin/main` 上不成立。** `docs/sql/schema.sql` 的 `product_skus.stock` 仍是 `INTEGER NOT NULL DEFAULT 0`；`git log origin/main --grep=5063` 无命中；#5063 的实现是 `gh pr view 5147` 显示的 **DRAFT、未合并** PR（`feat(product): #5063 库存米数小数化（1 位小数）—— 三层 INTEGER 一并升级`，head `feat/5063-stock-decimal-1dp`，`state=OPEN`、`isDraft=true`、`mergedAt=null`）。⇒ 第 3.6 节的精度口径**必须同时给出"#5063 已合"与"#5063 未合"两种分支**，否则本页会沦为一份基于错前提的设计。
6. **【推】本单新增代码的最小充分集**：1 个迁移（`inbound_orders` 2 列 + `stock_batches` 1 列 + 部分唯一索引）+ 1 个导入器服务 + 1 个上传端点 + 1 个前端页。**不需要**新建"基线快照表"（理由见 §3.5：批次行不可变 + #5145 已裁定"余量派生、不原地改"⇒ 基线可**永久复算**）。

---

## 2. 现状盘点表

### 2.1 汇总表

`小数米` 列 = 「这条路径能不能承载 0.5 米 / 60.5 米」。#5063 未合之前，库存侧的答案一律是**不能**。

| # | 能力 | 有没有导入路径 | 证据锚点（仓库相对全路径 + 符号/文本） | 小数米 |
|---|---|---|---|---|
| 1 | **商品（主数据）** | ⚠️ 单条有 / **批量无** | 单条：`POST /api/admin/products` → `backend/admin-api/src/main/java/com/migao/admin/controller/ProductController.java` 的 `createProduct` → `ProductService.createProduct`。批量：`ProductService.importProducts` **无端点**（见 §2.2.1） | ❌ `ProductCreateRequest.stock` 是 `Integer` |
| 2 | **SKU（颜色 × 门幅）** | ⚠️ 随商品单条建 / **批量无** | `backend/admin-api/src/main/java/com/migao/admin/dto/ProductCreateRequest.java` 的 `colors` / `doorWidths` / `skus`；落库 `ProductService` 里 `productSkuMapper.insert(entity)`；DTO `backend/admin-api/src/main/java/com/migao/admin/dto/ProductSkuInput.java`、`ProductColorInput.java` | ❌ `ProductSkuInput.stock` 是 `Integer`；`product_skus.stock` 是 `INTEGER`（`docs/sql/schema.sql`） |
| 3 | **客户** | ❌ **无建档端点** / ✅ 有**自动建档** | 无：`backend/admin-api/src/main/java/com/migao/admin/controller/CustomerController.java` 全文只有 `@GetMapping` / `@PutMapping` / `@DeleteMapping` + 标签 CRUD，**没有 `@PostMapping` 建档**。自动：`backend/admin-api/src/main/java/com/migao/admin/service/CustomerService.java` 的 `createFromOrder`（按 `phone + tenantId` 去重，存在则只刷 `lastActiveAt`），由 `OrderService.createOrder` 末尾调用 | 不涉及 |
| 4 | **订单（历史单）** | ❌ 批量无 / ⚠️ 单条有但**带库存副作用** | 单条：`POST /api/admin/orders` → `OrderController` → `OrderService.createOrder`（内含 `validateStockSufficientForRequest` 前置库存校验）；Agent 路径 `OrderService.createOrderForAgent` | ✅ `order_items.quantity` 已是 `DECIMAL(10,2)`（`backend/admin-api/src/main/resources/db/migration/V45__widen_order_items_quantity_to_decimal.sql`，issue #3666） |
| 5 | **库存（SKU 账）** | ❌ 无导入 / ⚠️ 有手工调整 | `backend/ai-agent-service/app/tools/inventory_manage.py` 的 `VALID_ACTIONS` = `{query, adjust, low_stock_alert}`，`adjustment` 为整数；无批量 | ❌ `INTEGER` |
| 6 | **批次（实物账）** | ✅ **有合规通路**（逐单，非批量） | `POST /api/admin/inbound-orders` + `PATCH /api/admin/inbound-orders/{id}` → `backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java` 的 `create` / `post` / `cancel`；端点权限 `inbound:create` / `inbound:view`（`InboundOrderController`） | ❌ `stock_batches.quantity` 是 `INT NOT NULL`；`InboundOrderCreateRequest.Item.quantity` 是 `Integer` |
| 7 | **工艺与工序配置** | ⚠️ **平台预置模板可套用** / ❌ 商家自有配置无导入 | `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionSeedTemplateController.java` 的 `GET /api/admin/production/seed-templates` + `POST /api/admin/production/seed-templates/{templateId}/apply` → `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java` 的 `applyTemplate` / `applyTemplateNode`；模板资产 `backend/admin-api/src/main/resources/production-templates/index.json` 与 `production-templates/curtain`；开租自动套用见 `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` | 不涉及（算料用料米数已向上进位到 0.1，issue #4527） |
| 8 | **工序 / 加工项（单条）** | ⚠️ 单条 CRUD / 批量无 | `ProductionController` 的 `/operations`、`/routings`、`/route-rules/**`；`ProcessingItemController`（`/api/admin/processing-items`）；`ProcessingCategoryController`（`/api/admin/processing-categories`） | 不涉及 |
| 9 | **算料参数配置** | ❌ 无导入（只有读写） | `backend/admin-api/src/main/java/com/migao/admin/controller/CraftCalcConfigController.java` 的 `GET` / `PUT /api/admin/production/craft-calc-config` | 不涉及 |
| 10 | **员工（账号）** | ⚠️ 单条有 / 批量无 | `backend/admin-api/src/main/java/com/migao/admin/controller/AdminUserController.java`（`POST /api/admin/users`、`PUT`、`DELETE`、`/reset-password`、`/status`）；Agent 侧同为单条：`backend/ai-agent-service/app/tools/employee_manage.py` 的 `VALID_ACTIONS` | 不涉及 |
| 11 | **岗位 / 权限码** | ⚠️ 开租自动种子 / 批量无 | 岗位（=角色）：`backend/admin-api/src/main/java/com/migao/admin/controller/AdminRoleController.java` 单条 CRUD；权限码**只读**：`AdminPermissionController` 只有 `@GetMapping`；开租种子：`RegistrationService` 的 `attachDefaultPermissions`（默认 5 岗位 `admin` / `customer_service` / `operator` / `sales` / `finance`）+ 日志「新租户默认岗位和权限初始化完成」 | 不涉及 |
| 12 | **工人档案（工号）** | ❌ **连单条写入都没有** | 档案 = `users` 行 + `users.worker_no`（`backend/admin-api/src/main/resources/db/migration/V98__create_worker_sessions_and_worker_no.sql`，issue #4733）；**写面缺失**：全 `backend/admin-api/src/main/java` 内 `workerNo` / `worker_no` 的命中只有 `backend/admin-api/src/main/java/com/migao/admin/mapper/UserMapper.java` 的两条 `SELECT`；`WorkerSessionService.findWorkerByNo` 只**读**；`WorkerAuthController` 只有 `/login`、`/session/*` | 不涉及 |

### 2.2 逐项证据展开

#### 2.2.1 商品 Excel 导入 = 未接线的死代码（本单最容易误判的一条）

**【核】存在的部分**（`backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java`）：

- `importProducts(MultipartFile file, Long tenantId)` —— `WorkbookFactory.create` 解析首个 sheet，**首行**当表头，逐行 `parseProductFromRow` + `productMapper.insert`，返回 `ProductImportResult`（总行数 / 成功 / 失败 / 逐行错误）。
- `generateImportTemplate(HttpServletResponse response)` —— 生成 `商品导入模板.xlsx`，表头 `{"商品名称*", "货号", "分类ID", "价格*", "库存", "描述"}`。
- `parseProductFromRow` —— 只解析 6 列；`product.setStatus("draft")`；`stock` 走 `(int) getCellNumericValue(row, 4)`（**直接强转 int**）。
- DTO：`backend/admin-api/src/main/java/com/migao/admin/dto/ProductImportResult.java`。

**【核】缺失的部分**：`ProductController` 的映射清单里**没有**任何 import/template 端点（只有 `GET /api/admin/products/export` → `exportProducts`）。全仓检索 `importProducts` / `generateImportTemplate` / `ProductImportResult` 的调用方：

- `ProductService` 自身（定义处）
- `backend/admin-api/src/test/java/com/migao/admin/dto/DtoTest.java`（DTO 单测）
- **没有 controller、没有 service 调用方、没有前端、没有 agent tool。**

**【推】结论**：这是**不可复用的既有能力**。它可以当"解析器写法参考"，但**不能当"已经有导入"**记入盘点；把它算作"有"会让缺口清单少一条 P0。另外它的字段面（6 列、无颜色 / 无门幅 / 无 SKU / 无缸号）**根本不覆盖期初批次需要的映射键**，即使把端点接上也不够用。

#### 2.2.2 导出侧是完整链路（对照组，说明"有"长什么样）

**【核】**`GET /api/admin/products/export` → `ProductController.exportProducts` → `ProductService.exportProducts`（XSSFWorkbook 写出 7 列）；前端 `frontend/admin-web/src/lib/api.ts` 的 `productApi.exportProducts`（`responseType: 'blob'`）由 `frontend/admin-web/src/app/(dashboard)/products/page.tsx` 调用。
⇒ 「有产品化通路」在本仓的判据 = **端点 + service + 前端 API + 页面按钮**四件齐。按此判据，导入侧 **0 条**达标。

#### 2.2.3 入库单是唯一"批次产生"通路（期初批次的载体，本页核心）

**【核】端点**（`backend/admin-api/src/main/java/com/migao/admin/controller/InboundOrderController.java`，类级 `@RequestMapping("/api/admin/inbound-orders")`）：

| 方法 | 端点 | 权限码 | 用途 |
|---|---|---|---|
| `list` | `GET /api/admin/inbound-orders` | `inbound:view` | 单头列表（`keyword` / `status` 过滤） |
| `batches` | `GET /api/admin/inbound-orders/batches` | `inbound:view` | **批次读面**（`skuId` / `dyeLot` / `inboundNo` 过滤） |
| `create` | `POST /api/admin/inbound-orders` | `inbound:create` | 建**草稿**（不动库存） |
| `detail` | `GET /api/admin/inbound-orders/{id}` | `inbound:view` | 单头 + 明细 |
| `act` | `PATCH /api/admin/inbound-orders/{id}` | `inbound:create` | 过账 / 作废 |

**【核】服务侧关键行为**（`InboundOrderService`）：

- `create` —— 校验后落 `inbound_orders`(draft) + `inbound_order_items`；`generateInboundNo()` 产 `RK-yyyyMMdd-NNNN`；明细行草稿态 `batch_no` 为 `NULL`。
- `post(rawId, tenantId, operator)` —— **幂等闸**：`if (!InboundOrder.STATUS_DRAFT.equals(order.getStatus())) throw BusinessException.conflict(...)`，文案「已过账的入库单不得重复过账（库存只加一次）；如需冲销请另开单据」。逐行：`nextFreeBatchNo(tenantId)` 生成批次号 → `productSkuMapper.receiveStock(skuId, quantity, afterAvg, batchNo)` → `stockLedgerService.record(..., StockLedger.REASON_INBOUND, order.getInboundNo(), ...)` → `stockBatchMapper.insert(StockBatch.builder()...)` → 回写行 `batch_no` → `syncProductStock(productId)`。
- `cancel(rawId, reason, ...)` —— **仅草稿可作废**；已过账不得作废（「冲销必须另开单据（留痕）」）。
- `movingAverage(beforeQty, beforeAvg, quantity, unitCost)` —— 移动加权平均；`unitCost == null` ⇒ **只加数量，均价保持原值**（不猜、不抹）。
- `nextFreeBatchNo(tenantId)` —— 注释逐字登记了 `uk_stock_batches_no` 撞号问题与 issue #5141 的修法（**逐行**生成号）。
- `list` / `batches` 各有 `LIST_LIMIT` / `BATCH_LIMIT` 常量（**读面是分页/截断的**，导入后的核账读面要留意上限）。

**【核】表结构**（`backend/admin-api/src/main/resources/db/migration/V111__create_inbound_orders_and_batches.sql`，终态同步在 `docs/sql/schema.sql`）：

- `inbound_orders`：`id` / `tenant_id` / `inbound_no`（`uk_inbound_orders_no` 唯一）/ `supplier` / `supplier_doc_no` / `warehouse` / `inbound_date DATE NOT NULL DEFAULT CURRENT_DATE`（列注释逐字「业务日期，**可回填历史单**」）/ `status`（`draft` / `posted` / `cancelled`）/ `total_amount` / `remark TEXT` / `posted_at` / `posted_by` / `cancelled_*` / `created_by` / 时间戳 / `deleted`。
- `inbound_order_items`：`sku_id` / `product_id` / `sku_code` / **`color_name`** / **`door_width`** / `quantity INT NOT NULL` / `unit_cost NUMERIC(12,4)` / `amount` / `batch_no VARCHAR(32)`（**过账时才写**）/ `dye_lot VARCHAR(64)` / `roll_length_m NUMERIC(8,2)` / `remark`。
- `stock_batches`：`batch_no VARCHAR(32)`（`uk_stock_batches_no` = `UNIQUE (tenant_id, batch_no)`）/ `product_id` / `sku_id` / `sku_code` / `inbound_order_id` / `inbound_item_id` / `inbound_no` / `quantity INT NOT NULL` / `unit_cost` / `amount` / `dye_lot` / `roll_length_m` / `supplier` / `warehouse` / `received_date DATE`（= 入库单 `inbound_date`）/ `remark` / `deleted`。
  🔴 **`stock_batches` 没有 `door_width` / `color_name` 列**，只有 `sku_code` ⇒ 批次读面上的"门幅 / 色号"必须经 `sku_id → product_skus`（`product_skus.door_width VARCHAR(20) NOT NULL`、`color_id → product_colors.color_name`）解析，**不是批次行自带的事实**。
- `stock_ledger_entries.reason` 约束 `ck_stock_ledger_reason` 放行四类：`order` / `aftersales` / `manual` / **`inbound`**（`ref_no` = 入库单号或批次号）。
- `product_skus` 追加 `avg_cost NUMERIC(12,4)` / `cost_amount NUMERIC(16,4)` / `latest_batch_no VARCHAR(32)`；`stock_ledger_entries` 追加 `unit_cost` / `cost_amount` / `avg_cost_before` / `avg_cost_after` 四个成本快照列。
- 权限种子：`inbound:view`（挂 `customer_service` / `operator` / `sales` / `finance`）+ `inbound:create`（挂 `operator`），与 `RegistrationService` 种子目录同源。
- 文件头逐字登记的数量单位边界：「`quantity` / `delta` / `before_qty` / `after_qty` 均为 **INTEGER** … 布料按米入库时非整数米（如 60.5 米）**本单不支持** … ⇒ 服务端对非整数入库量**显式拒绝**，不静默取整」。

#### 2.2.4 库存台账读面

**【核】**`backend/admin-api/src/main/java/com/migao/admin/controller/StockLedgerController.java`：类级 `@RequestMapping("/api/admin/stock-ledger")`，只有一个 `@GetMapping`，权限码 `product:list`。**只读**，无导入。

#### 2.2.5 工艺 / 工序配置：模板是"平台预置"，不是"商家旧配置"

**【核】**`ProductionSeedTemplateService`：

- `listTemplates()` → `GET /api/admin/production/seed-templates`，返回 DTO `backend/admin-api/src/main/java/com/migao/admin/dto/ProductionSeedTemplateInfo.java`（`templateId` / `industry` / `name` / `version` / `description` / `operationCount` / `routingCount` / `optionCount`）。
- `applyTemplate(Long tenantId, String industry)` → `applyTemplateNode`：按 `IndustryCodes.normalize` 归一后找模板；找不到 ⇒ 返回 `applied=false` + **非空 `reason`**（逐字告知「不是套用失败，是本来就没有」+ 给出手动补套端点），**不静默不套**。返回体含 `created_operations` / `created_routings` / `created_options` / `skipped`。
- 模板资产：`backend/admin-api/src/main/resources/production-templates/index.json` + `production-templates/curtain`。
- 开租自动套用：`RegistrationService`（日志「开租套用生产种子模板」）。
- 单条读面：`ProductionController` 的 `GET /api/admin/production/operations-catalog` 与 `GET /api/admin/production/routings`。

**【推】结论**：这是**平台预置行业的模板套用**（#4361 交付物），**不是**"导入商家自己的旧工序/路线/规则"。旧系统的工序命名、路线树、条件规则、部位价目矩阵在本仓**没有映射器也没有映射表** ⇒ 属于**要重建**的范畴，不是"导入"的范畴（见 GAP-06）。

#### 2.2.6 员工 / 岗位 / 权限 / 工人

**【核】员工账号**：`AdminUserController`（`/api/admin/users`）有 `POST` / `PUT` / `DELETE` / `PUT /{id}/reset-password` / `PUT /{id}/status` —— 全是**单条**。Agent 侧 `backend/ai-agent-service/app/tools/employee_manage.py` 的 `VALID_ACTIONS` = `{list, detail, create, update, delete, reset_password, toggle_status}`，同样单条且 `idempotent = False`。

**【核】岗位 = 角色**：`AdminRoleController`（`/api/admin/roles`，`GET` / `GET /all` / `GET /{id}` / `POST` / `PUT` / `DELETE`）单条 CRUD。

**【核】权限码只读**：`AdminPermissionController`（`/api/admin/permissions`）只有 `@GetMapping` —— 权限码是**平台目录**，商家不能自定义。

**【核】开租种子**：`RegistrationService` 建 5 个默认岗位（`admin` / `customer_service` / `operator` / `sales` / `finance`），逐条 `roleMapper.insert` / `permissionMapper.insert`，再 `attachDefaultPermissions(tenantId, role, codes, permissionByCode)` 写 `role_permissions`。权限码是 `permissions` 表按租户**复制**的种子行。

**【核】工人档案的写面缺失**：`backend/admin-api/src/main/resources/db/migration/V98__create_worker_sessions_and_worker_no.sql` 把工人定义为 `users` 行 + `users.worker_no`（列注释逐字「非 NULL = 该 users 行是**工人档案**（role=worker）」），并**明确不给 `production_work_logs` 加列**、**明确复用 `users` 而不新造 `workers` 表**（文件头给出理由：`user_identities.user_id NOT NULL REFERENCES users(id)` ⇒ 本来就必须有 `users` 行）。
但全 `backend/admin-api/src/main/java` 内检索 `workerNo` / `worker_no`：**只有 `UserMapper` 的两条 `SELECT`**；`WorkerSessionService.findWorkerByNo` 是查询；`WorkerAuthController` 只有 `POST /api/worker/login`、`/session/switch`、`/session/logout`、`/session/current`。⇒ **没有任何端点或 service 方法能写 `users.worker_no`**（设计文档 `docs/design/worker-h5-scan-and-report.md` 里也只把它列为"追加列"，没给写面）。
**【推】**：今天要建工人档案，只能**直接改库**。这不是"导入缺口"，是**建档能力本身缺失**（见 GAP-05）。

#### 2.2.7 AI Agent 侧工具面无批量

**【核】**`backend/ai-agent-service/app/tools/` 下检索批量语义：`processing_order_generate`（批量生成**加工单**，`order_ids` ≤ 100）、`validate_input`（`order_ids` 批量校验）是业务批量操作，**不是数据导入**。`inventory_manage.adjustment` 是整数、单 SKU；`customer_manage` 的 `VALID_ACTIONS` **没有 create**；`product_manage` / `sku_update` 均为单条。Python 侧**不依赖任何 Excel/CSV 库**（`grep openpyxl|pandas|csv` 在 `backend/ai-agent-service/app` 下 0 命中）。

#### 2.2.8 前端无导入 UI

**【核】**`frontend/admin-web/src` 全局检索 `导入`：仅 `frontend/admin-web/src/app/(dashboard)/production/page.tsx` 一处注释（"随搜索能力一并迁入"，讲的是**代码搬迁**）。
**【核】**菜单 `frontend/admin-web/src/config/menu.ts` 的全部 `path` 里没有任何 import / 导入项（生产管理组含 `inbound-orders` → `/inbound-orders`，`permissionCode: 'inbound:view'`）。

---

## 3. 期初批次导入口径（可执行）

### 3.1 为什么必须由「期初入库单」承载（不破坏 V111 的证明）

**【核】V111 的三条硬约束**（逐字取自 `backend/admin-api/src/main/resources/db/migration/V111__create_inbound_orders_and_batches.sql`）：

1. `stock_batches` 表注释：「批次台账（V111）：一行 = 一个入库批次（= 一条入库单明细行）… 批次行**不可改**：冲销走新单据，不原地改历史」。
2. `stock_batches.inbound_order_id` 有 `REFERENCES inbound_orders(id)` ⇒ 批次行的来源单据是 **FK**，不是可选元数据。
3. `inbound_orders.status` 注释：「draft → posted（过账，加库存+落台账+算移动加权成本）… **posted 是终态**（不可改不可删）」。

**【推】推论**：任何"直接 `INSERT INTO stock_batches`"的期初方案会产生 `inbound_order_id = NULL` 的孤儿批次行 —— 它既违反 V111 的口径（第 1、2 条），也会让后续所有消费方（派工扣减 / 余量派生 / 分布统计 / 对账）为它开分支。而**用一张入库单承载**则：批次行有真实来源单据、有 `received_date`（= 切换基准日）、走同一套过账逻辑（加库存 + 落台账 + 算成本）、天然享受 `posted` 终态不可改的**冻结**语义。
⇒ **期初批次 = 一次"视同收货"**。这在语义上也最贴近现实：切换那一刻，商家**确实**把旧系统的余料"交接入库"给了新系统。

### 3.2 字段表

**映射键前提（【推】，顺序不可颠倒）**：`InboundOrderService.validateRequest` 要求每个明细行的 `skuId` 属于本租户**且**属于所填 `productId`。⇒ **商品 + SKU 必须先存在**，期初批次才挂得上去。SKU 由（货号 / 色号 / 门幅）三元组定位，故旧系统导出必须先有这三列才能建 SKU。

| 旧系统字段 | 必填 | 落点 | 现状 | 备注 |
|---|---|---|---|---|
| **批次号（旧系统）** | ✅ | ❌ **无落点** | **缺口 GAP-01** | `InboundOrderCreateRequest.Item` 无 `batchNo`；`InboundOrderService.nextFreeBatchNo` 只会产 `PC-yyyyMMdd-NNNN`。**不得**塞进 `dye_lot`（V111 逐字禁止互相冒充），也不建议塞 `remark`（无唯一索引 ⇒ 做不了幂等键） |
| **货号** | ✅ | `inbound_order_items.sku_code`（快照）→ `stock_batches.sku_code`；解析键 = `sku_id` | ✅ 支持 | 货号用来**定位 SKU**；定位不到 ⇒ 该行 fail-closed 拒绝（不新建商品，见 GAP-04） |
| **色号** | ✅ | `inbound_order_items.color_name`（快照）；`stock_batches` **无该列** | ⚠️ 仅明细行有 | 批次读面的色号需经 `sku_id → product_skus.color_id → product_colors.color_name` 解析；`sku_id` 为空的历史批次行会解析不出（V111 的 `sku_id` 可空） |
| **门幅** | ✅ | `inbound_order_items.door_width`（快照）；`stock_batches` **无该列** | ⚠️ 仅明细行有 | 门幅是 SKU 的**构成维度**（`product_skus.door_width VARCHAR(20) NOT NULL`）⇒ 门幅参与 SKU 定位，导入后不随批次变化 |
| **缸号** | ❌ 可空 | `inbound_order_items.dye_lot` → `stock_batches.dye_lot`（`VARCHAR(64)`） | ✅ 支持 | V111 口径：缸号是**外部事实**，NULL = 没记，**不伪造**（不得用 `batch_no` 冒充） |
| **剩余米数** | ✅ | `inbound_order_items.quantity` → `stock_batches.quantity` | 🔴 **当前 `INT`，小数进不来** | 见 §3.6 精度口径。**语义 = 期初"视同入库量"，即旧系统该批次的剩余量**（理由见 §3.3） |
| **单位成本** | ❌ 可空 | `inbound_order_items.unit_cost`（`NUMERIC(12,4)`）→ `stock_batches.unit_cost` | ✅ 支持 | NULL = 未知 ⇒ `movingAverage` **只加数量、均价保持原值**（V111 已裁定存量成本一律不回填、**不猜 0**） |
| **每卷米数** | ❌ 可空 | `inbound_order_items.roll_length_m`（`NUMERIC(8,2)`） | ✅ 支持 | V111 逐字：卷长是**区间值**，不参与任何换算，仅记录/打印卷标 |
| **供应商 / 仓库** | ❌ 可空 | 单头 `inbound_orders.supplier` / `warehouse` | ✅ 支持 | 旧系统的供应商可整单带一条 |
| **切换基准日** | ✅ | 单头 `inbound_orders.inbound_date`（`DATE`） | ✅ 支持 | 列注释逐字「业务日期，**可回填历史单**」；会透传到 `stock_batches.received_date` |
| **备注 / 原值留痕** | ❌ 可空 | 单头 `inbound_orders.remark`（`TEXT`） | ✅ 支持 | 建议放**导入运行号 + 舍入残差汇总**（见 §3.6） |

### 3.3 承载单据与调用序列

**【推】一次导入 = 一张期初入库单**（不是一行一批次单、也不是每批次一张单）：

```
① 前置于本单：商品 + SKU 已在库（否则 3.2 的定位键无解）
② POST /api/admin/inbound-orders        → 建 draft（此时不动库存、批次号为 NULL）
   单头：inboundDate = 切换基准日 / supplier / warehouse / remark = 导入运行号 + 残差汇总
   明细：每行 = 一个旧系统批次（skuId, quantity = 剩余米数, unitCost ?, dyeLot ?）
③ 导入器做 dry-run 差异比对（见 §3.4），把逐行结果落导入报告（见 §3.8）
④ PATCH /api/admin/inbound-orders/{id}  → 过账（action = post）
   ⚠️ 过账即冻结：加库存 + 落台账(reason='inbound') + 逐行生成批次号 + 写 stock_batches + 回写行 batch_no
⑤ 之后如需修正：不得改这张单（posted 是终态）⇒ 另开单据冲销
```

**【推】为什么 `stock_batches.quantity` 记"剩余量"而不是"旧系统原始入库量"**：
#5145 已裁定 `余量 = 入库量 − Σ消耗`，且**不原地改** `stock_batches.quantity`。若把期初批次的 `quantity` 记成旧系统的**原始入库量**，就必须同时**伪造**一段"已被消耗掉多少"的历史账（那段历史在 MIGAO 里根本不存在、且旧系统的消耗明细拿不到）——那是**假真值**。
把期初 `quantity` 记成**剩余量**，等于宣布：「这一刻，这个批次入库了这么多米」，此后所有消耗都从这一刻开始记。账是自洽的、可对账的、无伪造的。
**代价（如实登记）**：旧系统的**原始入库量**与**原始入库日期**在 MIGAO 里**丢失**（除非另建列存，见 GAP-02 的可选项）。期初导入是**有损**的，这一点必须让商家知情。

### 3.4 幂等与可重跑

**【核】现有幂等闸只覆盖"过账"这一半**：`InboundOrderService.post` 用 `draft → posted` 一次性闸门挡住重复过账（`BusinessException.conflict`，文案「库存只加一次」）。**但 `create` 本身不幂等** —— 同一份文件重跑会**新建第二张 draft 单**，两张都能过账 ⇒ **库存被加两遍**。
**【推】⇒ 幂等必须在"建单之前"解决**，且判据必须能被机械验证。

**推荐（D1）：给期初导入加两个可判定的键（需要 1 个迁移，不在本单范围）**

| 落点 | 形态 | 作用 |
|---|---|---|
| `inbound_orders.source` | `VARCHAR(16) NOT NULL DEFAULT 'purchase'`，值域 `purchase` / `opening` | **基线集合的可寻址标识**：`WHERE source = 'opening'` 即"所有期初批次"。不靠 `supplier` 哨兵值、不靠备注文本 |
| `inbound_orders.import_run_id` | `VARCHAR(64)`，部分唯一索引 `UNIQUE (tenant_id, import_run_id) WHERE import_run_id IS NOT NULL AND deleted = 0` | **运行级幂等键**：同一份文件（同一 run id）重跑 ⇒ 唯一索引直接拒绝第二张单 |
| `stock_batches.legacy_batch_no` | `VARCHAR(64)`，部分唯一索引 `UNIQUE (tenant_id, legacy_batch_no) WHERE legacy_batch_no IS NOT NULL AND deleted = 0` | ① **保留旧系统批次号**（现场认得出、卷标打得出）；② **批次行级幂等键**（重跑能逐行认出"这行已导过"） |

**【核】部分唯一索引在本仓有先例**：V98 的 `uk_users_tenant_worker_no` 就是 `UNIQUE (tenant_id, worker_no) WHERE worker_no IS NOT NULL AND deleted = 0` ⇒ D1 的写法不是新发明。
**【核】⚠️ 存量唯一索引不带 `deleted` 谓词**：`uk_stock_batches_no` 是 `UNIQUE (tenant_id, batch_no)`、`uk_inbound_orders_no` 是 `UNIQUE (inbound_no)`，**都没有 `deleted = 0` 谓词**。⇒ 软删后的行仍占用号段（重导不会撞号，但"软删一行再建同号行"会撞）。D1 的两个新索引**必须带** `deleted = 0`，否则重跑语义会被软删行污染。

**备选（D2，零迁移）及其代价（【推】，如实登记）**：
用 `inbound_orders.supplier_doc_no`（列注释「供应商送货单号（对账用，可空）」）承载 run id、用 `stock_batches.remark` 承载旧批次号。
代价：① **语义借用**（把"对账用送货单号"当运行号）；② 两列**都没有唯一索引**（`inbound_orders` 只有 `idx_inbound_orders_tenant_supplier` 与 `(tenant_id, status, inbound_date DESC)`）⇒ 幂等只能靠应用层"先查后插"，**并发下会漏**；③ 旧批次号无索引 ⇒ 按旧批次号查批次会全表扫。
⇒ **不推荐**，但如果本单之后要"最快上线"，它是唯一不改 schema 的路。

**可重跑的三条硬要求（【推】，每条都要有红证）**：

1. **dry-run 必须先跑**：默认只读，输出"将建 N 行 / 撞号 M 行 / 定位不到 K 行"，`--apply` 才写。判据：不传 `--apply` 时数据库零变更（比对前后 `inbound_orders` / `stock_batches` 行数与 `max(updated_at)`）。
2. **重复跑不得加第二遍库存**：同 run id 第二次运行 ⇒ 被唯一索引拒绝**或**识别为"已导入"并**只输出对比**，`product_skus.stock` 与 `stock_batches` 行数**逐值不变**。
3. **过账失败必须整单回滚**：`post` 已是 `@Transactional(rollbackFor = Exception.class)`（【核】方法注解），且 `uk_stock_batches_no` 会在撞号时让整个事务回滚（【核】V111 的注释与 issue #5141 的修法都登记了这一点）⇒ 不会留下"加了一半库存"的单。**导入器不得把一批数据拆成多次过账**（一次过账 = 一个事务 = 全有或全无）。

### 3.5 导入即冻结基线快照（落点）

**【核】上游需求**（#5149 与 #5145 共同锁定的口径）：导入那一刻的**批次剩余量分布** = 裁剪智能化的**上线前硬基线**；旧系统"每个批次剩多少米"只在导入时拿得到，错过后**不可回溯**。

**【推】落点 = 期初入库单本身，不需要新建快照表。** 证明链：

1. 【核】`stock_batches` 行**不可改**、`inbound_orders.posted` 是**终态**（V111）⇒ 期初批次行在过账后**永久不变**。
2. 【核】#5145 已裁定：批次消耗**追加**写 `stock_ledger_entries`、**余量派生**（入库量 − Σ消耗）、**不原地改** `stock_batches.quantity` ⇒ 后续派工扣减**不会**改动期初行的 `quantity`。
3. ⇒ 基线集合 = `stock_batches WHERE inbound_order_id IN (期初单集合)`，其 `quantity` 分布**永久可复算**，且**不受后续消耗影响**。分档口径沿用 #5145 的四档：`≤0.2m / 0.2~0.5m / 0.5~1m / >1m`（按批次数与占比）。

**【推】要使这个落点可寻址，需要 §3.4 D1 的 `inbound_orders.source='opening'`。** 没有它，基线集合只能靠"备注里写了什么"来认——那正是 V111 反对的假真值形态。
**【推】不需要物化快照表的理由**：物化一张 `migration_baseline_snapshots` 会引入"快照与源事实可能不一致"的第二真值源；而这里源事实**天然不可变**（第 1、2 条）⇒ 物化是纯粹的多余状态。

**【推】冻结时刻的精确定义**：`inbound_orders.posted_at`（`TIMESTAMP WITH TIME ZONE`）。⇒ 事后可回答"这份基线是什么时候冻的、谁冻的"（`posted_by`）。建议把 run id 也写进 `remark` 以便人读。

### 3.6 精度口径（旧系统 2 位 → MIGAO 1 位）——**必须显式，禁静默截断**

**两条分支（因为 §1.5 已核 #5063 未合）**：

**分支 A（#5063 未合，= 当前 `origin/main` 的真实状态）**
- 【核】`inbound_order_items.quantity` / `stock_batches.quantity` / `product_skus.stock` 全 `INT`，服务端**显式拒绝**非整数。
- 【推】⇒ 期初导入**只能承载整数米**。**不允许**用 `Math.round` / `(int)` 强转（`ProductService.parseProductFromRow` 的 `(int) getCellNumericValue(...)` 就是**反面教材**：静默丢小数）。
- 【推】口径：**非整数余量 ⇒ fail-closed 拒绝该行**，并把该行原值写进导入报告；整单只有在"零拒绝行"或"用户显式接受丢弃清单"时才允许过账。
- 【推】**本分支下"导入即基线"是有损的**（余量被砍到整米，分布分档在 `≤1m` 档上会明显失真）。⇒ **【推】建议期初导入排在 #5063 之后**；若必须先行，必须在导入报告首行明写"本基线为整米近似，不可作为裁剪智能化的上线前硬基线"。

**分支 B（#5063 已合，1 位小数）**
- 【推】**舍入点 = 逐批次**（不是先汇总再舍入）：每个批次行的余量独立 `HALF_UP` 到 **0.1 m**。
- 【推】**为什么逐批次**：期初入库单过账会把 Σ行 `quantity` 加到 `product_skus.stock`（【核】`productSkuMapper.receiveStock` 逐行累加）。逐批次舍入 ⇒ `SKU 库存 ≡ Σ批次余量` **恒成立**（代数上无误差），这正是 #5145 对账读面要求的"差额 = 0"。若先汇总再舍入，`Σ批次余量` 与 `SKU 库存` 会差出 `n × 0.05` 量级，对账读面会**永久显示一个说不清来源的差额**。
- 【推】**残差必须可对账（禁静默）**：导入报告逐行给出 `原值 / 导入值 / 残差` 三列，并把整单 `Σ残差` 写进 `inbound_orders.remark`。目的是让"账比实物少了 0.37 米"这件事**看得见**，而不是被舍入吃掉。
- 【推】**舍入后为 0 的行不建批次**：余量 `< 0.05m`（HALF_UP 到 0.0）的行若仍建批次，会产生 `quantity = 0` 的批次行，直接污染分布分档（`≤0.2m` 档里塞满 0 米行）并使"批次数"这个口径失真。⇒ 这类行归类为**尾料**，交 §3.7 裁定。
- 【推】**不采用向下取整（`ROUND_DOWN`）**：它会让每条批次系统性少算最多 0.099m，且在"批次多、单批小"时把误差**定向**累积成资产少计；HALF_UP 的误差是**零均值**的，更适合当基线。

**共同要求（两分支都适用，【推】）**：
- **禁止静默截断**：任何被舍入/被拒绝的行必须在报告里逐行可见，且**报告是过账的前置产物**。
- **原值必须留痕**：分支 B 下 2 位原值建议放 `inbound_order_items.remark`（`VARCHAR(255)`，无唯一约束，仅为人读）或报告文件；**不得**声称"MIGAO 里能查到旧系统的 2 位原值"。
- **单位口径显式**：`quantity` 的单位 = 该 SKU 的库存单位（V111 逐字）。旧系统若按"卷/匹"记，必须在导入前换算好，**不得**在导入器里猜系数。

### 3.7 存量尾料处置 —— **待用户裁定（本页不替用户决定）**

**【推】问题**：旧系统里必然存在大量"小到不能再裁一件"的尾料（例如 0.3m、0.04m）。它们在三个意义上都特殊：① 分布分档的 `≤0.2m` 档会被它们撑满；② 它们**不能**参与 best-fit 指派（#5144 阶段 2）；③ 用户已裁定「这个废布不算在企业资产了」（#5145 逐字）⇒ 它们在**资产口径上应为零价值**。

**待裁定选项（【推】，我不选）**：

| 选项 | 形态 | 代价 |
|---|---|---|
| **T1 全部导入** | 所有批次行原样导入（含 0.04m） | 分布基线最忠实；但 `≤0.2m` 档与"批次数"被尾料主导，且把已判零价值的布记成资产（与 #5145 裁定张力） |
| **T2 设阈值，阈值以下不建批次** | 如 `< 0.2m` 不建批次（其米数不计入 `product_skus.stock`） | 分布基线干净、与"废布零价值"一致；但**丢弃的那部分米数不可回溯**，且阈值本身会变成一条**隐性资产核销** |
| **T3 全部导入 + 打尾料标记** | 新增标记列（`is_remnant` 或复用 `remark`） | 两边都保住；代价 = 又一处 schema 增量 + 所有消费方都要读该标记（分支扩散） |
| **T4 导入但单独一张"尾料单"** | 尾料走**第二张**入库单（`source='opening_remnant'`） | 主单分布干净、尾料可查；代价 = 基线集合变成两个来源，`source` 值域要多一个 |

**【推】需要用户回答的三个问题**（任一不回答都不应开工）：
1. 阈值取多少（0.2m？0.5m？"不足一件最小裁剪尺寸"？），以及**阈值是按米数还是按"能否裁出一件"**？
2. 阈值以下的米数**要不要计入 `product_skus.stock`**（影响销售账与实物账的差额来源）？
3. 旧系统里**已经被商家自己判废/扔掉的布**是否也在导出文件里（若在，导入器需要一列"状态"来区分）？

### 3.8 导入报告（可对账，【推】）

**【推】过账前置产物**，逐行给出：`旧批次号 / 旧货号 / 色号 / 门幅 / 缸号 / 原值(剩余米数) / 导入值 / 残差 / 解析到的 sku_id / 判定（导入 / 拒绝 / 重复 / 尾料）`，并给汇总：

- `总行数 / 导入行数 / 拒绝行数 / 重复行数 / 尾料行数`
- `Σ原值 / Σ导入值 / Σ残差`（= 精度损失总量，直接喂 §3.6）
- `Σ导入值` 必须**逐值等于**过账后 `product_skus.stock` 的增量（判据，可红证）
- 分布四档基线（`≤0.2m / 0.2~0.5m / 0.5~1m / >1m` 的批次数与占比）

**判据（【推】，每条都要有能单独让它红的红证）**：
① 报告 `Σ导入值` ≠ 过账后 SKU 库存增量 ⇒ 红；② 有"拒绝/重复/尾料"行而报告未列出 ⇒ 红；③ 未传 `--apply` 时库有变更 ⇒ 红；④ 同 run id 重跑后库存变化 ≠ 0 ⇒ 红。

---

## 4. 缺口清单

**严重度口径**：【P0】= 不解决则"导入即基线"这条口径**结构性不成立**；【P1】= 能导但会留下不可回溯的损失或人工黑洞；【P2】= 体验/效率。
**去向口径**：给**明确去向**（提议的新 issue 标题 + 归属范围），或明确写"**不做**"并给理由。**本页不建 issue、不写代码**（边界所限），issue 号由后续拆单时回填。

| ID | 缺口 | 严重度 | 证据锚点 | 建议去向 |
|---|---|---|---|---|
| **GAP-01** | **旧系统批次号无处落** | **P0** | `InboundOrderCreateRequest.Item` 无 `batchNo`；`InboundOrderService.nextFreeBatchNo` 只产 `PC-*`；`dye_lot` 被 V111 明令不得与批次号混用 | **新 issue**：《期初批次导入：`stock_batches.legacy_batch_no` + 部分唯一索引（保留旧批次号 + 批次行级幂等键）》。含 §3.4 D1 的最小迁移 |
| **GAP-02** | **期初批次无"运行级幂等键"与"可寻址来源标识"** | **P0** | `inbound_orders` 无 `source` / `import_run_id`；`create` 不幂等（只有 `post` 有 draft→posted 闸）⇒ 重跑会双倍加库存 | **新 issue**：《期初入库单来源标识与运行级幂等（`inbound_orders.source` + `import_run_id` 部分唯一索引）》。与 GAP-01 **同包**（同文件域 `inbound_orders` / `stock_batches` + 同迁移） |
| **GAP-03** | **期初导入器本身不存在**（建单 / dry-run / 报告 / 分布基线） | **P0** | §2.2 全表；`frontend/admin-web/src` 无导入 UI | **新 issue**：《期初批次导入器（dry-run + 幂等 + 导入报告 + 分布基线）》——**依赖 GAP-01/02**，且**依赖 #5063 合入**（§3.6 分支 A 下的基线是有损近似） |
| **GAP-04** | **商品 + SKU 的批量导入缺失**，而期初批次**必须**先有 SKU 才挂得上 | **P0** | `ProductService.importProducts` 无端点（死代码，且字段面不含颜色/门幅/SKU）；`ProductController` 无 import 映射；`InboundOrderService.validateRequest` 要求 `skuId` 属于本租户且属于该 `productId` | **新 issue**：《商品 + SKU 批量导入（Excel/CSV）—— 复用 `ProductService` 的解析器骨架并补齐颜色/门幅/SKU 三元组》。**排在 GAP-03 之前**（顺序依赖） |
| **GAP-05** | **工人档案无写面**（`users.worker_no` 没有任何端点/service 可写） | **P1** | `backend/admin-api/src/main/java` 内 `worker_no` 仅 `UserMapper` 两条 `SELECT`；`WorkerAuthController` 无建档端点 | **新 issue**：《工人档案建档/批量导入（`users.worker_no` 写面缺失）》。**独立于本单**——它是运行时能力缺失，不只是迁移问题 |
| **GAP-06** | **工艺 / 工序 / 路线 / 规则无导入**，且旧系统配置**语义不可映射** | **P1** | `ProductionSeedTemplateService.applyTemplate` 只套**平台预置**模板（`backend/admin-api/src/main/resources/production-templates/index.json`）；`ProductionController` / `ProcessingItemController` / `ProcessingCategoryController` 全为单条 CRUD；本仓无任何"旧工序名 → 新工序名"映射表 | **新 issue（可选，需先做映射可行性调研）**：《旧系统工艺配置迁移：映射表 vs 重建清单》。若调研结论是"逐商家手工重建"⇒ **改为"不做"**（并在本页回填该裁定） |
| **GAP-07** | **客户档案无建档端点**，只能被订单"带出来" | **P1** | `CustomerController` 无 `@PostMapping`；`CustomerService.createFromOrder` 按 `phone + tenantId` 去重且在 `customerPhone` 为空时**跳过建档**（`log.warn`） | **新 issue（低优先，可合并进 GAP-03）**：《客户档案批量建档（含无手机号客户的去重口径）》。若不导历史单则**可以不做** |
| **GAP-08** | **历史订单导入会触碰库存**，且订单号**全局唯一** | **P1** | `OrderService.createOrder` 内含 `validateStockSufficientForRequest` 与支付侧扣减、`orders.stock_deducted` 标志；`docs/sql/schema.sql` 的 `orders.order_no` 是**全局 `UNIQUE`**（非租户内） | **新 issue**：《历史订单导入（旁路建单，不触库存）+ 订单号重编号口径》。**需用户先裁定"历史单要不要导"**——若不导 ⇒ **不做** |
| **GAP-09** | **库存小数化未落地**（= 本页最大的前提风险） | **P0（阻塞 GAP-03/04 的验收）** | `docs/sql/schema.sql` 的 `product_skus.stock` 是 `INTEGER`；PR #5147（`feat/5063-stock-decimal-1dp`）`isDraft=true`、`mergedAt=null` | **已有去向：#5063 / PR #5147**。本页只登记"**期初导入的基线质量依赖它先合**"（§3.6 分支 A vs B） |
| **GAP-10** | **`docs/sql/schema.sql` 是 bootstrap 路径的第二真值源**，导入若只跑迁移链会漏列 | **P2** | V111 文件头逐字：「`docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态」 | **不做**（既有纪律已覆盖：V99/V100/V108/V111 同族；GAP-01/02 的迁移须按同一纪律同步 `docs/sql/schema.sql`） |
| **GAP-11** | **导出/读面有 200 行上限**，大租户核账读不完整 | **P2** | `InboundOrderService` 的 `LIST_LIMIT` / `BATCH_LIMIT` 常量 | **不做**（核账走导入报告 + SQL 直查即可；等真有商家撞上限再单开） |

**依赖顺序（【推】，同 `migao-dev-flow` §17 的"发现即并行、合并串行"）**：

```
GAP-01 + GAP-02（同包，1 个迁移）  ─┐
GAP-09（#5063，已有 PR）           ─┼─→ GAP-04（商品+SKU 批量导入）─→ GAP-03（期初批次导入器）
GAP-05（工人建档，独立）           ─┘        ↑
GAP-06 / GAP-07 / GAP-08：待用户裁定后再决定建不建
```

---

## 5. 风险

### 5.1 精度（旧系统 2 位 → MIGAO 1 位）——**禁静默截断**

- **【核】当前的静默截断形态已经存在**：`ProductService.parseProductFromRow` 用 `(int) getCellNumericValue(row, 4)` 把库存强转 int。这是**反面教材**：转换没有日志、没有报告、没有拒绝。期初导入**不得**复制这个形态。
- **【推】错误口径会把基线做废**：若逐批次向下取整，误差**定向**累积（每条少 0~0.099m × 批次数）；若先汇总再舍入，`Σ批次余量` 会与 `SKU 库存` 差出 `n × 0.05` 量级 ⇒ #5145 对账读面**永久**显示一个说不清来源的差额。
- **【推】禁止事项**：把 2 位原值悄悄丢掉而不留痕。原值要么留在报告里，要么留在 `remark` 里，**不能声称它存在 MIGAO 里**。

### 5.2 软删与历史单

- **【核】唯一索引不带 `deleted` 谓词**：`uk_stock_batches_no` = `UNIQUE (tenant_id, batch_no)`、`uk_inbound_orders_no` = `UNIQUE (inbound_no)`；而 V98 的 `uk_users_tenant_worker_no` **带** `WHERE ... deleted = 0`。⇒ 本仓两种写法并存，**新索引必须显式选一种并写清理由**（D1 建议带 `deleted = 0`）。
- **【核】所有主表都有逻辑删列**（`inbound_orders.deleted` / `inbound_order_items.deleted` / `stock_batches.deleted`，均 `INT DEFAULT 0`）⇒ 导入写入必须**显式**写 `deleted = 0`，不能依赖默认值以外的假设（走 MyBatis-Plus 时 `@TableLogic` 会处理，直写 SQL 时不会）。
- **【推】历史单的"删除"语义**：`posted` 入库单是终态（V111），⇒ 期初单**不可删**。若商家说"导错了"，唯一合规处置 = **另开冲销单**（不是删行、不是回滚）。这条要在导入报告与页面文案里**显式**写出来，否则运营会找不到"撤销按钮"而去找工程师改库。

### 5.3 租户隔离

- **【核】`orders.order_no` 是全局 `UNIQUE`**（`docs/sql/schema.sql`）⇒ 多租户导入历史单时，旧系统的订单号在**跨租户**范围内可能撞车。这是本单盘点里**唯一一处"看起来是租户内、实际是全局"**的键。**导入前必须重编号或加租户前缀**。
- **【核】批次号是租户内唯一**（`uk_stock_batches_no` = `(tenant_id, batch_no)`，V111 注释逐字「批次号在**租户内唯一**（不是全局唯一：多租户各自的序号空间独立）」）⇒ GAP-01 的 `legacy_batch_no` 也应取 `(tenant_id, legacy_batch_no)`，**不是**全局唯一（两家商家可能都叫 `2024-A-001`）。
- **【核】跨租户校验已在内建**：`InboundOrderService.validateRequest` 校验 SKU 属于本租户且属于所填商品；`resolveOrder(rawId, tenantId)` 按租户解析单据。⇒ 导入器**必须走服务层**，不得绕过它直插 SQL（绕过即失去这层护栏）。
- **【推】导入器必须显式传 `tenantId`**（照 `ProductionSeedTemplateService.applyTemplate` 的注释口径：「**显式传入**，不读 `TenantContext` —— 显式参数让『给哪个租户套』在调用点可读，也避免上下文错位时静默套到别的租户」）。批量导入是**最容易发生"上下文错位"**的场景。

### 5.4 导入失败的可回滚性

- **【核】过账是单事务**：`InboundOrderService.post` 带 `@Transactional(rollbackFor = Exception.class)`；`uk_stock_batches_no` 撞号会让**整单**回滚（issue #5141 的注释逐字登记了这一点）⇒ 不会留下"加了一半库存"的中间态。
- **【推】⇒ 导入器必须"一次过账"，不得分批多次过账**。分批 = 多个事务 = 可能成功一半，而"一半的期初批次"比"零"更危险（商家会以为导完了）。
- **【核】回滚是**有损**的**（V111 文件头逐字）：「`inbound_orders` / `stock_batches` 的行**回不来**（入库事实与批次号一并丢弃），而 `product_skus.stock` 已加上去的数量**不会自动回退** ⇒ 回滚后必须人工盘点。属**有意**（回滚一个已过账的库存单据本就不该静默复原数量）。」⇒ **期初导入的"撤销"= 另开冲销单 + 人工盘点**，不是 `DELETE`。
- **【推】⇒ `--apply` 之前的那次 dry-run 是唯一便宜的安全网**，必须默认开启。

### 5.5 幂等

- **【核】**只有 `post` 有幂等闸（`draft → posted` 一次）；`create` 没有。⇒ **重跑建第二张单 + 双倍加库存**是当前代码里的**真实可达路径**（不是理论风险）。
- **【推】**D1 的两个部分唯一索引把幂等从"应用层自觉"升级为"数据库拒绝"——这与 V111 自己的口径一致（文档里多次用唯一索引当"安全网"：`uk_stock_batches_no`「防重号是『自动生成批次号』的安全网」）。

### 5.6 其他（【推】，如实登记）

- **期初导入是**有损**的**：旧系统的**原始入库量 / 原始入库日期 / 历史消耗明细**在 MIGAO 里不保留（§3.3 的代价登记）。商家须知情。
- **精度与分布的耦合**：#5063 未合时基线只能按整米记，`≤1m` 档会明显失真 ⇒ §3.6 分支 A 明确标注"不可作为上线前硬基线"。
- **尾料裁定未定**（§3.7）：在用户回答那三个问题之前，GAP-03 的分布基线口径**不确定**（T1~T4 会给出四份不同的基线）。

---

## 6. 我核过的事实 vs 我的推断

### 6.1 【核】我核过的事实（每条都能在当前检出的仓库里 grep 到）

1. 全仓**没有任何产品化的批量导入通路**；`frontend/admin-web/src` 里 `导入` 只出现在 `frontend/admin-web/src/app/(dashboard)/production/page.tsx` 的一处注释。
2. `ProductService.importProducts` / `generateImportTemplate` / `parseProductFromRow` 存在但**无 HTTP 入口、无调用方**（`ProductController` 只有 `@GetMapping("/export")`）。
3. 商品导出是完整链路：`ProductController.exportProducts` + `ProductService.exportProducts` + `frontend/admin-web/src/lib/api.ts` 的 `productApi.exportProducts` + `frontend/admin-web/src/app/(dashboard)/products/page.tsx` 的调用。
4. 入库单端点与权限码：`POST /api/admin/inbound-orders`（`inbound:create`）、`PATCH /api/admin/inbound-orders/{id}`（`inbound:create`）、`GET /api/admin/inbound-orders` 与 `/batches`（`inbound:view`）。
5. `InboundOrderService.post` 的幂等闸是 `draft → posted` 一次性；`cancel` 仅草稿可作废；`@Transactional(rollbackFor = Exception.class)`。
6. 批次号 `PC-yyyyMMdd-NNNN` 由服务端 `generateBatchNo` / `nextFreeBatchNo` 生成；`InboundOrderCreateRequest.Item` **无** `batchNo` 字段。
7. V111 的三条硬约束原文（批次只能由入库产生 / 批次行不可改 / `posted` 是终态）、`stock_batches.inbound_order_id` 是 FK、`stock_ledger_entries.reason` 放行 `inbound`。
8. 三条数量列全 `INT`：`inbound_order_items.quantity`、`stock_batches.quantity`（SQL 与 `StockBatch.quantity` 实体均为整型）、`product_skus.stock`（`INTEGER NOT NULL DEFAULT 0`）。
9. `InboundOrderCreateRequest.Item.quantity` 是 `Integer`；V111 文件头与 `InboundOrderService` 的校验注释都写明"小数会被显式拒绝"。
10. `CustomerController` **无** `@PostMapping` 建档端点；`CustomerService.createFromOrder` 按 `phone + tenantId` 去重、无手机号时跳过。
11. `ProductionSeedTemplateController` / `ProductionSeedTemplateService.applyTemplate` 是**平台预置模板**套用；模板资产在 `backend/admin-api/src/main/resources/production-templates/`。
12. `RegistrationService` 开租建 5 个默认岗位 + 权限码 + `role_permissions`（`attachDefaultPermissions`）。
13. `users.worker_no`（V98）在 `backend/admin-api/src/main/java` 内**只有读**（`UserMapper` 两条 `SELECT`），**无写面**。
14. `orders.order_no` 是**全局** `UNIQUE`（`docs/sql/schema.sql`）；`order_items.quantity` 是 `DECIMAL(10,2)`（V45）。
15. `uk_stock_batches_no` / `uk_inbound_orders_no` **不带** `deleted` 谓词；`uk_users_tenant_worker_no` **带**。
16. Python agent 侧无 Excel/CSV 依赖、无批量导入工具（`customer_manage` 无 `create`、`inventory_manage.adjustment` 为整数）。
17. #5063 **未合**：`docs/sql/schema.sql` 的 `product_skus.stock` 仍是 `INTEGER`；PR #5147（`feat/5063-stock-decimal-1dp`）`state=OPEN`、`isDraft=true`、`mergedAt=null`。
18. `InboundOrderService` 有 `LIST_LIMIT` / `BATCH_LIMIT` 读面上限。

### 6.2 【推】我的推断（未执行验证，请按建议对待）

1. **期初批次必须由「期初入库单」承载**、且这条路**完全不需要破坏 V111** —— 依据是 §3.1 的三条硬约束 + "期初 = 切换那一刻收货"的语义。**我没有实际跑过一次期初导入**。
2. **`stock_batches.quantity` 记"剩余量"而不是"旧系统原始入库量"** 是正确口径 —— 理由是避免伪造消耗历史。**这是我的设计判断，不是仓库里已有的裁定。**
3. **基线不需要物化快照表**、`posted_at` + `source='opening'` 即可永久复算 —— 依据是"批次行不可改"+"#5145 不原地改 `quantity`"两条已核事实的**推论**。
4. **D1（`source` / `import_run_id` / `legacy_batch_no` 三列 + 两个部分唯一索引）是推荐方案**、D2（零迁移备选）不推荐 —— 是我的取舍判断，未与用户确认。
5. **舍入口径取"逐批次 HALF_UP 到 0.1"** —— 我的选择，理由是"逐批次 ⇒ `Σ批次余量 ≡ SKU 库存` 代数成立"。**未与用户确认**。
6. **GAP 清单的严重度与去向**（含"P0 四条"与依赖顺序）—— 我的判断。
7. **`SUPPLIER` 哨兵值方案不可取**、**`dye_lot` 不得借用** —— 依据 V111 的口径做的排除，但"必须新增列"这个结论是我的推断。
8. **期初导入的"撤销"= 另开冲销单 + 人工盘点**（而不是删除/回滚）—— 依据是 V111 文件头的"回滚是有损的"逐字登记 + `posted` 终态。
9. **任务书「库存已改 1 位小数」这句是错的**（§1.5 已给反证）—— 这句本身是事实判定，但"所以设计必须写两条分支"是我的处置选择。

---

## 7. 未取证 / 边界（照实登记，不粉饰）

1. **我没有连过任何数据库**：本页所有表结构结论来自迁移文件与 `docs/sql/schema.sql` 的**文本**，未对真实库跑过 `\d`。若线上库与迁移链有漂移，本页的表结构结论需要复核。
2. **我没有跑过一次真实的期初导入**（本单边界就是"只调研 + 设计"）。§3 的可执行口径是**设计**，不是**验证过的流程**。⇒ 本页**不能**被引用为"期初导入已可用"。
3. **旧系统的导出格式我不知道**：本页假设旧系统能导出（批次号 / 货号 / 色号 / 门幅 / 缸号 / 剩余米数 / 单位成本）七列。**若旧系统给不出"剩余米数按批次"这一粒度，§3 的全部设计都不成立**（这正是 #5149 开头说的"导入口径定晚了就永久丢一次"）。**这是本页最大的未取证前提。**
4. **旧系统的精度实际是几位、以及它是否在内部就有截断**，我未取证（任务书说 2 位，我按 2 位设计）。
5. **商家是否真的会切**、切换的时间窗、是否需要**双跑期**，本页未涉及（不在 #5149 范围）。
6. **GAP-06（工艺配置）的"可否映射"我没有调研**：本仓没有旧系统工序名的样本，我无法判断映射表可行还是必须手工重建。该条的去向写成"先做可行性调研"就是这个原因。
7. **幂等的"部分唯一索引"在 MyBatis-Plus 逻辑删下的行为我未实测**：`deleted = 0` 谓词 + `@TableLogic` 的组合在"软删后重导同一 legacy_batch_no"这一具体场景下会不会给出期望语义，需要在实现时用一条测试钉住。
8. **本页未创建任何 GitHub issue**（边界所限）。§4 的 11 条缺口都给了**可执行的去向描述**（提议标题 + 范围 + 依赖），但 issue 号需要拆单时回填。
9. **本页未改任何产品代码、未加迁移、未动 `.github/**`** —— 唯一改动是新增本文件。
