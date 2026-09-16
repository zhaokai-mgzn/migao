// case_ids: PG-005, PG-008, UI-012
// 加工单状态机 lib 单测：状态文案 / 徽章语义色 / 状态→可行动作映射
// （与后端 ProcessingOrderService.STATUS_TRANSITIONS 对齐，PG-005 主链 / PG-008 取消原因）
import { describe, it, expect } from 'vitest'
import {
  PROCESSING_ORDER_STATUS_LABELS,
  PROCESSING_ORDER_ACTIONS,
  PROCESSING_ORDER_ACTION_LABELS,
  PROCESSING_ORDER_ACTION_DONE,
  processingOrderStatusChipFor,
} from '@/lib/processing-order'

describe('lib/processing-order — 加工单状态机单一来源', () => {
  it('状态文案覆盖全部 5 个状态', () => {
    expect(PROCESSING_ORDER_STATUS_LABELS).toEqual({
      generated: '已生成',
      issued: '已发加工',
      in_processing: '加工中',
      completed: '加工完成',
      cancelled: '已取消',
    })
  })

  it('状态 → 语义色：等待动作=warning，加工中=info，完成=success，取消/未知=neutral', () => {
    expect(processingOrderStatusChipFor('generated')).toEqual({ tone: 'warning', label: '已生成' })
    expect(processingOrderStatusChipFor('issued')).toEqual({ tone: 'warning', label: '已发加工' })
    expect(processingOrderStatusChipFor('in_processing')).toEqual({ tone: 'info', label: '加工中' })
    expect(processingOrderStatusChipFor('completed')).toEqual({ tone: 'success', label: '加工完成' })
    expect(processingOrderStatusChipFor('cancelled')).toEqual({ tone: 'neutral', label: '已取消' })
    // 未知/空状态回退 neutral 且 label 恒为「暂无数据」（与订单 chips 同口径）
    expect(processingOrderStatusChipFor('bogus')).toEqual({ tone: 'neutral', label: '暂无数据' })
    expect(processingOrderStatusChipFor(null)).toEqual({ tone: 'neutral', label: '暂无数据' })
    expect(processingOrderStatusChipFor(undefined)).toEqual({ tone: 'neutral', label: '暂无数据' })
  })

  it('状态 → 可行动作与后端 STATUS_TRANSITIONS 对齐（completed/cancelled 为终态）', () => {
    expect(PROCESSING_ORDER_ACTIONS.generated).toEqual(['issue', 'cancel'])
    expect(PROCESSING_ORDER_ACTIONS.issued).toEqual(['start', 'cancel'])
    expect(PROCESSING_ORDER_ACTIONS.in_processing).toEqual(['complete', 'cancel'])
    expect(PROCESSING_ORDER_ACTIONS.completed).toEqual([])
    expect(PROCESSING_ORDER_ACTIONS.cancelled).toEqual([])
  })

  it('动作文案与成功 toast 文案齐全', () => {
    expect(PROCESSING_ORDER_ACTION_LABELS).toEqual({
      issue: '发加工',
      start: '开始加工',
      complete: '加工完成',
      cancel: '取消加工单',
    })
    expect(PROCESSING_ORDER_ACTION_DONE.issue).toBe('已发加工')
    expect(PROCESSING_ORDER_ACTION_DONE.start).toBe('已开始加工')
    expect(PROCESSING_ORDER_ACTION_DONE.complete).toBe('加工已完成')
    expect(PROCESSING_ORDER_ACTION_DONE.cancel).toBe('加工单已取消')
  })
})
