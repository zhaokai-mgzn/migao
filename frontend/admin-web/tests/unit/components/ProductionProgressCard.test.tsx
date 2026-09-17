// case_ids: UI-045
/**
 * 生产进度卡（B 端桌面会话内）— issue #4016 P14「补发射点」（用户 2026-09-18 裁定）
 *
 * ## 为什么 B 端桌面也要有这一端
 *
 * `production_progress_query` 同时绑在**两个 persona** 的 Skill 上（C 端小布 + B 端米宝，
 * 评测用例 CH-039/CH-040）⇒ 契约不变式「后端能发到这一端的卡型 ⊆ 这一端能渲染的卡型」
 * 要求三端都有渲染分支。**红证**：只补后端映射、不补本端分支时，
 * `test_card_type_cross_end_contract.py` 实测报
 * `B端桌面 admin-web ToolResultCard 缺 ['production_progress']`。
 *
 * ## 展示口径与 C 端逐字段一致（跨端一致性）
 *
 * 兼容两种载荷（缺一不可）：
 * 1. 工序树：`{positions[].operations[], progress:{total,done,percent}, expected_delivery_at}`
 * 2. 米宝精简进度：`{progress_percent, current_operation, pending_operations[],
 *    total_operations, done_operations, expected_delivery_date}`
 * 空态（两种载荷都没带工序信息）→「暂无生产进度」（不显示假进度、不空白）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ToolResultCard from '@/components/chat/ToolResultCard'
import ProductionProgressCard from '@/components/chat/ProductionProgressCard'

/** 米宝精简进度载荷 */
const SIMPLE = {
  order_no: 'CSO260915-02615',
  status: 'producing',
  progress_percent: 40,
  current_operation: '韩褶',
  pending_operations: ['韩褶', '定型', '打包'],
  expected_delivery_date: '2026-09-25',
}

/** 工序树载荷（含内部字段，必须**不被渲染**） */
const TREE = {
  order_no: 'CSO260915-02615',
  positions: [
    {
      position_name: '帘身',
      operations: [
        { id: '1', operation: '裁剪', status: 'done', unit_price: 3.5, worker_name: '张师傅' },
        { id: '2', operation: '韩褶', status: 'doing', unit_price: 5, worker_name: '李师傅' },
      ],
    },
  ],
  progress: { total: 2, done: 1, percent: 50 },
  expected_delivery_at: '2026-09-25T00:00:00Z',
  qr_token: 'qr-token-1',
}

describe('ProductionProgressCard（B 端桌面会话卡）', () => {
  it('经 ToolResultCard 的 production_progress 分支渲染（接线）', () => {
    const card = { type: 'production_progress' as const, data: SIMPLE }
    render(<ToolResultCard card={card} />)
    expect(screen.getByTestId('production-progress-card')).toBeInTheDocument()
    expect(screen.queryByTestId('tool-result-card-unsupported')).not.toBeInTheDocument()
  })

  it('精简载荷：进度% / 当前工序 / 待完工序数 / 预计交付', () => {
    render(<ProductionProgressCard data={SIMPLE} />)
    expect(screen.getByTestId('progress-percent')).toHaveTextContent('40%')
    expect(screen.getByText('当前工序：韩褶')).toBeInTheDocument()
    expect(screen.getByText('待完 3 道工序')).toBeInTheDocument()
    expect(screen.getByText('预计交付 2026-09-25')).toBeInTheDocument()
  })

  it('工序树载荷：percent 取 progress.percent，已完按 done/total，交期取 ISO 前 10 位', () => {
    render(<ProductionProgressCard data={TREE} />)
    expect(screen.getByTestId('progress-percent')).toHaveTextContent('50%')
    expect(screen.getByText('已完 1/2 道')).toBeInTheDocument()
    expect(screen.getByText('当前工序：韩褶')).toBeInTheDocument()
    expect(screen.getByText('预计交付 2026-09-25')).toBeInTheDocument()
  })

  it('空态：两种载荷都无工序信息 → 「暂无生产进度」（不空白、不显示假进度）', () => {
    render(<ProductionProgressCard data={{ order_no: 'X', progress_percent: 0 }} />)
    expect(screen.getByText('暂无生产进度')).toBeInTheDocument()
    expect(screen.getByTestId('progress-percent')).toHaveTextContent('0%')
  })

  it('不泄漏内部信息：工人姓名 / 计件单价 / qr_token 不进卡片文案（两套账分离）', () => {
    const { container } = render(<ProductionProgressCard data={TREE} />)
    const text = container.textContent || ''
    expect(text).not.toContain('张师傅')
    expect(text).not.toContain('李师傅')
    expect(text).not.toContain('qr-token-1')
    expect(text).not.toContain('单价')
    expect(text).not.toContain('3.50')
    expect(text).not.toContain('worker')
  })
})