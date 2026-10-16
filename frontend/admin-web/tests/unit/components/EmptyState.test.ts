// @vitest-environment jsdom
// case_ids: UI-104
/**
 * `EmptyState` 共享空态件的接口契约（issue #7007）。
 *
 * 这一份钉的是**四条会被改回去的契约**：
 * ① `testId` 透传成 DOM 的 `data-testid`；**不传时 DOM 上不得出现该属性**
 *    （对应 EmptyState 头注释里「与 `PageCard` 同口径」的承诺 —— 默认不改变 DOM）；
 * ② 四个 `icon` 值各自映射到**不同的** lucide 组件（`package→Package` / `search→Search`
 *    / `file→FileX` / `inbox→Inbox`）—— 四条同时断言「应到的那个在 + 另外三个都不在」，
 *    ⇒ 把映射改成「任意 key 都返回同一个图标」这种静默降级也当场红；
 * ③ 默认 `title`/`description` 逐字，以及给了 `action` 才渲染；
 * ④ 配色已收口到暖色 token：冷灰族（`gray`）+ 冷彩族（`blue/indigo/sky/violet/purple/cyan`）
 *    一个都不得出现在渲染出的 class 上。
 *
 * 取材方式：`className` / `data-testid` 直接断在**渲染结果**上（不是断源码字符串），
 * 只有「冷色族一个都不许有」这条用**源码**做（DOM 只能证明「当前这棵树没有」，
 * 源码才能证明「这个文件的每一处都没有」）。注释里的旧写法已剥掉，不误伤说明文字。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

import EmptyState from '@/components/ui/EmptyState'

/** 冷灰族：本仓没有 gray token ⇒ 任何一处都是漂移（issue #7007 判据 1 的硬禁对象）。 */
const NEUTRAL_GRAY = /(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:gray|slate|zinc|stone)-[0-9]/
/** 冷彩族：语义有歧义 ⇒ 逐包收口，不自造近似色（本包里不许再出现）。 */
const COOL_ACCENT = /(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:blue|indigo|sky|violet|purple|cyan)-[0-9]/

/**
 * 取 `EmptyState.tsx` 里**真实代码**的 class 类色彩工具类（剥掉注释、剥掉历史引用）。
 * jsdom 侧只覆盖「这次渲染出来的树」，源码侧覆盖「这个文件的每一处」。
 */
