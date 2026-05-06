/**
 * Mock @tarojs/taro
 *
 * 为测试环境提供 Taro API 的 mock 实现
 */

const storage: Record<string, any> = {}

const Taro = {
  // Storage
  getStorageSync: jest.fn((key: string) => storage[key] ?? ''),
  setStorageSync: jest.fn((key: string, value: any) => {
    storage[key] = value
  }),
  removeStorageSync: jest.fn((key: string) => {
    delete storage[key]
  }),
  getStorage: jest.fn(),
  setStorage: jest.fn(),
  removeStorage: jest.fn(),

  // Navigation
  navigateTo: jest.fn(() => Promise.resolve()),
  redirectTo: jest.fn(() => Promise.resolve()),
  switchTab: jest.fn(() => Promise.resolve()),
  navigateBack: jest.fn(() => Promise.resolve()),
  reLaunch: jest.fn(() => Promise.resolve()),

  // Request
  request: jest.fn(() => Promise.resolve({ statusCode: 200, data: {} })),

  // UI
  showToast: jest.fn(),
  hideToast: jest.fn(),
  showLoading: jest.fn(),
  hideLoading: jest.fn(),
  showModal: jest.fn(() => Promise.resolve({ confirm: true, cancel: false })),
  showActionSheet: jest.fn(() => Promise.resolve({ tapIndex: 0 })),

  // Login
  login: jest.fn(() => Promise.resolve({ code: 'mock_wx_code' })),
  getUserInfo: jest.fn(() => Promise.resolve({
    userInfo: { nickName: 'TestUser', avatarUrl: '' },
  })),

  // System
  getSystemInfoSync: jest.fn(() => ({
    platform: 'devtools',
    system: 'iOS 14.0',
    screenWidth: 375,
    screenHeight: 812,
    windowWidth: 375,
    windowHeight: 812,
    statusBarHeight: 44,
    pixelRatio: 3,
  })),

  // Events
  eventCenter: {
    on: jest.fn(),
    off: jest.fn(),
    trigger: jest.fn(),
  },

  // 页面生命周期
  useDidShow: jest.fn(),
  useDidHide: jest.fn(),
  useReady: jest.fn(),
  usePullDownRefresh: jest.fn(),

  // Env
  ENV_TYPE: {
    WEAPP: 'WEAPP',
    SWAN: 'SWAN',
    ALIPAY: 'ALIPAY',
    TT: 'TT',
    WEB: 'WEB',
  },
  getEnv: jest.fn(() => 'WEAPP'),

  // 下拉刷新
  startPullDownRefresh: jest.fn(),
  stopPullDownRefresh: jest.fn(),

  // 辅助：清理 storage（供测试用）
  __clearStorage: () => {
    Object.keys(storage).forEach(k => delete storage[k])
  },
  __getStorage: () => ({ ...storage }),
}

export const useDidShow = jest.fn()
export const useDidHide = jest.fn()
export const useReady = jest.fn()
export const usePullDownRefresh = jest.fn()

export default Taro
module.exports = Taro
module.exports.default = Taro
module.exports.useDidShow = useDidShow
module.exports.useDidHide = useDidHide
module.exports.useReady = useReady
module.exports.usePullDownRefresh = usePullDownRefresh
