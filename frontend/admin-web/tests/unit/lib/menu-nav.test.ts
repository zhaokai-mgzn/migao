// case_ids: UI-028, PR-106, PR-038, UI-074, UI-085
/**
 * 侧边栏导航**纯函数**穷举（issue #5271）。
 *
 * ## 为什么有本文件
 *
 * 重设计前「权限过滤 / 高亮选中 / 分组展开」三件事全内联在 `Sidebar.tsx` 里 ——
 * 只能靠渲染整个 Sidebar 才能验证（依赖 auth store / next-navigation / lucide 白名单三个替身），
 * 且**无法对「同一路由下哪个项高亮」做表驱动穷举**。issue #5271 把它们抽成
 * `frontend/admin-web/src/lib/menu-nav.ts` 的纯函数 ⇒ 本文件对**全部 28 项 × 若干路由**
 * 逐条断言（渲染面另有 `Sidebar.test.tsx` / `SidebarRedesign.test.tsx`）。
 *
 * ## 本文件同时是新 IA 的**表驱动事实源**
 *
 * （issue #7087 + #7369：**6 组 / 19 个组内项 + 3 个一级项**（最前席位「经营看板」+ 尾席位
 * 「商品管理」「企业基础设置」）+ 1 个尾部独立项「通知中心」= **25 项**。
 * 2026-10-17（issue #7087）「工作台」组整组撤销、「每日简报」菜单项删除；
 * 2026-10-20（issue #7369，用户裁定「新增的菜单不能放到仓储与物料下，得加个新大菜单」）
 * 新增组「供应链」（组 key `supply-chain`：入库单 → 供应商 → 采购单），组内项总数不变
 * （原「仓储与物料」组的三个单据节点整组搬出，本组只留库存明细 / 发货单 / 余料台账 / 省料看板）。）
 *
 * `EXPECTED_GROUPS` 逐字写下 issue #5271 的组 key / 组名 / 组内项顺序 —— 它不是从实现读出来的
 * （不是拿 `menuGroups` 反推 `menuGroups`），而是**独立写死的期望值**：实现漂了这里就红。
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import {
  hasPermission,
  isItemVisible,
  filterMenuItems,
  visibleMenuGroups,
  matchesRoute,
  resolveActivePath,
  resolveActiveGroupKey,
  initialExpandedGroups,
  flattenMenu,
  splitGroupsAtTopItemSlot,
  searchMenu,
  landingPath,
  promoteSingleItemGroups,
  hintedMenuItemPath,
  hintedGroupKey,
  FALLBACK_LANDING_PATH,
  type MenuFilterOptions,
} from '@/lib/menu-nav'
import {
  menuGroups,
  standaloneHeadItems,
  standaloneTopItems,
  standaloneItems,
  STANDALONE_TOP_AFTER_GROUP_KEY,
  type MenuItem,
} from '@/config/menu'

/**
 * 新 IA（issue #5778；#5939 +「发货单」；#6404 +「库存明细」；**2026-10-06 用户裁定方案 A1 重排**；
 * **#6573 +第二个一级项「参数总览」**；**#6580 收拢生产管理组、一级项改为「企业基础设置」**；
 * **2026-10-17 issue #7087 撤销「工作台」组、经营看板升为最前席位一级项、删「每日简报」菜单项**）：
 * **6 组 / 19 个组内项 + 3 个一级项 + 1 个尾部独立项 = 25 项**（issue #7369 新增「供应链」组；#7376 新增「报表中心」一级项）。
 *
 * 本表是**独立写死**的期望值（不拿 `menuGroups` 反推 `menuGroups`）= **顺序契约的承载体**：
 * 2026-10-06 的组内重排与一级项落位若被无声改回，这里当场红并具名报出差异。
 */
const EXPECTED_GROUPS: { key: string; name: string; keys: string[] }[] = [
  // 🔴 2026-10-29（issue #8086，用户裁定 Q2/Q5/Q6）：新增「基础资料」（商品管理 / 客户列表 / 供应商 / 价格本）
  // 与「质量」（质检记录 / 返工单）；「商品管理」由一级项降入组内、客户列表移出客户服务、
  // 价格本移出交易管理、供应商移出供应链。组数 6 → 8。
  { key: 'customer-service', name: '客户服务', keys: ['human-sessions', 'knowledge', 'after-sales'] },
  { key: 'basic-data', name: '基础资料', keys: ['products', 'customers', 'suppliers', 'price-books'] },
  { key: 'trade-center', name: '交易管理', keys: ['orders', 'finance'] },
  {
    key: 'production-center',
    name: '生产管理',
    keys: ['production-board', 'production-pool', 'production-piecework'],
  },
  { key: 'quality', name: '质量', keys: ['quality-inspections', 'rework-orders'] },
  { key: 'supply-chain', name: '供应链', keys: ['inbound-orders', 'purchase-orders'] },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    keys: ['stock-ledger', 'stocktakes', 'outbound-orders', 'shipments', 'production-remnants', 'production-saving-board'],
  },
  { key: 'org-center', name: '组织管理', keys: ['employees', 'roles'] },
]
/**
 * 一级项（**不占组**）—— 2026-10-17（issue #7087）起共**三个席位**，位置语义各不相同：
 *
 *   · `EXPECTED_STANDALONE_HEAD` —— **最前席位**（渲染在**所有分组之前**）：用户 2026-10-17 裁定
 *     给「经营看板」。为什么必须最前：`landingPath()` = **第一个可见菜单项**（issue #6758）
 *     ⇒ 放尾席位会让登录落点变成「在线接待」，与用户要的「一进来就直观看到经营看板」正好相反。
 *   · `EXPECTED_STANDALONE_TOP` —— **尾席位**（渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY` 那个组之后）：
 *     用户 2026-10-06 裁定「大菜单项并列」，该常量现取**最后一个组**（`org-center`）
 *     ⇒ 排在**所有可见分组之后**、尾部独立项之前。
 *
 * ⚠️ 尾席位组**不可见**时（实测：七个种子岗位里只有 admin 持 `system:view`）⇒ 一级项**挂到当前
 * 可见分组的末尾**（**不跳到最前**，见 `frontend/admin-web/src/lib/menu-nav.ts` 的
 * `splitGroupsAtTopItemSlot`）⇒ 渲染序 == **最前席位 → 全部分组 → 尾席位 → 尾部独立项**。
 */
/**
 * #6573（2026-10-08 用户裁定方案 C）：新增**第二个**一级项「参数总览」（`/settings/params`）——
 * 它与「商品管理」同级、渲染在**所有分组之后**，顺序 = `menu.ts` 里 `standaloneTopItems` 的数组顺序
 * （`products` → `params`）。
 */
/** 最前席位（issue #7087）：渲染在**所有分组之前**的唯一一项 */
// 报表中心（issue #7376 / #7377）：与经营看板同属经营数据面 ⇒ 最前席位第二项。
const EXPECTED_STANDALONE_HEAD = ['dashboard', 'reports']
const EXPECTED_STANDALONE_TOP = ['settings']
const EXPECTED_STANDALONE = ['notifications']
/** 一级项的**插入位**（本表是独立写死的期望值，不是从实现反推的） */
const SLOT_KEY = STANDALONE_TOP_AFTER_GROUP_KEY
/**
 * 渲染顺序：**最前席位 → 全部分组 → 尾席位 → 尾部独立项**（== `flattenMenu` 的顺序）。
 * ⚠️ 不按 `SLOT_KEY` 切段：2026-10-06 起回落方向 = 「挂到可见分组末尾」⇒ 席位组可见与否
 * **渲染序都一样**（这也正是该回落方向的价值），按席位切段只会把同一件事写两遍。
 */
const ALL_KEYS = [
  ...EXPECTED_STANDALONE_HEAD,
  ...EXPECTED_GROUPS.flatMap((g) => g.keys),
  ...EXPECTED_STANDALONE_TOP,
  ...EXPECTED_STANDALONE,
]

const ADMIN: MenuFilterOptions = { permissions: ['*'], roles: ['admin'] }
const adminFor = (): MenuFilterOptions => ({ ...ADMIN })

/** 可见项 key（按渲染顺序）—— 判据统一走这条路径，避免各测各的 */
const visibleKeys = (opts: MenuFilterOptions): string[] =>
  flattenMenu(
    visibleMenuGroups(menuGroups, opts),
    filterMenuItems(standaloneHeadItems, opts),
    filterMenuItems(standaloneTopItems, opts),
    filterMenuItems(standaloneItems, opts),
  ).map((i) => i.key)

/** 全部可见项（命令面板的输入面） */
const allItems = (opts: MenuFilterOptions = adminFor()) =>
  flattenMenu(
    visibleMenuGroups(menuGroups, opts),
    filterMenuItems(standaloneHeadItems, opts),
    filterMenuItems(standaloneTopItems, opts),
    filterMenuItems(standaloneItems, opts),
  )

