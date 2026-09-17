// case_ids: UI-045
/**
 * 顾客端生产进度卡测试（issue #3997，M4-G-3）
 *
 * 面向 C 端顾客：只展示**进度 / 当前工序 / 待完工序数 / 预计交付**，
 * 不得出现工人姓名、计件单价、成本、qr_token 等内部信息（两套账分离，真值源
 * docs/curtain-production-rules.md §4/§5）。
 * 空态（无工序数据）必须优雅降级，不崩不空白。
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import ProductionProgressCard from '../src/components/cards/ProductionProgressCard'
import MessageBubble from '../src/components/chat/MessageBubble'

/** 后端生产进度载荷（工序实例 + 进度 + 交期） */
const DATA = {
  order_id: 'CSO260915-02615',
  order_no: 'CSO260915-02615',
  qr_token: 'qr-token-1',
  status: 'producing',
  progress: { total: 5, done: 2, percent: 40 },
  positions: [
    {
      position_name: '布帘',
      operations: [
        { id: 'op1', operation: '精裁', status: 'done', qty: 11, unit: '米', unit_price: 3.5 },
        { id: 'op2', operation: '韩褶', status: 'pending', qty: 11, unit: '米', unit_price: 5, worker_name: '张师傅' },
      ],
    },
    {
      position_name: '纱帘',
      operations: [
        { id: 'op3', operation: '定型', status: 'pending', qty: 11, unit: '米', unit_price: 4 },
      ],
    },
  ],
  expected_delivery_at: '2026-09-25',
}

describe('ProductionProgressCard（顾客端生产进度卡）', () => {
  it('正常：展示进度百分比 / 当前工序 / 待完工序数 / 预计交付日期', () => {
    render(<ProductionProgressCard data={DATA} />)

    expect(screen.getByText('40%')).toBeTruthy()
    // 当前工序 = 第一个未完成工序
    expect(screen.getByText('当前工序：韩褶')).toBeTruthy()
    // 待完工序数 = status!=='done' 的工序数（韩褶 + 定型 = 2）
    expect(screen.getByText('待完 2 道工序')).toBeTruthy()
    expect(screen.getByText('预计交付 2026-09-25')).toBeTruthy()
  })

  it('进度缺省但工序齐全时：百分比按工序推导（不显示假进度）', () => {
    const { progress, ...rest } = DATA
    render(<ProductionProgressCard data={rest as typeof DATA} />)

    // done=1 / total=3 → 33%
    expect(screen.getByText('33%')).toBeTruthy()
    expect(screen.getByText('待完 2 道工序')).toBeTruthy()
  })

  it('空态：无工序数据时优雅降级（不崩、给文案、不出现当前工序行）', () => {
    render(<ProductionProgressCard data={{}} />)

    expect(screen.getByText('暂无生产进度')).toBeTruthy()
    expect(screen.queryByText(/当前工序/)).toBeNull()
    expect(screen.queryByText(/待完/)).toBeNull()
    expect(screen.queryByText(/预计交付/)).toBeNull()
  })

  it('交期字段缺省 → 不渲染交期行（优雅降级）', () => {
    const { expected_delivery_at, ...rest } = DATA
    render(<ProductionProgressCard data={rest as typeof DATA} />)

    expect(screen.getByText('40%')).toBeTruthy()
    expect(screen.queryByText(/预计交付/)).toBeNull()
  })

  it('不泄露内部信息（工人姓名 / 计件单价 / qr_token / 部位成本）', () => {
    const { container } = render(<ProductionProgressCard data={DATA} />)
    const text = container.textContent || ''

    expect(text).not.toContain('张师傅')
    expect(text).not.toContain('qr-token-1')
    expect(text).not.toContain('单价')
    expect(text).not.toContain('¥')
    expect(text).not.toContain('3.50')
    expect(text).not.toContain('worker')
  })

  it('经 MessageBubble 的 production_progress 分支真渲染（#4016 P14「补发射点」）', () => {
    // 本用例曾是**假接线验证**：只验证 renderCard 有分支、没验证后端会下发 ——
    // 而 `_detect_card_type` 当时**没有** `production_progress_query` 映射 ⇒ 组件永不渲染
    // （「交付物在 main ≠ 能力可达」）。用户 2026-09-18 裁定补发射点后，后端映射已补
    // （端到端那一格证据在 backend/ai-agent-service/tests/test_card_type_persist.py：
    //  工具结果 → event: card(type=production_progress) → metadata.cards）。
    render(
      <MessageBubble
        message={{
          id: 'm1',
          role: 'assistant',
          content: '',
          type: 'card',
          created_at: '2026-09-17T10:00:00Z',
          cardData: { type: 'production_progress', data: DATA },
        }}
      />,
    )

    expect(screen.getByText('40%')).toBeTruthy()
    expect(screen.getByText('当前工序：韩褶')).toBeTruthy()
    expect(screen.queryByText('📎 消息内容暂不支持预览')).toBeNull()
  })

  it('兼容米宝精简进度载荷（progress_percent/current_operation/pending_operations/expected_delivery_date）', () => {
    // 来源：M4-G-2 已合并的 GET /api/admin/agent/production/progress 返回形状（无 positions）
    render(
      <ProductionProgressCard
        data={{
          order_no: 'CSO260915-02615',
          status: 'producing',
          status_text: '生产中',
          progress_percent: 40,
          current_operation: '韩褶',
          pending_operations: ['韩褶', '定型'],
          total_operations: 5,
          done_operations: 2,
          expected_delivery_date: '2026-09-25',
        }}
      />,
    )

    expect(screen.getByText('40%')).toBeTruthy()
    expect(screen.getByText('当前工序：韩褶')).toBeTruthy()
    expect(screen.getByText('待完 2 道工序')).toBeTruthy()
    expect(screen.getByText('预计交付 2026-09-25')).toBeTruthy()
    // 有数据就不该落到空态
    expect(screen.queryByText('暂无生产进度')).toBeNull()
  })
})
