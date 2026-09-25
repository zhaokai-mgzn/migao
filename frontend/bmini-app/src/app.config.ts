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