/**
 * 快捷操作组件测试
 *
 * 覆盖: 渲染默认操作、点击触发回调
 *
 * UI-010: 小布聊天主页快捷入口改版 - 转人工→查物流、退换货→售后咨询
 */
// case_ids: UI-010
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

  it('应渲染4个默认快捷操作（查订单/找产品/售后咨询/查物流）', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('查订单')).toBeTruthy()
    expect(screen.getByText('找产品')).toBeTruthy()
    expect(screen.getByText('售后咨询')).toBeTruthy()
    expect(screen.getByText('查物流')).toBeTruthy()

    // UI-010：无「退换货」「转人工」文案残留
    expect(screen.queryByText('退换货')).toBeNull()
    expect(screen.queryByText('转人工')).toBeNull()
  })

  it('应渲染操作图标', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('📦')).toBeTruthy()
    expect(screen.getByText('🔍')).toBeTruthy()
    expect(screen.getByText('🤝')).toBeTruthy()
    expect(screen.getByText('🚚')).toBeTruthy()
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
