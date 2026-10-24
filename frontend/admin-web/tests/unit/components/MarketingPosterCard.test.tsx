// case_ids: PR-053
/**
 * 营销海报卡（issue #7351，B 端桌面）
 *
 * 钉住三件事：
 * 1. **卡型可达**：`ToolResultCard` 的 `marketing_poster` 分支能渲染
 *    （跨端契约 = `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）；
 * 2. **PC 下载**：点「下载海报」触发一个带 `download="营销海报-<商品名>.png"` 与
 *    `data:image/png` href 的锚点 —— 不是把 data URL 塞进新窗口；
 * 3. **降级不撒谎**：商品图没载进来时仍出海报，但明确提示「无图海报」；渲染失败有重试。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const renderMarketingPoster = vi.fn()

vi.mock('@/lib/marketing-poster-canvas', () => ({
  renderMarketingPoster: (...args: unknown[]) => renderMarketingPoster(...args),
}))

import ToolResultCard from '@/components/chat/ToolResultCard'

const DATA = {
  product: {
    id: 'prod_001',
    name: '高遮光雪尼尔窗帘',
    price: 299,
    unit: '米',
    image: 'https://img.example.com/1.jpg',
    specs: ['遮光率：95%'],
  },
  copy: { title: '新品上市', selling_points: ['高遮光', '免烫易打理'] },
}

describe('MarketingPosterCard（ToolResultCard 分发）', () => {
  beforeEach(() => {
    renderMarketingPoster.mockReset()
    renderMarketingPoster.mockResolvedValue({
      dataUrl: 'data:image/png;base64,POSTER',
      width: 750,
      height: 1000,
      hadImage: true,
    })
  })

  it('渲染海报图并把商品事实 + 操作员文案交给渲染层（不自行编文案）', async () => {
    render(<ToolResultCard card={{ type: 'marketing_poster', data: DATA }} />)

    const image = await screen.findByTestId('marketing-poster-img')
    expect(image.getAttribute('src')).toBe('data:image/png;base64,POSTER')
    expect(image.getAttribute('alt')).toContain('高遮光雪尼尔窗帘')

    const view = renderMarketingPoster.mock.calls[0][0]
    expect(view.product.name).toBe('高遮光雪尼尔窗帘')
    expect(view.copy).toEqual({ title: '新品上市', selling_points: ['高遮光', '免烫易打理'] })
    // 商品图经 resolveImageUrl 解析后交给绘制层（相对路径也能量）
    expect(view.product.image).toBe('https://img.example.com/1.jpg')
  })

  it('PC 下载：锚点带 download 文件名 + PNG data URL', async () => {
    const clicks: Array<{ href: string; download: string }> = []
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicks.push({ href: this.href, download: this.download })
      })

    render(<ToolResultCard card={{ type: 'marketing_poster', data: DATA }} />)
    const download = await screen.findByTestId('marketing-poster-download')
    fireEvent.click(download)

    expect(clicks).toEqual([
      { href: 'data:image/png;base64,POSTER', download: '营销海报-高遮光雪尼尔窗帘.png' },
    ])
    clickSpy.mockRestore()
  })

  it('商品图没载进来：仍出海报，但明确告知「无图海报」（不静默）', async () => {
    renderMarketingPoster.mockResolvedValue({
      dataUrl: 'data:image/png;base64,NOIMAGE',
      width: 750,
      height: 1000,
      hadImage: false,
    })

    render(<ToolResultCard card={{ type: 'marketing_poster', data: DATA }} />)

    expect(await screen.findByTestId('marketing-poster-no-image')).toBeTruthy()
    expect(screen.getByTestId('marketing-poster-img')).toBeTruthy()
  })

  it('渲染失败展示错误 + 重试（不返回空白图）', async () => {
    renderMarketingPoster.mockRejectedValueOnce(new Error('海报生成失败：画布拿不到 2d 上下文'))
    render(<ToolResultCard card={{ type: 'marketing_poster', data: DATA }} />)

    expect(await screen.findByTestId('marketing-poster-error')).toBeTruthy()
    expect(screen.queryByTestId('marketing-poster-img')).toBeNull()

    renderMarketingPoster.mockResolvedValueOnce({
      dataUrl: 'data:image/png;base64,RETRY',
      width: 750,
      height: 1000,
      hadImage: true,
    })
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(screen.getByTestId('marketing-poster-img')).toBeTruthy())
  })
})
