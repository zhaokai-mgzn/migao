// case_ids: PR-037, SP-006, PRC-005
//
// 公共 SKU 选择器（issue #7567）—— 用户 2026-10-23 逐字：
//   「这种选择SKU的组件应该作为sku的公共组件，你新增的采购单和作业单中的sku输入框是不能作为生产系统使用的，需要优化」
//
// 本文件守的是**组件层**的判据（三个消费面各自的行为由它们的页面用例守）：
//   ① 勾选回调把 `{product, sku}` **原样**带回 —— SKU id 是雪花号字符串（≈2.1e18 > 2^53），
//      逐字不得被 `Number()` 截断（#5904 同族；玩具 id 测不出这个洞，故用真实量级）；
//   ② 勾选态是**受控**的：`selectedSkuIds` 决定 checked，组件不存影子状态；
//   ③ 搜索失败 ≠ 空态、规格读失败 ≠「该商品还没有 SKU」（issue #6691 口径）：失败要能重试，
//      且不许拿「空列表」冒充「你没搜 / 没维护」；
//   ④ 单选态（价格本）= `radio` 语义，不是「checkbox 假装单选」。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProducts: (...args: unknown[]) => mockGetProducts(...args),
    getProduct: (...args: unknown[]) => mockGetProduct(...args),
  },
}))

import SkuPicker, {
  type SkuPickerChoice,
  skuDisplayName,
  skuLineLabel,
} from '@/components/products/SkuPicker'

/** 线上真实量级（2026-10-01 实测）：> Number.MAX_SAFE_INTEGER，`Number()` 会把末位 18 吞成 0 */
const SNOWFLAKE = '2097126615461462018'

const PRODUCT = { id: 'prod-1', name: '遮光窗帘布', skuCode: 'HUOHAO-01' }
const SKU = {
  id: SNOWFLAKE,
  colorName: '米白',
  doorWidth: '2.8',
  stock: 5,
  price: 30,
  status: 'active' as const,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProducts.mockResolvedValue({ data: { data: { items: [PRODUCT] } } })
  mockGetProduct.mockResolvedValue({ data: { data: { id: 'prod-1', name: '遮光窗帘布', skus: [SKU] } } })
})

/** 走法：搜商品 → 点商品 → 等右栏出现规格行（搜索有 300ms 防抖） */
async function pickProduct() {
  fireEvent.change(screen.getByLabelText('搜索商品'), { target: { value: '遮光' } })
  fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 }))
  await screen.findByRole('checkbox', undefined, { timeout: 3000 })
}

describe('公共 SKU 选择器：勾选回调原样带回商品与 SKU', () => {
  it('勾一个 SKU ⇒ 回调收到 product + sku；雪花号 id 逐字是字符串（不得被数字化）', async () => {
    const onToggle = vi.fn()
    render(<SkuPicker selectedSkuIds={[]} onToggle={onToggle} />)

    await pickProduct()
    fireEvent.click(screen.getByRole('checkbox'))

    expect(onToggle).toHaveBeenCalledTimes(1)
    const choice = onToggle.mock.calls[0][0] as SkuPickerChoice
    expect(choice.product.id).toBe('prod-1')
    expect(typeof choice.sku.id).toBe('string')
    expect(choice.sku.id).toBe(SNOWFLAKE)
    // 反面钉法：数字化之后的值（末位被吞）不得出现在回调里
    expect(choice.sku.id).not.toBe(String(Number(SNOWFLAKE)))
  })

  it('右栏一行说清「颜色 / 门幅 + 当前库存」，缺颜色门幅时给「默认」而不是空白', async () => {
    const onToggle = vi.fn()
    render(<SkuPicker selectedSkuIds={[]} onToggle={onToggle} />)

    await pickProduct()
    expect(screen.getByText('米白 / 2.8')).toBeInTheDocument()
    expect(screen.getByText('当前库存 5')).toBeInTheDocument()

    // 纯函数同源：缺值兜底看得见（空白行读起来像坏了）
    expect(skuDisplayName({ colorName: undefined, doorWidth: '' })).toBe('默认色 / 默认门幅')
    expect(skuLineLabel({ name: '遮光窗帘布' }, { colorName: '米白', doorWidth: '2.8' })).toBe(
      '遮光窗帘布 / 米白 / 2.8',
    )
  })
})

