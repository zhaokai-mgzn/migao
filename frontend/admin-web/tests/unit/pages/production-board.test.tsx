// case_ids: PP-014, PG-024, PG-036
//
// PP-014（issue #4307 前端半边）：菜单组第 4 项「工艺路线」—— 页面存在但侧边栏进不去等于没交付；
//   本文件的链接清单 + 权限码断言随加项由三项改四项（红证：加项后旧断言即红）。
// PG-024（issue #4303，**长期判据 = 加载竞态**）：列表请求时序保护 —— 先发出的慢请求晚到，
//   其响应必须被丢弃，列表不得回退成旧数据。⚠️ 本文件是该保护的**迁移落点**：
//   PG-036 把加工单列表页并入生产看板后，搜索/筛选/刷新全由看板承担 ⇒ 竞态保护必须随代码一起搬
//   （留在被合并掉的页面里 = 保护随页面一起消失）。
// PG-036（issue #4357）：加工单菜单并入生产管理组，且与生产看板**合并为单一入口** ——
//   ① 侧边栏：订单管理组 = 订单列表 / 售后工单（**不含**加工单）；生产管理组 4 项不变；
//   ② /production 吸收加工单列表页的**全部**既有能力：关键词/状态筛选、重置、刷新、
//      商品与数量快照摘要、「查看」跳订单详情（**合并 ≠ 丢能力**）；
//   ③ 保留 #4305 入口收敛：发加工/开始加工/加工完成/取消 四个按钮**仍不渲染**。
// issue #4360（分页 + 懒加载）：看板原先对**全部**加工单一次性扇出详情
//   （1 + 2N 次 HTTP，100 单 = 201 请求）——本文件的请求数断言即该缺陷的红证锚点：
//   ① 首屏只为当前页（默认 20）发详情请求；② 切页只为新页发；③ 切回已加载页不重复发；
//   ④ 「刷新」显式清缓存并重取当前页。判据是**调用次数**，不是渲染结果（渲染不出请求扇出）。
// 反 placeholder：看板断言必须落到真实数据行，不能只断言页面存在。
//
// ⚠️ case_ids 更正（issue #4357）：本文件此前声明 `PG-019`，但 PG-019 是**后端**用例
//   （存量加工单恢复路径，traces 全是 Java 测试，见 .github/cases/processing-order.yml），
//   与本文件断言无关 ⇒ 已移除该误引用。issue #4360 的分页/懒加载断言目前**没有**对应用例 ID
//   （如实登记，本单不改其断言实质）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockList = vi.fn()
const mockGetOrderOperations = vi.fn()
const mockGetPiecework = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    list: (...args: unknown[]) => mockList(...args),
  },
  productionApi: {
    getOrderOperations: (...args: unknown[]) => mockGetOrderOperations(...args),
    getPiecework: (...args: unknown[]) => mockGetPiecework(...args),
  },
  briefingApi: {
    getConfig: vi.fn().mockResolvedValue({ data: { data: { enabled: false } } }),
  },
}))

// 侧边栏测试：模拟已登录的管理员（全权限）
vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
  }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// 「查看」跳订单详情需要拿到 push 的实参（全局 setup 的 mock 每次返回新 vi.fn()，断言不到）
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/production',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
}))

vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import ProductionBoardPage from '@/app/(dashboard)/production/page'
import Sidebar from '@/components/layout/Sidebar'
import { menuGroups } from '@/config/menu'
import type { ProcessingOrder } from '@/types'

const ORDERS: ProcessingOrder[] = [
  {
    id: 'po-1',
    orderId: 'order-uuid-1',
    orderNo: 'MG20260917001',
    processingOrderNo: 'JG-20260917-0001',
    customerName: '李四',
    status: 'in_processing',
    items: [{ productName: '布帘', colorName: '米白', quantity: 3, unit: '米' }],
  },
  {
    id: 'po-2',
    orderId: 'order-uuid-2',
    orderNo: 'MG20260917002',
    processingOrderNo: 'JG-20260917-0002',
    customerName: '王五',
    status: 'generated',
    items: [{ productName: '纱帘', colorName: '纯白', quantity: 2, unit: '米' }],
  },
]

const ok = (data: unknown) => ({ data: { success: true, data } })

