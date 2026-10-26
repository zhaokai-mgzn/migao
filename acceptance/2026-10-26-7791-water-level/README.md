# 成品仓水位智能分配 + 批量建号（issue #7791）

- **日期**：2026-10-26（Asia/Shanghai）
- **分支**：`feat/7791-warehouse-water-level`
- **Worktree**：`migao-wt/7791-warehouse-water-level`
- **用户逐字**：「后续成品帘打包入库时要自动分配仓位时要能根据仓位水位智能分配」；「另外仓位管理允许批量创建，用户输入一个数字区间后批量生成仓位号」。
- **已确认口径**：水位按**件数**；容量**按区域统一**；默认 **10 件**。

## 改了什么（用户可见）

1. **水位分配**：一个仓位可放多件到区域容量；打包过账优先选**水位最低且未满**的 active 仓（同水位按仓位号），全满才顺延新建 `A-NN`。
2. **容量按区域统一**：仓位管理里改一个仓的容量会同步本区所有仓；新建 / 批量没给容量时沿用本区现有值，新区域缺省 10；容量 1~999。
3. **仓位管理新增水位列**：`在库件数 / 容量` + 进度条；满仓显示「已满」，部分占用显示「占用中」。
4. **批量新建**：仓位管理新增「批量新建」——输入区域 + 数字区间（如 A 区 1~20 ⇒ `A-01`…`A-20`），已存在的自动跳过，返回新建 / 跳过计数；单次最多 500 个；空态也能批量建号。
5. **并发容量**：候选仓位行 `SELECT … FOR UPDATE`，拿到锁后复核在库件数；并发过账不会把同一仓塞过容量。

## 环境 / 验证方式

- admin-api 从本 worktree 启动（`:8080`），启动时 V198 已成功落库：
  - `MigrationRunner` 日志：`🔄 执行迁移: V198__warehouse_capacity_and_water_level.sql` → `✅ 迁移完成`；
  - 首次连接 RDS 有网络超时，MigrationRunner 重试后成功（dev 环境网络抖动，不是代码回归）。
- admin-web 从本 worktree 用 `next dev -p 3002` 启动；本地临时把 `CORS_ALLOWED_ORIGINS` 扩到 3002（worktree `.env`，未提交）。
- 验收脚本（`migao-dev-flow` 的 `ui-multimodal-acceptance.mjs`）：
  - `--site http://localhost:3002 --path /outbound-orders --phone 13900001025 --code 123456`；
  - 登录成功 → 出库单页 → 「仓位管理」页签。
- **数据夹具（dev 租户 46）**：
  - 通过 UI 批量新建 `A-01`…`A-20`（默认容量 10）；
  - 为了给「水位」列取证，用 SQL 向 `A-01` 插 3 行、`A-02` 插 10 行在库成品（`order_id LIKE 'ACC-7791-%'`）；
  - 截图后**已清理**：删除 13 行夹具在库、软删 20 个夹具仓位；租户原有仓 `30` 保留未动（清理 SQL 读数：`acc_stock_left=0` / `a_bins_left=0` / `30|0`）。

## 证据（读图判定）

| 文件 | 读图结论 |
|---|---|
| `01-batch-modal-full.png` | 「批量新建仓位」弹窗：区域 A / 成品区、起始 1 / 结束 20、每仓容量 10；提示「输入数字区间，如 1~20 ⇒ A-01…A-20；已存在的跳过；单次最多 500 个」；预览「将生成 A-01 ~ A-20，共 20 个」；按钮「取消 / 批量创建」。无溢出、字段对齐、无重复 CTA。 |
| `02-batch-preview.png` | 预览行文案完整、颜色低对比灰底，不抢主操作。 |
| `03-batch-created-panel.png` | 批量创建成功 toast「已新建 20 个仓位」；列表 A-01…A-20 全部「0 / 10 · 空闲」；水位条、状态点、操作列对齐正常。 |
| `04-water-level-panel.png` | `A-01` 显示 **3 / 10**、绿色水位条、「占用中」；`A-02` 显示 **10 / 10**、红色水位条、「已满」；其余 0/10「空闲」；无溢出、无 5xx。 |

- 两次采集的 `summary.json`：URL `/outbound-orders`，`5xx: 0`，testid 42 / 134。
- 视觉判定：无「占位/调试文案」；水位/状态用「进度条 + 点 + 文字」陈述，没有孤立状态徽标；批量与单个新建是两个不同动作，空态/有数据时各只出现一组。

## 自动化判据（同 PR）

- 后端全量 `./verify-all.sh backend --allow-package-heavy` → ✅ admin-api 全量。
- 前端全量 `./verify-all.sh frontend --allow-package-heavy` → ✅ admin-web vitest / tsc / worker-h5。
- 真库并发 `WarehouseLocationAllocationRealDbTest`（本地 PG，`MIGAO_REQUIRE_REALDB=1`）：
  - 水位最低优先（A-01 1/2、A-02 空 ⇒ A-02）；
  - 第二事务在 `FOR UPDATE` 上等待；第一事务填满 A-01 后，第二事务复核并新建 A-02；
  - 若去掉 `FOR UPDATE` ⇒ 第二事务不阻塞，判据红；
  - 顺带抓到并修掉：`selectBestBinForAllocation` 被 MyBatis 一级缓存命中，同事务循环会拿到旧候选 ⇒ 已加 `@Options(useCache=false, flushCache=TRUE)` + 守卫测试。
- `./contract-check.sh` → 三端契约通过；`./check-ui-regression.sh` → 无回退。
- `./verify-all.sh gate --allow-package-heavy` → QA Growth Gate / cases 面 / 红证前提自检通过（详见 PR 检查记录）。
- 用例：WH-010 新增；WH-003 / WH-007 按新口径改判（一仓多件后不再要求 5 个不同仓号，标签仍打 `bin_code`）。

## 边界（照实登记）

- 不做货架层级 / 体积 / 重量维度（容量 = 件数）；不做移库 / 跨仓调拨。
- 容量下调到低于当前在库件数时不驱逐已有件，只停止继续分配；水位可能显示 >100%（本单 UI 用红色条 + 已满表达）。
- 真库并发测试覆盖「两事务争同一仓」；未做长时间高并发压测。
- 本单 UI 验收的 3/10、10/10 是**受控 SQL 夹具**（为了读图取证），不是真实打包流程产生的；真实打包链路由 `InboundOrderService` 单测 + `InboundStockDocumentTest` 覆盖，真库分配由上述 `WarehouseLocationAllocationRealDbTest` 覆盖。
- 截图中的租户原有仓 `30` 未清理（不是本单数据）；批量创建的 A-01…A-20 与夹具在库已清理。
