// case_ids: BM-028
/**
 * B 端「问米宝」快捷入口组件测试（issue #5747）
 *
 * 形态真值与 C 端**现行**判据一致（`.github/cases/ui.yml` 的 UI-014 / UI-044；用户 2026-09-18
 * 裁定「上个 2 列 × 3 行更好看」）：**六格等权、2 列 × 3 行**，无全宽主入口、无分组结构。
 *
 * ⚠️ 本文件此前声明 `# case_ids: UI-010, UI-014` —— 那是 **C 端（小布）的用例号**：
 * 连用例号一起被抄进 B 端，正是 issue #5747 的形态。现改钉 B 端自己的用例 BM-028。
 *
 * 第 6 格 = **查库存**（B 端专属能力：`batch_stock_query` / `stock_ledger_query` 挂
 * `product:list` 权限码，C 端 JWT 无权限码 ⇒ 不在 C 端面，见
 * `backend/ai-agent-service/app/graph/skills/product_skill.py`），补上「六格」的差额。
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import QuickActions from '../src/components/chat/QuickActions'

describe('QuickActions（B 端六格）', () => {
  const mockOnAction = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染标题', () => {
    render(<QuickActions onAction={mockOnAction} />)
    expect(screen.getByText('您可以试试以下问题')).toBeTruthy()
  })

  it('恰好六格等权（2 列 × 3 行）', () => {
    const { container } = render(<QuickActions onAction={mockOnAction} />)
    const items = container.querySelectorAll('.quick-actions__item')
    expect(items.length).toBe(6)
    for (const item of Array.from(items)) {
      // 全宽主入口已撤下（C 端 #4236 同款裁定）—— 留在 B 端就是「旧版 C 端页面」
      expect(item.className).not.toContain('quick-actions__item--wide')
    }
    // 负向：两栏分组结构（C 端 #4209 中间态）不得残留
    expect(container.querySelector('.quick-actions__group')).toBeNull()
    expect(container.querySelector('.quick-actions__row')).toBeNull()
  })

  it('六个入口齐全（含 B 端专属「查库存」）', () => {
    render(<QuickActions onAction={mockOnAction} />)

    for (const label of ['算料报价', '查订单', '查库存', '找产品', '售后咨询', '查物流']) {
      expect(screen.getByText(label)).toBeTruthy()
    }

    // UI-010 口径沿用：无「退换货」「转人工」文案残留
    expect(screen.queryByText('退换货')).toBeNull()
    expect(screen.queryByText('转人工')).toBeNull()
  })

  it('应渲染操作图标', () => {
    render(<QuickActions onAction={mockOnAction} />)

    expect(screen.getByText('🧮')).toBeTruthy()
    expect(screen.getByText('📦')).toBeTruthy()
    expect(screen.getByText('🔍')).toBeTruthy()
    expect(screen.getByText('🤝')).toBeTruthy()
    expect(screen.getByText('🚚')).toBeTruthy()
  })

  it('点击各入口应发送对应 prompt（逐格可断言）', () => {
    render(<QuickActions onAction={mockOnAction} />)

    const cases: [string, string][] = [
      ['算料报价', '帮我算一下窗帘用料和价格'],
      ['查订单', '帮我查一下最近的订单'],
      ['查库存', '帮我查一下库存'],
      ['找产品', '推荐一下热门窗帘产品'],
      ['售后咨询', '我想咨询售后问题'],
      ['查物流', '帮我查一下物流'],
    ]
    for (const [label, prompt] of cases) {
      mockOnAction.mockClear()
      fireEvent.click(screen.getByText(label))
      expect(mockOnAction).toHaveBeenCalledWith(prompt)
    }
  })
})
