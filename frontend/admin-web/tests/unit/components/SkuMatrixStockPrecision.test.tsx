// case_ids: UI-055, PR-010
/**
 * SkuMatrix 库存数字框两处漏网 —— issue #5237（A=P1 静默丢数 / B=P2 精度错配）的可执行判据
 *
 * ## 病灶（改前读数，取自 origin/main）
 * - **A（P1 静默丢数）**：批量填写库存框 = 裸 `<input type="number" step="1">` + `parseInt(batchStock, 10)`
 *   ⇒ 输入 `60.5` **静默变 `60`**（丢 0.5 米；无报错、无提示、无痕迹 —— 截断发生在提交之前，
 *   后端收到的就是 `60`，**无从察觉**）。旁边的价格框本来是对的（`step="0.01"` + `parseFloat`）。
 * - **B（P2 精度错配）**：单元格库存框 `<NumberInput min={0} placeholder="0">` **缺 `decimals={1}`**
 *   ⇒ 取默认 2 位 ⇒ 可提交 `10.55` ⇒ 后端 `StockQuantity.requireOneDecimalOrNull` **显式 422**。
 *   同排价格格有 `decimals={2}`（对齐 `price DECIMAL(10,2)`），库存格是异类。
 *
 * ## 口径（不许改）
 * `stock` 自 V115（#5063）起是 `NUMERIC(12,1)` = **1 位小数（0.1 米粒度）**；后端三层（列 /
 * `BigDecimal` / `StockQuantity`）**已就位、本单一行未改**，只改前端。
 *
 * ## 判据 ↔ 本文件的用例（每条都有单点变异红证；变异读数见 PR 说明）
 * 判据 1 批量 `60.5` ⇒ `stock === 60.5`；判据 2 批量 `60.55` ⇒ 按 1 位归一（不静默截断）；
 * 判据 3 库存格 `decimals === 1`；判据 4 库存格 `10.55` blur ⇒ `10.6`；
 * 判据 5 价格框**逐值不变**（`60.55` ⇒ `60.55`，防「顺手统一」砍掉价格精度）；
 * 判据 6 静态扫描：源码（剥注释后）不得再用 `parseInt(` 处理数量。
 *
 * ## ⚠️ 一处口径订正（issue 作者已确认，2026-09-23）
 * issue #5237 判据 2 的括注写「`60.55` ⇒ `60.6`」—— **算术上不成立**：实测
 * `(60.55).toFixed(1) === '60.5'`（`60.55` 的 IEEE754 实际值是 `60.5499…`），
 * 而同族的 `(10.55).toFixed(1) === '10.6'`（判据 4 的 `10.6` **成立**，原样保留）。
 * 本单选 issue 给的第二支「按 1 位小数归一」，且**复用共享 `NumberInput` 既有的归一化**
 * （`toFixed(decimals)` = 判据 4 依赖的**同一个**机制）⇒ 真实值就是 `60.5`。
 * **不为了凑 `60.6` 另造第三套舍入实现**（那是发明口径 + 违反最少代码阶梯）。
 */
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import SkuMatrix from '@/components/products/SkuMatrix'
import type { ProductColor, ProductSku } from '@/types'

// 批量填写成功会 toast.success ⇒ 与既有 SkuMatrix.test.tsx 同款打桩（不让 sonner 真跑）
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
const skuOf = (price: number, stock: number): ProductSku => ({
  id: 's1',
  colorId: 'c1',
  colorName: '红色',
  doorWidth: '2.8',
  price,
  stock,
  status: 'active',
})

/** 受控夹具：把 SkuMatrix 的 onChange 原样喂回 value（真实页面 ProductForm 的最小复现），
 *  并把每次载荷记进 `seen` ⇒ 能断言「**发出去**的值」而不只是「框里显示的值」。 */
