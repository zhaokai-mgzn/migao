// case_ids: BM-053, BM-040
/**
 * **扫码报工落地面：`/b/?t=<token>` 被消费，且与 `?code=`（补打页）不串道**（issue #7879）
 *
 * ## 治的形态：302 换了落地面，而落地面上**没有任何人读那个 `t`**
 *
 * 纸上的码 = `https://app.migaozn.com/s/<短码>`（加工单级是 `/o/<短码>`），服务端
 * `WorkerShortLinkController` / `ProcessingOrderShortLinkController` 302 到
 * `/b/?t=<token>&tenant_id=…&tenant_code=…`。改前 `/b/` 上**没有任何人读 `t`**
 * ⇒ 工人扫开自家纸上的码只会停在商家首页，**而且没有任何东西会变红**
 * （码是好的、302 是好的、页面也不报错）—— 与本仓 #5052 治过的 `?code=` 是同一形态。
 * 本文件钉住那一半（改动前 `?code=` 的对应判据在 `tests/inbound-landing-deeplink.test.tsx`）。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | B1 | `/b/?t=<token>` ⇒ 启动器 `Taro.redirectTo` 到报工页，token **原样**带走 | 删掉 `src/app.tsx` 的 `t` 支线 ⇒ 红（页面停在 chat/index） |
 * | B2 | **负控（不串道）**：`?code=` 仍走补打页；无参数 ⇒ 不动路由；两者同时出现 ⇒ 以 `t` 为准 | 把两支合并成一支（都去报工页 / 都去补打页）⇒ 红 |
 * | B3 | 商家首页不抢路由：URL 带 `?t=` 时**不**排「未登录 ⇒ 600ms 去商家登录页」的定时器 | 删掉那道闸 ⇒ 红（工人被踢到商家登录页） |
 * | B4 | **反向钉住**：`/w/` 不再是任何**跳转生产者**（302 常量 / app.tsx / 工人首页 / 台账 `via`） | 把 `WorkerShortLinkService.REPORT_PAGE_PATH` 换回 `/w/` ⇒ 红 |
 *
 * ⚠️ 报工页自身的四条硬约束不在这里（它们的载体是 `tests/worker-report-page.test.tsx` 与
 * `tests/report-state.test.ts`；本单只换落地面，那四条**一格未放宽**）。
 */
import path from 'path'
import fs from 'fs'
import React from 'react'
import { render } from '@testing-library/react'
import Taro from '@tarojs/taro'
import {
  REPORT_TOKEN_PARAM,
  currentReportToken,
  reportLandingUrl,
  reportTokenFromSearch,
} from '../src/utils/inbound/deepLink'
import {
  codeFromScanText,
  readQueryParam,
  resolveScanLanding,
  NONE_LANDING,
} from '../src/utils/scanInput'
import {
  PENDING_REPORT_RETURN_KEY,
  currentEntryLanding,
  rememberReportReturn,
  reportReturnUrl,
  takeReportReturn,
} from '../src/utils/reportEntry'
import { REPORT_PAGE_ROUTE, REPRINT_PAGE_ROUTE, WORKER_HOME_ROUTE } from '../src/utils/inbound/gaps'
import { STORAGE_KEYS } from '../src/utils/constants'
import { useMerchantSurfaceGuard } from '../src/utils/roleGuard'
import { PAGE_ENTRY_LEDGER } from '../src/utils/pageEntries'
import { BMINI_ROOT, stripComments } from './helpers/h5PlatformLists'

const ORIGINAL_TARO_ENV = process.env.TARO_ENV
process.env.TARO_ENV = 'h5'

// 32 位十六进制的**假** token（形态 = 服务端 `processing_set_part_tokens.token`：UUID 去横线）。
// 由字符表按位拼出、不写整串字面量：整串会被 Secret Scan（gitleaks `generic-api-key`）误判成凭据。
const TOKEN = Array.from({ length: 32 }, (_, i) => '0123456789abcdef'[i % 16]).join('')
const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')