// 100 张加工单：请求扇出缺陷的**最小可判规模**（100 单 = 200 次详情请求）
const MANY_ORDERS = Array.from({ length: 100 }, (_, i) => ({
  id: `po-${i + 1}`,
  orderId: `order-uuid-${i + 1}`,
  orderNo: `MG20260917${String(i + 1).padStart(3, '0')}`,
  processingOrderNo: `JG-20260917-${String(i + 1).padStart(4, '0')}`,
  customerName: `客户${i + 1}`,
  status: 'in_processing' as const,
}))

/** 可手动控制 resolve 时机的 promise（模拟「在飞的慢请求」，PG-024） */
function deferred() {
  let resolve!: (value: unknown) => void
  const promise = new Promise<unknown>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

/** 看板表格的**可见文案**（状态文案是用户可见文本） */
const tableText = () => screen.getByRole('table').textContent ?? ''
/** 状态筛选下拉：用 aria-label 定位（页脚分页也有一个 combobox，裸 getByRole 会命中两个） */
const statusSelect = () => screen.getByRole('combobox', { name: '状态筛选' })

describe('生产管理菜单入口（侧边栏）', () => {
  it('侧边栏出现「生产管理」组与四个节点，路径与权限码正确', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    const group = screen.getByText('生产管理').closest('.mb-4') as HTMLElement
    expect(group).toBeTruthy()
    const links = group.querySelectorAll('a')
    // 4 项：生产看板 / 工序库 / 工艺路线（issue #4307 新增）/ 计件工资
    expect(links).toHaveLength(4)
    expect(links[0].textContent).toContain('生产看板')
    expect(links[0]).toHaveAttribute('href', '/production')
    expect(links[1].textContent).toContain('工序库')
    expect(links[1]).toHaveAttribute('href', '/production/operations')
    expect(links[2].textContent).toContain('工艺路线')
    expect(links[2]).toHaveAttribute('href', '/production/routings')
    expect(links[3].textContent).toContain('计件工资')
    expect(links[3]).toHaveAttribute('href', '/production/piecework')
  })

  it('「加工单」不再是独立菜单项：订单管理组只余订单列表/售后工单（issue #4357）', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    // 订单管理组：加工单已并入生产管理组（issue #4357 —— 与生产看板合并为单一入口）
    const tradeGroup = screen.getByText('订单管理').closest('.mb-4') as HTMLElement
    expect(within(tradeGroup).queryByText('加工单')).not.toBeInTheDocument()
    expect(within(tradeGroup).getByText('订单列表')).toBeInTheDocument()
    expect(within(tradeGroup).getByText('售后工单')).toBeInTheDocument()
    expect(tradeGroup.querySelectorAll('a')).toHaveLength(2)

    // 全站不再有指向 /processing-orders 的菜单项（旧入口收敛到 /production）
    const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).not.toContain('/processing-orders')
  })

  it('权限码口径一致：生产管理组四项统一 processing:manage（与既有 menu.ts 口径一致）', () => {
    const group = menuGroups.find((g) => g.key === 'production')
    expect(group).toBeTruthy()
    expect(group!.children.map((c) => c.permissionCode)).toEqual([
      'processing:manage',
      'processing:manage',
      'processing:manage',
      'processing:manage',
    ])
  })
})

