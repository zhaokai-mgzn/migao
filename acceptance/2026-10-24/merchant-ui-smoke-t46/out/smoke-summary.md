# 商家后端 UI 冒烟结果

时间: 2026-10-23T19:06:19.221Z ｜ 通过 33/33 ｜ 失败 0 ｜ 未配置 0 ｜ skip 0

| # | 旅程 | 结果 | 证据 |
|---|------|------|------|
| 1 | 01-login | ✅ | login → /dashboard，刷新后会话保持; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/01-login.png |
| 2 | 02-dashboard | ✅ | 看板渲染数字片段: 4|4|5|3|5; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/02-dashboard.png |
| 3 | 03-briefing | ✅ | 简报页渲染，body 文本长度 1261; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/03-briefing.png |
| 4 | 04-agent-workspace-redirect | ✅ | 重定向到 /agent-workspace/human-sessions; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/04-agent-workspace-redirec |
| 5 | 05-human-sessions | ✅ | 在线接待页渲染（ai-agent 未起，空态）— UI-only; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/05-human-sessions.png |
| 6 | 06-agent-sessions | ✅ | 会话历史页渲染（ai-agent 未起，空态）— UI-only; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/06-agent-sessions.png |
| 7 | 07-chat | ✅ | 对话页输入框可用（ai-agent 未起）— UI-only; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/07-chat.png |
| 8 | 08-products-list | ✅ | 商品列表渲染 1 行; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/08-products-list.png |
| 9 | 09-products-new | ✅ | 门幅 值/显示分离 ✓(["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]→'2.8') + 建品可见 ✓(冒烟SKU商品1792782109843); /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant- |
| 10 | 10-product-detail | ✅ | 商品详情渲染（http://localhost:3001/products/c4be96295488418c92211d6762e7d28b）; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/scr |
| 11 | 11-product-edit-doorwidth | ✅ | 门幅下拉回显: value=2.8, 选项=["|请选择","2.8|2.8米","3.2|3.2米","3.4|3.4米"]（自造商品 d0443318334173875d5006e9a99a7b93 已清理）; /Users/guangzhen.zk/ai native/migao/acceptance/2026- |
| 12 | 12-processing | ✅ | 加工项 新建→列表可见→编辑→删除 完成；启停toggle可见=false; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/12-processing.png |
| 13 | 13-categories | ✅ | 分类 新建→可见→行内删除; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/13-categories.png |
| 14 | 14-orders-list | ✅ | 订单列表 20 行（无分页按钮或单页）; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/14-orders-list.png |
| 15 | 15-orders-new | ✅ | 表单校验提示可见; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/15-orders-new.png |
| 16 | 16-order-detail-processing-order | ✅ | 加工单生成+流转:  [发加工→徽标「已发加工」✓;按钮切换✓] [开始加工→徽标「加工中」✓;按钮切换✓] [加工完成→徽标「加工完成」✓;按钮切换✓]; 加工单 JG-20261024-3223 可见=true；前置自造订单 f7332291358bf6d557337a523fa0682b（下游 17- 复用，不清 |
| 17 | 32-production-qr-and-piecework | ✅ | 订单 5a0d5b297219c39192a3181b53cbcbc5 / 加工单 JG-20261024-3225：qr_token=6d52490e49df45c9bce6a170744b1b27；工序 12 道；DOM qr=1 占位=0 行=12；报工「精裁-布」2米 → 进度 8%（已完成 1/12 道工序） |
| 18 | 17-order-ship | ✅ | 发货页表单渲染（7 控件）; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/17-order-ship.png |
| 19 | 17b-ship-order-real | ✅ | 订单 d7f5bfaca8adb8d4872f5481f6b64098：UI 提交（X-Client-Request-Id=f9573c1e…） → API 读回 status=shipped/trackingNo=SF1792782267405；order_shipments 库 0→1（API 读面 0→1）；同键 |
| 20 | 18-after-sales-list | ✅ | 售后工单列表渲染 14 行; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/18-after-sales-list.png |
| 21 | 19-after-sales-detail | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/19-after-sales-detail.png |
| 22 | 20-customers-list | ✅ | 客户列表 7 行; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/20-customers-list.png |
| 23 | 21-customer-detail | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/21-customer-detail.png |
| 24 | 22-finance | ✅ | 财务对账页渲染; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/22-finance.png |
| 25 | 23-employees | ✅ | 员工 新建→可见→改手机号落库=false→删除；空提交校验=false; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/23-employees.png |
| 26 | 24-roles | ✅ | 岗位权限页 11 行，行内「编辑」（button[title="编辑"]）打开权限弹窗 ✓; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/24-roles.png |
| 27 | 25-settings | ✅ | 设置页只读校验：Tab 数=17、自动保存提示=true、意外「保存」按钮=false、密码字段=0、4xx=0; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/25-set |
| 28 | 26-notifications | ✅ | 通知中心渲染，已读操作可用; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/26-notifications.png |
| 29 | 27-corporate-home | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/27-corporate-home.png |
| 30 | 28-corporate-about | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/28-corporate-about.png |
| 31 | 29-corporate-contact | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/29-corporate-contact.png |
| 32 | 30-corporate-services | ✅ | /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/30-corporate-services.png |
| 33 | 31-register | ✅ | 注册页渲染，输入控件=2; /Users/guangzhen.zk/ai native/migao/acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/31-register.png |