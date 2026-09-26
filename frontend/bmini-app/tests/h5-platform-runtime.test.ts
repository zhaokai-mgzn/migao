// case_ids: BM-001, BM-005, BM-006
/**
 * bmini-app h5（浏览器）运行时平台适配（issue #5650）
 *
 * 用户 2026-09-26 裁定「**暂时只做 H5 浏览器访问，小程序链路先搁置**」⇒ h5 编译产物 = 唯一交付面。
 * 而 Taro 的 h5 实现包只对**一部分**小程序专有 API 给了 stub（`temporarilyNotSupport('<api>')`，
 * 实测 taro-h5 4.2.1 共 313 条）。本仓实际用到的 24 个 Taro API 里**只有 2 个**命中该清单：
 * `login` / `getRecorderManager`；另有 `scanCode` **不在**清单里，但实现是
 * `processOpenApi({ name: 'scanQRCode' })`（微信 JS-SDK）⇒ 纯浏览器下同样不可用。
 *
 * 本文件钉住三件事，每件都必须**显式**（不许静默失败、不许白屏、不许「点了没反应」）：
 *   1. `Taro.login` —— h5 一次都不调用，改走账号密码（BM-001 / BM-005）；
 *   2. `Taro.getRecorderManager` —— h5 一次都不调用，语音入口保留可见但禁用 + 点击给解释；
 *   3. `Taro.scanCode` —— h5 纯浏览器不调用，降级到手输单号这条**既有**路径（BM-006）；
 * 另：h5 的 SSE 是「整段解析（非流式）」—— 那是 2026-09-26 用户裁定**有意接受**的降级，
 * 判据在 `tests/sse.test.ts`（`dataType: 'text'` + 无 `onChunkReceived` 时不抛错、不丢内容）。
 */
import Taro from '@tarojs/taro'
import {
  canUseNativeScan,
  isH5,
  isWeapp,
  isWechatWebview,
  H5_SCAN_UNAVAILABLE_HINT,
  H5_WECHAT_LOGIN_UNAVAILABLE_HINT,
  H5_VOICE_UNAVAILABLE_HINT,
} from '../src/utils/platform'
import { miniAppLogin } from '../src/utils/auth'
import { isVoiceSupported } from '../src/utils/voice'
import { STORAGE_KEYS } from '../src/utils/constants'

jest.mock('../src/utils/request', () => ({
  post: jest.fn(),
}))

import { post } from '../src/utils/request'
const mockPost = post as jest.MockedFunction<typeof post>

const ORIGINAL_ENV = process.env.TARO_ENV
const ORIGINAL_UA = window.navigator.userAgent

/** Taro 把 `TARO_ENV` 声明成字面量联合类型 ⇒ 测试里改写要走一层环境袋（不污染 src 的类型） */
const envBag = process.env as unknown as Record<string, string | undefined>

function setPlatform(env: string | undefined): void {
  if (env === undefined) delete envBag.TARO_ENV
  else envBag.TARO_ENV = env
}

function setUserAgent(ua: string): void {
  Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true })
}

const CHROME_UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
const WECHAT_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 MicroMessenger/8.0.42'

