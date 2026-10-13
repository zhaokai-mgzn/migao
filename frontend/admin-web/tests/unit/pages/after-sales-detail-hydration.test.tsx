// case_ids: UI-097
// 实例判据（issue #6799 ①）：售后详情页 `/after-sales/[id]` 的 SSR→hydrate **不得**出现
// 「块级元素落在 `<p>` 里」（React 的 `validateDOMNesting`）。
//
// ## 真栈读数（修前，`scripts/ui-smoke-merchant/spec.mjs` 的 `19-after-sales-detail`，逐字）
//
//   [console.error] In HTML, %s cannot be a descendant of <%s>.
//   This will cause a hydration error.%s <div> p
//      ... <RedirectBoundary> <RedirectErrorBoundary router={{...}}>
//          <InnerLayoutRouter url="/after-sal..." …>
//   [console.error] <%s> cannot contain a nested %s.
//   See this log for the ancestor stack trace. p <div>
//
// ## 根因（怎么定位到的）
// React 只报形状（`<div>` 落在 `<p>` 里），不报宿主组件 ⇒ 先按"字面 JSX 嵌套"扫全树
// （`scripts/jsx-p-tag-nesting-scan.mjs`）：**0 命中** ⇒ 违规是**运行期组合**。
// 本页 `<p>` 里的子节点只有三处是"被引用组件"：`components/common/DateTimeCell`
// （根节点 `<div>`，两行 YYYY-MM-DD / HH:mm）挂在两个 `<p>` 里 ⇒ 命中；其余 `<p>` 的子节点都是短语内容。
// 实例读数的收敛判据就是下面这条：**服务端渲染出的 HTML 里不得有 `<p …><div …>`**。
//
// ## 判据为什么能红/能绿
// - 红（修前）：`vendorHtml(SSR)` 里出现 `<p class="text-sm font-medium…"><div class="text-sm…">`
//   ⇒ `expect(serverHtml).not.toMatch(P_IN_BLOCK)` 失败；
// - 绿（修后）：两处容器换成 `<div>` ⇒ 不再出现该形态，且 hydrate 的 `console.error` 里
//   **没有**这一族（`isNestingError` 逐条判定，不按总条数）。
// 判别力自证在 `frontend/admin-web/tests/unit/p-tag-block-nesting-guard.test.ts` 与
// `frontend/admin-web/tests/unit/hydration-witness-guard.test.tsx`（对注入的坏形态判红）。

import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { writeFileSync } from 'node:fs'

const mockGetTicket = vi.hoisted(() => vi.fn())
const mockUpdateTicketStatus = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api', () => ({
  afterSalesApi: {
    getTicket: (...args: unknown[]) => mockGetTicket(...args),
    updateTicketStatus: (...args: unknown[]) => mockUpdateTicketStatus(...args),
  },
}))

const mockPush = vi.hoisted(() => vi.fn())
vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'ticket-001' }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/after-sales/ticket-001',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: 'ticket-001' }),
  redirect: vi.fn(),
}))

