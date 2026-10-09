// case_ids: BM-040
/**
 * 「加工单详情」只读页（商家面）—— issue #6567
 *
 * ## 为什么是这五条
 * 这一页存在的理由只有一个：商家在「数据」页点一张待办卡片，要看到**这一单什么情况**，
 * 而不是拿起手机去扫码报工（旧落脚点是报工页：扫一扫 + 手输单号 + 「去登录工人身份」）。
 * ⇒ 判据必须同时钉住「该显示的显示了」与「**不该出现的没出现**」：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | 抬头逐字来自服务端（加工单号 / 订单号 / 客户 / 交期） | 把某一行的值改成本地拼串 ⇒ 值对不上 ⇒ 红 |
 * | 2 | 工序名单走唯一口径 `逻辑名 · 部位` + 应做/已报数量原样 | 手拼工序名 ⇒ 显示名对不上 ⇒ 红 |
 * | 3 | 🔴 **纯只读**：源码（去注释）里没有扫一扫 / 工人登录 / 报工写入口记号 | 注入一个「扫一扫」按钮或 `scanResolve(` ⇒ 红 |
 * | 4 | 403 ⇒ **权限文案**（不是「没有数据」） | 把 `forbidden` 分支删掉 ⇒ 落到「加载失败」⇒ 红 |
 * | 5 | 「订单还没有加工单」与「加载失败」分开说；失败可重试 | 把 `data:null` 当失败 ⇒ 文案错 ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    getCurrentInstance: jest.fn(() => ({ router: { params: { orderId: 'order-1' } } })),
    navigateTo: jest.fn(),
    redirectTo: jest.fn(),
    getStorageSync: jest.fn(() => ''),
    setStorageSync: jest.fn(),
    removeStorageSync: jest.fn(),
    showToast: jest.fn(),
  },
  useDidShow: jest.fn(),
}))

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  del: jest.fn(),
}))

import Taro from '@tarojs/taro'
import { get } from '../src/utils/request'
import OrderDetailPage from '../src/pages/production/order-detail/index'
import { stripComments } from './helpers/h5PlatformLists'

const mockGet = get as unknown as jest.Mock

/**
 * 「数据」页待办标签的样式（issue #6597 缺陷 A：`.task-item__tag` 原 `width: 64px` 装不下
 * 服务端下发的「卡在哪」3 字 ⇒ 折成两行）。本文件顺带钉住那一条的**形态**判据。
 */
const SRC_DIR = path.join(__dirname, '../src')
/** 剔除注释后的 scss（注释里写了 `white-space: nowrap` 不算落实） */
function scssCode(file: string): string {
  return fs
    .readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

/**
 * 取嵌套 scss 里 `&<suffix> { … }` 的规则体（suffix 例：`__tag` / `__tag-text`）。
 *
 * 🔴 尾边界要 `\n`（原写法 `\{([^}]*)\}` 会在 `&__tag { … &-text { … } }` 上从 `&__tag`
 * 一路吃到**最后**一个 `}` ⇒ 规则体里混进子规则，判据退化成「A 或 B 满足即可」）。
 * 射程内的规则体属性一行一条（本仓 scss 口径）⇒ 取到首个 `}` 所在行即可。
 */
function ruleBody(scss: string, suffix: string): string | null {
  const escaped = suffix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = scss.match(new RegExp(`&${escaped}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`))
  return match ? match[1] : null
}

/**
 * 取不到就**抛**（不是弱断言）。
 *
 * 🔴 刻意**不**写「取到非空」那种期望式：QA Growth Gate 把「只证明东西在」的期望式判**弱断言**
 * 且 fail-closed，而 `.github/weak-assert-baseline.json` **只许非增** —— 集成时实测本文件因它红过
 * （`--check-weak-baseline`：锚点 238 处 → 当前 239 处）。
 * ⚠️ 连**注释里**写出那个期望式的字面量也会被判红（扫描器分不清「引用」与「使用」，本仓已多次踩到）
 * ⇒ 本节只描述形态、**不写那个字面量**。
 * 「反空跑」的意图原样保留，但落成**会抛的取值**：取不到即当场失败，后面的读数断言不空转。
 * 同款写法见 `tests/e2e/specs/bmini/bmini-tabbar.spec.ts` 的 `must()`。
 */
function must<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) {
    throw new Error(`取不到 ${what}（选择器/文件漂了？）`)
  }
  return value
}