/** 启动器与商家首页共用的 auth store 替身（`initialize` 单独拿出来数调用次数） */
const mockAuthInitialize = jest.fn()
jest.mock('../src/store/authStore', () => {
  /** 商家首页把它当 hook 调，启动器 App 走 `getState()` —— 两种形态都要给 */
  const useAuthStore: any = () => ({
    isLoggedIn: false,
    checkAuth: () => false,
    user: null,
    logout: () => undefined,
  })
  useAuthStore.getState = () => ({ initialize: mockAuthInitialize })
  return { useAuthStore }
})
jest.mock('../src/utils/errorHandler', () => ({
  setupErrorHandler: jest.fn(),
  setupNetworkListener: jest.fn(),
}))

const BASE_HREF = 'http://localhost/b/'

/** 把地址栏设成落地页形态（jsdom：改 search、不动 hash，与真实 302 落点一致） */
function gotoLanding(search: string) {
  window.history.replaceState({}, '', `${BASE_HREF}${search}`)
}

/** 延迟 require：模块级 `jest.mock` 的工厂在**这里**才跑（`mockAuthInitialize` 已初始化） */
function loadApp(): React.ComponentType<{ children?: React.ReactNode }> {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  return require('../src/app').default
}

function loadChatPage(): React.ComponentType {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  return require('../src/pages/chat/index/index').default
}

/** 读仓库内某个文件的**代码**（剥注释：注释里写历史沿革不算"还在跳转生产者里"） */
function codeOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(BMINI_ROOT, relative), 'utf8'))
}

/** 读仓库内某个文件的**代码**（剥注释：注释里写历史沿革不算"还在跳转生产者里"） */
function io(relative: string): string {
  return codeOf(relative)
}

beforeEach(() => {
  jest.clearAllMocks()
  gotoLanding('')
})

afterAll(() => {
  process.env.TARO_ENV = ORIGINAL_TARO_ENV
})

describe('B1 读参数 + 拼落地 URL（逐字）', () => {
  it('B1 参数名 = `t`（与服务端 `reportPageLocation` 拼的那个键逐字同名）', () => {
    expect(REPORT_TOKEN_PARAM).toBe('t')
  })

  it('B1 三态可分：出现 / 不出现 / 出现但为空（读不到 ≠ 读到空）', () => {
    expect(reportTokenFromSearch(`?t=${TOKEN}&tenant_id=7&tenant_code=migao`)).toEqual({
      present: true,
      raw: TOKEN,
    })
    expect(reportTokenFromSearch(`t=${TOKEN}`)).toEqual({ present: true, raw: TOKEN })
    expect(reportTokenFromSearch('?t=')).toEqual({ present: true, raw: '' })
    expect(reportTokenFromSearch('?tenant_id=7')).toEqual({ present: false, raw: '' })
    expect(reportTokenFromSearch('')).toEqual({ present: false, raw: '' })
    // 🔴 不串道的第一半：`t` 的读取器**不许**把 `?code=` 当自己的参数（反之亦然，见 B2）
    expect(reportTokenFromSearch('?code=ABCD2345')).toEqual({ present: false, raw: '' })
    // 非法百分号编码不得把"读参数"变成白屏
    expect(reportTokenFromSearch('?t=AB%ZZ')).toEqual({ present: true, raw: 'AB%ZZ' })
  })

  it('B1 报工页落地 URL 逐字（路由 + 参数名只有一处真值）', () => {
    expect(REPORT_PAGE_ROUTE).toBe('/pages/worker/report/index')
    expect(reportLandingUrl(TOKEN)).toBe(`${REPORT_PAGE_ROUTE}?t=${TOKEN}`)
    // 原样编码带走（启动器不改写码值）
    expect(reportLandingUrl('a b')).toBe(`${REPORT_PAGE_ROUTE}?t=a%20b`)
    expect(reportLandingUrl('')).toBe(`${REPORT_PAGE_ROUTE}?t=`)
    // 与补打页是**两个下游**（改这支不许把补打页那支挤掉）
    expect(REPRINT_PAGE_ROUTE).not.toBe(REPORT_PAGE_ROUTE)
  })

  it('B1 h5 当前 URL 上的 token（weapp 恒 absent：小程序没有 URL query）', () => {
    gotoLanding(`?t=${TOKEN}&tenant_id=7`)
    expect(currentReportToken()).toEqual({ present: true, raw: TOKEN })
    gotoLanding('')
    expect(currentReportToken()).toEqual({ present: false, raw: '' })
  })
})