describe('新 IA 事实（issue #5778 + #6404 + #6457 + #6573 + #6580 + #7087 + #7140 + #7369：6 组 + 三个一级项 + 尾部独立项 = 28 项，一项不少不减）', () => {
  it('组 key / 组名 / 组顺序逐值相等，且无 `customer-center` / `product-center` / 旧 `production`', () => {
    expect(menuGroups.map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
    expect(menuGroups.map((g) => g.name)).toEqual(EXPECTED_GROUPS.map((g) => g.name))
    // 旧 IA 的四处钉子：`customer-center` 消失；生产管理组 key 由 `production` → `production-center`；
    // #5778：`product-center`（商品与加工项）撤销、`smart-customer-service` 改判为 `customer-service`
    expect(menuGroups.map((g) => g.key)).not.toContain('customer-center')
    expect(menuGroups.map((g) => g.key)).not.toContain('production')
    expect(menuGroups.map((g) => g.key)).not.toContain('product-center')
    expect(menuGroups.map((g) => g.key)).not.toContain('smart-customer-service')
    expect(menuGroups.map((g) => g.name)).not.toContain('商品与加工项')
    expect(menuGroups.map((g) => g.name)).not.toContain('智能客服')
  })

  it('每组组内项 key 序列逐值相等（顺序敏感），且总数恒为 24', () => {
    expect(
      menuGroups.map((g) => ({ key: g.key, keys: g.children.map((c) => c.key) })),
    ).toEqual(EXPECTED_GROUPS.map((g) => ({ key: g.key, keys: g.keys })))
    expect(ALL_KEYS).toHaveLength(28)
    expect(visibleKeys(ADMIN)).toEqual(ALL_KEYS)
  })

  it('🔴 最前席位 =「经营看板」→「报表中心」（#7087 + #7376）：渲染在**所有分组之前**，且不占任何组', () => {
    // 用户 2026-10-17 逐字：「经营看板直接作为一级菜单，移除工作台，这样用户一进来就很直观的看到经营看板了」
    expect(standaloneHeadItems.map((i) => i.key)).toEqual(EXPECTED_STANDALONE_HEAD)
    // 报表中心（issue #7376 / #7377）**紧随其后**：两者同属经营数据面，位置本身是信息架构决定
    expect(standaloneHeadItems.map((i) => i.name)).toEqual(['经营概览', '报表中心'])
    expect(standaloneHeadItems.map((i) => i.path)).toEqual(['/dashboard', '/reports'])
    expect(standaloneHeadItems.map((i) => i.permissionCode)).toEqual(['dashboard:view', 'dashboard:view'])
    // 它**不得**同时出现在任何组里（升为一级项 = 从原组移出）
    const groupedKeys = menuGroups.flatMap((g) => g.children.map((c) => c.key))
    for (const k of EXPECTED_STANDALONE_HEAD) expect(groupedKeys).not.toContain(k)
    // 判别力：旧形态（它属「工作台」组）会让下面两条红 —— `workspace` 组必须**整组**不存在
    expect(menuGroups.map((g) => g.key)).not.toContain('workspace')
    expect(menuGroups.map((g) => g.name)).not.toContain('工作台')
    // 「每日简报」菜单项随之删除（连同菜单级开关字段 `briefingToggle`）
    const allMenuItems = [
      ...menuGroups.flatMap((g) => g.children),
      ...standaloneHeadItems,
      ...standaloneTopItems,
      ...standaloneItems,
    ]
    expect(allMenuItems.map((i) => i.key)).not.toContain('briefing')
    expect(allMenuItems.filter((i) => 'briefingToggle' in i)).toEqual([])
  })

  it('一级项 =「企业基础设置」（#8086：商品管理已降入「基础资料」组；排在**所有分组之后**、不计入任何组）；尾部独立项仍是「通知中心」', () => {
    // 🔴 席位本身是**用户裁定**（2026-10-06 方案 A1：大菜单项并列 ⇒ 尾席位沉到分组之后）
    // ⇒ 写死在期望表里，改常量即红
    expect(STANDALONE_TOP_AFTER_GROUP_KEY).toBe('org-center')
    expect(STANDALONE_TOP_AFTER_GROUP_KEY).toBe(EXPECTED_GROUPS[EXPECTED_GROUPS.length - 1].key)
    expect(EXPECTED_GROUPS.map((g) => g.key)).toContain(STANDALONE_TOP_AFTER_GROUP_KEY)
    expect(standaloneTopItems.map((i) => i.key)).toEqual(EXPECTED_STANDALONE_TOP)
    // 🔴 #8086：商品管理已进「基础资料」组 ⇒ 尾席位只剩「企业基础设置」（#6580 起改名）
    expect(standaloneTopItems.map((i) => i.name)).toEqual(['企业基础设置'])
    expect(standaloneTopItems.map((i) => i.path)).toEqual(['/settings'])
    // 一级项**不得**同时出现在任何组里（升为一级项 = 从原组移出）
    const groupedKeys = menuGroups.flatMap((g) => g.children.map((c) => c.key))
    for (const k of EXPECTED_STANDALONE_TOP) expect(groupedKeys).not.toContain(k)

    expect(standaloneItems.map((i) => i.key)).toEqual(EXPECTED_STANDALONE)
    expect(menuGroups.map((g) => g.key)).not.toContain('notifications')
    expect(menuGroups.map((g) => g.key)).not.toContain('pinned')
  })

  it('flattenMenu 顺序 = 最前席位 → 全部分组 → 尾席位 → 尾部独立项（与侧边栏渲染顺序同源）', () => {
    const flat = allItems().map((i) => i.key)
    // 🔴 issue #7087：第 1 项 = 最前席位「经营看板」（它是 `flattenMenu` 的**第 1 个参数**，
    // 也是登录落点 —— 见下方 `landingPath` 判据）；旧的「工作台组第 1 项」形态已不存在。
    expect(flat[0]).toBe('dashboard')
    // 尾席位（商品管理 / 企业基础设置）仍在**所有分组之后**、通知中心之前
    expect(flat.indexOf('settings')).toBeGreaterThan(flat.indexOf('roles'))
    expect(flat.indexOf('products')).toBeLessThan(flat.indexOf('notifications'))
    expect(flat.indexOf('settings')).toBeLessThan(flat.indexOf('notifications'))
    expect(flat[flat.length - 1]).toBe('notifications')
    // 一级项（最前席位 / 尾席位）与尾部独立项都不带组标签；分组项带
    expect(allItems()[0].groupKey).toBe('')
    expect(allItems()[0].groupName).toBe('')
    expect(allItems().find((i) => i.key === 'products')!.groupName).toBe('基础资料')
    expect(allItems().find((i) => i.key === 'settings')!.groupName).toBe('')
    expect(allItems()[allItems().length - 1].groupName).toBe('')
    expect(allItems().find((i) => i.key === 'orders')!.groupName).toBe('交易管理')
    expect(allItems().find((i) => i.key === 'human-sessions')!.groupName).toBe('客户服务')
  })

  it('🔴 前四个参数必填（判据 = 函数元数 == 4）：漏传最前席位 ⇒ ⌘K 里搜不到经营看板', () => {
    // `flattenMenu(groups, head, top, bottom, topSlotKey = …)`：只有**第 5 个**参数有默认值。
    // 若有人把 `standaloneHead` 改成有默认值（恰好是本次改动最容易犯的错），元数会掉到 3 ⇒ 当场红；
    // 类型侧由 `npx tsc --noEmit` 兜底（调用点漏传参数 = 编译错误，不是静默漂移）。
    expect(flattenMenu.length).toBe(4)
    // 空 groups + 非空 head ⇒ head 项照旧在索引里（不是「没有组就丢掉一级项」）
    expect(flattenMenu([], standaloneHeadItems, [], []).map((i) => i.key))
      .toEqual(['dashboard', 'reports'])
  })
})

describe('hasPermission：无码 = 全员；`*` = 超管通配', () => {
  it.each([
    ['无码（undefined）', undefined, [], true],
    ['无码（空串）', '', [], true],
    ['有码且命中', 'order:list', ['order:list'], true],
    ['有码但未命中', 'order:list', ['product:list'], false],
    ['`*` 通配', 'order:list', ['*'], true],
    ['`*` 通配（码不在列表里也一样放行）', 'processing:manage', ['*'], true],
    ['空权限集', 'order:list', [], false],
  ])('%s', (_name, code, permissions, expected) => {
    expect(hasPermission(code as string | undefined, permissions as string[])).toBe(expected)
  })
})

describe('isItemVisible：两条件（adminOnly ∧ permissionCode）', () => {
  // adminOnly 分支用**合成项**覆盖：真实 `menu.ts` 当前无人使用该字段（下一条断言即证明）
  const adminOnlyItem: MenuItem = { key: 'x', name: 'X', icon: 'Bell', path: '/x', adminOnly: true }
  const codedItem: MenuItem = { key: 'c', name: 'C', icon: 'Bell', path: '/c', permissionCode: 'c:read' }

  it('真实菜单里 `adminOnly` 无使用者 ⇒ 该分支只能靠合成项判（此断言即取证）', () => {
    const withAdminOnly = menuGroups.flatMap((g) => g.children).filter((c) => c.adminOnly)
    expect(withAdminOnly).toEqual([])
    // 面非空自检：上面的空数组不是因为解析失灵（issue #7140 后 = 19 个组内项）
    expect(menuGroups.flatMap((g) => g.children)).toHaveLength(24)
  })

  it('🔴 过滤**只有两条件**（adminOnly ∧ permissionCode）：`briefingToggle` 随「每日简报」菜单项撤掉（issue #7087）', () => {
    // 旧形态的第三条过滤条件（企业开关 ∧ 角色，issue #3468）**已不存在** —— 它随菜单项一起撤掉，
    // 企业开关从此只驱动**经营看板上的结论卡**（`BriefingCard`），不再参与任何菜单显隐。
    // 判据：① `MenuItem` 类型上不再有该字段的**使用者**；② 选项对象里给不给都不会改变可见性。
    const allMenuItems = [
      ...menuGroups.flatMap((g) => g.children),
      ...standaloneHeadItems,
      ...standaloneTopItems,
      ...standaloneItems,
    ]
    expect(allMenuItems.filter((i) => 'briefingToggle' in i)).toEqual([])
    // ② 同一权限集下，带不带（已废弃的）`briefingEnabled` 字段 ⇒ 可见项**逐值相同**
    const opts = { permissions: ['dashboard:view'], roles: [] as string[] }
    expect(filterMenuItems(standaloneHeadItems, opts).map((i) => i.key)).toEqual(['dashboard', 'reports'])
    expect(
      filterMenuItems(standaloneHeadItems, { ...opts, briefingEnabled: true } as MenuFilterOptions)
        .map((i) => i.key),
    ).toEqual(['dashboard', 'reports'])
  })

  it.each([
    ['adminOnly + role=admin', adminOnlyItem, { permissions: [], roles: ['admin'] }, true],
    ['adminOnly + role=operator', adminOnlyItem, { permissions: [], roles: ['operator'] }, false],
    ['adminOnly + roles 缺省', adminOnlyItem, { permissions: [] }, false],
    ['adminOnly + `*` 权限也**不**放行（是角色条件不是权限条件）', adminOnlyItem, { permissions: ['*'] }, false],
    ['有码 + 命中', codedItem, { permissions: ['c:read'] }, true],
    ['有码 + 未命中', codedItem, { permissions: ['c:write'] }, false],
    ['有码 + `*`', codedItem, { permissions: ['*'] }, true],
  ])('%s', (_name, item, opts, expected) => {
    expect(isItemVisible(item as MenuItem, opts as MenuFilterOptions)).toBe(expected)
  })
})

/**
 * 岗位矩阵（issue #6392 · case UI-085 · 2026-10-06「岗位 × 页面」深度验收固化）
 *
 * 为什么单列：`isItemVisible` 只证明**两条件各自**成立，证明不了「**某个真实岗位**登进来到底看得见哪几项」——
 * 2026-10-06 的验收是在真浏览器里逐岗位量出来的（7 岗位 × DOM 实测），本用例把那组读数**固化成判据**。
 *
 * 两处期望都是**独立写死**的（不拿实现反推）：
 *   · `permissions` = 新租户七岗种子逐字（`backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java`）；
 *   · `expected` = 该权限集 ∩ `menu.ts` 各节点 `permissionCode` 后的可见项 key 清单。
 * 🔴 2026-10-17（issue #7087）：口径里**不再有**企业简报开关这一维（`briefingEnabled` 已随
 * 「每日简报」菜单项撤掉）；六个岗位的读数**逐项不变**，只有 `dashboard` 的来源从「工作台组首项」
 * 变成「最前席位一级项」——它在清单里仍是**第 1 项**（这正是把席位放最前的价值）。
 * 突变敏感性：改 `menu.ts` 任一节点的 `permissionCode`、或改 `isItemVisible` 的任一条件 ⇒ 本表必红。
 */
describe('岗位矩阵：role_permissions（种子）× menu.ts 两条件 ⇒ 可见项逐值相等（UI-085）', () => {
  const ROLES: { name: string; permissions: string[]; expected: string[] }[] = [
    {
      name: '客服 customer_service（12 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'customer:view', 'agent:session',
        'processing:view', 'inbound:view', 'after_sales:view', 'knowledge:view',
        'agent:session:manage', 'production:execute', 'order:refund',
      ],
      expected: ['dashboard', 'reports', 'human-sessions', 'knowledge', 'after-sales', 'customers', 'suppliers', 'price-books', 'orders', 'production-pool', 'rework-orders', 'inbound-orders', 'purchase-orders', 'stocktakes', 'outbound-orders', 'shipments', 'notifications']
    },
    {
      name: '销售 sales（9 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'customer:view', 'processing:view',
        'product:list', 'inbound:view', 'order:create', 'production:execute',
      ],
      expected: ['dashboard', 'reports', 'products', 'customers', 'suppliers', 'price-books', 'orders', 'production-pool', 'inbound-orders', 'purchase-orders', 'stock-ledger', 'stocktakes', 'outbound-orders', 'shipments', 'production-saving-board', 'notifications']
    },
    {
      name: '财务 finance（9 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'customer:view', 'finance:view',
        'processing:view', 'inbound:view', 'finance:create', 'production:execute',
      ],
      expected: ['dashboard', 'reports', 'customers', 'suppliers', 'price-books', 'orders', 'finance', 'production-pool', 'inbound-orders', 'purchase-orders', 'stocktakes', 'outbound-orders', 'shipments', 'notifications']
    },
    {
      name: '知识编辑 knowledge_editor（4 码）',
      permissions: ['dashboard:view', 'knowledge:view', 'knowledge:manage', 'product:list'],
      expected: ['dashboard', 'reports', 'knowledge', 'products', 'stock-ledger', 'production-saving-board', 'notifications']
    },
    {
      name: '商品管理员 product_manager（8 码）',
      permissions: [
        'dashboard:view', 'product:list', 'product:create', 'product:category',
        'product:category:view', 'processing:view', 'processing:manage', 'production:view',
      ],
      expected: ['dashboard', 'reports', 'products', 'production-board', 'production-pool', 'production-piecework', 'stock-ledger', 'production-remnants', 'production-saving-board', 'settings', 'notifications']
    },
    {
      name: '运营 operator（26 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'order:update', 'order:create', 'order:refund',
        'product:list', 'product:create', 'product:category', 'product:category:view',
        'processing:view', 'processing:manage', 'processing:update', 'production:view', 'production:execute',
        'inbound:view', 'inbound:create', 'customer:view', 'customer:create', 'finance:view', 'finance:create',
        'agent:session', 'agent:session:manage', 'employee:list', 'after_sales:view', 'knowledge:view',
      ],
      expected: ['dashboard', 'reports', 'human-sessions', 'knowledge', 'after-sales', 'products', 'customers', 'suppliers', 'price-books', 'orders', 'finance', 'production-board', 'production-pool', 'production-piecework', 'rework-orders', 'inbound-orders', 'purchase-orders', 'stock-ledger', 'stocktakes', 'outbound-orders', 'shipments', 'production-remnants', 'production-saving-board', 'employees', 'settings', 'notifications']
    },
  ]

  it.each(ROLES.map((r) => [r.name, r.permissions, r.expected] as const))(
    '%s 的可见项（顺序敏感）逐值相等',
    (_name, permissions, expected) => {
      expect(visibleKeys({ permissions })).toEqual(expected)
    },
  )

  it('🔴 最前席位随 `dashboard:view` 门控（issue #7087）：有码 ⇒ 第 1 项就是它；无码 ⇒ 它整项不在', () => {
    // 六个岗位**都**持 `dashboard:view` ⇒ 每个清单的第 1 项都是「经营看板」（见上表逐值断言）。
    for (const r of ROLES) {
      expect(visibleKeys({ permissions: r.permissions })[0], r.name).toBe('dashboard')
    }
    // 反面：把该码摘掉 ⇒ 最前席位整项消失（**不是**退化成「显示但点进去 403」，
    // 也不是「换成第一个可见项顶在最前」），且首个可见项变成该岗位的第一个分组项。
    const cs = ROLES[0].permissions.filter((p) => p !== 'dashboard:view')
    const without = visibleKeys({ permissions: cs })
    expect(without).not.toContain('dashboard')
    expect(without[0]).toBe('human-sessions')
  })

  it('判别力自证：把某岗位的写码摘掉不改变菜单（菜单只看 permissionCode），改掉一个节点的码必然改变清单', () => {
    // 自证 1：`knowledge:manage` 不是任何菜单项的 permissionCode ⇒ 摘掉它，可见项**不变**
    const ke = ROLES[3].permissions
    expect(visibleKeys({ permissions: ke.filter((p) => p !== 'knowledge:manage') }))
      .toEqual(ROLES[3].expected)
    // 自证 2：`product:list` 是「商品管理 / 省料看板 / 库存明细」三项的码 ⇒ 摘掉它，清单必须**少三项**
    const after = visibleKeys({ permissions: ke.filter((p) => p !== 'product:list') })
    expect(after).not.toContain('products')
    expect(after).not.toContain('production-saving-board')
    expect(after).not.toContain('stock-ledger')
  })
})

