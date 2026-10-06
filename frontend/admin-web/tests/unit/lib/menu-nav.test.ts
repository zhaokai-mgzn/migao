// case_ids: UI-028, PR-106, PR-038, UI-074, UI-085
/**
 * 侧边栏导航**纯函数**穷举（issue #5271）。
 *
 * ## 为什么有本文件
 *
 * 重设计前「权限过滤 / 高亮选中 / 分组展开」三件事全内联在 `Sidebar.tsx` 里 ——
 * 只能靠渲染整个 Sidebar 才能验证（依赖 auth store / next-navigation / lucide 白名单三个替身），
 * 且**无法对「同一路由下哪个项高亮」做表驱动穷举**。issue #5271 把它们抽成
 * `frontend/admin-web/src/lib/menu-nav.ts` 的纯函数 ⇒ 本文件对**全部 21 项 × 若干路由**
 * 逐条断言（渲染面另有 `Sidebar.test.tsx` / `SidebarRedesign.test.tsx`）。
 *
 * ## 本文件同时是新 IA 的**表驱动事实源**（#5778：6 组 + 1 顶部一级项 + 1 尾部独立项 = 21 项）
 *
 * `EXPECTED_GROUPS` 逐字写下 issue #5271 的组 key / 组名 / 组内项顺序 —— 它不是从实现读出来的
 * （不是拿 `menuGroups` 反推 `menuGroups`），而是**独立写死的期望值**：实现漂了这里就红。
 */
import { describe, it, expect } from 'vitest'
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
  type MenuFilterOptions,
} from '@/lib/menu-nav'
import {
  menuGroups,
  standaloneTopItems,
  standaloneItems,
  STANDALONE_TOP_AFTER_GROUP_KEY,
  type MenuItem,
} from '@/config/menu'

/** 新 IA（issue #5778；#5939 +「发货单」；#6404 +「库存明细」）：**6 组 / 21 个组内项 + 1 个顶部一级项 + 1 个尾部独立项 = 23 项** */
const EXPECTED_GROUPS: { key: string; name: string; keys: string[] }[] = [
  { key: 'workspace', name: '工作台', keys: ['dashboard', 'briefing'] },
  {
    key: 'customer-service',
    name: '客户服务',
    keys: ['human-sessions', 'customers', 'knowledge', 'after-sales'],
  },
  { key: 'trade-center', name: '交易管理', keys: ['orders', 'finance'] },
  {
    key: 'production-center',
    name: '生产管理',
    keys: ['production-board', 'production-pool', 'processing', 'production-process', 'production-piecework'],
  },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    keys: ['inbound-orders', 'shipments', 'production-remnants', 'production-saving-board', 'stock-ledger'],
  },
  { key: 'org-center', name: '组织管理', keys: ['employees', 'roles', 'settings'] },
]
/**
 * 一级项（**不占组**）：#5778 起「商品管理」不再占一个单成员组；
 * #5877（用户 2026-10-01 裁定）起渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY` 那个**组之后**
 * （该组不可见时回落到所有分组之前 —— 见 `splitGroupsAtTopItemSlot` 的专条判据）。
 */
const EXPECTED_STANDALONE_TOP = ['products']
const EXPECTED_STANDALONE = ['notifications']
/** 一级项的**插入位**（本表是独立写死的期望值，不是从实现反推的） */
const SLOT_KEY = STANDALONE_TOP_AFTER_GROUP_KEY
/** 渲染顺序：head 组（含 slot 组）→ 一级项 → tail 组 → 尾部独立项（== `flattenMenu` 的顺序） */
const ALL_KEYS = [
  ...EXPECTED_GROUPS.filter((g) => g.key === SLOT_KEY).flatMap((g) => g.keys),
  ...EXPECTED_STANDALONE_TOP,
  ...EXPECTED_GROUPS.filter((g) => g.key !== SLOT_KEY).flatMap((g) => g.keys),
  ...EXPECTED_STANDALONE,
]

const ADMIN: MenuFilterOptions = { permissions: ['*'], roles: ['admin'], briefingEnabled: true }
const adminFor = (): MenuFilterOptions => ({ ...ADMIN })

