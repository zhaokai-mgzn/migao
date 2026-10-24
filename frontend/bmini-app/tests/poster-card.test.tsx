// case_ids: PR-053
/**
 * 营销海报卡（issue #7351，B 端移动 H5）
 *
 * 钉住三件事：
 * 1. **卡型可达**：`MessageBubble` 的 `marketing_poster` 分支能渲染
 *    （跨端契约 = `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）；
 * 2. **保存到相册**：微信内置浏览器 ⇒ 弹「长按保存」提示（JS 无法直接写相册，
 *    不谎报「已保存」）；其它浏览器 ⇒ 触发带 `download` 的锚点 + toast；
 * 3. **降级不撒谎**：商品图没载进来 ⇒ 明说「无图海报」；渲染失败有重试。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'

jest.mock('../src/utils/poster/posterCanvas', () => ({
  renderMarketingPoster: jest.fn(),
}))

import { renderMarketingPoster } from '../src/utils/poster/posterCanvas'
import PosterCard from '../src/components/cards/PosterCard'

const mockedRender = renderMarketingPoster as jest.Mock

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

describe('PosterCard（B 端移动）', () => {
  const originalUA = window.navigator.userAgent

  beforeEach(() => {
    jest.clearAllMocks()
    mockedRender.mockResolvedValue({
      dataUrl: 'data:image/png;base64,POSTER',
      width: 750,
      height: 1000,
      hadImage: true,
    })
  })

  afterEach(() => {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: originalUA,
      configurable: true,
    })
  })

  it('渲染海报图并把商品事实 + 操作员文案交给渲染层', async () => {
    const { container } = render(<PosterCard data={DATA} />)

    await waitFor(() => expect(container.querySelector('.poster-card__image')).toBeTruthy())
    const image = container.querySelector('.poster-card__image') as HTMLImageElement
    expect(image.getAttribute('src')).toBe('data:image/png;base64,POSTER')

    const view = mockedRender.mock.calls[0][0]
    expect(view.product.name).toBe('高遮光雪尼尔窗帘')
    expect(view.copy).toEqual({ title: '新品上市', selling_points: ['高遮光', '免烫易打理'] })
  })

  it('微信内：点「保存到相册」弹长按保存提示（不谎报已保存）', async () => {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: 'Mozilla/5.0 (iPhone) MicroMessenger/8.0',
      configurable: true,
    })

    render(<PosterCard data={DATA} />)
    await screen.findByText('保存到相册')
    fireEvent.click(screen.getByText('保存到相册'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ content: expect.stringContaining('长按') }),
    )
  })

  it('普通浏览器：触发带 download 的锚点 + toast', async () => {
    const clicks: Array<{ href: string; download: string }> = []
    const spy = jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicks.push({ href: this.href, download: this.download })
      })

    render(<PosterCard data={DATA} />)
    await screen.findByText('保存到相册')
    fireEvent.click(screen.getByText('保存到相册'))

    expect(clicks).toEqual([
      { href: 'data:image/png;base64,POSTER', download: '营销海报-高遮光雪尼尔窗帘.png' },
    ])
    expect(Taro.showToast).toHaveBeenCalled()
    spy.mockRestore()
  })

  it('商品图没载进来：仍出海报，但明确告知「无图海报」', async () => {
    mockedRender.mockResolvedValue({
      dataUrl: 'data:image/png;base64,NOIMAGE',
      width: 750,
      height: 1000,
      hadImage: false,
    })

    render(<PosterCard data={DATA} />)

    expect(await screen.findByText(/无图海报/)).toBeTruthy()
  })

  it('渲染失败展示错误 + 重试（不返回空白图）', async () => {
    mockedRender.mockRejectedValueOnce(new Error('海报生成失败：画布拿不到 2d 上下文'))
    const { container } = render(<PosterCard data={DATA} />)

    expect(await screen.findByText(/海报生成失败/)).toBeTruthy()
    expect(container.querySelector('.poster-card__image')).toBeNull()

    mockedRender.mockResolvedValueOnce({
      dataUrl: 'data:image/png;base64,RETRY',
      width: 750,
      height: 1000,
      hadImage: true,
    })
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(container.querySelector('.poster-card__image')).toBeTruthy())
  })
})