function Harness({
  price = 0,
  stock = 0,
  seen,
}: {
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

/** 批量填写两个框（单元格价格格占位符是 `0.00`、库存格是 `0` ⇒ 用批量框自己的占位符定位，不歧义） */
const batchStockBox = () => screen.getByPlaceholderText('数量') as HTMLInputElement
const batchPriceBox = () => screen.getByPlaceholderText('价格') as HTMLInputElement
const fillButton = () => screen.getByRole('button', { name: '批量填写' })

/** 单元格输入框：`td` 内第 0 个 = 价格、第 1 个 = 库存（与既有 SkuMatrixNumbers.test.tsx 同口径） */
const cells = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('td input')) as HTMLInputElement[]

/** 最近一次发出去的载荷里的库存 / 价格（目标 SKU = skus[0]） */
const lastStock = (seen: MatrixValue[]) => seen.at(-1)!.skus[0].stock
const lastPrice = (seen: MatrixValue[]) => seen.at(-1)!.skus[0].price

/** 小数位数 —— 后端 `requireOneDecimalOrNull` 的判据形态（> 1 ⇒ 必 422） */
const decimalsOf = (n: number) => (String(n).split('.')[1] ?? '').length

/** 被测源码（静态扫描用；vitest 的 cwd = frontend/admin-web） */
const SRC_PATH = join(process.cwd(), 'src/components/products/SkuMatrix.tsx')

/**
 * 剥掉注释再扫：注释里写旧形态是**说明**，不是接线（假阳性来源，实测踩过）。
 * 与 tests/unit/components/NumberInputWiring.test.ts 的 stripComments 同源 ——
 * 有意重抄这 2 行而不 import：那个文件是 `.test.ts`，import 它会把它的 describe 在本文件里
 * **再注册一遍**（同一批测试被跑两遍）。
 */
function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 把源码拆成每个 `<NumberInput … />` 的属性块（用于按「格」断言各自的小数位声明） */
function numberInputBlocks(src: string): string[] {
  return src
    .split('<NumberInput')
    .slice(1)
    .map((b) => b.split('/>')[0])
}

describe('#5237 判据 1：批量填写 60.5 ⇒ stock === 60.5（不是 60）', () => {
  it('批量填写库存 60.5 ⇒ 发出去的 stock 是 60.5（旧 parseInt 形态会静默截成 60）', () => {
    const seen: MatrixValue[] = []
    render(<Harness stock={30} seen={seen} />)
    const box = batchStockBox()
    fireEvent.change(box, { target: { value: '60.5' } })
    fireEvent.blur(box)
    fireEvent.click(fillButton())
    // 红证（单点变异）：把 `const stockNum = batchStock` 改回 `parseInt(String(batchStock), 10)`
    // ⇒ 本断言收到 60（实测 1 failed）。
    expect(lastStock(seen)).toBe(60.5)
    expect(lastStock(seen)).not.toBe(60) // 截断缺陷本体：60 就是「静默丢 0.5 米」
  })

  it('批量填写 0.5（布艺按米，0.x 米是常见量）⇒ stock 是 0.5，不被截成 0', () => {
    const seen: MatrixValue[] = []
    render(<Harness stock={30} seen={seen} />)
    const box = batchStockBox()
    fireEvent.change(box, { target: { value: '0.5' } })
    fireEvent.blur(box)
    fireEvent.click(fillButton())
    // 红证：同一处变异 ⇒ 旧形态 `parseInt('0.5', 10)` = 0 ⇒ 本断言收到 0
    expect(lastStock(seen)).toBe(0.5)
  })
})

describe('#5237 判据 2：批量填写 60.55 ⇒ 按 1 位小数归一（不静默截断）', () => {
  it('选「按 1 位归一」这一支：60.55 失焦 ⇒ 60.5，提交值 === 60.5 且 !== 60、位数 ≤ 1', () => {
    // 口径见文件头「一处口径订正」：60.55 的 IEEE754 实际值 = 60.5499… ⇒ toFixed(1) = '60.5'
    // （issue 括注的 60.6 算错了，已由 issue 作者确认）。这里断言**真实值**，不写 60.6。
    const seen: MatrixValue[] = []
    render(<Harness stock={30} seen={seen} />)
    const box = batchStockBox()
    fireEvent.change(box, { target: { value: '60.55' } })
    expect(box.value).toBe('60.55') // 输入中的草稿逐字保留（不打断录入）
    fireEvent.blur(box)
    expect(box.value).toBe('60.5') // 失焦按 1 位归一，就地上屏
    fireEvent.click(fillButton())
    expect(lastStock(seen)).toBe(60.5)
    expect(lastStock(seen)).not.toBe(60) // 不是旧 parseInt 的截断值
    expect(decimalsOf(lastStock(seen))).toBeLessThanOrEqual(1) // 后端 requireOneDecimalOrNull 必收
  })
})

describe('#5237 判据 3：单元格库存格的 decimals === 1（与列 NUMERIC(12,1) 同口径）', () => {
  it('静态扫描：库存格 NumberInput 块声明 decimals={1}，价格格声明 decimals={2}（各按自己的列精度）', () => {
    const src = stripComments(readFileSync(SRC_PATH, 'utf8'))
    const blocks = numberInputBlocks(src)
    const stockBlocks = blocks.filter((b) => b.includes("'stock'"))
    const priceBlocks = blocks.filter((b) => b.includes("'price'"))
    expect(stockBlocks).toHaveLength(1) // 库存格（handleSkuChange(…, 'stock', …)）
    expect(priceBlocks).toHaveLength(1) // 价格格（handleSkuChange(…, 'price', …)）
    // 红证（单点变异）：删掉库存格的 `decimals={1}` ⇒ 本断言红（实测：本 describe 1 failed）
    expect(stockBlocks[0]).toContain('decimals={1}')
    expect(priceBlocks[0]).toContain('decimals={2}')
  })
})

describe('#5237 判据 4：单元格库存框 10.55 blur ⇒ 10.6（1 位归一），提交值位数 ≤ 1', () => {
  it('输入 10.55 ⇒ 失焦后框内 10.6，且发出去的 stock 小数位 ≤ 1', () => {
    const seen: MatrixValue[] = []
    const { container } = render(<Harness price={12.5} stock={30} seen={seen} />)
    const stock = cells(container)[1]
    fireEvent.change(stock, { target: { value: '10.55' } })
    expect(stock.value).toBe('10.55') // 输入中态不打断
    fireEvent.blur(stock)
    // 红证（单点变异）：删掉库存格的 `decimals={1}` ⇒ 取默认 2 位 ⇒ 失焦后仍是 '10.55'
    // ⇒ 本断言实测收到 '10.55'（1 failed）
    expect(stock.value).toBe('10.6')
    expect(lastStock(seen)).toBe(10.6)
    expect(decimalsOf(lastStock(seen))).toBeLessThanOrEqual(1)
  })
})

describe('#5237 判据 5：价格框逐值不变（防「顺手统一」把价格精度砍掉）', () => {
  it('批量填写价格 60.55 ⇒ 价格是 60.55（**不**被按库存的 1 位口径归一成 60.5）', () => {
    const seen: MatrixValue[] = []
    render(<Harness price={1} seen={seen} />)
    const box = batchPriceBox()
    fireEvent.change(box, { target: { value: '60.55' } })
    fireEvent.click(fillButton())
    // 红证（单点变异）：把价格解析也接上 1 位归一（`Number(parseFloat(batchPrice).toFixed(1))`，
    // 即「顺手统一」的真实形态）⇒ 本断言实测收到 60.5（1 failed）
    expect(lastPrice(seen)).toBe(60.55)
  })

  it('单元格价格 60.55 失焦 ⇒ 仍是 60.55（decimals={2} 对齐 price DECIMAL(10,2)）', () => {
    const seen: MatrixValue[] = []
    const { container } = render(<Harness price={12.5} stock={30} seen={seen} />)
    const price = cells(container)[0]
    fireEvent.change(price, { target: { value: '60.55' } })
    fireEvent.blur(price)
    // 红证（单点变异）：把价格格的 `decimals={2}` 改成 `decimals={1}` ⇒ 失焦按 1 位归一
    // ⇒ 本断言实测收到 '60.5'（1 failed）—— 这就是 issue 点名的「顺手统一」形态
    expect(price.value).toBe('60.55')
    expect(lastPrice(seen)).toBe(60.55)
  })
})

describe('#5237 判据 6：SkuMatrix.tsx 不得再用 parseInt( 处理数量', () => {
  const raw = readFileSync(SRC_PATH, 'utf8')

  it('剥掉注释后，源码里不出现 `parseInt(`', () => {
    // 红证（单点变异）：在批量填写路径上加回 `parseInt(String(batchStock), 10)` ⇒ 本断言红
    expect(stripComments(raw)).not.toContain('parseInt(')
  })

  it('负控：原文（含注释）里确实出现过 `parseInt(` ⇒ 说明「剥注释」这一层是承重的，扫描没被自己的文案喂绿', () => {
    // 注释里逐字保留着旧形态（`parseInt(batchStock, 10)` / `parseInt(raw) || 0`）**是有意的**
    // —— 它们是「为什么这么改」的证据。⇒ 扫描必须先剥注释，否则会把说明当违规（假阳性）。
    expect(raw).toContain('parseInt(')
    expect(stripComments(raw)).not.toContain('parseInt(')
  })
})
