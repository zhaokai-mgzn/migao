// case_ids: PP-014, PG-024, PG-038, PG-041, PR-106, PG-021
//
// PP-014（issue #4307 前端半边）：菜单组第 4 项「工艺路线」—— 页面存在但侧边栏进不去等于没交付；
//   本文件的链接清单 + 权限码断言随加项改判（红证：加项后旧断言即红）。
//   issue #5034（V111）再加一项「入库单」（/inbound-orders，权限码 inbound:view）⇒ 三项 → 四项。
// PG-024（issue #4303，**长期判据 = 加载竞态**）：列表请求时序保护 —— 先发出的慢请求晚到，
//   其响应必须被丢弃，列表不得回退成旧数据。⚠️ 本文件是该保护的**迁移落点**：
//   PG-038 把加工单列表页并入生产看板后，搜索/筛选/刷新全由看板承担 ⇒ 竞态保护必须随代码一起搬
//   （留在被合并掉的页面里 = 保护随页面一起消失）。
// PG-038（issue #4357）：加工单菜单并入生产管理组，且与生产看板**合并为单一入口** ——
//   ① 侧边栏：订单管理组 = 订单列表 / 售后工单（**不含**加工单）；生产管理组 = 生产看板 / 工艺配置 /
//      计件工资（issue #4490 规格修订后回到 3 项 —— 「加工项管理」归**商品管理**组）；
//   ② /production 吸收加工单列表页的**全部**既有能力：关键词/状态筛选、重置、刷新、
//      商品与数量快照摘要、「查看」跳订单详情（**合并 ≠ 丢能力**）；
//   ③ 保留 #4305 入口收敛：发加工/开始加工/加工完成/取消 四个按钮**仍不渲染**。
// PG-041（issue #4360，分页 + 懒加载）：看板原先对**全部**加工单一次性扇出详情
//   （1 + 2N 次 HTTP，100 单 = 201 请求）——本文件的请求数断言即该缺陷的红证锚点：
//   ① 首屏只为当前页（默认 20）发详情请求；② 切页只为新页发；③ 切回已加载页不重复发；
//   ④ 「刷新」显式清缓存并重取当前页。判据是**调用次数**，不是渲染结果（渲染不出请求扇出）。
// 反 placeholder：看板断言必须落到真实数据行，不能只断言页面存在。
//
// ⚠️ case_ids 更正（issue #4357）：本文件此前声明 `PG-019`，但 PG-019 是**后端**用例
//   （存量加工单恢复路径，traces 全是 Java 测试，见 .github/cases/processing-order.yml），
//   与本文件断言无关 ⇒ 已移除该误引用。
// ⚠️ case_ids 补齐（issue #4431 B6）：#4360 的分页/懒加载断言当时**没有**对应用例 ID
//   （如实登记在本行上方）⇒ 本 PR 新增 **PG-041** 承载该行为（判据 = HTTP 调用次数），
//   并在此声明。用例 ID 与断言一一对应，不再是"断言无处挂载"。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, act, fireEvent } from '@testing-library/react'
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

