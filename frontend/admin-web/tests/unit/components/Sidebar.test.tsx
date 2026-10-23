// case_ids: HR-001, DF-007, UI-005, UI-011, UI-028, PR-038, PR-106, UI-067
/**
 * 侧边栏（`Sidebar.tsx`）——**既有能力不许退化**的判据（issue #5271 按新 IA 重写期望文案）。
 *
 * ## 与 `SidebarRedesign.test.tsx` 的分工
 *
 * 本文件守**能力面**：25 项一项不少不减（逐项名 + href + `data-menu-key` 序列）、
 * 图标、`bg-primary-600` 高亮与互斥单高亮、权限过滤正负控、空组整组隐藏、
 * 折叠态不渲染组名。新交互面（默认展开态 / 路由联动 / 折叠态分组锚点 / 移动端抽屉 / ⌘K 入口）
 * 在 `tests/unit/components/SidebarRedesign.test.tsx`。
 *
 * 🔴 issue #7140 起：**6 组 19 项 + 3 个一级项**（最前席位「经营看板」
 * / 尾席位「商品管理」「企业基础设置」）+ 尾部独立项「通知中心」= **25 项**；
 * （issue #7369：新增「供应链」组，把入库单 / 供应商 / 采购单 从「仓储与物料」搬出 ⇒ 组数 5 → 6，
 *  组内项总数不变）
 * 「工作台」组整组撤销、「每日简报」菜单项删除（企业开关只驱动经营看板上的结论卡）。
 *
 * ## ⚠️ 重设计带来的一处**结构性**变化（不是判据放宽）
 *
 * 新 IA 下**分组默认只展开当前路由所在组** ⇒ 想断言「其它组的项在不在」就必须
 * **先展开该组**（`data-testid="sidebar-group-toggle-<key>"`）。因此下列用例里凡断言
 * 非当前组项的，都先调 `expandGroups(...)` / `expandAll()` —— 断言本身**一条没删、没放宽**
 * （有 `expect(links).toHaveLength(27)` 这类**更强**的新钉子作反向证明）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { gold } from '@/lib/brand-palette'

// Mock useAuthStore
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock next/navigation
const mockUsePathname = vi.fn()
vi.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

// 🔴 2026-10-17（issue #7087）：侧边栏**不再**拉企业简报配置（`briefingToggle` 随「每日简报」菜单项
// 一起撤掉；企业开关从此只驱动经营看板上的结论卡）。这里保留 `@/lib/api` 的替身并**计数** ——
// 「一次都没调用」本身就是新形态的判据（旧接线回潮 ⇒ 当场红），比直接删掉替身更有判别力。
const mockBriefingGetConfig = vi.hoisted(() => vi.fn(() => Promise.resolve({ data: { data: { enabled: true } } })))
vi.mock('@/lib/api', () => ({
  briefingApi: { getConfig: mockBriefingGetConfig },
}))

import Sidebar from '@/components/layout/Sidebar'
// #5877：一级项的插入位（席位常量 = 三源同批表达的同一件事）
import { STANDALONE_TOP_AFTER_GROUP_KEY } from '@/config/menu'

/** issue #7087 + #7369 新 IA：**6 组**（「工作台」组整组撤销；#7369 新增「供应链」组） */
const GROUPS: { key: string; name: string; items: [string, string][] }[] = [
  {
    key: 'customer-service',
    name: '客户服务',
    items: [
      ['human-sessions', '在线接待'],
      ['knowledge', '知识库'],
      ['after-sales', '售后工单'],
      ['customers', '客户列表'],
    ],
  },
  // 价格本（#7375 段 3）：交易前置 ⇒ 组内第一项
  // 🔴 2026-10-24（issue #7593，用户裁定）：'approvals'（审批中心）**撤出侧边栏** —— 入口改顶栏
  // `ApprovalBell`（图标 + 待审数徽标）；`/approvals` 页面与路由守卫保留。
  { key: 'trade-center', name: '交易管理', items: [['price-books', '价格本'], ['orders', '销售订单'], ['finance', '财务对账']] },
  {
    key: 'production-center',
    name: '生产管理',
    // 🔴 2026-10-09（issue #6580）：「加工项管理」「工艺配置」两个菜单项按用户裁定**移除**
    //（功能体并入一级项「企业基础设置」页内的配置域）⇒ 本组由 5 项收拢为 3 项。
    items: [
      ['production-board', '作业看板'],
      ['production-pool', '智能派单'],
      ['production-piecework', '计件工资'],
      // 质检记录（issue #7140 = #5652 的商家面）：排在本组末尾（三源同构：menu.ts / MenuController / AuthService）
      ['quality-inspections', '质检记录'],
      // 返工单（issue #7377）：售后判定要返工 ⇒ 紧跟质检记录（三源同序）
      ['rework-orders', '返工单'],
    ],
  },
  {
    key: 'supply-chain',
    name: '供应链',
    // issue #7369（用户 2026-10-20 裁定）：入库单 → 供应商 → 采购单（谁供货 → 买什么 → 到货登记）
    items: [
      ['inbound-orders', '入库单'],
      ['suppliers', '供应商'],
      ['purchase-orders', '采购单'],
    ],
  },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    // issue #7369：单据类节点搬去「供应链」组 ⇒ 本组只留 库存 → 出库 → 台账 → 分析
    items: [
      ['stock-ledger', '库存明细'],
      ['stocktakes', '盘点单'],
      ['shipments', '发货单'],
      ['production-remnants', '余料台账'],
      ['production-saving-board', '省料看板'],
    ],
  },
  {
    key: 'org-center',
    name: '组织管理',
    // #6580：「企业基础设置」升为**一级项**（不再占组织管理组的组内席位）
    items: [['employees', '员工管理'], ['roles', '岗位权限']],
  },
]
/**
 * **最前席位**一级项（`standaloneHeadItems`，issue #7087）：`renderStandaloneBlock` 渲染在
 * **所有分组之前**、块 `data-testid="sidebar-standalone-head"`、**无星标**。
 */
const STANDALONE_HEAD_KEYS = ['dashboard', 'reports']
const STANDALONE_HEAD_TESTID = 'sidebar-standalone-head'
/**
 * 一级项（**不占组**）：#5778 起「商品管理」不再占一个单成员组；
 * #6573（2026-10-08 用户裁定方案 C）起**并列第二个**一级项；**#6580 起该席位改为「企业基础设置」**
 *（原「参数总览」随本页并入而撤掉，`/settings`，由组织管理组的组内项升为一级项）。
 * **用户 2026-10-06 裁定**起二者都渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY`（现取**最后一个组**）之后
 * ⇒ 排在**所有分组之后**、尾部独立项之前（顺序 = 数组顺序：products → settings）。
 */
const STANDALONE_TOP_KEYS = ['products', 'settings']
/** 一级项的插入位（本表独立写死，不从实现反推） */
const TOP_SLOT_KEY = 'org-center'
const GROUP_KEYS = GROUPS.map((g) => g.key)
/**
 * 展开全部组后应渲染的 **27 项**（**最前席位 → 全部分组 → 尾席位 → 尾部独立项**，== `flattenMenu` 顺序）。
 * 🔴 🔊 2026-10-17（issue #7087）：`STANDALONE_HEAD_KEYS`（「经营看板」）在**最前**；
 * 尾席位一级项仍落在**末尾附近**（`TOP_SLOT_KEY` = 最后一个组 ⇒ 通知中心之前）。
 */
const ALL_MENU_KEYS = [
  ...STANDALONE_HEAD_KEYS,
  ...GROUPS.flatMap((g) => g.items.map(([k]) => k)),
  ...STANDALONE_TOP_KEYS,
  'notifications',
]

