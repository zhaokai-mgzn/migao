// case_ids: BM-026
/**
 * **落地页深链被消费且按码空间分流**（issue #5052 实现 PR；设计 §5.4 / §7.1）
 *
 * ## 治的形态：服务端 302 了，而参数**没有任何人读**
 *
 * 纸上的码 = `https://app.migaozn.com/i/<短码>`，服务端 `InboundLabelShortLinkController`
 * 302 到 `/b/?code=<短码>&tenant_id=…`。**实测（修复前）**：全仓 `params.code` / `query.code` /
 * `searchParams` **零命中** ⇒ 工人扫了自家标签、落到商家首页，**而且没有任何东西会变红**
 * （码好的、302 好的、页面也不报错）。本文件钉住三件事：
 * ① 参数被**读到**（"出现但为空"与"根本没出现"是两件事）；
 * ② 分流**复用** `codeSpace.ts` 的既有判定（不新造第五套口径）；
 * ③ 失败方向**不静默**（读不到 / 形态不合法 ⇒ 明确提示）。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | D1 | `/b/?code=<合法入库短码>`（服务端 302 的**裸短码**形态）⇒ 入库标签空间 + 短码原样带走 | 删掉消费逻辑 / 裸码判成 foreign ⇒ 红 |
 * | D2 | 🔴 `/b/?code=<洗水码 URL>` ⇒ 洗水码空间 + 报工入口（**绝不**当入库标签） | 不看码空间直接取路径段 ⇒ 红 |
 * | D3 | 别域名 / 纯文本 ⇒ 「这不是米高的标签」；空值 ⇒ 「8 位短码」提示（**都不静默**） | 读不到就 `return`（静默当没有参数）⇒ 红 |
 * | D4 | 「**出现但为空**」与「**没出现**」可区分（`present`） | 合并成一个 `raw === ''` 判断 ⇒ 红 |
 * | D5 | 启动器（`src/app.tsx`）真的把码交给补打页（渲染 `App` 实跑，断言 `Taro.redirectTo`） | 删掉那两行 ⇒ 红 |
 * | D6 | 商家首页**不抢路由**：URL 上带 `?code=` 时不再排"未登录 ⇒ 去商家登录"的定时器 | 删掉那道闸 ⇒ 红（工人被踢到商家登录页） |
 *
 * ⚠️ 页面侧的消费（`router.params.code` → 码空间判定 → 读详情 / 拒绝读详情）在
 * `tests/worker-reprint-page.test.tsx` 的 R1~R4；两文件合起来才是「h5 落地 → 页面消费」的整条链。
 */
import React from 'react'
import { render } from '@testing-library/react'
import Taro from '@tarojs/taro'
import {
  LANDING_CODE_PARAM,
  classifyLandingCode,
  landingCodeFromParams,
  landingCodeFromSearch,
  reprintLandingUrl,
} from '../src/utils/inbound/deepLink'
import {
  FOREIGN_CODE_MESSAGE,
  MANUAL_CODE_INVALID_MESSAGE,
  REPORT_PAGE_ROUTE,
  WASH_CODE_MESSAGE,
} from '../src/utils/inbound/codeSpace'
import { REPRINT_PAGE_ROUTE } from '../src/utils/inbound/gaps'
import { BMINI_ROOT, stripComments } from './helpers/h5PlatformLists'

const ORIGINAL_TARO_ENV = process.env.TARO_ENV
process.env.TARO_ENV = 'h5'

/** 启动器 App 与商家首页都要用到的那一份 auth store 替身（`initialize` 单独拿出来数调用次数） */
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

beforeEach(() => {
  jest.clearAllMocks()
  gotoLanding('')
})

afterAll(() => {
  process.env.TARO_ENV = ORIGINAL_TARO_ENV
})