const BRIEF = {
  success: true,
  data: {
    id: 'po-1',
    orderId: 'order-1',
    orderNo: 'SO-2026-001',
    processingOrderNo: 'MO-2026-001',
    customerName: '陈女士',
    expectedDeliveryDate: '2026-10-12',
  },
}

const OPERATIONS = {
  success: true,
  data: {
    order_id: 'order-1',
    positions: [
      {
        position_name: '布帘',
        operations: [
          {
            id: 'op-1',
            seq: 1,
            operation: '精裁-布',
            logical_name: '精裁',
            position: '布帘',
            group: 'g1',
            unit: '米',
            qty: 6,
            unit_price: 3,
            is_must_finish: true,
            is_start_marker: false,
            status: 'done',
            done_qty: 6,
          },
        ],
      },
    ],
    progress: { total: 1, done: 1, percent: 100 },
  },
}

/** 按 URL 分派桩响应（两条读面各自独立，便于单条失败/403 的用例） */
function stub(props: { brief?: any; operations?: any; briefError?: any; opsError?: any } = {}) {
  mockGet.mockImplementation((url: string) => {
    // 卡点面（issue #6597 缺陷 B）在本文件里不是被测对象 ⇒ 一律桩「没有卡点」，
    // 让本文件既有五条判据的读数不被它影响（它自己的判据在 processing-order-detail-stuck.test.tsx）。
    if (url.includes('/api/admin/production/stuck-points')) {
      return Promise.resolve({ success: true, data: { stuck_total: 0, stuck: [] } })
    }
    if (url.includes('/api/admin/processing-orders/')) {
      return props.briefError ? Promise.reject(props.briefError) : Promise.resolve(props.brief ?? BRIEF)
    }
    if (url.includes('/operations')) {
      return props.opsError ? Promise.reject(props.opsError) : Promise.resolve(props.operations ?? OPERATIONS)
    }
    return Promise.reject(new Error(`未桩住的端点：${url}`))
  })
}

