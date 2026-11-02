// case_ids: BM-058
/**
 * **短链 JSON 解析面**（`GET /s/{短码}/json`）的前端调用点（issue #8196）
 *
 * 微信「扫普通链接二维码打开小程序」（A 档）里，小程序**不跟随 HTTP 302** ⇒ 纸上的
 * `https://app.migaozn.com/s/<短码>` 必须还有一条 JSON 面把短码换成报工 token。
 * 服务端的形状/不泄露判据在 `WorkerShortLinkControllerTest`（admin-api）；本文件判**客户端那一半**：
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | ① | 请求形状：`GET /s/<短码>/json`、`Accept: application/json`、**不带**商家凭据（公开面） | 路径写错 / 带 Authorization ⇒ 红 |
 * | ② | 成功 ⇒ `{reportPath, token}` 原样带回（页面只用 token，不做第二套映射） | 解析出别的东西 ⇒ 红 |
 * | ③ | 未知（404）/ 已撤销（410）都**不抛**、状态码原样带回（页面据此给明确错误） | 抛异常 / 吞掉状态码 ⇒ 红 |
 * | ④ | 200 但没有 token ⇒ 当成读不到（不把空 token 交给报工解析） | 把空 token 当成功 ⇒ 红 |
 * | ⑤ | 空输入**不发请求**（手滑 / 空参数不该打服务端） | 打成 `//json` ⇒ 红 |
 */
import Taro from '@tarojs/taro'
import {
  resolveWorkerShortLink,
  WORKER_SHORT_LINK_INVALID_HINT,
} from '../src/services/workerShortLinkService'

/** 纸上的 8 位短码（Crockford Base32 形态） */
const SHORT_CODE = '7K3M9QP2'
/** 32 位十六进制的**假** token（按位拼出，不写整串字面量 —— Secret Scan 会误判成凭据） */
const TOKEN = Array.from({ length: 32 }, (_, i) => 'abcdef0123456789'[i % 16]).join('')

const mockRequest = Taro.request as jest.Mock

describe('短链 JSON 解析面（GET /s/{短码}/json）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  it('① 请求形状：GET …/s/<短码>/json、声明 Accept: application/json、不带商家凭据', async () => {
    Taro.setStorageSync('auth_token', 'merchant-token-from-storage')
    mockRequest.mockResolvedValueOnce({
      statusCode: 200,
      data: { reportPath: '/b/report/', token: TOKEN },
    })

    await resolveWorkerShortLink(SHORT_CODE)

    expect(mockRequest).toHaveBeenCalledTimes(1)
    const args = mockRequest.mock.calls[0][0]
    expect(String(args.url)).toContain(`/s/${SHORT_CODE}/json`)
    expect(args.method).toBe('GET')
    expect(args.header.Accept).toBe('application/json')
    // 短码在纸上、对任何持码人等价 ⇒ 这一跳**不是**身份入口：不发商家 token
    expect(args.header.Authorization).toBeUndefined()
  })

  it('② 成功 ⇒ {reportPath, token} 原样带回（前端不自己拼报工路径）', async () => {
    mockRequest.mockResolvedValueOnce({
      statusCode: 200,
      data: { reportPath: '/b/report/', token: TOKEN },
    })

    await expect(resolveWorkerShortLink(SHORT_CODE)).resolves.toEqual({
      success: true,
      data: { reportPath: '/b/report/', token: TOKEN },
    })
  })

  it('③ 未知（404）/ 已撤销（410）都不抛，状态码原样带回', async () => {
    mockRequest.mockResolvedValueOnce({ statusCode: 404, data: { error: 'not_found' } })
    await expect(resolveWorkerShortLink(SHORT_CODE)).resolves.toEqual({
      success: false,
      statusCode: 404,
      message: 'not_found',
    })

    mockRequest.mockResolvedValueOnce({ statusCode: 410, data: { error: 'revoked' } })
    await expect(resolveWorkerShortLink(SHORT_CODE)).resolves.toEqual({
      success: false,
      statusCode: 410,
      message: 'revoked',
    })
  })

  it('④ 200 但没有 token ⇒ 当成读不到（不把空 token 交给报工解析）', async () => {
    mockRequest.mockResolvedValueOnce({ statusCode: 200, data: { reportPath: '/b/report/' } })

    const res = await resolveWorkerShortLink(SHORT_CODE)
    expect(res.success).toBe(false)
    // 没有状态码 ⇒ 调用方按「读不到」处理（退回既有行为），而不是当成「码坏了」
    expect(res.statusCode).toBeUndefined()
  })

  it('⑤ 空输入不发请求', async () => {
    const res = await resolveWorkerShortLink('   ')
    expect(res.success).toBe(false)
    expect(mockRequest).not.toHaveBeenCalled()
  })

  it('⑥ 未知/已撤销的文案说得清「下一步怎么做」（不责备、不甩内部标识）', () => {
    expect(WORKER_SHORT_LINK_INVALID_HINT).toContain('已失效')
    expect(WORKER_SHORT_LINK_INVALID_HINT).toContain('手动输入')
  })
})
