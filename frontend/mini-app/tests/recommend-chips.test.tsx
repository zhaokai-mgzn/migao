/**
 * 推荐胶囊组件测试（主页顶部横滑，瑞幸 Agent 主页同款语言形态）
 *
 * 覆盖：渲染静态策划胶囊（图标+文案）、点胶囊发送对应 prompt、
 *       且**不出现任何商品图/商品名卡片**（与 UI-044「空态不铺商品」的裁定一致）
 *
 * UI-046: 小布主页按瑞幸 Agent 布局重做 —— 顶部横滑推荐胶囊（纯前端静态文案，不恢复商品接口）
 */
// case_ids: UI-046
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import RecommendChips from '../src/components/chat/RecommendChips'

describe('RecommendChips', () => {
  const mockOnPick = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染横滑容器与胶囊行', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    expect(container.querySelector('.recommend-chips')).toBeTruthy()
    expect(container.querySelector('.recommend-chips__scroll')).toBeTruthy()
    expect(container.querySelector('.recommend-chips__row')).toBeTruthy()
  })

  it('应渲染 5 条推荐胶囊（图标 + 文案）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    const chips = container.querySelectorAll('.recommend-chips__chip')
    expect(chips.length).toBe(5)

    expect(screen.getByText('遮光窗帘，一拉就黑')).toBeTruthy()
    expect(screen.getByText('算料报价，一分钟出')).toBeTruthy()
    expect(screen.getByText('热门花色，大家都在买')).toBeTruthy()
    expect(screen.getByText('货到哪了，一查便知')).toBeTruthy()
    expect(screen.getByText('想换窗帘，先挑布料')).toBeTruthy()
  })

  it('不应渲染任何商品图/商品名卡片（不恢复 NewArrivals 形态）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    // 无图片元素（商品图）
    expect(container.querySelectorAll('img').length).toBe(0)
    // 无商品卡类名残留
    expect(container.querySelectorAll('.new-arrivals').length).toBe(0)
    expect(container.querySelectorAll('.new-arrivals__card').length).toBe(0)
    // 无价格展示
    expect(screen.queryByText(/¥/)).toBeNull()
  })

  it('点击「遮光窗帘」胶囊应发送遮光窗帘推荐 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('遮光窗帘，一拉就黑'))
    expect(mockOnPick).toHaveBeenCalledWith('推荐一下遮光窗帘')
  })

  it('点击「算料报价」胶囊应发送算料 prompt（含 quote 路由关键词）', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('算料报价，一分钟出'))
    expect(mockOnPick).toHaveBeenCalledWith('帮我算一下窗帘用料和价格')
  })

  it('点击「热门花色」胶囊应发送热门商品推荐 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('热门花色，大家都在买'))
    expect(mockOnPick).toHaveBeenCalledWith('推荐一下热门商品')
  })

  it('点击「货到哪了」胶囊应发送物流查询 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('货到哪了，一查便知'))
    expect(mockOnPick).toHaveBeenCalledWith('帮我查一下物流')
  })

  it('点击「想换窗帘」胶囊应发送找产品 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('想换窗帘，先挑布料'))
    expect(mockOnPick).toHaveBeenCalledWith('推荐一下热门窗帘产品')
  })
})