describe('加工单详情页（商家只读面）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    stub()
  })

  it('抬头与工序逐字来自服务端（加工单号 / 订单号 / 客户 / 交期 + 工序进度）', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-header')).toBeTruthy())

    expect(screen.getByText('加工单号')).toBeTruthy()
    expect(screen.getByText('MO-2026-001')).toBeTruthy()
    expect(screen.getByText('订单号')).toBeTruthy()
    expect(screen.getByText('SO-2026-001')).toBeTruthy()
    expect(screen.getByText('客户')).toBeTruthy()
    expect(screen.getByText('陈女士')).toBeTruthy()
    expect(screen.getByText('交期')).toBeTruthy()
    expect(screen.getByText('2026-10-12')).toBeTruthy()
    // 工序名走唯一口径（`逻辑名 · 部位`），数量原样
    expect(screen.getByText('精裁 · 布帘')).toBeTruthy()
    expect(screen.getByText('应做 6米 · 已报 6米')).toBeTruthy()
    expect(screen.getByText('已完成 1/1')).toBeTruthy()
  })

  it('拿不到的字段**不渲染那一行**（不补默认值、不摆占位）', async () => {
    stub({ brief: { success: true, data: { id: 'po-1', orderId: 'order-1', processingOrderNo: 'MO-1' } } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-header')).toBeTruthy())

    expect(screen.getByText('MO-1')).toBeTruthy()
    expect(screen.queryByText('客户')).toBeNull()
    expect(screen.queryByText('交期')).toBeNull()
    expect(screen.queryByText('订单号')).toBeNull()
  })

  it('🔴 403 ⇒ 显式权限文案（**不是**「没有数据」，也不是「加载失败」）', async () => {
    stub({ briefError: Object.assign(new Error('无权限'), { statusCode: 403 }) })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-forbidden')).toBeTruthy())

    expect(screen.getByText('无「生产看板」查看权限（需要权限码 production:view）')).toBeTruthy()
    expect(screen.queryByTestId('order-detail-no-processing-order')).toBeNull()
    expect(screen.queryByTestId('order-detail-error')).toBeNull()
  })

  it('订单还没有加工单（服务端 `success + data:null`）⇒ 单独一句，不当失败', async () => {
    stub({ brief: { success: true, data: null } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-no-processing-order')).toBeTruthy())

    expect(screen.getByText('这笔订单还没有加工单')).toBeTruthy()
    expect(screen.queryByTestId('order-detail-error')).toBeNull()
    expect(screen.queryByTestId('order-detail-forbidden')).toBeNull()
  })

  it('加载失败 ⇒ 错误文案 + 可重试（重试真的再发一次请求）', async () => {
    stub({ briefError: new Error('boom') })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-error')).toBeTruthy())

    const callsBefore = mockGet.mock.calls.length
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(mockGet.mock.calls.length).toBeGreaterThan(callsBefore))
  })

  it('没带参数 ⇒ 说清「从数据页的待办点进来」，不发任何请求', async () => {
    ;(Taro.getCurrentInstance as jest.Mock).mockReturnValue({ router: { params: {} } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-missing-id')).toBeTruthy())
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('🔴 纯只读：源码（去注释）里没有任何工人面记号', () => {
    const src = stripComments(
      fs.readFileSync(path.join(__dirname, '../src/pages/production/order-detail/index.tsx'), 'utf8'),
    )
    ;[
      '扫一扫',
      '去登录工人身份',
      'scanResolve',
      'completeByScan',
      'getWorkerOrderOperations',
      'hasWorkerSession',
      'WORKER_TAB_LOGIN_ROUTE',
      'PRODUCTION_WORKER_LOGIN_REQUIRED',
      'workerSessionHeaders',
    ].forEach((token) => {
      expect({ token, present: src.includes(token) }).toEqual({ token, present: false })
    })
    // 反向自证：源码里**确实**在消费那两条只读读面（否则上面那串「都没出现」是空跑）
    expect(src).toContain('getProcessingOrderBrief(')
    expect(src).toContain('getOrderOperations(')
  })
})

/**
 * issue #6597 缺陷 A：「卡在哪」标签折行（用户截图 = 「卡在 / 哪」两行）。
 *
 * **根因**：`src/pages/dashboard/index/index.scss` 的 `.task-item__tag{width:64px;…}` ——
 * 标签文案由**服务端**下发（`type_label`，3 字 × `font-size:24px` = 72px）⇒ 装不下就折行。
 * 前端不该为固定文案配死宽度。
 *
 * **判据形态**：扫**剔除注释后**的 scss（注释里写规则不算落实），且用
 * `[.task-item__tag]` 选择器锚定「精确那一条规则」——`&-text` 是另一条规则，不会被误读成父级。
 * 几何（是否真的还折行）在浏览器里复测，读数记在 PR body；本文件只钉形态。
 */
describe('「数据」页待办标签不折行（issue #6597 缺陷 A）', () => {
  const DASHBOARD_SCSS = path.join(SRC_DIR, 'pages', 'dashboard', 'index', 'index.scss')

  it('标签宽度**自适应**（不再是固定 64px）+ 文案不换行 + 左右留内边距 + 高度仍 40px', () => {
    const scss = scssCode(DASHBOARD_SCSS)
    // 反空跑：真的取到了那条规则（取不到 ⇒ 当场抛，下面几条读数不空转）
    const tag = must(ruleBody(scss, '__tag'), 'src/pages/dashboard/index/index.scss 的 .task-item__tag 规则体')

    // ① 不再是固定宽度（原 `width: 64px` 就是折行的根因）
    expect(tag).not.toMatch(/width:\s*64px/)
    // ② 文案不换行（写在父级或 `&-text` 上都算落实）
    const tagText = ruleBody(scss, '-text')
    expect(`${tag}${tagText}`).toMatch(/white-space:\s*nowrap/)
    // ③ 左右内边距（宽度自适应的「呼吸位」，不许贴边）
    expect(tag).toMatch(/padding:\s*0\s+\d+px/)
    // ④ 高度/视觉对齐既有 40px
    expect(tag).toMatch(/height:\s*40px/)
  })

  it('🔴 宽度自适应**装得下**服务端下发的 3 字标签（按 scss 自己声明的 font-size 复算）', () => {
    const scss = scssCode(DASHBOARD_SCSS)
    const tag = ruleBody(scss, '__tag') ?? ''
    const tagText = ruleBody(scss, '-text') ?? ''
    const fontSize = Number((tagText.match(/font-size:\s*(\d+)px/) ?? [])[1])
    const padLeft = Number((tag.match(/padding:\s*0\s+(\d+)px/) ?? [])[1])
    // 反空跑：两个数都真的读到了
    expect(fontSize).toBeGreaterThan(0)
    expect(padLeft).toBeGreaterThan(0)
    // 「卡在哪」= 3 字；固定宽度时代 = 64px（< 3 × 24 = 72），且**没有** nowrap ⇒ 折行
    expect(padLeft * 2 + fontSize * 3).toBeGreaterThan(64)
    expect(scssCode(DASHBOARD_SCSS)).toMatch(/white-space:\s*nowrap/)
  })
})
