// @vitest-environment jsdom
// case_ids: UI-107
/**
 * `PageHeader` 原语判据（issue #7007）。
 *
 * ## 为什么这个文件存在（两重理由，都要写清楚）
 *
 * ① **实例判据**：本原语是「页面标题层级」这条病根的唯一修法 —— 改前全仓 **26 处手写 `h1`**
 *    且**全部**写 `text-xl`，而 `frontend/admin-web/src/lib/design-tokens.ts` 的 `TYPE_SCALE`
 *    规定 `text-2xl` 才是 h1 档、`text-xl` 是区块标题（h2）档 ⇒ 页面标题与页内区块标题**同档**，
 *    层级读不出来。用户 2026-10-16 逐字说的「只有订单管理的设计是非常精美的，其他的页面没有
 *    这样的感觉」，最结构性的一处就是它。
 * ② **CI QA Growth Gate**：新增的组件源码必须有同名测试（精确路径
 *    `tests/unit/components/PageHeader.test.ts`）⇒ 没有这个文件，PR 直接红。
 *
 * ## 红证（每条关键断言都能指出「改掉什么 ⇒ 当场红」）
 *
 * - 把 `text-2xl` 改回 `text-xl` ⇒ 「标题是 h1 档」当场红（**这条就是本包的主判据**）；
 * - 把 `<h1>` 换成 `<div>` ⇒ 「语义标签」当场红（读屏器靠 h1 建立大纲，`text-2xl` 的 div
 *   对读屏器毫无意义 —— 视觉与语义必须同时到位）；
 * - 去掉 `subtitle &&` 的条件 ⇒ 「不传副标题时不留空 `<p>`」当场红；
 * - 去掉 `actions &&` 的条件 ⇒ 「不传动作区时不留空壳 `div`」当场红（空壳会占 flex 位、
 *   把标题挤窄）；
 * - 把 `items-start` 换成 `items-center` ⇒ 视觉上按钮在有无副标题时会上下跳（**这条是几何
 *   判据，jsdom 量不到，故此处只钉类名，真几何留给真浏览器读图**，如实登记）。
 *
 * ⚠️ 文件名是 `.test.ts`（Growth Gate 按精确路径查存在性，只认 `.ts`）⇒ 本文件**不能用 JSX**，
 * 一律 `React.createElement`。仓内先例：`tests/unit/pages/after-sales-detail.test.tsx`。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createElement as h } from 'react'
import PageHeader from '@/components/ui/PageHeader'

describe('PageHeader —— 页面头共享原语（issue #7007）', () => {
  it('标题渲染成 <h1> 且是 TYPE_SCALE 的 h1 档（text-2xl）—— 本包的主判据', () => {
    render(h(PageHeader, { title: '商品管理' }))
    // 红证：① 改回 `text-xl` ⇒ 红（页面标题与区块标题同档，正是被修的病灶）；
    //       ② 把 `<h1>` 换成 `<div>` ⇒ 红（读屏器大纲里就没有这一页了）。
    const heading = screen.getByRole('heading', { level: 1 })
    expect(heading.textContent).toBe('商品管理')
    expect(heading.className).toContain('text-2xl')
    expect(heading.className).toContain('font-semibold')
    expect(heading.className).toContain('text-neutral-900')
    // 反向：h1 档**不得**退化成 h2 档的字号（这条是「改对」而不是「改宽」的证据）
    expect(heading.className).not.toContain('text-xl')
  })

  it('整仓不许再出现 font-bold 的页头 —— 字重只有 semibold 一支', () => {
    // 改前有两种字重：`font-bold`（分类页）vs `font-semibold`（其余 25 处）⇒ 同一层级的标题
    // 字重不同。原语只有一支。红证：给 h1 加 `font-bold` ⇒ 红。
    render(h(PageHeader, { title: '分类管理' }))
    expect(screen.getByRole('heading', { level: 1 }).className).not.toContain('font-bold')
  })

  it('副标题是可选的：传了才渲染，且不与标题同级', () => {
    const { unmount } = render(h(PageHeader, { title: '客户管理', subtitle: '管理客户信息、标签和互动记录' }))
    const sub = screen.getByText('管理客户信息、标签和互动记录')
    expect(sub.tagName).toBe('P')
    // 副标题是 `text-sm` + `text-neutral-500`：比标题弱两档（字号 + 明度），层级才读得出来
    expect(sub.className).toContain('text-sm')
    expect(sub.className).toContain('text-neutral-500')
    unmount()

    // 不传 ⇒ 不留空 `p`（红证：去掉 `subtitle &&` 的条件 ⇒ 这里会摸到一个空 <p>）
    const { container } = render(h(PageHeader, { title: '客户管理' }))
    expect(container.querySelectorAll('p')).toHaveLength(0)
  })

  it('动作区是可选的：传了原样渲染，不传不留空壳 div', () => {
    const { unmount } = render(
      h(PageHeader, {
        title: '员工管理',
        actions: h('button', { type: 'button' }, '新增员工'),
      }),
    )
    expect(screen.getByRole('button', { name: '新增员工' })).toBeTruthy()
    unmount()

    // 红证：去掉 `actions &&` 的条件 ⇒ 会留下一个空的 flex 容器，把标题的可用宽度挤掉。
    const { container } = render(h(PageHeader, { title: '员工管理' }))
    // 只有外层那一个 div（`flex items-start justify-between gap-4`）+ 标题容器
    expect(container.querySelectorAll('div')).toHaveLength(2)
  })

  it('动作区与标题的纵向对齐用 items-start —— 有无副标题时按钮不上下跳', () => {
    // 口径：`items-start`（标题行高对齐）而不是 `items-center`（居中）——
    // 居中会让「有副标题」时按钮下沉、「无副标题」时上跳，同一批页面里按钮位置不一致。
    // ⚠️ 如实登记：这条**只钉类名**；真实几何（两态下按钮 y 坐标是否一致）jsdom 量不到，
    //    由 `migao-dev-flow` §15.7 的真浏览器读图覆盖（本包 ACCEPTANCE.md 的 12-employees 等）。
    const { container } = render(h(PageHeader, { title: '发货单' }))
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain('items-start')
    expect(root.className).toContain('justify-between')
  })

  it('原语不吃权限码：`canWrite` 类门留在调用方（结构上没有回显权限码的入口）', () => {
    // 与 `AccessDenied` 同族口径：原语**结构上**就不接受权限码 —— 它只渲染 title/subtitle/actions。
    // 红证：若有人给 PageHeader 加一个 `permission` prop 并内部判权，本判据的「props 面」就变了；
    // 这里用「只传 title 时输出里不含任何权限码字样」做可执行的下界。
    const { container } = render(h(PageHeader, { title: '财务对账' }))
    const html = container.innerHTML
    for (const code of ['canWrite', 'order:list', 'employee:write', 'permission']) {
      expect(html).not.toContain(code)
    }
  })

  it('className 透传：调用方要加自己的外层修饰时不被迫退回手写 div', () => {
    const { container } = render(h(PageHeader, { title: '入库单', className: 'mb-2' }))
    expect((container.firstElementChild as HTMLElement).className).toContain('mb-2')
  })
})
