// @vitest-environment jsdom
// case_ids: UI-108
/**
 * `PageCard` 原语判据（issue #7007）。
 *
 * ## 为什么这个文件存在
 *
 * `PageCard` 是「页内**一级容器**」。改前全仓 **15 处内层容器只有 `border`、没有 `shadow-card`**
 * ⇒ 与 `layout.tsx` 那张整页卡片（`rounded-2xl border shadow-card`）同为「白底 + 边框」，
 * 两层视觉权重相同 ⇒ 页面读起来是**边框套边框**、层级分不开。用户点名的「订单页精美」，
 * 机制上正是订单页把层级放在了**阴影**上（外层阴影 / 内层边框）。
 *
 * 本文件钉的就是那个机制：**内层容器必须自带 `shadow-card`**，以及三条会改变页面行为的
 * props 语义（`padded` / `testId` / `className`）。
 *
 * ## 红证
 *
 * - 去掉 `shadow-card` ⇒ 「自带软分层阴影」当场红（**主判据**）；
 * - 把 `border-neutral-200` 换成 `border-gray-200` ⇒ 红（`gray` 在本仓**没有 token**，
 *   由 `warm-token-palette-guard.test.ts` 硬禁；这里再钉一次实例面）；
 * - 把 `rounded-lg` 换成 `rounded-xl` ⇒ 红（改前圆角三种写法混用 ⇒ 同屏区块起点参差）；
 * - 让 `padded={false}` 仍然加 `p-5` ⇒ 红（整宽表格 + 分页脚的页面会被多套一层内边距）；
 * - 不把 `testId` 透传到 DOM ⇒ 红（**这是关键**：页面级判据大量以 `data-testid="search-area"`
 *   / `"*-empty"` 定位容器 —— 原语不透传就只能退回手写 div，本包 14 页的迁移就不成立）。
 *
 * ⚠️ 文件名是 `.test.ts`（Growth Gate 精确路径）⇒ **不能用 JSX**，一律 `React.createElement`。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createElement as h } from 'react'
import PageCard from '@/components/ui/PageCard'

/**
 * 把 className 切成 token 再断言 —— **不要**用 `className.toContain('flex')` 这种裸子串判据：
 * `flex-shrink-0` 里也含 `flex`、`min-w-[4.5em]` 里也含 `w-[4.5em]`。
 * 本仓实测过这个坑（同批 `SearchPanel.test.ts` 的第一版就这样假绿过：它断言 `w-[4.5em]`，
 * 而真值是**被修的病灶** `min-w-[4.5em]` ⇒ 断言仍然通过）。issue #7007。
 */
function tokens(el: Element): string[] {
  return (el.getAttribute('class') || '').split(/\s+/).filter(Boolean)
}

/** 取到原语渲染出的那个容器 div（本文件里它是 container 的第一个元素） */
function cardEl(ui: Parameters<typeof render>[0]) {
  const { container } = render(ui)
  return container.firstElementChild as HTMLElement
}

describe('PageCard —— 页内一级容器原语（issue #7007）', () => {
  it('自带 shadow-card：内层靠阴影分层，不再与整页卡片同为「边框套边框」—— 主判据', () => {
    // 红证：去掉 `shadow-card` ⇒ 当场红。这条正是「精美」在机制上的最小可测单位：
    // 改前 15 处内层容器都只有 border，两层视觉权重相同。
    const el = cardEl(h(PageCard, null, '内容'))
    expect(el.className).toContain('shadow-card')
  })

  it('形态值只来自 token：白底 + 暖中性边框 + 圆角基数阶', () => {
    const el = cardEl(h(PageCard, null, '内容'))
    expect(el.className).toContain('bg-white')
    // 红证：换成 `border-gray-200` ⇒ 红（`gray` 在本仓没有 token，暖亚麻族的中性边框是
    // `neutral-200`；跨文件硬禁见 warm-token-palette-guard.test.ts，这里钉实例面）。
    expect(el.className).toContain('border-neutral-200')
    expect(el.className).not.toContain('border-gray-')
    // 红证：换成 `rounded` / `rounded-xl` ⇒ 红（改前圆角三种写法混用）。
    expect(el.className).toContain('rounded-lg')
    expect(el.className).not.toContain('rounded-xl')
  })

  it('默认 padded：自带 p-5（统一容器内边距档）', () => {
    expect(cardEl(h(PageCard, null, '内容')).className).toContain('p-5')
  })

  it('padded={false}：整宽表格 + 分页脚的页面不被多套一层内边距', () => {
    // 红证：让 `padded=false` 仍然加 `p-5` ⇒ 红（整宽列表会被内缩，表头与卡片边脱开）。
    const el = cardEl(h(PageCard, { padded: false }, '内容'))
    expect(el.className).not.toContain('p-5')
    // 但形态（阴影 / 边框 / 圆角）**一格都不许少** —— 关掉的只是内边距档，不是分层。
    expect(el.className).toContain('shadow-card')
    expect(el.className).toContain('border-neutral-200')
  })

  it('testId 必须透传到 DOM 的 data-testid —— 本包 14 页迁移的支点', () => {
    // 红证：不透传 ⇒ 红。页面级判据以 `data-testid="search-area"` / `"*-empty"` 定位容器，
    // 不透传就只能退回手写 div ⇒ 本轮「共享原语」的迁移前提不成立。
    render(h(PageCard, { testId: 'search-area' }, [h('span', { key: 'c' }, '内容')]))
    const el = screen.getByTestId('search-area')
    expect(el.className).toContain('shadow-card')
  })

  it('不传 testId 时 DOM 上不出现 data-testid —— 默认不改变既有页面的 DOM', () => {
    // 反向契约：原语要能替换掉原来的手写 div 而**不引入**新属性（否则既有选择器都会漂）。
    // ⚠️ 这里**刻意传空 children**：本判据只问「属性有没有」，与内容无关；
    //    若靠一个字符串 child 来满足 `children` 必填，就把两个无关的东西绑在一起了。
    const el = cardEl(h(PageCard, { children: [] }))
    expect(el.hasAttribute('data-testid')).toBe(false)
  })

  it('className 透传且与基类共存（调用方加 `flex items-center gap-3` 之类的版式修饰）', () => {
    const el = cardEl(h(PageCard, { className: 'flex items-center gap-3' }, [h('span', { key: 'c' }, '内容')]))
    expect(tokens(el)).toContain('flex')
    expect(tokens(el)).toContain('items-center')
    expect(el.className).toContain('shadow-card')
  })

  it('不碰布局语义：children 原样渲染，原语不加栅格 / 不改区块顺序', () => {
    // 架构边界（与 SearchPanel 的「不持有 state」同族）：原语只保证**形态一致**，
    // 栅格列数、区块顺序、留白仍由页面自己定。
    // 红证：若原语给 children 套一层 grid / 包一层额外 div，本判据的元素计数会变。
    const el = cardEl(
      h(PageCard, null, h('span', null, '甲'), h('span', null, '乙')),
    )
    expect(el.children).toHaveLength(2)
    expect(el.textContent).toBe('甲乙')
    expect(tokens(el)).not.toContain('grid')
  })
})
