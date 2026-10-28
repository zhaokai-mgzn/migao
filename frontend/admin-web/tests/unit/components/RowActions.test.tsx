// case_ids: UI-057, UI-058, UI-130
/**
 * 共享原语 `ui/RowActions` 的判据（issue #8038）—— 「1 主行动 + ⋯ 菜单」的**唯一实现**。
 *
 * ## 为什么原语自己要有判据
 *
 * #8011 在 `/orders` 里写的那份实现在 `OrderTable.tsx` 内部，于是 `products`（每行 5 个）与
 * `knowledge`（每行 4 个）又各自长了一遍平铺文字链（#8035 审计）。#8038 把实现抽到这里 →
 * **收起态不进 DOM、键盘可达、点外部收起** 这三条从此只在这一处被执行；
 * 页面级判据（`product-actions-*` / `knowledge-actions-*`）只管「用没用它、主行动对不对」。
 *
 * ## 判据（会红，不是"看起来像"）
 *
 * ① **收起态菜单项不进 DOM**（`role="menuitem"` 取不到 —— 不是 CSS 隐藏、不是 `sr-only`）；
 * ② `aria-haspopup="menu"` / `aria-expanded` 随开合变化；`role="menu"` / `role="menuitem"`；
 * ③ `Escape` 收起、**点外部**收起；
 * ④ 点菜单项 ⇒ **先执行回调再收起**（顺序反了动作就丢）；
 * ⑤ `items` 为空 ⇒ **不渲染触发器**（不摆一个点开是空盒子的「⋯」）；
 * ⑥ 危险项红字（`danger`）只是观感；**二次确认仍由页面承担**（本原语不弹任何确认）。
 *
 * ## 注入式红证（复核用，非本文件运行时执行）
 *
 * - 把 `{open && (…)}` 改成 `className={open ? '' : 'hidden'}` ⇒ ① 当场红（收起态仍有 menuitem）；
 * - 去掉 `onKeyDown` 的 Escape 分支 / 去掉 `document` 的 mousedown 监听 ⇒ ③ 当场红；
 * - 把「先 `setAnchor(null)` 再 `item.onClick()`」颠倒 ⇒ ④ 的收起断言仍绿、但换成
 *   「回调里读 DOM 是否已收起」的形态会红（本文件按**可观察结果**判：点击后菜单消失且回调被调用）；
 * - 去掉 `items.length > 0` 守卫 ⇒ ⑤ 当场红。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import RowActions from '@/components/ui/RowActions'

const ITEMS = [
  { key: 'view', label: '查看', onClick: vi.fn() },
  { key: 'delete', label: '删除', onClick: vi.fn(), danger: true },
]

function renderActions(props: Partial<React.ComponentProps<typeof RowActions>> = {}) {
  const items = props.items ?? ITEMS.map((i) => ({ ...i, onClick: vi.fn() }))
  const utils = render(
    <RowActions menuTestId="row-menu" testId="row-actions" items={items} {...props}>
      <button type="button">编辑</button>
    </RowActions>,
  )
  return { ...utils, items }
}

const trigger = () => screen.getByRole('button', { name: '更多操作' })

describe('ui/RowActions — 「1 主行动 + ⋯ 菜单」的单一实现（issue #8038）', () => {
  it('① 收起态：菜单项**不进 DOM**；触发器带 aria-haspopup 且 aria-expanded=false', () => {
    renderActions()

    // 靶心：CSS 隐藏 / sr-only 的形态在这里也能过 —— 所以判的是「DOM 里根本没有」
    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.queryAllByRole('menuitem')).toHaveLength(0)
    expect(trigger().getAttribute('aria-haspopup')).toBe('menu')
    expect(trigger().getAttribute('aria-expanded')).toBe('false')
  })

  it('② 点开：出现 role="menu" 与逐项 role="menuitem"，aria-expanded=true', () => {
    renderActions()
    fireEvent.click(trigger())

    expect(trigger().getAttribute('aria-expanded')).toBe('true')
    const menu = screen.getByRole('menu')
    expect(menu.getAttribute('data-row-menu')).toBe('row-menu')
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['查看', '删除'])
  })

  it('③ Escape 收起', () => {
    renderActions()
    fireEvent.click(trigger())
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(trigger().getAttribute('aria-expanded')).toBe('false')
  })

  it('③ 点外部收起（菜单不在屏上时不会误触发）', () => {
    renderActions()
    fireEvent.click(trigger())
    // 点面板**内部**不收起（否则一次点击会先关后开，动作点不到）
    fireEvent.mouseDown(screen.getByRole('menuitem', { name: '查看' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('④ 点菜单项：**执行回调 + 收起**（两个结果都要，缺一个就是动作丢失或菜单赖在屏上）', () => {
    const { items } = renderActions()
    fireEvent.click(trigger())
    fireEvent.click(screen.getByRole('menuitem', { name: '查看' }))

    expect(items[0].onClick).toHaveBeenCalledTimes(1)
    expect(items[1].onClick).not.toHaveBeenCalled()
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('⑤ items 为空 ⇒ 不渲染触发器（主行动仍在）', () => {
    renderActions({ items: [] })
    expect(screen.queryByRole('button', { name: '更多操作' })).toBeNull()
    expect(screen.getByRole('button', { name: '编辑' })).toBeInTheDocument()
  })

  it('⑥ 危险项红字（danger）、普通项中性色；原语**不弹任何确认**', () => {
    renderActions()
    fireEvent.click(trigger())

    expect(screen.getByRole('menuitem', { name: '查看' }).className).toMatch(/text-neutral-700/)
    expect(screen.getByRole('menuitem', { name: '删除' }).className).toMatch(/text-red-600/)
    // 原语里没有确认闸门（改容器不改语义：二次确认由页面 Modal 承担）
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('主行动（children）在容器内可达，且容器带页面级 testid', () => {
    renderActions()
    const cell = screen.getByTestId('row-actions')
    expect(cell.contains(screen.getByRole('button', { name: '编辑' }))).toBe(true)
    expect(cell.contains(trigger())).toBe(true)
    // 实测读数：一行恰好 2 个可点元素（主行动 + 触发器）—— 类级扫描器的同一口径
    expect(screen.getAllByRole('button')).toHaveLength(2)
  })

  it('行内动作不触发行点击（`ui/Table` 支持 onRowClick，触发器与菜单项都要吞事件）', () => {
    // 把动作面放进一个「整行可点」的容器里，模拟 `ui/Table` 的 onRowClick
    const onRowClick = vi.fn()
    const view = vi.fn()
    render(
      <div onClick={onRowClick}>
        <RowActions menuTestId="row-menu" items={[{ key: 'view', label: '查看', onClick: view }]}>
          <button type="button">编辑</button>
        </RowActions>
      </div>,
    )

    fireEvent.click(trigger())
    // 触发器本身就不该把点击漏给整行（否则点开菜单 = 同时进了详情页）
    expect(onRowClick).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('menuitem', { name: '查看' }))
    expect(view).toHaveBeenCalledTimes(1)
    // 菜单项若冒泡到整行，这个 spy 会被调用 —— 吞掉事件是原语的责任
    expect(onRowClick).not.toHaveBeenCalled()
  })
})
