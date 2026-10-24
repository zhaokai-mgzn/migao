// case_ids: UI-129
/**
 * ProductImageAI 组件测试（issue #7335 · 建品页「AI 生成商品图」；issue #7533 改为生成即落位）。
 *
 * 判据：
 * 1. 没有样图 ⇒ 入口不可用 + 明确提示（不让商家点了才发现没样图）；
 * 2. 有样图 ⇒ 选用途后「生成」调 `aiProductImageApi.generate`（imageUrl = 样图）；
 * 3. **生成成功即自动填入图片位**：主图 ⇒ `onApplyMain(url)`，细节 ⇒ `onApplyDetail(url)`，
 *    无需再点任何按钮（issue #7533：改前多一步「用这张」，商家漏点 = 白生成 ⇒ 保存后也没有）；
 * 4. **再生成 = 替换**：第二次落位携带 `replaceUrl` = 上一次自动填入的那张（不叠加）；
 * 5. 多张图可切换样图（生成携带所选样图 URL）；生成中按钮 loading；失败不落位且错误可见。
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
const SAMPLE_2 = 'https://oss.example.com/sample-2.png'
const RESULT = 'https://oss.example.com/generated.png'
const RESULT_2 = 'https://oss.example.com/generated-2.png'

const ok = (url = RESULT) =>
  ({ data: { success: true, data: { url, model: 'qwen-image-3.0' } } }) as never

function renderAI(overrides: Partial<React.ComponentProps<typeof ProductImageAI>> = {}) {
  const onApplyMain = vi.fn()
  const onApplyDetail = vi.fn()
  render(
    <ProductImageAI
      sampleImages={[SAMPLE]}
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
    renderAI({ sampleImages: [] })
    expect(screen.getByRole('button', { name: 'AI 生成商品图' })).toBeDisabled()
    expect(screen.getByText(/先上传一张样图/)).toBeInTheDocument()
  })

  it('默认主图：生成成功即自动填入封面位（无需再点「用这张」）', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT, undefined))
    expect(onApplyDetail).not.toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith({
      imageUrl: SAMPLE,
      productName: '回归布帘-遮光提花',
      kind: 'main',
    })
    // 落位反馈可见；旧的「用这张」入口已消失（回归守卫：别再让商家多点一步）
    expect(await screen.findByRole('status')).toHaveTextContent('已填入主图封面位')
    expect(screen.queryByRole('button', { name: '用这张' })).toBeNull()
  })

  it('选「材质细节」生成后自动走 onApplyDetail', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '材质细节' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(onApplyDetail).toHaveBeenCalledWith(RESULT, undefined))
    expect(onApplyMain).not.toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'texture' }))
    expect(await screen.findByRole('status')).toHaveTextContent('已加入「详情图」')
  })

  it('再生成一张 = 替换：第二次携带上一次自动填入的 URL', async () => {
    generate.mockResolvedValueOnce(ok(RESULT)).mockResolvedValueOnce(ok(RESULT_2))
    const { onApplyMain } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT, undefined))

    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT_2, RESULT))
    expect(onApplyMain).toHaveBeenCalledTimes(2)
  })

  it('换用途后再生成：跨槽位也带上上一次的 URL（先摘旧位再写新位）', async () => {
    generate.mockResolvedValueOnce(ok(RESULT)).mockResolvedValueOnce(ok(RESULT_2))
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT, undefined))

    fireEvent.click(screen.getByRole('button', { name: '工艺细节' }))
    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(onApplyDetail).toHaveBeenCalledWith(RESULT_2, RESULT))
  })

  it('多张图时可切换样图，按选中的样图生成', async () => {
    renderAI({ sampleImages: [SAMPLE, SAMPLE_2] })

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '使用第2张作为样图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() =>
      expect(generate).toHaveBeenCalledWith({
        imageUrl: SAMPLE_2,
        productName: '回归布帘-遮光提花',
        kind: 'main',
      })
    )
  })

  it('生成中按钮 loading；失败时不落位、展示可行动错误', async () => {
    let reject!: (e: unknown) => void
    generate.mockReturnValue(new Promise((_, r) => { reject = r }) as never)
    const { onApplyMain } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    const generating = await screen.findByRole('button', { name: '生成' })
    expect(generating).toBeDisabled()

    reject(new Error('boom'))
    expect(await screen.findByText(/生成失败，请稍后重试/)).toBeInTheDocument()
    expect(onApplyMain).not.toHaveBeenCalled()
  })
})
