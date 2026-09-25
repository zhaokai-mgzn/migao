// case_ids: UI-028, PR-106, PR-038
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
 * ## 本文件同时是新 IA 的**表驱动事实源**（7 组 21 项，一项不少不减）
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
  searchMenu,
  type MenuFilterOptions,
} from '@/lib/menu-nav'
import { menuGroups, standaloneItems, type MenuItem } from '@/config/menu'

/** 新 IA（issue #5271）：7 组 / 20 个组内项 / 1 个独立项 = 21 项 */
const EXPECTED_GROUPS: { key: string; name: string; keys: string[] }[] = [
  { key: 'workspace', name: '工作台', keys: ['dashboard', 'briefing'] },
  { key: 'smart-customer-service', name: '智能客服', keys: ['human-sessions', 'knowledge'] },
  { key: 'product-center', name: '商品与加工项', keys: ['products', 'processing'] },
  { key: 'trade-center', name: '交易管理', keys: ['orders', 'after-sales', 'customers', 'finance'] },
  {
    key: 'production-center',
    name: '生产管理',
    keys: ['production-board', 'production-pool', 'production-process', 'production-piecework'],
  },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    keys: ['inbound-orders', 'production-remnants', 'production-saving-board'],
  },
  { key: 'org-center', name: '组织管理', keys: ['employees', 'roles', 'settings'] },
]
const EXPECTED_STANDALONE = ['notifications']
const ALL_KEYS = [...EXPECTED_GROUPS.flatMap((g) => g.keys), ...EXPECTED_STANDALONE]

const ADMIN: MenuFilterOptions = { permissions: ['*'], roles: ['admin'], briefingEnabled: true }
const adminFor = (): MenuFilterOptions => ({ ...ADMIN })

/** 可见项 key（按渲染顺序：分组项在前、独立项在后）—— 判据统一走这条路径，避免各测各的 */
const visibleKeys = (opts: MenuFilterOptions): string[] =>
  flattenMenu(visibleMenuGroups(menuGroups, opts), filterMenuItems(standaloneItems, opts)).map(
    (i) => i.key,
  )

/** 全部可见项（命令面板的输入面） */
const allItems = (opts: MenuFilterOptions = adminFor()) =>
  flattenMenu(visibleMenuGroups(menuGroups, opts), filterMenuItems(standaloneItems, opts))