describe('生产看板页 /production（加工单唯一入口，PG-036）', () => {
  beforeEach(() => {
    mockPush.mockReset()
    mockList.mockReset().mockResolvedValue(ok(ORDERS))
    mockGetOrderOperations.mockReset().mockImplementation((orderId: string) =>
      Promise.resolve(
        ok(
          orderId === 'order-uuid-1'
            ? { positions: [{ position_name: '布帘', operations: [] }], progress: { total: 11, done: 4, percent: 36 } }
            : { positions: [], progress: { total: 0, done: 0, percent: 0 } },
        ),
      ),
    )
    mockGetPiecework.mockReset().mockImplementation((orderId: string) =>
      Promise.resolve(ok(orderId === 'order-uuid-1' ? { total: 17, per_worker: {}, per_operation: [] } : { total: 0 })),
    )
  })

  it('渲染真实数据：≥1 行加工单 + 每单工序进度 + 计件合计', async () => {
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    // 两行都渲染（不是空壳）
    expect(screen.getAllByTestId(/^production-row-po-/)).toHaveLength(2)
    expect(screen.getByTestId('production-row-po-1')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('production-row-po-1')).toHaveTextContent('MG20260917001')
    // 每单工序进度（issue #4360：详情懒加载 ⇒ 行先渲染，进度/计件随后异步补齐）
    await waitFor(() => expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('36%'))
    expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('4/11')
    expect(screen.getByTestId('production-row-progress-po-2')).toHaveTextContent('0%')
    // 每单计件合计
    await waitFor(() => expect(screen.getByTestId('production-row-piecework-po-1')).toHaveTextContent('¥17.00'))
    expect(screen.getByTestId('production-row-piecework-po-2')).toHaveTextContent('¥0.00')
  })

  it('按加工单上的 orderId 拉工序进度与计件（复用既有端点）', async () => {
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())
    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-1')
    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-2')
    expect(mockGetPiecework).toHaveBeenCalledWith('order-uuid-1')
  })

  it('无加工单：空态提示，不报错', async () => {
    mockList.mockResolvedValue(ok([]))
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-board-empty')).toBeInTheDocument())
  })

  it('列表失败：错误提示 + 重试按钮', async () => {
    mockList.mockRejectedValueOnce(new Error('boom'))
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-board-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-board-retry')).toBeInTheDocument()
  })

  // ── 合并能力（PG-036）：加工单列表页并入后，下列能力一条都不能丢 ──

  it('合并能力①关键词搜索：按单号筛选后**列表内容随之变化**（结果可见，非只断言 API 被调用）', async () => {
    mockList.mockResolvedValueOnce(ok(ORDERS)).mockResolvedValueOnce(ok([ORDERS[1]]))
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('请输入加工单号或订单号'), 'JG-20260917-0002{Enter}')

    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({ keyword: 'JG-20260917-0002', status: undefined }),
    )
    // 结果可见：被筛掉的行消失、命中的行留下
    await waitFor(() => expect(screen.queryByTestId('production-row-po-1')).not.toBeInTheDocument())
    expect(screen.getByTestId('production-row-po-2')).toBeInTheDocument()
  })

  it('合并能力②状态筛选：选「已发加工」后按 status 重新拉取', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(statusSelect(), 'issued')
    await user.click(screen.getByRole('button', { name: /查询/ }))

    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ keyword: undefined, status: 'issued' }))
  })

  it('合并能力③重置：清空关键词与状态并恢复全量列表', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const user = userEvent.setup()
    const keyword = screen.getByPlaceholderText('请输入加工单号或订单号')
    await user.type(keyword, 'JG-2026')
    await user.selectOptions(statusSelect(), 'issued')
    // 先真的提交一次筛选（否则「重置」后仍与首屏那次调用同参 ⇒ 断言会**平凡通过**）
    await user.click(screen.getByRole('button', { name: /查询/ }))
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ keyword: 'JG-2026', status: 'issued' }))

    await user.click(screen.getByRole('button', { name: /重置/ }))

    // 输入框被清空（用户可见）+ 以空筛选重新拉取（与上一次调用**不同**）
    await waitFor(() => expect(keyword).toHaveValue(''))
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ keyword: undefined, status: undefined }))
  })

  it('合并能力④刷新：重新拉取列表', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())
    const before = mockList.mock.calls.length

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /刷新/ }))

    await waitFor(() => expect(mockList.mock.calls.length).toBeGreaterThan(before))
  })

  it('合并能力⑤商品与数量：快照明细摘要可见（原列表页独有列）', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    expect(screen.getByTestId('production-row-po-1')).toHaveTextContent('布帘（米白）× 3米')
    expect(screen.getByTestId('production-row-po-2')).toHaveTextContent('纱帘（纯白）× 2米')
  })

  it('合并能力⑥查看：跳对应订单详情（订单详情已含加工单块，issue #4305）', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const user = userEvent.setup()
    const row = screen.getByTestId('production-row-po-1')
    await user.click(within(row).getByRole('button', { name: '查看' }))

    expect(mockPush).toHaveBeenCalledWith('/orders/order-uuid-1')
  })

  it('生产明细：跳 /processing-orders/{加工单号}/production（子路由未随菜单移除）', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const user = userEvent.setup()
    const row = screen.getByTestId('production-row-po-1')
    await user.click(within(row).getByRole('button', { name: '生产明细' }))

    expect(mockPush).toHaveBeenCalledWith('/processing-orders/JG-20260917-0001/production')
  })

  it('入口收敛不回归（issue #4305）：四个状态流转按钮仍不渲染 + 引导文案可见', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    for (const label of ['发加工', '开始加工', '加工完成', '取消加工单']) {
      expect(screen.queryByRole('button', { name: label })).toBeNull()
    }
    expect(tableText()).toContain('状态流转请在订单详情操作')
  })

  it('PG-024 时序保护：旧的在飞列表响应晚 resolve，不得把看板覆盖回旧数据', async () => {
    const oldSlow = deferred() // 先发出的慢请求（旧数据快照）
    const fresh = deferred() // 后发出的快请求（新数据）
    mockList
      .mockResolvedValueOnce(ok(ORDERS)) // #1 首屏
      .mockReturnValueOnce(oldSlow.promise) // #2 慢（旧）
      .mockReturnValueOnce(fresh.promise) // #3 快（新）

    render(<ProductionBoardPage />)
    await waitFor(() => expect(tableText()).toContain('加工中'))

    const user = userEvent.setup()
    const keyword = screen.getByPlaceholderText('请输入加工单号或订单号')
    await user.type(keyword, 'JG-20260917{Enter}')
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
    await user.clear(keyword)
    await user.type(keyword, 'MG20260917{Enter}')
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(3))

    // 新请求先回来：看板 = 新数据
    const NEW = [{ ...ORDERS[0], status: 'completed' as const }]
    await act(async () => {
      fresh.resolve(ok(NEW))
    })
    await waitFor(() => expect(tableText()).toContain('加工完成'))

    // 旧请求晚到（issue #4303 的 4174ms 形态）：**不得**覆盖已渲染的新数据
    await act(async () => {
      oldSlow.resolve(ok(ORDERS))
    })

    expect(tableText()).toContain('加工完成')
    expect(tableText()).not.toContain('加工中')
  })
})