// 登录态（issue #5913）：**必须按 zustand 选择器返回** —— 看板新增的「订单详情」入口按 `order:list`
// 显隐（`usePermission()` → `useAuthStore(s => s.user)`），而原 mock 无视入参、恒返回整份 state
// ⇒ 选择器拿到的 `user` 是 undefined ⇒ `has()` 恒 false ⇒ 该入口在**所有**用例里都不渲染
// （显隐判据退化成「永远不显示」= 恒真断言）。权限可按用例改写，默认仍为管理员（全权限）。
const authMock = vi.hoisted(() => ({
  state: {
    user: {
      id: '1',
      username: 'admin',
      name: '管理员',
      permissions: ['*'] as string[],
      roles: ['admin'] as string[],
    },
  },
}))
vi.mock('@/store/auth', () => ({
  // Sidebar 用无参形态（`useAuthStore()` 取整份 state），usePermission 用选择器形态 —— 两种都要支持
  useAuthStore: (selector?: (state: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
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
  /** 展开指定组（issue #5271：分组默认只展开当前路由所在组 = /production ⇒ 生产管理组） */
  const expandGroup = (key: string) => {
    const btn = screen.getByTestId(`sidebar-group-toggle-${key}`)
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }

  it('侧边栏出现「生产管理」组与**四个**节点，路径与权限码正确', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    const group = screen.getByText('生产管理').closest('[data-group-key]') as HTMLElement
    expect(group).toBeTruthy()
    const links = group.querySelectorAll('a')
    // issue #5271 重排后本组**由 7 项降到 4 项**：只留「加工执行 + 工艺配置 + 结算」。
    // 拆出去的是面料进出与消耗三项（入库单 / 余料台账 / 省料看板）⇒ 新组「仓储与物料」。
    // ⚠️ issue #4416 把原第 2 项「工序库」与第 3 项「工艺路线」合并为「工艺配置」⇒ 项数 5 → 4；
    //    issue #4490（含同日**规格修订**）把「加工费管理」与「加工项管理」合并为单一入口
    //    （#4542 起菜单名 =「加工项管理」）；
    //    issue #5034 / #5177 / #5159 / #5191 先后往本组加过 4 项，**#5271 把它们中的 3 项搬走**。
    // 🔴 #5778（用户裁定「加工项应该属于生产管理」）：加工项管理自「商品与加工项」组**移入本组**
    //    ⇒ 4 → **5 项**（位次 = 智能派单之后、工艺配置之前）。
    expect(links).toHaveLength(5)
    expect(links[0].textContent).toContain('生产看板')
    expect(links[0]).toHaveAttribute('href', '/production')
    expect(links[1].textContent).toContain('智能派单')
    expect(links[1]).toHaveAttribute('href', '/production/pool')
    expect(links[2].textContent).toContain('加工项管理')
    expect(links[2]).toHaveAttribute('href', '/production/processing')
    expect(links[3].textContent).toContain('工艺配置')
    expect(links[3]).toHaveAttribute('href', '/production/routings')
    expect(links[4].textContent).toContain('计件工资')
    expect(links[4]).toHaveAttribute('href', '/production/piecework')
    // 旧「工序库」入口不再作为独立菜单项（页面改为重定向，旧深链仍可达）
    expect(Array.from(links).map((a) => a.textContent).join('|')).not.toContain('工序库')
    // #5778：合并项**现在就在本组**（归生产管理组；它的结构/图标断言在 processing-merged.test.tsx）
    expect(Array.from(links).map((a) => a.textContent).join('|')).toContain('加工项管理')
    // issue #5271：面料三项也不在本组（移入「仓储与物料」组）
    const productionText = Array.from(links).map((a) => a.textContent).join('|')
    expect(productionText).not.toContain('入库单')
    expect(productionText).not.toContain('余料台账')
    expect(productionText).not.toContain('省料看板')
  })

  it('面料三项落在「仓储与物料」组（issue #5271 新组），点得到且 href 正确', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(screen.getByText('仓储与物料')).toBeInTheDocument()
    // 当前路由是 /production ⇒ 该组默认收起，先展开再断言（断言强度不变）
    expandGroup('inventory-center')
    const group = screen.getByText('仓储与物料').closest('[data-group-key]') as HTMLElement
    const links = group.querySelectorAll('a')
    // #5939：本组 3 → 4 项（+「发货单」`/shipments`，与「入库单」上下相邻）
    // #6404：本组 4 → 5 项（+「库存明细」`/stock-ledger`）
    expect(links).toHaveLength(5)
    expect(links[0].textContent).toContain('入库单')
    expect(links[0]).toHaveAttribute('href', '/inbound-orders')
    expect(links[1].textContent).toContain('发货单')
    expect(links[1]).toHaveAttribute('href', '/shipments')
    expect(links[2].textContent).toContain('余料台账')
    expect(links[2]).toHaveAttribute('href', '/production/remnants')
    expect(links[3].textContent).toContain('省料看板')
    expect(links[3]).toHaveAttribute('href', '/production/saving-board')
    expect(links[4].textContent).toContain('库存明细')
    expect(links[4]).toHaveAttribute('href', '/stock-ledger')
  })

  it('「加工单」不再是独立菜单项：交易管理组只余两个业务项（issue #4357；#5778 收窄）', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    // 交易管理组：加工单已并入生产管理组（issue #4357 —— 与生产看板合并为单一入口）
    // issue #5271：原「订单管理」组 + 原「客户管理」组的客户列表/财务对账**并为一组** ⇒ 4 项
    expect(screen.getByText('交易管理')).toBeInTheDocument()
    expandGroup('trade-center')
    const tradeGroup = screen.getByText('交易管理').closest('[data-group-key]') as HTMLElement
    expect(within(tradeGroup).queryByText('加工单')).not.toBeInTheDocument()
    expect(within(tradeGroup).getByText('订单列表')).toBeInTheDocument()
    expect(within(tradeGroup).getByText('财务对账')).toBeInTheDocument()
    // #5778：售后工单 / 客户列表已移入「客户服务」组 ⇒ 本组只余「下单 → 收款」两项
    expect(tradeGroup.querySelectorAll('a')).toHaveLength(2)
    expect(within(tradeGroup).queryByText('售后工单')).not.toBeInTheDocument()
    expect(within(tradeGroup).queryByText('客户列表')).not.toBeInTheDocument()

    // 全站不再有指向 /processing-orders 的菜单项（旧入口收敛到 /production）——
    // 展开**全部**组后再查全站 href，避免「因为收起所以查不到」的恒真断言
    for (const key of [
      'workspace',
      'customer-service',
      'trade-center',
      'production-center',
      'inventory-center',
      'org-center',
    ]) {
      expandGroup(key)
    }
    const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).toHaveLength(22) // 简报开关关 ⇒ 22 项（23 - 每日简报；#5939：21 → 22；#6404：22 → 23 项）
    expect(hrefs).not.toContain('/processing-orders')
  })

  it('权限码口径（#5291 + #5699 P4）：生产看板/工艺配置/计件工资 = production:view，智能派单 = processing:view，省料看板 = product:list', () => {
    // issue #4490：合并**不改变权限码** —— 两个旧菜单项本来就是 processing:manage（组内同码）
    const group = menuGroups.find((g) => g.key === 'production-center')
    expect(group).toBeTruthy()
    // #5271：本组 4 项**同码**（都是加工/生产管理动作）；
    // 原先「入库单是仓储动作、权限码独立（inbound:view，issue #5034）」的口径**不变**，
    // 只是它现在挂在**新组**「仓储与物料」下 ⇒ 本用例改判为「按组取码」而不是把它算进本组。
    expect(group!.children.map((c) => c.permissionCode)).toEqual([
      'production:view',    // 生产看板（issue #5291）
      'processing:view',    // 智能派单（issue #5699 P4：节点码 = 该页读端点码）
      'production:view',    // 加工项管理（#5778 移入本组）
      'production:view',    // 工艺配置
      'production:view',    // 计件工资
    ])
    const inventory = menuGroups.find((g) => g.key === 'inventory-center')
    expect(inventory!.children.map((c) => c.permissionCode)).toEqual([
      'inbound:view',
      'order:list',         // 发货单（issue #5939：取**既有** order:list ⇒ 与订单列表同码、零授权 delta）
      'processing:manage',
      'product:list',       // 省料看板（issue #5699 P4：节点码 = 该页两个读端点的码）
      'product:list',       // 库存明细（issue #6404：同取既有 product:list ⇒ 零授权 delta）
    ])
    // 反恒真（issue #5291）：组内**不是**同码 —— 若有人把四项一起改回去（或一起改过来），本条必红。
    // issue #5699（P4）：智能派单的码由 processing:manage 收敛为 processing:view ⇒ 本集合同批改准。
    expect(new Set(group!.children.map((c) => c.permissionCode)))
      .toEqual(new Set(['production:view', 'processing:view']))
  })
})

