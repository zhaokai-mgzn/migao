/**
 * 推荐胶囊组件测试（主页顶部，3 条 × 3 行居中）
 *
 * 覆盖：渲染静态策划胶囊（图标+专业服务句）、点胶囊发送对应 prompt、
 *       居中竖排结构（非横滑）、且**不出现任何商品图/商品名卡片**
 *       （与 UI-044「空态不铺商品」的裁定一致）
 *
 * UI-044: 空态顶部推荐胶囊（纯前端静态文案，不恢复商品接口）
 *         形态沿革：横滑 5 条 → 3 条 × 3 行居中（2026-09-18 用户裁定，issue #4236）
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

  it('应渲染胶囊容器', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    expect(container.querySelector('.recommend-chips')).toBeTruthy()
  })

  it('应渲染 3 条推荐胶囊（图标 + 专业服务句）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    const chips = container.querySelectorAll('.recommend-chips__chip')
    expect(chips.length).toBe(3)

    expect(screen.getByText('按窗尺寸测算用布量与报价')).toBeTruthy()
    expect(screen.getByText('遮光率等级与适用场景')).toBeTruthy()
    expect(screen.getByText('查询订单物流轨迹')).toBeTruthy()
  })

  it('应为居中竖排结构（横滑实现已按 issue #4236 撤下，不得残留）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    // 横滑容器/行已移除：3 条各占一行、居中 —— 横滑必然左对齐 + 右端截断，与「居中」相斥
    expect(container.querySelectorAll('.recommend-chips__scroll').length).toBe(0)
    expect(container.querySelectorAll('.recommend-chips__row').length).toBe(0)
  })

  it('3 条文案互不重复，且各指向不同能力（不重复堆「推荐商品」）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    const texts = Array.from(container.querySelectorAll('.recommend-chips__text')).map((el) =>
      (el.textContent || '').trim(),
    )
    expect(texts.length).toBe(3)
    expect(new Set(texts).size).toBe(3)
    // 已被裁掉的两条不得残留
    expect(screen.queryByText('高遮光率卧室窗帘选型')).toBeNull()
    expect(screen.queryByText('按预算筛选高性价比方案')).toBeNull()
  })

  it('文案应专业（无口语化称呼/语气词）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    const all = Array.from(container.querySelectorAll('.recommend-chips__text'))
      .map((el) => el.textContent || '')
      .join('')
    // 「我/你/一问便知/搭最省」这类聊天语气必须已被替换掉
    for (const taboo of ['我', '你', '一问便知', '搭最省']) {
      expect(all).not.toContain(taboo)
    }
  })

  it('不应渲染任何商品图/商品名卡片（不恢复 NewArrivals 形态）', () => {
    const { container } = render(<RecommendChips onPick={mockOnPick} />)
    expect(container.querySelectorAll('img').length).toBe(0)
    expect(container.querySelectorAll('.new-arrivals').length).toBe(0)
    expect(container.querySelectorAll('.new-arrivals__card').length).toBe(0)
    expect(screen.queryByText(/¥/)).toBeNull()
  })

  it('点击「按窗尺寸测算用布量与报价」应发送算料 prompt（含 quote 路由关键词）', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('按窗尺寸测算用布量与报价'))
    expect(mockOnPick).toHaveBeenCalledWith('帮我算一下窗帘用料和价格')
  })

  it('点击「遮光率等级与适用场景」应发送遮光率知识问题', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('遮光率等级与适用场景'))
    expect(mockOnPick).toHaveBeenCalledWith('遮光率怎么选？客厅西晒适合哪种窗帘')
  })

  it('点击「查询订单物流轨迹」应发送物流查询 prompt', () => {
    render(<RecommendChips onPick={mockOnPick} />)
    fireEvent.click(screen.getByText('查询订单物流轨迹'))
    expect(mockOnPick).toHaveBeenCalledWith('帮我查一下物流')
  })
})
