# 商家后端 UI 冒烟结果

时间: 2026-10-14T16:34:18.017Z ｜ 通过 10/32 ｜ 失败 0 ｜ 未配置 0 ｜ skip 22

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
| 10 | 10-product-detail | ✅ | 商品详情渲染（http://localhost:3001/products/fedc11b97d26ca05662ae664a462d14b）; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/10-product-detail.png |
| 11 | 11-product-edit-doorwidth | ✅ | 门幅下拉回显: value=2.8, 选项=["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]（自造商品 d260c2b4dbf3b3ea25b3951beeac5a32 已清理）; acceptance/2026-10-14/main-ui/out-r2-final-1/screens |
| 12 | 12-processing | ✅ | 加工项 新建→列表可见→编辑→删除 完成；启停toggle可见=false; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/12-processing.png |
| 13 | 13-categories | ✅ | 分类 新建→可见→行内删除; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/13-categories.png |
| 14 | 14-orders-list | ✅ | 订单列表 20 行（无分页按钮或单页）; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/14-orders-list.png |
| 15 | 15-orders-new | ✅ | 新建订单提交后跳转 http://localhost:3001/orders/new（自造商品 冒烟建单商品1791995618571 已清理，商品总数 14→14）; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/15-orders-new.png |
| 16 | 16-order-detail-processing-order | ✅ | 加工单生成+流转:  [发加工→徽标「已发加工」✓;按钮切换✓] [开始加工→徽标「加工中」✓;按钮切换✓] [加工完成→徽标「加工完成」✓;按钮切换✓]; 加工单 JG-20261015-9530 可见=true；前置自造订单 08f9aa264c3edb7429e19234cb756744（下游 17- 复用，不清 |
| 17 | 32-production-qr-and-piecework | ⏭️ skip | --group 1 过滤（本轮未跑） |
| 18 | 17-order-ship | ✅ | 发货页表单渲染（7 控件）; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/17-order-ship.png |
| 19 | 18-after-sales-list | ✅ | 售后工单列表渲染 11 行; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/18-after-sales-list.png |
| 20 | 19-after-sales-detail | ✅ | 关闭原因落库回显=true; acceptance/2026-10-14/main-ui/out-r2-final-1/screenshots/19-after-sales-detail.png |
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