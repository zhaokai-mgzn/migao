// case_ids: UI-028, UI-066
/**
 * 菜单命令面板 ⌘K（`CommandPalette`，issue #5271）——四项新交互中的「菜单搜索」。
 *
 * ## 口径（写判据的事实依据，逐条对应 `CommandPalette.tsx`）
 *
 *   · **空查询 = 全量索引**（不是空白页）：只列**当前用户有权访问**的项；
 *   · 命中面 = 菜单名 ∪ 组名 ∪ `menu.ts` 的 `keywords`（拼音首字母 / 常见叫法）；
 *   · **只列有权项** —— 搜索不是绕过权限的口子（负控：无权限项搜不出来、也不在空查询列表里）；
 *   · 键盘：↑/↓ 移动高亮、Enter 跳转（`router.push`）、Esc 关闭；点遮罩关闭、点结果项跳转 + 关闭；
 *   · 无结果给可读文案，Enter 不得跳转（不崩）。
 *
 * 反 placeholder：断言落在**具体 testid 序列 / 具体 path / 具体高亮类**上，
 * 不用「面板存在」这类空断言（`menu-nav.test.ts` 判纯函数，本文件判组件接线）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

let mockUser: { permissions: string[]; roles?: string[] } = { permissions: ['*'], roles: ['admin'] }
vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({ user: mockUser }),
}))

const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/dashboard',
}))

// 🔴 2026-10-17（issue #7087）：⌘K **不再**拉企业简报配置（`briefingToggle` 随「每日简报」菜单项
// 一起撤掉）。这里保留 `@/lib/api` 的替身并**计数** —— 「一次都没调用」本身就是新形态的判据
//（旧接线回潮 ⇒ 当场红），比直接删掉替身更有判别力。
const mockBriefingGetConfig = vi.hoisted(() => vi.fn(() => Promise.resolve({ data: { data: { enabled: true } } })))
vi.mock('@/lib/api', () => ({
  briefingApi: { getConfig: mockBriefingGetConfig },
}))

import CommandPalette from '@/components/layout/CommandPalette'

/**
 * 新 IA 全量 **25 项**（**2026-10-17 issue #7087**：**最前席位** → 全部分组 → 尾席位 → 独立项，
 * == `flattenMenu` 顺序；#5939 +「发货单」；#6404 +「库存明细」；#6573 +第二个一级项；
 * **#6580 生产管理组收拢为 3 项、一级项由「参数总览」改为「企业基础设置」**；
 * **#7087 撤销「工作台」组、经营看板升最前席位、删「每日简报」菜单项**）。
 *
 * 顺序是本表**独立写死**的期望值 ⇒ 组内重排 / 席位落位被无声改回 ⇒ 本用例当场红。
 */
const ALL_KEYS = [
  // 最前席位（issue #7087 + #7376）：⌘K 索引的**前两项**（都在所有分组之前）
  'dashboard',
  'reports',
  'human-sessions',
  'knowledge',
  'after-sales',
  'customers',
  // 价格本（#7375 段 3）：交易管理组内第一项
  'price-books',
  'orders',
  'finance',
  'production-board',
  'production-pool',
  'production-piecework',
  'quality-inspections',
  'inbound-orders', 'suppliers', 'purchase-orders',
  'stock-ledger',
  'stocktakes',
  'shipments',
  'production-remnants',
  'production-saving-board',
  'employees',
  'roles',
  // 尾席位一级项（#6580：「企业基础设置」由组织管理组的组内项升为一级项）
  'products',
  'settings',
  // 尾部独立项
  'notifications',
]

/** 结果区里**实际渲染**的项 key（按 DOM 顺序） */
const renderedKeys = () =>
  Array.from(document.querySelectorAll('[data-testid^="command-palette-item-"]')).map(
    (el) => el.getAttribute('data-testid')!.replace('command-palette-item-', ''),
  )

const input = () => screen.getByTestId('command-palette-input') as HTMLInputElement
const typeQuery = (q: string) => fireEvent.change(input(), { target: { value: q } })
const press = (key: string) => fireEvent.keyDown(input(), { key })
/** 高亮项 = 结果区里带 `bg-primary-50` 的那一项（具体类名，不是「存在性」） */
const highlightedKeys = () =>
  Array.from(document.querySelectorAll('[data-testid^="command-palette-item-"]'))
    .filter((el) => el.className.includes('bg-primary-50'))
    .map((el) => el.getAttribute('data-testid')!.replace('command-palette-item-', ''))

