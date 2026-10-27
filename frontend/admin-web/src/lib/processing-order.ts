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

/** 订单详情读面键 `work_order_kind` 的形状（缺键 / `null` = **无需要报工的作业**） */
export type WorkOrderKind = 'processing' | 'outbound' | null

/**
 * **纸面标题**（issue #7891）：成品帘 ⇒「加工单」；面料单 ⇒「面料单」。
 *
 * 用户 2026-10-27 逐字「面料单就叫面料单，不要叫裁剪单」（同批裁定还包括「把销售单左上角的
 * 扫码报工二维码迁移到加工单打印上」「面料单不能打印水洗唛，应该打印加工单」）——
 * 面料单只做**裁剪**一道简单工序，但纸名不能叫「裁剪单」：裁剪只是其中一道工序，纸是整张作业单。
 *
 * 🔴 这是**纸面**用名，**不是**屏幕上的类型名：屏上仍是 {@link ORDER_KIND_LABELS}
 * （「加工单」/「出库作业单」）—— 屏幕要说出「卖布单的裁剪打包作业 ≠ 外发加工」这层业务语义，
 * 纸面只印两型名。**两者不得互相覆盖**（改一个就把另一个的意思改掉了）。
 */
export const WORK_ORDER_DOC_TITLES: Record<'processing' | 'outbound', string> = {
  processing: '加工单',
  outbound: '面料单',
}

/**
 * 纸面标题取值（issue #7891）：缺键 / `null` ⇒「加工单」—— 与 {@link orderKindOf} 的
 * 存量单口径**同一把尺**（存量行不带 `order_kind`，把它印成「面料单」= 给客户一张名字写错的纸）。
 */
export function workOrderDocTitleOf(kind?: WorkOrderKind): string {
  return WORK_ORDER_DOC_TITLES[kind === 'outbound' ? 'outbound' : 'processing']
}

/**
 * 读面键 `work_order_kind`（订单详情面，issue #7079 第 5 包）→ 两型；`null` = 无需要报工的作业。
 *
 * 🔴 **键名口径（issue #7319，实测断线）**：后端下发的是 **snake_case 冻结键**
 * `work_order_kind`（`OrderDetailResponse` 的 `@JsonProperty("work_order_kind")`，
 * 登记面 = `tests/unit_ci_workflows/read_face_json_key_ledger.json`）；全局 Jackson 没有
 * SNAKE_CASE 策略、前端也没有 snake→camel 响应变换 ⇒ 本函数必须读 `order.work_order_kind`。
 * 改前读的是 camelCase 键 `workOrderKind` —— 线上报文里没有这把键 ⇒ 恒 `null`
 * ⇒ 生成作业单入口对**所有**订单都不出现，而全部单测用 camelCase 夹具 ⇒ 一直是绿的。
 *
 * 🔴 这是「这单发货前要不要作业」在前端的**唯一**读点：详情页的生成入口、发货页的前置守卫、
 * 详情页的发货入口三处都读它，**不许**再按 `processingItems` 长度（只覆盖「含加工项」那一半）
 * 自己推 —— 卖布单（按米卖布、行上没有加工项）正是被那一侧漏掉的。
 */
export function workOrderKindOf(order: { work_order_kind?: 'processing' | 'outbound' | null }): WorkOrderKind {
  return order.work_order_kind === 'outbound'
    ? 'outbound'
    : order.work_order_kind === 'processing'
      ? 'processing'
      : null
}

/** 读面键 `work_order_kind` 的中文业务名（缺键 ⇒ `''`，调用方据此不渲染） */
export function workOrderKindLabelOf(order: { work_order_kind?: 'processing' | 'outbound' | null }): string {
  const kind = workOrderKindOf(order)
  return kind ? ORDER_KIND_LABELS[kind] : ''
}

/**
 * 「该生成哪一型作业单」的**文案单一真值**（issue #7079 第 5 包）：生成入口的说明 / 按钮 /
 * 发货前的引导句都从这里取，**不新造词**（类型名仍取 {@link ORDER_KIND_LABELS}）。
 *
 * 为什么按型分：卖布单要走**裁剪 → 打包**两道工序（出库作业单，没有加工方 / 交期），
 * 成品帘单走**加工**（加工单）。同一句文案套两型，商家就会在错的单子里找那张纸。
 */
export const WORK_ORDER_NEEDED_COPY: Record<'processing' | 'outbound', {
  /** 生成入口的说明（订单详情「作业单」区块） */
  generateIntro: string
  /** 发货前被拦时的引导句（详情页发货入口 / 发货页阻断页 —— 与后端守卫文案同口径） */
  shipBlocked: string
}> = {
  processing: {
    generateIntro: '该订单含加工项，可生成加工单发给加工方（订单将进入「生产中」）。',
    shipBlocked: '该订单含加工项：先完成加工单的加工报工，再发货',
  },
  outbound: {
    generateIntro: '该订单是卖布单（按米卖布），可生成出库作业单交车间裁剪与打包（订单将进入「生产中」）。',
    shipBlocked: '该订单是卖布单：先完成出库作业单的裁剪与打包报工，再发货',
  },
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

/**
 * 状态 → 可执行动作（与后端 STATUS_TRANSITIONS 对齐；completed/cancelled 为终态）。
 *
 * 🔴 issue #7723（用户 2026-10-25 裁定 A）：`generated` **不再有 `issue`** —— 「发加工」从作业单
 * 上移除，外发（加工厂 + 回厂日）改在**智能派单**录入；作业单由首工序报工自动进「加工中」。
 * `issue` 动作本身保留在 API 里（存量单 / agent 通道），只是不再是新单的必经步骤。
 */
export const PROCESSING_ORDER_ACTIONS: Record<
  ProcessingOrder['status'],
  ProcessingOrderUpdateParams['action'][]
> = {
  generated: ['cancel'],
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