// 权限：默认给全（本判据只管 DOM 形状，不管入口显隐 —— 那是 after-sales-detail.test.tsx 的事）
const authMock = vi.hoisted(() => ({
  state: { user: { id: '1', username: 'u', name: 'u', permissions: ['after_sales:view', 'order:list'], roles: [] as string[] } },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (state: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

import AfterSalesDetailPage from '@/app/(dashboard)/after-sales/[id]/AfterSalesDetail'
import { witnessHydration, isNestingError } from '../helpers/hydration-witness'

/**
 * 「块级元素直接落在 `<p>` 里」的字面形态（服务端 HTML 上判）。
 * 覆盖 `<p>` → 直接子元素是块级标签的形态（本页相关的是 `div`；列表一并收进来，
 * 因为后续谁把 `<ul>` / `<table>` 塞进来是同一族）。
 */
const P_WITH_BLOCK_CHILD = /<p\b[^>]*>\s*<(div|section|article|aside|nav|header|footer|main|form|fieldset|ul|ol|li|dl|dt|dd|table|thead|tbody|tfoot|tr|td|th|h[1-6]|pre|blockquote|hr|figure|address|details)\b/

const ticket = {
  id: 'ticket-001',
  ticketNo: 'AS202606001',
  ticketType: 'refund',
  status: 'pending',
  priority: 'normal',
  description: '测试售后描述',
  orderId: 'order-001',
  orderNo: 'MG202606001',
  customerName: '测试客户',
  customerPhone: '13800138000',
  createdAt: '2026-06-20T10:00:00Z',
  deadline: '2026-06-22T10:00:00Z',
  updatedAt: '2026-06-20T11:00:00Z',
  assignedAt: '2026-06-20T10:30:00Z',
  statusHistory: [
    { status: 'pending', time: '2026-06-20T10:00:00Z', operator: '系统', remark: '客户提交售后申请' },
  ],
}

describe('售后详情页 hydration 形状（issue #6799 ①）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetTicket.mockResolvedValue({ data: { data: ticket } })
    mockUpdateTicketStatus.mockResolvedValue({ data: { success: true } })
  })

  it('服务端渲染的 HTML 里不得出现「块级直接落在 <p> 里」（DateTimeCell 是 <div> 根）', async () => {
    const page = <AfterSalesDetailPage />
    const { serverHtml, nestingErrors, container } = witnessHydration(page)

    // ① 形状面（会红的那一条）：服务端 HTML 里 `<p>` 的直接子元素不得是块级
    expect(P_WITH_BLOCK_CHILD.test(serverHtml), `SSR HTML 里出现块级落在 <p> 里：\n${serverHtml.slice(0, 2000)}`).toBe(false)

    // ② 运行期面：hydrate 不得报这一族（React 的 validateDOMNesting / Hydration failed）
    expect(nestingErrors, `hydrate 报了 DOM 嵌套错误：\n${nestingErrors.join('\n---\n')}`).toEqual([])

    // 落一份 SSR HTML 供**真浏览器读图**（issue #6799 的多模态验收）：真栈 `next dev` 在本机
    // 当前环境下 HTTP 层无响应（已如实登记），改用"真浏览器解析/渲染同一份 SSR HTML"这条路径，
    // 见 PR body 的读数与边界说明。
    writeFileSync('/tmp/6799-ssr-after-sales-detail.html', serverHtml)

    // ③ 负控（判据不是恒真）：这一版 DOM 里必须真有**日期内容**（否则"没报错"可能只是什么都没渲染）。
    //    SSR 出的是 loading 壳（useEffect 不在服务端跑）⇒ 数据在 hydrate 后的 effect 里落下；
    //    注意读**当场**的 DOM（`container.innerHTML`），不是解构出来的快照字符串。
    await waitFor(() => expect(container.innerHTML).toMatch(/2026-06-20/))
    container.remove()
  })

  it('客户端挂载后 DOM 里同样没有「块级落在 <p> 里」（补 JS 面：数据加载完的重渲染）', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => expect(screen.getByText('工单详情')).toBeInTheDocument())
    // 等 DateTimeCell 真渲染出日期（两行 div），确认我们判的是**有内容**的那一版
    await waitFor(() => expect(screen.getAllByText('2026-06-20').length).toBeGreaterThan(0))

    const illegal = Array.from(document.querySelectorAll('p')).filter((p) =>
      Array.from(p.children).some((child) => /^(DIV|SECTION|UL|OL|TABLE|H[1-6]|FORM|PRE)$/.test(child.tagName)),
    )
    expect(illegal.map((p) => p.outerHTML.slice(0, 200))).toEqual([])
  })

  it('判别力自证：见证器对注入的坏形态判红、对好形态不报（同一条判据的对照读数）', async () => {
    const { BadNestingProbe, GoodNestingProbe } = await import('../helpers/hydration-witness')
    const bad = witnessHydration(<BadNestingProbe />)
    expect(bad.nestingErrors.length, '坏形态必须判红 —— 否则本判据是空断言').toBeGreaterThan(0)
    expect(bad.nestingErrors.some(isNestingError)).toBe(true)

    const good = witnessHydration(<GoodNestingProbe />)
    expect(good.nestingErrors).toEqual([])
  })
})
