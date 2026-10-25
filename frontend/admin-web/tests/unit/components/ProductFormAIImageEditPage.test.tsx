// case_ids: UI-129
/**
 * 复现「编辑商品页」的落位回退（issue #7533 复现回归）。
 *
 * 用户逐字（2026-10-25）：「生成的图片没有填入主图，这里主图是允许有多张的」
 * 「保存后也没有更新到主图，还是老问题」，并给出 DB 读数：`products.images` 仍是那一张色卡。
 *
 * 🔴 与既有 `ProductFormAIImage.test.tsx` 的差别：那边把 `ImageUploader` 换成了 div、
 * 且**父组件从不再渲染**；真实编辑页 `/products/[id]/edit` 每次渲染都会**新建** `initialData`
 * 对象字面量（`EditProduct.tsx`），而 `ProductForm` 有一条 `useEffect(..., [initialData])`
 * 把表单 merge 回 `initialData`。本用例用**真实 ImageUploader** 复现这条路径。
 */
import { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ProductForm from '@/components/products/ProductForm'
import { aiProductImageApi } from '@/lib/api'

vi.mock('@/components/products/SkuMatrix', () => ({
  default: () => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'sku-matrix' }, 'SkuMatrix')
  },
}))
vi.mock('@/components/products/ProductAttributes', () => ({
  default: () => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'product-attributes' }, 'ProductAttributes')
  },
}))
vi.mock('@/components/products/RichTextEditor', () => ({
  default: () => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'rich-text-editor' }, 'RichTextEditor')
  },
}))
vi.mock('@/lib/product-utils', async (importOriginal) => {
  const actual = await importOriginal<any>()
  return { ...actual, validateProductForm: () => ({}) }
})
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<any>()
  return {
    ...actual,
    categoryApi: { getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }) },
    aiProductImageApi: { generate: vi.fn() },
    fileApi: { upload: vi.fn() },
  }
})

const generate = vi.mocked(aiProductImageApi.generate)
const SAMPLE = 'https://oss.example.com/sample.png'
const RESULT = 'https://oss.example.com/generated.png'
const ok = (url: string) => ({ data: { success: true, data: { url, model: 'qwen-image-3.0' } } }) as never

/** 真实编辑页的形态：`initialData` 每次渲染都是**新对象**（EditProduct.tsx 的对象字面量）。 */
function EditPageHarness({ images = [SAMPLE], name = '回归布帘' }: { images?: string[]; name?: string } = {}) {
  const [, setTick] = useState(0)
  const initialData = { name, images, detailImages: [] }
  return (
    <div>
      <button type="button" onClick={() => setTick((t) => t + 1)}>
        父组件再渲染
      </button>
      <ProductForm initialData={initialData as never} onSubmit={vi.fn()} submitText="保存修改" />
    </div>
  )
}

/** 商品主图位的真实 DOM 读数：`ImageUploader` 的图片 alt 是 `图片 N`。 */
const mainTiles = () =>
  screen.getAllByAltText(/^图片 \d+$/).map((el) => el.getAttribute('src') || '')

describe('编辑页 × AI 生图落位（真实 ImageUploader）', () => {
  beforeEach(() => {
    generate.mockReset()
    generate.mockResolvedValue(ok(RESULT))
  })

  it('生成成功后主图位多一张；父组件再渲染后不得被 initialData 冲掉', async () => {
    render(<EditPageHarness />)
    expect(mainTiles()).toEqual([SAMPLE])

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(mainTiles()).toEqual([RESULT, SAMPLE]))

    // 真实编辑页只要父组件再渲染一次（任何 state 变化 / router.refresh），
    // `initialData` 就是新对象 ⇒ `ProductForm` 的同步 effect 会把图片列表 merge 回服务端值。
    fireEvent.click(screen.getByRole('button', { name: '父组件再渲染' }))
    await waitFor(() => expect(mainTiles()).toEqual([RESULT, SAMPLE]))
  }, 20000)

  it('内容真的变了（换商品 / 服务端刷新出不同数据）⇒ 仍然同步进表单', async () => {
    const { rerender } = render(<EditPageHarness />)
    expect(mainTiles()).toEqual([SAMPLE])
    const reloaded = 'https://oss.example.com/reloaded.png'
    rerender(<EditPageHarness images={[SAMPLE, reloaded]} name="换了一个商品" />)
    await waitFor(() => expect(mainTiles()).toEqual([SAMPLE, reloaded]))
  }, 20000)
})
