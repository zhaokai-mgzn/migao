// case_ids: PG-038
/**
 * 侧边栏菜单 ↔ 面包屑**覆盖**守卫（issue #5071）—— 治「加了菜单项、忘了面包屑」这一类漏改。
 *
 * ## 病根（同类**已发生两次**，本守卫是第三处的通用解法）
 *
 * `config/menu.ts`（真实侧边栏）与 `components/layout/Header.tsx` 的 `ROUTE_BREADCRUMB_MAP`
 * 是**两份各自维护**的清单：
 *   - `#5034`（V111）新增「入库单」菜单项时，`menu.ts` 加了条目、**匹配表没跟**
 *     ⇒ 该页面包屑落兜底分支、**只剩一项「工作台」**（issue #5071 实测）；
 *   - 「每日简报」`/briefing` 是**同一形态的第二例**（#5071 同批机械对账抓出）。
 *
 * 为什么**没有东西会变红**：`menu.ts` 侧的测试只看菜单本身，`Header.test.tsx` 是**逐条手写路径**
 * 的用例 ⇒ **新增路径无人覆盖**（`migao-dev-flow` §19「不会红的判据」形态；§15.2 要求
 * 「面包屑与侧边栏菜单名一致」，但此前只靠人记得去写那一条用例）。
 *
 * ## 判据（对**每一个**带 `path` 的菜单项，渲染**真实的** `<Header />`）
 *
 *   ① 面包屑**至少一项**（0 项 = 什么都没渲染）；
 *   ② **末项 label == 该菜单项的 `name`**（把 §15.2 变成**可执行**的定义）。
 *
 * 🔴 为什么 ① 从 `>= 2` 改成 `>= 1`（#5877，2026-10-01）：一级项「商品管理」与尾部独立项
 * 「通知中心」**本来就没有父组** ⇒ 面包屑就是**单级**（`Header.tsx` 给「通知中心」的一直是单级）。
 * 原口径 `>= 2` 与它自相矛盾 —— 只因两者**没进检出面**（本文件旧实现只从 `menuGroups` 展开）才没红。
 * ⚠️ 改成 `>= 1` **不是放水**：**「落兜底分支」的判别力由 ② 承担** —— 兜底分支返回的是
 * `[{ label: '工作台', href: '/dashboard' }]`，其末项是「工作台」，**永远不等于**菜单名
 * （没有哪个菜单项叫「工作台」）⇒ 漏改照样红。
 *
 * ## 红证（实测，非推理）
 *
 * 删掉 `Header.tsx` 里 `/inbound-orders` 那一行 ⇒ 本文件对应那条**判红**；
 * 还原后全绿。断言强度**只增不减**：它比「逐条手写路径」宽（自动覆盖**将来**新增的菜单项）。
 * #5877 起另加一条**自动化红证**（`把 /products 摘掉 ⇒ 必须红`，见文件末尾）：因为
 * `ROUTE_BREADCRUMB_MAP` 是模块私有的、无法在运行时注入，那条用**同源文本**做单点变异。
 *
 * ## 边界（如实登记）
 *
 * - 只判**正向**（菜单项 ⇒ 有面包屑）。**反向不判**：面包屑表合法地覆盖非菜单路由
 *   （如 `/processing-orders/{id}/production`「生产明细」、`/agent-workspace/sessions`），
 *   要求「每个面包屑条目都有菜单项」会造**假红**；
 * - 判据取 `nav` 的文本按 `/` 切分（分隔符就是 DOM 里那个字面 `/`）。菜单名均不含 `/`
 *   ⇒ 安全；将来若出现含 `/` 的菜单名，需改用逐 crumb 节点断言（届时本注释即线索）。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import React from 'react'

let mockPathname = '/'

vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({ user: { name: '测试用户' }, logout: vi.fn() }),
}))
vi.mock('@/components/layout/NotificationBell', () => ({
  default: () => null,
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => mockPathname,
}))

import Header from '@/components/layout/Header'
import { menuGroups, standaloneTopItems, standaloneItems } from '@/config/menu'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

type Page = { path: string; name: string }
const withPath = (items: any[]): Page[] =>
  (items ?? []).filter((c) => !!c.path).map((c) => ({ path: c.path as string, name: c.name as string }))

/**
 * 侧边栏里**每一个带 `path` 的菜单项**（= 用户点得到的页面）。
 *
 * 🔴 #5877：检出面必须覆盖**全部三处菜单数组** —— `menuGroups`（组内项）**+**
 * `standaloneTopItems`（一级项，如商品管理）**+** `standaloneItems`（尾部独立项，如通知中心）。
 * 只从 `menuGroups` 展开时，两个 standalone 数组里的项**根本不在检出面里**
 * （= 它们的面包屑怎么错都不会红，实测正是「/products 单级」这条一直没人发现的原因）。
 */
const PAGES: Page[] = [
  ...(menuGroups as any[]).flatMap((g) => withPath(g.children)),
  ...withPath(standaloneTopItems),
  ...withPath(standaloneItems),
]

