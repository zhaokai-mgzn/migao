// case_ids: BM-057
/**
 * **扫码报工页：未登录 ⇒ 就地登录（不再跳三角色登录页）**（issue #8194）
 *
 * ## 治的形态
 *
 * 新手机第一次扫纸上的码（`/s/<短码>` → 302 → `/b/?t=<token>` → 报工页）时，本机没有工人
 * session。改前报工页把这个人**踢到三角色登录页的工人 tab**（`/pages/auth/login/index?tab=worker`）：
 * 那张表单的标题 / 副标题 / 字段（还多一格「设备标签」）/ 配色与本端 `/w/` 全不一样，
 * 而且**手里的码要绕一圈才能接着报**。同一件事在扫码落地点被打断 ⇒ 工人只会觉得「扫码没反应」。
 *
 * 改后：未登录**就地**渲染与 `/w/` 逐字一致的 `WorkerLoginForm`（文案/字段判据 =
 * `tests/worker-login-parity.test.ts`），登录成功**留在本页**继续手里的码（带码）或回工人首页（无码）。
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 未登录 ⇒ 三个输入 + 「登 录」上屏；**没有**「去登录工人身份」跳转按钮，也**不**导航去三角色登录页 | 还原成跳转 ⇒ 红 |
 * | 2 | 带码（`/b/?t=<token>`）登录成功 ⇒ **留在本页**并解析该码（`scanResolve(token)`），不跳走 | 登录后回首页 ⇒ 红 |
 * | 3 | 无码登录成功 ⇒ 回工人首页（`WORKER_HOME_ROUTE`），不解析任何码 | 停在空页 ⇒ 红 |
 * | 4 | 登录失败 ⇒ 错误上屏、仍是未登录态、不解析码 | 吞掉错误 ⇒ 红 |
 * | 5 | 「登录后接着报这个码」走 `utils/reportEntry.ts` 的同一条一次性记录（登录前 write、成功后 take 并清） | 另造一套待报码通道 ⇒ 红 |
 * | 6 | 提交**不带设备标签**（`workerLogin(no, pin, undefined, enterpriseCode)`）：`/w/` 没有那一格 | 传 deviceLabel ⇒ 红 |
 *
 * ⚠️ 本文件只判**装配与去向**；文案/字段的跨端逐字一致在 `tests/worker-login-parity.test.ts`。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// 入口参数走 h5 分支（`window.location.search`）——与线上 `/b/?t=` 同一条解析器
process.env.TARO_ENV = 'h5'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      showLoading: jest.fn(),
      hideLoading: jest.fn(),
      navigateTo: jest.fn(),
      redirectTo: jest.fn(() => Promise.resolve()),
      getCurrentInstance: jest.fn(() => ({ router: { path: '', params: {} } })),
      getEnterOptionsSync: jest.fn(() => ({ query: {}, scene: 0 })),
      scanCode: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
      __store: store,
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
  workerLogin: jest.fn(),
}))

jest.mock('../src/services/productionService', () => ({
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerReportPage from '../src/pages/worker/report/index'
import { fetchCurrentWorker, workerLogin } from '../src/services/workerService'
import { scanResolve } from '../src/services/productionService'
import { PENDING_REPORT_RETURN_KEY } from '../src/utils/reportEntry'
import { WORKER_HOME_ROUTE, WORKER_TAB_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import { clearWorkerSession } from '../src/utils/workerSession'
import { WORKER_LOGIN_SUBMIT_TEXT } from '../src/components/WorkerLoginForm'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

// 32 位十六进制的**假** token（服务端 token 形态）；按位拼出，不写整串字面量（Secret Scan 会误判）
const TOKEN = Array.from({ length: 32 }, (_, i) => 'abcdef0123456789'[i % 16]).join('')

const mockFetchWorker = fetchCurrentWorker as jest.Mock
const mockWorkerLogin = workerLogin as jest.Mock
const mockResolve = scanResolve as jest.Mock

function enterWithCode(code: string): void {
  window.history.replaceState({}, '', `/b/?t=${encodeURIComponent(code)}`)
}

function enterWithoutCode(): void {
  window.history.replaceState({}, '', '/b/')
}

/** 填三格并提交（值取与 `/w/` 一致的字段） */
async function submitLogin(values = { enterprise: 'migao', no: 'G001', pin: '1234' }): Promise<void> {
  fireEvent.change(screen.getByTestId('worker-login-enterprise-code'), {
    target: { value: values.enterprise },
  })
  fireEvent.change(screen.getByTestId('worker-login-worker-no'), { target: { value: values.no } })
  fireEvent.change(screen.getByTestId('worker-login-pin'), { target: { value: values.pin } })
  fireEvent.click(screen.getByTestId('worker-login-submit'))
}

async function bootUnauthorized(): Promise<void> {
  clearWorkerSession()
  mockFetchWorker.mockResolvedValue({ success: false, message: '尚未登录工人身份' })
  render(<WorkerReportPage />)
  await screen.findByTestId('worker-login-form')
}

