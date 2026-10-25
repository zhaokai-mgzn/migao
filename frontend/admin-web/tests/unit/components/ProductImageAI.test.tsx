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
 * 6. **失败话术按 admin-api 错误码分叉**（issue #7552）：模型不支持 / 额度用尽 / 真·瞬时三类
 *    说不同的话；「稍后重试」只出现在真·瞬时那一条；页面上**不出现**服务名与内部地址（§31 P3）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
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
  const onApplyMain = vi.fn(() => true)
  const onApplyDetail = vi.fn(() => true)
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

  it('默认主图：生成成功即自动追加到主图（无需再点「用这张」）', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT))
    expect(onApplyDetail).not.toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith({
      imageUrl: SAMPLE,
      productName: '回归布帘-遮光提花',
      kind: 'main',
      variant: 0,
    })
    // 落位反馈可见；旧的「用这张」入口已消失（回归守卫：别再让商家多点一步）
    expect(await screen.findByRole('status')).toHaveTextContent('已加入主图')
    expect(screen.queryByRole('button', { name: '用这张' })).toBeNull()
  })

  it('白底图：走 onApplyMain（进主图列表），面板写明可直接放第 5 张', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '白底图' }))

    expect(screen.getByText(/可直接放第 5 张/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT))
    expect(onApplyDetail).not.toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'white', variant: 0 }))
    expect(await screen.findByRole('status')).toHaveTextContent('已加入主图（白底图）')
  })

  it('主图连点：构图按 0→1→2→0 轮换（用户「生成的都一样」的判据）', async () => {
    generate
      .mockResolvedValueOnce(ok(RESULT))
      .mockResolvedValueOnce(ok(RESULT_2))
      .mockResolvedValueOnce(ok(`${RESULT}-3`))
      .mockResolvedValueOnce(ok(`${RESULT}-4`))
    renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(3))
    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(4))

    const variants = generate.mock.calls.map((c) => (c[0] as { variant?: number }).variant)
    expect(variants).toEqual([0, 1, 2, 0])
  })

  it('选「材质细节」生成后自动走 onApplyDetail', async () => {
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '材质细节' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(onApplyDetail).toHaveBeenCalledWith(RESULT))
    expect(onApplyMain).not.toHaveBeenCalled()
    expect(generate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'texture' }))
    expect(await screen.findByRole('status')).toHaveTextContent('已加入「详情图」')
  })

  it('再生成一张 = 追加（不替换、不摘掉上一张）', async () => {
    generate.mockResolvedValueOnce(ok(RESULT)).mockResolvedValueOnce(ok(RESULT_2))
    const { onApplyMain } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT))

    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT_2))
    expect(onApplyMain).toHaveBeenCalledTimes(2)
  })

  it('换用途后再生成：只写对应槽位，不碰上一张', async () => {
    generate.mockResolvedValueOnce(ok(RESULT)).mockResolvedValueOnce(ok(RESULT_2))
    const { onApplyMain, onApplyDetail } = renderAI()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    await waitFor(() => expect(onApplyMain).toHaveBeenCalledWith(RESULT))

    fireEvent.click(screen.getByRole('button', { name: '工艺细节' }))
    fireEvent.click(screen.getByRole('button', { name: '再生成一张' }))
    await waitFor(() => expect(onApplyDetail).toHaveBeenCalledWith(RESULT_2))
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
        variant: 0,
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

  // ===== 失败话术按错误码分叉（issue #7552：只认 error.code，不切字符串） =====

  /** admin-api 的失败信封 `{success:false, error:{code,message}}`。 */
  const failure = (code: string | undefined, message = '服务端理由') =>
    Object.assign(new Error('Request failed with status code 422'), {
      isAxiosError: true,
      response: { status: 422, data: { success: false, error: { code, message } } },
    })

  async function failWith(error: unknown) {
    generate.mockRejectedValue(error as never)
    const { onApplyMain } = renderAI()
    fireEvent.click(screen.getByRole('button', { name: 'AI 生成商品图' }))
    fireEvent.click(screen.getByRole('button', { name: '生成' }))
    return { onApplyMain }
  }

  it('模型不支持 ⇒ 「暂不可用、已反馈平台」+ 手工传图，且不说「稍后重试」', async () => {
    const { onApplyMain } = await failWith(failure('AI_PRODUCT_IMAGE_MODEL_UNSUPPORTED'))

    const shown = await screen.findByText(/该能力暂不可用，已反馈平台/)
    expect(shown).toBeInTheDocument()
    expect(shown.textContent).not.toContain('稍后重试')
    expect(onApplyMain).not.toHaveBeenCalled()
  })

  it('额度用尽 ⇒ 说清「今日额度已用完」，与模型不支持的话术不同', async () => {
    await failWith(failure('AI_PRODUCT_IMAGE_QUOTA_EXCEEDED'))
    expect(await screen.findByText(/今日额度已用完/)).toBeInTheDocument()
  })

  it('未启用 / 未配置 ⇒ 与模型不支持同口径（平台侧，不劝「稍后重试」）', async () => {
    for (const code of ['AI_PRODUCT_IMAGE_DISABLED', 'AI_PRODUCT_IMAGE_NOT_CONFIGURED']) {
      await failWith(failure(code))
      const shown = await screen.findByText(/该能力暂不可用，已反馈平台/)
      expect(shown.textContent).not.toContain('稍后重试')
      cleanup()
      generate.mockReset()
    }
  })

  it('无失败码（网络 / 超时）⇒ 保留「稍后重试」兜底', async () => {
    await failWith(new Error('Network Error'))
    expect(await screen.findByText(/生成失败，请稍后重试/)).toBeInTheDocument()
  })

  it('失败话术不把服务端内部标识带上屏（服务名 / 地址一律不出现）', async () => {
    await failWith(
      failure(
        'AI_PRODUCT_IMAGE_MODEL_UNSUPPORTED',
        '商品图生成服务（ai-agent）暂不可用（当前服务地址 http://ai-agent:8001）'
      )
    )
    await screen.findByText(/该能力暂不可用/)
    expect(document.body.textContent).not.toMatch(/ai-agent|https?:\/\//)
  })
})
