// case_ids: UI-028
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

let mockBriefingEnabled = true
vi.mock('@/lib/api', () => ({
  briefingApi: { getConfig: () => Promise.resolve({ data: { data: { enabled: mockBriefingEnabled } } }) },
}))

import CommandPalette from '@/components/layout/CommandPalette'

/** 新 IA 全量 21 项（独立项在最后） */
const ALL_KEYS = [
  'dashboard',
  'briefing',
  'human-sessions',
  'knowledge',
  'products',
  'processing',
  'orders',
  'after-sales',
  'customers',
  'finance',
  'production-board',
  'production-pool',
  'production-process',
  'production-piecework',
  'inbound-orders',
  'production-remnants',
  'production-saving-board',
  'employees',
  'roles',
  'settings',
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
    mockBriefingEnabled = true
  })

  it('open=false ⇒ 面板/输入框/遮罩都不渲染（不占位、不截获键盘）', () => {
    render(<CommandPalette open={false} onClose={mockOnClose} />)
    expect(screen.queryByTestId('command-palette')).toBeNull()
    expect(screen.queryByTestId('command-palette-input')).toBeNull()
    expect(screen.queryByTestId('command-palette-mask')).toBeNull()
    expect(document.querySelectorAll('[data-testid^="command-palette-item-"]')).toHaveLength(0)
  })

  it('空查询 = 全量索引：列出全部 21 项（含独立项「通知中心」），顺序 = 菜单自身顺序', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(21))
    expect(renderedKeys()).toEqual(ALL_KEYS)
    expect(input().value).toBe('')
  })

  it('空查询也**不含**无权项：简报开关关 ⇒ 恰少「每日简报」（与侧边栏同一口径）', async () => {
    mockBriefingEnabled = false
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(20))
    expect(renderedKeys()).toEqual(ALL_KEYS.filter((k) => k !== 'briefing'))
  })

  it('空查询 + 受限权限：只列有权项（负控：搜索不是绕过权限的口子）', async () => {
    mockUser = { permissions: ['order:list'], roles: [] }
    render(<CommandPalette open onClose={mockOnClose} />)
    await waitFor(() => expect(renderedKeys()).toHaveLength(3))
    // 面非空（不是「全被过滤光」造成的恒真空集）：无权限码的经营看板 + 订单列表 + 独立项
    expect(renderedKeys()).toEqual(['dashboard', 'orders', 'notifications'])
    expect(screen.queryByTestId('command-palette-item-products')).toBeNull()
    expect(screen.queryByTestId('command-palette-item-finance')).toBeNull()
  })

  it('关键字命中（拼音首字母 `ddlb` ⇒ 订单列表，且显示所属组名）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('ddlb')
    expect(renderedKeys()).toEqual(['orders'])
    const item = screen.getByTestId('command-palette-item-orders')
    expect(item.textContent).toContain('订单列表')
    expect(item.textContent).toContain('交易管理')
    // 未命中的项**不出现**（不是只把命中项排前面）
    expect(screen.queryByTestId('command-palette-item-products')).toBeNull()
  })

  it('组名命中：`仓储` ⇒ 仓储与物料组的 3 项（顺序 = 组内顺序）', async () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('仓储')
    expect(renderedKeys()).toEqual(['inbound-orders', 'production-remnants', 'production-saving-board'])
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
    typeQuery('lb') // keywords 命中：商品列表(splb) / 订单列表(ddlb) / 客户列表(khlb)
    expect(renderedKeys()).toEqual(['products', 'orders', 'customers'])
    expect(highlightedKeys()).toEqual(['products'])

    press('ArrowDown')
    expect(highlightedKeys()).toEqual(['orders'])
    press('ArrowDown')
    expect(highlightedKeys()).toEqual(['customers'])

    press('Enter')
    expect(mockPush).toHaveBeenCalledTimes(1)
    expect(mockPush).toHaveBeenCalledWith('/customers')
    expect(mockOnClose).toHaveBeenCalledTimes(1)
  })

  it('↑ 从首项回绕到末项（不是停在原地），Enter 跳到末项', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('lb')
    press('ArrowUp')
    expect(highlightedKeys()).toEqual(['customers'])
    press('Enter')
    expect(mockPush).toHaveBeenCalledWith('/customers')
  })

  it('查询变化 ⇒ 高亮归零（否则会停在越界/错位的下标上）', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('lb')
    press('ArrowDown')
    press('ArrowDown')
    expect(highlightedKeys()).toEqual(['customers'])

    typeQuery('caiwu') // 单结果集：若不归零，高亮下标会停在 2（越界 ⇒ 无高亮）
    expect(renderedKeys()).toEqual(['finance'])
    expect(highlightedKeys()).toEqual(['finance'])
    press('Enter')
    expect(mockPush).toHaveBeenCalledWith('/finance')
  })

  it('点结果项：跳转 + 关闭（鼠标路径与键盘路径同口径）', () => {
    render(<CommandPalette open onClose={mockOnClose} />)
    const item = screen.getByTestId('command-palette-item-production-pool')
    expect(within(item).getByText('池看板')).toBeInTheDocument()

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

  it('重新打开清空上次查询（不是把上一轮的搜索词与结果留着）', async () => {
    const { rerender } = render(<CommandPalette open onClose={mockOnClose} />)
    typeQuery('ddlb')
    expect(renderedKeys()).toEqual(['orders'])

    rerender(<CommandPalette open={false} onClose={mockOnClose} />)
    rerender(<CommandPalette open onClose={mockOnClose} />)

    await waitFor(() => expect(renderedKeys()).toHaveLength(21))
    expect(input().value).toBe('')
  })
})