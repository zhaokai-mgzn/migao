# 经营看板现状盘点（`/dashboard`）

> ⚠️ **本文是「现状读数」，不是设计单、也不含改进方案。**
> 用途 = 让产品负责人对着清单逐项标「留 / 改 / 删 / 加」，再据此定重构范围（issue #5778 会话：
> 用户 2026-09-29 提出「经营看板需要重构一下，当前的功能不满足当前整体产品功能需要了」，
> 并要求先出一份现状盘点清单）。
>
> 盘点方式：**只读**读码（grep / read）。未运行应用、未看线上数据。
> 坐标一律「仓库相对路径 + 符号名」（不写行号 —— 活跃文件的裸行号分钟级失效）。

## 1. 页面构成

| 角色 | 仓库相对路径 | 关键符号 |
|---|---|---|
| 页面入口（全部区块在此拼装） | `frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx` | `DashboardPage`、`BizStatCard`、`PendingCard`、`SectionHeading`、`MiniSparkline`、`MiniBarChart`、`ChartSkeleton`、`METRIC_STYLES`、`PENDING_COLORS`、`fmtCurrency`、`fmtNum`、`fmtSigned` |
| 黄金策「今日经营速览」洞察条 | `frontend/admin-web/src/components/dashboard/TodayOverviewBar.tsx` | `TodayOverviewBar`、`buildInsightSentence`、`processingRatio`、`formatOrderChange` |
| 每日经营简报卡（与 `/briefing` 共用） | `frontend/admin-web/src/components/dashboard/BriefingCard.tsx` | `BriefingCard`、`ItemRow`、`SeverityBadge`、`ReviewStrip`、`changeDirection` |
| 通用趋势图（SVG） | `frontend/admin-web/src/components/dashboard/TrendChart.tsx` | `TrendChart`、`niceCeil`；横轴降采样复用 `frontend/admin-web/src/lib/axis-sampling.ts` 的 `sampleTickIndices` |
| 近期订单列表 | `frontend/admin-web/src/components/dashboard/RecentOrders.tsx` | `RecentOrders`、`formatAmount`、`formatTime` |
| API 客户端 | `frontend/admin-web/src/lib/api.ts` | `dashboardApi`、`briefingApi` |
| 类型 | `frontend/admin-web/src/types/index.ts` | `DashboardStats`、`ProductRanking`、`OrderTrendPoint`、`OrderStatusDistribution`、`ActiveSession`、`PendingTask`、`BriefingContent`、`BriefingItem`、`BriefingReviewItem` |
| 简报独立页（复用同一卡片） | `frontend/admin-web/src/app/(dashboard)/briefing/page.tsx` | `BriefingPage` |
| 路由权限守卫 | `frontend/admin-web/src/app/(dashboard)/layout.tsx` | `ROUTE_PERMISSION_MAP`（`/dashboard`、`/briefing` 均 `dashboard:view`） |

**第一屏渲染顺序**（读 `DashboardPage` 的 JSX）：页头（标题 + 数据更新时间 + 刷新）→ 黄金策今日经营速览 → 每日经营简报卡 → 待处理（3 张卡）→ 经营数据（4 张卡）→ 趋势图（订单趋势 / 销售额两栏）→ 列表（近期订单 / 商品销量排行两栏）。

## 2. 指标 / 数据点清单

### 2.1 待处理 · 经营数据（同一端点 `GET /api/admin/dashboard/stats`）

