// case_ids: UI-002
import { describe, it, expect } from 'vitest'
import {
  chipToneClasses,
  orderStatusChip,
  afterSalesStatusChip,
  orderStatusChipFor,
  afterSalesStatusChipFor,
} from '@/lib/status-chip'

describe('status-chip 语义色 chips', () => {
  it('chipToneClasses 将语义 tone 映射到织物质感 token 类', () => {
    expect(chipToneClasses.warning).toContain('bg-amber-50')
    expect(chipToneClasses.info).toContain('bg-primary-50')
    expect(chipToneClasses.success).toContain('bg-emerald-50')
    expect(chipToneClasses.error).toContain('bg-red-50')
    expect(chipToneClasses.neutral).toContain('bg-neutral-100')
  })

  it('chipToneClasses 不含旧默认蓝/灰/绿', () => {
    for (const cls of Object.values(chipToneClasses)) {
      expect(cls).not.toContain('bg-blue-')
      expect(cls).not.toContain('bg-indigo-')
      expect(cls).not.toContain('bg-green-')
      expect(cls).not.toContain('bg-gray-')
    }
  })

  it('orderStatusChip 六种订单状态映射语义 tone 与中文 label', () => {
    expect(orderStatusChip.pending_payment).toEqual({ tone: 'warning', label: '待付款' })
    expect(orderStatusChip.pending_shipment).toEqual({ tone: 'info', label: '待发货' })
    expect(orderStatusChip.shipped).toEqual({ tone: 'info', label: '已发货' })
    expect(orderStatusChip.completed).toEqual({ tone: 'success', label: '已完成' })
    expect(orderStatusChip.closed).toEqual({ tone: 'neutral', label: '已关闭' })
    expect(orderStatusChip.refund).toEqual({ tone: 'error', label: '退款/售后' })
  })

  it('afterSalesStatusChip 五种售后状态映射语义 tone 与中文 label', () => {
    expect(afterSalesStatusChip.pending).toEqual({ tone: 'warning', label: '待处理' })
    expect(afterSalesStatusChip.processing).toEqual({ tone: 'info', label: '处理中' })
    expect(afterSalesStatusChip.resolved).toEqual({ tone: 'success', label: '已完成' })
    expect(afterSalesStatusChip.rejected).toEqual({ tone: 'error', label: '已拒绝' })
    expect(afterSalesStatusChip.closed).toEqual({ tone: 'neutral', label: '已关闭' })
  })

  it('orderStatusChipFor 未知/空状态回退 neutral 且 label=暂无数据', () => {
    expect(orderStatusChipFor('unknown')).toEqual({ tone: 'neutral', label: '暂无数据' })
    expect(orderStatusChipFor(undefined)).toEqual({ tone: 'neutral', label: '暂无数据' })
    expect(orderStatusChipFor(null)).toEqual({ tone: 'neutral', label: '暂无数据' })
  })

  it('afterSalesStatusChipFor 未知/空状态回退 neutral 且 label=暂无数据', () => {
    expect(afterSalesStatusChipFor('unknown')).toEqual({ tone: 'neutral', label: '暂无数据' })
    expect(afterSalesStatusChipFor('')).toEqual({ tone: 'neutral', label: '暂无数据' })
    expect(afterSalesStatusChipFor(null)).toEqual({ tone: 'neutral', label: '暂无数据' })
  })
})