function sourceColorClasses(): string[] {
  const src = readFileSync(resolve(__dirname, '../../../src/components/ui/EmptyState.tsx'), 'utf8')
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
    .match(/(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-[a-z]+-[0-9][0-9a-z/]*/g) ?? []
}

/** 渲染结果里所有元素的 `class` 属性值，合成一个可扫的字符串 */
function renderedClasses(container: HTMLElement): string {
  return Array.from(container.querySelectorAll('*'))
    .map((el) => el.getAttribute('class') ?? '')
    .join(' ')
}

const FOUR_ICONS = ['package', 'search', 'file', 'inbox'] as const
/** 与 `lucide-mock` 的 stub 命名同口径（`icon-<小写图标名>`） */
const ICON_TEST_ID = {
  package: 'icon-package',
  search: 'icon-search',
  file: 'icon-filex',
  inbox: 'icon-inbox',
} as const

describe('EmptyState（共享空态件，issue #7007）', () => {
  it('传 testId ⇒ 落到 DOM 的 data-testid', () => {
    render(React.createElement(EmptyState, { testId: 'orders-empty' }))
    const root = screen.getByTestId('orders-empty')
    // 锚点必须挂在**容器**上（页面级判据靠它定位整块空态面，不能挂在里面的图标上）
    expect(root.tagName).toBe('DIV')
    expect(root).toHaveTextContent('暂无数据')
  })

  it('不传 testId ⇒ DOM 上不出现 data-testid（默认不改变 DOM）', () => {
    const { container } = render(React.createElement(EmptyState, {}))
    const root = container.firstElementChild as HTMLElement
    // 红证：把 `data-testid={testId}` 改成 `data-testid={testId ?? 'empty-state'}`
    // （或任何兜底值）⇒ 这里当场红 —— 组件默认形态不该多出可被选择的锚点。
    // 注：只判**容器**有没有 —— 里面的图标自带 `data-testid`（lucide mock 的 stub 形态），
    // 那不是本契约的对象，「整棵树一个 testid 都没有」这条断言本身是错的。
    expect(root.hasAttribute('data-testid')).toBe(false)
  })

  it('四个 icon 值各自映射到不同的 lucide 组件（package/search/file/inbox）', () => {
    for (const icon of FOUR_ICONS) {
      const { unmount } = render(React.createElement(EmptyState, { icon }))
      const expected = ICON_TEST_ID[icon]
      // 应到的那个在
      expect(screen.getByTestId(expected)).toBeInTheDocument()
      // 另外三个都不在 ⇒ 「全部落到同一个图标」这种静默降级也红
      for (const other of FOUR_ICONS) {
        if (other !== icon) {
          expect(screen.queryByTestId(ICON_TEST_ID[other])).toBeNull()
        }
      }
      unmount()
    }
  })

  it('默认 title/description 逐字，给了才覆盖；action 给了才渲染', () => {
    const { unmount } = render(React.createElement(EmptyState, {}))
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('暂无数据')
    expect(screen.getByText('当前列表为空')).toBeInTheDocument()
    // 默认档不该凭空多出一个动作区（`queryAllByRole` 返回空数组；`getAllByRole` 找不到会抛）
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    unmount()

    render(
      React.createElement(
        EmptyState,
        { title: '还没有客户', description: '点击右上角新建', action: React.createElement('button', { type: 'button' }, '新建客户') },
      ),
    )
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('还没有客户')
    expect(screen.getByText('点击右上角新建')).toBeInTheDocument()
    // action 传进来的节点真的上屏（不是「传了就丢」）
    expect(screen.getByRole('button', { name: '新建客户' })).toBeInTheDocument()
  })

  it('渲染面配色收口：图标底 = bg-neutral-100，图标 = text-neutral-400，标题/说明 = text-neutral-900/500', () => {
    const { container } = render(React.createElement(EmptyState, {}))
    const iconWrap = screen.getByTestId('icon-inbox').parentElement as HTMLElement
    expect(iconWrap).toHaveClass('bg-neutral-100')
    expect(iconWrap).toHaveClass('rounded-full')
    expect(screen.getByTestId('icon-inbox')).toHaveClass('text-neutral-400')
    expect(screen.getByRole('heading', { level: 3 })).toHaveClass('text-neutral-900')
    expect(screen.getByText('当前列表为空')).toHaveClass('text-neutral-500')
    // 红证：任一处置回 `bg-gray-100` / `text-gray-400` / `text-gray-900` / `text-gray-500`
    // ⇒ 上面四条当场红（改前实测 = 该文件 4 处冷灰）
    expect(renderedClasses(container)).not.toMatch(NEUTRAL_GRAY)
    expect(renderedClasses(container)).not.toMatch(COOL_ACCENT)
  })

  it('源码侧：冷灰族 + 冷彩族一个都不出现（DOM 只证明当前树，源码证明每一处）', () => {
    const classes = sourceColorClasses()
    // 自证扫到了东西（空集恒等于空集 ⇒ 那种绿是假绿）
    expect(classes.length).toBeGreaterThan(0)
    const offenders = classes.filter((c) => NEUTRAL_GRAY.test(c) || COOL_ACCENT.test(c))
    // 红证：把任一 class 改回 `bg-gray-100` / `text-blue-600` ⇒ offenders 当场非空
    expect(offenders).toEqual([])
    // 暖色 token 必须是**在位的**（不是「把所有 class 删光」也能过）
    expect(classes).toContain('bg-neutral-100')
    expect(classes).toContain('text-neutral-400')
    expect(classes).toContain('text-neutral-900')
    expect(classes).toContain('text-neutral-500')
  })
})
