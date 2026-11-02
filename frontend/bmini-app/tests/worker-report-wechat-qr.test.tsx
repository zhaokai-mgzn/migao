// case_ids: BM-058
/**
 * **微信「扫普通链接二维码打开小程序」（A 档）⇒ 报工页**（issue #8196）
 *
 * ## 治的形态
 *
 * 纸上的码是 `https://app.migaozn.com/s/<短码>`（永不变、已印出去的不可重印）。H5 靠服务端
 * **302** 进 `/b/?t=<token>`；而微信「扫普通链接二维码打开小程序」把整条链接放进
 * `getEnterOptionsSync().query.q`（URL-encoded），**小程序不跟随 302** —— 页面手里只有一个
 * 短码。若直接把它当 token 递给报工页，线上表现是「扫码后停在报工页、报工按钮一直不出来」，
 * 而**没有任何东西会变红**（码是好的、302 也是好的）。
 *
 * 改后：`q` 里的 `/s/<短码>` 由**短链 JSON 解析面**（`GET /s/<短码>/json`）换回报工 token，
 * 再走 #8194 已有的「就地登录 → 继续手里的码」流程；`q` 是 `/b/report/?t=<token>` 时直接取 `t`。
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | ① | `q=/s/<短码>` + 已登录 ⇒ 先 JSON 解析（只一次）拿 token，再用 **token**（不是短码）解析一屏 | 把短码直接递给 `scanResolve`（改前行为）/ 少了解析这一步 ⇒ 红 |
 * | ② | `q=/s/<短码>` + 未登录 ⇒ **登录前**就解析（无效码当场说清），登录成功**接着报这个码**（token） | 登录后才解析 / 登录后把码丢了 / 回首页 ⇒ 红 |
 * | ③ | `q=/b/report/?t=<token>` ⇒ **不**调 JSON 面，直接取 `t`（与 H5 落地同一份解析） | 多打一次网络 / 取到路径段 ⇒ 红 |
 * | ④ | 页面自身 `?t=` 与「直接进 `/b/report/`（无码）」行为不变 | 无码也发请求 / 无码也导航 ⇒ 红 |
 * | ⑤ | 未知 / 已撤销码 ⇒ **明确错误**上屏 + 不出报工入口，且**只解析一次**（不无限重试、不白屏） | 静默吞掉 / 循环重试 ⇒ 红 |
 * | ⑥ | JSON 面读不到（离线 / 旧后端没有这条路径）⇒ 退回既有行为（短码原样交给工人扫码端点） | 直接报错或白屏 ⇒ 红（已印出去的码不能因为新版前端而作废） |
 * | ⑦ | 解码边界：中文 / 百分号 / 重复参数 / 非法百分号编码 ⇒ 取出同一个短码且**不抛**（不让解析变成白屏） | 抛异常 / 取到错码 ⇒ 红 |
 *
 * ⚠️ 本文件判**装配与去向**；短链 JSON 面的**形状与不泄露**在 admin-api 的
 * `WorkerShortLinkControllerTest`（`/s/<短码>/json`）。
 * ⚠️ 平台分支仍只住在 `utils/reportEntry.ts`：页面里没有 `process.env.TARO_ENV` 判断。
 */
process.env.TARO_ENV = 'weapp'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  const enter: { query: Record<string, any>; params: Record<string, any> } = {
    query: {},
    params: {},
  }
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      showLoading: jest.fn(),
      hideLoading: jest.fn(),
      navigateTo: jest.fn(),
      redirectTo: jest.fn(() => Promise.resolve()),
      getCurrentInstance: jest.fn(() => ({ router: { path: '', params: enter.params } })),
      getEnterOptionsSync: jest.fn(() => ({ query: enter.query, scene: 0 })),
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
      /** 注入「进入参数」：`query` = 微信冷启动参数（A 档 `q`），`params` = 页面参数（redirectTo 带过去的 `t`） */
      __setEnter: (query: Record<string, any>, params: Record<string, any> = {}) => {
        enter.query = query
        enter.params = params
      },
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

// 短链 JSON 解析面（`GET /s/<短码>/json`）—— 本文件只判页面怎么用它；请求形状在
// `tests/worker-short-link-service.test.ts`。
jest.mock('../src/services/workerShortLinkService', () => {
  // 只换掉网络那一跳；文案等常量取真实模块（否则页面拿到的会是 undefined，判据变成空断言）
  const actual = jest.requireActual('../src/services/workerShortLinkService')
  return { ...actual, resolveWorkerShortLink: jest.fn() }
})

