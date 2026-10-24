// case_ids: PR-074
/**
 * 商品图生成卡（issue #7541，B 端桌面）
 *
 * 钉住三件事：
 * 1. **卡型可达**：`ToolResultCard` 的 `generated_image` 分支能渲染
 *    （跨端契约 = `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）；
 * 2. **预览 + 下载**：有图时渲染预览图与「下载图片」按钮；点按钮走「取文件再存」，
 *    取不到时**打开原图 + 明说**，不谎报「已下载」；
 * 3. **空态/失败态可行动**：没有图片地址、图片加载失败都给出下一步（重新生成 / 后台上传），
 *    且**只出现用户看得懂的词**（不摆内部键名 / 模型名）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import ToolResultCard from '@/components/chat/ToolResultCard'

const IMAGE_URL = 'https://out.example.com/generated.png'

const DATA = {
  image_url: IMAGE_URL,
  model: 'qwen-image-3.0',
  product: { id: 'prod_001', name: '高遮光雪尼尔窗帘', kind: 'main' },
}

describe('GeneratedImageCard（ToolResultCard 分发）', () => {
  beforeEach(() => {
    // jsdom 不实现 createObjectURL ⇒ 直接定义（spyOn 在缺失的方法上会抛）
    Object.defineProperty(URL, 'createObjectURL', {
      value: vi.fn(() => 'blob:generated'),
      writable: true,
      configurable: true,
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: vi.fn(),
      writable: true,
      configurable: true,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('有图时渲染预览图与商品名（不摆内部键名 / 模型名）', () => {
    render(<ToolResultCard card={{ type: 'generated_image', data: DATA }} />)

    const image = screen.getByTestId('generated-image-card-img')
    expect(image.getAttribute('src')).toBe(IMAGE_URL)
    expect(image.getAttribute('alt')).toContain('高遮光雪尼尔窗帘')

    // 内部标识不上屏：不显示卡型名、不显示模型名
    const text = document.body.textContent || ''
    expect(text).not.toContain('generated_image')
    expect(text).not.toContain('qwen-image')
    expect(text).toContain('商品主图')
  })

  it('下载按钮存在，点击后把文件按「商品图-<商品名>.png」存盘', async () => {
    const blob = new Blob(['png'], { type: 'image/png' })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob })
    vi.stubGlobal('fetch', fetchMock)

    const clicks: HTMLAnchorElement[] = []
    const originalClick = HTMLAnchorElement.prototype.click
    HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
      clicks.push(this)
    }

    try {
      render(<ToolResultCard card={{ type: 'generated_image', data: DATA }} />)
      fireEvent.click(screen.getByRole('button', { name: /下载图片/ }))

      await waitFor(() => expect(clicks.length).toBe(1))
      expect(clicks[0].download).toBe('商品图-高遮光雪尼尔窗帘.png')
      expect(clicks[0].href).toContain('blob:generated')
      expect(fetchMock).toHaveBeenCalledWith(IMAGE_URL)
    } finally {
      HTMLAnchorElement.prototype.click = originalClick
      vi.unstubAllGlobals()
    }
  })

  it('取文件失败时打开原图并明说，不谎报已下载', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('CORS')))
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)

    try {
      render(<ToolResultCard card={{ type: 'generated_image', data: DATA }} />)
      fireEvent.click(screen.getByRole('button', { name: /下载图片/ }))

      await waitFor(() => expect(openSpy).toHaveBeenCalledWith(IMAGE_URL, '_blank', 'noopener'))
      const hint = await screen.findByTestId('generated-image-card-hint')
      expect(hint.textContent).toContain('另存为')
      expect(hint.textContent).not.toContain('已下载')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('没有图片地址时不画空图框，给出可行动的下一步', () => {
    render(
      <ToolResultCard
        card={{ type: 'generated_image', data: { product: { id: 'p', name: '窗帘' } } }}
      />,
    )

    const empty = screen.getByTestId('generated-image-card-empty')
    expect(empty.textContent).toContain('重新生成')
    expect(empty.textContent).toContain('商品管理')
    expect(screen.queryByTestId('generated-image-card-img')).toBeNull()
  })

  it('图片加载失败时提示链接可能过期并可重新加载', async () => {
    render(<ToolResultCard card={{ type: 'generated_image', data: DATA }} />)

    fireEvent.error(screen.getByTestId('generated-image-card-img'))

    const failed = await screen.findByTestId('generated-image-card-image-failed')
    expect(failed.textContent).toContain('过期')
    fireEvent.click(screen.getByRole('button', { name: '重新加载图片' }))
    await waitFor(() => expect(screen.queryByTestId('generated-image-card-image-failed')).toBeNull())
  })
})
