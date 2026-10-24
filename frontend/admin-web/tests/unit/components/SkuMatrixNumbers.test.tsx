// case_ids: PR-010, PR-042
/**
 * SkuMatrix 价格输入框 —— 「0 打不进去」治理的端到端红证（issue #5198 / #5218）
 *
 * 红证（改前必红，实测）：单元格旧形态 `value={sku?.price || ''}` + `onChange(parseFloat(raw) || 0)`，
 * 受控父组件把值写回后 `0 || ''` = `''` ⇒ 用户敲下 "0" 的**当刻输入框被清空**，
 * 因此永远打不出 "0.5" / "0.6"（布艺按米计价，0.x 米是常见量）。
 *
 * 🔴 库存那条已随 issue #7597 下线（用户裁定 2026-10-24：商品档案不再设置库存数值）：
 * SKU 矩阵里**不再有**库存输入框 —— 移除判据见 `SkuMatrixStockRemoved.test.tsx`。
 */
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import SkuMatrix from '@/components/products/SkuMatrix'
import type { ProductColor, ProductSku } from '@/types'

vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

const COLORS = [{ id: 'c1', colorName: '红色', remark: '', sortOrder: 0 } as ProductColor]
const WIDTHS = ['2.8']
const skuOf = (price: number, stock = 0): ProductSku => ({
  id: 's1',
  colorId: 'c1',
  colorName: '红色',
  doorWidth: '2.8',
  price,
  stock,
  status: 'active',
})

/** 受控夹具：把 SkuMatrix 的 onChange 原样喂回 value（真实页面 ProductForm 的最小复现） */
function Harness({ price = 0 }: { price?: number }) {
  const [value, setValue] = useState({
    colors: COLORS,
    doorWidths: WIDTHS,
    skus: [skuOf(price)],
  })
  return <SkuMatrix value={value} onChange={setValue} />
}

/** 单元格输入框（每行只剩价格一个；库存列已移除） */
function cells(container: HTMLElement): HTMLInputElement[] {
  return Array.from(container.querySelectorAll('td input')) as HTMLInputElement[]
}

describe('SkuMatrix 数字输入：0 打不进去（issue #5198 红证）', () => {
  it('价格格输入 "0" ⇒ DOM 值仍为 "0"（改前：当场被清成 ""）', () => {
    const { container } = render(<Harness />)
    const price = cells(container)[0]
    fireEvent.change(price, { target: { value: '0' } })
    expect(price.value).toBe('0')
  })

  it('价格格可以连续打出 "0.5"（0 → 0. → 0.5 三步都不丢键）', () => {
    const { container } = render(<Harness />)
    const price = cells(container)[0]
    fireEvent.change(price, { target: { value: '0' } })
    expect(price.value).toBe('0')
    fireEvent.change(price, { target: { value: '0.' } })
    expect(price.value).toBe('0.')
    fireEvent.change(price, { target: { value: '0.5' } })
    expect(price.value).toBe('0.5')
    fireEvent.blur(price)
    expect(price.value).toBe('0.5')
  })

  it('每行只有一个输入框（库存列已移除，issue #7597）', () => {
    const { container } = render(<Harness price={0} />)
    expect(cells(container)).toHaveLength(1)
    // 表头只剩 颜色分类 / 规格尺寸 / 价格
    expect(container.querySelectorAll('thead th')).toHaveLength(3)
    expect(screen.queryByText(/库存/)).toBeNull()
  })
})

describe('SkuMatrix 数字输入：编辑**既有值**方向（issue #5218 判据 1 红证）', () => {
  // 为什么单开一组：issue #5198 的夹具从 `price=0` 起步 ⇒ 外部 prop 恒为「空」⇒
  // **结构性覆盖不到「编辑既有值」这条最常见的路径**，于是 `x ? x : null` 这个新形态漏网。
  it('判据 1（红证）：价格已是 12.5 ⇒ 全选输入 "0" ⇒ DOM 仍为 "0"', () => {
    const { container } = render(<Harness price={12.5} />)
    const price = cells(container)[0]
    expect(price.value).toBe('12.5')
    fireEvent.change(price, { target: { value: '0' } })
    // 红证（单点变异，实测）：把接线改回 `value={sku?.price ? sku.price : null}` ⇒
    // 0 是 falsy ⇒ 外部值变 null ⇒ 草稿被洗成 '' ⇒ 本断言收到 ''（框当场清空）
    expect(price.value).toBe('0')
  })

  it('编辑既有值 ⇒ 逐键 0 → . → 5 打出 "0.5"（价格 12.5 改成 0.5 的真实路径）', () => {
    const { container } = render(<Harness price={12.5} />)
    const price = cells(container)[0]
    fireEvent.change(price, { target: { value: '0' } })
    expect(price.value).toBe('0')
    fireEvent.change(price, { target: { value: '0.' } })
    expect(price.value).toBe('0.')
    fireEvent.change(price, { target: { value: '0.5' } })
    expect(price.value).toBe('0.5')
    fireEvent.blur(price)
    expect(price.value).toBe('0.5')
  })

  it('既有值可直接改大改小（12.5 ⇒ 7.25），不留旧值残影', () => {
    const { container } = render(<Harness price={12.5} />)
    const [price] = cells(container)
    fireEvent.change(price, { target: { value: '7.25' } })
    expect(price.value).toBe('7.25')
  })
})