describe('落地页深链：读参数（读不到 ≠ 读到空）', () => {
  it('D4 从 URL query 读：出现 / 不出现 / 出现但为空 三态可分', () => {
    expect(landingCodeFromSearch('?code=ABCD2345')).toEqual({ present: true, raw: 'ABCD2345' })
    expect(landingCodeFromSearch('code=ABCD2345&tenant_id=7')).toEqual({ present: true, raw: 'ABCD2345' })
    expect(landingCodeFromSearch('?code=')).toEqual({ present: true, raw: '' })
    expect(landingCodeFromSearch('?tenant_id=7')).toEqual({ present: false, raw: '' })
    expect(landingCodeFromSearch('')).toEqual({ present: false, raw: '' })
    // 值里的百分号编码 / `+`（空格）要还原，其余**原样**交给服务端
    expect(landingCodeFromSearch('?code=/s/7K3M9QP2')).toEqual({ present: true, raw: '/s/7K3M9QP2' })
    expect(landingCodeFromSearch('?code=https%3A%2F%2Fapp.migaozn.com%2Fs%2F7K3M9QP2')).toEqual({
      present: true,
      raw: 'https://app.migaozn.com/s/7K3M9QP2',
    })
    expect(landingCodeFromSearch('?code=ABCD%20234')).toEqual({ present: true, raw: 'ABCD 234' })
    // 非法百分号编码不得把"读参数"变成白屏
    expect(landingCodeFromSearch('?code=ABCD%ZZ')).toEqual({ present: true, raw: 'ABCD%ZZ' })
  })

  it('D4 从页面参数读（小程序那一侧与 h5 路由 query 共用它）', () => {
    expect(landingCodeFromParams({ code: 'ABCD2345' })).toEqual({ present: true, raw: 'ABCD2345' })
    expect(landingCodeFromParams({ code: '' })).toEqual({ present: true, raw: '' })
    expect(landingCodeFromParams({ tenant_id: '7' })).toEqual({ present: false, raw: '' })
    expect(landingCodeFromParams(null)).toEqual({ present: false, raw: '' })
    expect(landingCodeFromParams(undefined)).toEqual({ present: false, raw: '' })
  })

  it('D1 短码 ⇒ 送进补打页（路由 + 参数名只有一处真值）', () => {
    expect(reprintLandingUrl('ABCD2345')).toBe(`${REPRINT_PAGE_ROUTE}?${LANDING_CODE_PARAM}=ABCD2345`)
    // 含分隔符 / 特殊字符的原文照样编码带走（页面再判定，启动器不改写）
    expect(reprintLandingUrl('/s/7K3M9QP2')).toBe(`${REPRINT_PAGE_ROUTE}?code=%2Fs%2F7K3M9QP2`)
    expect(reprintLandingUrl('')).toBe(`${REPRINT_PAGE_ROUTE}?code=`)
  })
})

describe('落地页深链：按码空间分流（复用 codeSpace 的既有判定）', () => {
  it('D1 服务端 302 的裸短码 ⇒ 入库标签空间 + 短码原样（客户端不归一化）', () => {
    const reading = classifyLandingCode('7K3M9QP2')
    expect(reading.space).toBe('inbound-label')
    expect(reading.shortCode).toBe('7K3M9QP2')
    // 抄错形态（O/I/L）照样原样交给服务端（归一化在 `WorkerShortLinkService.normalize`）
    expect(classifyLandingCode('ABCDO234').shortCode).toBe('ABCDO234')
    // 整条 URL 形态也认（工人从聊天记录里粘过来的就是它）
    expect(classifyLandingCode('https://app.migaozn.com/i/ABCD2345').space).toBe('inbound-label')
  })

  it('D2 🔴 洗水码 ⇒ 洗水码空间 + 报工入口（**绝不**当入库标签）', () => {
    for (const raw of ['https://app.migaozn.com/s/7K3M9QP2', '/s/7K3M9QP2']) {
      const reading = classifyLandingCode(raw)
      expect({ raw, space: reading.space }).toEqual({ raw, space: 'wash-code' })
      expect(reading.message).toBe(WASH_CODE_MESSAGE)
      expect(reading.action?.route).toBe(REPORT_PAGE_ROUTE)
    }
    // 🔴 红证：不看码空间的宽松口径**确实**能从 `/s/` 的码里取出一段像模像样的 8 位短码
    const loose = 'https://app.migaozn.com/s/7K3M9QP2'.split('/').pop()
    expect(loose).toBe('7K3M9QP2')
    expect(classifyLandingCode('https://app.migaozn.com/s/7K3M9QP2').space).not.toBe('inbound-label')
  })

  it('D3 别域名 / 纯文本 ⇒ 「这不是米高的标签」；空值 ⇒ 「8 位」提示（都不静默）', () => {
    for (const raw of ['https://evil.example/i/ABCD2345', 'MG-1001', 'hello world']) {
      const reading = classifyLandingCode(raw)
      expect({ raw, space: reading.space }).toEqual({ raw, space: 'foreign' })
      expect(reading.message).toBe(FOREIGN_CODE_MESSAGE)
      expect(reading.shortCode).toBe(null)
    }
    for (const raw of ['', '   ']) {
      const reading = classifyLandingCode(raw)
      expect({ raw, space: reading.space }).toEqual({ raw, space: 'invalid-input' })
      expect(reading.message).toBe(MANUAL_CODE_INVALID_MESSAGE)
    }
    // 抄短的 / 抄漏的形态（工人最常见的错）⇒ 走「扫到」口径的 foreign（明说"这不是米高的标签"
    // 并给出"手输那 8 位"的出路）—— 判据只要求**不静默**、给得出下一句可行动的话
    expect(classifyLandingCode('ABCD2').space).toBe('foreign')
    expect(classifyLandingCode('ABCD2').message).toBe(FOREIGN_CODE_MESSAGE)
    // 空值**不许**被判成"没解出码"（`undecoded` 的文案是"请重拍照片" —— 这里根本没人在拍照）
    expect(classifyLandingCode('').space).not.toBe('undecoded')
  })
})

