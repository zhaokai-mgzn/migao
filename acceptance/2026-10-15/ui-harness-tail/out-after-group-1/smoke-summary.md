# 商家后端 UI 冒烟结果

时间: 2026-10-14T15:26:39.903Z ｜ 通过 9/32 ｜ 失败 0 ｜ 未配置 0 ｜ skip 23

| # | 旅程 | 结果 | 证据 |
|---|------|------|------|
| 1 | 01-login | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 2 | 02-dashboard | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 3 | 03-briefing | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 4 | 04-agent-workspace-redirect | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 5 | 05-human-sessions | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 6 | 06-agent-sessions | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 7 | 07-chat | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 8 | 08-products-list | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 9 | 09-products-new | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 10 | 10-product-detail | ✅ | 商品详情渲染（http://localhost:3001/products/fedc11b97d26ca05662ae664a462d14b）; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-ha |
| 11 | 11-product-edit-doorwidth | ✅ | 门幅下拉回显: value=2.8, 选项=["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]（自造商品 2f0f0b662b88a99f407dae0ad77c16b7 已清理）; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harne |
| 12 | 12-processing | ✅ | 加工项 新建→列表可见→编辑→删除 完成；启停toggle可见=false; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/scree |
| 13 | 13-categories | ✅ | 分类 新建→可见→行内删除; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/screenshots/13-categories.png |
| 14 | 14-orders-list | ✅ | 订单列表 20 行（无分页按钮或单页）; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/screenshots/14-orders-l |
| 15 | 15-orders-new | ✅ | 新建订单提交后跳转 http://localhost:3001/orders/new（自造商品 冒烟建单商品1791991571815 已清理，商品总数 14→14）; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026 |
| 16 | 16-order-detail-processing-order | ✅ | /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/screenshots/16-order-detail-processing-order |
| 17 | 32-production-qr-and-piecework | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 18 | 17-order-ship | ⏭️ skip | /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/screenshots/17-order-ship.png |
| 19 | 18-after-sales-list | ✅ | 售后工单列表渲染 8 行; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/screenshots/18-after-sales-lis |
| 20 | 19-after-sales-detail | ✅ | 关闭原因落库回显=true; /Users/guangzhen.zk/ai native/migao-wt/6942-ui-harness-tail/acceptance/2026-10-15/ui-harness-tail/out-after-group-1/screenshots/19-after-sales-de |
| 21 | 20-customers-list | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 22 | 21-customer-detail | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 23 | 22-finance | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 24 | 23-employees | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 25 | 24-roles | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 26 | 25-settings | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 27 | 26-notifications | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 28 | 27-corporate-home | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 29 | 28-corporate-about | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 30 | 29-corporate-contact | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 31 | 30-corporate-services | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 32 | 31-register | ⏭️ skip | --group 1 过滤（本轮未跑） |

## ⏭️ skip（前置/依赖不满足，**未跑**）

- 01-login：--group 1 过滤（本轮未跑）
- 02-dashboard：--group 1 过滤（本轮未跑）
- 03-briefing：--group 1 过滤（本轮未跑）
- 04-agent-workspace-redirect：--group 1 过滤（本轮未跑）
- 05-human-sessions：--group 1 过滤（本轮未跑）
- 06-agent-sessions：--group 1 过滤（本轮未跑）
- 07-chat：--group 1 过滤（本轮未跑）
- 08-products-list：--group 1 过滤（本轮未跑）
- 09-products-new：--group 1 过滤（本轮未跑）
- 32-production-qr-and-piecework：--group 1 过滤（本轮未跑）
- 17-order-ship：前置不满足（生产路线/默认工艺未配置）：本租户指定单（588efd131d493a6d09126c97533174de）生成加工单**未落库**：接口 HTTP 200 但 data 为空 —— api 日志 INCIDENT_PRODUCTION_ROUTING_UNRESOLVED「订单缺 craft 且该租户没有
- 20-customers-list：--group 1 过滤（本轮未跑）
- 21-customer-detail：--group 1 过滤（本轮未跑）
- 22-finance：--group 1 过滤（本轮未跑）
- 23-employees：--group 1 过滤（本轮未跑）
- 24-roles：--group 1 过滤（本轮未跑）
- 25-settings：--group 1 过滤（本轮未跑）
- 26-notifications：--group 1 过滤（本轮未跑）
- 27-corporate-home：--group 1 过滤（本轮未跑）
- 28-corporate-about：--group 1 过滤（本轮未跑）
- 29-corporate-contact：--group 1 过滤（本轮未跑）
- 30-corporate-services：--group 1 过滤（本轮未跑）
- 31-register：--group 1 过滤（本轮未跑）