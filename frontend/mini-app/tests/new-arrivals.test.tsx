// case_ids: PR-001
/**
 * NewArrivals 新品推荐组件测试
 *
 * 覆盖：空态欢迎屏展示商家推荐商品（C 端新品推荐位）：
 * - 拉取 /chat/products/new-arrivals 并渲染横滑卡片
 * - 点击商品卡片 → 唤起对话询问该商品
 * - 加载失败/无数据 → 不渲染（降级不阻塞对话）
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import NewArrivals from '../src/components/chat/NewArrivals'

jest.mock('../src/services/productService', () => ({
  getNewArrivals: jest.fn(),
}))

import { getNewArrivals } from '../src/services/productService'

const mockGetNewArrivals = getNewArrivals as jest.Mock

describe('NewArrivals', () => {
  beforeEach(() => {
    mockGetNewArrivals.mockReset()
  })

  it('应渲染新品推荐卡片（名称+价格）', async () => {
    mockGetNewArrivals.mockResolvedValue([
      { id: 'p1', name: '遮光窗帘', price: 199, image: 'img1' },
      { id: 'p2', name: '北欧风窗帘', price: 299, image: 'img2' },
    ])
    render(<NewArrivals onPick={jest.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('遮光窗帘')).toBeTruthy()
      expect(screen.getByText('北欧风窗帘')).toBeTruthy()
    })
    expect(screen.getByText(/新品推荐/)).toBeTruthy()
  })

  it('点击商品卡片应唤起对话（onPick 传商品名）', async () => {
    mockGetNewArrivals.mockResolvedValue([
      { id: 'p1', name: '遮光窗帘', price: 199, image: 'img1' },
    ])
    const onPick = jest.fn()
    render(<NewArrivals onPick={onPick} />)

    await waitFor(() => {
      expect(screen.getByText('遮光窗帘')).toBeTruthy()
    })
    fireEvent.click(screen.getByText('遮光窗帘'))
    expect(onPick).toHaveBeenCalledWith('遮光窗帘')
  })

  it('无推荐数据时不渲染（降级）', async () => {
    mockGetNewArrivals.mockResolvedValue([])
    const { container } = render(<NewArrivals onPick={jest.fn()} />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })

  it('拉取失败时不渲染（不阻塞对话）', async () => {
    mockGetNewArrivals.mockRejectedValue(new Error('network'))
    const { container } = render(<NewArrivals onPick={jest.fn()} />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })
})
