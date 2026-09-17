/**
 * 快捷操作组件测试
 *
 * 覆盖: 渲染默认操作（六格等权，算料报价取消全宽）、点击触发回调
 *
 * UI-010: 小布聊天主页快捷入口改版 - 转人工→查物流、退换货→售后咨询
 * UI-014: 小布聊天主页快捷入口六格化 - 算料报价与推荐热门商品并列（取消全宽）
 * UI-044: 空态移除商品推荐卡，推荐改由「推荐热门商品」快捷对话入口承载
 */
// case_ids: UI-010, UI-014, UI-044
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import QuickActions from '../src/components/chat/QuickActions'

describe('QuickActions', () => {
  const mockOnAction = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染标题', () => {
    render(<QuickActions onAction={mockOnAction} />)
    expect(screen.getByText('您可以试试以下问题')).toBeTruthy()
  })

  it('应渲染默认快捷操作（算料报价/推荐热门商品/查订单/找产品/售后咨询/查物流）', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('算料报价')).toBeTruthy()
    expect(screen.getByText('推荐热门商品')).toBeTruthy()
    expect(screen.getByText('查订单')).toBeTruthy()
    expect(screen.getByText('找产品')).toBeTruthy()
    expect(screen.getByText('售后咨询')).toBeTruthy()
    expect(screen.getByText('查物流')).toBeTruthy()

    // UI-010：无「退换货」「转人工」文案残留
    expect(screen.queryByText('退换货')).toBeNull()
    expect(screen.queryByText('转人工')).toBeNull()
  })

  it('算料报价为首项且与其他入口等权（6 个入口、均无 wide 全宽样式）', () => {
    const { container } = render(<QuickActions onAction={mockOnAction} />)
    const items = container.querySelectorAll('.quick-actions__item')
    expect(items.length).toBe(6)
    const first = items[0]
    expect(first.textContent).toContain('算料报价')
    expect(first.className).not.toContain('quick-actions__item--wide')
    items.forEach((item) => {
      expect(item.className).not.toContain('quick-actions__item--wide')
    })
  })

  it('应渲染操作图标', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('🧮')).toBeTruthy()
    expect(screen.getByText('🔥')).toBeTruthy()
    expect(screen.getByText('📦')).toBeTruthy()
    expect(screen.getByText('🔍')).toBeTruthy()
    expect(screen.getByText('🤝')).toBeTruthy()
    expect(screen.getByText('🚚')).toBeTruthy()
  })

  it('点击"算料报价"应触发算料 prompt（含 quote 路由关键词）', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('算料报价'))

    expect(mockOnAction).toHaveBeenCalledWith('帮我算一下窗帘用料和价格')
  })

  it('点击"推荐热门商品"应触发推荐 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('推荐热门商品'))

    expect(mockOnAction).toHaveBeenCalledWith('推荐一下热门商品')
  })

  it('点击"查订单"应触发对应 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('查订单'))

    expect(mockOnAction).toHaveBeenCalledWith('帮我查一下最近的订单')
  })

  it('点击"找产品"应触发对应 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('找产品'))

    expect(mockOnAction).toHaveBeenCalledWith('推荐一下热门窗帘产品')
  })

  it('点击"售后咨询"应触发售后 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('售后咨询'))

    expect(mockOnAction).toHaveBeenCalledWith('我想咨询售后问题')
  })

  it('点击"查物流"应触发物流查询 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('查物流'))

    expect(mockOnAction).toHaveBeenCalledWith('帮我查一下物流')
  })
})
