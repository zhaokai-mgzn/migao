// case_ids: PP-011
// PP-011（issue #4000，M4-H 按需单据渲染）：计件汇总 —— 合计（total）+ per_operation 明细
// + per_worker 分人（有则展示）+ 空态。
// 真值源：docs/curtain-production-rules.md §4 计件（计件工资 = Σ 报工数量 × 工序单价；
// 单工序一人制；与对外加工费两套账分离）。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import PieceworkTable from '@/components/production/PieceworkTable'
import type { PieceworkSummary } from '@/types'

/** GET /api/admin/production/orders/{orderId}/piecework 的响应（后端 Map → snake_case 键） */
const summary: PieceworkSummary = {
  total: 184.5,
  per_worker: { 蒋雪云: 96, 李红梅: 88.5 },
  per_operation: [
    { operation: '定型-布', amount: 96 },
    { operation: '韩褶-布', amount: 88.5 },
  ],
}

describe('PieceworkTable', () => {
  it('渲染计件合计与 per_operation 明细', () => {
    render(<PieceworkTable summary={summary} />)

    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥184.50')

    const first = screen.getByTestId('piecework-operation-0')
    expect(within(first).getByText('定型-布')).toBeInTheDocument()
    expect(within(first).getByTestId('piecework-operation-amount')).toHaveTextContent('¥96.00')

    const second = screen.getByTestId('piecework-operation-1')
    expect(within(second).getByText('韩褶-布')).toBeInTheDocument()
    expect(within(second).getByTestId('piecework-operation-amount')).toHaveTextContent('¥88.50')
  })

  it('per_worker 非空时展示分人金额', () => {
    render(<PieceworkTable summary={summary} />)

    const worker = screen.getByTestId('piecework-worker-0')
    expect(within(worker).getByText('蒋雪云')).toBeInTheDocument()
    expect(within(worker).getByTestId('piecework-worker-amount')).toHaveTextContent('¥96.00')
    expect(screen.getByTestId('piecework-worker-1')).toBeInTheDocument()
  })

  it('无报工数据（total=0 且无明细）渲染空态', () => {
    render(<PieceworkTable summary={{ total: 0, per_worker: {}, per_operation: [] }} />)

    expect(screen.getByText('暂无计件数据')).toBeInTheDocument()
  })

  it('summary 缺省同样走空态（接口失败不白屏）', () => {
    render(<PieceworkTable summary={null} />)

    expect(screen.getByText('暂无计件数据')).toBeInTheDocument()
  })
})
