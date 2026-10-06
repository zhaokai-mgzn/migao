# 变更日志

> **2026-10-06 一次性轮转**：此前的全部历史条目已移入
> [`docs/CHANGELOG-archive-2026-10-06.md`](docs/CHANGELOG-archive-2026-10-06.md)（只读）。
> 原因 = 单文件涨到 512KB 越过扫描上限，详见存档文件头与 issue #6404。
> **后续条目继续在本文件 `## [Unreleased]` 下累加。**

## [Unreleased]

### 后台新增「库存明细」页：查得到一个 SKU 的库存为什么会从 X 变成 Y（2026-10-06，issue #6404）

用户 2026-10-06：> 我在哪里查批次的剩余布料？我们是不是缺了库存明细这个功能

「批次剩余布料」本来就能查（商品详情 → 批次账 / 余料台账 / 省料看板 / 米宝），但**库存流水查不到**：
后端只读端点 `GET /api/admin/stock-ledger`（issue #4055）与 agent 工具 `stock_ledger_query`（issue #5247）
早就在，`StockLedgerController` 的 javadoc 也把「不做前端页面」逐字登记为**显式延后项**
⇒ 同一个问题**米宝答得出、商家在后台点不出来**（`git grep -c "stock-ledger" origin/main -- frontend/` = 零命中）。

- 侧边栏「仓储与物料 ▸ 库存明细」（`/stock-ledger`）：一行 = 一次 SKU 级库存变更
  （时间 / 货号·SKU / 变动 / 变动前 / 变动后 / 原因 / 单据号 / 操作人 / 成本金额）+ 分页。
- 🔴 **成本 NULL 显示「未知」，不伪造 `¥0.00`**（存量行成本列全为 NULL）；数量 NULL 显示「-」。
- 🔴 **页面不重算**：`delta` / `beforeQty` / `afterQty` / 金额一律原样渲染服务端值，
  判别器 = 测试里的**见证行**（服务端值与「现算」值故意不等的那一行）。
- 商品筛选**分两步**（先按关键词搜商品拿到 `productId`，再按 id 查流水）—— 该端点**没有**关键词参数，
  传了会被服务端静默丢弃 = 拿全量冒充过滤结果。
- 权限码取**既有** `product:list`（与端点注解逐字同码）⇒ 零授权 delta；
  菜单三源（`config/menu.ts` / `MenuController` / `AuthService`）+ 路由守卫 + 面包屑同批补齐。
