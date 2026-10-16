import type { ProcessingOrder, ProcessingOrderUpdateParams } from '@/types'
import type { StatusChip } from '@/lib/status-chip'

/**
 * 加工单状态机单一来源（issue #3340）。
 * 与后端 ProcessingOrderService.STATUS_TRANSITIONS / STATUS_LABELS 对齐：
 *   generated → issued → in_processing → completed | cancelled（各活跃态均可取消）。
 * 列表页与订单详情加工单块共用，禁止各自再写一份状态文案/动作映射。
 */

/**
 * 作业单两型的**中文业务名**（issue #7079）—— 唯一真值，页面/组件一律引用它。
 *
 * 上位概念叫「作业单」；实体两型：`processing` = 加工单（成品帘）/ `outbound` = 出库作业单（卖布）。
 * 🔴 机器键（`processing` / `outbound` / `order_kind`）**绝不上屏**，屏上只出现这里的中文名。
 */
export const ORDER_KIND_LABELS: Record<'processing' | 'outbound', string> = {
  processing: '加工单',
  outbound: '出库作业单',
}

/**
 * 服务端读面键 `order_kind` → 两型（**缺键 / `null` = 存量单 ⇒ 按加工单处理**，issue #7079）。
 * 存量行不带该键，把它们读成「出库」会把加工单的加工方/交期整块藏掉。
 */
export function orderKindOf(po: Pick<ProcessingOrder, 'order_kind'>): 'processing' | 'outbound' {
  return po.order_kind === 'outbound' ? 'outbound' : 'processing'
}

/** 作业单类型的中文业务名（屏上只出现它，不出现机器键） */
export function orderKindLabelOf(po: Pick<ProcessingOrder, 'order_kind'>): string {
  return ORDER_KIND_LABELS[orderKindOf(po)]
}

/** 状态文案（与后端 STATUS_LABELS 一致） */
export const PROCESSING_ORDER_STATUS_LABELS: Record<ProcessingOrder['status'], string> = {
  generated: '已生成',
  issued: '已发加工',
  in_processing: '加工中',
  completed: '加工完成',
  cancelled: '已取消',
}

/** 状态 → 语义色 chip（沿用订单/售后 chips 的 chipToneClasses token 体系） */
export function processingOrderStatusChipFor(status?: string | null): StatusChip {
  switch (status) {
    // 待下一步人工动作的两个状态同为警示色
    case 'generated':
    case 'issued':
      return { tone: 'warning', label: PROCESSING_ORDER_STATUS_LABELS[status] }
    // 加工中 = 进行中
    case 'in_processing':
      return { tone: 'info', label: PROCESSING_ORDER_STATUS_LABELS[status] }
    case 'completed':
      return { tone: 'success', label: PROCESSING_ORDER_STATUS_LABELS[status] }
    case 'cancelled':
      return { tone: 'neutral', label: PROCESSING_ORDER_STATUS_LABELS[status] }
    default:
      return { tone: 'neutral', label: '暂无数据' }
  }
}

/** 状态 → 可执行动作（与后端 STATUS_TRANSITIONS 对齐；completed/cancelled 为终态） */
export const PROCESSING_ORDER_ACTIONS: Record<
  ProcessingOrder['status'],
  ProcessingOrderUpdateParams['action'][]
> = {
  generated: ['issue', 'cancel'],
  issued: ['start', 'cancel'],
  in_processing: ['complete', 'cancel'],
  completed: [],
  cancelled: [],
}

/** 动作按钮文案 */
export const PROCESSING_ORDER_ACTION_LABELS: Record<ProcessingOrderUpdateParams['action'], string> = {
  issue: '发加工',
  start: '开始加工',
  complete: '加工完成',
  cancel: '取消加工单',
}

/** 动作成功后的 toast 文案 */
export const PROCESSING_ORDER_ACTION_DONE: Record<ProcessingOrderUpdateParams['action'], string> = {
  issue: '已发加工',
  start: '已开始加工',
  complete: '加工已完成',
  cancel: '加工单已取消',
}