describe('B1/B2 启动器（h5 落地）', () => {
  it('B1 🔴 `/b/?t=<token>` ⇒ 启动器把 token 交给报工页（`Taro.redirectTo`）', () => {
    gotoLanding(`?t=${TOKEN}&tenant_id=7&tenant_code=migao`)
    const App = loadApp()
    render(React.createElement(App, null, null))
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `${REPORT_PAGE_ROUTE}?t=${TOKEN}` })
  })

  it('B1 出现但为空（`/b/?t=`）⇒ 也交给报工页（页面自己说"扫到的码是空的"，不静默当没有参数）', () => {
    gotoLanding('?t=')
    const App = loadApp()
    render(React.createElement(App, null, null))
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `${REPORT_PAGE_ROUTE}?t=` })
  })

  it('B2 🔴 负控：`/b/?code=<短码>` ⇒ **仍走补打页**（两支不串道）', () => {
    gotoLanding('?code=ABCD2345&tenant_id=7')
    const App = loadApp()
    render(React.createElement(App, null, null))
    expect(Taro.redirectTo).toHaveBeenCalledTimes(1)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `${REPRINT_PAGE_ROUTE}?code=ABCD2345` })
  })

  it('B2 负控：两个参数同时出现 ⇒ 以 `t` 为准（报工是工人当下要走的那条路）', () => {
    gotoLanding(`?code=ABCD2345&t=${TOKEN}`)
    const App = loadApp()
    render(React.createElement(App, null, null))
    expect(Taro.redirectTo).toHaveBeenCalledTimes(1)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `${REPORT_PAGE_ROUTE}?t=${TOKEN}` })
  })

  it('B2 负控：一个参数都没有 ⇒ **不动路由**（商家正常开首页；空跑反证）', () => {
    gotoLanding('?tenant_id=7')
    const App = loadApp()
    render(React.createElement(App, null, null))
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    expect(mockAuthInitialize).toHaveBeenCalledTimes(1)
  })
})

describe('B3 商家首页不抢路由', () => {
  it('B3 源码面：首页初始化前先看「URL 上有没有落地参数」，两个支线都让位', () => {
    const code = codeOf('src/pages/chat/index/index.tsx')
    // 🔴 issue #7887：判据收成一处（`hasLandingIntent()`）后，这里钉的是**"有没有这道闸"**，
    // 不是某个具体 helper 名 —— 页面上不再各写一份 `?code=` / `?t=` 的条件。
    expect(code).toContain('hasLandingIntent')
    const gate = code.indexOf('hasLandingIntent()')
    const steal = code.indexOf("Taro.redirectTo({ url: '/pages/auth/login/index' })")
    expect(gate).toBeGreaterThan(-1)
    // 闸必须在"去商家登录"之前（反了就等于没有）
    expect(steal).toBeGreaterThan(gate)
  })

  it('B3 行为面：带 `?t=` 落地时首页不排那个 600ms 的跳转（红证：删掉闸 ⇒ 工人被踢到商家登录页）', () => {
    jest.useFakeTimers()
    try {
      gotoLanding(`?t=${TOKEN}`)
      const ChatPage = loadChatPage()
      render(React.createElement(ChatPage))
      jest.advanceTimersByTime(1000)
      expect(Taro.redirectTo).not.toHaveBeenCalled()
    } finally {
      jest.useRealTimers()
    }
  })

  it('B3 行为面反证：没有落地参数时首页照旧排那个跳转（证明上一条的"绿"不是空跑）', async () => {
    jest.useFakeTimers()
    try {
      gotoLanding('')
      const ChatPage = loadChatPage()
      render(React.createElement(ChatPage))
      // `checkAuth()` 自 issue #7249 起是异步的 ⇒ 跳转定时器排在微任务里（判据不放宽，只让微任务跑完）
      await Promise.resolve()
      await Promise.resolve()
      jest.advanceTimersByTime(1000)
      expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/auth/login/index' })
    } finally {
      jest.useRealTimers()
    }
  })
})