| 区块 | 展示项 | 取值 | 后端实现 | 来源表 | 口径 |
|---|---|---|---|---|---|
| 待处理 | 待发货订单 | `stats.pendingShipOrders` | `DashboardController::getStats` → `OrderMapper::selectDashboardOrderStats`（`pending_ship`） | `orders` | `COUNT(*) FILTER (status IN ('confirmed','producing') AND deleted=0)`；⚠️ 卡片文案只写「待发货」，下钻链接只过滤 `status=待发货`（= `confirmed`）⇒ **计数口径比下钻口径宽**（`producing` 的中文标签是「生产中」） |
| 待处理 | 含加工待发货 | `stats.processingPendingOrders` | `OrderItemMapper::selectProcessingPendingOrdersCount` | `order_items` ⋈ `orders` | `COUNT(DISTINCT oi.order_id)`，`o.status IN ('confirmed','producing')` ∧ `oi.processing_info IS NOT NULL` |
| 待处理 | 待补库存商品 | `stats.lowStockItems` | `ProductService::getLowStockSkuCount(tenantId, 100)` → `ProductMapper::countLowStockSkus` | `product_skus` ⋈ `products` | `on_sale` ∧ `stock BETWEEN 0 AND 100`，按 **SKU**（颜色规格）计数，阈值 `100` 硬编码在调用处 |
| 经营数据 | 今日订单数 + 环比 | `stats.todayOrders` / `todayOrdersChange` | `selectDashboardOrderStats`（`today_orders` / `yesterday_orders`） | `orders` | 业务日 `Asia/Shanghai` 半开区间；环比 `(今−昨)/昨×100`，**分母 0 ⇒ 0**（不区分「无昨日」） |
| 经营数据 | 今日销售额 + 环比 + 迷你柱 | `stats.todaySales` / `todaySalesChange` + `order-trend` | 同上 + `DashboardController::getOrderTrend` | `orders` | `SUM(total_amount)`；🔴 **无状态过滤**（含 `pending` 未付款与 `cancelled` 已取消） |
| 经营数据 | 客单价 | 前端内联 `Math.round(todaySales / max(todayOrders,1))`；`todayOrders<=0` ⇒ 0 | **无独立端点** | `orders`（经 stats 两字段） | 🔴 分子含未付款/已取消，分母是全部今日订单 ⇒ 与「本月销售额」的状态过滤口径**不一致** |
| 经营数据 | 本月销售额 + 环比 | `stats.monthRevenue` / `monthRevenueChange` | `selectDashboardOrderStats`（`month_revenue`） | `orders` | `created_at >= 本月 1 日 00:00+08` ∧ `status IN ('confirmed','producing','shipped','completed')`；⚠️ **只有下界、无上界**（未来创建时间也会计入） |

### 2.2 趋势图（`GET /api/admin/dashboard/order-trend?days=7|30`）

| 展示项 | 取值 | 后端 | 口径 |
|---|---|---|---|
| 订单趋势折线 | `trendData[].orders` | `DashboardController::getOrderTrend` → `OrderMapper::selectOrderTrend` | `startOfDay(today − (days−1))` ⇒ 含今天共 `days` 天；SQL `GROUP BY DATE(created_at)`；缺日补 0 |
| 销售额面积图 | `trendData[].amount` | 同上 | `COALESCE(SUM(total_amount),0)`；🔴 **无状态过滤**（与「本月销售额」口径不同） |
| 右上角「数据更新时间」 | `updateTime.slice(11,19)` | 无（纯前端切片） | 🔴 截的是 **ISO 串的 UTC 时分秒**；而页头同一字段走 `formatFullDateTime`（浏览器本地时区）⇒ **两处不同源** |

### 2.3 列表区

| 区块 | 展示项 | 端点 / 后端 | 口径 |
|---|---|---|---|
| 近期订单 | 订单号 / 客户 / 金额 / 状态 / 时间（5 条） | `GET /api/admin/dashboard/recent-orders?limit=5` → `DashboardController::getRecentOrders` | `ORDER BY created_at DESC LIMIT 5`，无状态过滤 |
| 商品销量排行 | 排名 / 商品名 / 进度条 / 成交量 / 环比（10 条） | `GET /api/admin/dashboard/product-ranking?period=day&limit=10` → `OrderItemMapper::selectProductRanking` + `selectPrevPeriodQuantities` | 本期 = `startOfDay(today−7d)`（**近 8 天含今天**，文案写「近7天」）；状态集 `confirmed/producing/shipped/completed`；环比分母 0 ⇒ 0；🔴 环比 0 会渲染成红色「▼ 0%」 |