describe('CommandPalette（⌘K 菜单搜索，issue #5271）', () => {
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { permissions: ['*'], roles: ['admin'] }
  })

  it('open=false ⇒ 面板/输入框/遮罩都不渲染（不占位、不截获键盘）', () => {
    render(<CommandPalette open={false} onClose={mockOnClose} />)
    expect(screen.queryByTestId('command-palette')).toBeNull()
    expect(screen.queryByTestId('command-palette-input')).toBeNull()
    expect(screen.queryByTestId('command-palette-mask')).toBeNull()
    expect(document.querySelectorAll('[data-testid^="command-palette-item-"]')).toHaveLength(0)
  })

  it('空查询 = 全量索引：列出全部 25 项（含独立项「通知中心」），顺序 = 菜单自身顺序', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(26))
    expect(renderedKeys()).toEqual(ALL_KEYS)
    expect(input().value).toBe('')
  })

  it('🔴 索引**第 1 项** = 最前席位「经营看板」（issue #7087，判据 = `flattenMenu` 的 head 参数）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(26))
    // ① 第 1 项就是它（旧形态是「工作台」组的第一项 —— 也是它，但那时它属一个**组**）
    // ① 第 1 项仍是经营看板（登录落点不变）
    expect(renderedKeys()[0]).toBe('dashboard')
    // ② 第 2 项是报表中心（#7376：同为最前席位、按 menu.ts 顺序紧跟其后）
    expect(renderedKeys()[1]).toBe('reports')
    // ③ 默认高亮也在第 1 项身上（键盘路径的第一跳 = 登录落点那一页）
    expect(highlightedKeys()[0]).toBe('dashboard')
    // ③ 它是**一级项**：面板上不显示组名标签（`groupName` 空串）
    const item = screen.getByTestId('command-palette-item-dashboard')
    expect(item.textContent).toContain('经营看板')
    // 对照：组内项照旧显示所属组名（证明「不显示组名」不是渲染坏了）
    expect(screen.getByTestId('command-palette-item-orders').textContent).toContain('交易管理')
  })

  it('🔴 ⌘K 里取不到「工作台」与「每日简报」（issue #7087）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(26))
    // 已撤销的组名 / 已删除的菜单项都不在（`queryByText` 是**精确**文本匹配 ⇒ 不会误命中
    // 含「工作台」三字的其它文案，如别处的「客服工作台」）
    expect(screen.queryByText('工作台')).toBeNull()
    expect(screen.queryByText('每日简报')).toBeNull()
    // 双路径：`data-testid` 上也不得有这两项
    expect(screen.queryByTestId('command-palette-item-briefing')).toBeNull()
    // 反恒真：同一把尺子对**存在**的项会命中
    expect(screen.getByTestId('command-palette-item-dashboard')).toBeInTheDocument()
    expect(screen.getByTestId('command-palette-item-notifications')).toBeInTheDocument()
  })

  it('空查询 + 受限权限：只列有权项（负控：搜索不是绕过权限的口子）', async () => {
    mockUser = { permissions: ['order:list'], roles: [] }
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(4))
    // 面非空（不是「全被过滤光」造成的恒真空集）：销售订单 + **发货单**（#5939：与销售订单同码）
    // + 独立项
    // 🔴 issue #5699（P4）：经营看板要 `dashboard:view` ⇒ 本权限集**无**该码 ⇒ 它（最前席位）不在。
    expect(renderedKeys()).toEqual(['price-books', 'orders', 'shipments', 'notifications'])
    expect(screen.queryByTestId('command-palette-item-products')).toBeNull()
    expect(screen.queryByTestId('command-palette-item-finance')).toBeNull()
    expect(screen.queryByTestId('command-palette-item-dashboard')).toBeNull()
  })

  it('关键字命中（拼音首字母 `ddlb` ⇒ 销售订单，且显示所属组名）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('ddlb')
    expect(renderedKeys()).toEqual(['orders'])
    const item = screen.getByTestId('command-palette-item-orders')
    expect(item.textContent).toContain('销售订单')
    expect(item.textContent).toContain('交易管理')
    // 未命中的项**不出现**（不是只把命中项排前面）
    expect(screen.queryByTestId('command-palette-item-products')).toBeNull()
  })

  it('组名命中：`仓储` ⇒ 仓储与物料组的 4 项（顺序 = 组内顺序：库存明细 → 发货单 → 余料台账 → 省料看板；issue #7369 起单据三项已搬去「供应链」组）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('仓储')
    expect(renderedKeys()).toEqual(['stock-ledger', 'stocktakes', 'shipments', 'production-remnants', 'production-saving-board'])
  })

  it('无结果：给可读文案，且列表清空（不是留着上一轮结果）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('ddlb')
    expect(renderedKeys()).toEqual(['orders'])

    typeQuery('zzz-不存在')
    expect(renderedKeys()).toEqual([])
    expect(screen.getByText('没有匹配的菜单')).toBeInTheDocument()
  })

  it('无权限项**搜不出来**（负控）：`splb`（商品列表）在受限账号下 0 命中', async () => {
    mockUser = { permissions: ['order:list'], roles: [] }
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('splb')
    expect(renderedKeys()).toEqual([])
    expect(screen.getByText('没有匹配的菜单')).toBeInTheDocument()
    // 反恒真：同一输入面在**全量权限**下是搜得到的（证明是权限拦的，不是关键词失效）
    // —— 该对照已在 menu-nav.test.ts 逐值断言（searchMenu(items,'splb') === ['products']）
    typeQuery('ddlb')
    expect(renderedKeys()).toEqual(['orders'])
  })

  it('↑/↓ 移动高亮 + Enter 跳转：router.push 收到**被高亮那一项**的 path', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('lb') // keywords 命中：商品列表(splb) / 销售订单(ddlb) / 客户列表(khlb)
    // 顺序 = **菜单自身顺序**（同档稳定）⇒ 2026-10-06 方案 A1 后：客户列表（客户服务）→ 销售订单（交易管理）
    // → 商品管理（一级项，排在所有分组之后）
    // 「lb」只命中三个 keyword（商品列表 / 销售订单 / 客户列表）—— 价格本的关键词不含 lb
    expect(renderedKeys()).toEqual(['customers', 'orders', 'products'])
    expect(highlightedKeys()).toEqual(['customers'])

    press('ArrowDown')
    expect(highlightedKeys()).toEqual(['orders'])
    press('ArrowDown')
    expect(highlightedKeys()).toEqual(['products'])

    press('Enter')
    expect(mockPush).toHaveBeenCalledTimes(1)
    expect(mockPush).toHaveBeenCalledWith('/products')
    expect(mockOnClose).toHaveBeenCalledTimes(1)
  })

  it('↑ 从首项回绕到末项（不是停在原地），Enter 跳到末项', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('lb')   // 多结果集：客户列表 → 销售订单 → 商品管理（顺序 = 菜单自身顺序）
    press('ArrowUp')
    expect(highlightedKeys()).toEqual(['products'])
    press('Enter')
    expect(mockPush).toHaveBeenCalledWith('/products')
  })

  it('查询变化 ⇒ 高亮归零（否则会停在越界/错位的下标上）', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('lb')
    press('ArrowDown')
    press('ArrowDown')
    expect(highlightedKeys()).toEqual(['products'])

    typeQuery('caiwu') // 单结果集：若不归零，高亮下标会停在 2（越界 ⇒ 无高亮）
    expect(renderedKeys()).toEqual(['finance'])
    expect(highlightedKeys()).toEqual(['finance'])
    press('Enter')
    expect(mockPush).toHaveBeenCalledWith('/finance')
  })

  it('点结果项：跳转 + 关闭（鼠标路径与键盘路径同口径）', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    const item = screen.getByTestId('command-palette-item-production-pool')
    expect(within(item).getByText('智能派单')).toBeInTheDocument()

    fireEvent.click(item)
    expect(mockOnClose).toHaveBeenCalledTimes(1)
    expect(mockPush).toHaveBeenCalledWith('/production/pool')
  })

  it('Esc 关闭', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    press('Escape')
    expect(mockOnClose).toHaveBeenCalledTimes(1)
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('点遮罩关闭（不跳转）', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    fireEvent.click(screen.getByTestId('command-palette-mask'))
    expect(mockOnClose).toHaveBeenCalledTimes(1)
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('无结果时 Enter 不跳转、不关闭（不崩、不误跳）', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('zzz-不存在')
    expect(renderedKeys()).toEqual([])
    press('Enter')
    expect(mockPush).not.toHaveBeenCalled()
    expect(mockOnClose).not.toHaveBeenCalled()
  })

  it('🔴 ⌘K **不再**拉企业简报配置（issue #7087：旧接线回潮 ⇒ 当场红）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(26))
    // 旧形态：面板打开时调一次 `briefingApi.getConfig()`，用返回值决定「每日简报」是否进索引。
    // 菜单项与菜单级开关机制一起撤掉后，这次请求必须**消失**（过滤器只剩权限一维）。
    expect(mockBriefingGetConfig).not.toHaveBeenCalled()
  })

  it('重新打开清空上次查询（不是把上一轮的搜索词与结果留着）', async () => {
    const { rerender } = render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('ddlb')
    expect(renderedKeys()).toEqual(['orders'])

    rerender(<CommandPalette open={false} onClose={mockOnClose} />)
    rerender(<CommandPalette open onClose={mockOnClose} />)

    await waitFor(() => expect(renderedKeys()).toHaveLength(26))
    expect(input().value).toBe('')
  })
})