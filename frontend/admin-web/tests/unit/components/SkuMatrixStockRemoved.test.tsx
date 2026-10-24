// case_ids: UI-055, PR-132
/**
 * 商品表单不再有库存录入面 —— issue #7597 的移除判据（用户裁定 2026-10-24）
 *
 * ## 改后口径（被本文件钉住的东西）
 * 商品档案不再设置库存数值：SKU 矩阵没有「库存」列、没有库存输入框、批量填写区没有数量框；
 * 建品时 SKU 一律从 0 起算，库存只由真实单据产生（入库单 / 订单 / 售后回补 / 批次盘点）。
 * 后端忽略 `stock` / `skus[].stock` 的判据在 `ProductCreateStockIgnoredTest`。
 *
 * ## 红证（每条都能被单点变异打红）
 * 判据 1 表头不得出现「库存」列（把 `<th>库存（米）</th>` 加回去 ⇒ 红）；
 * 判据 2 每行只有价格一个输入框（把库存 `<td>` 加回去 ⇒ 输入框数变成 2）；
 * 判据 3 批量填写区没有「数量」框、只有价格框（把批量库存框加回去 ⇒ 红）；
 * 判据 4 批量填价格**不动** SKU 的 stock（把 `stock: stockNum` 写回 map ⇒ 红）；
 * 判据 5 静态扫描：剥注释后的源码不再引用 `STOCK_UNIT` / `'stock'` 字段写入
 *        （从 git 历史恢复旧版组件 ⇒ 红）。
 */
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import SkuMatrix from '@/components/products/SkuMatrix'
import type { ProductColor, ProductSku } from '@/types'

// 批量填写成功会 toast.success ⇒ 与既有 SkuMatrix.test.tsx 同款打桩
vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

type MatrixValue = {
  colors: ProductColor[]
  doorWidths: string[]
  skus: ProductSku[]
}

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

/** 受控夹具：原样把 onChange 喂回 value（真实页面 ProductForm 的最小复现） */
function Harness({ price = 100, stock = 30, seen }: {
  price?: number
  stock?: number
  seen: MatrixValue[]
}) {
  const [value, setValue] = useState<MatrixValue>({
    colors: COLORS,
    doorWidths: WIDTHS,
    skus: [skuOf(price, stock)],
  })
  return (
    <SkuMatrix
      value={value}
      onChange={(v) => {
        seen.push(v)
        setValue(v)
      }}
    />
  )
}

/** 剥掉注释再扫：注释里写旧形态是**说明**，不是接线（假阳性来源） */
function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const SRC_PATH = join(process.cwd(), 'src/components/products/SkuMatrix.tsx')

describe('#7597 商品表单没有库存录入面', () => {
  it('判据 1：表头没有「库存」列（只剩 颜色分类 / 规格尺寸 / 价格）', () => {
    const { container } = render(<Harness seen={[]} />)
    const headers = Array.from(container.querySelectorAll('thead th')).map(
      (th) => th.textContent || ''
    )
    expect(headers).toHaveLength(3)
    expect(headers.some((h) => h.includes('库存'))).toBe(false)
    expect(headers.some((h) => h.includes('价格'))).toBe(true)
  })

  it('判据 2：每行只有一个输入框（价格），SKU 的 stock 不出现在单元格里', () => {
    const { container } = render(<Harness stock={30} seen={[]} />)
    expect(container.querySelectorAll('td input')).toHaveLength(1)
    expect(screen.queryByDisplayValue('30')).toBeNull()
  })

  it('判据 3：批量填写区没有「数量」框，只有价格框', () => {
    render(<Harness seen={[]} />)
    expect(screen.queryByPlaceholderText('数量')).toBeNull()
    expect(screen.getByPlaceholderText('价格')).toBeTruthy()
    expect(screen.getByText(/提示：选择目标范围并填入价格/)).toBeTruthy()
  })

  it('判据 4：批量填价格只改价格，SKU 的 stock 保持现值（不被表单改写）', () => {
    const seen: MatrixValue[] = []
    render(<Harness price={100} stock={30} seen={seen} />)
    const box = screen.getByPlaceholderText('价格') as HTMLInputElement
    fireEvent.change(box, { target: { value: '168' } })
    fireEvent.click(screen.getByRole('button', { name: '批量填写' }))
    expect(seen.at(-1)!.skus[0].price).toBe(168)
    // 库存不在本表录入 ⇒ 发出去的载荷里 stock 原样保留（后端也会忽略它）
    expect(seen.at(-1)!.skus[0].stock).toBe(30)
  })

  it('判据 5：静态扫描 —— 源码（剥注释）不再有库存列 / 批量库存框的接线', () => {
    const src = stripComments(readFileSync(SRC_PATH, 'utf8'))
    expect(src).not.toContain('STOCK_UNIT')
    expect(src).not.toContain("'stock'")
    expect(src).not.toContain('batchStock')
    expect(src).not.toContain('库存（')
  })
})
