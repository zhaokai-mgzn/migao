// case_ids: AU-014
/**
 * 扫码即登录（issue #7825）—— 手机端把二维码票据换成自己的登录态。
 *
 * 判据（每条都能单独变红）：
 * 1. 票据读取：`?qr=` 在 search 与 hash 两种形态下都能读到（Taro h5 两种打开形态）；
 * 2. 票据抹除：兑换后地址栏不再有 `qr=`，其它参数原样保留（票据不进历史/分享/referer）；
 * 3. 兑换成功：token/user/tenant 三件落地（与密码登录同一写点），探针记 `qr_login_ok`；
 * 4. 兑换失败：**不毁既有会话**（已登录的人扫到过期码不该被踢出去）+ 探针记 `qr_login_failed`；
 * 5. 启动门：地址带票据时，`checkAuth` **先等兑换**再判登录（否则页面先跳登录页，兑换白做）。
 *
 * 红证形态：把 `qrLoginReady` 的 await 从 `checkAuth` 里删掉 ⇒ 第 5 条红（无 token ⇒ 判未登录）；
 * 把 `stripQrTicket()` 调删掉 ⇒ 第 2 条红；把失败分支改成 `logout()` ⇒ 第 4 条红。
 */
import Taro from '@tarojs/taro'

const importQrLogin = () => require('../src/utils/qrLogin')
const importAuthDiag = () => require('../src/utils/authDiag')
const importConstants = () => require('../src/utils/constants')

const mockRequest = Taro.request as jest.Mock

function resetStorage(): void {
  ;(Taro as any).__clearStorage()
}

/**
 * 造一个 **structurally valid 的 JWT**（3 段 + 未过期 exp）。
 *
 * 为什么需要：`checkTokenValidity()` 会解析 `exp` —— 随手写个 `'tok-gate'` 会被判过期，
 * 于是 checkAuth 先走续期（而不是走「已登录」分支）⇒ 用例测的就不是「启动门」这件事了。
 */
function futureJwt(): string {
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString('base64')
  return `header.${encode({ exp: Math.floor(Date.now() / 1000) + 3600 })}.signature`
}

