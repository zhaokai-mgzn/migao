# 商家后端 UI 冒烟结果

时间: 2026-10-14T12:35:04.630Z ｜ 通过 28/34 ｜ 失败 2 ｜ 未配置 0 ｜ skip 4

| # | 旅程 | 结果 | 证据 |
|---|------|------|------|
| 1 | 01-login | ✅ | login → /dashboard，刷新后会话保持; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/01-login.png |
| 2 | 02-dashboard | ✅ | 看板渲染数字片段: 1|4|2|3|5; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/02-dashboard.png |
| 3 | 03-briefing | ✅ | 简报页渲染，body 文本长度 202; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/03-briefing.png |
| 4 | 04-agent-workspace-redirect | ✅ | 重定向到 /agent-workspace/human-sessions; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/04-agent-workspace-redirect.png |
| 5 | 05-human-sessions | ✅ | 在线接待页渲染（ai-agent 未起，空态）— UI-only; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/05-human-sessions.png |
| 6 | 06-agent-sessions | ❌ | 会话历史页渲染（ai-agent 未起，空态）— UI-only; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/06-agent-sessions.png |
| 7 | 07-chat | ❌ | 对话页输入框可用（ai-agent 未起）— UI-only; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/07-chat.png |
| 8 | 08-products-list | ✅ | 商品列表渲染 1 行; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/08-products-list.png |
| 9 | 09-products-new | ✅ | 门幅 值/显示分离 ✓(["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]→'2.8') + 建品可见 ✓(冒烟SKU商品1791981181241); /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/o |
| 10 | 10-product-detail | ✅ | 商品详情渲染（http://localhost:3001/products/b304e3cef375e205864246b9bb846051）; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/10-pr |
| 11 | 11-product-edit-doorwidth | ✅ | 门幅下拉回显: value=2.8, 选项=["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]（自造商品 e378137946273d983876b78dbe70c1ff 已清理）; /Users/guangzhen.zk/ai native/migao/acceptance/2026- |
| 12 | 12-processing | ✅ | 加工项 新建→列表可见→编辑→删除 完成；启停toggle可见=false; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/12-processing.png |
| 13 | 13-categories | ✅ | 分类 新建→可见→行内删除; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/13-categories.png |
| 14 | 14-orders-list | ✅ | 订单列表 20 行（无分页按钮或单页）; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/14-orders-list.png |
| 15 | 15-orders-new | ✅ | 新建订单提交后跳转 http://localhost:3001/orders/new; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/15-orders-new.png |
| 16 | 16-order-detail-processing-order | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/16-order-detail-processing-order.png |
| 17 | 32-production-qr-and-piecework | ⏭️ skip | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/32-production-qr-and-piecework.png |
| 18 | 17-order-ship | ⏭️ skip | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/17-order-ship.png |
| 19 | 18-after-sales-list | ✅ | 售后工单列表渲染 1 行; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/18-after-sales-list.png |
| 20 | 19-after-sales-detail | ✅ | 关闭原因落库回显=true; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/19-after-sales-detail.png |
| 21 | 20-customers-list | ✅ | 客户列表 20 行; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/20-customers-list.png |
| 22 | 21-customer-detail | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/21-customer-detail.png |
| 23 | 22-finance | ✅ | 财务对账页渲染; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/22-finance.png |
| 24 | 23-employees | ✅ | 员工 新建→可见→改手机号落库=false→删除；空提交校验=false; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/23-employees.png |
| 25 | 24-roles | ✅ | 岗位权限页 1 行，行内「编辑」（button[title="编辑"]）打开权限弹窗 ✓; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/24-roles.png |
| 26 | 25-settings | ✅ | 设置页只读校验：Tab 数=11、自动保存提示=false、意外「保存」按钮=true、密码字段=0、4xx=0; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/25-settings.png |
| 27 | 26-notifications | ✅ | 通知中心渲染，已读操作可用; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/26-notifications.png |
| 28 | 27-corporate-home | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/27-corporate-home.png |
| 29 | 28-corporate-about | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/28-corporate-about.png |
| 30 | 29-corporate-contact | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/29-corporate-contact.png |
| 31 | 30-corporate-services | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/30-corporate-services.png |
| 32 | 31-register | ✅ | 注册页渲染，输入控件=2; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-14/main-ui/out/screenshots/31-register.png |
| 33 | 27-corporate | ⏭️ skip | 整轮预算 1500s 到点：本轮未跑 |
| 34 | 28-register | ⏭️ skip | 整轮预算 1500s 到点：本轮未跑 |

## ⏭️ skip（前置/依赖不满足，**未跑**）

- 32-production-qr-and-piecework：前置不满足（生产路线/默认工艺未配置）：本租户指定单（81c501b3a5aa383e8df7ed5def9f1f83）生成加工单**未落库**：接口 HTTP 200 但 data 为空 —— api 日志 INCIDENT_PRODUCTION_ROUTING_UNRESOLVED「订单缺 craft 且该租户没有
- 17-order-ship：前置不满足（生产路线/默认工艺未配置）：本租户指定单（e909fd6a5e84ce97b816797cfb3f0ef7）生成加工单**未落库**：接口 HTTP 200 但 data 为空 —— api 日志 INCIDENT_PRODUCTION_ROUTING_UNRESOLVED「订单缺 craft 且该租户没有
- 27-corporate：整轮预算 1500s 到点：本轮未跑
- 28-register：整轮预算 1500s 到点：本轮未跑