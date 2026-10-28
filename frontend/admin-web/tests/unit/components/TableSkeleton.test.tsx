// case_ids: UI-143
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import TableSkeleton from '@/components/ui/TableSkeleton'

/**
 * 通用表格骨架（issue #8036）的**组件契约**。
 *
 * 红证（改任一条，对应用例当场红）：
 * - 把 `rows` 写死（忽略入参）⇒「行数可配」红；
 * - 把 `columns` 写死 ⇒「列数可配」红；
 * - 去掉 `data-testid="table-skeleton"` ⇒ 首条红；
 * - 去掉 `animate-pulse` / 灰底 ⇒「视觉口径」红；
 * - 放任何文案进去 ⇒「纯布局」红。
 *
 * ⚠️ 边界：jsdom 只能证「在场 + 无文案 + 行列数 + class 口径」；
 * **骨架行高与真实表格行是否对齐**（视觉）由真机截图复核，这里证不了。
 */
describe('TableSkeleton（#8036：列表页加载态的通用表格骨架）', () => {
  it('渲染 table-skeleton 根节点，默认 8 行 6 列', () => {
    const { container } = render(<TableSkeleton />)
    expect(screen.getByTestId('table-skeleton')).toBeInTheDocument()
    expect(container.querySelectorAll('[data-testid="table-skeleton-row"]')).toHaveLength(8)
    // 表头占位 columns 格 + 每行 columns 格 = (rows + 1) × columns
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength((8 + 1) * 6)
  })

  it('行数可配（rows）', () => {
    const { container } = render(<TableSkeleton rows={3} columns={4} />)
    expect(container.querySelectorAll('[data-testid="table-skeleton-row"]')).toHaveLength(3)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength((3 + 1) * 4)
  })

  it('列数可配（columns）—— 每一行的占位块数 = columns', () => {
    const { container } = render(<TableSkeleton rows={2} columns={9} />)
    const rows = Array.from(container.querySelectorAll('[data-testid="table-skeleton-row"]'))
    expect(rows).toHaveLength(2)
    rows.forEach((row) => {
      expect(row.querySelectorAll('.animate-pulse')).toHaveLength(9)
    })
  })

  it('纯布局：不含任何文案，也不给读屏念占位', () => {
    const { container } = render(<TableSkeleton rows={4} columns={5} />)
    expect(container.textContent).toBe('')
    expect(screen.getByTestId('table-skeleton')).toHaveAttribute('aria-hidden', 'true')
  })

  it('视觉口径同 #8012：灰底 + animate-pulse + 圆角', () => {
    const { container } = render(<TableSkeleton rows={1} columns={2} />)
    const bars = Array.from(container.querySelectorAll('.animate-pulse'))
    expect(bars).toHaveLength((1 + 1) * 2)
    bars.forEach((bar) => {
      expect(bar.className).toContain('animate-pulse')
      expect(bar.className).toContain('bg-neutral-')
      expect(bar.className).toContain('rounded')
    })
  })

  it('rows / columns 给 0 也至少出 1 行 1 列（不产出空壳）', () => {
    const { container } = render(<TableSkeleton rows={0} columns={0} />)
    expect(container.querySelectorAll('[data-testid="table-skeleton-row"]')).toHaveLength(1)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength((1 + 1) * 1)
  })
})
