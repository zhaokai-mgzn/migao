// case_ids: PR-010, PR-042
/**
 * SkuMatrix 价格/库存输入框 —— 「0 打不进去」治理的**端到端红证**（issue #5198）
 *
 * 红证（改前必红，实测）：单元格旧形态 `value={sku?.price || ''}` + `onChange(parseFloat(raw) || 0)`，
 * 受控父组件把值写回后 `0 || ''` = `''` ⇒ 用户敲下 "0" 的**当刻输入框被清空**，
 * 因此永远打不出 "0.5" / "0.6"（布艺按米计价，0.x 米是常见量）。
 * 本文件第 1、2 条即该红证；第 3 条起是「原来的正常行为没变」的回归护栏。
 */
import { useState } from 'react'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import SkuMatrix from '@/components/products/SkuMatrix'
import type { ProductColor, ProductSku } from '@/types'

vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

const COLORS = [{ id: 'c1', colorName: '红色', remark: '', sortOrder: 0 } as ProductColor]
const WIDTHS = ['2.8']
const skuOf = (price: number, stock: number): ProductSku => ({
  id: 's1',
  colorId: 'c1',
  colorName: '红色',
  doorWidth: '2.8',
  price,
  stock,
  status: 'active',
})

/** 受控夹具：把 SkuMatrix 的 onChange 原样喂回 value（真实页面 ProductForm 的最小复现） */
function Harness({ price = 0, stock = 0 }: { price?: number; stock?: number }) {
  const [value, setValue] = useState({
    colors: COLORS,
    doorWidths: WIDTHS,
    skus: [skuOf(price, stock)],
  })
  return <SkuMatrix value={value} onChange={setValue} />
}

/** 单元格输入框：`td` 内第 0 个 = 价格、第 1 个 = 库存 */
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

  it('库存格输入 "0"（无库存）⇒ DOM 值仍为 "0"（改前：当场被清成 ""）', () => {
    const { container } = render(<Harness price={10} />)
    const stock = cells(container)[1]
    fireEvent.change(stock, { target: { value: '0' } })
    expect(stock.value).toBe('0')
  })
})

describe('SkuMatrix 数字输入：原行为回归护栏（issue #5198）', () => {
  it('价格/库存仍是每行两个输入框，且空值仍显示占位符（不是 0）', () => {
    const { container } = render(<Harness />)
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    const [price, stock] = cells(container)
    expect(price.value).toBe('')
    expect(price.getAttribute('placeholder')).toBe('0.00')
    expect(stock.value).toBe('')
    expect(stock.getAttribute('placeholder')).toBe('0')
  })

  it('已填值回显正常（价格 12.5 / 库存 30）', () => {
    const { container } = render(<Harness price={12.5} stock={30} />)
    const [price, stock] = cells(container)
    expect(price.value).toBe('12.5')
    expect(stock.value).toBe('30')
  })

  it('改价格发出去的仍是 {field: price} 且带上颜色/门幅定位（onChange 载荷形状不变）', () => {
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={{ colors: COLORS, doorWidths: WIDTHS, skus: [skuOf(0, 0)] }}
        onChange={onChange}
      />
    )
    const price = Array.from(document.querySelectorAll('td input'))[0] as HTMLInputElement
    fireEvent.change(price, { target: { value: '9.8' } })
    const next = onChange.mock.calls.at(-1)![0]
    expect(next.skus).toHaveLength(1)
    expect(next.skus[0].price).toBe(9.8)
    expect(next.skus[0].stock).toBe(0)
    expect(next.skus[0].colorName).toBe('红色')
    expect(next.skus[0].doorWidth).toBe('2.8')
  })

  it('校验失败时价格格仍标红 + aria-invalid（#2908 行为不变）', () => {
    const { container } = render(
      <SkuMatrix
        value={{ colors: COLORS, doorWidths: WIDTHS, skus: [skuOf(0, 0)] }}
        onChange={vi.fn()}
        errors={{ skus: '请完整填写所有 SKU 的价格与库存' }}
      />
    )
    const [price, stock] = cells(container)
    expect(price.className).toContain('border-red-400')
    expect(price.getAttribute('aria-invalid')).toBe('true')
    // 库存 0 视为有效，不标红
    expect(stock.className).not.toContain('border-red-400')
  })

  it('警示横幅计数不受影响（价格=0 计 1 处）', () => {
    render(
      <SkuMatrix
        value={{ colors: COLORS, doorWidths: WIDTHS, skus: [skuOf(0, 0)] }}
        onChange={vi.fn()}
        errors={{ skus: '请完整填写所有 SKU 的价格与库存' }}
      />
    )
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('1 处')
  })
})
