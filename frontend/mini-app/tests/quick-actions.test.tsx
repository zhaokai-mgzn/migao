/**
 * 快捷操作组件测试
 *
 * 覆盖: 瑞幸式两栏分组入口（组头 + 行 + 箭头）、六入口全保留、点击触发回调
 *
 * UI-010: 小布聊天主页快捷入口改版 - 转人工→查物流、退换货→售后咨询
 * UI-014: 小布聊天主页快捷入口六格化 - 算料报价与推荐热门商品并列（取消全宽）
 * UI-044: 空态移除商品推荐卡，推荐改由「推荐热门商品」快捷对话入口承载
 * UI-046: 主页按瑞幸 Agent 布局重做 —— 「你可以这样对我说：」两栏分组卡（下单小助手/专属推荐师）
 */
// case_ids: UI-010, UI-014, UI-044, UI-046
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import QuickActions from '../src/components/chat/QuickActions'

/** 六个入口的 prompt 真值（改版前后必须逐字一致，不回归） */
const PROMPTS: Array<[string, string]> = [
  ['算料报价', '帮我算一下窗帘用料和价格'],
  ['找产品', '推荐一下热门窗帘产品'],
  ['查订单', '帮我查一下最近的订单'],
  ['推荐热门商品', '推荐一下热门商品'],
  ['售后咨询', '我想咨询售后问题'],
  ['查物流', '帮我查一下物流'],
]

describe('QuickActions', () => {
  const mockOnAction = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染瑞幸式标题「你可以这样对我说：」', () => {
    render(<QuickActions onAction={mockOnAction} />)
    expect(screen.getByText('你可以这样对我说：')).toBeTruthy()
  })

  it('应渲染两栏分组（下单小助手 / 专属推荐师）', () => {
    const { container } = render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('下单小助手')).toBeTruthy()
    expect(screen.getByText('专属推荐师')).toBeTruthy()

    const groups = container.querySelectorAll('.quick-actions__group')
    expect(groups.length).toBe(2)
    // 组头配色区分：蓝 / 紫（瑞幸同款两栏组头）
    expect(container.querySelectorAll('.quick-actions__group--blue').length).toBe(1)
    expect(container.querySelectorAll('.quick-actions__group--purple').length).toBe(1)
  })

  it('应渲染六个入口（六格时代的能力全保留，仅重排为两栏分组）', () => {
    const { container } = render(<QuickActions onAction={mockOnAction} />)

    const rows = container.querySelectorAll('.quick-actions__row')
    expect(rows.length).toBe(6)

    for (const [label] of PROMPTS) {
      expect(screen.getByText(label)).toBeTruthy()
    }

    // UI-010：无「退换货」「转人工」文案残留
    expect(screen.queryByText('退换货')).toBeNull()
    expect(screen.queryByText('转人工')).toBeNull()
  })

  it('每个入口行都带右箭头（瑞幸式可点行）', () => {
    const { container } = render(<QuickActions onAction={mockOnAction} />)
    const arrows = container.querySelectorAll('.quick-actions__row-arrow')
    expect(arrows.length).toBe(6)
    arrows.forEach((a) => expect((a.textContent || '').trim()).toBe('›'))
  })

  it('每个入口行都带图标', () => {
    render(<QuickActions onAction={mockOnAction} />)
    for (const icon of ['🧮', '🔍', '📦', '🔥', '🤝', '🚚']) {
      expect(screen.getByText(icon)).toBeTruthy()
    }
  })

  it('不应残留六格时代的 item / wide 全宽样式（UI-014：等权，不再跨整行）', () => {
    const { container } = render(<QuickActions onAction={mockOnAction} />)
    expect(container.querySelectorAll('.quick-actions__item').length).toBe(0)
    expect(container.querySelectorAll('.quick-actions__item--wide').length).toBe(0)
  })

  it.each(PROMPTS)('点击「%s」应发送对应 prompt（逐字不回归）', (label, prompt) => {
    render(<QuickActions onAction={mockOnAction} />)
    fireEvent.click(screen.getByText(label))
    expect(mockOnAction).toHaveBeenCalledWith(prompt)
  })
})
