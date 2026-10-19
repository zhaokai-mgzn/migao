// case_ids: PG-005, PG-008, UI-012, UI-115
// 加工单状态机 lib 单测：状态文案 / 徽章语义色 / 状态→可行动作映射
// （与后端 ProcessingOrderService.STATUS_TRANSITIONS 对齐，PG-005 主链 / PG-008 取消原因）
// + issue #7319：订单详情读面 wire 键 `work_order_kind`（snake_case）的**唯一读点**单测
import { describe, it, expect } from 'vitest'
import {
  PROCESSING_ORDER_STATUS_LABELS,
  PROCESSING_ORDER_ACTIONS,
  PROCESSING_ORDER_ACTION_LABELS,
  PROCESSING_ORDER_ACTION_DONE,
  processingOrderStatusChipFor,
  workOrderKindOf,
  workOrderKindLabelOf,
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

/**
 * issue #7319：订单详情读面键是 **snake_case 冻结键** `work_order_kind`
 * （后端 `OrderDetailResponse` 的 `@JsonProperty("work_order_kind")`，
 * 登记面 = tests/unit_ci_workflows/read_face_json_key_ledger.json）。
 *
 * 改前 `workOrderKindOf` 读的是 camelCase `order.workOrderKind` —— 线上报文里没有这个键
 * ⇒ 恒 `null` ⇒ 生成作业单入口对所有订单都不出现（而所有单测用 camelCase 夹具 ⇒ 全绿）。
 * 本组判据钉「读的就是下发的那把键」+ 反向护栏（缺键不猜）。
 */
describe('lib/processing-order — 读面 wire 键 work_order_kind（#7319）', () => {
  it('wire 形状（snake_case）逐值: outbound / processing / 缺键 ⇒ null', () => {
    expect(workOrderKindOf({ work_order_kind: 'outbound' })).toBe('outbound')
    expect(workOrderKindOf({ work_order_kind: 'processing' })).toBe('processing')
    expect(workOrderKindOf({ work_order_kind: null })).toBeNull()
    expect(workOrderKindOf({})).toBeNull()
    // 未知取值不猜（不许默认成 processing）
    expect(workOrderKindOf({ work_order_kind: 'bogus' } as never)).toBeNull()
  })

  it('camelCase 夹具不再被读（防回流：达表绿而线上读不到）', () => {
    expect(workOrderKindOf({ workOrderKind: 'outbound' } as never)).toBeNull()
  })

  it('中文业务名按型分岔，缺键 ⇒ 空串（调用方据此不渲染）', () => {
    expect(workOrderKindLabelOf({ work_order_kind: 'outbound' })).toBe('出库作业单')
    expect(workOrderKindLabelOf({ work_order_kind: 'processing' })).toBe('加工单')
    expect(workOrderKindLabelOf({})).toBe('')
  })
})
