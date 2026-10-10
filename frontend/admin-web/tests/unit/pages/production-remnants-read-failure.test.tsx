// case_ids: PP-010, UI-046, UI-057
/**
 * `/production/remnants`（余料台账）**读面失败**判据（issue #6702）。
 *
 * ## 修前实测（集成侧真机注入 + 本包复算）
 *
 * 注入 `GET /api/admin/production/remnants**` ⇒ 500，屏上同时出现三样东西：
 *
 * | # | 修前读数 | 为什么算缺陷 |
 * |---|---|---|
 * | ① | 「余料台账读取失败（**可能是当前岗位没有「工艺配置」权限**）」 | **误归因**：500 被说成权限问题 ⇒ 商家去找管理员开一个**跟本页无关**的权限（「工艺配置」属算料配置域） |
 * | ② | **「共 0 块」** | 与①**同屏自相矛盾**：一边说读失败、一边断言总数是 0（读不到 ⇒ 计数是**未知**，印 0 是界面在撒谎） |
 * | ③ | `failAnchors: []`（该页 22 个 `data-testid` 无一个 error/fail/retry） | **无失败锚点** ⇒ 类级守卫扫不到，也没有「真重发」的出口 |
 *
 * ## 判据（各自能单独变红，红证写在每条上）
 *
 * - **① 读失败不印零**：注入 500 ⇒ 屏上**不得**出现「共 0 块」，计数位显示 `—`。
 *   修前红证：源码逐字 `共 {data?.page?.total ?? 0} 块`，而 `catch` 里 `setData(null)`
 *   ⇒ `null ?? 0` = 0 ⇒ `getByText(/共\s*0\s*块/)` **取得到** ⇒ 红。
 * - **② 不归因成权限**：注入 500 ⇒ 屏上文案**不得**含「没有…权限」式归因（且不得出现「工艺配置」）。
 *   修前红证：文案逐字含「可能是当前岗位没有「工艺配置」权限」⇒ 红。
 * - **③ 失败锚点 + 重试出口**：`data-testid="remnant-ledger-load-failed"` 存在，且其内有
 *   `data-testid="remnant-ledger-retry"`。修前红证：`queryByTestId(...)` 为 `null` ⇒ 红。
 * - **④ 重试真重发 + 计数恢复**：拆掉注入后点重试 ⇒ `ledger` 被调第二次，且计数行恢复成
 *   **服务端真 total（332）**。修前红证：`load` 只在依赖变化时跑，页面**没有**重试出口
 *   （`getByTestId('remnant-ledger-retry')` 抛错）⇒ 红。
 * - **⑤ 403 才谈权限**：注入 403 ⇒ 文案说**本页**对应的权限域（「生产管理」读码），
 *   且**同样**不印「共 0 块」。反过来：④ 的 500 分支**不得**说权限（两条各自钉死）。
 *
 * ## 与 #6697（分页）的关系
 *
 * 分页控件在本页由 `!loading && !error && total > 0` 门控 ⇒ 失败态下**本就不渲染**
 * （不会出现「共 0 条」那一半）。本文件第 ① 条把这一点**一并钉住**：失败态下
 * `remnant-pagination` 必须取不到。
 *
 * ## 边界（照实登记）
 *
 * - 只测**本页**；类级面在 `tests/unit/lib/read-failure-copy-attribution-guard.test.ts`
 *   （扫描面 = `(dashboard)/**`，**有意让出 `dashboard/`** 给 #6701 的工作台金额面）；
 * - 只 mock `remnantApi` / `orderApi`，**不 mock** `@/components/ui` 的 `Button`
 *   —— 判的必须是真控件（stub 一个假按钮会把「页面没接出口」测成绿）；
 * - 不注入真 HTTP：`remnantApi.ledger` 的 rejection 用 `{ response: { status } }` 形状
 *   （与 `request.ts` 拦截器 reject 的 axios 错误同形）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

const mockLedger = vi.fn()
const mockMatch = vi.fn()
const mockRecover = vi.fn()
const mockScrap = vi.fn()
const mockGetOrders = vi.fn()
const mockGetOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  remnantApi: {
    ledger: (...a: unknown[]) => mockLedger(...a),
    match: (...a: unknown[]) => mockMatch(...a),
    recover: (...a: unknown[]) => mockRecover(...a),
    scrap: (...a: unknown[]) => mockScrap(...a),
  },
  orderApi: {
    getOrders: (...a: unknown[]) => mockGetOrders(...a),
    getOrder: (...a: unknown[]) => mockGetOrder(...a),
  },
}))

// 显式列出本页 + `@/components/ui` 用到的图标（**不要用 Proxy**：实测 vitest 收集阶段会挂死）
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: Record<string, unknown>) =>
    React.createElement('span', { 'data-testid': `icon-${name}`, ...props })
  return {
    AlertCircle: stub('alert-circle'),
    RefreshCw: stub('refresh'),
    Search: stub('search'),
    Loader2: stub('loader-2'),
    ChevronDown: stub('chevron-down'),
    ChevronUp: stub('chevron-up'),
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
    Package: stub('package'),
    FileX: stub('file-x'),
    Inbox: stub('inbox'),
    Upload: stub('upload'),
    File: stub('file'),
    FileText: stub('file-text'),
    Image: stub('image'),
    X: stub('x'),
  }
})

import RemnantLedgerPage from '@/app/(dashboard)/production/remnants/page'

/** 服务端真读数（issue #6702 正文：租户实测 `total = 332`） */
const REAL_TOTAL = 332

