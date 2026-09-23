// case_ids: PR-102
/**
 * BatchStockCard（B 端**移动**会话卡）— issue #5188
 *
 * `batch_stock_query` 声明 `product:list`（仅 B 端可达）⇒ 按 persona 推导，
 * 卡型 `batch_stock` 的渲染端 = B 端移动（本端）+ B 端桌面（admin-web）；
 * C 端 `mini-app` 有意不加分支（永不命中的死 UI，反向契约判据专门拦这种）。
 *
 * 口径纪律：米数/金额/占比**原样渲染服务端值**；档位文案取服务端 `label`；
 * `null` ⇒ 「无数据」（不回落 0）。
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import BatchStockCard from '../src/components/cards/BatchStockCard'
import MessageBubble from '../src/components/chat/MessageBubble'
import type { Message } from '../src/types'

const BATCHES = {
  action: 'batches',
  matched_count: 2,
  truncated: false,
  filters: { nearly_used_up: true, nearly_used_up_threshold_meters: '0.2' },
  batches: [
    { batchNo: 'PC-20260901-0001', dyeLot: 'A12', remainingMeters: 0.2 },
    { batchNo: 'PC-20260902-0002', dyeLot: 'A13', remainingMeters: -0.3 },
  ],
}

const BOARD = {
  action: 'saving_board',
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [
    {
      cohort: 'purchase', cohortLabel: '切换后（采购入库）', batchCount: 7, le0_2Count: 3,
      le0_2Share: 0.4286, savedMeters: 24.68, savedAmount: 113.45, lineCount: 2,
      unknownCostLines: 0, buckets: [{ key: 'le_0_2', label: '档位甲', batchCount: 3, share: 0.4286 }],
    },
    {
      cohort: 'opening', cohortLabel: '存量导入（切换前历史包袱）', batchCount: 0,
      le0_2Share: null, savedMeters: null, savedAmount: null, lineCount: 0, buckets: [],
    },
  ],
  total: { savedMeters: 24.68, savedAmount: 113.45 },
}

describe('BatchStockCard（B 端移动会话卡）', () => {
  it('批次余量：渲染批次号 / 缸号 / 服务端余量（含负余量）', () => {
    render(<BatchStockCard data={BATCHES} />)
    expect(screen.getByText(/PC-20260901-0001/)).toBeTruthy()
    expect(screen.getByText(/缸号 A13/)).toBeTruthy()
    expect(screen.getByText('剩 0.2 米')).toBeTruthy()
    expect(screen.getByText('剩 -0.3 米')).toBeTruthy()
  })

  it('省料度量：原样渲染服务端值（重算会漂 ⇒ 24.67 不许出现）+ 档位文案取服务端 label', () => {
    render(<BatchStockCard data={BOARD} />)
    expect(screen.getByText('24.68 米 / 113.45 元')).toBeTruthy()
    expect(screen.queryByText(/24\.67/)).toBeNull()
    expect(screen.getByText(/档位甲/)).toBeTruthy()
    expect(screen.getByText('存量导入（切换前历史包袱）')).toBeTruthy()
    // 存量导入组读不出 ⇒ 「无数据」，不是 0
    expect(screen.getAllByText('无数据').length).toBeGreaterThan(0)
    expect(screen.queryByText('0.0%')).toBeNull()
  })

  it('经 MessageBubble 的 batch_stock 分支渲染（不落「暂不支持预览」占位）', () => {
    const msg = {
      id: 'm1',
      role: 'assistant',
      content: '批次余量：',
      createdAt: new Date().toISOString(),
      cards: [{ type: 'batch_stock', data: BATCHES }],
    } as unknown as Message
    render(<MessageBubble message={msg} />)
    expect(screen.getByText(/PC-20260901-0001/)).toBeTruthy()
    expect(screen.queryByText('📎 消息内容暂不支持预览')).toBeNull()
  })

  it('空数据不冒充 0：空批次列表显示「无数据」', () => {
    render(<BatchStockCard data={{ action: 'batches', batches: [], matched_count: 0 }} />)
    expect(screen.getAllByText('无数据').length).toBeGreaterThan(0)
  })
})