import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'
import WorkerReportPage from '../src/pages/worker/report/index'
import { fetchCurrentWorker, workerLogin } from '../src/services/workerService'
import { scanResolve } from '../src/services/productionService'
import { resolveWorkerShortLink } from '../src/services/workerShortLinkService'
import { PENDING_REPORT_RETURN_KEY } from '../src/utils/reportEntry'
import { resolveScanLanding, readQueryParam } from '../src/utils/scanInput'
import { WORKER_HOME_ROUTE } from '../src/utils/inbound/gaps'
import { clearWorkerSession, setWorkerSessionId } from '../src/utils/workerSession'
import { WORKER_LOGIN_SUBMIT_TEXT } from '../src/components/WorkerLoginForm'
import type { ReportView } from '../src/utils/reportState'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

/** 纸上的 8 位短码（Crockford Base32 形态；与后端 `WorkerShortLinkService.CODE_LENGTH` 同款） */
const SHORT_CODE = '7K3M9QP2'
/** 32 位十六进制的**假** token（按位拼出，不写整串字面量 —— Secret Scan 会误判成凭据） */
const TOKEN = Array.from({ length: 32 }, (_, i) => 'abcdef0123456789'[i % 16]).join('')

const MAIN_VIEW: ReportView = {
  granularity: 'set_position',
  set_no: 1,
  position: { order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' },
  operation: { operation_id: 'op-1', logical_name: '车被', qty: 11, unit: '米' },
  alternatives: [],
  needs_selection: [],
  set_progress: { done: 0, total: 1 },
}

const mockFetchWorker = fetchCurrentWorker as jest.Mock
const mockWorkerLogin = workerLogin as jest.Mock
const mockResolve = scanResolve as jest.Mock
const mockShortLink = resolveWorkerShortLink as jest.Mock

function setEnterQuery(query: Record<string, any>, params: Record<string, any> = {}): void {
  ;(Taro as any).__setEnter(query, params)
}

/** A 档：微信把整条 `q` 链接 URL-encoded 放进 query */
function enterWithShortLink(code = SHORT_CODE, extraQuery = ''): void {
  setEnterQuery({ q: encodeURIComponent(`https://app.migaozn.com/s/${code}${extraQuery}`) }, { t: code })
}

async function bootLoggedIn(): Promise<void> {
  setWorkerSessionId(WORKER.session_id)
  mockFetchWorker.mockResolvedValue({ success: true, data: WORKER })
  render(<WorkerReportPage />)
  await waitFor(() => expect(mockFetchWorker).toHaveBeenCalled())
}

async function bootUnauthorized(): Promise<void> {
  clearWorkerSession()
  mockFetchWorker.mockResolvedValue({ success: false, message: '尚未登录工人身份' })
  render(<WorkerReportPage />)
  await screen.findByTestId('worker-login-form')
}

async function submitLogin(values = { enterprise: 'migao', no: 'G001', pin: '1234' }): Promise<void> {
  fireEvent.change(screen.getByTestId('worker-login-enterprise-code'), {
    target: { value: values.enterprise },
  })
  fireEvent.change(screen.getByTestId('worker-login-worker-no'), { target: { value: values.no } })
  fireEvent.change(screen.getByTestId('worker-login-pin'), { target: { value: values.pin } })
  fireEvent.click(screen.getByTestId('worker-login-submit'))
}

describe('微信 A 档（扫普通链接二维码打开小程序）⇒ 报工页（issue #8196）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    setEnterQuery({})
    mockResolve.mockResolvedValue({ success: true, data: MAIN_VIEW })
    mockShortLink.mockResolvedValue({
      success: true,
      data: { reportPath: '/b/report/', token: TOKEN },
    })
    mockFetchWorker.mockResolvedValue({ success: false, message: '尚未登录工人身份' })
  })

  it('① q=…/s/<短码> + 已登录 ⇒ 先 JSON 解析拿 token，再用 token 解析一屏（不是短码）', async () => {
    enterWithShortLink()
    await bootLoggedIn()

    await waitFor(() => expect(mockShortLink).toHaveBeenCalledTimes(1))
    expect(mockShortLink).toHaveBeenCalledWith(SHORT_CODE)
    await waitFor(() => expect(mockResolve).toHaveBeenCalledWith(TOKEN, undefined, null))
    // 短码**不得**原样进报工解析（那正是改前的静默失败形态）
    expect(mockResolve).not.toHaveBeenCalledWith(SHORT_CODE, undefined, null)

    expect(await screen.findByTestId('worker-report-card')).toBeTruthy()
    expect(screen.getByTestId('worker-report-operation').textContent).toContain('车被')
    // 落地后不跳走（报工页就是落地面）
    expect(Taro.redirectTo).not.toHaveBeenCalled()
  })

  it('② q=…/s/<短码> + 未登录 ⇒ 登录**前**解析（无效码当场说清），登录后接着报这个码', async () => {
    enterWithShortLink()
    await bootUnauthorized()

    // 登录前就已解析：无效码不必等工人输完 PIN 才说
    await waitFor(() => expect(mockShortLink).toHaveBeenCalledTimes(1))
    // 登录前**不**解析一屏（工人端点要工人 session）
    expect(mockResolve).not.toHaveBeenCalled()
    // 跨登录带上的是 **token**（短码已经换掉了）
    await waitFor(() => {
      const raw = Taro.getStorageSync(PENDING_REPORT_RETURN_KEY)
      expect(raw).not.toBe('')
      expect(JSON.parse(String(raw)).code).toBe(TOKEN)
    })

    mockWorkerLogin.mockResolvedValue({ success: true, data: WORKER })
    mockFetchWorker.mockResolvedValue({ success: true, data: WORKER })
    await submitLogin()

    await waitFor(() => expect(mockWorkerLogin).toHaveBeenCalledTimes(1))
    // 登录成功 ⇒ 留在本页继续手里的码（token），不回首页
    await waitFor(() => expect(mockResolve).toHaveBeenCalledWith(TOKEN, undefined, null))
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    expect(await screen.findByTestId('worker-report-card')).toBeTruthy()
  })

  it('③ q=…/b/report/?t=<token> ⇒ 不调 JSON 面，直接取 t（与 H5 落地同一份解析）', async () => {
    setEnterQuery({ q: encodeURIComponent(`https://app.migaozn.com/b/report/?t=${TOKEN}`) })
    await bootLoggedIn()

    await waitFor(() => expect(mockResolve).toHaveBeenCalledWith(TOKEN, undefined, null))
    expect(mockShortLink).not.toHaveBeenCalled()
    expect(await screen.findByTestId('worker-report-card')).toBeTruthy()
  })

  it('④ 页面自身 ?t=（redirectTo 带过来）行为不变；直接进（无码）⇒ 什么都不发、不导航', async () => {
    // ④a：页面参数 `t` = token（H5 启动器 / redirectTo 的既有形态）
    setEnterQuery({}, { t: TOKEN })
    await bootLoggedIn()

    await waitFor(() => expect(mockResolve).toHaveBeenCalledWith(TOKEN, undefined, null))
    expect(mockShortLink).not.toHaveBeenCalled()
  })

  it('④b 无码直接进报工页 ⇒ 不解析、不导航、停在扫码/手输态', async () => {
    await bootLoggedIn()

    expect(mockShortLink).not.toHaveBeenCalled()
    expect(mockResolve).not.toHaveBeenCalled()
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    expect(await screen.findByTestId('worker-report-scan')).toBeTruthy()
  })

  it('⑤a 未知码（JSON 面 404）⇒ 明确错误上屏、不出报工入口、只解析一次（不无限重试）', async () => {
    mockShortLink.mockResolvedValue({ success: false, statusCode: 404, message: 'not_found' })
    enterWithShortLink('ZZZZZZZZ')
    await bootLoggedIn()

    const error = await screen.findByTestId('worker-report-entry-error')
    expect(error.textContent).toContain('已失效')
    expect(mockShortLink).toHaveBeenCalledTimes(1)
    expect(mockResolve).not.toHaveBeenCalled()
    // 不是白屏：页面仍在，手输码这条降级路径还在
    expect(screen.getByTestId('worker-report-scan')).toBeTruthy()
  })

  it('⑤b 已撤销（JSON 面 410）+ 未登录 ⇒ 错误上屏**并且**回到工人登录（不白屏、不重试）', async () => {
    mockShortLink.mockResolvedValue({ success: false, statusCode: 410, message: 'revoked' })
    enterWithShortLink()
    await bootUnauthorized()

    expect((await screen.findByTestId('worker-report-entry-error')).textContent).toContain('已失效')
    expect(screen.getByTestId('worker-login-form')).toBeTruthy()
    expect(screen.getByTestId('worker-login-submit').textContent).toBe(WORKER_LOGIN_SUBMIT_TEXT)
    expect(mockShortLink).toHaveBeenCalledTimes(1)
    // 死码**不**跨登录带走（否则登录成功后还会白解析一次）
    expect(Taro.getStorageSync(PENDING_REPORT_RETURN_KEY)).toBe('')
  })

  it('⑥ JSON 面读不到（离线 / 旧后端没有这条路径）⇒ 退回既有行为：短码原样交给工人扫码端点', async () => {
    mockShortLink.mockResolvedValue({ success: false })
    enterWithShortLink()
    await bootLoggedIn()

    await waitFor(() => expect(mockResolve).toHaveBeenCalledWith(SHORT_CODE, undefined, null))
    expect(screen.queryByTestId('worker-report-entry-error')).toBeNull()
  })
})

