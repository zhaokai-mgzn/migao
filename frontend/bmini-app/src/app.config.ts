export default defineAppConfig({
  // 🔴 小程序蓝牙**搜索**权限（issue #7802）：`lpapi-ble-wx` 在安卓上靠 `wx.startBluetoothDevicesDiscovery`
  // 找打印机，而该接口要求**已声明位置权限**，否则一台都搜不到（厂商 SDK README「二、权限配置」）。
  // 只声明用途文案，**不主动请求定位**：工人在蓝牙授权弹窗里看到的是「用于搜索蓝牙标签打印机」。
  // 另需在小程序后台「管理 → 账号设置 → 用户隐私保护指引」勾选：位置信息（蓝牙搜索）/ 设备信息 / 蓝牙。
  permission: {
    'scope.userLocation': {
      desc: '用于搜索蓝牙标签打印机',
    },
  },
  pages: [
    'pages/chat/index/index',
    'pages/dashboard/index/index',
    'pages/sessions/index/index',
    'pages/profile/index/index',
    'pages/sessions/detail/index',
    'pages/auth/login/index',
    // 首登强制改密页（issue #5485）：管理员设的初始密码必须首登后改掉；
    // 改密端点(`POST /api/auth/password/change`)在强制改密白名单内、成功即换发新凭据
    // ⇒ 商家员工在本页自助改密，不必去电脑端
    'pages/auth/change-password/index',
    // 🔴 **小程序工人扫码报工页的起落**：2026-10-14 按 issue #6868 整页下架（当时报工唯一实现 =
    // `frontend/worker-h5` 的 `/w/`）；2026-10-26 用户改判（#7806「手机端收口到 bmini」）后由
    // #7812 P2a 重建 —— 现登记在下面（`pages/worker/report/index`），且 #7879 起**它就是扫码的
    // 落地面**（服务端 `/s/` `/o/` 302 → `/b/?t=<token>`）。不用 web-view，见
    // `src/utils/inbound/lpapiTransport.ts` 文件头的 2026-09-29 形态裁定。
    // 商家面（tabBar / pages/admin/** / pages/production/order-detail）一个字节都没动。
    // 工人登录（issue #4733）：工号 + PIN，主路径不依赖微信；与商家登录页是两条链路
    'pages/worker/login/index',
    // 工人**首页**（issue #6467 切片 1）：纯工人设备（有工人 session、无商家会话）的落地页 ——
    // 身份卡 + 扫码报工 / 拍照入库 / 补打入库标签 + 退出工人身份。
    // 为什么不是商家 tabBar：工人零商家权限（`/api/admin/**` 拒绝集合含 `worker`），
    // 且 `Taro.switchTab` 只能落 tabBar 页 ⇒ 工人登录成功只能 redirectTo 本页。
    // 路由字面量是**单一真值**：`src/utils/inbound/gaps.ts` 的 `WORKER_HOME_ROUTE` 必须逐字等于它
    // （没登记 = 死链 ⇒ 入口台账 tests/page-entry-reachability.test.ts 与 G0 同款守卫判红）
    'pages/worker/home/index',
    // 工人**扫码报工**（issue #7812 P2a）：扫一扫 / 手输码 → 一屏（套/部位/帘种/工序/应做）→ 报工 → 回执。
    // 走 `/api/worker/production/scan[/complete]`（工人零商家权限码）；**记账口径一字未动**。
    // 为什么现在有这一页：2026-10-26 用户改判（#7806）——手机端收口到 bmini，小程序是最终形态。
    'pages/worker/report/index',
    // 工人**拍照入库**（issue #5052 P3）：拍上游标签 → 本机解码优先（0 次 LLM）→ 工人确认
    // → 过账（不可逆，二次确认）→ 出 50×80mm 标签 → 送打印（Web Bluetooth，Android / 桌面 Chrome）。
    // 走 `/api/worker/inbound/**`（工人零商家权限码，不是管理面）。
    // 路由字面量是**单一真值**：`src/utils/inbound/gaps.ts` 的 `INBOUND_PAGE_ROUTE` 必须逐字等于它
    // （守卫 tests/inbound-page-platform-gaps.test.ts 判据 G0：没登记进这里 = 死链 ⇒ 红）
    'pages/worker/inbound/index',
    // 工人**拍照补打标签**（issue #5640 功能②）：拍观星台入库标签（或手输 8 位短码）→ 看单据详情
    // → 补打一张新标签。标签贴丢 / 磨花 / 贴错时，工人不必再回电脑端管理后台。
    // 版面 / 渲染 / 打印三件与入库页**共用**（`src/utils/inbound/labelLayout|labelCanvas|labelPrint`）
    // ⇒ 只换数据源（过账回执 ⇒ 按短码读详情）。路由字面量同上：gaps.ts 的 `REPRINT_PAGE_ROUTE` 必须逐字等于它。
    'pages/worker/reprint/index',
    // 工人**拍照发货**（issue #6761，#5648 的 UI 面收口）：拍订单行 / 商品标签 → 识别候选
    // → **工人核对**（不确定的格子留空、绝不预填 0）→ 用单号经 `GET /api/worker/production/scan?token=`
    // 定位订单（拿 `order_id`）→ 生成发货单（实发明细 + 运单号，幂等键 `X-Client-Request-Id`）
    // → 实发读面（套 / 件 / 卷说人话）。
    // 走 `/api/worker/shipment/**`（工人零商家权限码，不是管理面）；**零后端改动**。
    // 路由字面量是**单一真值**：`src/utils/inbound/gaps.ts` 的 `SHIPMENT_PAGE_ROUTE` 必须逐字等于它
    // （守卫 tests/page-entry-reachability.test.ts 的 L2：没登记进这里 = 死链 ⇒ 红）
    'pages/worker/shipment/index',
    // 工人**待发货单**列表（issue #7806 P1a）：全完工订单一屏可见（订单号 / 收货人 + 电话 /
    // 地址 / 物流方式 · 公司 / N 套全完工），只读、无写入口。
    // 数据源 = `GET /api/worker/shipment/orders`（#7764 已上线：只回「多套全部完工 + 可发货状态 +
    // 作业单已完成」的单）⇒ 端侧**不筛、不补算**（半完工行照实显示 `1/3 套`）。
    // ⚠️ 本期不含标签打印（依赖 #7803 的小程序 BLE 通道 + 画布）。
    // 路由字面量是**单一真值**：`src/utils/inbound/gaps.ts` 的 `SHIPMENT_ORDERS_PAGE_ROUTE`
    // 必须逐字等于它（没登记 = 死链 ⇒ 入口台账 tests/page-entry-reachability.test.ts 的 L0/L2 判红）
    'pages/worker/shipment-orders/index',
    // ── 管理面 4 项（issue #5654）：管理员离店后也要能办的事 ──
    // 路由字面量是**单一真值**：`src/utils/adminPermission.ts` 的 `ADMIN_SURFACES[].route`
    // 必须逐字等于这里的字符串（守卫 tests/admin-surfaces-platform-guard.test.ts 核验：
    // 页面没登记进这里 = 死链 ⇒ 红）。4 项都走 `/api/admin/**`（商家会话），不是工人面。
    'pages/admin/pool/index',
    'pages/admin/inbound/index',
    'pages/admin/after-sales/index',
    'pages/admin/piecework/index',
    // 加工单**详情**（商家只读面，issue #6567）：「数据」页三类待办（待排产 / 卡在哪 / 待发货）的落脚点。
    // 此前它们一律落到报工页（工人面：扫一扫 + 手输单号 + 「去登录工人身份」）⇒ 商家点一张待办卡片
    // 看到的是「请先登录工人身份」（用户 2026-10-08 反馈）。本页**纯只读**：不扫码、不报工、不发货，
    // 读 `GET /api/admin/processing-orders/{id}` + `GET /api/admin/production/orders/{id}/operations`
    // （都是 `production:view`，与 todo-overview 同码）。路由字面量是**单一真值**：
    // `backend/admin-api/src/main/java/com/migao/admin/service/ProductionTodoService.java` 里
    // `processingOrderDetailPage()` 拼的路径必须逐字等于它（入口台账 pageEntries.ts 双向钉住）。
    'pages/production/order-detail/index',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#0A2540',
    navigationBarTitleText: '黄金策商家助手',
    navigationBarTextStyle: 'white',
    backgroundColor: '#F5F7FA',
  },
  tabBar: {
    color: '#9AA5B1',
    selectedColor: '#1A73E8',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    list: [
      {
        pagePath: 'pages/chat/index/index',
        text: '问黄金策',
        iconPath: 'assets/tabbar/chat.png',
        selectedIconPath: 'assets/tabbar/chat-active.png',
      },
      {
        pagePath: 'pages/dashboard/index/index',
        text: '数据',
        // 看板字形（issue #5759）：此前借用 sessions 的「列表」图标，语义不符，现用新建的柱状图
        iconPath: 'assets/tabbar/dashboard.png',
        selectedIconPath: 'assets/tabbar/dashboard-active.png',
      },
      {
        pagePath: 'pages/sessions/index/index',
        text: '坐席',
        // 🔴 此前与「问黄金策」共用 chat.png（两处 img.src 的 base64 实测完全相同）⇒ 底栏两个入口长得一样；
        // 现用「列表」字形（客服坐席列表），与问黄金策的对话气泡区分开。判据 = tests/tabbar-icons.test.ts
        iconPath: 'assets/tabbar/sessions.png',
        selectedIconPath: 'assets/tabbar/sessions-active.png',
      },
      {
        pagePath: 'pages/profile/index/index',
        text: '我的',
        iconPath: 'assets/tabbar/profile.png',
        selectedIconPath: 'assets/tabbar/profile-active.png',
      },
    ],
  },
})