### 2.4 每日简报卡（`GET /api/admin/briefing/today`）+ 开关（`GET /api/admin/briefing/config`）

| 展示项 | 取值 | 后端 | 口径 |
|---|---|---|---|
| 一句话总览 + 昨日回顾 + 今日必办 / 风险预警 / 优化建议 | `data.content.{summary,review,todo,risks,suggestions}` | `BriefingController::getToday` → `DailyBriefingService::getTodayBriefing` | 按「租户 + 业务日」取 `daily_briefings.content`（LLM 生成、数字经后端回填校验）；`review` 非数组 ⇒ 归一化为 null ⇒ 显示「已安全丢弃不实条目」 |
| 整卡是否渲染 | `res.data.data.enabled` → `briefingEnabled` | `BriefingController::getConfig` → `DailyBriefingService::getConfig` | `tenants.briefing_enabled`（在 `/settings` 基本设置维护）；请求失败 ⇒ `catch(() => false)` ⇒ **静默隐藏整卡**（无提示） |

### 2.5 黄金策「今日经营速览」

一句话解读由 `TodayOverviewBar::buildInsightSentence` 拼装（入参 = 今日订单数/销售额/两项环比/含加工占比/低库存数）。⚠️ stats 未到或失败时全部入参退化为 0 ⇒ 固定渲染「今日暂无新订单，销售额 ¥0」——**与「今日真的零单」不可区分**（无独立空态）。

## 3. 刷新与口径

- **挂载拉一次**（`fetchData` 的 `useCallback` + `useEffect`）；**切换「近7天 / 近30天」会重拉全部 4 个接口**（`Promise.allSettled`：stats / order-trend / recent-orders / product-ranking）。
- **无轮询**（页面内无 `setInterval` / `visibilitychange` / `focus` 重取）；手动「刷新」按钮 `onClick={fetchData}`，loading 时**不禁用**。
- 简报独立拉取（挂载一次 + 卡内刷新）；企业开关另发一次请求。
- **无缓存层**（`lib/api.ts` / `lib/request.ts` 无 cache / SWR / react-query）。
- **时区**：后端唯一业务时钟 = `backend/admin-api/src/main/java/com/migao/admin/time/BusinessClock.java`（`BUSINESS_ZONE = Asia/Shanghai`，守卫 `BusinessClockSourceGuardTest`）；前端两处时间显示**不同源**（见 2.2）。
- 🔴 **失败与空数据不可区分**：`allSettled` 的 rejected 分支只 `console.error`，UI 一律退化为「空数据」或 0 ⇒ 用户无法区分「今天没单」与「接口挂了」。

## 4. 可见性与权限

| 维度 | 事实 |
|---|---|
| 后端读权限 | 看板全部端点**类级** `@RequirePermission("dashboard:view")`（`DashboardController`） |
| 简报 | `/briefing/today`、`/briefing/config`(GET) = `dashboard:view`；PUT config / generate = `system:manage` |
| 前端路由守卫 | `/dashboard`、`/briefing` 均 `dashboard:view`；无权限渲染 403 面板（不重定向） |
| 侧边栏 | 「经营看板」`dashboard:view`；「每日简报」同码 + `briefingToggle`（企业开关） |
| 页内分角色 | **无** —— 除简报开关外，页面没有任何按角色 / 行业 / 企业配置切换区块的逻辑（只有 `loading` / `briefingEnabled` / `trendDays` 三个状态） |

## 5. 下钻入口

| 区块 | 下钻目标 |
|---|---|
| 待发货订单 | `/orders?status=待发货` |
| 含加工待发货 | `/orders?category=含加工订单&status=待发货` |
| 待补库存商品 | `/products?low_stock=true` |
| 订单趋势 / 销售额空态 | `/orders/new` |
| 近期订单「查看全部」/ 行 | `/orders` / `/orders/{id}` |
| 商品销量排行「查看更多」 | `/products?sortBy=salesCount&sortOrder=desc` |
| 简报卡空态「去开启」 | `/settings?tab=basic` |
| **经营数据 4 张卡** | **无下钻** |
| **黄金策洞察条** | **无下钻** |

