export default defineAppConfig({
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
    'pages/production/index/index',
    // 工人登录（issue #4733）：工号 + PIN，主路径不依赖微信；与商家登录页是两条链路
    'pages/worker/login/index',
    // 工人**拍照入库**（issue #5052 P3）：拍上游标签 → 本机解码优先（0 次 LLM）→ 工人确认
    // → 过账（不可逆，二次确认）→ 出 50×30mm 标签 → 送打印（Web Bluetooth，Android / 桌面 Chrome）。
    // 走 `/api/worker/inbound/**`（工人零商家权限码，不是管理面）。
    // 路由字面量是**单一真值**：`src/utils/inbound/gaps.ts` 的 `INBOUND_PAGE_ROUTE` 必须逐字等于它
    // （守卫 tests/inbound-page-platform-gaps.test.ts 判据 G0：没登记进这里 = 死链 ⇒ 红）
    'pages/worker/inbound/index',
    // 工人**拍照补打标签**（issue #5640 功能②）：拍米高入库标签（或手输 8 位短码）→ 看单据详情
    // → 补打一张新标签。标签贴丢 / 磨花 / 贴错时，工人不必再回电脑端管理后台。
    // 版面 / 渲染 / 打印三件与入库页**共用**（`src/utils/inbound/labelLayout|labelCanvas|labelPrint`）
    // ⇒ 只换数据源（过账回执 ⇒ 按短码读详情）。路由字面量同上：gaps.ts 的 `REPRINT_PAGE_ROUTE` 必须逐字等于它。
    'pages/worker/reprint/index',
    // ── 管理面 4 项（issue #5654）：管理员离店后也要能办的事 ──
    // 路由字面量是**单一真值**：`src/utils/adminPermission.ts` 的 `ADMIN_SURFACES[].route`
    // 必须逐字等于这里的字符串（守卫 tests/admin-surfaces-platform-guard.test.ts 核验：
    // 页面没登记进这里 = 死链 ⇒ 红）。4 项都走 `/api/admin/**`（商家会话），不是工人面。
    'pages/admin/pool/index',
    'pages/admin/inbound/index',
    'pages/admin/after-sales/index',
    'pages/admin/piecework/index',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#0A2540',
    navigationBarTitleText: '米宝商家助手',
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
        text: '问米宝',
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
        // 🔴 此前与「问米宝」共用 chat.png（两处 img.src 的 base64 实测完全相同）⇒ 底栏两个入口长得一样；
        // 现用「列表」字形（客服坐席列表），与问米宝的对话气泡区分开。判据 = tests/tabbar-icons.test.ts
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