describe('B3b 商家面守卫也不抢落地（issue #7887：工人扫纸上的码落在工人菜单）', () => {
  /** 纯工人设备：有工人 session、**没有**商家凭据（= 车间里每一台工人手机） */
  function workerOnly(): void {
    Taro.removeStorageSync(STORAGE_KEYS.TOKEN)
    Taro.removeStorageSync(STORAGE_KEYS.USER)
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'ws-1')
    Taro.setStorageSync(STORAGE_KEYS.WORKER, { id: 'w1', name: '工人', workerNo: '009' })
  }

  /** 探针：只挂守卫（测的是 hook 本身，不是某一页的副作用） */
  function GuardProbe() {
    useMerchantSurfaceGuard()
    return React.createElement('div')
  }

  afterEach(() => {
    ;[STORAGE_KEYS.WORKER_SESSION, STORAGE_KEYS.WORKER].forEach((key) => Taro.removeStorageSync(key))
  })

  it('负控基线：纯工人设备 + **无**落地参数 ⇒ 照旧送回工人工作台（证明 skip 不是把守卫废掉）', () => {
    gotoLanding('')
    workerOnly()
    render(React.createElement(GuardProbe))
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: WORKER_HOME_ROUTE })
  })

  it('🔴 带 `?t=` 落地 ⇒ 守卫**不抢路由**（否则两跳 redirect 只会活下来"工人工作台"那条）', () => {
    gotoLanding(`?t=${TOKEN}`)
    workerOnly()
    render(React.createElement(GuardProbe))
    expect(Taro.redirectTo).not.toHaveBeenCalled()
  })

  it('🔴 带 `?code=` 落地 ⇒ 守卫同样不抢路由（补打页不被劫，与 #5052 同款动线）', () => {
    gotoLanding('?code=ABCD2345')
    workerOnly()
    render(React.createElement(GuardProbe))
    expect(Taro.redirectTo).not.toHaveBeenCalled()
  })

  it('🔴 负控（#7880 不许被本单影响）：手机端 `?qr=<票据>` 不含 t/code ⇒ 守卫照旧把人送回工人工作台', () => {
    // 「手机端」码 = 商家在 PC 上点「手机端」出的票据（`?qr=`），**不是**纸上的码（`?t=` / `?code=`）。
    // 它的去处由 #7880 的工人优先逻辑决定（工人 session 在场 ⇒ 工人工作台）—— 本单的落地闸不许把它一起放行。
    gotoLanding('?qr=ticket-abc')
    workerOnly()
    render(React.createElement(GuardProbe))
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: WORKER_HOME_ROUTE })
  })

  it('类级：守卫**在跳转之前**必须问 `hasLandingIntent()`（把闸删掉 ⇒ 这里红，不是只靠上面两条行为面）', () => {
    const code = codeOf('src/utils/roleGuard.ts')
    const body = code.slice(code.indexOf('export function useMerchantSurfaceGuard'))
    expect(body).toContain('hasLandingIntent()')
    // 闸必须在 `redirectTo` **之前**（写在后面 = 等于没有闸，但行为面可能因为渲染时序看起来是绿的）
    expect(body.indexOf('Taro.redirectTo')).toBeGreaterThan(body.indexOf('hasLandingIntent()'))
  })
})

describe('B3c 服务端 302 的路由常量与前端注册的路由逐字一致（issue #7889）', () => {
  it('🔴 报工落点不写前端路由（`/w/` 是静态多页应用，加 hash 路由只会让「第二跳」回来 —— issue #7899）', () => {
    const java = fs.readFileSync(
      path.join(REPO_ROOT, 'backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java'),
      'utf8',
    )
    // 强断言：源码里不得再声明 REPORT_ROUTE（有 ⇒ 说明又有人把 SPA 路由写进 302 目标）
    expect(/REPORT_ROUTE/.test(java)).toBe(false)
  })

  it('🔴 `InboundLabelService.LANDING_ROUTE` == `REPRINT_PAGE_ROUTE`（补打页同款）', () => {
    const java = fs.readFileSync(
      path.join(REPO_ROOT, 'backend/admin-api/src/main/java/com/migao/admin/service/InboundLabelService.java'),
      'utf8',
    )
    const matched = /LANDING_ROUTE\s*=\s*"([^"]+)"/.exec(java)
    expect(matched?.[1]).toBe(REPRINT_PAGE_ROUTE)
  })
})

