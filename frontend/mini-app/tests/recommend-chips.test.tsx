/**
 * 推荐胶囊组件测试（主页顶部横滑，瑞幸 Agent 主页同款语言形态）
 *
 * 覆盖：渲染静态策划胶囊（图标+文案）、点胶囊发送对应 prompt、
 *       且**不出现任何商品图/商品名卡片**（与 UI-044「空态不铺商品」的裁定一致）
 *
 * UI-044: 空态顶部横滑推荐胶囊（纯前端静态文案，不恢复商品接口）
 *         文案方向 = 能力钩子 + 场景痛点（2026-09-18 用户裁定，issue #4236）
 */
// case_ids: UI-044
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

    expect(screen.getByText('报个尺寸，我算你要几米布')).toBeTruthy()
    expect(screen.getByText('客厅西晒？先看遮光率')).toBeTruthy()
    expect(screen.getByText('卧室要暗，这几款遮光好')).toBeTruthy()
    expect(screen.getByText('预算有限？我帮你搭最省的')).toBeTruthy()
    expect(screen.getByText('货到哪了，一问便知')).toBeTruthy()
  })

  it('5 条胶囊文案互不重复（旧版 5 条里 3 条都落在「推荐商品」上 ⇒ 信息量被浪费）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    const texts = Array.from(container.querySelectorAll('.recommend-chips__text')).map((el) =>
      (el.textContent || '').trim(),
    )
    expect(texts.length).toBe(5)
    expect(new Set(texts).size).toBe(5)
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

  it('点击「报个尺寸」胶囊应发送算料 prompt（含 quote 路由关键词）', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('报个尺寸，我算你要几米布'))
    expect(mockOnPick).toHaveBeenCalledWith('帮我算一下窗帘用料和价格')
  })

  it('点击「客厅西晒」胶囊应发送遮光率知识问题', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('客厅西晒？先看遮光率'))
    expect(mockOnPick).toHaveBeenCalledWith('遮光率怎么选？客厅西晒适合哪种窗帘')
  })

  it('点击「卧室要暗」胶囊应发送卧室遮光窗帘推荐 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('卧室要暗，这几款遮光好'))
    expect(mockOnPick).toHaveBeenCalledWith('推荐几款卧室用的遮光窗帘')
  })

  it('点击「预算有限」胶囊应发送性价比推荐 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('预算有限？我帮你搭最省的'))
    expect(mockOnPick).toHaveBeenCalledWith('预算有限，帮我推荐性价比高的窗帘')
  })

  it('点击「货到哪了」胶囊应发送物流查询 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('货到哪了，一问便知'))
    expect(mockOnPick).toHaveBeenCalledWith('帮我查一下物流')
  })
})