describe('filterMenuItems / visibleMenuGroups：过滤保持顺序 + 空组剔除', () => {
  it('filterMenuItems 保持原顺序（不是重排）', () => {
    const items = menuGroups.find((g) => g.key === 'trade-center')!.children
    // #8086：价格本已移入「基础资料」组 ⇒ 本组按菜单自身顺序只剩 销售订单 → 财务对账
    expect(filterMenuItems(items, { permissions: ['finance:view', 'order:list'] }).map((i) => i.key)).toEqual([
      'orders',
      'finance',
    ])
  })

  it('空组**整组**剔除（组内一项不剩 ⇒ 组名也不渲染）', () => {
    // 只有 order:list ⇒ 只剩「交易管理」（仅销售订单）+「仓储与物料」（#5939 起**发货单也用该码**
    // —— 它与销售订单是同一批人在用，故同码不同页；这正是「取既有码、零授权 delta」的可见后果）。
    // 🔴 2026-10-17（issue #7087）：「工作台」组**已整组撤销**（经营看板改为最前席位一级项，
    // 它未出现在本清单里是因为本权限集无 `dashboard:view` —— 与旧口径的可见后果一致）。
    const groups = visibleMenuGroups(menuGroups, { permissions: ['order:list'] })
    // #8086：价格本（order:list）在「基础资料」组 ⇒ 该组也可见（只剩价格本一项）
    expect(groups.map((g) => g.key)).toEqual(['basic-data', 'trade-center', 'inventory-center'])
    expect(
      groups.map((g) => ({ key: g.key, keys: g.children.map((c) => c.key) })),
    ).toEqual([
      { key: 'basic-data', keys: ['price-books'] },
      { key: 'trade-center', keys: ['orders'] },
      { key: 'inventory-center', keys: ['shipments'] },
    ])
    // 反恒真：确实被削过（8 组 → 3 组，5 个空组整组消失）
    expect(menuGroups).toHaveLength(8)
  })

  it('组被过滤时组名/组图标保留原值（不是重建对象）', () => {
    const groups = visibleMenuGroups(menuGroups, adminFor())
    expect(groups.map((g) => ({ key: g.key, name: g.name, icon: g.icon }))).toEqual(
      menuGroups.map((g) => ({ key: g.key, name: g.name, icon: g.icon })),
    )
  })
})

