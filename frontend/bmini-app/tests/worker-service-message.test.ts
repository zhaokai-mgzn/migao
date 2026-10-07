// case_ids: BM-033
/**
 * 工人登录的**失败文案**链路（issue #6467 切片 1 判据 1 的一半）。
 *
 * ## 病灶（零推断，读服务端信封即可判定）
 * 服务端失败信封是 `ApiResponse` = `{success:false, error:{code,message}}`
 * （`backend/admin-api/src/main/java/com/migao/admin/config/GlobalExceptionHandler.java` 的
 * `handleBusinessException`），而 `frontend/bmini-app/src/services/workerService.ts` 的 `fail()`
 * 原先只读 `error.data.message` —— 取不到就落回 `error.message`，而请求层抛的是
 * `new Error('Request failed with status 401')` ⇒ **工人输错 PIN / 工人身份失效时，
 * 上屏的是技术噪声而不是服务端那句「工号或 PIN 不正确（或尚未登录工人身份…）」**。
 *
 * 现场（2026-10-07 生产）正是这条链：报工写入口 401 的服务端文案被吞掉，用户只看到
 * 「登录已过期，请重新登录」（那是请求层另一条缺陷，见 `tests/request.test.ts` 的 401 分流判据）。
 *
 * ## 判据
 * ① 401 + `{success:false, error:{message}}` ⇒ `res.message` **逐字等于**服务端文案；
 * ② 兼容信封印花（顶层 `{message}`）同样取到；③ 传输层失败 ⇒ `offline=true` 且文案可行动
 *   （不是 `Request failed with status …` 这类 HTTP 层噪声）。
 *
 * ## 红证（注入方式 + 修前读数见 PR body）
 * 把 `fail()` 的消息取值改回 `error?.data?.message || error?.message || fallback` ⇒ ① 判红
 * （收到「Request failed with status 401」）。
 */
import Taro from '@tarojs/taro'
import { workerLogin } from '../src/services/workerService'

describe('workerService 失败文案 = 服务端文案（issue #6467）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  it('🔴 401（`{success:false, error:{message}}` 信封）⇒ 原样上屏服务端文案，不是 HTTP 层噪声', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 401,
      data: { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } },
    })

    const res = await workerLogin('G001', '0000')

    expect(res.success).toBe(false)
    expect(res.message).toBe('工号或 PIN 不正确')
    expect(res.message).not.toContain('Request failed')
  })

  it('兼容信封印花：顶层 `{message}` 也取到（与 `productionService` 同口径）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 422,
      data: { success: false, message: '该工号已停用' },
    })

    const res = await workerLogin('G001', '2468')

    expect(res.message).toBe('该工号已停用')
  })

  it('传输层失败 ⇒ offline=true 且文案可行动（不把 HTTP 状态码当原因上屏）', async () => {
    // 请求层对可重试的网络错误会走指数退避（MAX_RETRIES + 1s/2s/4s）⇒ 用假定时器把窗口推完，
    // 不用真等 7 秒（判据关心的是**分类与文案**，不是退避时长）。
    jest.useFakeTimers()
    try {
      const timeoutError: any = new Error('request:fail timeout')
      timeoutError.errMsg = 'request:fail timeout'
      ;(Taro.request as jest.Mock).mockRejectedValue(timeoutError)

      const pending = workerLogin('G001', '2468')
      await jest.advanceTimersByTimeAsync(30_000)
      const res = await pending

      expect(res.offline).toBe(true)
      expect(res.message).not.toContain('Request failed')
    } finally {
      jest.useRealTimers()
    }
  })
})