describe('A 档入口的解码边界（q = URL-encoded 完整链接）', () => {
  it('中文 / 百分号 / 重复参数都取出同一个短码，且标记为「短链」（需要 JSON 解析）', () => {
    expect(resolveScanLanding({ q: encodeURIComponent(`https://app.migaozn.com/s/${SHORT_CODE}`) })).toEqual({
      kind: 'report',
      code: SHORT_CODE,
      from: 'link-qr-short',
    })
    // 链接里带中文 / 百分号的既有查询参数：路径段才是码，参数不影响
    const decorated = `https://app.migaozn.com/s/${SHORT_CODE}?from=%E5%BE%AE%E4%BF%A1&r=%25`
    expect(resolveScanLanding({ q: encodeURIComponent(decorated) })).toEqual({
      kind: 'report',
      code: SHORT_CODE,
      from: 'link-qr-short',
    })
    // `+` 在 query 里是空格（工人从聊天记录里粘 URL 的形态）：不影响路径段
    expect(resolveScanLanding({ q: `https%3A%2F%2Fapp.migaozn.com%2Fs%2F${SHORT_CODE}+` }).code).toBe(SHORT_CODE)
  })

  it('非法百分号编码 / 垃圾输入不抛（读参数不许变成白屏）', () => {
    expect(() => resolveScanLanding({ q: '%%%' })).not.toThrow()
    expect(resolveScanLanding({ q: '%%%' })).toEqual({ kind: 'report', code: '%%%', from: 'link-qr' })
    expect(() => resolveScanLanding({ q: 'https%3A%2F%2Fapp.migaozn.com%2Fs%2F7K3M9QP2%25ZZ' })).not.toThrow()
    // 非法编码退回原样 ⇒ 仍能认出里面的路径段（不吞输入、也不白屏）
    expect(resolveScanLanding({ q: 'https%3A%2F%2Fapp.migaozn.com%2Fs%2F7K3M9QP2%25ZZ' }).code).toBe(SHORT_CODE)
  })

  it('重复参数取第一个（q 里重复的 t、以及 query 里重复的 q）', () => {
    // URL 里的 `t`：第一个为准（`paramInText` 的正则只取首个命中）
    expect(resolveScanLanding({ q: encodeURIComponent('https://app.migaozn.com/b/report/?t=AAA&t=BBB') }).code).toBe(
      'AAA',
    )
    // search 形态同样「首个命中即停」
    expect(readQueryParam('?t=first&t=second', 't').raw).toBe('first')
    // `/s/` + 显式 `t` 参数同时出现 ⇒ 以 `t` 为准（那是 302 落点的形态），不再申请 JSON 解析
    expect(resolveScanLanding({ q: encodeURIComponent(`https://app.migaozn.com/s/${SHORT_CODE}?t=${TOKEN}`) })).toEqual({
      kind: 'report',
      code: TOKEN,
      from: 'link-qr',
    })
  })
})

// 保留 `WORKER_HOME_ROUTE` 的引用（无码登录回首页的既有判据在 worker-report-login.test.tsx；
// 本文件不重复造那条，只保证 A 档场景下**不会**走它）
void WORKER_HOME_ROUTE
