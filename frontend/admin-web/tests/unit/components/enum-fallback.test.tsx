// case_ids: OR-001, UI-048
/**
 * 内部枚举 / 标识**不得上屏**（issue #6664 第 5 条）。
 *
 * 缺陷形态（审计在 4 处命中）：服务端下发的是内部键（`in_transit`、`bulk_cut`、未知 status），
 * 界面把它**原样渲染**成 `信息满足` 的英文键 —— 商家用户读不懂，且一眼看出是给谁做的。
 *
 * 判据形态（**带判别力自证**）：**给定未知枚举值** ⇒ 界面出现**人话兜底**，
 * 且**不出现**那个英文原值。反过来，已知值必须映射成人话（不是一律兜底）。
 */
import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ToolResultCard from '@/components/chat/ToolResultCard'
import { sourceLabel } from '@/components/orders/shipment-source'
import type { CardType } from '@/types'

describe('订单状态 chip：未知值不裸奔（issue #6664 第 5 条）', () => {
  it('① 未知 status ⇒ 人话兜底「状态待确认」，**不出现**英文原值', () => {
    render(
      <ToolResultCard
        card={{ type: 'order' as CardType, data: { order: { id: 'o1', orderNo: 'ORD-1', status: 'weird_new_state' } } }}
      />,
    )
    expect(screen.getByText('状态待确认')).toBeInTheDocument()
    expect(screen.queryByText('weird_new_state')).toBeNull()
    // 已知信息照常显示（兜底没有吃掉卡本体）
    expect(screen.getByText(/ORD-1/)).toBeInTheDocument()
  })

  it('② 已知 status 仍走真映射（兜底不是「一律未知」）', () => {
    render(
      <ToolResultCard
        card={{ type: 'order' as CardType, data: { order: { id: 'o2', orderNo: 'ORD-2', status: 'producing' } } }}
      />,
    )
    expect(screen.getByText('生产中')).toBeInTheDocument()
    expect(screen.queryByText('状态待确认')).toBeNull()
    expect(screen.queryByText('producing')).toBeNull()
  })

  it('③ 订单卡日期也走唯一真值源 DateTimeCell（issue #6664 第 7 条）', () => {
    render(
      <ToolResultCard
        card={{
          type: 'order' as CardType,
          data: { order: { id: 'o3', orderNo: 'ORD-3', status: 'producing', createdAt: '2026-03-04T05:06:00Z' } },
        }}
      />,
    )
    expect(screen.getByText(/^\d{4}-\d{2}-\d{2}$/)).toBeInTheDocument()
    expect(screen.getByText(/^\d{2}:\d{2}$/)).toBeInTheDocument()
  })
})

describe('发货单来源：未知值不裸奔（issue #6664 第 5 条）', () => {
  it('① 未知 source ⇒ 「未知来源」，已知值仍走真映射', () => {
    // 渲染面判据在 `tests/unit/pages/shipments.test.tsx`（那页 mock 齐了）；这里只钉映射口径，
    // 且**同一份映射**来自页面也在用的那个模块（不是本文件另抄一份 —— 抄一份就是第二份会漂的口径）。
    expect(sourceLabel('worker_photo')).toBe('工人拍照')
    expect(sourceLabel('brand_new_source')).toBe('未知来源')
  })
})

