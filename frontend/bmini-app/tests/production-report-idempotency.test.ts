// case_ids: BM-006
/**
 * 报工网络层契约测试：幂等键（issue #4116 §5-1）+ 失败分类（issue #4206 弱网降级的前提）。
 *
 * ## 病根（服务端去重挡不住的那一半）
 * 服务端按 `X-Client-Request-Id` 去重（同键重放、不重复累加 `done_qty`），但**前提是请求带了键**。
 * 小程序侧此前完全不发该头 ⇒ 服务端 `claim(null)` 走 no-op 首执分支 ⇒ 网络层重试/连点
 * 各自成为一次「首次报工」。本文件锁的就是这个接线（缺头 ⇒ 服务端幂等整条失效）。
 *
 * ## 红证
 * 把 `reportOperation` 的 `headers` 去掉 ⇒ 断言 ① 必红（Taro.request 收到的 header 里没有幂等键）。
 * 把 `newReportRequestId()` 写成常量 ⇒ 断言 ② 必红（两次调用同键 = 第二次报工被服务端当重复丢弃）。
 * 把失败分类写成恒 `offline: true`（或删掉该字段）⇒ 「有 HTTP 状态码 ⇒ false」必红 ——
 * 那正是「一次数量超上限的拒绝被当成离线失败、联网后被反复重发」的形态（issue #4206）。
 */
import Taro from '@tarojs/taro'
import {
  CLIENT_REQUEST_ID_HEADER,
  ReportInFlightLock,
  newReportRequestId,
  reportOperation,
} from '../src/services/productionService'

const ORDER_ID = 'CSO260915-02615'
const PAYLOAD = {
  worker_id: 'u1',
  worker_name: '张师傅',
  qty: 11,
  qualified_qty: 11,
  work_type: 'normal' as const,
}

function lastRequestHeader(): Record<string, string> {
  const calls = (Taro.request as jest.Mock).mock.calls
  expect(calls.length).toBeGreaterThan(0)
  return calls[calls.length - 1][0].header
}

describe('reportOperation 幂等键（issue #4116 §5-1）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 200,
      data: {
        success: true,
        data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
      },
    })
  })

  it('报工请求带 X-Client-Request-Id（缺头 ⇒ 服务端幂等整条失效）', async () => {
    await reportOperation(ORDER_ID, 'op2', PAYLOAD)

    const header = lastRequestHeader()
    expect(header[CLIENT_REQUEST_ID_HEADER]).toBeTruthy()
    expect(header[CLIENT_REQUEST_ID_HEADER]).toMatch(/^report-/)
  })

  it('每次调用生成**不同**的幂等键（两次合法报工不得被服务端当重复丢弃）', async () => {
    await reportOperation(ORDER_ID, 'op2', PAYLOAD)
    const first = lastRequestHeader()[CLIENT_REQUEST_ID_HEADER]

    await reportOperation(ORDER_ID, 'op2', PAYLOAD)
    const second = lastRequestHeader()[CLIENT_REQUEST_ID_HEADER]

    expect(first).toBeTruthy()
    expect(second).toBeTruthy()
    expect(second).not.toBe(first)
  })

  it('幂等键不超过服务端上限（client_request_keys.client_request_id VARCHAR(128)）', async () => {
    const key = newReportRequestId()
    expect(key.length).toBeLessThanOrEqual(128)
    expect(key).not.toContain(' ')
  })
})

/**
 * 失败分类（issue #4206）：离线报工队列**只**收「传输层失败」。
 *
 * 为什么这条必须在网络层（真 `reportOperation` + mock `Taro.request`）测：页面的用例会
 * mock 掉整个服务层，`offline` 标记就成了测试自己喂进去的常量 ⇒ 把实现写成
 * `offline: true`（或删掉该标记）页面用例**照样绿**（本会话实测：本条是唯一能红的判据）。
 *
 * 为什么区分这么重要：有 HTTP 状态码 = 服务端**已经答复**（422 数量超上限 / 404 非本部位 /
 * 409 同键在飞），且失败路径上服务端已 `discard` 释放幂等键 ⇒ 换个时机重发会**真的再执行一次**。
 */
describe('reportOperation 失败分类（issue #4206 弱网降级）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('无 HTTP 状态码（断网/超时后仍失败）⇒ offline=true（页面据此入离线队列）', async () => {
    // 这里用**不可重试**的传输层错误：可重试形态（errMsg 含 fail/timeout/网络）会先走满
    // 3 次指数退避（1+2+4s）才抛出，而判据是同一条 —— 有没有 HTTP 状态码，故不值得让
    // 全套用例为它多等 7 秒。
    ;(Taro.request as jest.Mock).mockRejectedValue({ errMsg: 'boom' })

    const res = await reportOperation(ORDER_ID, 'op2', PAYLOAD)

    expect(res.success).toBe(false)
    expect(res.offline).toBe(true)
  })

  it('有 HTTP 状态码（422 数量超上限）⇒ offline=false 且后端 message 透出（不得入离线队列）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 422,
      data: { success: false, message: '报工数量超上限：本次最多可报 11' },
    })

    const res = await reportOperation(ORDER_ID, 'op2', PAYLOAD)

    expect(res.success).toBe(false)
    expect(res.offline).toBe(false)
    expect(res.message).toBe('报工数量超上限：本次最多可报 11')
  })
})

/**
 * in-flight 锁本体（issue #4116 §5-1）。
 *
 * 为什么**必须**直接测锁对象而不能只测页面：页面里的 `<Button disabled>` 会在第一次点击后
 * 立即生效（fireEvent 内部 act() 刷 DOM），jsdom/浏览器都会**跳过 disabled 元素上的点击**
 * ⇒ 第二次点击根本到不了 `handleReport` ⇒ 把页面里的锁整个拔掉，连点断言**照样绿**
 * （本会话实测两次，是典型的「断言被另一道防护代偿」的假绿）。
 * 抽成独立对象后，「第二笔被拒 / 结束后恢复」就能被直接、判别性地证明。
 */
describe('ReportInFlightLock（报工在飞锁本体）', () => {
  it('在飞期间第二笔被拒（连点 = 两个不同幂等键，服务端去重挡不住）', () => {
    const lock = new ReportInFlightLock()
    expect(lock.tryAcquire()).toBe(true)
    expect(lock.isInFlight()).toBe(true)
    expect(lock.tryAcquire()).toBe(false)
    expect(lock.tryAcquire()).toBe(false)
  })

  it('release 之后可再次 acquire（一次性网络异常不得把工人永久锁死）', () => {
    const lock = new ReportInFlightLock()
    lock.tryAcquire()
    lock.release()
    expect(lock.isInFlight()).toBe(false)
    expect(lock.tryAcquire()).toBe(true)
  })

  it('新实例互不影响（锁是页面级状态，不是模块级全局单例的隐式串扰）', () => {
    const first = new ReportInFlightLock()
    const second = new ReportInFlightLock()
    first.tryAcquire()
    expect(second.tryAcquire()).toBe(true)
  })
})