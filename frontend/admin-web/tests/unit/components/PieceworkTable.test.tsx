// case_ids: PP-011
// PP-011（issue #4000，M4-H 按需单据渲染）：计件汇总 —— 合计（total）+ per_operation 明细
// + per_worker 分人（有则展示）+ 空态。
// 真值源：docs/curtain-production-rules.md §4 计件（计件工资 = Σ 报工数量 × 工序单价；
// 单工序一人制；与对外加工费两套账分离）。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import PieceworkTable from '@/components/production/PieceworkTable'
import type { PieceworkSummary } from '@/types'

/** 被测组件源码：`key` 不进 DOM（React 内部用）⇒ 只能读源码判「key 里不得出现变体名」 */
const COMPONENT_SRC = readFileSync(
  join(process.cwd(), 'src/components/production/PieceworkTable.tsx'),
  'utf-8',
)

/** GET /api/admin/production/orders/{orderId}/piecework 的响应（后端 Map → snake_case 键） */
const summary: PieceworkSummary = {
  total: 184.5,
  per_worker: { 蒋雪云: 96, 李红梅: 88.5 },
  per_operation: [
    { operation: '定型-布', amount: 96 },
    { operation: '韩褶-布', amount: 88.5 },
  ],
}

/**
 * issue #4630（同一份 `per_operation` 数据的**第 4 个消费面**：加工单「生产」页计件表）：
 * 后端**已经**同时给 `logical_name` + `position`（#4621 读时派生、不写库）⇒ 界面渲染 `逻辑名 · 部位`。
 */
const summaryWithLogicalName: PieceworkSummary = {
  total: 184.5,
  per_worker: { 蒋雪云: 96 },
  per_operation: [
    { operation: '精裁-布', logical_name: '精裁', position: '布帘', amount: 96 },
    { operation: '韩褶-布', logical_name: '韩褶', position: '布帘', amount: 88.5 },
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

  // ── issue #4630：加工单生产页计件表改渲染「逻辑名 · 部位」（红证：改前必红）────────────

  it('per_operation 有 logical_name + position ⇒ 渲染「逻辑名 · 部位」，不出现变体名', () => {
    const { container } = render(<PieceworkTable summary={summaryWithLogicalName} />)

    const first = screen.getByTestId('piecework-operation-0')
    expect(within(first).getByText('精裁 · 布帘')).toBeInTheDocument()
    const second = screen.getByTestId('piecework-operation-1')
    expect(within(second).getByText('韩褶 · 布帘')).toBeInTheDocument()

    // 变体名（工人端快照名）不得出现在界面**任何**位置（含属性 / data-testid）
    expect(screen.queryByText('精裁-布')).not.toBeInTheDocument()
    expect(screen.queryByText('韩褶-布')).not.toBeInTheDocument()
    expect(container.innerHTML).not.toContain('精裁-布')
    expect(container.innerHTML).not.toContain('韩褶-布')

    // 金额明细不受影响（既有契约不变）
    expect(within(first).getByTestId('piecework-operation-amount')).toHaveTextContent('¥96.00')
  })

  it('老数据缺 logical_name ⇒ 退回 operation 原文（不空白）；position 为空 ⇒ 只显示逻辑名', () => {
    render(
      <PieceworkTable
        summary={{
          total: 96,
          per_worker: {},
          per_operation: [
            // 老数据 / 商家自建工序：无 logical_name ⇒ 退回 operation 原文
            { operation: '定型-布', amount: 60 },
            // 部位无关工序（外帘装袋）：position 空 ⇒ 只显示逻辑名，不拼「· 」
            { operation: '外帘装袋', logical_name: '外帘装袋', position: null, amount: 36 },
          ],
        }}
      />,
    )

    expect(within(screen.getByTestId('piecework-operation-0')).getByText('定型-布')).toBeInTheDocument()
    const fallback = screen.getByTestId('piecework-operation-1')
    expect(within(fallback).getByText('外帘装袋')).toBeInTheDocument()
    expect(fallback.textContent).not.toContain('·')
  })

  it('data-testid 与 key 里不得出现变体名（key 不进 DOM ⇒ 读源码判）', () => {
    const { container } = render(<PieceworkTable summary={summaryWithLogicalName} />)

    const testids = Array.from(container.querySelectorAll('[data-testid]')).map(
      (el) => el.getAttribute('data-testid') ?? '',
    )
    expect(testids.length).toBeGreaterThan(0)
    for (const id of testids) {
      expect(id).not.toContain('精裁-布')
      expect(id).not.toContain('韩褶-布')
    }

    // key 只出现在源码里（不进 DOM）：不得用工人端快照名 `item.operation`
    const code = COMPONENT_SRC.split('\n')
      .filter((line) => !line.trimStart().startsWith('//'))
      .join('\n')
    expect(COMPONENT_SRC).toContain("from '@/lib/operation-display'")
    expect(code).not.toMatch(/item\.operation/)
  })
})

/**
 * 未定价显式可见（issue #4696，P1）—— 红证② 的前端半边。
 *
 * 缺陷原形：未定价的报工在**算钱的地方**被静默折成 0 元，界面只在**读面徽标**上说「未定价」
 * ⇒ 工人白干且无人知道，且「没定价」与「价本来就是 0」不可区分。
 */
describe('PieceworkTable 未定价显式可见（issue #4696）', () => {
  const onlyUnpriced: PieceworkSummary = {
    total: 0,
    per_worker: {},
    per_operation: [],
    unpriced: {
      qty: 5,
      operations: [{ operation: '配料', logical_name: '配料', position: '布料', qty: 5 }],
      hint: '以下工序未定价',
    },
  }

  it('🔴 只有未定价报工 ⇒ **不得**渲染「暂无计件数据」，必须显示未定价 + 定价入口', () => {
    render(<PieceworkTable summary={onlyUnpriced} />)

    expect(
      screen.queryByTestId('piecework-empty'),
      '未定价的单子里 per_operation/per_worker/total 全空 —— 只看它们会把「干了活没定价」藏起来',
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('配料')
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('未定价')
    expect(screen.getByTestId('piecework-unpriced-detail')).toHaveTextContent('5')
    expect(screen.getByTestId('piecework-unpriced-pricing-link')).toHaveAttribute(
      'href',
      '/production/routings',
    )
  })

  it('反向护栏：**价 0** 的工序照常渲染 ¥0.00 且**不出现**未定价块（两态可区分）', () => {
    render(
      <PieceworkTable
        summary={{
          total: 0,
          per_worker: {},
          per_operation: [{ operation: '配料', amount: 0 }],
          unpriced: { qty: 0, operations: [] },
        }}
      />,
    )

    expect(screen.queryByTestId('piecework-unpriced')).not.toBeInTheDocument()
    expect(screen.getByTestId('piecework-operation-amount')).toHaveTextContent('¥0.00')
  })

  it('零条未定价 ⇒ 不制造噪音（未定价块不渲染）', () => {
    render(<PieceworkTable summary={summary} />)
    expect(screen.queryByTestId('piecework-unpriced')).not.toBeInTheDocument()
  })
})