`/briefing` 与看板的关系：独立路由，页面主体是**同一个 `BriefingCard`**（`<BriefingCard enabled />`）⇒ 简报内容在两页**逐字重复**（同端点、同组件）。

## 6. 后端已实现、但看板**没有**展示的能力（重构空间的证据）

**已实现的读端点，前端封装了但零调用（或组件已是死代码）**

| 端点 | 后端实现 | 前端现状 |
|---|---|---|
| `GET /api/admin/dashboard/order-status` | `DashboardController::getOrderStatusDistribution` → `OrderMapper::selectOrderStatusDistribution`（返回 status/label/count/color） | `dashboardApi.getOrderStatusDistribution` 零调用；组件 `frontend/admin-web/src/components/dashboard/OrderStatusChart.tsx` 无任何页面引用 |
| `GET /api/admin/dashboard/active-sessions` | `DashboardController::getActiveSessions`（客户名 / 渠道 / 最后一条消息 / 时长 / 是否 AI） | `dashboardApi.getActiveSessions` 零调用；组件 `ActiveSessions.tsx` 未被引用 |
| `GET /api/admin/dashboard/pending-tasks` | `DashboardController::getPendingTasks`（待支付订单 + 待处理售后工单，**带 `link` 可下钻**） | `dashboardApi.getPendingTasks` 零调用；类型 `PendingTask` 无消费方 |
| `GET /api/admin/dashboard/pending-shipment-count` | `DashboardController::getPendingShipmentCount` | 前端无绑定（注释自述已被 stats 聚合替代） |
| `GET /api/admin/dashboard/processing-shipment-count` | `DashboardController::getProcessingShipmentCount` | 前端无绑定；🔴 与上一个**实现完全相同**（同条件同返回），只留 TODO（等 `orders.has_processing` 列） |
| `GET /api/admin/briefing/snapshot` | `BriefingController::getSnapshot` → `DailyBriefingService::aggregateSnapshot` | admin-web 无调用；唯一消费方 = `backend/ai-agent-service/app/tools/briefing_query.py` |

**`/stats` 已返回、页面从不渲染的字段**（前后端类型里都有）

`totalOrders`、`totalCustomers`、`newCustomersToday`、`activeSessions`、`aiSessionRate`、`totalTickets`、`totalProducts`；另 `ProductRanking.salesAmount` / `amountDisplay`（页面只用 `qtyDisplay`）、`BriefingItem.metrics`。

**简报快照里已算好、看板未展示的指标**（`DailyBriefingService::aggregateSnapshot`）

`pending_tickets` / `overdue_tickets`（= `pending|processing` 且 `deadline` 已过）/ `total_tickets` / `ai_sessions` / `ai_session_rate_pct` / `orders_change_pct` / `total_customers` / `new_customers_today`；以及 `facts[]`（待发货 / 含加工 / 低库存 / **超时工单**的可下钻事实条，与看板 3 张待处理卡高度重合但口径与下钻链接由后端给出）、行级数组 `orders` / `skus` / `returns` / `product_return_stats` / `order_discounts`、租户级事实 `cost_accounting` / `audit_tool_logging`。
（`price_changes` 在代码注释里明确声明**不装配**：全仓无改价流水表。）

**看起来该有却没有的指标 —— ⚠️ 以下是判断，不是事实**