const SUMMARY = {
  availableCount: 1,
  availableMeters: 3.2,
  usedCount: 0,
  recoveredMetersTotal: 0,
  scrappedCount: 0,
  scrappedMetersTotal: 0,
  customerTakenCount: 0,
  recoveredAmountTotal: 0,
  issuedCostTotal: 500,
  recoveryRate: null,
  scrapRate: null,
}

function line(id: number) {
  return {
    id,
    lengthM: 1.6,
    widthM: 2,
    areaM2: 3.2,
    pieceKind: 'end',
    sourceOrderNo: `ORD-${id}`,
    sourceBatchNo: 'B-2026-10',
    dyeLot: 'D01',
    status: 'available',
    recoveredAmount: null,
    recoveredMeters: null,
    recoveredUnitCost: null,
    usedByOrderNo: null,
    usedByItemKey: null,
    recoveredBy: null,
    recoveredAt: null,
    scrapReason: null,
    scrappedBy: null,
    scrappedAt: null,
  }
}

function okResponse(size = 20) {
  return {
    data: {
      data: {
        summary: SUMMARY,
        page: { items: Array.from({ length: size }, (_, i) => line(i + 1)), total: REAL_TOTAL, page: 1, size },
      },
    },
  }
}

/** 注入读面失败（形状与 `request.ts` 拦截器 reject 的 axios 错误同形） */
function rejectWithStatus(status: number) {
  return Promise.reject({ response: { status } })
}

/**
 * 等读面 settle（轮询到 `ledger` 真被调用 + 一拍 flush）。
 *
 * ⚠️ 这里**有意不用** `findByTestId` / `waitFor`：本用例在**修前**跑时失败锚点**不存在**，
 * 而 `waitFor` 默认超时 5s ⇒ 红读数会变成「超时」而不是**具名的判据红**
 * （本包实测：5 个用例各超时 5s = 25s，报错与判据无关）。改用「轮询 + 同步断言」⇒
 * 修前每条都在**自己那条判据**上当场红（如 ① 报「`共 0 块` 不该在」）。
 */
async function settle() {
  for (let i = 0; i < 60 && mockLedger.mock.calls.length === 0; i += 1) {
    await new Promise((r) => setTimeout(r, 10))
  }
  await new Promise((r) => setTimeout(r, 30))
}

