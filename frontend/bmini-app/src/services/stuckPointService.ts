/**
 * 「卡在哪」卡点面（**只读**，issue #6597）
 *
 * 消费服务端既有端点 `GET /api/admin/production/stuck-points?processing_order_id=…`
 * （`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java#stuckPoints`；
 * 判据本体 `backend/admin-api/src/main/java/com/migao/admin/service/ProductionStuckPointService.java`）。
 *
 * ## 为什么单独一个模块
 *
 * `services/productionService.ts` 的文件归属被并发包占用（issue #6598）⇒ 本面另起一文件，
 * **不改**那一个字节。同时这也让「卡点读面」的消费点只有一处，便于守卫。
 *
 * ## 契约（逐字照服务端 `report(...)` 的响应键）
 *
 * `{mode, threshold_hours, threshold_source, scope, states, stuck_total, stuck[]}`，
 * `stuck[]` 一行 = `{kind, processing_order_id, set_id, set_no, set_index,
 * position{…}, operation{operation_id, logical_name, position, seq, unit, qty, done_qty, state},
 * predecessor{operation_id, logical_name, seq, done_at}, stalled_hours, threshold_hours, threshold_source}`。
 *
 * 🔴 **前端不重算任何读数**：等待时长（`stalled_hours`，起算点 = 上道 `done_at`）、阈值
 * （`threshold_hours`）、阈值来源（`threshold_source`）**一律原样渲染** —— 自己算一份就是第二份
 * 会漂的口径（与 web 面 `frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx`
 * 同纪律）。`threshold_source` 恒为 `default`（S3 全局兜底；`history` = S1 历史中位数，
 * **尚未落码**）⇒ 不得渲染成「业务标准工时」。
 *
 * ## 三态（与「数据」页口径同款）
 *
 * `ok`（含 `stuck: []` = **真的没有卡点**）/ `forbidden`（403 —— 不是「没有卡点」）/ `error`。
 * 把 403 读成空 = 把「看不到」说成「没有」（同 `dashboardService.getProductionTodoOverview`）。
 */
import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'

/** 卡点报表的一行（按套 × 工序） */
export interface StuckPointRow {
  kind?: string | null
  processing_order_id?: string | null
  set_id?: string | null
  set_no?: string | null
  set_index?: number | null
  position?: {
    order_item_id?: string | null
    position_kind?: string | null
    position_name?: string | null
  } | null
  /** 卡住的那道工序（显示名走唯一口径 `operationDisplayName`，不在此自拼） */
  operation?: {
    operation_id?: string | null
    logical_name?: string | null
    position?: string | null
    seq?: number | null
    unit?: string | null
    qty?: number | null
    done_qty?: number | null
    state?: string | null
  } | null
  /** 立即前道（「上道几点完成」）—— 等待时长的**唯一**起算点 */
  predecessor?: {
    operation_id?: string | null
    logical_name?: string | null
    seq?: number | null
    done_at?: string | null
  } | null
  /** 已经等了多久（小时）—— **服务端算的**，前端不重算 */
  stalled_hours?: number | null
  threshold_hours?: number | null
  threshold_source?: string | null
}

export interface StuckPointsReport {
  /** 判定模式：`A`（A 模式只查「没开工」那一种） */
  mode?: string | null
  threshold_hours?: number | null
  /** `default`（S3 兜底）/ `history`（S1 历史中位数，**尚未落码**） */
  threshold_source?: string | null
  scope?: { processing_order_id?: string | null } | null
  states?: { not_started?: number; in_progress?: number; completed?: number } | null
  stuck_total?: number | null
  stuck?: StuckPointRow[]
}

/** 拉取结果三态（403 与「空」必须可区分） */
export type StuckPointsResult =
  | { status: 'ok'; data: StuckPointsReport }
  | { status: 'forbidden' }
  | { status: 'error' }

/** 阈值来源展示（与「数据」页 `thresholdSourceLabel` 同口径：history = 历史中位数，否则系统兜底默认值） */
export function stuckThresholdSourceLabel(source?: string | null): string {
  return source === 'history' ? '历史中位数' : '系统兜底默认值'
}

/** 本单的卡点报表（只读；`processing_order_id` 由调用方给，本模块不猜对象） */
export async function getStuckPoints(processingOrderId: string): Promise<StuckPointsResult> {
  try {
    const res = await get<{ success: boolean; data?: StuckPointsReport }>(
      `/api/admin/production/stuck-points?processing_order_id=${encodeURIComponent(processingOrderId)}`,
      { baseURL: API_BASE_URL },
    )
    if (!res?.success || !res.data) return { status: 'error' }
    return { status: 'ok', data: res.data }
  } catch (e: any) {
    if (e?.statusCode === 403) return { status: 'forbidden' }
    return { status: 'error' }
  }
}

export default { getStuckPoints, stuckThresholdSourceLabel }
