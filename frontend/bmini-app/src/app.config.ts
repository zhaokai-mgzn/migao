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
        iconPath: 'assets/tabbar/sessions.png',
        selectedIconPath: 'assets/tabbar/sessions-active.png',
      },
      {
        pagePath: 'pages/sessions/index/index',
        text: '坐席',
        iconPath: 'assets/tabbar/chat.png',
        selectedIconPath: 'assets/tabbar/chat-active.png',
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