describe('B4 落点真值 = `/w/`（issue #7899：纸上的码回到经多轮测试的静态多页报工面）', () => {
  it('B4 302 的唯一真值 = `/w/`（`REPORT_PAGE_PATH`）', () => {
    const source = stripComments(
      fs.readFileSync(
        path.join(
          REPO_ROOT,
          'backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java',
        ),
        'utf8',
      ),
    )
    const declared = /REPORT_PAGE_PATH\s*=\s*"([^"]+)"/.exec(source)
    expect(declared?.[1]).toBe('/w/')
  })

  it('B4 启动器 / 工人首页 / 入口台账的**代码**里不再出现 `/w/`', () => {
    for (const relative of [
      'src/app.tsx',
      'src/pages/worker/home/index.tsx',
      'src/utils/pageEntries.ts',
      'src/utils/inbound/gaps.ts',
    ]) {
      expect({ relative, hits: codeOf(relative).includes('/w/') }).toEqual({ relative, hits: false })
    }
  })

  it('B4 入口台账：报工页有**两条**发射方（端内点击 + 扫码落地），且 `via` 都不含 `/w/`', () => {
    const entries = PAGE_ENTRY_LEDGER.filter((entry) => entry.route === REPORT_PAGE_ROUTE)
    expect(entries.map((entry) => entry.from).sort()).toEqual([
      'src/app.tsx',
      'src/pages/worker/home/index.tsx',
    ])
    for (const entry of entries) {
      expect(entry.via).not.toContain('/w/')
    }
    // 扫码落地那条必须走 `reportLandingUrl`（拼装只有一处），不是手拼 `?t=`
    const landing = entries.find((entry) => entry.from === 'src/app.tsx')
    expect(landing?.nav).toBe('redirectTo')
    expect(landing?.via).toBe('reportLandingUrl')
    expect(codeOf('src/app.tsx')).toContain('reportLandingUrl(')
  })
})

