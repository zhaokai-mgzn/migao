// case_ids: PR-120
/**
 * 新增商品页：「拍照 / 上传识别」入口的**落点**与**功能**（issue #5918，用户 2026-10-01 走查裁定）。
 *
 * 改前形态：该按钮由页面渲染成一个**游离在表单卡片之外**的独立容器
 * （`<div className="max-w-6xl mx-auto px-6 pt-4">`），周围是页面底色；而同类页面 `/orders/new`
 * 把**同一个组件**放在「商品信息」卡标题行里 ⇒ 两页两种版式。
 * 改后：商品页由 `ProductForm` 的标题行动作槽（`titleActions`）承载 —— 落点固定在
 * 「新增商品 / 编辑商品」标题卡片内、标题行右侧，与「重置」同排、识别在前。
 *
 * 判据 1 = 落点（会红：改前连 `pf-title-card` / `pf-title-actions` 都不存在）；
 * 判据 2 = 功能一条不减（选图 → 上传 → 识别 → 字段回填），且识别结果**不落库**（零 create/update）。
 * 跨页口径（`/orders/new` 的同一按钮）由 `recognize-entry-placement-guard.test.ts` 的台账 +
 * `orders-new-layout.test.tsx` 的「识别入口挂在**商品信息**卡标题行」钉住。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'

// 稳定的 router 对象（每次 render 新建对象会让 effect 反复重跑 —— 与 edit-product.test.tsx 同款处理）
const { mockRouter } = vi.hoisted(() => ({
  mockRouter: { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}))

const mockCreateProduct = vi.fn()
const mockGetCategories = vi.fn()
const mockUploadImage = vi.fn()
const mockRecognize = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
  usePathname: () => '/products/new',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@/lib/api', () => ({
  productApi: { createProduct: (...a: unknown[]) => mockCreateProduct(...a) },
  categoryApi: { getCategories: (...a: unknown[]) => mockGetCategories(...a) },
  uploadApi: { uploadImage: (...a: unknown[]) => mockUploadImage(...a) },
  imageRecognizeApi: { recognize: (...a: unknown[]) => mockRecognize(...a) },
}))

// 重子组件与本页判据无关 —— 与 ProductForm.test.tsx 同款 mock，不拖入上传 / 富文本 / SKU 矩阵依赖
vi.mock('@/components/products/ImageUploader', () => ({
  default: () => {
    const R = require('react')
    return R.createElement('div', { 'data-testid': 'image-uploader' })
  },
}))
vi.mock('@/components/products/SkuMatrix', () => ({
  default: () => {
    const R = require('react')
    return R.createElement('div', { 'data-testid': 'sku-matrix' })
  },
}))
vi.mock('@/components/products/ProductAttributes', () => ({
  default: () => {
    const R = require('react')
    return R.createElement('div', { 'data-testid': 'product-attributes' })
  },
}))
vi.mock('@/components/products/RichTextEditor', () => ({
  default: () => {
    const R = require('react')
    return R.createElement('div', { 'data-testid': 'rich-text-editor' })
  },
}))

import NewProductPage from '@/app/(dashboard)/products/new/page'

/** DOM 顺序判定：`a` 是否在 `b` 之前（与 orders-new-layout.test.tsx 同款） */
function appearsBefore(a: Node, b: Node): boolean {
  return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
}

describe('#5918 新增商品页：识别入口的落点与功能', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    mockGetCategories.mockResolvedValue({ data: { data: [] } })
  })

  it('判据 1：识别入口在「新增商品」标题卡片内、与「重置」同排且在它之前', () => {
    render(<NewProductPage />)

    // 前置自证：这张卡真的是「新增商品」标题栏（不是随便一个带 testid 的容器）
    const card = screen.getByTestId('pf-title-card')
    expect(within(card).getByRole('heading', { level: 2 }).textContent).toContain('新增商品')

    const button = screen.getByTestId('image-recognize-button')
    // 🔴 本单的核心断言：按钮在标题卡片**内**（改前它在卡片外的独立容器里 ⇒ 必红）
    expect(card.contains(button)).toBe(true)
    // 唯一渲染点（不再有游离在卡片外的第二处）
    expect(screen.getAllByTestId('image-recognize-button')).toHaveLength(1)

    // 与「重置」同排 + 识别在前
    const actions = within(card).getByTestId('pf-title-actions')
    const reset = within(card).getByRole('button', { name: /重置/ })
    expect(actions.contains(button)).toBe(true)
    expect(actions.contains(reset)).toBe(true)
    expect(appearsBefore(button, reset)).toBe(true)

    // 卡片性：标题栏本身是白底带边框圆角的卡片（改前那个 `pt-4` 裸容器没有底色与边框）
    expect(card.className).toContain('bg-white')
    expect(card.className).toContain('border')
    expect(card.className).toContain('rounded')
  })

  it('判据 2：选图 → 上传 → 识别 → 字段回填；识别结果**不落库**', async () => {
    mockUploadImage.mockResolvedValue({ data: { data: { url: 'https://cdn.example.com/roll.jpg' } } })
    mockRecognize.mockResolvedValue({
      data: {
        data: {
          degraded: false,
          fields: [{ key: 'name', label: '商品标题', value: '识别出来的遮光窗帘' }],
        },
      },
    })
    render(<NewProductPage />)

    const file = new File(['x'], 'a.png', { type: 'image/png' })
    fireEvent.change(screen.getByTestId('image-recognize-input'), { target: { files: [file] } })

    // 上传 → 识别：targetType 与上传得到的地址逐字断言（快通道不依赖米宝）
    await waitFor(() =>
      expect(mockRecognize).toHaveBeenCalledWith('product', ['https://cdn.example.com/roll.jpg']),
    )
    expect(mockUploadImage).toHaveBeenCalledTimes(1)

    // 字段回填 + 来源徽标 + 识别结果可见
    await waitFor(() => expect(screen.getByDisplayValue('识别出来的遮光窗帘')).toBeTruthy())
    expect(screen.getByTestId('recognized-marker-name')).toBeTruthy()
    expect(screen.getByTestId('image-recognize-result')).toBeTruthy()

    // 🔴 识别结果**不落库**：全程零 create/update（提交永远是人的动作）
    expect(mockCreateProduct).not.toHaveBeenCalled()
  })

  it('判据 2b：识别入口留在**标题行**里 —— 字段回填后仍在标题卡片内（不被结果区挤出去）', async () => {
    mockUploadImage.mockResolvedValue({ data: { data: { url: 'https://cdn.example.com/roll.jpg' } } })
    mockRecognize.mockResolvedValue({
      data: {
        data: {
          degraded: false,
          fields: [{ key: 'name', label: '商品标题', value: '识别出来的遮光窗帘' }],
        },
      },
    })
    render(<NewProductPage />)

    fireEvent.change(screen.getByTestId('image-recognize-input'), {
      target: { files: [new File(['x'], 'a.png', { type: 'image/png' })] },
    })
    await waitFor(() => expect(screen.getByTestId('image-recognize-result')).toBeTruthy())

    const card = screen.getByTestId('pf-title-card')
    const button = screen.getByTestId('image-recognize-button')
    expect(card.contains(button)).toBe(true)
    expect(card.contains(screen.getByTestId('image-recognize-result'))).toBe(true)
  })
})