describe('matchesRoute：最长前缀匹配的底座', () => {
  it.each([
    ['/dashboard ↔ /dashboard', '/dashboard', '/dashboard', true],
    ["/dashboard 额外认根路径 /", '/dashboard', '/', true],
    ['/dashboard 不认自己的子路由（既有口径，与重设计前一致）', '/dashboard', '/dashboard/x', false],
    ['/orders 精确', '/orders', '/orders', true],
    ['/orders 认子路径', '/orders', '/orders/new', true],
    ['前缀边界：/orders-archive 不是 /orders 的子路径', '/orders', '/orders-archive', false],
    ['前缀匹配是「自身或子路径」：/production 也认 /production/pool（故高亮必须取最长）', '/production', '/production/pool', true],
    ['/production/pool 不认父路径', '/production/pool', '/production', false],
    ['/production/pool 认子路径', '/production/pool', '/production/pool/9', true],
    ['前缀边界：/production/poo 不是 /production/pool', '/production/pool', '/production/poo', false],
    ['完全无关', '/orders', '/products', false],
    // ── 旧深链别名（issue #4439）────────────────────────────────────────────
    ['旧深链：#4439 生产明细子页 /processing-orders/{id}/production ⇒ /production 必须认', '/production', '/processing-orders/88/production', true],
    ['旧深链：/production 也认旧列表路径 /processing-orders（重定向前）', '/production', '/processing-orders', true],
    ['别名边界：/processing-orders-archive 不是别名 /processing-orders 的子路径', '/production', '/processing-orders-archive', false],
    ['别名只挂在 /production 上：其它项不认 /processing-orders', '/orders', '/processing-orders/88/production', false],
  ])('%s', (_name, itemPath, current, expected) => {
    expect(matchesRoute(itemPath as string, current as string)).toBe(expected)
  })
})

describe('resolveActivePath：命中项里取**最长**（否则会出现两项同时高亮）', () => {
  const allPaths = ALL_PATHS()

  function ALL_PATHS(): string[] {
    return flattenMenu(
      visibleMenuGroups(menuGroups, adminFor()),
      filterMenuItems(standaloneHeadItems, adminFor()),
      filterMenuItems(standaloneTopItems, adminFor()),
      filterMenuItems(standaloneItems, adminFor()),
    ).map((i) => i.path)
  }

  it.each([
    ['/dashboard 归「经营看板」', '/dashboard', '/dashboard'],
    ['根路径 / 归「经营看板」', '/', '/dashboard'],
    ['/orders/new 归「销售订单」', '/orders/new', '/orders'],
    ['/production 归「作业看板」', '/production', '/production'],
    ['/production/pool ↔ /production 同时命中 ⇒ 取最长', '/production/pool', '/production/pool'],
    ['/production/saving-board 同时命中 /production ⇒ 取最长', '/production/saving-board', '/production/saving-board'],
    ['/production/remnants 同时命中 /production ⇒ 取最长', '/production/remnants', '/production/remnants'],
    // 🔴 2026-10-09（issue #6580）：「加工项管理」菜单项已移除（`/production/processing` 现为重定向薄壳、
    // 无菜单节点）⇒ 该深链**只**命中 `/production`（作业看板）⇒ 高亮作业看板（不再是最长命中自己的项）。
    ['旧深链 /production/processing 只命中 /production ⇒ 高亮「作业看板」（#6580 移除该菜单项）', '/production/processing', '/production'],
    ['/inbound-orders 只命中自己', '/inbound-orders', '/inbound-orders'],
    // issue #5844：建单页从弹窗改成独立整页 ⇒ 深链 /inbound-orders/new 必须仍高亮「入库单」
    // （侧边栏 + 面包屑都靠 resolveActivePath；漏了会让新页「哪一项都不高亮」）
    ['/inbound-orders/new 归「入库单」（issue #5844）', '/inbound-orders/new', '/inbound-orders'],
    ['/notifications（独立项）', '/notifications', '/notifications'],
    // issue #4439：真实菜单下的**用户可见判据** —— 旧深链必须高亮「作业看板」
    ['旧深链 /processing-orders/{id}/production ⇒ 高亮「作业看板」（issue #4439）', '/processing-orders/88/production', '/production'],
  ])('%s', (_name, current, expected) => {
    expect(resolveActivePath(allPaths, current as string)).toBe(expected)
  })

  it('最小反例：只有 /production 与 /production/pool 两项时，/production/pool 必须胜出', () => {
    expect(resolveActivePath(['/production', '/production/pool'], '/production/pool')).toBe('/production/pool')
    // 首个命中胜出会给出 '/production'（长度更短）⇒ 该断言即「取最长」的判别力
    expect(resolveActivePath(['/production', '/production/pool'], '/production/pool')!.length).toBeGreaterThan(
      '/production'.length,
    )
  })

  it('#4439 判别力：把别名表去掉 ⇒ 旧深链必然 0 项高亮（这条断言就是它存在的理由）', () => {
    // 正向：别名在 ⇒ 命中「作业看板」
    expect(resolveActivePath(allPaths, '/processing-orders/88/production')).toBe('/production')
    // 反向（判别力自证）：仅用**不含别名的匹配口径**跑同一路径 ⇒ 必须无命中。
    // 这条对照说明：若 `matchesRoute` 退回「只认自身或子路径」，本用例的第一行就会红。
    const withoutAlias = allPaths.filter((p) => {
      if (p === '/dashboard') return false
      return '/processing-orders/88/production' === p || '/processing-orders/88/production'.startsWith(p + '/')
    })
    expect(withoutAlias).toEqual([])
  })

  it('无命中 / pathname 为 null ⇒ null（不得回落成「第一项」）', () => {
    expect(resolveActivePath(allPaths, '/unknown-page')).toBeNull()
    expect(resolveActivePath(allPaths, null)).toBeNull()
  })

  it('🔴 最前席位的高亮与落点同源（issue #7087）：`/` 与 `/dashboard` 都归它', () => {
    // 「菜单看得见」与「点得进」同一把尺子：`resolveActivePath` 的输入面**必须**含最前席位
    // （`Sidebar.tsx` 与 `flattenMenu` 都从 `standaloneHeadItems` 取；漏了 ⇒ 登录落点那一页
    // 侧边栏一项都不高亮）。
    expect(allPaths).toContain('/dashboard')
    expect(resolveActivePath(allPaths, '/dashboard')).toBe('/dashboard')
    expect(resolveActivePath(allPaths, '/')).toBe('/dashboard')
  })
})