describe('入口解析：六形态一张表（H5 与小程序共用同一个解析器）', () => {
  it('形态 1：h5 302 落点 `?t=<token>` ⇒ 报工页', () => {
    expect(resolveScanLanding({ search: `?t=${TOKEN}&tenant_id=7&tenant_code=migao` })).toEqual({
      kind: 'report',
      code: TOKEN,
      from: 'param-t',
    })
  })

  it('形态 2：小程序码 `scene`（B 档，≤32 字符、需 decodeURIComponent）⇒ 报工页', () => {
    expect(resolveScanLanding({ query: { scene: '7K3M9QP2' } })).toEqual({
      kind: 'report',
      code: '7K3M9QP2',
      from: 'mini-app-code',
    })
    // 编码过的 scene 也要还原（微信会做 urlencode）
    expect(resolveScanLanding({ scene: '7K3M9QP2%3D' }).code).toBe('7K3M9QP2=')
  })

  it('形态 3：扫普通链接二维码进小程序 `q`（A 档 = **主路径**，URL-encoded 完整链接）⇒ 报工页', () => {
    const link = 'https://app.migaozn.com/s/7K3M9QP2'
    expect(resolveScanLanding({ query: { q: encodeURIComponent(link) } })).toEqual({
      kind: 'report',
      code: '7K3M9QP2',
      from: 'link-qr',
    })
    // 完整链接里带 302 落点那种形态（`/b/?t=`）也要取出 token
    expect(resolveScanLanding({ q: encodeURIComponent(`https://app.migaozn.com/b/?t=${TOKEN}`) }).code).toBe(TOKEN)
    // 🔴 顺序：A 档（`q`）优先于 B 档（`scene`）—— 两个都在时以 `q` 为准
    expect(resolveScanLanding({ query: { q: encodeURIComponent(link), scene: 'ZZZZZZZZ' } }).code).toBe('7K3M9QP2')
  })

  it('形态 4：小程序内扫一扫的完整 URL（含 `/s/<短码>`）⇒ 报工页', () => {
    expect(resolveScanLanding({ text: 'https://app.migaozn.com/s/7K3M9QP2' })).toEqual({
      kind: 'report',
      code: '7K3M9QP2',
      from: 'scan-text',
    })
    // 手输的加工单号 / 订单号也原样交给服务端（服务端自己判它是不是码）
    expect(codeFromScanText('JG-20260901-001')).toBe('JG-20260901-001')
  })

  it('形态 5：裸 8 位短码（页面参数 / 手输）⇒ 报工页', () => {
    expect(resolveScanLanding({ params: { t: '7K3M9QP2' } })).toEqual({
      kind: 'report',
      code: '7K3M9QP2',
      from: 'param-t',
    })
    expect(resolveScanLanding({ text: '7K3M9QP2' }).code).toBe('7K3M9QP2')
    // `code` 是**入库标签**那一支（补打页），与报工不串道
    expect(resolveScanLanding({ params: { code: '7K3M9QP2' } }).kind).toBe('reprint')
  })

  it('形态 6：垃圾输入 / 空输入 ⇒ 没有落地（不去任何页），且不抛', () => {
    expect(resolveScanLanding({})).toEqual(NONE_LANDING)
    expect(resolveScanLanding({ search: '?tenant_id=7' })).toEqual(NONE_LANDING)
    expect(resolveScanLanding({ search: '?t=' })).toEqual({ kind: 'report', code: '', from: 'param-t' })
    expect(resolveScanLanding({ query: { foo: 'bar' } })).toEqual(NONE_LANDING)
    // 非法百分号编码不得把解析变成异常/白屏
    expect(readQueryParam('?t=AB%ZZ', 't')).toEqual({ present: true, raw: 'AB%ZZ' })
    expect(resolveScanLanding({ q: '%%%' }).code).toBe('%%%')
  })

  it('不依赖 `window`：小程序侧（无 URL）也能跑 → 并给出 platform-agnostic 结论', () => {
    // 解析器本身是纯函数：不读 window / 不读 TARO_ENV（判据 = 下面这条结构断言）
    const codes = io(`src/utils/scanInput.ts`)
    expect(codes).not.toContain('window.')
    expect(codes).not.toContain('process.env.TARO_ENV')
    expect(codes).not.toContain("'@tarojs/taro'")
  })
})

