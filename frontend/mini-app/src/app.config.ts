export default defineAppConfig({
  pages: [
    'pages/chat/index/index',
    'pages/chat/sessions/index',
    'pages/auth/login/index',
    'pages/profile/index/index',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#2F54EB',
    navigationBarTitleText: '小布',
    navigationBarTextStyle: 'white',
  },
  tabBar: {
    color: '#999999',
    selectedColor: '#2F54EB',
    backgroundColor: '#ffffff',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'pages/chat/index/index',
        text: '对话',
        iconPath: 'assets/tabbar/chat.png',
        selectedIconPath: 'assets/tabbar/chat-active.png',
      },
      {
        pagePath: 'pages/chat/sessions/index',
        text: '会话',
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