describe('落地页深链：启动器 App（h5 落地）', () => {
  it('D5 🔴 `/b/?code=<短码>` ⇒ 启动器把码交给补打页（`Taro.redirectTo`）', () => {
    gotoLanding('?code=ABCD2345&tenant_id=7')
    const App = loadApp()
    render(<App>{null}</App>)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `${REPRINT_PAGE_ROUTE}?code=ABCD2345` })
  })

  it('D5 洗水码**照样**交给补打页（判定与文案在页面里；启动器只搬运、不自己判）', () => {
    gotoLanding('?code=https%3A%2F%2Fapp.migaozn.com%2Fs%2F7K3M9QP2')
    const App = loadApp()
    render(<App>{null}</App>)
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: `${REPRINT_PAGE_ROUTE}?code=${encodeURIComponent('https://app.migaozn.com/s/7K3M9QP2')}`,
    })
  })

  it('D5 出现但为空 ⇒ 也交给补打页（页面给"8 位短码"提示，不静默当没有参数）', () => {
    gotoLanding('?code=')
    const App = loadApp()
    render(<App>{null}</App>)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `${REPRINT_PAGE_ROUTE}?code=` })
  })

  it('D5 没有这个参数 ⇒ **不抢路由**（商家 h5 正常开首页；空跑反证）', () => {
    gotoLanding('?tenant_id=7')
    const App = loadApp()
    render(<App>{null}</App>)
    expect(Taro.redirectTo).not.toHaveBeenCalled()
    expect(mockAuthInitialize).toHaveBeenCalledTimes(1)
  })
})

describe('落地页深链：商家首页不抢路由（D6）', () => {
  it('D6 源码面：首页初始化前先看「URL 上有没有落地码」，有就让位', () => {
    const code = stripComments(
      require('fs').readFileSync(require('path').join(BMINI_ROOT, 'src/pages/chat/index/index.tsx'), 'utf8'),
    )
    expect(code).toContain('currentLandingCode')
    const gate = code.indexOf('currentLandingCode()')
    const steal = code.indexOf("Taro.redirectTo({ url: '/pages/auth/login/index' })")
    expect(gate).toBeGreaterThan(-1)
    // 闸必须在"去商家登录"之前（反了就等于没有）
    expect(steal).toBeGreaterThan(gate)
  })

  it('D6 行为面：带码落地时首页不排那个 600ms 的跳转（红证：删掉闸 ⇒ 工人被踢到商家登录页）', () => {
    jest.useFakeTimers()
    try {
      gotoLanding('?code=ABCD2345')
      const ChatPage = loadChatPage()
      render(<ChatPage />)
      jest.advanceTimersByTime(1000)
      expect(Taro.redirectTo).not.toHaveBeenCalled()
    } finally {
      jest.useRealTimers()
    }
  })

  it('D6 行为面反证：**没有**落地码时首页照旧排那个跳转（证明上一条的"绿"不是空跑）', () => {
    jest.useFakeTimers()
    try {
      gotoLanding('')
      const ChatPage = loadChatPage()
      render(<ChatPage />)
      jest.advanceTimersByTime(1000)
      expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/auth/login/index' })
    } finally {
      jest.useRealTimers()
    }
  })
})
