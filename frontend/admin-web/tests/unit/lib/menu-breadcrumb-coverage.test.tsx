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
 *   ① 面包屑**不止一项**（兜底分支只有一项「工作台」⇒ 一项即漏改）；
 *   ② **末项 label == 该菜单项的 `name`**（把 §15.2 变成**可执行**的定义）。
 *
 * ## 红证（实测，非推理）
 *
 * 删掉 `Header.tsx` 里 `/inbound-orders` 那一行 ⇒ 本文件对应那条**判红**；
 * 还原后全绿。断言强度**只增不减**：它比「逐条手写路径」宽（自动覆盖**将来**新增的菜单项）。
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
import { menuGroups } from '@/config/menu'

/** 侧边栏里**每一个带 `path` 的菜单项**（= 用户点得到的页面） */
const PAGES: { path: string; name: string }[] = (menuGroups as any[]).flatMap((g) =>
  ((g.children ?? []) as any[])
    .filter((c) => !!c.path)
    .map((c) => ({ path: c.path as string, name: c.name as string })),
)

describe('侧边栏菜单 ↔ 面包屑覆盖（issue #5071 / §15.2）', () => {
  it('检出面非空 —— 否则下面每条都在空集上恒真（判据退化）', () => {
    // 实测 17 条（2026-09-21）。写 15 而不是 17：允许菜单增删，但**不允许解析失灵 ⇒ 0 条**。
    expect(PAGES.length).toBeGreaterThanOrEqual(15)
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

    expect(
      crumbs.length,
      `${path} 的面包屑只有 ${crumbs.length} 项（${JSON.stringify(crumbs)}）⇒ 落兜底分支，` +
        `§15.2「面包屑与侧边栏菜单名一致」不成立`,
    ).toBeGreaterThanOrEqual(2)
    expect(
      crumbs[crumbs.length - 1],
      `${path} 的面包屑末项与侧边栏菜单名不一致（应为「${name}」）`,
    ).toBe(name)

    cleanup()
  })
})
