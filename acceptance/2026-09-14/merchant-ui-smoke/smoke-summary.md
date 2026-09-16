# 商家后端 UI 冒烟结果

时间: 2026-09-14T09:21:30.819Z ｜ 通过 31/31 ｜ 失败 0

| # | 旅程 | 结果 | 证据 |
|---|------|------|------|
| 1 | 01-login | ✅ | login → /dashboard，刷新后会话保持; /tmp/ui-smoke/out5/screenshots/01-login.png |
| 2 | 02-dashboard | ✅ | 看板渲染数字片段: 44|11|419|12|¥3,955; /tmp/ui-smoke/out5/screenshots/02-dashboard.png |
| 3 | 03-briefing | ✅ | 简报页渲染，body 文本长度 225; /tmp/ui-smoke/out5/screenshots/03-briefing.png |
| 4 | 04-agent-workspace-redirect | ✅ | 重定向到 /agent-workspace/human-sessions; /tmp/ui-smoke/out5/screenshots/04-agent-workspace-redirect.png |
| 5 | 05-human-sessions | ✅ | 在线接待页渲染（ai-agent 未起，空态）— UI-only; /tmp/ui-smoke/out5/screenshots/05-human-sessions.png |
| 6 | 06-agent-sessions | ✅ | 会话历史页渲染（ai-agent 未起，空态）— UI-only; /tmp/ui-smoke/out5/screenshots/06-agent-sessions.png |
| 7 | 07-chat | ✅ | 对话页输入框可用（ai-agent 未起）— UI-only; /tmp/ui-smoke/out5/screenshots/07-chat.png |
| 8 | 08-products-list | ✅ | 商品列表渲染 10 行; /tmp/ui-smoke/out5/screenshots/08-products-list.png |
| 9 | 09-products-new | ✅ | 门幅 值/显示分离 ✓(["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]→'2.8') + 建品可见 ✓(冒烟SKU商品1789377558016); /tmp/ui-smoke/out5/screenshots/09-products-new.png |
| 10 | 10-product-detail | ✅ | 商品详情渲染（http://localhost:3001/products/701dec2d2d994da111167c859c7cbf26）; /tmp/ui-smoke/out5/screenshots/10-product-detail.png |
| 11 | 11-product-edit-doorwidth | ✅ | 门幅下拉回显: value=2.8, 选项=["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]; /tmp/ui-smoke/out5/screenshots/11-product-edit-doorwidth.png |
| 12 | 12-processing | ✅ | 加工项 新建→列表可见→编辑→删除 完成；启停toggle可见=false; /tmp/ui-smoke/out5/screenshots/12-processing.png |
| 13 | 13-categories | ✅ | 分类 新建→可见→行内删除; /tmp/ui-smoke/out5/screenshots/13-categories.png |
| 14 | 14-orders-list | ✅ | 订单列表 20 行（无分页按钮或单页）; /tmp/ui-smoke/out5/screenshots/14-orders-list.png |
| 15 | 15-orders-new | ✅ | 新建订单提交后跳转 http://localhost:3001/orders/new; /tmp/ui-smoke/out5/screenshots/15-orders-new.png |
| 16 | 16-order-detail-processing-order | ✅ | 加工单生成+流转:  [发加工→ok] [开始加工→ok] [加工完成→ok]; 加工单可见=false; /tmp/ui-smoke/out5/screenshots/16-order-detail-processing-order.png |
| 17 | 17-order-ship | ✅ | 发货页表单渲染（4 控件）; /tmp/ui-smoke/out5/screenshots/17-order-ship.png |
| 18 | 18-after-sales-list | ✅ | 售后工单列表渲染 20 行; /tmp/ui-smoke/out5/screenshots/18-after-sales-list.png |
| 19 | 19-after-sales-detail | ✅ | /tmp/ui-smoke/out5/screenshots/19-after-sales-detail.png |
| 20 | 20-customers-list | ✅ | 客户列表 20 行; /tmp/ui-smoke/out5/screenshots/20-customers-list.png |
| 21 | 21-customer-detail | ✅ | /tmp/ui-smoke/out5/screenshots/21-customer-detail.png |
| 22 | 22-finance | ✅ | 财务对账页渲染; /tmp/ui-smoke/out5/screenshots/22-finance.png |
| 23 | 23-employees | ✅ | 员工 新建→可见→改手机号落库=false→删除；空提交校验=false; /tmp/ui-smoke/out5/screenshots/23-employees.png |
| 24 | 24-roles | ✅ | 岗位权限页 1 行，权限编辑弹窗可开; /tmp/ui-smoke/out5/screenshots/24-roles.png |
| 25 | 25-settings | ✅ | 设置页渲染，Tab 数=1; /tmp/ui-smoke/out5/screenshots/25-settings.png |
| 26 | 26-notifications | ✅ | 通知中心渲染，已读操作可用; /tmp/ui-smoke/out5/screenshots/26-notifications.png |
| 27 | 27-corporate-home | ✅ | /tmp/ui-smoke/out5/screenshots/27-corporate-home.png |
| 28 | 28-corporate-about | ✅ | /tmp/ui-smoke/out5/screenshots/28-corporate-about.png |
| 29 | 29-corporate-contact | ✅ | /tmp/ui-smoke/out5/screenshots/29-corporate-contact.png |
| 30 | 30-corporate-services | ✅ | /tmp/ui-smoke/out5/screenshots/30-corporate-services.png |
| 31 | 31-register | ✅ | 注册页渲染，输入控件=2; /tmp/ui-smoke/out5/screenshots/31-register.png |