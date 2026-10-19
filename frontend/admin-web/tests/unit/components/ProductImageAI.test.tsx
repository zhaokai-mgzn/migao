// case_ids: UI-129
/**
 * ProductImageAI 组件测试（issue #7335 · 建品页「AI 生成商品图」）。
 *
 * 判据：
 * 1. 没有样图 ⇒ 入口不可用 + 明确提示（不让商家点了才发现没样图）；
 * 2. 有样图 ⇒ 选用途后「生成」调 `aiProductImageApi.generate`（imageUrl = 第一张图）；
 * 3. 「用这张」：主图 ⇒ `onApplyMain`；细节图 ⇒ `onApplyDetail`（不自动落库，只是写表单）；
 * 4. 生成中按钮 loading（不可重复提交）；失败可见错误文案。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ProductImageAI from '@/components/products/ProductImageAI'
import { aiProductImageApi } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    aiProductImageApi: { generate: vi.fn() },
  }
})

const generate = vi.mocked(aiProductImageApi.generate)

const SAMPLE = 'https://oss.example.com/sample.png'
const RESULT = 'https://oss.example.com/generated.png'

const ok = (url = RESULT) =>
  ({ data: { success: true, data: { url, model: 'qwen-image-3.0' } } }) as never

function renderAI(overrides: Partial<React.ComponentProps<typeof ProductImageAI>> = {}) {
  const onApplyMain = vi.fn()
  const onApplyDetail = vi.fn()
  render(
    <ProductImageAI
      sampleImage={SAMPLE}
      productName="回归布帘-遮光提花"
      onApplyMain={onApplyMain}
      onApplyDetail={onApplyDetail}
      {...overrides}
    />
  )
  return { onApplyMain, onApplyDetail }
}

describe('ProductImageAI', () => {
  beforeEach(() => {
    generate.mockReset()
    generate.mockResolvedValue(ok())
  })

  it('没有样图时按钮不可用，并提示先上传样图', () => {
    renderAI({ sampleImage: undefined })
    expect(screen.getByRole('button', { name: 'AI 生成商品图' })).toBeDisabled()
    expect(screen.getByText(/先上传一张样图/)).toBeInTheDocument()
  })

  it('选「材质细节」生成后，「用这张」走 onApplyDetail', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '材质细节' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() =>
      expect(generate).toHaveBeenCalledWith({
        imageUrl: SAMPLE,
        productName: '回归布帘-遮光提花',
        kind: 'texture',
      })
    )
    const apply = await screen.findByRole('button', { name: '用这张' })
    fireEvent.click(apply)

    expect(onApplyDetail).toHaveBeenCalledWith(RESULT)
    expect(onApplyMain).not.toHaveBeenCalled()
  })

  it('默认主图：生成后「用这张」走 onApplyMain', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    fireEvent.click(await screen.findByRole('button', { name: '用这张' }))

    expect(onApplyMain).toHaveBeenCalledWith(RESULT)
    expect(onApplyDetail).not.toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'main' }))
  })

  it('生成中按钮 loading；失败时展示可行动错误', async () => {
    let reject!: (e: unknown) => void
    generate.mockReturnValue(new Promise((_, r) => { reject = r }) as never)

    renderAI()
    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    const generating = await screen.findByRole('button', { name: '生成' })
    expect(generating).toBeDisabled()

    reject(new Error('boom'))
    expect(await screen.findByText(/生成失败，请稍后重试/)).toBeInTheDocument()
  })
})