describe('余料台账 /production/remnants 读面失败（issue #6702）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockMatch.mockResolvedValue({
      data: {
        data: { configured: true, requiredItems: [], recommendations: [], unmatched: [], unconfiguredItems: [] },
      },
    })
    mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    mockGetOrder.mockResolvedValue({ data: { data: null } })
  })

  it('① 读面 500 ⇒ 不得印「共 0 块」，计数位是「—」，分页控件不出现', async () => {
    mockLedger.mockImplementation(() => rejectWithStatus(500))
    render(<RemnantLedgerPage />)
    await settle()

    // 🔴 修前红证（本包实测，先于锚点断言）：`data?.page?.total ?? 0` + catch 里 `setData(null)`
    // ⇒ 屏上逐字「共 0 块」（读不到的时候印 0 = 界面在撒谎）
    expect(screen.queryByText(/共\s*0\s*块/)).not.toBeInTheDocument()
    // 分页控件由 `!error` 门控 ⇒ 失败态下不得出现（也就不会有「共 0 条」那一半）
    expect(screen.queryByTestId('remnant-pagination')).not.toBeInTheDocument()
    // 修后形态：计数位是「—」（未知 ≠ 0），且失败锚点在
    expect(screen.getByText(/共\s*—\s*块/)).toBeInTheDocument()
    expect(screen.getByTestId('remnant-ledger-load-failed')).toBeInTheDocument()
  })

  it('② 读面 500 ⇒ 不得把失败归因成「没有权限」（更不得提「工艺配置」）', async () => {
    mockLedger.mockImplementation(() => rejectWithStatus(500))
    render(<RemnantLedgerPage />)
    await settle()

    // 🔴 修前红证（本包实测，先于锚点断言）：屏上逐字含
    // `余料台账读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试`
    const page = screen.getByTestId('remnant-ledger-page')
    expect(page.textContent ?? '').not.toMatch(/没有[^。，；]*权限/)
    expect(page.textContent ?? '').not.toContain('工艺配置')
    // 真原因（服务侧）必须说出来
    const box = screen.getByTestId('remnant-ledger-load-failed')
    expect(box.textContent ?? '').toMatch(/不可用|读不到|暂时/)
  })

  it('③ 存在失败锚点 + 真重试出口', async () => {
    mockLedger.mockImplementation(() => rejectWithStatus(500))
    render(<RemnantLedgerPage />)
    await settle()

    // 🔴 修前红证（本包实测）：该页 22 个 testid 里一个 error/fail/retry 都没有（`failAnchors: []`）
    const box = screen.getByTestId('remnant-ledger-load-failed')
    expect(within(box).getByTestId('remnant-ledger-retry')).toBeInTheDocument()
  })

  it('④ 放开注入后点重试 ⇒ 真重发，计数行恢复服务端真 total（332）', async () => {
    mockLedger.mockImplementationOnce(() => rejectWithStatus(500))
    render(<RemnantLedgerPage />)
    await settle()
    // 🔴 修前红证（本包实测）：没有重试出口 ⇒ 下面 `getByTestId('remnant-ledger-retry')` 抛错
    //（修前屏上连失败锚点都没有：`failAnchors: []`）
    expect(mockLedger).toHaveBeenCalledTimes(1)

    // 「放开注入」= 让下一次请求成功
    mockLedger.mockImplementation(() => Promise.resolve(okResponse()))
    fireEvent.click(screen.getByTestId('remnant-ledger-retry'))

    // 真重发（不是只把文案抹掉）
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(2))
    // 计数行恢复成**服务端真 total**（332），不是「—」也不是 0
    await waitFor(() => expect(screen.getByText(new RegExp(`共\\s*${REAL_TOTAL}\\s*块`))).toBeInTheDocument())
    expect(screen.queryByTestId('remnant-ledger-load-failed')).not.toBeInTheDocument()
    // 真实 total ⇒ 分页控件回来了（证明「失败态不渲染分页」不是靠永久隐藏做到绿的）
    expect(screen.getByTestId('remnant-pagination')).toBeInTheDocument()
  })

  it('⑤ 403 才谈权限：说本页对应的权限域，且同样不印「共 0 块」', async () => {
    mockLedger.mockImplementation(() => rejectWithStatus(403))
    render(<RemnantLedgerPage />)
    await settle()
    // 🔴 修前红证（本包实测）：修前屏上逐字是「可能是当前岗位没有「工艺配置」权限」
    //（500 与 403 共用同一条文案）⇒ 下一条 `not.toContain('工艺配置')` 当场红
    const box = screen.getByTestId('remnant-ledger-load-failed')
    expect(box.textContent ?? '').toMatch(/权限/)
    // 🔴 反例钉死：不得提与本页无关的「工艺配置」（那是算料配置域的菜单）
    expect(box.textContent ?? '').not.toContain('工艺配置')
    expect(screen.queryByText(/共\s*0\s*块/)).not.toBeInTheDocument()
    expect(screen.getByText(/共\s*—\s*块/)).toBeInTheDocument()
  })
})