describe('公共 SKU 选择器：勾选态由调用方控制', () => {
  it('`selectedSkuIds` 里有它 ⇒ 就是勾上的；没有 ⇒ 不勾（组件不存影子状态）', async () => {
    const onToggle = vi.fn()
    const { rerender } = render(<SkuPicker selectedSkuIds={[SNOWFLAKE]} onToggle={onToggle} />)

    await pickProduct()
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true)

    // 同一个组件、换一份「已选」⇒ 展示跟着变（受控）：这正是三处消费能各自持账的前提
    rerender(<SkuPicker selectedSkuIds={[]} onToggle={onToggle} />)
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
  })
})

describe('公共 SKU 选择器：失败 ≠ 空态（issue #6691 口径）', () => {
  it('商品搜索失败 ⇒ 说「没读到数据」+ 可重试；**不**显示「输入关键词搜索商品」', async () => {
    mockGetProducts.mockRejectedValue(new Error('boom'))
    render(<SkuPicker selectedSkuIds={[]} onToggle={vi.fn()} />)

    const error = await screen.findByTestId('sku-picker-product-search-error', undefined, { timeout: 3000 })
    expect(error).toHaveTextContent('商品搜索失败')
    expect(screen.queryByText('输入关键词搜索商品')).not.toBeInTheDocument()

    // 重试：这次读得到 ⇒ 列表出来、失败面消失
    mockGetProducts.mockResolvedValue({ data: { data: { items: [PRODUCT] } } })
    fireEvent.click(screen.getByTestId('sku-picker-product-search-retry'))
    expect(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByTestId('sku-picker-product-search-error')).not.toBeInTheDocument()
  })

  it('规格读取失败 ⇒ 说「没读到这个商品的规格」；**不**说「该商品还没有 SKU」（那是数据事实）', async () => {
    mockGetProduct.mockRejectedValue(new Error('boom'))
    render(<SkuPicker selectedSkuIds={[]} onToggle={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('搜索商品'), { target: { value: '遮光' } })
    fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 }))

    const error = await screen.findByTestId('sku-picker-sku-error', undefined, { timeout: 3000 })
    expect(error).toHaveTextContent('规格读取失败')
    expect(screen.queryByText(/该商品还没有 SKU/)).not.toBeInTheDocument()

    // 重试：读得到就出规格行
    mockGetProduct.mockResolvedValue({ data: { data: { id: 'prod-1', name: '遮光窗帘布', skus: [SKU] } } })
    fireEvent.click(screen.getByTestId('sku-picker-sku-retry'))
    expect(await screen.findByRole('checkbox', undefined, { timeout: 3000 })).toBeInTheDocument()
  })

  it('真的一个 SKU 都没有时说「该商品还没有 SKU」（与读失败严格分开）', async () => {
    mockGetProduct.mockResolvedValue({ data: { data: { id: 'prod-1', name: '遮光窗帘布', skus: [] } } })
    render(<SkuPicker selectedSkuIds={[]} onToggle={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('搜索商品'), { target: { value: '遮光' } })
    fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 }))

    expect(await screen.findByText(/该商品还没有 SKU/, undefined, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByTestId('sku-picker-sku-error')).not.toBeInTheDocument()
  })

  it('还没选商品时说「先在左侧选一个商品」（空态即引导，不是空白）', async () => {
    render(<SkuPicker selectedSkuIds={[]} onToggle={vi.fn()} />)
    expect(screen.getByText('先在左侧选一个商品')).toBeInTheDocument()
  })
})

describe('公共 SKU 选择器：单选态（价格本）用 radio 语义', () => {
  it('`mode="single"` ⇒ 规格行是 radio（不是 checkbox 假装单选），选中态同样受控', async () => {
    render(<SkuPicker mode="single" selectedSkuIds={[SNOWFLAKE]} onToggle={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('搜索商品'), { target: { value: '遮光' } })
    fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 }))

    const radio = await screen.findByRole('radio', undefined, { timeout: 3000 })
    expect((radio as HTMLInputElement).checked).toBe(true)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})

describe('公共 SKU 选择器：testid 前缀（各页保留自己的既有 testid）', () => {
  it('传 `testIdPrefix` ⇒ 失败面/重试按钮按前缀命名（入库单沿用 `inbound-*`）', async () => {
    mockGetProducts.mockRejectedValue(new Error('boom'))
    render(<SkuPicker testIdPrefix="inbound" selectedSkuIds={[]} onToggle={vi.fn()} />)

    await waitFor(() => expect(screen.getByTestId('inbound-product-search-error')).toBeInTheDocument(), {
      timeout: 3000,
    })
    expect(screen.getByTestId('inbound-product-search-retry')).toBeInTheDocument()
  })
})