describe('侧边栏菜单 ↔ 面包屑覆盖（issue #5071 / §15.2）', () => {
  it('检出面非空 —— 否则下面每条都在空集上恒真（判据退化）', () => {
    // 实测 21 条（2026-09-21 是 17 条：当时只从 menuGroups 展开，两个 standalone 数组漏在外面；
    // #5877 补齐后 = 19 组内项 + 1 一级项 + 1 尾部独立项）。写 15 是留增删余量，
    // 但**不允许解析失灵 ⇒ 0 条**。
    expect(PAGES.length).toBeGreaterThanOrEqual(15)
  })

  it('🔴 检出面覆盖三处数组的**并集**（menu.ts 里任何带 path 的菜单项都不得漏）', () => {
    const inGroups = (menuGroups as any[]).flatMap((g) => withPath(g.children))
    const expected = new Set([
      ...inGroups.map((p) => p.path),
      ...withPath(standaloneTopItems).map((p) => p.path),
      ...withPath(standaloneItems).map((p) => p.path),
    ])
    expect(new Set(PAGES.map((p) => p.path))).toEqual(expected)
    // 两个 standalone 数组**确实**在检出面里（各自点名一项，防止将来又被漏掉）
    expect(PAGES.map((p) => p.path)).toContain('/products')       // 一级项
    expect(PAGES.map((p) => p.path)).toContain('/notifications')  // 尾部独立项
    // 反恒真：并集本身不是空的、也不等于「只有组内项」
    expect(expected.size).toBeGreaterThan(inGroups.length)
  })

  it.each(PAGES)('$path ⇒ 面包屑末项 == 侧边栏菜单名「$name」', ({ path, name }) => {
    mockPathname = path
    const { container } = render(<Header />)
    const nav = container.querySelector('nav')
    expect(nav, `${path} 未渲染出面包屑容器`).toBeTruthy()

    const crumbs = (nav!.textContent || '')
      .split('/')
      .map((s) => s.trim())
      .filter(Boolean)

    // #5877：**至少一项**（一级项 / 尾部独立项就是单级面包屑）——「落兜底分支」由下一条末项断言拦
    //（兜底 = `[{ label: '工作台' }]`，末项「工作台」≠ 任何菜单名）。
    expect(
      crumbs.length,
      `${path} 的面包屑一项都没有（${JSON.stringify(crumbs)}）`,
    ).toBeGreaterThanOrEqual(1)
    expect(
      crumbs[crumbs.length - 1],
      `${path} 的面包屑末项与侧边栏菜单名不一致（应为「${name}」）`,
    ).toBe(name)

    cleanup()
  })
})

/** `Header.tsx` 的源码（红证用：`ROUTE_BREADCRUMB_MAP` 是模块私有的，无法在运行时注入） */
const HEADER_SRC = readFileSync(
  join(__dirname, '../../../src/components/layout/Header.tsx'),
  'utf8',
)

/**
 * 面包屑表覆盖的路径（两种形态都要认，否则解析失灵会把 `/dashboard` 误报成「未覆盖」）：
 *   · `p.startsWith('/x')` —— 前缀型；
 *   · `p === '/x'` —— 精确型（`/` 与 `/dashboard` 那条就是这种写法）。
 */
function breadcrumbPrefixes(src: string): string[] {
  return [
    ...[...src.matchAll(/match:\s*\(p\)\s*=>\s*p\.startsWith\('([^']+)'\)/g)].map((m) => m[1]),
    ...[...src.matchAll(/p === '([^']+)'/g)].map((m) => m[1]),
  ]
}

/** 检出面里**没有被任何前缀覆盖**的路径（空 = 全覆盖） */
function uncoveredPages(pages: Page[], prefixes: string[]): string[] {
  return pages
    .filter((p) => !prefixes.some((pre) => p.path === pre || p.path.startsWith(pre + '/')))
    .map((p) => p.path)
}

describe('红证：把一条面包屑从匹配表里摘掉 ⇒ 覆盖判据必须红（#5877）', () => {
  it('真源码：检出面**全部**被匹配表覆盖（正面读数，与上面的渲染判据同源）', () => {
    expect(uncoveredPages(PAGES, breadcrumbPrefixes(HEADER_SRC))).toEqual([])
    // 反恒真：前缀确实被解析出来了（解析失灵 ⇒ 上面那条会「空集上恒真」）
    expect(breadcrumbPrefixes(HEADER_SRC).length).toBeGreaterThanOrEqual(15)
  })

  it('🔴 注入：把 `/products` 那条从匹配表摘掉 ⇒ `/products` 必须出现在未覆盖集里', () => {
    const injected = HEADER_SRC.replace("p.startsWith('/products')", "p.startsWith('/products-disabled')")
    expect(injected).not.toBe(HEADER_SRC)   // 注入必须生效（锚点失配 ⇒ 本判据当场红，而不是假绿）
    expect(uncoveredPages(PAGES, breadcrumbPrefixes(injected))).toEqual(['/products'])
  })
})