describe('扫码即登录（issue #7825）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    resetStorage()
    importAuthDiag().clearAuthDiag()
    window.history.replaceState({}, '', '/b/')
  })

  it('票据读取：search 与 hash 两种形态都认（decode 正确）；无票据 ⇒ 空串', () => {
    const { readQrTicket } = importQrLogin()

    expect(readQrTicket({ search: '?qr=abc123' })).toBe('abc123')
    expect(readQrTicket({ search: '?from=pc&qr=a%2Bb' })).toBe('a+b')
    expect(readQrTicket({ search: '', hash: '#/pages/chat/index/index?qr=hash-ticket' })).toBe('hash-ticket')
    expect(readQrTicket({ search: '', hash: '#/pages/chat/index/index' })).toBe('')
    expect(readQrTicket(null)).toBe('')
  })

  it('票据抹除：`qr=` 从地址里消失，其它参数原样保留（含 hash 路由形态）', () => {
    const { stripQrTicket } = importQrLogin()

    const replaceState = jest.fn()
    stripQrTicket({ href: 'https://app.invalid/b/?qr=abc123&from=pc' }, { replaceState })
    expect(replaceState).toHaveBeenCalledTimes(1)
    const next = String(replaceState.mock.calls[0][2])
    expect(next).not.toContain('qr=abc123')
    expect(next).toContain('from=pc')

    const hashReplace = jest.fn()
    stripQrTicket(
      { href: 'https://app.invalid/b/#/pages/auth/login/index?diag=1&qr=abc123' },
      { replaceState: hashReplace },
    )
    expect(hashReplace).toHaveBeenCalledTimes(1)
    const nextHashUrl = String(hashReplace.mock.calls[0][2])
    expect(nextHashUrl).not.toContain('qr=abc123')
    expect(nextHashUrl).toContain('diag=1')
  })

  it('兑换成功：token / user / tenant 三件落地 + 探针记 qr_login_ok', async () => {
    const { exchangeQrTicket } = importQrLogin()
    const { readAuthDiag } = importAuthDiag()
    const { STORAGE_KEYS } = importConstants()

    mockRequest.mockResolvedValueOnce({
      statusCode: 200,
      data: {
        success: true,
        data: { accessToken: 'tok-qr', user: { id: 'u9', tenantId: 7, nickname: '店主' } },
      },
    })

    await expect(exchangeQrTicket('ticket-1')).resolves.toBe(true)

    expect(Taro.getStorageSync(STORAGE_KEYS.TOKEN)).toBe('tok-qr')
    expect(JSON.parse(String(Taro.getStorageSync(STORAGE_KEYS.USER))).id).toBe('u9')
    expect(Taro.getStorageSync(STORAGE_KEYS.TENANT_ID)).toBe(7)
    expect(readAuthDiag().map((entry: any) => entry.kind)).toContain('qr_login_ok')
  })

  it('兑换失败（票据过期）：**不毁既有会话**，探针记 qr_login_failed', async () => {
    const { exchangeQrTicket } = importQrLogin()
    const { readAuthDiag } = importAuthDiag()
    const { STORAGE_KEYS } = importConstants()

    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'tok-existing')
    mockRequest.mockResolvedValueOnce({
      statusCode: 401,
      data: { success: false, error: { code: 'AUTH_FAILED', message: '二维码已过期，请重新扫码' } },
    })

    await expect(exchangeQrTicket('expired-ticket')).resolves.toBe(false)

    expect(Taro.getStorageSync(STORAGE_KEYS.TOKEN)).toBe('tok-existing')
    expect(readAuthDiag().map((entry: any) => entry.kind)).toContain('qr_login_failed')
    expect(readAuthDiag().map((entry: any) => entry.kind)).not.toContain('session_cleared_401')
  })

  it('兑换失败（网络异常）：返回 false，不抛（探针记 qr_login_failed）', async () => {
    const { exchangeQrTicket } = importQrLogin()
    const { readAuthDiag } = importAuthDiag()

    mockRequest.mockRejectedValueOnce(new Error('timeout'))

    await expect(exchangeQrTicket('ticket-2')).resolves.toBe(false)
    expect(readAuthDiag().map((entry: any) => entry.kind)).toContain('qr_login_failed')
  })

  it('工人设备扫「手机端」码 ⇒ **不兑换商家会话**，只标记去工人工作台（issue #7878）', async () => {
    const { STORAGE_KEYS } = importConstants()
    window.history.replaceState({}, '', '/b/?qr=ticket-for-worker')

    let gateResult: boolean | null = null
    let freshTaro: any = null
    await jest.isolateModulesAsync(async () => {
      // ⚠️ `resetModules` 之后 `@tarojs/taro` 是**新实例**（存储也是新的一份）⇒ 工人 session 必须
      //    写在**新实例**上，否则被测代码读到的是空存储（实测：这条会静默变成「没有工人会话」）。
      const taro = require('@tarojs/taro')
      freshTaro = taro.default ?? taro
      freshTaro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'worker-sess-1')
      const { qrLoginReady } = require('../src/utils/qrLogin')
      gateResult = await qrLoginReady
    })

    expect(gateResult).toBe(true)
    // 🔴 零请求：不把 PC 的商家令牌落到共用车间设备上
    expect(freshTaro.request).not.toHaveBeenCalled()
    // 票据不留在地址栏
    expect(window.location.search).not.toContain('qr=')
    // 一次性落地标记：商家首页据此把工人送到工人工作台
    expect(freshTaro.getStorageSync('qr_worker_landing')).toBe('1')
  })

  it('启动门：地址带票据时，checkAuth **先等兑换**再判登录', async () => {
    const { STORAGE_KEYS } = importConstants()
    window.history.replaceState({}, '', '/b/?qr=ticket-gate')

    let checkResult: boolean | null = null
    let seenByFreshModule = ''
    await jest.isolateModulesAsync(async () => {
      // ⚠️ `resetModules` 之后 `@tarojs/taro` 也会被重新实例化（**存储也是新的一份**）⇒ 必须用
      //    **新模块**的实例来注入响应与断言存储，否则跟被测代码用的不是同一个（实测：静默返回默认空响应）。
      const taro = require('@tarojs/taro')
      const freshTaro = taro.default ?? taro
      freshTaro.request.mockResolvedValueOnce({
        statusCode: 200,
        data: { success: true, data: { accessToken: futureJwt(), user: { id: 'u10', tenantId: 7 } } },
      })
      const { useAuthStore } = require('../src/store/authStore')
      checkResult = await useAuthStore.getState().checkAuth()
      seenByFreshModule = String(freshTaro.getStorageSync(STORAGE_KEYS.TOKEN) || '')
    })

    expect(checkResult).toBe(true)
    expect(seenByFreshModule).toMatch(/^header\./)
    expect(window.location.search).not.toContain('qr=')
  })
})