describe('resolveActiveGroupKey / initialExpandedGroups：默认只展开当前组', () => {
  it('每个菜单项的路径都归到它**自己所属**的组（22 个组内项逐条穷举；一级项两个席位都不入组）', () => {
    // ⚠️ 这张表**不留豁免**：曾经 `/production/remnants` 与 `/production/saving-board` 被列为
    // 「已知偏差」（同前缀的 `/production` 抢走归组）—— 该偏差已修（见下方专条），
    // 于是两条回归契约表。**留豁免就等于把 bug 写成规格**。
    const cases = EXPECTED_GROUPS.flatMap((g) =>
      g.keys.map((k) => {
        const item = menuGroups.flatMap((x) => x.children).find((c) => c.key === k)!
        return [item.path, g.key] as const
      }),
    )
    expect(cases).toHaveLength(24)
    expect(menuGroups.flatMap((g) => g.children)).toHaveLength(24)
    for (const [path, groupKey] of cases) {
      expect(`${path} ⇒ ${resolveActiveGroupKey(menuGroups, path)}`).toBe(`${path} ⇒ ${groupKey}`)
    }
  })

  it('🔴 最前席位（`/dashboard`）**不属于任何组** ⇒ 归组为 null（issue #7087）', () => {
    // 它由一级项席位承载 ⇒ 无组可展开（与「商品管理」「通知中心」同口径）。
    // 这条是「/dashboard 冷加载时侧边栏应**全部收起**」这一新形态的直接判据 ——
    // 旧形态（它属「工作台」组）会让 `workspace` 展开，而该组已不存在。
    expect(resolveActiveGroupKey(menuGroups, '/dashboard')).toBeNull()
    expect(resolveActiveGroupKey(menuGroups, '/')).toBeNull()
    expect(
      Object.values(initialExpandedGroups(menuGroups, resolveActiveGroupKey(menuGroups, '/dashboard'))),
    ).toEqual(EXPECTED_GROUPS.map(() => false))
  })

  it('重定向型旧路径：/production/processing ⇒ 生产管理（#5778 起加工项归生产组）；/processing ⇒ 归属兜底到「企业基础设置」', () => {
    expect(resolveActiveGroupKey(menuGroups, '/production/processing')).toBe('production-center')
    // /processing 是重定向壳（→ /production/processing；加工项管理已并入「企业基础设置」）：
    // #8085 起走**菜单项归属兜底**（而不是「一项都不亮」）；企业基础设置是尾席位、不属任何组。
    expect(hintedMenuItemPath('/processing')).toBe('/settings')
    expect(resolveActiveGroupKey(menuGroups, '/processing')).toBeNull()
  })

  it('同前缀兄弟项不得抢走归组（回归 #5271 自动验收抓出的真 bug）', () => {
    // 机制：曾用「取**首个**含命中项的组」，而 `/production`（作业看板）按「自身或子路径」前缀匹配
    // **也**命中 `/production/remnants` ⇒ 归到 `production-center`，导致**冷加载**该页时
    // 生产管理被展开、所在组收起，当前项（余料台账 / 省料看板）在侧边栏里**看不见**。
    // 现口径：先按最长前缀定出唯一激活项，再取它所属组。
    expect(resolveActiveGroupKey(menuGroups, '/production/remnants')).toBe('inventory-center')
    expect(resolveActiveGroupKey(menuGroups, '/production/saving-board')).toBe('inventory-center')
    // 判别力：退回「首个命中」口径时下面两条会得 production-center —— 那正是原 bug 的形态
    expect(resolveActiveGroupKey(menuGroups, '/production/remnants')).not.toBe('production-center')
    // 对照：其余同前缀兄弟项本来就对（证明修复没把别的归组搞坏）
    // 🔴 #6580：「加工项管理」菜单项已移除 ⇒ 旧深链 `/production/processing` 归到 `/production`
    // 所属的「生产管理」组（页面随即重定向到 `/settings`）—— 断言形态不变，只更新口径说明。
    expect(resolveActiveGroupKey(menuGroups, '/production/processing')).toBe('production-center')
    expect(resolveActiveGroupKey(menuGroups, '/production/pool')).toBe('production-center')
    // 可观察后果：所在组初值**展开**、被误判的那个组收起 ⇒ 当前项看得见
    const expanded = initialExpandedGroups(menuGroups, resolveActiveGroupKey(menuGroups, '/production/remnants'))
    expect(expanded['inventory-center']).toBe(true)
    expect(expanded['production-center']).toBe(false)
    // 旧重定向页 /production/processing-fees 无对应菜单项 ⇒ 落到 `/production` 所属组（页面随即重定向）
    expect(resolveActiveGroupKey(menuGroups, '/production/processing-fees')).toBe('production-center')
  })

  it('独立项 / 未知路由 / null ⇒ null（独立项不属于任何组）', () => {
    expect(resolveActiveGroupKey(menuGroups, '/notifications')).toBeNull()
    expect(resolveActiveGroupKey(menuGroups, '/unknown-page')).toBeNull()
    expect(resolveActiveGroupKey(menuGroups, null)).toBeNull()
  })

  it('初值：恰好一个组为 true，其余全 false；null ⇒ 全 false', () => {
    const expanded = initialExpandedGroups(menuGroups, 'trade-center')
    expect(Object.keys(expanded)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
    expect(Object.entries(expanded).filter(([, v]) => v)).toEqual([['trade-center', true]])
    expect(Object.values(initialExpandedGroups(menuGroups, null))).toEqual(
      EXPECTED_GROUPS.map(() => false),
    )
    expect(Object.values(initialExpandedGroups(menuGroups, 'not-a-group'))).toEqual(
      EXPECTED_GROUPS.map(() => false),
    )
  })
})

describe('flattenMenu：最前席位 → 全部分组 → 尾席位 → 尾部独立项（命令面板的索引面）', () => {
  const flat = flattenMenu(menuGroups, standaloneHeadItems, standaloneTopItems, standaloneItems)

  it('顺序 = 28 项全部，且与组结构逐项对齐', () => {
    expect(flat.map((i) => i.key)).toEqual(ALL_KEYS)
    expect(flat).toHaveLength(28)
    const expected = EXPECTED_GROUPS.flatMap((g) => g.keys.map((k) => ({ key: k, groupKey: g.key, groupName: g.name })))
    // 🔴 issue #7087：最前席位（「经营看板」）由 `head` 参数承载、**排在最前**；
    // 尾席位一级项仍排在**所有分组之后**（席位组可见与否**同序** —— 见 `ALL_KEYS` 的注释）
    expect(flat.map((i) => ({ key: i.key, groupKey: i.groupKey, groupName: i.groupName }))).toEqual([
      { key: 'dashboard', groupKey: '', groupName: '' },
      // 报表中心（#7376）：同为最前席位、紧随经营看板
      { key: 'reports', groupKey: '', groupName: '' },
      ...expected,
      // 🔴 #8086：商品管理已进「基础资料」组（不再是一级项）
      { key: 'settings', groupKey: '', groupName: '' },
      { key: 'notifications', groupKey: '', groupName: '' },
    ])
  })
})

describe('splitGroupsAtTopItemSlot：一级项的插入位（#5877）', () => {
  it('slot 组在可见分组里 ⇒ head 含 slot 组（含）及其之前，tail 为其余组', () => {
    const { head, tail } = splitGroupsAtTopItemSlot(menuGroups, 'trade-center')
    expect(head.map((g) => g.key)).toEqual(['customer-service', 'basic-data', 'trade-center'])
    expect(tail.map((g) => g.key)).toEqual(
      ['production-center', 'quality', 'supply-chain', 'inventory-center', 'org-center'],
    )
    // 两段拼起来恰好是全量（无重复、无丢失）
    expect([...head, ...tail].map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
  })

  it('slot 取中间组 ⇒ head 含它及之前的所有组（不是「只含它一个」）', () => {
    const { head, tail } = splitGroupsAtTopItemSlot(menuGroups, 'org-center')
    expect(head.map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
    expect(tail.map((g) => g.key)).toEqual([])
  })

  it('🔴 slot 组**不在可见分组里**（权限过滤掉）⇒ head = 全部可见组、tail 为空 = 一级项挂在**可见分组末尾**', () => {
    // 硬要求：一级项**绝不允许跟着 slot 组一起消失**；且回落方向是「挂到末尾」**不是**「跳到最前」
    //（2026-10-06 修正：席位组 `org-center` 只有 admin 持 `system:view` ⇒ 若回落到最前，
    //  「商品管理」会对多数岗位跑到菜单第一行，与「沉底」的裁定正好相反）。
    const visible = visibleMenuGroups(menuGroups, { permissions: ['order:list'], roles: [] })
    // 反恒真：slot 组确实被滤掉了（#5939 起 order:list 还会带出「仓储与物料」组的发货单）
    expect(visible.map((g) => g.key)).toEqual(['basic-data', 'trade-center', 'inventory-center'])
    const { head, tail } = splitGroupsAtTopItemSlot(visible, 'org-center')
    expect(head.map((g) => g.key)).toEqual(['basic-data', 'trade-center', 'inventory-center'])
    expect(tail).toEqual([])
  })

  it('slotKey 为 null（缺省/未配置）⇒ 同上：head 全量、tail 为空', () => {
    const { head, tail } = splitGroupsAtTopItemSlot(menuGroups, null)
    expect(head.map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
    expect(tail).toEqual([])
  })

  it('空输入 ⇒ 两段都是空表（不抛错、不凭空造组）', () => {
    expect(splitGroupsAtTopItemSlot([], 'org-center')).toEqual({ head: [], tail: [] })
  })

  it('纯函数：不修改输入数组（head 是切片，不是原数组）', () => {
    const before = menuGroups.map((g) => g.key)
    const { head } = splitGroupsAtTopItemSlot(menuGroups, 'org-center')
    expect(menuGroups.map((g) => g.key)).toEqual(before)
    expect(head).not.toBe(menuGroups)
  })

  it('🔴 回落口径与 flattenMenu 同源：slot 组不可见时，一级项仍渲染在**可见分组之后**（而不是消失、也不是跳到最前）', () => {
    // 本权限集可见的组 = 基础资料（商品管理 product:list / 价格本 order:list）+ 交易管理（order:list）
    // + 仓储与物料（发货单 order:list / 省料看板 product:list）
    // ⚠️ 本权限集**无** `dashboard:view` ⇒ 最前席位那一项也不在（head 传空表）——
    // 「席位与权限各判各的」正是本条的判别力：尾席位照旧挂在可见分组末尾。
    // 🔴 #8086：商品管理进「基础资料」组 ⇒ 它回到组内（不再挂在尾席位），可见组从 2 个变成 3 个。
    const groups = visibleMenuGroups(menuGroups, { permissions: ['order:list', 'product:list'], roles: [] })
    expect(groups.map((g) => g.key)).toEqual(['basic-data', 'trade-center', 'inventory-center'])
    expect(flattenMenu(groups, [], standaloneTopItems, standaloneItems).map((i) => i.key)).toEqual([
      'products', 'price-books', 'orders',
      'stock-ledger', 'shipments', 'production-saving-board',
      'settings', 'notifications',
    ])
  })
})

describe('searchMenu：命中面 = 菜单名 ∪ 组名 ∪ keywords（+ 排序档位）', () => {
  const items = allItems()

  it('面非空自检：可搜索面 = 28 项', () => {
    expect(items).toHaveLength(28)
  })

  it('空查询 / 纯空白 ⇒ 空数组（面板的「空查询列全量」由调用方实现，不是本函数）', () => {
    expect(searchMenu(items, '')).toEqual([])
    expect(searchMenu(items, '   ')).toEqual([])
    expect(searchMenu(items, '\t\n')).toEqual([])
  })

  it.each([
    ['菜单名前缀（rank 0）', '订单', ['orders']],
    // 🔴 #6580：「加工项管理」「工艺配置」两个菜单项已移除（其 keywords 里的「生产」族别名随之消失）
    // ⇒ 「生产」靠**旧名关键词**「生产看板」命中「作业看板」这一项（rank 2）。
    // ⚠️ 另两项（智能派单 / 计件工资）靠**组名**「生产管理」命中（rank 3，同档内按菜单自身顺序）
    // 🔴 #8086：质检记录 / 返工单已拆到「质量」组（组名不含「生产」）⇒ 命中面回到生产管理的三项
    ['旧名关键词（rank 2）+ 组名（rank 3）', '生产', ['production-board', 'production-pool', 'production-piecework']],
    ['拼音首字母 keywords（rank 2）', 'ddlb', ['orders']],
    ['拼音首字母 keywords（rank 2）', 'yltz', ['production-remnants']],
    ['拼音首字母 keywords（rank 2）', 'sckb', ['production-board']],
    ['大小写不敏感', 'DINGDAN', ['orders']],
    ['组名命中（rank 3）', '仓储', ['stock-ledger', 'stocktakes', 'outbound-orders', 'shipments', 'production-remnants', 'production-saving-board']],
    // 🔴 2026-10-17（issue #7087）：旧**组名**「工作台」不再存在于任何分组的 `groupName` 里，
    // 但它作为**别名**（`menu.ts` 里 `dashboard` 的 keywords）保留 ⇒ 用户按老叫法搜仍能搜到
    // **最前席位**「经营看板」（rank 2，不是组名档 —— 这条同时钉住了「组名档与 keywords 档不是一回事」）。
    ['旧组名别名（rank 2 keywords）', '工作台', ['dashboard']],
    // 🔴 #6580：原样本「加工费」（唯一命中项是已移除的「加工项管理」）改为「配置」——
    // 唯一命中项是一级项「企业基础设置」的 keywords。
    ['keywords 里的中文别名（rank 2）', '配置', ['settings']],
    ['已删除的菜单项搜不到', '简报', []],
    ['无命中 ⇒ []', '不存在的菜单', []],
  ])('%s：`%s`', (_name, query, expected) => {
    expect(searchMenu(items, query as string).map((i) => i.key)).toEqual(expected)
  })

  it('排序档位：菜单名前缀(0) → 菜单名包含(1) → keywords(2) → 组名(3)，同档保持菜单自身顺序', () => {
    // 🔴 #6580：`加工` 现在只剩 production-board 的 keywords['加工单'](2) —— 菜单名含「加工」的
    // 「加工项管理」「工艺配置」两项已移除；`products` 靠**组名**命中的那条在 #5778 已被撤销。
    expect(searchMenu(items, '加工').map((i) => i.key)).toEqual(['production-board'])
    // `工`：两个档位**同时出现**，逐档验证（1 名包含 → 2 keywords「人工」/「加工单」/「工作台」）
    // 🔴 #6580：rank 0 那档随「工艺配置」菜单项移除而**消失**（不再有菜单名以「工」开头的项）——
    // 这是「档位真的在按规则分档」的读数，不是把断言放宽。
    // 🔴 2026-10-17（issue #7087）：rank 3（组名「工作台」）那档**随该组撤销而消失** ——
    // 「经营看板」改由 **rank 2**（keywords「工作台」）命中，且它在扁平索引里是**第 0 项**
    // ⇒ 同档内排在另两项之前（同档按菜单自身顺序 —— 这条读数同时钉住了「最前席位进 ⌘K 索引」）。
    expect(searchMenu(items, '工').map((i) => i.key)).toEqual([
      'after-sales', // rank 1：菜单名「售后工单」包含「工」
      'production-piecework', // rank 1：菜单名「计件工资」包含「工」
      'rework-orders', // rank 1：菜单名「返工单」包含「工」
      'employees', // rank 1：菜单名「员工管理」包含「工」
      'dashboard', // rank 2：keywords「工作台」（且是索引第 0 项 ⇒ 同档最前）
      'human-sessions', // rank 2：keywords「人工」
      'production-board', // rank 2：keywords「加工单」
    ])
    // `lb`：三个 keywords 命中（rank 2）按菜单自身顺序 ⇒ **商品管理 → 客户列表 → 销售订单**
    // （🔴 #8086：商品管理进「基础资料」组、客户列表也进该组，而基础资料组在交易管理之前 ⇒ 顺序改判）
    expect(searchMenu(items, 'lb').map((i) => i.key)).toEqual(['products', 'customers', 'orders'])
  })

  it('命中面**只**来自传入的项：无权限项不在输入面 ⇒ 搜不到（搜索不是绕过权限的口子）', () => {
    const restricted = allItems({ permissions: ['order:list'], roles: [] })
    // 🔴 issue #5699（P4）：经营看板节点码 = `dashboard:view` ⇒ 受限面 = 交易管理的销售订单
    // + **仓储与物料的发货单**（#5939：与销售订单同码 `order:list`，同一批人在用）+ 独立项
    // 价格本（#7375 段 3）同码 `order:list` ⇒ 受限面按菜单自身顺序同样含它（且在销售订单之前）
    expect(restricted.map((i) => i.key)).toEqual(['price-books', 'orders', 'shipments', 'notifications'])
    // `splb`（商品列表的拼音）在全量面里命中，在受限面里必须为空
    expect(searchMenu(items, 'splb').map((i) => i.key)).toEqual(['products'])
    expect(searchMenu(restricted, 'splb')).toEqual([])
    // 反恒真：受限面本身搜得到东西（不是「搜索坏了所以搜不到」）
    expect(searchMenu(restricted, 'ddlb').map((i) => i.key)).toEqual(['orders'])
  })

  it('不修改输入数组（纯函数，稳定可预期）', () => {
    const snapshot = items.map((i) => i.key)
    searchMenu(items, '工')
    expect(items.map((i) => i.key)).toEqual(snapshot)
  })
})

describe('权限过滤的端到端口径（可见项 key 集合，逐条精确断言）', () => {
  /**
   * 「除 `dashboard:view` 外的全部菜单码」—— 用来把**最前席位**单独摘出来判：
   * 它是本轮唯一「靠一个码决定登录落点」的项（`landingPath` = 第一个可见菜单项）。
   */
  const ALL_MENU_CODES_EXCEPT_DASHBOARD = [
    ...new Set(
      [
        ...menuGroups.flatMap((g) => g.children.map((c) => c.permissionCode)),
        ...standaloneHeadItems.map((i) => i.permissionCode),
        ...standaloneTopItems.map((i) => i.permissionCode),
        ...standaloneItems.map((i) => i.permissionCode),
      ].filter((c): c is string => !!c),
    ),
  ].filter((c) => c !== 'dashboard:view')

  it.each([
    [
      '超管 `*` + admin 角色 ⇒ 28 项全可见（含最前席位「经营看板」+「报表中心」）',
      { permissions: ['*'], roles: ['admin'] },
      ALL_KEYS,
    ],
    [
      '🔴 除 `dashboard:view` 外的全部菜单码 ⇒ **恰少最前席位两项**（经营看板 + 报表中心，同码 #7376）',
      // 旧形态里「工作台」组会整组消失（组内两项都挂 `dashboard:view`）；新形态下该组不存在，
      // 唯一被这个码挡掉的就是一级项「经营看板」—— 且它被挡掉时**不**留下空席位（不占位、不留空块）。
      { permissions: ALL_MENU_CODES_EXCEPT_DASHBOARD, roles: ['admin'] },
      ALL_KEYS.filter((k) => k !== 'dashboard' && k !== 'reports'),
    ],
    [
      '生产（读码+管理码）/仓管混合权限 ⇒ 基础资料组 1 项（供应商）+ 生产管理组 2 项 + 供应链组 2 项 + 仓储与物料组 3 项 + 一级项「企业基础设置」（#8086）',
      // issue #5291：作业看板/计件工资挂**读**码 production:view。
      // 🔴 issue #5699（P4）：**每个子菜单恰好一个码** —— 智能派单 = processing:view（该页读码）、
      // 省料看板 = product:list（该页读码）⇒ 本组权限（读码+管理码、无 product:list、无 processing:view）
      // 里这两项**都不在**。
      // 🔴 #6580：「加工项管理」「工艺配置」两个菜单项已移除；一级项「企业基础设置」的节点码
      // = production:view（本权限集**有**）⇒ 它出现在尾部独立项之前。
      {
        permissions: ['dashboard:view', 'production:view', 'processing:manage', 'inbound:view'],
        roles: ['operator'],
      },
      [
        // 顺序 = 渲染顺序：**最前席位两项**先出现（同码 `dashboard:view`，本权限集里有），
        // 然后 生产管理组（作业看板 → 计件工资）→ 供应链组（入库单 → 供应商 → 采购单）
        // → 仓储与物料组（余料台账，issue #7369 起单据三项已搬去供应链组）；
        // 尾席位一级项各自按自己的码判定 —— 「商品管理」要 product:list（本权限集**无** ⇒ 不出现）、
        // 「企业基础设置」要 production:view（本权限集**有** ⇒ 出现）。
        'dashboard', 'reports',
        // 🔴 #8086：供应商在「基础资料」组（组序在供应链之前）⇒ 先出现
        'suppliers',
        'production-board',
        'production-piecework',
        'inbound-orders', 'purchase-orders',
        'stocktakes', 'outbound-orders',
        'production-remnants',
        'settings',
        'notifications',
      ],
    ],
    [
      '只有 inbound:view ⇒ 「基础资料」的供应商 +「供应链」2 项（入库单 / 采购单）+「仓储与物料」的盘点单/出库单（#7373/#7750 同码）；余料要 processing:manage、省料要 product:list ⇒ 那两项不在',
      { permissions: ['inbound:view'] },
      // 🔴 #8086：供应商移入「基础资料」组 ⇒ 组序（基础资料在供应链之前）决定它排最前
      ['suppliers', 'inbound-orders', 'purchase-orders', 'stocktakes', 'outbound-orders', 'notifications'],
    ],
    [
      '只有 processing:manage ⇒ 入库单**不在**（inbound:view 是独立门禁）；生产组整组消失、仓储组只剩余料台账（#5699 P4）',
      { permissions: ['processing:manage'] },
      ['production-remnants', 'notifications'],
    ],
    [
      '只持生产**读**码 production:view ⇒ 作业看板/计件工资/一级项「企业基础设置」（#6580）在；智能派单/余料/省料**不在**',
      { permissions: ['production:view'] },
      [
        // 🔴 #6580：生产管理组只剩「作业看板 → 计件工资」（加工项管理/工艺配置已移除）
        'production-board',
        'production-piecework',
        // 「企业基础设置」节点码 = 本码 ⇒ 一级项落在**所有分组之后**、通知中心之前
        'settings',
        'notifications',
      ],
    ],
    [
      '客服域两码（在线接待 agent:session + 知识库读码 knowledge:view）⇒ 客户服务组 2 项（#5778 组名改判）',
      { permissions: ['agent:session', 'knowledge:view'] },
      ['human-sessions', 'knowledge', 'notifications'],
    ],
    [
      '只持知识库**写**码 knowledge:manage（无读码）⇒ 知识库入口隐藏（issue #5246 读写分权）',
      { permissions: ['knowledge:manage'] },
      ['notifications'],
    ],
    [
      // issue #7377：「返工单」与售后工单**同码** `after_sales:view` ⇒ 只持读码两者都可见
      '只持售后**读**码 after_sales:view ⇒ 售后工单 + 返工单可见（issue #5246 读码 / #7377 同码复用）',
      { permissions: ['after_sales:view'] },
      ['after-sales', 'rework-orders', 'notifications'],
    ],
    [
      '只持售后**写**码 order:refund ⇒ 售后工单隐藏（写码不再等于页面可见性）',
      { permissions: ['order:refund'] },
      ['notifications'],
    ],
    ['零权限 ⇒ 只剩「两侧都无码」的通知中心（#5699 P4：经营看板不再是无码项）', { permissions: [], roles: [] }, ['notifications']],
  ])('%s', (_name, opts, expected) => {
    expect(visibleKeys(opts as MenuFilterOptions)).toEqual(expected)
  })
})

describe('🔴 landingPath（登录落点 = 第一个可见菜单项，issue #6758 / #7087）', () => {
  it('持 `dashboard:view` ⇒ 落点 = `/dashboard`（最前席位；通配与真实岗位两条路径）', () => {
    expect(landingPath({ permissions: ['*'], roles: ['admin'] })).toBe('/dashboard')
    // 真实岗位种子（客服 customer_service 的码，含 `dashboard:view`）
    expect(
      landingPath({ permissions: ['dashboard:view', 'agent:session', 'knowledge:view'], roles: [] }),
    ).toBe('/dashboard')
  })

  it('🔴 不持 `dashboard:view` ⇒ **不落** `/dashboard`，走第一个可见项（逐岗位点名读数）', () => {
    // 只有 order:list ⇒ 首个可见项 = 交易管理的「价格本」（#7375 段 3：组内第一项，交易前置）
    // ⚠️ 六类种子岗位**都持** `dashboard:view` ⇒ 真实落点仍是 /dashboard；本条是「首个可见项」的纯语义探针
    expect(landingPath({ permissions: ['order:list'], roles: [] })).toBe('/price-books')
    // 🔴 #8086：商品管理已进「基础资料」组（该组是最靠前的组、组内首项就是它）⇒ 落点变成 /products
    //（旧形态下它是尾席位、排在所有分组之后 ⇒ 那时落点是仓储与物料的「库存明细」）
    expect(landingPath({ permissions: ['product:list'], roles: [] })).toBe('/products')
    // 只有 agent:session ⇒ 客户服务的「在线接待」
    expect(landingPath({ permissions: ['agent:session'], roles: [] })).toBe('/agent-workspace/human-sessions')
    // 三个都不是 `/dashboard`（这条是上面三条的并联形态）
    for (const perms of [['order:list'], ['product:list'], ['agent:session']]) {
      expect(landingPath({ permissions: perms, roles: [] }), perms.join()).not.toBe('/dashboard')
    }
  })

  it('零权限 ⇒ 落点 = 无码的「通知中心」（**不是**兜底常量 —— 兜底只在连无码项都没有时才走到）', () => {
    // 通知中心（`standaloneItems`）两侧都无码 ⇒ 零权限也可见 ⇒ 它就是第一个可见菜单项。
    expect(landingPath({ permissions: [], roles: [] })).toBe('/notifications')
    // 兜底常量本身仍钉在 `/dashboard`（真实菜单数据下**不可达**的防御分支：通知中心恒可见）；
    // 这条同时防止有人把兜底悄悄改成别的路径。
    expect(FALLBACK_LANDING_PATH).toBe('/dashboard')
  })

  it('判别力自证：把最前席位从落点计算里摘掉（= 旧形态「放尾席位」）⇒ 落点变成「在线接待」', () => {
    // 这正是 issue #7087 逐字给出的理由：若「经营看板」与「商品管理」并列在**尾席位**，
    // `landingPath` 会取到第一个**分组**项 ⇒ 用户登录后看到的不是经营看板。
    // 这条断言就是「席位必须最前」这个用户口径的**可执行形式**（改成尾席位 ⇒ 上面第一条当场红）。
    const withoutHead = flattenMenu(
      visibleMenuGroups(menuGroups, ADMIN),
      [],
      filterMenuItems(standaloneTopItems, ADMIN),
      filterMenuItems(standaloneItems, ADMIN),
    )[0]
    expect(withoutHead.key).toBe('human-sessions')
    expect(withoutHead.path).not.toBe('/dashboard')
  })

// ══════════════════════════════════════════════════════════════════════════════
// issue #8085：单成员组提升 + 非菜单页归属兜底
// ══════════════════════════════════════════════════════════════════════════════
describe('promoteSingleItemGroups：过滤后的单成员组按一级项渲染（issue #8085）', () => {
  const ROLES: Record<string, string[]> = {
    admin: ['*'],
    operator: ['after_sales:view', 'agent:session', 'customer:create', 'customer:view', 'dashboard:view', 'employee:list', 'finance:create', 'finance:view', 'inbound:create', 'inbound:view', 'knowledge:view', 'order:create', 'order:detail', 'order:list', 'order:refund', 'order:update', 'processing:manage', 'processing:update', 'processing:view', 'product:category', 'product:category:view', 'product:create', 'product:list', 'production:execute', 'production:view'],
    customer_service: ['after_sales:view', 'agent:session', 'agent:session:manage', 'customer:view', 'dashboard:view', 'inbound:view', 'knowledge:view', 'order:detail', 'order:list', 'order:refund', 'processing:view', 'production:execute'],
    finance: ['customer:view', 'dashboard:view', 'finance:create', 'finance:view', 'inbound:view', 'order:detail', 'order:list', 'processing:view', 'production:execute'],
    sales: ['customer:view', 'dashboard:view', 'inbound:view', 'order:create', 'order:detail', 'order:list', 'processing:view', 'product:list', 'production:execute'],
    product_manager: ['dashboard:view', 'processing:manage', 'processing:view', 'product:category', 'product:category:view', 'product:create', 'product:list', 'production:view'],
    knowledge_editor: ['dashboard:view', 'knowledge:manage', 'knowledge:view', 'product:list'],
    inspector: ['production:inspect', 'production:view'],
  }

  it('8 个岗位：提升后**不存在**「组内只剩 1 项」的组块（会红：任一岗位出现单成员组）', () => {
    for (const [role, permissions] of Object.entries(ROLES)) {
      const blocks = promoteSingleItemGroups(
        visibleMenuGroups(menuGroups, { permissions, roles: [role === 'admin' ? 'admin' : role] }),
      )
      for (const block of blocks) {
        if (block.kind === 'group') {
          expect(block.items.length, `${role} 的「${block.name}」`).toBeGreaterThan(1)
        }
      }
    }
  })

  it('提升只改形态：项数与项 key 序列与「直接拍平 groups」逐值相等', () => {
    const opts = { permissions: ROLES.finance, roles: ['finance'] }
    const groups = visibleMenuGroups(menuGroups, opts)
    const blocks = promoteSingleItemGroups(groups)
    const fromBlocks = blocks.flatMap((b) => (b.kind === 'group' ? b.items.map((i) => i.key) : [b.item.key]))
    expect(fromBlocks).toEqual(groups.flatMap((g) => g.children.map((i) => i.key)))
    // 提升项带原组名（可追溯）与真实的 item 对象（不是重建的壳）
    // 🔴 #8086：不再写死某个 label（客户列表已移出客户服务）—— 判据改成「第一个单成员组的唯一子项」，
    // 与实现无关、且仍能钉住「提升的是组内那个真对象」。
    const firstSingle = groups.find((g) => g.children.length === 1)!
    const promoted = blocks.find((b) => b.kind === 'promoted')
    expect(promoted && promoted.kind === 'promoted' ? promoted.item.key : null).toBe(firstSingle.children[0].key)
  })

  it('判别力自证：多成员组不会被误提升（admin 全量 ⇒ 0 个 promoted）', () => {
    const blocks = promoteSingleItemGroups(visibleMenuGroups(menuGroups, { permissions: ['*'] }))
    expect(blocks.every((b) => b.kind === 'group')).toBe(true)
  })
})

describe('非菜单页归属兜底（issue #8085）', () => {
  it('真有父级菜单项的页面 ⇒ 高亮该菜单项（/categories → 商品管理）', () => {
    const paths = flattenMenu(
      visibleMenuGroups(menuGroups, { permissions: ['*'] }),
      standaloneHeadItems,
      standaloneTopItems,
      standaloneItems,
    ).map((i) => i.path)
    expect(resolveActivePath(paths, '/categories')).toBe('/products')
  })

  it('只有「域」清楚的页面 ⇒ 提亮分组并自动展开（/approvals → trade-center）', () => {
    expect(resolveActiveGroupKey(menuGroups, '/approvals')).toBe('trade-center')
    expect(resolveActiveGroupKey(menuGroups, '/agent-workspace/sessions')).toBe('customer-service')
    // 最长前缀：/agent-workspace/sessions 不能被 /agent-workspace 抢走（两者同组，此条是口径自证）
    expect(hintedGroupKey('/agent-workspace')).toBe('customer-service')
  })

  it('🔴 类级：**每个**后台静态路由都至少有一个锚点（当前项 或 所属组）—— 新增页面忘了登记归属 ⇒ 当场红', () => {
    const paths = flattenMenu(
      visibleMenuGroups(menuGroups, { permissions: ['*'] }),
      standaloneHeadItems,
      standaloneTopItems,
      standaloneItems,
    ).map((i) => i.path)
    const groups = visibleMenuGroups(menuGroups, { permissions: ['*'] })
    // 有意排除：外部门户/认证页（无侧边栏）+ `/chat`（黄金策对话经右下角 FAB，**有意**不进菜单）
    const EXCLUDED = new Set(['/', '/login', '/register', '/about', '/contact', '/services', '/change-password', '/chat'])
    const routes = dashboardStaticRoutes().filter((r) => !EXCLUDED.has(r))
    expect(routes.length).toBeGreaterThan(30)
    for (const route of routes) {
      const item = resolveActivePath(paths, route)
      const group = resolveActiveGroupKey(groups, route)
      expect(Boolean(item || group), `${route} 在侧边栏没有任何锚点（补 PARENT_ITEM_HINTS / PARENT_GROUP_HINTS）`).toBe(true)
    }
  })
})

/** 枚举 `src/app` 下的**静态**后台路由（跳过动态段 `[id]`、剔除路由组括号） */
function dashboardStaticRoutes(): string[] {
  const appDir = join(process.cwd(), 'src/app')
  const out: string[] = []
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name)
      if (statSync(p).isDirectory()) walk(p)
      else if (name === 'page.tsx') {
        const parts = relative(appDir, dir)
          .split(sep)
          .filter((seg) => seg && !(seg.startsWith('(') && seg.endsWith(')')))
        if (parts.some((seg) => seg.startsWith('['))) continue
        out.push('/' + parts.join('/'))
      }
    }
  }
  walk(appDir)
  return out
}
})