- **售后时效**：`overdue_tickets` 后端已算好、`/after-sales` 页存在，看板只有未展示的 `totalTickets`。
- **退款 / 退货率**：`product_return_stats`（按商品的退货工单数 / 订单行数）已在快照里算好并配了同源守卫，看板完全不展示。
- **欠款 / 对账（应收）**：`/finance` 页与 `finance:view` 码存在，看板无任何财务口径指标（既无应收、也无毛利 / 成本）。
- **产能 / 交期**：`/production/*` 下已有排产 / 工序 / 计件 / 余料 / 省料多页，看板未展示任何产能 / 在制 / 逾期交期指标。
- **客户结构**：`new_customers_today` / `total_customers` 已返回未展示；看板无复购率 / 客群结构。
- **未付款风险**：`/pending-tasks` 已实现「待支付订单」未用；而「今日销售额 / 客单价」恰好把未付款单**计入**。
- **AI 服务量**：`activeSessions` / `aiSessionRate` 已返回未展示（这是「AI 客服 SaaS」的经营主指标之一）。

## 7. 已知缺口与死代码

| 类型 | 内容 | 证据 |
|---|---|---|
| TODO | 「等 orders 表加 `has_processing` 列后加 `.eq(Order::getHasProcessing, true)`」 | `DashboardController::getProcessingShipmentCount` |
| 重复实现（占位） | `getPendingShipmentCount` 与 `getProcessingShipmentCount` 返回**同一条查询** | `DashboardController` 两方法 |
| 文案 / 口径不符 | 方法注释写「待发货订单数（status = 待发货）」，实际条件含 `producing` | `DashboardController::getPendingShipmentCount` 注释 + `selectDashboardOrderStats` 的 `pending_ship` |
| 前端死组件 | `StatCard.tsx` / `OrderTrendChart.tsx` / `OrderStatusChart.tsx` / `ActiveSessions.tsx`：`src` 侧无引用，只有自身测试在导入 | grep 全量 |
| 前端死 API | `dashboardApi.getOrderStatusDistribution` / `getActiveSessions` / `getPendingTasks` 零调用 | `lib/api.ts` + 全量 grep |
| 类型缺口 | 后端 `/briefing/today` 返回 `sourceSnapshot`，前端 `TodayBriefingResponse` **没有该字段** | `BriefingController::getToday` vs `types/index.ts` |
| 空态与失败态混淆 | rejected 只 `console.error`，UI 退化成空数据 / 0 | `dashboard/page.tsx` 的 `fetchData`；`RecentOrders` / `TrendChart` 空态分支 |
| 同页口径不一致（6 处） | ① 今日销售额无状态过滤 vs 本月过滤四态；② 本月无上界；③ 环比分母 0 一律回 0；④ 销量排行 `day` 实为近 8 天且不随 7/30 切换；⑤ 待发货计数含 `producing` 而下钻只过滤「待发货」；⑥ 时间显示两处不同源（浏览器本地 vs UTC 切片） | `DashboardController::getStats` + `selectDashboardOrderStats` + `selectProductRanking` + `dashboard/page.tsx` |

## 8. 盘点边界（如实登记）

1. **未运行任何服务**：第一屏顺序是读 JSX 静态推得，响应式断点下的真实布局未核。
2. **线上 / 云 dev 真实数据未知**：各指标分布、空态在生产的常见度、`daily_briefings` 是否真有记录，均无法从静态代码判断。
3. **未读简报生成链路**：只读 admin-api 侧；LLM prompt 与数字回填校验规则在 ai-agent-service 侧，本次未展开；`docs/design/daily-briefing-design.md` 未逐节读完。
4. **权限授予面未穷举**：只按 `dashboard:view` 命中 V137 与 archive 的 V29/V32。
5. **`/` 是否指向看板未验证**：仓库路由树里**没有**根 `page.tsx`，`next.config.mjs` 无 `redirects`、无 `src/middleware.ts` ⇒ 部署层是否有 `/` → `/dashboard` 重写未确认（`lib/menu-nav.ts` 对 `/` 的特判在当前路由树里找不到对应页面）。
6. **未核对**：`check-ui-regression.sh` 的基线是否覆盖看板各区块；`frontend/admin-web/tests/unit/pages/dashboard.test.tsx` 的断言细节。
7. **无法从静态代码判断**：浏览器时区分布、`product-ranking` 的 `dailyChange` 在真实数据上多常为 0、简报 `link` 的 LLM 输出稳定性、租户行级隔离在运行期的实际效果。