describe('新 IA 事实（issue #5271：7 组 21 项，一项不少不减）', () => {
  it('组 key / 组名 / 组顺序逐值相等，且无 `customer-center`、组 key 不是旧 `production`', () => {
    expect(menuGroups.map((g) => g.key)).toEqual(EXPECTED_GROUPS.map((g) => g.key))
    expect(menuGroups.map((g) => g.name)).toEqual(EXPECTED_GROUPS.map((g) => g.name))
    // 旧 IA 的三处钉子：`customer-center` 组消失；生产管理组 key 由 `production` → `production-center`
    expect(menuGroups.map((g) => g.key)).not.toContain('customer-center')
    expect(menuGroups.map((g) => g.key)).not.toContain('production')
  })

  it('每组组内项 key 序列逐值相等（顺序敏感），且总数恒为 21', () => {
    expect(
      menuGroups.map((g) => ({ key: g.key, keys: g.children.map((c) => c.key) })),
    ).toEqual(EXPECTED_GROUPS.map((g) => ({ key: g.key, keys: g.keys })))
    expect(ALL_KEYS).toHaveLength(21)
    expect(visibleKeys(ADMIN)).toEqual(ALL_KEYS)
  })

  it('独立项仍是「通知中心」（渲染在分组之后，不计入 7 组）', () => {
    expect(standaloneItems.map((i) => i.key)).toEqual(EXPECTED_STANDALONE)
    expect(menuGroups.map((g) => g.key)).not.toContain('notifications')
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
    expect(menuGroups.flatMap((g) => g.children)).toHaveLength(20)
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

describe('filterMenuItems / visibleMenuGroups：过滤保持顺序 + 空组剔除', () => {
  it('filterMenuItems 保持原顺序（不是重排）', () => {
    const items = menuGroups.find((g) => g.key === 'trade-center')!.children
    expect(filterMenuItems(items, { permissions: ['finance:view', 'order:list'] }).map((i) => i.key)).toEqual([
      'orders',
      'finance',
    ])
  })

  it('空组**整组**剔除（组内一项不剩 ⇒ 组名也不渲染）', () => {
    // 只有 order:list ⇒ 只剩「工作台」（经营看板无权限码，全员可见）与「交易管理」（仅订单列表）
    const groups = visibleMenuGroups(menuGroups, { permissions: ['order:list'] })
    expect(groups.map((g) => g.key)).toEqual(['workspace', 'trade-center'])
    expect(
      groups.map((g) => ({ key: g.key, keys: g.children.map((c) => c.key) })),
    ).toEqual([
      { key: 'workspace', keys: ['dashboard'] },
      { key: 'trade-center', keys: ['orders'] },
    ])
    // 反恒真：确实被削过（7 组 → 2 组，5 个空组整组消失）
    expect(menuGroups).toHaveLength(7)
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
    return flattenMenu(visibleMenuGroups(menuGroups, adminFor()), filterMenuItems(standaloneItems, adminFor())).map(
      (i) => i.path,
    )
  }

  it.each([
    ['/dashboard 归「经营看板」', '/dashboard', '/dashboard'],
    ['根路径 / 归「经营看板」', '/', '/dashboard'],
    ['/orders/new 归「订单列表」', '/orders/new', '/orders'],
    ['/production 归「生产看板」', '/production', '/production'],
    ['/production/pool ↔ /production 同时命中 ⇒ 取最长', '/production/pool', '/production/pool'],
    ['/production/saving-board 同时命中 /production ⇒ 取最长', '/production/saving-board', '/production/saving-board'],
    ['/production/remnants 同时命中 /production ⇒ 取最长', '/production/remnants', '/production/remnants'],
    ['/production/processing 同时命中 /production ⇒ 取最长（该项归商品与加工项组）', '/production/processing', '/production/processing'],
    ['/inbound-orders 只命中自己', '/inbound-orders', '/inbound-orders'],
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
  it('每个菜单项的路径都归到它**自己所属**的组（20 项逐条穷举）', () => {
    // ⚠️ 这张表**不留豁免**：曾经 `/production/remnants` 与 `/production/saving-board` 被列为
    // 「已知偏差」（同前缀的 `/production` 抢走归组）—— 该偏差已修（见下方专条），
    // 于是两条回归契约表。**留豁免就等于把 bug 写成规格**。
    const cases = EXPECTED_GROUPS.flatMap((g) =>
      g.keys.map((k) => {
        const item = menuGroups.flatMap((x) => x.children).find((c) => c.key === k)!
        return [item.path, g.key] as const
      }),
    )
    expect(cases).toHaveLength(20)
    expect(menuGroups.flatMap((g) => g.children)).toHaveLength(20)
    for (const [path, groupKey] of cases) {
      expect(`${path} ⇒ ${resolveActiveGroupKey(menuGroups, path)}`).toBe(`${path} ⇒ ${groupKey}`)
    }
  })

  it('重定向型旧路径：/production/processing ⇒ 商品与加工项；/processing 无对应项 ⇒ null', () => {
    expect(resolveActiveGroupKey(menuGroups, '/production/processing')).toBe('product-center')
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
    expect(resolveActiveGroupKey(menuGroups, '/production/processing')).toBe('product-center')
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

describe('flattenMenu：分组项在前、独立项在后（命令面板的索引面）', () => {
  const flat = flattenMenu(menuGroups, standaloneItems)

  it('顺序 = 21 项全部，且与组结构逐项对齐', () => {
    expect(flat.map((i) => i.key)).toEqual(ALL_KEYS)
    expect(flat).toHaveLength(21)
    const expected = EXPECTED_GROUPS.flatMap((g) => g.keys.map((k) => ({ key: k, groupKey: g.key, groupName: g.name })))
    expect(flat.map((i) => ({ key: i.key, groupKey: i.groupKey, groupName: i.groupName }))).toEqual([
      ...expected,
      { key: 'notifications', groupKey: '', groupName: '' },
    ])
  })
})

describe('searchMenu：命中面 = 菜单名 ∪ 组名 ∪ keywords（+ 排序档位）', () => {
  const items = allItems()

  it('面非空自检：可搜索面 = 21 项', () => {
    expect(items).toHaveLength(21)
  })

  it('空查询 / 纯空白 ⇒ 空数组（面板的「空查询列全量」由调用方实现，不是本函数）', () => {
    expect(searchMenu(items, '')).toEqual([])
    expect(searchMenu(items, '   ')).toEqual([])
    expect(searchMenu(items, '\t\n')).toEqual([])
  })

  it.each([
    ['菜单名前缀（rank 0）', '订单', ['orders']],
    ['菜单名前缀（rank 0）', '生产', ['production-board', 'production-pool', 'production-process', 'production-piecework']],
    ['拼音首字母 keywords（rank 2）', 'ddlb', ['orders']],
    ['拼音首字母 keywords（rank 2）', 'yltz', ['production-remnants']],
    ['拼音首字母 keywords（rank 2）', 'sckb', ['production-board']],
    ['大小写不敏感', 'DINGDAN', ['orders']],
    ['组名命中（rank 3）', '仓储', ['inbound-orders', 'production-remnants', 'production-saving-board']],
    ['keywords 里的中文别名（rank 2）', '加工费', ['processing']],
    ['无命中 ⇒ []', '不存在的菜单', []],
  ])('%s：`%s`', (_name, query, expected) => {
    expect(searchMenu(items, query as string).map((i) => i.key)).toEqual(expected)
  })

  it('排序档位：菜单名前缀(0) → 菜单名包含(1) → keywords(2) → 组名(3)，同档保持菜单自身顺序', () => {
    // `加工`：processing 名包含(1) → production-board 的 keywords['加工单'](2) → products 的组名「商品与加工项」(3)
    expect(searchMenu(items, '加工').map((i) => i.key)).toEqual(['processing', 'production-board', 'products'])
    // `工`：四个档位**同时出现**，逐档验证（0 前缀「工艺配置」→ 1 名包含 → 2 keywords「加工单」/「人工」→ 3 组名「工作台」/「商品与加工项」）
    expect(searchMenu(items, '工').map((i) => i.key)).toEqual([
      'production-process', // rank 0：菜单名「工艺配置」以「工」**开头**
      'processing', // rank 1：菜单名包含
      'after-sales', // rank 1：售后工单
      'production-piecework', // rank 1：计件工资
      'employees', // rank 1：员工管理
      'human-sessions', // rank 2：keywords「人工」
      'production-board', // rank 2：keywords「加工单」
      'dashboard', // rank 3：组名「工作台」
      'briefing', // rank 3：组名「工作台」
      'products', // rank 3：组名「商品与加工项」
    ])
    // `lb`：三个 keywords 命中（rank 2）按菜单自身顺序 ⇒ 商品列表 → 订单列表 → 客户列表
    expect(searchMenu(items, 'lb').map((i) => i.key)).toEqual(['products', 'orders', 'customers'])
  })

  it('命中面**只**来自传入的项：无权限项不在输入面 ⇒ 搜不到（搜索不是绕过权限的口子）', () => {
    const restricted = allItems({ permissions: ['order:list'], roles: [] })
    // 经营看板无权限码（全员可见）⇒ 受限面 = 工作台的经营看板 + 交易管理的订单列表 + 独立项
    expect(restricted.map((i) => i.key)).toEqual(['dashboard', 'orders', 'notifications'])
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
      '超管 `*` + admin 角色 + 简报开关开 ⇒ 21 项全可见',
      { permissions: ['*'], roles: ['admin'], briefingEnabled: true },
      ALL_KEYS,
    ],
    [
      '超管但简报开关关 ⇒ 恰少「每日简报」（briefingToggle 独立于权限码）',
      { permissions: ['*'], roles: ['admin'], briefingEnabled: false },
      ALL_KEYS.filter((k) => k !== 'briefing'),
    ],
    [
      '生产（读码+管理码）/仓管混合权限 ⇒ 生产管理组 4 项 + 仓储与物料组 3 项 + 加工项管理',
      // issue #5291：生产看板/工艺配置/计件工资改挂**读**码 production:view，
      // 池看板/余料台账/省料看板仍是 processing:manage（同组不同权）。
      {
        permissions: ['dashboard:view', 'production:view', 'processing:manage', 'inbound:view'],
        roles: ['operator'],
      },
      [
        'dashboard',
        'processing',
        'production-board',
        'production-pool',
        'production-process',
        'production-piecework',
        'inbound-orders',
        'production-remnants',
        'production-saving-board',
        'notifications',
      ],
    ],
    [
      '只有 inbound:view ⇒ 「仓储与物料」组**只剩入库单**（余料/省料要 processing:manage）',
      { permissions: ['inbound:view'] },
      ['dashboard', 'inbound-orders', 'notifications'],
    ],
    [
      '只有 processing:manage ⇒ 入库单**不在**（inbound:view 是独立门禁）；生产组只剩池看板（#5291 同组不同权）',
      { permissions: ['processing:manage'] },
      [
        'dashboard',
        'production-pool',
        'production-remnants',
        'production-saving-board',
        'notifications',
      ],
    ],
    [
      '只持生产**读**码 production:view ⇒ 生产看板/工艺配置/计件工资 + 加工项管理在；池看板/余料/省料**不在**',
      { permissions: ['production:view'] },
      [
        'dashboard',
        'processing',
        'production-board',
        'production-process',
        'production-piecework',
        'notifications',
      ],
    ],
    [
      '客服域两码（在线接待 agent:session + 知识库读码 knowledge:view）⇒ 智能客服组 2 项',
      { permissions: ['agent:session', 'knowledge:view'] },
      ['dashboard', 'human-sessions', 'knowledge', 'notifications'],
    ],
    [
      '只持知识库**写**码 knowledge:manage（无读码）⇒ 知识库入口隐藏（issue #5246 读写分权）',
      { permissions: ['knowledge:manage'] },
      ['dashboard', 'notifications'],
    ],
    [
      '只持售后**读**码 after_sales:view ⇒ 售后工单可见（issue #5246：节点码是读码）',
      { permissions: ['after_sales:view'] },
      ['dashboard', 'after-sales', 'notifications'],
    ],
    [
      '只持售后**写**码 order:refund ⇒ 售后工单隐藏（写码不再等于页面可见性）',
      { permissions: ['order:refund'] },
      ['dashboard', 'notifications'],
    ],
    ['零权限 ⇒ 仅无码项（经营看板）与独立项（通知中心）', { permissions: [], roles: [] }, ['dashboard', 'notifications']],
  ])('%s', (_name, opts, expected) => {
    expect(visibleKeys(opts as MenuFilterOptions)).toEqual(expected)
  })
})