describe('h5 运行时平台适配（issue #5650）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    delete (window as any).wx
    setUserAgent(CHROME_UA)
  })

  afterEach(() => {
    setPlatform(ORIGINAL_ENV)
    setUserAgent(ORIGINAL_UA)
    delete (window as any).wx
  })

  describe('平台判别本身（判据不许空转）', () => {
    it('编译目标读出正确：h5 / weapp 各归各位', () => {
      setPlatform('h5')
      expect(isH5()).toBe(true)
      expect(isWeapp()).toBe(false)

      setPlatform('weapp')
      expect(isH5()).toBe(false)
      expect(isWeapp()).toBe(true)
    })
  })

  describe('Taro.login：h5 不调用它，改走账号密码（BM-001 / BM-005）', () => {
    it('h5 下 miniAppLogin 一次都不调 Taro.login，也不发请求，并给出可行动的账号密码指引', async () => {
      setPlatform('h5')

      const result = await miniAppLogin(1)

      expect((Taro as any).login).not.toHaveBeenCalled()
      expect(mockPost).not.toHaveBeenCalled()
      expect(result.success).toBe(false)
      expect(result.error).toBe(H5_WECHAT_LOGIN_UNAVAILABLE_HINT)
      // 「明确提示」= 用户照着这句话就能把事办完（指向账号密码这条路）
      expect(result.error).toContain('密码')
    })

    it('weapp 下微信换码链路零回归：仍调 Taro.login 并 POST /api/auth/mini/login', async () => {
      setPlatform('weapp')
      mockPost.mockResolvedValue({
        success: true,
        data: { accessToken: 'tk-1', user: { id: 'u1', tenantId: 7 } },
      } as any)

      const result = await miniAppLogin(7)

      expect((Taro as any).login).toHaveBeenCalledTimes(1)
      expect(mockPost).toHaveBeenCalledWith(
        '/api/auth/mini/login',
        { code: 'mock_wx_code', tenantId: 7 },
        expect.objectContaining({ skipAuth: true }),
      )
      expect(result.success).toBe(true)
      expect(Taro.getStorageSync(STORAGE_KEYS.TOKEN)).toBe('tk-1')
    })
  })

  describe('Taro.getRecorderManager：h5 不调用它，语音入口保留可见但禁用', () => {
    // 共享 mock 的 getRecorderManager 返回**可用**录音器 ⇒ 若 h5 分支漏了，
    // 能力探测会拿到「可用」而 isVoiceSupported() 返回 true ⇒ 下面的判据当场红（不是靠调用计数）。
    it('h5：isVoiceSupported() 必须为 false（不靠「探测 stub 缺什么方法」推断环境）', () => {
      setPlatform('h5')
      expect(isH5()).toBe(true)
      expect(isVoiceSupported()).toBe(false)
      expect((Taro as any).getRecorderManager).not.toHaveBeenCalled()
    })

    it('weapp：仍走真录音器，isVoiceSupported() 为 true（零回归）', () => {
      setPlatform('weapp')
      expect(isVoiceSupported()).toBe(true)
    })

    it('h5 的提示文案说清「用文字」这个出路（不是一句「不支持」了事）', () => {
      expect(H5_VOICE_UNAVAILABLE_HINT).toContain('文字')
    })
  })

  describe('Taro.scanCode：h5 纯浏览器降级到手输单号（BM-006）', () => {
    it('h5 + Chrome：canUseNativeScan() 为 false（Taro.scanCode 的实现是微信 JS-SDK）', () => {
      setPlatform('h5')
      setUserAgent(CHROME_UA)
      delete (window as any).wx

      expect(isWechatWebview()).toBe(false)
      expect(canUseNativeScan()).toBe(false)
    })

    it('h5 + 微信内置浏览器且 wx.scanQRCode 可用：仍走 Taro.scanCode 原通道（不误伤）', () => {
      setPlatform('h5')
      setUserAgent(WECHAT_UA)
      ;(window as any).wx = { scanQRCode: jest.fn() }

      expect(isWechatWebview()).toBe(true)
      expect(canUseNativeScan()).toBe(true)
    })

    it('h5 + 微信 UA 但 JS-SDK 未就绪（无 wx.scanQRCode）：判不可用，不赌一次必然失败的调用', () => {
      setPlatform('h5')
      setUserAgent(WECHAT_UA)
      delete (window as any).wx

      expect(canUseNativeScan()).toBe(false)
    })

    it('weapp：不受 window.wx 缺失影响，原生扫码照旧可用', () => {
      setPlatform('weapp')
      delete (window as any).wx
      expect(canUseNativeScan()).toBe(true)
    })

    it('降级文案必须指到**既有**的手输单号路径（不平行造第二条识别链）', () => {
      expect(H5_SCAN_UNAVAILABLE_HINT).toContain('手输')
    })
  })
})
