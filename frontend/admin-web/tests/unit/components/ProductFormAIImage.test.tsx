// case_ids: UI-129
/**
 * 建品页「AI 生成商品图」落位闭环（issue #7533 · 用户 2026-10-23 反馈）。
 *
 * 用户逐字：「商品的AI生图点击生成后，不会自动设置到对应图片位置，而且保存后也没有」。
 * 改前：生成只回预览，必须再点「用这张」；漏点 ⇒ 表单没变 ⇒ 提交载荷没有该 URL ⇒ 保存后也没有。
 *
 * 判据（都是会红的形态）：
 * 1. 生成成功 ⇒ **主图位立即**变成 `[生成图, 原图]`（不需要任何额外点击）；
 * 2. 点「提交并上架」⇒ `onSubmit` 载荷的 `images` 带生成图（保存后仍在）；
 * 3. 再生成一张 ⇒ **替换**上一张（不叠加）；
 * 4. 用途选细节/工艺/场景 ⇒ 追加到 `detailImages` 末位。
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ProductForm from '@/components/products/ProductForm'
import { aiProductImageApi } from '@/lib/api'

vi.mock('@/components/products/ImageUploader', () => ({
  default: (props: any) => {
    const React = require('react')
    const testId = props.max === 9 ? 'uploader-detail' : 'uploader-main'
    return React.createElement('div', { 'data-testid': testId, 'data-images': (props.value || []).join('|') },
      // 模拟「生成期间商家自己动图片列表」（生图要 ~40s，落位必须基于最新列表）
      React.createElement('button', {
        type: 'button',
        'data-testid': `${testId}-clear`,
        onClick: () => props.onChange([]),
      }, '清空'),
    )
  },
}))
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
// 只放行校验（本用例只判落位与提交载荷，不测必填项）；价格推导保留真实现。
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
  }
})

const generate = vi.mocked(aiProductImageApi.generate)
const SAMPLE = 'https://oss.example.com/sample.png'
const RESULT = 'https://oss.example.com/generated.png'
const RESULT_2 = 'https://oss.example.com/generated-2.png'

const ok = (url: string) =>
  ({ data: { success: true, data: { url, model: 'qwen-image-3.0' } } }) as never

const mainImages = () => screen.getAllByTestId('uploader-main')[0].getAttribute('data-images')
const detailImages = () => screen.getAllByTestId('uploader-detail')[0].getAttribute('data-images')

function renderForm() {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <ProductForm
      initialData={{ name: '回归布帘', images: [SAMPLE], detailImages: [] } as never}
      onSubmit={onSubmit}
    />
  )
  return { onSubmit }
}

describe('ProductForm × AI 生成商品图（issue #7533）', () => {
  beforeEach(() => {
    generate.mockReset()
    generate.mockResolvedValue(ok(RESULT))
  })

  it('生成成功即写入主图位，且提交载荷带这张图（保存后仍在）', async () => {
    const { onSubmit } = renderForm()
    expect(mainImages()).toBe(SAMPLE)

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    // ① 没有任何额外点击，主图位就已经变了
    await waitFor(() => expect(mainImages()).toBe(`${RESULT}|${SAMPLE}`))

    // ② 保存 = 提交载荷带上生成图（改前的「保存后也没有」就在这里）
    fireEvent.click(screen.getByRole('button', { name: '提交并上架' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.images).toEqual([RESULT, SAMPLE])
    expect(payload.detailImages).toEqual([])
  })

  it('再生成一张 = 替换上一张，不叠加', async () => {
    generate.mockResolvedValueOnce(ok(RESULT)).mockResolvedValueOnce(ok(RESULT_2))
    renderForm()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(mainImages()).toBe(`${RESULT}|${SAMPLE}`))

    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(mainImages()).toBe(`${RESULT_2}|${SAMPLE}`))
  })

  it('生成中商家改过图片列表：落位基于最新列表（不复活已删的图）', async () => {
    let resolveGenerate!: (v: unknown) => void
    generate.mockReturnValue(new Promise((r) => { resolveGenerate = r }) as never)
    renderForm()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    // 生图期间商家清空了图片列表（面板随之收起，但生成的请求仍在飞）
    fireEvent.click(screen.getByTestId('uploader-main-clear'))
    await waitFor(() => expect(mainImages()).toBe(''))

    resolveGenerate(ok(RESULT))
    // 落位只写生成图 —— 已删的样图不得被 40s 前的闭包快照复活
    await waitFor(() => expect(mainImages()).toBe(RESULT))
  })

  it('细节/工艺/场景用途追加到详情图末位', async () => {
    renderForm()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '材质细节' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(detailImages()).toBe(RESULT))
    // 主图位不受影响
    expect(mainImages()).toBe(SAMPLE)
  })
})