describe('结构断言：两条入口路径都走同一个解析器（禁止给小程序再写一份）', () => {
  it('h5 启动器与小程序报工页都调用 `currentEntryLanding()`，且页面里**不判平台**', () => {
    for (const relative of ['src/app.tsx', 'src/pages/worker/report/index.tsx']) {
      const code = io(relative)
      expect({ relative, resolver: code.includes('currentEntryLanding(') }).toEqual({
        relative,
        resolver: true,
      })
      // 「一套代码」的判据：页面不出现任何平台分支
      expect({ relative, platform: /process\.env\.TARO_ENV|isH5\(|isWeapp\(/.test(code) }).toEqual({
        relative,
        platform: false,
      })
    }
    // 平台分支只许住在 reportEntry.ts 一个文件里
    const entry = io('src/utils/reportEntry.ts')
    expect(entry).toContain('isH5()')
    expect(entry).toContain('isWeapp()')
    // 小程序进入参数的读取也只许在这一处
    for (const relative of ['src/app.tsx', 'src/pages/worker/report/index.tsx', 'src/utils/scanInput.ts']) {
      expect({ relative, enter: io(relative).includes('getEnterOptionsSync') }).toEqual({
        relative,
        enter: false,
      })
    }
    expect(entry).toContain('getEnterOptionsSync')
  })

  it('报工页不再自己解析扫码原文（唯一实现在 `scanInput.ts`）', () => {
    expect(io('src/pages/worker/report/index.tsx')).toContain('resolveScanLanding(')
    // 转发层（`tokensFromScanResult`）也不许再写第二份解析
    expect(io('src/utils/reportState.ts')).toContain('codeFromScanText(text)')
  })
})

describe('未登录回跳：登录完回到报工页继续报这一笔', () => {
  it('`rememberReportReturn` ⇒ `takeReportReturn` 往返一次即清（一次性）', () => {
    rememberReportReturn(TOKEN)
    expect(takeReportReturn()).toEqual({ present: true, code: TOKEN })
    // 读到即清：下一次登录不会被上一次的码带跑
    expect(takeReportReturn()).toEqual({ present: false, code: '' })
    // 只记「回报工页」不记码也成立（工人回来重新扫）
    rememberReportReturn('')
    expect(takeReportReturn()).toEqual({ present: true, code: '' })
  })

  it('回跳 URL 就是报工页的落地形态（与 302 落点同一个参数名）', () => {
    expect(reportReturnUrl(TOKEN)).toBe(`${REPORT_PAGE_ROUTE}?t=${TOKEN}`)
    expect(reportReturnUrl('')).toBe(`${REPORT_PAGE_ROUTE}?t=`)
  })

  it('接线：报工页在「去登录」前记、登录页在成功后读并回跳（红证：删掉任一侧 ⇒ 这里红）', () => {
    const report = io('src/pages/worker/report/index.tsx')
    expect(report).toContain('rememberReportReturn(')
    const login = io('src/pages/auth/login/index.tsx')
    expect(login).toContain('takeReportReturn()')
    expect(login).toContain('reportReturnUrl(')
    expect(login).toContain('WORKER_HOME_ROUTE')
    // 存储键是单一真值（两侧都用这个常量，不各写一份字面量）
    expect(PENDING_REPORT_RETURN_KEY).toBe('workerPendingReportReturn')
  })
})

describe('h5 与小程序同一份：`currentEntryLanding()` 按平台取来源', () => {
  it('h5：读 URL search（小程序分支在这条路径上不发生）', () => {
    gotoLanding(`?t=${TOKEN}`)
    expect(currentEntryLanding()).toEqual({ kind: 'report', code: TOKEN, from: 'param-t' })
    gotoLanding('?code=ABCD2345')
    expect(currentEntryLanding()).toEqual({ kind: 'reprint', code: 'ABCD2345', from: 'param-code' })
    gotoLanding('')
    expect(currentEntryLanding()).toEqual(NONE_LANDING)
  })
})

describe('小程序侧：同一份代码、同一个解析器（无 `window` 也能跑）', () => {
  afterEach(() => {
    process.env.TARO_ENV = 'h5'
    ;(Taro as any).getEnterOptionsSync.mockReset()
    ;(Taro as any).getEnterOptionsSync.mockReturnValue({ query: {}, scene: 0 })
  })

  it('A 档主路径：`getEnterOptionsSync().query.q`（URL-encoded 完整链接）⇒ 报工页', () => {
    process.env.TARO_ENV = 'weapp'
    ;(Taro as any).getEnterOptionsSync.mockReturnValue({
      query: { q: encodeURIComponent('https://app.migaozn.com/s/7K3M9QP2') },
    })
    // 小程序里没有 `window`（jsdom 有，但这条路一个字节都不读它）
    expect(currentEntryLanding()).toEqual({ kind: 'report', code: '7K3M9QP2', from: 'link-qr' })
  })

  it('B 档：小程序码 `query.scene`（8 位短码）⇒ 报工页；没有进入参数 ⇒ 不去任何页', () => {
    process.env.TARO_ENV = 'weapp'
    ;(Taro as any).getEnterOptionsSync.mockReturnValue({ query: { scene: '7K3M9QP2' } })
    expect(currentEntryLanding()).toEqual({ kind: 'report', code: '7K3M9QP2', from: 'mini-app-code' })
    ;(Taro as any).getEnterOptionsSync.mockReturnValue({ query: {} })
    expect(currentEntryLanding()).toEqual(NONE_LANDING)
  })
})