// ── issue #4360：请求扇出 ⇒ 分页 + 懒加载（判据 = HTTP 调用次数）──────────────
describe('生产看板页 /production 分页 + 懒加载（issue #4360）', () => {
  const PAGE_SIZE = 20
  const detailCalls = () => mockGetOrderOperations.mock.calls.length
  const rowCount = () => screen.getAllByTestId(/^production-row-po-/).length
  // 等「当前页详情都发完」：最后一次调用的 orderId 是页内第 N 条（默认 20）
  const waitPageLoaded = (last: number) =>
    waitFor(() => expect(mockGetOrderOperations).toHaveBeenCalledWith(`order-uuid-${last}`))
  /** 页脚分页的「每页条数」下拉：用 aria-label 定位（查询区也有一个 combobox，裸 getByRole 会命中两个） */
  const pageSizeSelect = () => screen.getByRole('combobox', { name: '每页条数' })

  beforeEach(() => {
    mockList.mockReset().mockResolvedValue(ok(MANY_ORDERS))
    mockGetOrderOperations.mockReset().mockImplementation((orderId: string) =>
      Promise.resolve(ok({ positions: [], progress: { total: 10, done: 3, percent: 30 } })),
    )
    mockGetPiecework.mockReset().mockImplementation((orderId: string) => Promise.resolve(ok({ total: 17 })))
  })

  it('100 张单首屏：只为当前页（20）发详情，不对 100 行扇出', async () => {
    render(<ProductionBoardPage />)

    await waitPageLoaded(PAGE_SIZE)
    expect(rowCount()).toBe(PAGE_SIZE)
    // 缺陷形态是 100 次（每单 1 次）；修复后 ≤ 页大小
    expect(detailCalls()).toBeLessThanOrEqual(PAGE_SIZE)
    expect(mockGetPiecework.mock.calls.length).toBeLessThanOrEqual(PAGE_SIZE)
    expect(detailCalls()).toBe(PAGE_SIZE)
    expect(mockGetOrderOperations).not.toHaveBeenCalledWith(`order-uuid-${PAGE_SIZE + 1}`)
  })

  it('切到第 2 页：只为第 2 页发详情（累计 = 2 × 页大小）', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)

    await user.click(screen.getByRole('button', { name: '2' }))

    await waitPageLoaded(PAGE_SIZE * 2)
    expect(detailCalls()).toBe(2 * PAGE_SIZE)
    expect(mockGetPiecework.mock.calls.length).toBe(2 * PAGE_SIZE)
    expect(rowCount()).toBe(PAGE_SIZE)
    expect(screen.getByTestId(`production-row-po-${PAGE_SIZE + 1}`)).toBeInTheDocument()
  })

  it('切回第 1 页：命中缓存，不重复请求', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)
    await user.click(screen.getByRole('button', { name: '2' }))
    await waitPageLoaded(PAGE_SIZE * 2)
    const before = detailCalls()

    await user.click(screen.getByRole('button', { name: '1' }))

    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())
    expect(detailCalls()).toBe(before)
    expect(mockGetPiecework.mock.calls.length).toBe(before)
  })

  it('点「刷新」：清缓存并重新请求当前页', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)
    await user.click(screen.getByRole('button', { name: '2' }))
    await waitPageLoaded(PAGE_SIZE * 2)
    const before = detailCalls()

    await user.click(screen.getByRole('button', { name: /刷新/ }))

    await waitFor(() => expect(detailCalls()).toBe(before + PAGE_SIZE))
    expect(mockGetPiecework.mock.calls.length).toBe(before + PAGE_SIZE)
  })

  it('页大小可见可切：20 → 50 只为新页补发详情', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)

    await user.selectOptions(pageSizeSelect(), '50')

    await waitPageLoaded(50)
    expect(detailCalls()).toBe(50)
    expect(rowCount()).toBe(50)
    expect(pageSizeSelect()).toHaveValue('50')
  })

  // ── issue #4372：失败行的缓存语义（把"真实"行为钉住，防被"照注释修正"成死循环）──
  //
  // 为什么必须钉：`page.tsx` 里 `if (d.status === 'fulfilled')` 只是 **TS 类型收窄**，
  // 内层 `allSettled` 让 mapper 永不 reject ⇒ **失败行同样进缓存、本会话不重试**。
  // 若有人把它读成「失败不写缓存」并照此改实现，`pending` 会**永不收敛** ⇒
  // 每次 `setRows(prev.map(...))` 产生新数组 ⇒ effect（依赖 `[rows,…]`）反复触发
  // ⇒ **无限请求循环**。本条断言即该陷阱的红线：改坏即红。
  it('详情永久失败的行：仍进缓存 ⇒ 切页来回不重发（防"失败不写缓存"改成死循环）', async () => {
    const user = userEvent.setup()
    // 仅 order-uuid-1 的**两个**详情接口都永久失败，其余正常
    mockGetOrderOperations.mockImplementation((orderId: string) =>
      orderId === 'order-uuid-1'
        ? Promise.reject(new Error('boom'))
        : Promise.resolve(ok({ positions: [], progress: { total: 10, done: 3, percent: 30 } })),
    )
    mockGetPiecework.mockImplementation((orderId: string) =>
      orderId === 'order-uuid-1' ? Promise.reject(new Error('boom')) : Promise.resolve(ok({ total: 17 })),
    )
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)

    // 该行保持「—」形态（计件 ¥0.00、进度 0%），且不拖垮其它行
    expect(screen.getByTestId('production-row-piecework-po-1')).toHaveTextContent('¥0.00')
    expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('0%')
    expect(screen.getByTestId('production-row-piecework-po-2')).toHaveTextContent('¥17.00')
    const failedCalls = () => mockGetOrderOperations.mock.calls.filter((c) => c[0] === 'order-uuid-1').length
    expect(failedCalls()).toBe(1)

    await user.click(screen.getByRole('button', { name: '2' }))
    await waitPageLoaded(PAGE_SIZE * 2)
    await user.click(screen.getByRole('button', { name: '1' }))
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    // 关键判据：失败行**没有**被重发（= 已进缓存）。改成"失败不写缓存" ⇒ 这里变 2 ⇒ 红。
    expect(failedCalls()).toBe(1)
    expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument()
  })
})