const groupButton = (key: string) => screen.getByTestId(`sidebar-group-toggle-${key}`)
/** 展开指定组（幂等：已展开则不点）—— 新 IA 默认只展开当前路由所在组 */
function expandGroups(...keys: string[]) {
  for (const key of keys) {
    const btn = groupButton(key)
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }
}
const expandAll = () => expandGroups(...GROUP_KEYS)
const menuKeys = () =>
  Array.from(document.querySelectorAll('[data-menu-key]')).map((el) => el.getAttribute('data-menu-key'))
const activeKeys = () =>
  Array.from(document.querySelectorAll('nav a'))
    .filter((a) => a.className.includes('bg-primary-600'))
    .map((a) => a.getAttribute('data-menu-key'))
const linkFor = (name: string) => screen.getByText(name).closest('a')!

describe('Sidebar', () => {
  const user = userEvent.setup()
  const mockOnToggle = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockUsePathname.mockReturnValue('/dashboard')
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
    })
  })

  // ── 基础结构 ──

  it('should render the sidebar with logo', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  // issue #7476（用户 2026-10-22 裁定）：左上角那一格的语义位是**租户身份**，品牌与企业名并列会被
  // 读成「两个主体并列」（商家上传自家 Logo 后尤甚）⇒ 顶部只留企业身份，平台品牌沉到底部署名。
  it('左上角只留企业身份，平台品牌沉到侧边栏底部署名（issue #7476）', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantName: '测试企业' },
    })
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 顶部主位：逐字只有企业名（品牌不再作为第二行与企业名并列）
    expect(screen.getByText('测试企业').parentElement?.textContent).toBe('测试企业')
    // 底部署名：逐字「观星台」，且整栏只出现这一次
    expect(screen.getByTestId('sidebar-brand-name').textContent).toBe('观星台')
    expect(screen.getAllByText('观星台')).toHaveLength(1)
  })

  it('企业名缺失时品牌占主位，且全栏只出现一次（issue #7476）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getAllByText('观星台')).toHaveLength(1)
    // 主位已经是品牌名 ⇒ 底部不再重复署名
    expect(screen.queryByTestId('sidebar-brand')).toBeNull()
  })

  // issue #7480（用户 2026-10-22：「这样放置设计的太丑陋了，让我们品牌高大上一点」）：
  // 品牌不是一行孤零零的灰字 —— 它和折叠控制同处**页脚一行**，且带品牌图形。
  it('品牌署名与折叠控制同处页脚一行（issue #7480）', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantName: '测试企业' },
    })
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const footer = screen.getByTestId('sidebar-footer')
    const brand = screen.getByTestId('sidebar-brand')
    const collapse = within(footer).getByTitle('收起侧边栏')
    // 同一行：署名与折叠按钮同父、互为相邻兄弟（退回「两行各居一侧」即红）
    expect(brand.parentElement).toBe(collapse.parentElement)
    expect(brand.nextElementSibling).toBe(collapse)
    // 品牌图形在位**且取品牌金**（删掉星标 / 改色都会红 —— 不写成「非空」那种空断言）
    expect(brand.querySelector('svg path')?.getAttribute('fill')).toBe(gold[400])
    expect(within(brand).getByTestId('sidebar-brand-name').textContent).toBe('观星台')
    // issue #7487：MIGAO 已移除（观星台 = 米高，同一个名字不说两遍）
    expect(within(footer).queryByText('MIGAO')).toBeNull()
    // issue #7491：公司法定名**撤出侧边栏**（侧边栏是租户的地盘，不挂供应商名）——
    // 它改到顶栏用户菜单「关于观星台」按需查看；这里出现即红。
    expect(screen.queryByTestId('sidebar-company')).toBeNull()
    expect(screen.queryByText('杭州词元通达科技有限公司')).toBeNull()
  })

  it('折叠态不渲染品牌文本（issue #7476）', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantName: '测试企业' },
    })
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.queryByTestId('sidebar-brand')).toBeNull()
    expect(screen.queryByTestId('sidebar-company')).toBeNull()
    expect(screen.queryByText('观星台')).toBeNull()
  })

  it('未设置企业 Logo 时回退观星台默认 Logo', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantName: '测试企业' },
    })
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
    expect(screen.queryByAltText('企业 Logo')).not.toBeInTheDocument()
  })

  it('已设置企业 Logo 时展示 img，加载失败后回退默认 Logo', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantLogo: 'https://oss.example.com/logo.png' },
    })
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const img = screen.getByAltText('企业 Logo')
    expect(img).toHaveAttribute('src', 'https://oss.example.com/logo.png')
    expect(screen.queryByTestId('logo')).not.toBeInTheDocument()

    // Logo URL 失效 → 回退默认 Logo，避免空白
    fireEvent.error(img)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
    expect(screen.queryByAltText('企业 Logo')).not.toBeInTheDocument()
  })

  it('should render all menu items（issue #7140 + #7369 新 IA：6 组 + 3 个一级项 + 独立项 = 25 项）', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 🔴 分组标题 = **6 组**（「工作台」组已整组撤销；#7369 新增「供应链」组 —— 见下方负断言）
    expect(screen.getByText('客户服务')).toBeInTheDocument()
    expect(screen.getByText('交易管理')).toBeInTheDocument()
    expect(screen.getByText('生产管理')).toBeInTheDocument()
    expect(screen.getByText('供应链')).toBeInTheDocument()
    expect(screen.getByText('仓储与物料')).toBeInTheDocument()
    expect(screen.getByText('组织管理')).toBeInTheDocument()
    // 🔴 旧组名不再出现：「工作台」组（2026-10-17 issue #7087 整组撤销）、#5778 起「商品与加工项」撤销、
    // 「智能客服」改判为「客户服务」，且「商品管理」不再是**组名**（它是一级项，不渲染组标题）。
    expect(screen.queryByText('工作台')).not.toBeInTheDocument()
    expect(screen.queryByText('商品与加工项')).not.toBeInTheDocument()
    expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
    expect(screen.queryByText('订单管理')).not.toBeInTheDocument()
    expect(screen.queryByText('客户管理')).not.toBeInTheDocument()

    // 非当前组（/dashboard 属**最前席位**、不入任何组 ⇒ 默认**全部组收起**）的项必须先展开该组才可见
    expandAll()
    // 子菜单项：25 项**一项不少不减**
    expect(menuKeys()).toEqual(ALL_MENU_KEYS)
    for (const [, name] of GROUPS.flatMap((g) => g.items)) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    // UI-005/UI-011: **客户服务**分组下 在线接待 + 知识库（#3094 黄金策·在线对话 菜单入口已移除，对话经右下角 FAB）；#2969 知识库并入本组；#3081 AI 客服配置已合并进企业基础信息
    // #5778：客户列表 / 售后工单也并入本组
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    // 🔴「每日简报」菜单项**已删除**（issue #7087：结论本来就在经营看板上，企业开关只驱动那张卡）
    expect(screen.queryByText('每日简报')).not.toBeInTheDocument()
    // 最前席位一级项「经营看板」在（不是「跟着旧组一起消失」）
    expect(screen.getByText('经营看板')).toBeInTheDocument()
    // #1403: 商品分类管理已移出侧边栏，入口内嵌到新增商品页
    expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
    // 旧菜单名（#4490 的合并名，用码点构造以免在源码里再写出它）不再出现在侧边栏（issue #4542 改名）
    expect(screen.queryByText('\u52a0\u5de5\u9879\u4e0e\u52a0\u5de5\u8d39')).not.toBeInTheDocument()
    // UI-005: 「机器人设置」已更名为「AI 客服配置」，不再出现旧名
    expect(screen.queryByText('机器人设置')).not.toBeInTheDocument()
    // #2969: 「角色权限」已改名「岗位权限」，旧名不再出现
    expect(screen.queryByText('角色权限')).not.toBeInTheDocument()
  })

  it('25 项一项不少不减：`data-menu-key` 序列逐值 == 新 IA（最前席位 → 全部分组 → 尾席位 → 独立项）', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 🔴 /dashboard 属**最前席位**（不入任何组）⇒ 冷加载时 6 个组**全部收起**（新形态的直接读数）
    await waitFor(() => expect(screen.getByTestId(STANDALONE_HEAD_TESTID)).toBeInTheDocument())
    expect(
      Object.fromEntries(GROUP_KEYS.map((k) => [k, groupButton(k).getAttribute('aria-expanded')])),
    ).toEqual(Object.fromEntries(GROUP_KEYS.map((k) => [k, 'false'])))
    expandAll()
    // 🔴 2026-10-17（issue #7087）：最前席位「经营看板」在**第 1 位**；
    // 尾席位一级项（商品管理 / 企业基础设置）仍排在**所有分组之后**、通知中心之前。
    expect(menuKeys()).toEqual([
      'dashboard',
      // 报表中心（#7376）：经营看板之后、分组之前
      'reports',
      'human-sessions', 'knowledge', 'after-sales', 'customers',
      // 🔴 #7593：'approvals' 已撤出侧边栏（入口改顶栏 `ApprovalBell`）
      'price-books', 'orders', 'finance',
      'production-board', 'production-pool', 'production-piecework', 'quality-inspections', 'rework-orders',
      'inbound-orders', 'suppliers', 'purchase-orders', 'stock-ledger', 'stocktakes', 'shipments', 'production-remnants',
      'production-saving-board',
      'employees', 'roles',
      'products',
      'settings',
      'notifications',
    ])
    expect(menuKeys()).toHaveLength(27)
  })

  // ── 🔴 issue #7087 新形态（会红的那几条）────────────────────────────────────────

  it('🔴 最前席位「经营看板 → 报表中心」渲染在**所有分组之前**，且**不渲染星标**（#7087 + #7376）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const head = screen.getByTestId(STANDALONE_HEAD_TESTID)
    // ① 块里是**两项**：经营看板 → 报表中心（#7376：同为最前席位、经营数据面）
    expect(within(head).getByText('经营看板')).toBeInTheDocument()
    expect(within(head).getByText('报表中心')).toBeInTheDocument()
    const links = head.querySelectorAll('[data-menu-key]')
    expect(links).toHaveLength(2)
    expect(links[0].getAttribute('data-menu-key')).toBe('dashboard')
    expect(links[1].getAttribute('data-menu-key')).toBe('reports')

    // ② 位置判据：它在**任何** `[data-group-key]` 之前（DOM 顺序，不是「渲染了就算」）
    const follows = (a: Element, b: Element) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
    const firstGroup = document.querySelector('[data-group-key]')!
    expect(firstGroup).toBeTruthy()
    expect(follows(head, firstGroup)).toBe(true)
    // 判别力：旧形态（一级项块在分组之后）会让这两条红
    expect(follows(firstGroup, head)).toBe(false)
    // ③ 它在**尾席位**一级项之前（两个席位不是同一处）
    expect(follows(head, linkFor('商品管理'))).toBe(true)
    expect(follows(head, linkFor('企业基础设置'))).toBe(true)

    // ④ **无星标**：一级项不可收藏（否则「常用」里会出现第二条一模一样的入口）
    expect(within(head).queryByTestId('sidebar-pin-dashboard')).toBeNull()
    expect(screen.queryByTestId('sidebar-pin-dashboard')).toBeNull()
    // 对照（不是「星标整体被删」）：组内项照旧有星标
    expandGroups('trade-center')
    expect(screen.getByTestId('sidebar-pin-orders')).toBeInTheDocument()
  })

  it('🔴 侧边栏取不到「工作台」与「每日简报」；分组数 = 6（issue #7087 / #7369）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 分组数 = **6**（`data-group-key`；未钉任何项 ⇒ 「常用」合成组不渲染）
    expect(document.querySelectorAll('[data-group-key]')).toHaveLength(6)
    expect(GROUP_KEYS).toHaveLength(6)
    // 组名「工作台」与菜单项「每日简报」都不在。`queryByText` 是**精确**文本匹配
    // （整段文本相等），因此不会误命中含「工作台」三字的其它文案（如别处的「客服工作台」）。
    expect(screen.queryByText('工作台')).toBeNull()
    expect(screen.queryByText('每日简报')).toBeNull()
    // 双路径再判一次：文案若被拆成多个节点，文本匹配会失灵 ⇒ 用 `data-menu-key` 兜底
    expect(document.querySelector('[data-menu-key="briefing"]')).toBeNull()
    // 反恒真：同一把尺子对**存在**的项会命中（否则上面两条可能是「整块没渲染」的假绿）
    expect(document.querySelector('[data-menu-key="dashboard"]')).toBeTruthy()
    expect(document.querySelector('[data-menu-key="notifications"]')).toBeTruthy()
  })

  it('🔴 侧边栏**不再**拉企业简报配置（issue #7087：旧接线回潮 ⇒ 当场红）', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await waitFor(() => expect(screen.getByText('经营看板')).toBeInTheDocument())
    // 旧形态：挂载时调一次 `briefingApi.getConfig()`，用返回值决定「每日简报」是否渲染。
    // 菜单项与菜单级开关机制一起撤掉后，这次请求必须**消失**（企业开关只驱动经营看板上的 BriefingCard）。
    expect(mockBriefingGetConfig).not.toHaveBeenCalled()
  })

  it('should render navigation links with correct paths', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandAll()
    expect(linkFor('经营看板')).toHaveAttribute('href', '/dashboard')
    expect(linkFor('商品管理')).toHaveAttribute('href', '/products')
    // #6580：第二个一级项「企业基础设置」→ /settings（「加工项管理」「工艺配置」已不是菜单项）
    expect(linkFor('企业基础设置')).toHaveAttribute('href', '/settings')
    expect(linkFor('销售订单')).toHaveAttribute('href', '/orders')
    expect(linkFor('售后工单')).toHaveAttribute('href', '/after-sales')
    expect(linkFor('客户列表')).toHaveAttribute('href', '/customers')
    expect(linkFor('财务对账')).toHaveAttribute('href', '/finance')
    expect(linkFor('作业看板')).toHaveAttribute('href', '/production')
    expect(linkFor('智能派单')).toHaveAttribute('href', '/production/pool')
    expect(linkFor('计件工资')).toHaveAttribute('href', '/production/piecework')
    // issue #5271：面料进出与消耗移入「仓储与物料」（原生产管理组）；
    // issue #7369：单据三项（入库单 / 供应商 / 采购单）再拆到新组「供应链」，余料/省料仍留仓储组
    expect(linkFor('入库单')).toHaveAttribute('href', '/inbound-orders')
    expect(linkFor('余料台账')).toHaveAttribute('href', '/production/remnants')
    expect(linkFor('省料看板')).toHaveAttribute('href', '/production/saving-board')
    expect(linkFor('员工管理')).toHaveAttribute('href', '/employees')
    expect(linkFor('岗位权限')).toHaveAttribute('href', '/roles')
    // #3094: 黄金策 · 在线对话 菜单入口已移除（侧边栏不再渲染 /chat 链接）
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    expect(linkFor('在线接待')).toHaveAttribute('href', '/agent-workspace/human-sessions')
    expect(linkFor('知识库')).toHaveAttribute('href', '/knowledge')
    expect(linkFor('通知中心')).toHaveAttribute('href', '/notifications')
  })

  // ── 折叠状态 ──

  it('should hide text labels when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    for (const g of GROUPS) {
      expect(screen.queryByText(g.name)).not.toBeInTheDocument()
    }
    expect(screen.queryByText('观星台')).not.toBeInTheDocument()
    // 菜单名文本同样不渲染（此态下只有图标）
    expect(screen.queryByText('商品列表')).not.toBeInTheDocument()
    expect(screen.queryByText('经营看板')).not.toBeInTheDocument()
  })

  it('should show expand button when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.getByTitle('展开侧边栏')).toBeInTheDocument()
  })

  it('should show collapse button when expanded', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('收起')).toBeInTheDocument()
  })

  it('should call onToggle when collapse button is clicked', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await user.click(screen.getByText('收起'))
    expect(mockOnToggle).toHaveBeenCalledTimes(1)
  })

  // ── 高亮激活 ──

  function getActiveClass(el: HTMLElement) {
    return el.className
  }

  it('should highlight active menu item for /dashboard', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('经营看板')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight active menu item for /products', () => {
    mockUsePathname.mockReturnValue('/products')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5778：「商品管理」升为**一级项**（#5877 起渲染在「工作台」组之后、不属任何组）⇒ 它**恒渲染**，无需展开任何组
    const link = linkFor('商品管理')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should not highlight inactive menu items', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 非当前组默认收起 ⇒ 先展开「客户服务」再断言它**不高亮**（断言强度不变）
    expandGroups('customer-service')
    const link = linkFor('客户列表')
    expect(getActiveClass(link)).not.toContain('bg-primary-600')
  })

  it('should highlight nested route for /products/123', () => {
    mockUsePathname.mockReturnValue('/products/123')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('商品管理')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight for root path as dashboard', () => {
    mockUsePathname.mockReturnValue('/')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('经营看板')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  // ── 前缀嵌套路由互斥单高亮（#3094 黄金策菜单已移除：/chat 无侧边栏入口，在线接待不重复高亮）──

  it('/chat 时无侧边栏菜单高亮（黄金策入口已移除，对话经右下角 FAB）', () => {
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    // /chat 不属于任何菜单项 ⇒ 无组可展开；展开智能客服后「在线接待」仍在 DOM 且不得高亮
    expandGroups('customer-service')
    const humanLink = linkFor('在线接待')
    expect(getActiveClass(humanLink)).not.toContain('bg-primary-600')
  })

  it('/chat 时侧边栏无高亮菜单项（#3094 黄金策入口已移除）', async () => {
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // /chat 不属于任何菜单项 ⇒ **全部组默认收起**（这本身就是「无高亮」的一种形态）；
    // 展开全部组后再断言「27 项都在 DOM 里，仍然一个都不高亮」
    expandAll()
    await waitFor(() => expect(document.querySelectorAll('nav a')).toHaveLength(27))
    expect(activeKeys()).toEqual([])
  })

  it('/orders/new 时「销售订单」高亮（嵌套路由前缀匹配回归保护）', () => {
    mockUsePathname.mockReturnValue('/orders/new')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5778：交易管理组现为「销售订单 + 财务对账」（售后工单已移入客户服务组）——
    // 同组对照项随之换成「财务对账」，断言**强度一条没减**（仍是「前缀命中只高亮销售订单」）。
    expandGroups('trade-center')
    const ordersLink = linkFor('销售订单')
    const financeLink = linkFor('财务对账')
    expect(getActiveClass(ordersLink)).toContain('bg-primary-600')
    expect(getActiveClass(financeLink)).not.toContain('bg-primary-600')
  })

  it('前缀同时命中（/production/pool ↔ /production）时**只有一项**高亮 —— 最长前缀胜出', () => {
    mockUsePathname.mockReturnValue('/production/pool')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(activeKeys()).toEqual(['production-pool'])
    expect(getActiveClass(linkFor('智能派单'))).toContain('bg-primary-600')
    expect(getActiveClass(linkFor('作业看板'))).not.toContain('bg-primary-600')
  })

  // ── 分组折叠/展开 ──

  it('should toggle group expansion when clicking group header', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // /dashboard ⇒ 「组织管理」默认**收起**（新交互 ①），故先点开、再点收。
    // ⚠️ #5778：原锚点「商品与加工项」组已撤销（商品列表升为一级项 ⇒ 不再有单成员组），
    // 本用例改用「组织管理」（3 项、非当前路由所在组）—— 断言的**强度一条没减**。
    expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
    expect(groupButton('org-center').getAttribute('aria-expanded')).toBe('false')

    await user.click(screen.getByText('组织管理'))
    expect(screen.getByText('员工管理')).toBeInTheDocument()
    expect(groupButton('org-center').getAttribute('aria-expanded')).toBe('true')

    await user.click(screen.getByText('组织管理'))
    expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
    expect(groupButton('org-center').getAttribute('aria-expanded')).toBe('false')
  })

  // ── 独立菜单项 ──

  it('should render standalone items exactly once each', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5271: 交易管理是**唯一**的合并组（原「订单管理」+「客户管理」组的客户列表/财务对账）
    expect(screen.getAllByText('交易管理').length).toBe(1)
    // #5778：「商品管理」现在是一级项（渲染恰一次，但不是组标题）
    expect(screen.getAllByText('商品管理').length).toBe(1)
    // #3081: AI 客服配置已移除（合并进企业基础信息），不再渲染
    expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    // #2969: 岗位权限归入组织管理组（唯一）—— 该组默认收起，先展开；通知中心仍为独立菜单（唯一）
    expandGroups('org-center')
    expect(screen.getAllByText('岗位权限').length).toBe(1)
    expect(screen.getAllByText('通知中心').length).toBe(1)
  })

  // ── UI-005: 智能客服大类分组与图标 ──

  it('（2026-10-06 用户裁定 / #6580 / #7087）**尾席位**两个一级项都在**所有分组之后**、「通知中心」之前（DOM 顺序）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const follows = (a: HTMLElement, b: HTMLElement) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
    const productItem = linkFor('商品管理')
    const settingsItem = linkFor('企业基础设置')
    const customerService = screen.getByText('客户服务')
    const trade = screen.getByText('交易管理')
    const org = screen.getByText('组织管理')
    const notifications = screen.getByText('通知中心')
    // 组锚点：**最后一个组**是 org-center（席位插入位就在它之后）
    const orgHeader = org.closest('[data-group-key]') as HTMLElement
    // 🔴 位置 = **所有分组之后**（用户 2026-10-06 裁定：大菜单项并列 ⇒ 尾席位沉底）
    expect(follows(customerService, productItem)).toBe(true)
    expect(follows(org, productItem)).toBe(true)
    expect(follows(orgHeader, productItem)).toBe(true)
    // #6580：第二个一级项同在分组之后（不是「只有第一个沉底」）
    expect(follows(customerService, settingsItem)).toBe(true)
    expect(follows(org, settingsItem)).toBe(true)
    expect(follows(productItem, notifications)).toBe(true)
    expect(follows(settingsItem, notifications)).toBe(true)
    // 两者之间的顺序 = `standaloneTopItems` 数组顺序（商品管理 → 企业基础设置）
    expect(follows(productItem, settingsItem)).toBe(true)
    // 组顺序不受影响（判别力：这条与「一级项的位置」是两件事）
    expect(follows(customerService, trade)).toBe(true)
    // 判别力：旧口径（一级项夹在分组之间）在下面两条上会给出 true ⇒ 现在就红
    expect(follows(productItem, customerService)).toBe(false)
    expect(follows(settingsItem, customerService)).toBe(false)
    // 席位常量与渲染位必须同源（改常量而不改判据 = 无声漂移）
    expect(STANDALONE_TOP_AFTER_GROUP_KEY).toBe(TOP_SLOT_KEY)
  })

  it('（#5877）一级项用**板块入口**规格（与组头同级排版 + 不旋转 chevron + 分隔线 + 无星标）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('商品管理')
    // 一整行可点的一级项：常态颜色/悬停与组头同级（不是与组内项同级的 text-sm text-neutral-300）
    expect(link.className).toContain('text-neutral-400')
    expect(link.className).toContain('hover:bg-white/5')
    expect(link.className).toContain('hover:text-neutral-200')
    // 文案 = 组头规格
    const label = within(link).getByText('商品管理')
    expect(label.className).toContain('text-xs')
    expect(label.className).toContain('font-medium')
    expect(label.className).toContain('tracking-wide')
    // 对照：组头也是同一套排版（「板块入口」= 与组头同级，而不是随口一说）
    const groupLabel = screen.getByText('客户服务')
    for (const cls of ['text-xs', 'font-medium', 'tracking-wide']) {
      expect(groupLabel.className).toContain(cls)
    }
    // 图标 = 组头同款尺寸
    const icon = within(link).getByTestId('icon-package')
    expect(icon.getAttribute('class')).toContain('h-3.5')
    expect(icon.getAttribute('class')).toContain('w-3.5')
    // 右端 = **不旋转**的 ChevronRight（表示「直达」，不是可展开的组）
    const chevron = within(link).getByTestId('icon-chevron-right')
    expect(chevron.getAttribute('class')).toContain('text-neutral-600')
    expect(chevron.getAttribute('class')).not.toContain('rotate-90')
    // 与上方之间（head 组之后）有分隔线：仓内既有同款
    expect(screen.getByTestId('sidebar-standalone-top').className).toContain('border-t')
    // 🔴 对照（issue #7087）：**最前席位**在顶部紧接「常用」⇒ **不画**分隔线（两种情形，别只按一种理解）
    expect(screen.getByTestId(STANDALONE_HEAD_TESTID).className).not.toContain('border-t')
    // 无星标：一级项不可收藏
    expect(within(link).queryByTestId('sidebar-pin-products')).toBeNull()
  })

  it('（#5877）一级项无星标；组内项与尾部独立项**仍有**星标（对照：不是星标整体被删）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByTestId('sidebar-pin-products')).toBeNull()
    // #6580：第二个一级项（「企业基础设置」，席位原属「参数总览」）同样是「板块入口」⇒ 也没有星标
    expect(screen.queryByTestId('sidebar-pin-settings')).toBeNull()
    expandGroups('trade-center')
    expect(screen.getByTestId('sidebar-pin-orders')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-pin-notifications')).toBeInTheDocument()
  })

  it('（#5877）折叠态：一级项按组锚点同款处理（图标居中、title = 菜单名、不渲染文字）', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    const link = document.querySelector('[data-menu-key="products"]') as HTMLAnchorElement
    expect(link).toBeTruthy()
    expect(link.className).toContain('justify-center')
    expect(link.getAttribute('title')).toBe('商品管理')
    expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
    expect(within(link).queryByTestId('sidebar-pin-products')).toBeNull()
  })

  it('（2026-10-06 方案 A1）「客户服务」组内顺序：在线接待 → 知识库 → 售后工单 → 客户列表', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandGroups('customer-service')
    const groupContainer = screen.getByText('客户服务').closest('[data-group-key]') as HTMLElement
    const links = groupContainer.querySelectorAll('a')
    expect(links.length).toBe(4)
    expect(links[0].textContent).toContain('在线接待')
    expect(links[1].textContent).toContain('知识库')
    expect(links[2].textContent).toContain('售后工单')
    expect(links[3].textContent).toContain('客户列表')
  })

  it('🔴「工作台」组**整组撤销**（issue #7087）：无此组锚点，「经营看板」改由**最前席位**承载', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // ① 组不存在：既不是可见组、也不是「空组」（不留组头、不留锚点）
    expect(document.querySelector('[data-group-key="workspace"]')).toBeNull()
    expect(screen.queryByText('工作台')).toBeNull()
    expect(document.querySelectorAll('[data-group-key]')).toHaveLength(6)
    // ② 原组内两项的去向：经营看板 → 最前席位块；每日简报 → 删除
    const head = screen.getByTestId(STANDALONE_HEAD_TESTID)
    expect(within(head).getByText('经营看板')).toBeInTheDocument()
    expect(document.querySelector('[data-menu-key="briefing"]')).toBeNull()
    // ③ 它在**所有分组之前**（不是「换个位置藏在某组里」）
    const follows = (a: Element, b: Element) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
    expect(follows(head, document.querySelector('[data-group-key]')!)).toBe(true)
    // ④「在线接待」整体仍存在（#5778 起它就在「客户服务」分组里，与本轮无关）
    expandGroups('customer-service')
    expect(screen.getByText('在线接待')).toBeInTheDocument()
    expect(linkFor('在线接待')).toHaveAttribute('href', '/agent-workspace/human-sessions')
  })

  it('「在线接待」渲染 Headphones 图标，与「经营看板」BarChart3 图标明确区分', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandGroups('customer-service')
    const humanLink = linkFor('在线接待')
    expect(within(humanLink).getByTestId('icon-headphones')).toBeInTheDocument()
    expect(within(humanLink).queryByTestId('icon-bar-chart3')).not.toBeInTheDocument()
    const dashboardLink = linkFor('经营看板')
    expect(within(dashboardLink).getByTestId('icon-bar-chart3')).toBeInTheDocument()
  })

  it('（#5778）「客户服务」组渲染 MessageSquare 图标（#3081 AI 客服配置菜单已移除）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const groupButtonEl = screen.getByText('客户服务').closest('button')!
    // ⚠️ 组图标**不得**与组内任一项同图（判据 = 图标两两不同，issue #5582）——
    // 曾用 Headphones（与组内「在线接待」同图）⇒ 实测判红；改用空闲的 MessageSquare。
    expect(within(groupButtonEl).getByTestId('icon-message-square')).toBeInTheDocument()
    expect(within(groupButtonEl).queryByTestId('icon-headphones')).not.toBeInTheDocument()
  })

  it('「黄金策·在线对话」菜单入口已移除（#3094：智能体对话经右下角浮动按钮进入）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
  })

  // ── 权限过滤 ──

  describe('Permission-based menu filtering', () => {
    it('should show all menu items for admin user with * permission', async () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // /dashboard 属最前席位（不入组）⇒ 没有组会自动展开 ⇒ 等最前席位块落地
      await waitFor(() => expect(screen.getByTestId(STANDALONE_HEAD_TESTID)).toBeInTheDocument())
      // 六大组头（「工作台」组已撤销；含 #5271 的「仓储与物料」与 #7369 新增的「供应链」）
      for (const g of GROUPS) {
        expect(screen.getByText(g.name)).toBeInTheDocument()
      }
      expect(screen.queryByText('工作台')).not.toBeInTheDocument()
      expandAll()
      for (const [, name] of GROUPS.flatMap((g) => g.items)) {
        expect(screen.getByText(name)).toBeInTheDocument()
      }
      // #1403: 商品分类管理已移出侧边栏
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // UI-005/UI-011: admin 可见智能客服大类及其子菜单（#3094 黄金策·在线对话 入口已移除）
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(menuKeys()).toHaveLength(27)
    })

    it('should filter out items user has no permission for', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '2', username: 'operator', name: '运营', permissions: ['dashboard:view', 'order:list', 'product:list'], roles: ['operator'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 有权限的：最前席位两项（本权限集持 dashboard:view ⇒ 看板与报表中心同码同可见）
      expect(screen.getByText('经营看板')).toBeInTheDocument()
      expect(screen.getByText('报表中心')).toBeInTheDocument()
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      // #5778：「商品管理」是**一级项**（恒渲染，不需要展开任何组）
      expect(screen.getByText('商品管理')).toBeInTheDocument()
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      expandGroups('trade-center')
      expect(screen.getByText('销售订单')).toBeInTheDocument()
      expect(screen.getByText('销售订单')).toBeInTheDocument()
      // 无权限的
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
      expect(screen.queryByText('加工项管理')).not.toBeInTheDocument()
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // #5271: 客户列表/财务对账与销售订单**同组**（交易管理）⇒ 无码时只有它们从组内消失，组本身仍在
      expect(screen.queryByText('客户列表')).not.toBeInTheDocument()
      expect(screen.queryByText('财务对账')).not.toBeInTheDocument()
      // 旧「客户管理」组已不存在（#5271 并入交易管理）
      expect(screen.queryByText('客户管理')).not.toBeInTheDocument()
      // #2969: 组织管理组（员工+岗位权限+企业信息）整组隐藏
      expect(screen.queryByText('组织管理')).not.toBeInTheDocument()
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      expect(screen.queryByText('岗位权限')).not.toBeInTheDocument()
      expect(screen.queryByText('企业基础信息')).not.toBeInTheDocument()
      // 生产管理整组隐藏（四项都要 production:view / processing:view，本组权限一个都不持）
      expect(screen.queryByText('生产管理')).not.toBeInTheDocument()
      expect(screen.queryByText('入库单')).not.toBeInTheDocument()
      expect(screen.queryByText('余料台账')).not.toBeInTheDocument()
      // 🔴 issue #5699（P4）：省料看板节点码 = 该页读码 `product:list`（不再是 processing:manage）
      // ⇒ 本组权限含它 ⇒ 「仓储与物料」只剩 库存明细 + 发货单 + 省料看板 三项（不再是「整组隐藏」；
      //   库存明细 #6404 同取 `product:list`、发货单 #5939 取 order:list）。
      // issue #7369：入库单 / 供应商 / 采购单 已搬去「供应链」组 ⇒ 本权限集无 inbound:view ⇒ 该组整组不在。
      expect(screen.getByText('仓储与物料')).toBeInTheDocument()
      expandGroups('inventory-center')
      expect(screen.getByText('省料看板')).toBeInTheDocument()
      // 无 knowledge:view（知识库节点码，issue #5246 起为**读**码）→ 入口隐藏；通知中心全员可见
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // 可见项**精确**清单（渲染顺序）：
      // 🔴 本用例的可见项里**没有** `org-center`（员工管理要 employee:list）⇒ 一级项挂到**可见分组末尾**
      // （回落方向 = 「挂到末尾」，**不是**跳到最前）
      // 经营看板 → 销售订单 → **库存明细**（仓储与物料组首项）→ **发货单**
      // （#5939：与销售订单同码 order:list）→ 省料看板 → 商品管理（一级项）→ 通知中心
      // （issue #7369：入库单 / 供应商 / 采购单 已搬去「供应链」组 ⇒ 本权限集无 inbound:view ⇒ 整组不在）
      expect(menuKeys()).toEqual(
        // 本权限集持 dashboard:view ⇒ 最前席位两项都在（报表中心同码，#7376）
        ['dashboard', 'reports', 'price-books', 'orders', 'stock-ledger', 'shipments', 'production-saving-board',
          'products', 'notifications'])
      // UI-005/UI-011: 无 agent:session / knowledge:view / customer:view / after_sales:view →
      // **客户服务**整组隐藏（#5778 组名改判；#3081 已移除 AI 客服配置菜单）
      expect(screen.queryByText('客户服务')).not.toBeInTheDocument()
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
    })

    it('零权限 ⇒ 只剩「通知中心」（#5699 P4：经营看板也按 dashboard:view 门控，不再是「无码全员可见」）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '3', username: 'newbie', name: '新人', permissions: [], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 🔴 #5699 P4：经营看板节点码 = `dashboard:view` ⇒ 零权限时**工作台整组不渲染**
      //（此前它无码 ⇒ 全员可见，而页面/路由守卫都要码 = 「看得见、点进去 403」）。
      expect(screen.queryByText('工作台')).not.toBeInTheDocument()
      expect(screen.queryByText('经营看板')).not.toBeInTheDocument()
      // 分组标题应该都不在（含工作台在内，七组全空 ⇒ 整组剔除）
      for (const name of ['工作台', '客户服务', '交易管理', '订单管理', '商品与加工项', '智能客服', '生产管理', '供应链', '仓储与物料', '组织管理', '客户管理']) {
        expect(screen.queryByText(name)).not.toBeInTheDocument()
      }
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      // 零权限唯一可见项：通知中心（**两侧都无码**，见 RBAC 的 FAIL_OPEN_PAGES 台账）
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      expect(menuKeys()).toEqual(['notifications'])
      // 零权限不可见：知识库（需 knowledge:view —— issue #5246 起节点用读码）；「每日简报」菜单项已删除（issue #7087）
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.queryByText('每日简报')).not.toBeInTheDocument()
    })

    it('有 agent:session → 保留「在线接待」（#3094 黄金策·在线对话 菜单已移除不渲染；#3081 无 AI 客服配置菜单）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '5', username: 'cs', name: '客服', permissions: ['agent:session'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('客户服务')).toBeInTheDocument()
      expandGroups('customer-service')
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.getByText('在线接待')).toBeInTheDocument()
      expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
      // 组内**只有**在线接待（知识库要 knowledge:view —— issue #5246 起节点用读码）
      expect(menuKeys()).toEqual(['human-sessions', 'notifications'])   // #5699 P4：经营看板要 dashboard:view
    })

    it('仅 knowledge:view → 隐藏「在线接待」，保留「知识库」（#3094 黄金策入口已移除）', () => {
      // issue #5246（已合入 main）：『知识库』节点码从写码 `knowledge:manage` 换成**读码**
      // `knowledge:view`（拆读写：只想看知识卡片的岗位不该被授予增删改发布权）⇒ 入口可见性按读码判。
      mockUseAuthStore.mockReturnValue({
        user: { id: '6', username: 'kb', name: '知识管理员', permissions: ['knowledge:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('客户服务')).toBeInTheDocument()
      expandGroups('customer-service')
      expect(screen.getByText('知识库')).toBeInTheDocument()
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['knowledge', 'notifications'])   // #5699 P4：同上
    })

    it('仅 knowledge:manage（**写**码、无读码）→ 知识库入口隐藏（issue #5246 的读写分权口径）', () => {
      // 反面钉法：节点码是读码 ⇒ 只持写码的岗位看不到页面（内置岗位无人如此：admin 走 `*`，
      // 客服/运营持读码）。这与后端「写端点仍要 knowledge:manage」并不矛盾：写权限 ≠ 页面可见性；
      // 自定义岗位若只勾写码，需商家同时勾读码才能看到入口（已在 CHANGELOG/RBAC 登记）。
      mockUseAuthStore.mockReturnValue({
        user: { id: '7', username: 'kbw', name: '知识编辑', permissions: ['knowledge:manage'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.queryByText('客户服务')).not.toBeInTheDocument()
      // 组内四项都不可见 ⇒ 客户服务**整组剔除**（空组不渲染）；#5699 P4 后经营看板也需 dashboard:view
      expect(menuKeys()).toEqual(['notifications'])
    })

    it('售后工单走**读**码 after_sales:view；只持写码 order:refund ⇒ 入口隐藏（issue #5246）', () => {
      // 同族反面钉法在交易管理组上取一次：『售后工单』节点码 = `after_sales:view`（读码），
      // `order:refund` 是不挂在菜单节点上的**写**码 ⇒ 它不进可见性判定（否则「能退款」被当成「该看到入口」）。
      mockUseAuthStore.mockReturnValue({
        user: { id: '8', username: 'as', name: '售后', permissions: ['after_sales:view'], roles: [] },
      })
      const { unmount } = render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // #5778：售后工单已随「服务客户」动线移入**客户服务**组（原交易管理组）
      expandGroups('customer-service')
      expect(screen.getByText('售后工单')).toBeInTheDocument()
      expect(screen.queryByText('销售订单')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['after-sales', 'notifications'])   // #5699 P4：经营看板要 dashboard:view
      unmount()

      mockUseAuthStore.mockReturnValue({
        user: { id: '9', username: 'asw', name: '售后写', permissions: ['order:refund'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // 组内无可见项 ⇒ **客户服务**整组剔除（#5778：售后工单已在该组）；#5699 P4 后经营看板也需 dashboard:view
      expect(screen.queryByText('客户服务')).not.toBeInTheDocument()
      expect(screen.queryByText('交易管理')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['notifications'])
    })

    it('两个子菜单均不可见时「智能客服」大类整组隐藏（#3094）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '7', username: 'nocs', name: '无客服权限', permissions: ['dashboard:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
    })

    // #1403: 商品分类管理移出侧边栏
    it('should NOT show 商品分类管理 even for admin user (#1403)', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
    })

    it('should hide entire group when all children are filtered out', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '4', username: 'partial', name: '部分权限', permissions: ['dashboard:view', 'order:list'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 交易管理 group should show (has order:list)
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      expandGroups('trade-center')
      expect(screen.getByText('销售订单')).toBeInTheDocument()
      // 但售后工单不应该出现
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // 商品与加工项 group should be completely hidden（无 product:list / processing:manage）
      expect(screen.queryByText('商品与加工项')).not.toBeInTheDocument()
      // dashboard:view ⇒ 看板 + 报表中心同码同可见（#7376）
      expect(menuKeys()).toEqual(['dashboard', 'reports', 'price-books', 'orders', 'notifications'])
    })

    // ── #5271 新组的权限边界（正负控：菜单可见性与页面门禁同码，不互相顶替）──

    it('入库单（inbound:view）与余料台账（processing:manage）**互不顶替**：正负控双向', async () => {
      // ① 只有 inbound:view ⇒ 「供应链」组在（入库单 / 供应商 / 采购单可见），余料台账/省料看板不在；
      //    「仓储与物料」组整组不在（它的四项分别要 product:list / order:list / processing:manage）
      mockUseAuthStore.mockReturnValue({
        user: { id: '8', username: 'wh', name: '仓管', permissions: ['inbound:view'], roles: [] },
      })
      const { unmount } = render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('供应链')).toBeInTheDocument()
      expandGroups('supply-chain')
      expect(screen.getByText('入库单')).toBeInTheDocument()
      expect(screen.queryByText('余料台账')).not.toBeInTheDocument()
      expect(screen.queryByText('省料看板')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['inbound-orders', 'suppliers', 'purchase-orders', 'notifications'])   // #5699 P4：经营看板要 dashboard:view
      unmount()

      // ② 只有 processing:manage ⇒ 入库单**不在**（独立门禁，不因邻组而放行），余料台账/省料看板在
      mockUseAuthStore.mockReturnValue({
        user: { id: '9', username: 'op', name: '生产', permissions: ['processing:manage'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // ⚠️ 只展开仓储组：生产组在本组权限下**整组被剔除**（没有 toggle 可点）——
      // 这本身就是 #5699 P4 后的读数（生产组四项分别要 production:view / processing:view）。
      expandGroups('inventory-center')
      expect(screen.getByText('余料台账')).toBeInTheDocument()
      expect(screen.queryByText('入库单')).not.toBeInTheDocument()
      // issue #5291：作业看板/计件工资 改挂读码 production:view ⇒ 只持 processing:manage 时不在
      //（#6580：「加工项管理」「工艺配置」两个菜单项已移除）；
      // 🔴 issue #5699（P4）：省料看板节点码 = 该页读码 `product:list`，**智能派单节点码 = processing:view**
      // ⇒ 只持 processing:manage 时两者都**不在**（仓储组只剩余料台账、生产组整组剔除）。
      expect(screen.queryByText('省料看板')).not.toBeInTheDocument()
      expect(screen.queryByText('智能派单')).not.toBeInTheDocument()
      expect(screen.queryByText('生产管理')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['production-remnants', 'notifications'])
    })
  })

  // ── 菜单图标两两不同（issue #5582）─────────────────────────────────────────────

  it('🔴 菜单图标两两不同（渲染面）：25 项的图标互不重复（issue #5582）', async () => {
    // 用户实测「左侧菜单栏有部分子菜单的图标完全一样」——数据层去重（menu-icons.test.ts 判据④）
    // 只证明**配置**不重复；这里证明**渲染出来**的图标也不重复（§15.1 结果可见）。
    // 🔴 2026-10-17（issue #7087）：本判据**不再**需要「先打开简报开关」那一步 ——
    // 「每日简报」菜单项已删除（旧形态下它是异步 effect 驱动的，曾让本判据踩过
    // `Unable to find text: 每日简报`），现在 25 项**全部**同步渲染。
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await waitFor(() => expect(screen.getByTestId(STANDALONE_HEAD_TESTID)).toBeInTheDocument())
    expandAll()

    // 🔴 三个席位都要计入（**最前席位**在 #7087 新增；漏了它这条判据就少判一项）
    const items: [string, string][] = [
      ['dashboard', '经营看板'],       // 最前席位
      ['reports', '报表中心'],         // 最前席位（#7376）
      ['products', '商品管理'],        // 尾席位
      ['settings', '企业基础设置'],     // 尾席位（#6580）
      ...GROUPS.flatMap((g) => g.items),
      ['notifications', '通知中心'],
    ]
    const byIcon = new Map<string, string[]>()
    for (const [, name] of items) {
      const link = linkFor(name)
      // tests/setup.ts 的 lucide 夹具把每个图标渲染成 `data-testid="icon-<kebab>"` ⇒ 从**渲染结果**反读图标名
      const icon =
        link.querySelector('[data-testid^="icon-"]')?.getAttribute('data-testid')?.replace(/^icon-/, '') ?? '(无图标)'
      byIcon.set(icon, [...(byIcon.get(icon) ?? []), name])
    }

    const collisions = [...byIcon.entries()]
      .filter(([, names]) => names.length > 1)
      .map(([icon, names]) => `${icon} → ${names.join('、')}`)

    expect(items, '面非空自证：27 项（最前席位 2 + 尾席位 2 + 22 组内项 + 通知中心；#7140 / #7369 / #7376 / #7593 撤审批中心）').toHaveLength(27)
    expect(
      collisions,
      `以下菜单项在侧边栏里渲染出**同一个图标**（紧挨着出现 = 没有区分度，issue #5582）：\n${collisions.join('\n')}\n`
        + '出口：给后出现的那一项换一个语义相近的 lucide 图标（menu.ts + menu-icons.ts + tests/setup.ts 白名单三处同批）。',
    ).toEqual([])
    expect(byIcon.size).toBe(items.length)
  })

  // ── 「常用（收藏）」渲染面（#5778：用户自己钉 4~6 项，pin 在侧边栏顶部）──

  describe('常用（收藏）', () => {
    beforeEach(() => {
      window.localStorage.clear()
      mockUsePathname.mockReturnValue('/dashboard')
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
    })

    it('未钉任何项 ⇒ **整个「常用」区不渲染**（不留空标题），且每项有一枚可点的星标', async () => {
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // /dashboard 属最前席位（不入组）⇒ 没有组会展开；只需等菜单本体渲染出来
      await waitFor(() => expect(screen.getByText('经营看板')).toBeInTheDocument())
      expect(document.querySelector('[data-group-key="pinned"]')).toBeNull()
      expect(screen.queryByText('常用')).not.toBeInTheDocument()
      // 星标在（当前项恒显、其余 hover 才显 —— 但按钮元素一直在 DOM 里）
      // ⚠️ 交易管理组默认收起 ⇒ 先展开再断言（不是「找不到就等于没有」）
      expandGroups('trade-center')
      expect(screen.getByTestId('sidebar-pin-orders')).toBeInTheDocument()
      expect(screen.getByTestId('sidebar-pin-orders').getAttribute('data-pinned')).toBe('false')
    })

    it('点星标 ⇒ 该项进入顶部「常用」区（`data-group-key="pinned"`）+ 计数 `1/6` + 落盘 localStorage', async () => {
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(screen.getByText('经营看板')).toBeInTheDocument())
      expandGroups('trade-center')

      fireEvent.click(screen.getByTestId('sidebar-pin-orders'))

      const pinnedSec = document.querySelector('[data-group-key="pinned"]') as HTMLElement
      expect(pinnedSec).toBeTruthy()
      expect(within(pinnedSec).getByText('常用')).toBeInTheDocument()
      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('1/6')
      // 钉住的项在「常用」区里可点，且 href 正确
      expect(within(pinnedSec).getByText('销售订单')).toBeInTheDocument()
      expect(within(pinnedSec).getByText('销售订单').closest('a')).toHaveAttribute('href', '/orders')
      // 渲染序（#5877 / #7087）：**常用**区在最顶部 → **最前席位**「经营看板」→ 各分组 → 尾席位 → 尾部独立项
      const allKeys = menuKeys()
      expect(allKeys[0]).toBe('orders')
      expect(allKeys[1]).toBe('dashboard')
      // 尾席位一级项排在**所有分组之后**（用它前面最后一个组内项做锚点）
      expect(allKeys.indexOf('products')).toBeGreaterThan(allKeys.indexOf('roles'))
      expect(allKeys.indexOf('products')).toBeLessThan(allKeys.indexOf('notifications'))
      // 反恒真：orders 在交易管理组里**也**渲染（常用区是快捷方式，不是搬家）
      expect(allKeys.filter((k) => k === 'orders')).toHaveLength(2)
      // 落盘（键名与纯函数同源常量）
      const raw = window.localStorage.getItem('migao.sidebar.pinned.v1')
      expect(JSON.parse(raw!)).toEqual(['orders'])
      // 星标状态翻成已钉（钉住后该项在「常用」区与域内各一枚 ⇒ 两枚都是已钉态）
      const pins = screen.getAllByTestId('sidebar-pin-orders')
      expect(pins.length).toBeGreaterThanOrEqual(2)
      for (const el of pins) expect(el.getAttribute('data-pinned')).toBe('true')
    })

    it('🔴 取消钉住 ⇒ 「常用」区消失（清单为空）+ 落盘为空表', async () => {
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(screen.getByText('经营看板')).toBeInTheDocument())
      expandGroups('trade-center')

      fireEvent.click(screen.getByTestId('sidebar-pin-orders'))
      expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy()

      // 「常用」区里那一枚永远可见 ⇒ 再点它即取消（取「常用」区内的那一枚，避开拓扑歧义）
      const pinnedSec = document.querySelector('[data-group-key="pinned"]') as HTMLElement
      fireEvent.click(within(pinnedSec).getByTestId('sidebar-pin-orders'))
      expect(document.querySelector('[data-group-key="pinned"]')).toBeNull()
      expect(JSON.parse(window.localStorage.getItem('migao.sidebar.pinned.v1')!)).toEqual([])
    })

    it('启动时从 localStorage 恢复（惰性：首帧为空、effect 后出现）—— 恢复的项不可见（无权）则整区不渲染', async () => {
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['orders']))
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => {
        expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy()
      })
      // 换成只持 product:list 的账号 ⇒ orders 无权 ⇒ 常用区整区消失（权限优先于偏好）
      cleanup()
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['orders']))
      mockUseAuthStore.mockReturnValue({
        user: { id: '2', username: 'pm', name: '商品', permissions: ['product:list'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(screen.getByText('商品管理')).toBeInTheDocument())
      expect(document.querySelector('[data-group-key="pinned"]')).toBeNull()
    })

    it('🔴 localStorage 里残留一级项 `products` / `dashboard` ⇒ 「常用」区**都不出现**它们（只剩 orders，计数 1/6）', async () => {
      // 旧版本用户可以钉过 `products`（那时它还有星标）⇒ 升级后必须**静默丢弃**，不能出现两条一模一样的入口；
      // 🔴 issue #7087：新增的**最前席位** `dashboard` 同一条口径（它同样没有星标、不进可收藏面）。
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['products', 'dashboard', 'orders']))
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 正信号：先等「常用」区真的出现（否则下面两条可能是「还没恢复完」的假绿）
      await waitFor(() => expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy())
      const pinnedSec = document.querySelector('[data-group-key="pinned"]') as HTMLElement
      expect(within(pinnedSec).queryByText('商品管理')).toBeNull()
      expect(within(pinnedSec).queryByText('经营看板')).toBeNull()
      expect(within(pinnedSec).getByText('销售订单')).toBeInTheDocument()
      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('1/6')
      // 两个一级项本身**照旧各渲染一次**（不进「常用」≠ 从侧边栏消失）
      expect(screen.getAllByText('商品管理')).toHaveLength(1)
      expect(screen.getAllByText('经营看板')).toHaveLength(1)
      expect(menuKeys().filter((k) => k === 'products')).toHaveLength(1)
      expect(menuKeys().filter((k) => k === 'dashboard')).toHaveLength(1)
    })

    it('钉满 6 项后再钉第 7 项 ⇒ **被拒**（计数停在 6/6、localStorage 不含第 7 项）', async () => {
      // 🔴 #6580：原第 6 项用 `settings` —— 它已升为**一级项**（板块入口无星标、不可钉）⇒
      // 换成同为组内项的「发货单」（组内项才有星标），本用例的口径（钉满 6 项后被拒）一字不变。
      const six = ['orders', 'finance', 'customers', 'employees', 'roles', 'shipments']
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(six))
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy())
      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('6/6')

      expandGroups('supply-chain')
      fireEvent.click(screen.getByTestId('sidebar-pin-inbound-orders'))

      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('6/6')
      expect(JSON.parse(window.localStorage.getItem('migao.sidebar.pinned.v1')!)).toEqual(six)
      expect(screen.getByTestId('sidebar-pin-inbound-orders').getAttribute('data-pinned')).toBe('false')
    })
  })
})