/** 可见项 key（按渲染顺序）—— 判据统一走这条路径，避免各测各的 */
const visibleKeys = (opts: MenuFilterOptions): string[] =>
  flattenMenu(
    visibleMenuGroups(menuGroups, opts),
    filterMenuItems(standaloneTopItems, opts),
    filterMenuItems(standaloneItems, opts),
  ).map((i) => i.key)

/** 全部可见项（命令面板的输入面） */
const allItems = (opts: MenuFilterOptions = adminFor()) =>
  flattenMenu(
    visibleMenuGroups(menuGroups, opts),
    filterMenuItems(standaloneTopItems, opts),
    filterMenuItems(standaloneItems, opts),
  )

describe('新 IA 事实（issue #5778：6 组 + 一级项 + 独立项 = 21 项，一项不少不减）', () => {
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

  it('每组组内项 key 序列逐值相等（顺序敏感），且总数恒为 23', () => {
    expect(
      menuGroups.map((g) => ({ key: g.key, keys: g.children.map((c) => c.key) })),
    ).toEqual(EXPECTED_GROUPS.map((g) => ({ key: g.key, keys: g.keys })))
    expect(ALL_KEYS).toHaveLength(23)
    expect(visibleKeys(ADMIN)).toEqual(ALL_KEYS)
  })

  it('一级项 =「商品管理」（#5877：渲染在「工作台」组之后、不计入任何组）；尾部独立项仍是「通知中心」', () => {
    // 🔴 席位本身是**用户裁定**（2026-10-01）⇒ 写死在期望表里，改常量即红
    expect(STANDALONE_TOP_AFTER_GROUP_KEY).toBe('workspace')
    expect(EXPECTED_GROUPS.map((g) => g.key)).toContain(STANDALONE_TOP_AFTER_GROUP_KEY)
    expect(standaloneTopItems.map((i) => i.key)).toEqual(EXPECTED_STANDALONE_TOP)
    expect(standaloneTopItems.map((i) => i.name)).toEqual(['商品管理'])
    expect(standaloneTopItems.map((i) => i.path)).toEqual(['/products'])
    // 一级项**不得**同时出现在任何组里（升为一级项 = 从原组移出）
    const groupedKeys = menuGroups.flatMap((g) => g.children.map((c) => c.key))
    for (const k of EXPECTED_STANDALONE_TOP) expect(groupedKeys).not.toContain(k)

    expect(standaloneItems.map((i) => i.key)).toEqual(EXPECTED_STANDALONE)
    expect(menuGroups.map((g) => g.key)).not.toContain('notifications')
    expect(menuGroups.map((g) => g.key)).not.toContain('pinned')
  })

  it('flattenMenu 顺序 = head 组 → 一级项 → tail 组 → 尾部独立项（与侧边栏渲染顺序同源）', () => {
    const flat = allItems().map((i) => i.key)
    // #5877：一级项**不再**在最前 —— 它排在「工作台」组之后、「客户服务」组之前
    expect(flat[0]).toBe('dashboard')
    expect(flat.indexOf('products')).toBeGreaterThan(flat.indexOf('briefing'))
    expect(flat.indexOf('products')).toBeLessThan(flat.indexOf('human-sessions'))
    expect(flat[flat.length - 1]).toBe('notifications')
    // 一级项与尾部独立项都不带组标签；分组项带
    // ⚠️ #5877：`allItems()[0]` 现在是「工作台」组的**组内项**（一级项已不再排在最前）
    expect(allItems()[0].groupName).toBe('工作台')
    expect(allItems().find((i) => i.key === 'products')!.groupName).toBe('')
    expect(allItems()[allItems().length - 1].groupName).toBe('')
    expect(allItems().find((i) => i.key === 'orders')!.groupName).toBe('交易管理')
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

describe('isItemVisible：三条件（adminOnly ∧ briefingToggle ∧ permissionCode）', () => {
  // adminOnly 分支用**合成项**覆盖：真实 `menu.ts` 当前无人使用该字段（下一条断言即证明）
  const adminOnlyItem: MenuItem = { key: 'x', name: 'X', icon: 'Bell', path: '/x', adminOnly: true }
  const briefingItem: MenuItem = {
    key: 'b',
    name: 'B',
    icon: 'Newspaper',
    path: '/b',
    permissionCode: 'dashboard:view',
    briefingToggle: true,
  }
  const codedItem: MenuItem = { key: 'c', name: 'C', icon: 'Bell', path: '/c', permissionCode: 'c:read' }

  it('真实菜单里 `adminOnly` 无使用者 ⇒ 该分支只能靠合成项判（此断言即取证）', () => {
    const withAdminOnly = menuGroups.flatMap((g) => g.children).filter((c) => c.adminOnly)
    expect(withAdminOnly).toEqual([])
    // 面非空自检：上面的空数组不是因为解析失灵
    expect(menuGroups.flatMap((g) => g.children)).toHaveLength(21)
  })

  it.each([
    ['adminOnly + role=admin', adminOnlyItem, { permissions: [], roles: ['admin'] }, true],
    ['adminOnly + role=operator', adminOnlyItem, { permissions: [], roles: ['operator'] }, false],
    ['adminOnly + roles 缺省', adminOnlyItem, { permissions: [] }, false],
    ['adminOnly + `*` 权限也**不**放行（是角色条件不是权限条件）', adminOnlyItem, { permissions: ['*'] }, false],
    ['briefingToggle + 开关开 + 有码', briefingItem, { permissions: ['dashboard:view'], briefingEnabled: true }, true],
    ['briefingToggle + 开关关', briefingItem, { permissions: ['dashboard:view'], briefingEnabled: false }, false],
    ['briefingToggle + 开关缺省（= 关）', briefingItem, { permissions: ['dashboard:view'] }, false],
    ['briefingToggle + 开关开但无码', briefingItem, { permissions: [], briefingEnabled: true }, false],
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
 * 为什么单列：`isItemVisible` 只证明**三条件各自**成立，证明不了「**某个真实岗位**登进来到底看得见哪几项」——
 * 2026-10-06 的验收是在真浏览器里逐岗位量出来的（7 岗位 × DOM 实测），本用例把那组读数**固化成判据**。
 *
 * 两处期望都是**独立写死**的（不拿实现反推）：
 *   · `permissions` = 新租户七岗种子逐字（`backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java`）；
 *   · `expected` = 该权限集 ∩ `menu.ts` 各节点 `permissionCode` 后的可见项 key 清单。
 * 口径：`briefingEnabled = false`（新租户默认，`tenants.briefing_enabled = false`）⇒「每日简报」不在任何清单里。
 * 突变敏感性：改 `menu.ts` 任一节点的 `permissionCode`、或改 `isItemVisible` 的任一条件 ⇒ 本表必红。
 */
describe('岗位矩阵：role_permissions（种子）× menu.ts 三条件 ⇒ 可见项逐值相等（UI-085）', () => {
  const ROLES: { name: string; permissions: string[]; expected: string[] }[] = [
    {
      name: '客服 customer_service（12 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'customer:view', 'agent:session',
        'processing:view', 'inbound:view', 'after_sales:view', 'knowledge:view',
        'agent:session:manage', 'production:execute', 'order:refund',
      ],
      expected: ['dashboard', 'human-sessions', 'customers', 'knowledge', 'after-sales', 'orders',
        'production-pool', 'inbound-orders', 'shipments', 'notifications'],
    },
    {
      name: '销售 sales（9 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'customer:view', 'processing:view',
        'product:list', 'inbound:view', 'order:create', 'production:execute',
      ],
      expected: ['dashboard', 'products', 'customers', 'orders', 'production-pool',
        'inbound-orders', 'shipments', 'production-saving-board', 'stock-ledger', 'notifications'],
    },
    {
      name: '财务 finance（9 码）',
      permissions: [
        'dashboard:view', 'order:list', 'order:detail', 'customer:view', 'finance:view',
        'processing:view', 'inbound:view', 'finance:create', 'production:execute',
      ],
      expected: ['dashboard', 'customers', 'orders', 'finance', 'production-pool',
        'inbound-orders', 'shipments', 'notifications'],
    },
    {
      name: '知识编辑 knowledge_editor（4 码）',
      permissions: ['dashboard:view', 'knowledge:view', 'knowledge:manage', 'product:list'],
      expected: ['dashboard', 'products', 'knowledge', 'production-saving-board', 'stock-ledger', 'notifications'],
    },
    {
      name: '商品管理员 product_manager（8 码）',
      permissions: [
        'dashboard:view', 'product:list', 'product:create', 'product:category',
        'product:category:view', 'processing:view', 'processing:manage', 'production:view',
      ],
      expected: ['dashboard', 'products', 'production-board', 'production-pool', 'processing',
        'production-process', 'production-piecework', 'production-remnants',
        'production-saving-board', 'stock-ledger', 'notifications'],
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
      expected: ['dashboard', 'products', 'human-sessions', 'customers', 'knowledge', 'after-sales',
        'orders', 'finance', 'production-board', 'production-pool', 'processing', 'production-process',
        'production-piecework', 'inbound-orders', 'shipments', 'production-remnants',
        'production-saving-board', 'stock-ledger', 'employees', 'notifications'],
    },
  ]

  it.each(ROLES.map((r) => [r.name, r.permissions, r.expected] as const))(
    '%s 的可见项（顺序敏感）逐值相等',
    (_name, permissions, expected) => {
      expect(visibleKeys({ permissions, briefingEnabled: false })).toEqual(expected)
    },
  )

  it('`briefingEnabled=true` 时「每日简报」才进清单（toggle 分支的岗位级取证）', () => {
    const cs = ROLES[0].permissions
    expect(visibleKeys({ permissions: cs, briefingEnabled: false })).not.toContain('briefing')
    expect(visibleKeys({ permissions: cs, briefingEnabled: true })).toContain('briefing')
  })

  it('判别力自证：把某岗位的写码摘掉不改变菜单（菜单只看 permissionCode），改掉一个节点的码必然改变清单', () => {
    // 自证 1：`knowledge:manage` 不是任何菜单项的 permissionCode ⇒ 摘掉它，可见项**不变**
    const ke = ROLES[3].permissions
    expect(visibleKeys({ permissions: ke.filter((p) => p !== 'knowledge:manage'), briefingEnabled: false }))
      .toEqual(ROLES[3].expected)
    // 自证 2：`product:list` 是「商品管理 / 省料看板 / 库存明细」三项的码 ⇒ 摘掉它，清单必须**少三项**
    const after = visibleKeys({ permissions: ke.filter((p) => p !== 'product:list'), briefingEnabled: false })
    expect(after).not.toContain('products')
    expect(after).not.toContain('production-saving-board')
    expect(after).not.toContain('stock-ledger')
  })
})

describe('filterMenuItems / visibleMenuGroups：过滤保持顺序 + 空组剔除', () => {
  it('filterMenuItems 保持原顺序（不是重排）', () => {
    const items = menuGroups.find((g) => g.key === 'trade-center')!.children
    expect(filterMenuItems(items, { permissions: ['finance:view', 'order:list'] }).map((i) => i.key)).toEqual([
      'orders',
      'finance',
    ])
  })

  it('空组**整组**剔除（组内一项不剩 ⇒ 组名也不渲染）', () => {
    // 只有 order:list ⇒ 只剩「交易管理」（仅订单列表）+「仓储与物料」（#5939 起**发货单也用该码**
    // —— 它与订单列表是同一批人在用，故同码不同页；这正是「取既有码、零授权 delta」的可见后果）。
    // 🔴 issue #5699（P4）：经营看板节点码 = `dashboard:view` ⇒ 无该码时「工作台」**整组消失**
    //（此前它无码 ⇒ 全员可见，与页面/路由守卫的码不一致）。
    const groups = visibleMenuGroups(menuGroups, { permissions: ['order:list'] })
    expect(groups.map((g) => g.key)).toEqual(['trade-center', 'inventory-center'])
    expect(
      groups.map((g) => ({ key: g.key, keys: g.children.map((c) => c.key) })),
    ).toEqual([
      { key: 'trade-center', keys: ['orders'] },
      { key: 'inventory-center', keys: ['shipments'] },
    ])
    // 反恒真：确实被削过（6 组 → 2 组，4 个空组整组消失）
    expect(menuGroups).toHaveLength(6)
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
      filterMenuItems(standaloneTopItems, adminFor()),
      filterMenuItems(standaloneItems, adminFor()),
    ).map((i) => i.path)
  }

  it.each([
    ['/dashboard 归「经营看板」', '/dashboard', '/dashboard'],
    ['根路径 / 归「经营看板」', '/', '/dashboard'],
    ['/orders/new 归「订单列表」', '/orders/new', '/orders'],
    ['/production 归「生产看板」', '/production', '/production'],
    ['/production/pool ↔ /production 同时命中 ⇒ 取最长', '/production/pool', '/production/pool'],
    ['/production/saving-board 同时命中 /production ⇒ 取最长', '/production/saving-board', '/production/saving-board'],
    ['/production/remnants 同时命中 /production ⇒ 取最长', '/production/remnants', '/production/remnants'],
    ['/production/processing 同时命中 /production ⇒ 取最长（#5778 起该项归生产管理组）', '/production/processing', '/production/processing'],
    ['/inbound-orders 只命中自己', '/inbound-orders', '/inbound-orders'],
    // issue #5844：建单页从弹窗改成独立整页 ⇒ 深链 /inbound-orders/new 必须仍高亮「入库单」
    // （侧边栏 + 面包屑都靠 resolveActivePath；漏了会让新页「哪一项都不高亮」）
    ['/inbound-orders/new 归「入库单」（issue #5844）', '/inbound-orders/new', '/inbound-orders'],
    ['/notifications（独立项）', '/notifications', '/notifications'],
    // issue #4439：真实菜单下的**用户可见判据** —— 旧深链必须高亮「生产看板」
    ['旧深链 /processing-orders/{id}/production ⇒ 高亮「生产看板」（issue #4439）', '/processing-orders/88/production', '/production'],
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
    // 正向：别名在 ⇒ 命中「生产看板」
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
})

describe('resolveActiveGroupKey / initialExpandedGroups：默认只展开当前组', () => {
  it('每个菜单项的路径都归到它**自己所属**的组（20 个组内项逐条穷举；#5778 起「商品管理」是一级项，不入组）', () => {
    // ⚠️ 这张表**不留豁免**：曾经 `/production/remnants` 与 `/production/saving-board` 被列为
    // 「已知偏差」（同前缀的 `/production` 抢走归组）—— 该偏差已修（见下方专条），
    // 于是两条回归契约表。**留豁免就等于把 bug 写成规格**。
    const cases = EXPECTED_GROUPS.flatMap((g) =>
      g.keys.map((k) => {
        const item = menuGroups.flatMap((x) => x.children).find((c) => c.key === k)!
        return [item.path, g.key] as const
      }),
    )
    expect(cases).toHaveLength(21)
    expect(menuGroups.flatMap((g) => g.children)).toHaveLength(21)
    for (const [path, groupKey] of cases) {
      expect(`${path} ⇒ ${resolveActiveGroupKey(menuGroups, path)}`).toBe(`${path} ⇒ ${groupKey}`)
    }
  })

  it('重定向型旧路径：/production/processing ⇒ 生产管理（#5778 起加工项归生产组）；/processing 无对应项 ⇒ null', () => {
    expect(resolveActiveGroupKey(menuGroups, '/production/processing')).toBe('production-center')
    // /processing 已无菜单项（重定向页）⇒ 无组可展开（与重设计前「该路径不高亮」一致）
    expect(resolveActiveGroupKey(menuGroups, '/processing')).toBeNull()
  })

  it('同前缀兄弟项不得抢走归组（回归 #5271 自动验收抓出的真 bug）', () => {
    // 机制：曾用「取**首个**含命中项的组」，而 `/production`（生产看板）按「自身或子路径」前缀匹配
    // **也**命中 `/production/remnants` ⇒ 归到 `production-center`，导致**冷加载**该页时
    // 生产管理被展开、所在组收起，当前项（余料台账 / 省料看板）在侧边栏里**看不见**。
    // 现口径：先按最长前缀定出唯一激活项，再取它所属组。
    expect(resolveActiveGroupKey(menuGroups, '/production/remnants')).toBe('inventory-center')
    expect(resolveActiveGroupKey(menuGroups, '/production/saving-board')).toBe('inventory-center')
    // 判别力：退回「首个命中」口径时下面两条会得 production-center —— 那正是原 bug 的形态
    expect(resolveActiveGroupKey(menuGroups, '/production/remnants')).not.toBe('production-center')
    // 对照：其余同前缀兄弟项本来就对（证明修复没把别的归组搞坏）
    // #5778：加工项管理已移入「生产管理」组 ⇒ 它现在**是**同组兄弟项
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

describe('flattenMenu：head 组 → 一级项 → tail 组 → 尾部独立项（命令面板的索引面）', () => {
  const flat = flattenMenu(menuGroups, standaloneTopItems, standaloneItems)

  it('顺序 = 23 项全部，且与组结构逐项对齐', () => {
    expect(flat.map((i) => i.key)).toEqual(ALL_KEYS)
    expect(flat).toHaveLength(23)
    const expected = EXPECTED_GROUPS.flatMap((g) => g.keys.map((k) => ({ key: k, groupKey: g.key, groupName: g.name })))
    // #5877：一级项插在「工作台」组（head）与其余组（tail）之间；不属于任何组 ⇒ 组标签为空
    const headLen = EXPECTED_GROUPS.filter((g) => g.key === SLOT_KEY).flatMap((g) => g.keys).length
    expect(flat.map((i) => ({ key: i.key, groupKey: i.groupKey, groupName: i.groupName }))).toEqual([
      ...expected.slice(0, headLen),
      { key: 'products', groupKey: '', groupName: '' },
      ...expected.slice(headLen),
      { key: 'notifications', groupKey: '', groupName: '' },
    ])
  })
})

describe('splitGroupsAtTopItemSlot：一级项的插入位（#5877）', () => {
  it('slot 组在可见分组里 ⇒ head 含 slot 组（含）及其之前，tail 为其余组', () => {
    const { head, tail } = splitGroupsAtTopItemSlot(menuGroups, 'workspace')
    expect(head.map((g) => g.key)).toEqual(['workspace'])
    expect(tail.map((g) => g.key)).toEqual(
      EXPECTED_GROUPS.filter((g) => g.key !== 'workspace').map((g) => g.key),
    )
    // 两段拼起来恰好是全量（无重复、无丢失）
    expect([...head, ...tail].map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
  })

  it('slot 取中间组 ⇒ head 含它及之前的所有组（不是「只含它一个」）', () => {
    const { head, tail } = splitGroupsAtTopItemSlot(menuGroups, 'trade-center')
    expect(head.map((g) => g.key)).toEqual(['workspace', 'customer-service', 'trade-center'])
    expect(tail.map((g) => g.key)).toEqual(['production-center', 'inventory-center', 'org-center'])
  })

  it('🔴 slot 组**不在可见分组里**（权限过滤掉）⇒ head 为空、tail 全量 = 回落到「所有分组之前」', () => {
    // 这是硬要求：一级项**绝不允许跟着 slot 组一起消失**（最坏退回旧位置，也不能没有入口）
    const visible = visibleMenuGroups(menuGroups, { permissions: ['order:list'], roles: [] })
    // 反恒真：slot 组确实被滤掉了（#5939 起 order:list 还会带出「仓储与物料」组的发货单）
    expect(visible.map((g) => g.key)).toEqual(['trade-center', 'inventory-center'])
    const { head, tail } = splitGroupsAtTopItemSlot(visible, 'workspace')
    expect(head).toEqual([])
    expect(tail.map((g) => g.key)).toEqual(['trade-center', 'inventory-center'])
  })

  it('slotKey 为 null（缺省/未配置）⇒ 同上：head 为空、tail 全量', () => {
    const { head, tail } = splitGroupsAtTopItemSlot(menuGroups, null)
    expect(head).toEqual([])
    expect(tail.map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
  })

  it('空输入 ⇒ 两段都是空表（不抛错、不凭空造组）', () => {
    expect(splitGroupsAtTopItemSlot([], 'workspace')).toEqual({ head: [], tail: [] })
  })

  it('纯函数：不修改输入数组（tail 是切片，不是原数组）', () => {
    const before = menuGroups.map((g) => g.key)
    const { tail } = splitGroupsAtTopItemSlot(menuGroups, 'workspace')
    expect(menuGroups.map((g) => g.key)).toEqual(before)
    expect(tail).not.toBe(menuGroups)
  })

  it('🔴 回落口径与 flattenMenu 同源：slot 组不可见时，一级项仍渲染在**所有分组之前**（而不是消失）', () => {
    // 本权限集可见的组 = 交易管理（order:list）+ 仓储与物料（发货单 order:list / 省料看板 product:list）
    const groups = visibleMenuGroups(menuGroups, { permissions: ['order:list', 'product:list'], roles: [] })
    expect(groups.map((g) => g.key)).toEqual(['trade-center', 'inventory-center'])
    expect(flattenMenu(groups, standaloneTopItems, standaloneItems).map((i) => i.key)).toEqual([
      'products', 'orders', 'shipments', 'production-saving-board', 'stock-ledger', 'notifications',
    ])
  })
})

describe('searchMenu：命中面 = 菜单名 ∪ 组名 ∪ keywords（+ 排序档位）', () => {
  const items = allItems()

  it('面非空自检：可搜索面 = 23 项', () => {
    expect(items).toHaveLength(23)
  })

  it('空查询 / 纯空白 ⇒ 空数组（面板的「空查询列全量」由调用方实现，不是本函数）', () => {
    expect(searchMenu(items, '')).toEqual([])
    expect(searchMenu(items, '   ')).toEqual([])
    expect(searchMenu(items, '\t\n')).toEqual([])
  })

  it.each([
    ['菜单名前缀（rank 0）', '订单', ['orders']],
    // #5778：加工项管理移入生产管理组后，它的 keywords 也含「生产」族别名 ⇒ 命中面随之 +1
    ['菜单名前缀（rank 0）', '生产', ['production-board', 'production-pool', 'processing', 'production-process', 'production-piecework']],
    ['拼音首字母 keywords（rank 2）', 'ddlb', ['orders']],
    ['拼音首字母 keywords（rank 2）', 'yltz', ['production-remnants']],
    ['拼音首字母 keywords（rank 2）', 'sckb', ['production-board']],
    ['大小写不敏感', 'DINGDAN', ['orders']],
    ['组名命中（rank 3）', '仓储', ['inbound-orders', 'shipments', 'production-remnants', 'production-saving-board', 'stock-ledger']],
    ['keywords 里的中文别名（rank 2）', '加工费', ['processing']],
    ['无命中 ⇒ []', '不存在的菜单', []],
  ])('%s：`%s`', (_name, query, expected) => {
    expect(searchMenu(items, query as string).map((i) => i.key)).toEqual(expected)
  })

  it('排序档位：菜单名前缀(0) → 菜单名包含(1) → keywords(2) → 组名(3)，同档保持菜单自身顺序', () => {
    // `加工`：processing 名包含(1) → production-board 的 keywords['加工单'](2)
    // 🔴 #5778：原 rank 3 的 `products`（靠**组名**「商品与加工项」命中）**不再命中** ——
    // 该组已撤销、改判为「商品」，而一级项的组名为空 ⇒ 这条断言随组名改判同步收窄（不是放宽）。
    expect(searchMenu(items, '加工').map((i) => i.key)).toEqual(['processing', 'production-board'])
    // `工`：四个档位**同时出现**，逐档验证（0 前缀「工艺配置」→ 1 名包含 → 2 keywords「加工单」/「人工」→ 3 组名「工作台」/「商品与加工项」）
    expect(searchMenu(items, '工').map((i) => i.key)).toEqual([
      'production-process', // rank 0：菜单名「工艺配置」以「工」**开头**
      'after-sales', // rank 1：菜单名「售后工单」包含「工」
      'processing', // rank 1：菜单名「加工项管理」包含「工」
      'production-piecework', // rank 1：菜单名「计件工资」包含「工」
      'employees', // rank 1：菜单名「员工管理」包含「工」
      'human-sessions', // rank 2：keywords「人工」（同档内按菜单自身顺序）
      'production-board', // rank 2：keywords「加工单」
      'dashboard', // rank 2：keywords「工作台」（该词作为关键词登记在项上，故 rank 2 而非组名档 3）
      'briefing', // rank 2：同上
    ])
    // `lb`：三个 keywords 命中（rank 2）按菜单自身顺序 ⇒ 商品管理 → 客户列表 → 订单列表
    // （#5778：客户列表已由交易管理组移入**客户服务**组，而该组渲染在交易管理组之前 ⇒ 顺序随之改判）
    expect(searchMenu(items, 'lb').map((i) => i.key)).toEqual(['products', 'customers', 'orders'])
  })

  it('命中面**只**来自传入的项：无权限项不在输入面 ⇒ 搜不到（搜索不是绕过权限的口子）', () => {
    const restricted = allItems({ permissions: ['order:list'], roles: [] })
    // 🔴 issue #5699（P4）：经营看板节点码 = `dashboard:view` ⇒ 受限面 = 交易管理的订单列表
    // + **仓储与物料的发货单**（#5939：与订单列表同码 `order:list`，同一批人在用）+ 独立项
    expect(restricted.map((i) => i.key)).toEqual(['orders', 'shipments', 'notifications'])
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
  it.each([
    [
      '超管 `*` + admin 角色 + 简报开关开 ⇒ 23 项全可见',
      { permissions: ['*'], roles: ['admin'], briefingEnabled: true },
      ALL_KEYS,
    ],
    [
      '超管但简报开关关 ⇒ 恰少「每日简报」（briefingToggle 独立于权限码）',
      { permissions: ['*'], roles: ['admin'], briefingEnabled: false },
      ALL_KEYS.filter((k) => k !== 'briefing'),
    ],
    [
      '生产（读码+管理码）/仓管混合权限 ⇒ 生产管理组 3 项 + 仓储与物料组 2 项 + 加工项管理',
      // issue #5291：生产看板/工艺配置/计件工资改挂**读**码 production:view。
      // 🔴 issue #5699（P4）：**每个子菜单恰好一个码** —— 智能派单 = processing:view（该页读码）、
      // 省料看板 = product:list（该页读码）⇒ 本组权限（读码+管理码、无 product:list、无 processing:view）
      // 里这两项**都不在**。
      {
        permissions: ['dashboard:view', 'production:view', 'processing:manage', 'inbound:view'],
        roles: ['operator'],
      },
      [
        // 顺序 = 渲染顺序：一级项在前（本轮该权限集无 product:list ⇒ 商品管理不出现），
        // 然后 工作台 → 生产管理组（生产看板/加工项管理/工艺配置/计件工资）→ 仓储与物料组
        'dashboard',
        'production-board',
        'processing',
        'production-process',
        'production-piecework',
        'inbound-orders',
        'production-remnants',
        'notifications',
      ],
    ],
    [
      '只有 inbound:view ⇒ 「仓储与物料」组**只剩入库单**（余料要 processing:manage、省料要 product:list）',
      { permissions: ['inbound:view'] },
      ['inbound-orders', 'notifications'],
    ],
    [
      '只有 processing:manage ⇒ 入库单**不在**（inbound:view 是独立门禁）；生产组整组消失、仓储组只剩余料台账（#5699 P4）',
      { permissions: ['processing:manage'] },
      ['production-remnants', 'notifications'],
    ],
    [
      '只持生产**读**码 production:view ⇒ 生产看板/加工项管理/工艺配置/计件工资在；智能派单/余料/省料**不在**',
      { permissions: ['production:view'] },
      [
        // #5778：`processing`（加工项管理）现属**生产管理**组（原属已撤销的 `product-center` 组）
        'production-board',
        'processing',
        'production-process',
        'production-piecework',
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
      '只持售后**读**码 after_sales:view ⇒ 售后工单可见（issue #5246：节点码是读码）',
      { permissions: ['after_sales:view'] },
      ['after-sales', 'notifications'],
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