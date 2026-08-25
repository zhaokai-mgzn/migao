// case_ids: DA-005
import { describe, it, expect } from 'vitest'
import {
  orderStatusChip,
  afterSalesStatusChip,
  chipToneClasses,
  type ChipTone,
} from '@/lib/status-chip'

describe('status-chip — 订单/售后状态语义色映射', () => {
  it('订单状态映射为语义色 chips（label + tone）', () => {
    expect(orderStatusChip('pending_payment')).toEqual({ label: '待付款', tone: 'warning' })
    expect(orderStatusChip('pending_shipment')).toEqual({ label: '待发货', tone: 'info' })
    expect(orderStatusChip('shipped')).toEqual({ label: '已发货', tone: 'info' })
    expect(orderStatusChip('completed')).toEqual({ label: '已完成', tone: 'success' })
    expect(orderStatusChip('closed')).toEqual({ label: '已关闭', tone: 'neutral' })
    expect(orderStatusChip('refund')).toEqual({ label: '退款/售后', tone: 'error' })
  })

  it('售后状态映射为语义色 chips（label + tone）', () => {
    expect(afterSalesStatusChip('pending')).toEqual({ label: '待处理', tone: 'warning' })
    expect(afterSalesStatusChip('processing')).toEqual({ label: '处理中', tone: 'info' })
    expect(afterSalesStatusChip('resolved')).toEqual({ label: '已完成', tone: 'success' })
    expect(afterSalesStatusChip('rejected')).toEqual({ label: '已拒绝', tone: 'error' })
    expect(afterSalesStatusChip('closed')).toEqual({ label: '已关闭', tone: 'neutral' })
  })

  it('未知/空状态回退为 neutral，且不出现 "-" 占位', () => {
    for (const s of [undefined, null, '', 'unknown_status']) {
      const chip = orderStatusChip(s as string | null | undefined)
      expect(chip.tone).toBe('neutral')
      expect(chip.label).toBeTruthy()
      expect(chip.label).not.toBe('-')
      expect(chip.label).not.toBe('--')
    }
  })

  it('语义色 class 不使用默认蓝 #3b82f6 / blue 系', () => {
    const tones = Object.keys(chipToneClasses) as ChipTone[]
    expect(tones.length).toBeGreaterThanOrEqual(5)
    for (const tone of tones) {
      const cls = chipToneClasses[tone]
      expect(cls).toBeTruthy()
      expect(cls).not.toMatch(/bg-blue-|text-blue-|#3b82f6|#2563eb/i)
    }
  })
})
