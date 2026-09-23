// case_ids: PR-100, PR-101
/**
 * 批次账 / 省料卡（B 端桌面会话内）— issue #5188
 *
 * ## 为什么 B 端桌面必须有这一端
 *
 * `batch_stock_query` 绑在米宝的 Skill（`general` / `product`）上，且声明 `product:list`
 * ⇒ **只有 B 端可达**。契约不变式「后端能发到这一端的卡型 ⊆ 这一端能渲染的卡型」
 * （`backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）**实测红证**：
 * 只加后端 `_detect_card_type` 映射、不加本端分支时报
 * `B端桌面 admin-web ToolResultCard 缺 ['batch_stock']`。
 *
 * ## 本文件钉的口径纪律（前端**不算数**）
 *
 * - 米数/金额/占比**原样渲染服务端值**：夹具刻意取「重算会漂」的账
 *   （`savedMeters = 24.68` 而 `formulaMeters − plannedMeters = 24.67`）⇒ 前端若顺手求和/求差，
 *   `24.68 米` 这条断言当场红。
 * - 档位文案（如「≤0.2 米」）**必须**来自服务端 `buckets[].label` ⇒ 夹具换成任意标签，
 *   页面必须跟着变（写死就红）。
 * - 空数据 ⇒ 「无数据」，**不得**回 `0`。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ToolResultCard from '@/components/chat/ToolResultCard'
import BatchStockCard from '@/components/chat/BatchStockCard'

/** 批次余量载荷（服务端 `BatchRemaining` 逐字段） */
const BATCHES = {
  action: 'batches',
  batch_count: 2,
  matched_count: 2,
  truncated: false,
  filters: { nearly_used_up: true, nearly_used_up_threshold_meters: '0.2' },
  batches: [
    { batchNo: 'PC-20260901-0001', dyeLot: 'A12', remainingMeters: 0.2 },
    { batchNo: 'PC-20260902-0002', dyeLot: 'A13', remainingMeters: -0.3 },
  ],
}

/** 剩余量分布载荷（档位标签**来自服务端**，故意用非默认文案证明没写死） */
const DISTRIBUTION = {
  action: 'distribution',
  totalBatches: 9,
  buckets: [
    { key: 'le_0_2', label: '档位甲', batchCount: 3, share: 0.3333 },
    { key: 'b0_2_0_5', label: '档位乙', batchCount: 2, share: 0.2222 },
    { key: 'b0_5_1', label: '档位丙', batchCount: 2, share: 0.2222 },
    { key: 'gt_1', label: '档位丁', batchCount: 2, share: 0.2222 },
  ],
}

/** 省料看板载荷：`24.68` 是服务端读面值；朴素重算（40.00 − 15.33）会得 24.67 */
const BOARD = {
  action: 'saving_board',
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [
    {
      cohort: 'purchase', cohortLabel: '切换后（采购入库）', opening: false,
      batchCount: 7, le0_2Count: 3, le0_2Share: 0.4286, remainingMeters: 4.8,
      savedMeters: 24.68, savedAmount: 113.45, lineCount: 2, unknownCostLines: 1,
      buckets: [{ key: 'le_0_2', label: '档位甲', batchCount: 3, share: 0.4286 }],
    },
    {
      cohort: 'opening', cohortLabel: '存量导入（切换前历史包袱）', opening: true,
      batchCount: 2, le0_2Count: 0, le0_2Share: null, remainingMeters: null,
      savedMeters: null, savedAmount: null, lineCount: 0, unknownCostLines: 0, buckets: [],
    },
  ],
  total: { savedMeters: 24.68, savedAmount: 113.45, le0_2Share: 0.3333, batchCount: 9, lineCount: 2 },
}

describe('BatchStockCard（B 端桌面会话卡）', () => {
  it('经 ToolResultCard 的 batch_stock 分支渲染（接线，不落「暂不支持预览」占位）', () => {
    render(<ToolResultCard card={{ type: 'batch_stock', data: BOARD }} />)
    expect(screen.getByTestId('batch-stock-card')).toBeInTheDocument()
    expect(screen.queryByTestId('tool-result-card-unsupported')).not.toBeInTheDocument()
  })

  it('批次余量：逐行渲染服务端余量值（含负余量），阈值取工具回的口径', () => {
    render(<BatchStockCard data={BATCHES} />)
    expect(screen.getByText(/PC-20260901-0001/)).toBeInTheDocument()
    expect(screen.getByText(/缸号 A13/)).toBeInTheDocument()
    expect(screen.getByText('剩 0.2 米')).toBeInTheDocument()
    expect(screen.getByText('剩 -0.3 米')).toBeInTheDocument()
    expect(screen.getByText(/快用尽（剩余 ≤ 0.2 米）/)).toBeInTheDocument()
  })

  it('剩余量分布：档位文案取自服务端 label（写死就红），计数与占比原样渲染', () => {
    render(<BatchStockCard data={DISTRIBUTION} />)
    for (const label of ['档位甲', '档位乙', '档位丙', '档位丁']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('3 个 · 33.3%')).toBeInTheDocument()
    // 服务端没给过的档位文案不得出现在页面上
    expect(screen.queryByText('≤0.2 米')).not.toBeInTheDocument()
  })

  it('省料度量：原样渲染服务端 savedMeters（重算会漂 ⇒ 24.67 不许出现）', () => {
    render(<BatchStockCard data={BOARD} />)
    expect(screen.getByText('24.68 米 / 113.45 元')).toBeInTheDocument()
    expect(screen.queryByText(/24\.67/)).not.toBeInTheDocument()
    expect(screen.getByTestId('batch-stock-total')).toHaveTextContent('24.68 米')
    // 来源组标签取自服务端（存量单列）
    expect(screen.getByText('存量导入（切换前历史包袱）')).toBeInTheDocument()
    // 未记均价的行数显式说明（否则「读不出」会被读成「只省了这么点」）
    expect(screen.getByText(/其中 1 行没有均价/)).toBeInTheDocument()
  })

  it('空数据不冒充 0：null 占比渲染「无数据」，不得出现 0%', () => {
    render(<BatchStockCard data={BOARD} />)
    // 存量导入组：savedMeters / le0_2Share 全 null
    expect(screen.getAllByText('无数据').length).toBeGreaterThan(0)
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
  })

  it('空批次列表 / 空分布：显示「无数据」而不是空白或 0', () => {
    render(<BatchStockCard data={{ action: 'batches', batches: [], matched_count: 0 }} />)
    expect(screen.getByTestId('batch-stock-empty')).toHaveTextContent('无数据')

    render(
      <BatchStockCard
        data={{ action: 'distribution', totalBatches: 0, buckets: [] }}
      />,
    )
    expect(screen.getAllByTestId('batch-stock-empty').length).toBeGreaterThan(0)
  })

  it('省料趋势：采购 / 消耗 / 存量导入三条腿都用服务端值，缺值显「无数据」', () => {
    render(
      <BatchStockCard
        data={{
          action: 'saving_trend',
          granularity: 'month',
          purchasedTotalMeters: 120,
          consumedTotalMeters: 100,
          openingTotalMeters: null,
        }}
      />,
    )
    expect(screen.getByText('120 米')).toBeInTheDocument()
    expect(screen.getByText('100 米')).toBeInTheDocument()
    expect(screen.getByText('无数据')).toBeInTheDocument()
  })
})