describe('扫码报工页 · 未登录就地登录（issue #8194）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    enterWithoutCode()
    mockFetchWorker.mockResolvedValue({ success: false, message: '尚未登录工人身份' })
    mockResolve.mockResolvedValue({ success: true, data: null })
  })

  it('① 未登录 ⇒ 三个输入 + 「登 录」上屏；没有「去登录工人身份」，也不跳三角色登录页', async () => {
    await bootUnauthorized()

    const form = screen.getByTestId('worker-login-form')
    expect(form).toBeTruthy()
    expect(screen.getByTestId('worker-login-enterprise-code')).toBeTruthy()
    expect(screen.getByTestId('worker-login-worker-no')).toBeTruthy()
    expect(screen.getByTestId('worker-login-pin')).toBeTruthy()
    expect(screen.getByTestId('worker-login-submit').textContent).toBe(WORKER_LOGIN_SUBMIT_TEXT)

    // 反向：不再有「去登录工人身份」这个跳转按钮，也不发起任何导航
    expect(screen.queryByText('去登录工人身份')).toBeNull()
    expect(Taro.navigateTo).not.toHaveBeenCalled()
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    expect(Taro.navigateTo).not.toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
    // 未登录 ⇒ 不出报工按钮
    expect(screen.queryByTestId('worker-report-submit')).toBeNull()

    // 🔴 未登录**不渲染页头**（用户 2026-10-31 裁定）：`/w/` 的登录屏只有一张卡片，
    // 若这里照样印「扫码报工」就变成两层标题（扫码报工 + 工人报工）⇒ 与 /w/ 不一致
    expect(screen.queryByTestId('worker-report-header')).toBeNull()
    expect(screen.queryByText('扫码报工')).toBeNull()
    expect(screen.queryByTestId('worker-report-worker')).toBeNull()
  })

  it('② 带码登录成功 ⇒ 留在本页并解析该码（不回首页、不跳走）', async () => {
    enterWithCode(TOKEN)
    await bootUnauthorized()

    mockWorkerLogin.mockResolvedValue({ success: true, data: WORKER })
    mockFetchWorker.mockResolvedValue({ success: true, data: WORKER })
    mockResolve.mockResolvedValue({ success: true, data: { granularity: 'set_position', operation: null } })

    await submitLogin()

    await waitFor(() => expect(mockWorkerLogin).toHaveBeenCalledTimes(1))
    // 判据 6：第三参 = 设备标签 ⇒ 必须是 undefined（`/w/` 没有这一格）
    expect(mockWorkerLogin).toHaveBeenCalledWith('G001', '1234', undefined, 'migao')
    // 判据 2：手里的码被继续解析，且**留在本页**
    await waitFor(() => expect(mockResolve).toHaveBeenCalledWith(TOKEN, undefined, null))
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    // 登录成功 ⇒ 页头（页面身份 + 当前工人）出现：谁在干活是计件凭证
    expect(await screen.findByTestId('worker-report-header')).toBeTruthy()
    expect(screen.getByText('扫码报工')).toBeTruthy()
    expect(screen.getByTestId('worker-report-worker').textContent).toContain('张三')
    // 判据 5：一次性记录被读走（读到即清）—— 不会把上一次的码带给下一次登录
    expect(Taro.getStorageSync(PENDING_REPORT_RETURN_KEY)).toBe('')
  })

  it('③ 无码登录成功 ⇒ 回工人首页（不解析任何码）', async () => {
    await bootUnauthorized()

    mockWorkerLogin.mockResolvedValue({ success: true, data: WORKER })
    mockFetchWorker.mockResolvedValue({ success: true, data: WORKER })

    await submitLogin()

    await waitFor(() => expect(Taro.redirectTo).toHaveBeenCalledWith({ url: WORKER_HOME_ROUTE }))
    expect(mockResolve).not.toHaveBeenCalled()
  })

  it('④ 登录失败 ⇒ 错误上屏、仍是未登录态、不解析码', async () => {
    enterWithCode(TOKEN)
    await bootUnauthorized()

    mockWorkerLogin.mockResolvedValue({ success: false, message: '工号或 PIN 不正确' })

    await submitLogin()

    expect(await screen.findByTestId('worker-login-error')).toBeTruthy()
    expect(screen.getByTestId('worker-login-error').textContent).toBe('工号或 PIN 不正确')
    expect(mockResolve).not.toHaveBeenCalled()
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    expect(screen.getByTestId('worker-login-form')).toBeTruthy()
  })

  it('⑤ 手里有码时先记进 reportEntry 的一次性记录（登录那一步不丢码）', async () => {
    enterWithCode(TOKEN)
    await bootUnauthorized()

    // 判据 5：未登录 + 有码 ⇒ 复用既有的「登录后接着报这个码」记录（不是第二套通道）
    await waitFor(() => {
      const raw = Taro.getStorageSync(PENDING_REPORT_RETURN_KEY)
      expect(raw).not.toBe('')
      expect(JSON.parse(String(raw)).code).toBe(TOKEN)
    })
  })
})
