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

describe('SkuMatrix 数字输入：编辑**既有值**方向（issue #5218 判据 1/2 红证）', () => {
  // 为什么单开一组：issue #5198 的夹具从 `price=0 / stock=0` 起步 ⇒ 外部 prop 恒为「空」⇒
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

  it('判据 2（红证）：库存已是 30 ⇒ 输入 "0" ⇒ DOM 仍为 "0"', () => {
    const { container } = render(<Harness price={12.5} stock={30} />)
    const stock = cells(container)[1]
    expect(stock.value).toBe('30')
    fireEvent.change(stock, { target: { value: '0' } })
    // 红证：同上（`sku?.stock ? sku.stock : null`）
    expect(stock.value).toBe('0')
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

  it('既有值可直接改大改小（12.5 ⇒ 7.25 / 30 ⇒ 12），不留旧值残影', () => {
    const { container } = render(<Harness price={12.5} stock={30} />)
    const [price, stock] = cells(container)
    fireEvent.change(price, { target: { value: '7.25' } })
    expect(price.value).toBe('7.25')
    fireEvent.change(stock, { target: { value: '12' } })
    expect(stock.value).toBe('12')
  })
})

describe('SkuMatrix 数字输入：原行为回归护栏（issue #5198）', () => {
  it('矩阵未重建（该行**没有** SKU）⇒ 显示占位符 0.00 / 0（缺行才是空）', () => {
    const { container } = render(
      <SkuMatrix value={{ colors: COLORS, doorWidths: WIDTHS, skus: [] }} onChange={vi.fn()} />
    )
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    const [price, stock] = cells(container)
    expect(price.value).toBe('')
    expect(price.getAttribute('placeholder')).toBe('0.00')
    expect(stock.value).toBe('')
    expect(stock.getAttribute('placeholder')).toBe('0')
  })

  // issue #5218 #1 的可见面变化（如实登记）：`rebuildSkus` 给新行落的是 `price: 0 / stock: 0`，
  // 而旧接线 `sku?.price || ''` 把 0 当成「空」渲染成占位符。拆掉这层伪装后，**未填的行显示 0**
  // ——「0 = 未填写」由既有校验（价格必须 > 0 + 标红 + 计数横幅）表达，不再由输入框替商家隐藏。
  it('已存在的行 price=0/stock=0（未填写）⇒ 显示 "0"（不再冒充占位符），校验标红仍生效', () => {
    const { container } = render(
      <SkuMatrix
        value={{ colors: COLORS, doorWidths: WIDTHS, skus: [skuOf(0, 0)] }}
        onChange={vi.fn()}
        errors={{ skus: '请完整填写所有 SKU 的价格与库存' }}
      />
    )
    const [price, stock] = cells(container)
    expect(price.value).toBe('0')
    expect(stock.value).toBe('0')
    expect(price.className).toContain('border-red-400')
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
