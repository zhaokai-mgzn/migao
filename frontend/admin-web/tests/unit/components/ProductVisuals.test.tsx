// case_ids: UI-082
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  CustomerChatMock,
  DashboardMock,
  ProductionMock,
  StockMock,
  WorkbenchMock,
} from '@/components/corporate/ProductVisuals'

describe('ProductVisuals（官网产品界面示意）', () => {
  it('工作台示意：经营模块 + 黄金策问答 + 界面示意', () => {
    render(<WorkbenchMock />)
    expect(screen.getByText('生意管家 · 工作台')).toBeInTheDocument()
    expect(screen.getByText('界面示意')).toBeInTheDocument()
    for (const label of ['订单进度', '生产报工', '批次库存', '待处理事项', '订单趋势', '黄金策']) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('顾客对话示意：估算报价 + 估算标记', () => {
    render(<CustomerChatMock />)
    expect(screen.getByText('微信客服 · 智能客服')).toBeInTheDocument()
    expect(screen.getByText('估算报价')).toBeInTheDocument()
    expect(screen.getByText('估算')).toBeInTheDocument()
    expect(screen.getByText(/成交单价以商品库权威价为准/)).toBeInTheDocument()
  })

  it('经营报表示意：报表标签 + 每日简报', () => {
    render(<DashboardMock />)
    expect(screen.getByText('管理后台 · 经营报表')).toBeInTheDocument()
    for (const label of ['经营报表', '每日简报', '数据问答', '今日简报']) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('生产看板示意：裁剪 / 车位 / 后整', () => {
    render(<ProductionMock />)
    expect(screen.getByText('加工单 · 生产进度')).toBeInTheDocument()
    for (const stage of ['裁剪', '车位', '后整']) {
      expect(screen.getByText(stage)).toBeInTheDocument()
    }
    expect(screen.getByText(/扫码报工/)).toBeInTheDocument()
  })

  it('库存台账示意：批次 / 门幅 / 库存 / 成本', () => {
    render(<StockMock />)
    expect(screen.getByText('库存台账 · 批次')).toBeInTheDocument()
    for (const label of ['批次', '门幅', '库存', '成本', '库存变动', '计件明细']) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
    }
  })
})