describe('生产看板页 /production（加工单唯一入口，PG-038）', () => {
  beforeEach(() => {
    authMock.state.user.permissions = ['*'] // 默认全权限；「无 order:list」的红线用例自行改写
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

    // issue #4414：详情是**懒加载的第二个请求**，与「行出现」不是同一个 promise ⇒
    // 不能在 waitFor(行) 之后**同步**断言调用（调度顺序一变就 0 次调用 = 间歇性红）。
    // ⇒ 把三条调用断言**也放进 waitFor**（等的是「调用发生」这件事本身）。
    await waitFor(() => {
      expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-1')
      expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-2')
      expect(mockGetPiecework).toHaveBeenCalledWith('order-uuid-1')
    })
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

  // ── 合并能力（PG-038）：加工单列表页并入后，下列能力一条都不能丢 ──

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

  it('合并能力⑥订单详情：跳对应订单详情（订单详情已含加工单块，issue #4305）', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const user = userEvent.setup()
    const row = screen.getByTestId('production-row-po-1')
    // issue #5913：文案由「查看」改判为「订单详情」—— 本行主键是**加工单**，
    // 「查看」在这一行没有确定宾语（与同行的「生产明细」互换也不违和 = 命名失败的判据）。
    await user.click(within(row).getByRole('button', { name: '订单详情' }))

    expect(mockPush).toHaveBeenCalledWith('/orders/order-uuid-1')
  })

  // ── issue #5913：入口可见性 = **目标页的守卫码**（可见却 403 是缺陷，不是「少点一次」）──

  it('无 order:list ⇒ **不渲染**「订单详情」入口（生产岗点进 403 的红线）', async () => {
    // 默认岗位 product_manager：持 `production:view`（进得了本页）、**不持** `order:list`
    // ⇒ 改前该入口照渲染，点进 /orders/{id} 被路由守卫拦成「无权访问该页面」。
    // ⚠️ roles 必须一起清空：`usePermission()` 把 `roles: ['admin']` 判为全权限（isAdmin），
    // 只改 permissions 会让这条判据**恒真**（红线永远"通过"）。
    authMock.state.user.permissions = ['production:view']
    authMock.state.user.roles = []
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    const row = screen.getByTestId('production-row-po-1')
    expect(within(row).queryByRole('button', { name: '订单详情' })).toBeNull()
    // 「生产明细」与本源页同码（production:view）⇒ 不受影响，一条能力都不丢
    expect(within(row).getByRole('button', { name: '生产明细' })).toBeInTheDocument()
  })

  it('持 order:list ⇒ 入口照常渲染（显隐判据不是恒假）', async () => {
    authMock.state.user.permissions = ['production:view', 'order:list']
    authMock.state.user.roles = []
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    expect(
      within(screen.getByTestId('production-row-po-1')).getByRole('button', { name: '订单详情' }),
    ).toBeInTheDocument()
  })

  it('引导文案是**页面级**的：全页只渲染一次且不在表格里（issue #5913）', async () => {
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    // 改前 = 每行一份（2 行数据 ⇒ 2 条），并挤在 8 列中最后的「操作」格里
    expect(screen.getAllByText(/状态流转请在订单详情操作/)).toHaveLength(1)
    expect(within(screen.getByRole('table')).queryByText(/状态流转请在订单详情操作/)).toBeNull()
  })

  it('无 order:list 时引导文案标明需订单查看权限（不把人指向去不了的地方）', async () => {
    authMock.state.user.permissions = ['production:view']
    authMock.state.user.roles = []
    render(<ProductionBoardPage />)
    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    expect(screen.getByTestId('production-status-hint')).toHaveTextContent('状态流转请在订单详情操作')
    expect(screen.getByTestId('production-status-hint')).toHaveTextContent('无订单查看权限')
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
    // issue #5913：引导文案仍在（#4305 的判据一条不放宽），但落点由「每行一份」改为**页面级一次**
    expect(screen.getByTestId('production-status-hint')).toHaveTextContent('状态流转请在订单详情操作')
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
