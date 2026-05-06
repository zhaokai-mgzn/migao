/**
 * 快捷操作组件测试
 *
 * 覆盖: 渲染默认操作、点击触发回调
 */
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

  it('应渲染4个默认快捷操作', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('查订单')).toBeTruthy()
    expect(screen.getByText('找产品')).toBeTruthy()
    expect(screen.getByText('退换货')).toBeTruthy()
    expect(screen.getByText('转人工')).toBeTruthy()
  })

  it('应渲染操作图标', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('📦')).toBeTruthy()
    expect(screen.getByText('🔍')).toBeTruthy()
    expect(screen.getByText('🔄')).toBeTruthy()
    expect(screen.getByText('👤')).toBeTruthy()
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

  it('点击"退换货"应触发对应 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('退换货'))

    expect(mockOnAction).toHaveBeenCalledWith('我想申请退换货')
  })

  it('点击"转人工"应触发对应 prompt', () => {
    render(<QuickActions onAction={mockOnAction} />)

    fireEvent.click(screen.getByText('转人工'))

    expect(mockOnAction).toHaveBeenCalledWith('我想联系人工客服')
  })
})
