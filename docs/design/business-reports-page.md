# 经营报表页（`/dashboard`）口径与信息架构

> 状态：**已实装**（issue #8852，用户 2026-11-09 钉钉要求，2026-11-09 落地）。
> 上游：`docs/design/dashboard-refactor-stage2.md`（看板指标口径）、`docs/design/dashboard-as-is-inventory.md`（现状盘点）。
> 本文是 AI 页面上下文（`backend/ai-agent-service/app/context/page_registry.py` 的 `business-reports`
> 真值源）与后续改动的**单一入口**：口径与本文不符时，以用户最新裁定为准，并同批改本文。

## 1. 用户原始要求（2026-11-09 钉钉）

> 把“经营概览”和“报表中心”两个页面整合为一个页面“经营报表”。整合后的页面展示要符合用户查看、分析、管理逻辑，不要把数据乱七八糟的杂揉在一起。

## 2. 合并后的信息架构（三段，顺序即阅读顺序）

`/dashboard` 是唯一入口；`/reports` 保留为重定向薄壳（→ `/dashboard`）。菜单只有一个节点
「经营报表」，节点 key / 路径 / 权限码保持 `dashboard` / `/dashboard` / `dashboard:view`
（登录落点与授权口径零变化）。

| 段 | 页面标题 | 回答的问题 | 内容 |
|---|---|---|---|
| 一 | **今日经营（查看）** | 今天卖了多少、还有哪些要处理 | 黄金策「今日经营」速览/简报、待处理 5 卡（待支付 / 待发货 / 含加工待发货 / 超时工单 / 待补库存）、经营数据 4 卡、AI 接待占比（能力位驱动，未购买不渲染） |
| 二 | **经营分析（分析）** | 走势如何、钱/货/人/客户的结构问题在哪 | 订单趋势、销售额趋势、订单状态分布；**经营报表五张卡**：订单毛利、库存滞销、员工业绩、质量成本（含维度汇总）、应收账龄 |
| 三 | **经营明细（管理）** | 具体哪一单、哪款货，点进去处理 | 近期订单、商品销量排行（均带下钻入口） |

排序理由：**先看今天 → 再看结构 → 最后落到单**。原「待处理」保持在首屏（issue #8105 的用户裁定
不回退）；原报表中心的时间区间筛选随五张报表一起进入「经营分析」段，不再单独占一页页头。

## 3. 看板卡片口径

- 「经营数据」四卡：今日订单数 / 今日销售额 / 客单价 / 本月销售额；金额与订单量只统计
  `confirmed / producing / shipped / completed` 四态（与「本月销售额」同口径）。
- 环比：后端返回百分比（`25.5` = +25.5%），前端统一换算成比值；无上期可比 ⇒ 「—」；`|环比| ≥ 500%`
  ⇒ 倍数展示（`+23×`），避免小基数造出读不出量级的百分比。
- 读不到 ≠ 0：`stats` 未取到 ⇒ 显示「—」/「经营数据没读到」，不得印成 0；加载失败按块告警并保留
  上次成功值（`dashboard-load-failed`）。
- 待处理卡的数量与下钻链接同源：卡说多少，点进去的筛选就筛多少。

这些规则的实现真值是 `frontend/admin-web/src/lib/dashboard-cards.ts`（可插拔卡注册表）与
`frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx`（格式化/失败态），本文只描述对外形态。

## 4. 报表口径（业务事实）

五张报表都是**只读**，走既有 `GET /api/admin/reports/**` 端点（类级权限码 `dashboard:view`），
**不新增写面**。共同的展示纪律（与后端 `ReportService.java` 的 javadoc 一一对应）：

1. **合计 = 明细之和**：合计与小计必须可复算；
2. **没有数据不画成 0**：`hasData=false` / `totals=null` ⇒ 「暂无数据」，不是 `¥0.00`；
3. **未知不填 0**：成本未知、未定价、未采集、未发生的分项显示「未采集 / 未知」并说明原因；
4. **合计不完整要标注**：质量成本 `complete=false` 时明写「这不是完整质量成本，还缺哪几项」。

时间区间（默认**本月**）只作用于「订单毛利 / 员工业绩（按下单日期）」与「质量成本（按返工报工日、
退款发生日）」；**库存滞销与应收账龄是「此刻」读数，不受区间影响** —— 这句话必须留在筛选条旁，
否则商家会以为「筛了 10 月，滞销数字怎么没变」。

## 5. 明确不改的边界

- 不改任何统计口径、金额算法、后端读端点与权限码；
- 不改订单 / 售后 / 商品 / 财务页面的写操作与下钻语义；
- 不新增菜单项与权限码；`/reports` 仅作旧深链兼容重定向。

## 6. 判据

- 页面结构 / 分区顺序 / 报表段挂载：`frontend/admin-web/tests/unit/pages/business-reports-page.test.tsx`
  （同时断言 `/reports` 重定向）；
- 报表五卡的四条展示纪律：`frontend/admin-web/tests/unit/pages/reports.test.tsx`（组件级，口径原样）；
- 菜单三源同构：`tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`；
- AI 导航镜像：`tests/unit_ci_workflows/test_menu_navigator.py`；页面上下文登记：
  `tests/unit_ci_workflows/test_page_context_registry_coverage.py`；
- 真浏览器（fixture 数据）：`tests/e2e/specs/dashboard/dashboard.spec.ts`（PR CI 显式列表内）。
