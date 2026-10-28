/**
 * 智能派单 / 池化派单的**纯前端薄助手**（issue #5177）。
 *
 * 🔴 本文件**只做两件事**：① 拼请求体；② 把服务端给的数字**格式化成文案**。
 *
 * 它**不做**（这是本仓库明令的口径红线，见 `migao-dev-flow` §15 与冻结契约）：
 * - **不重排**：`urgentLines` / `groups[].lines` 的顺序是**服务端唯一口径**
 *   （到货日升序 null 最后 → waitHours 降序 → waitingSince 升序 → orderId 升序）。
 *   在浏览器里再写一份比较器 = 第二份会漂的口径；「加急优先」是**结构性**的
 *   （整段 `urgentLines` 渲染在 `groups` 之前），不是排序键。
 * - **不算米数**：`savedMeters` / `poolingGainMeters` / `perOrderPlannedMeters` 全部原样渲染
 *   服务端值 —— 要求是「口径必须与落账逐值相等」，前端重算就是那类「两套语义」的 bug。
 */
import type { PoolBoard, PoolDispatchRequest, PoolGroup, PoolLine, PoolPreview } from '@/types'

/**
 * 批次指派规则（逐行不指定批次 ⇒ 由服务端按这条规则补位 = **算法替商家挑批次**）。
 *
 * 真值源 = 服务端 `ProcessingOrderService.AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE`（`"fifo"`）——
 * 前端只是把自动路径既有的缺省规则显式说出来，**不在这里另立一套策略**。
 */
export const POOL_ASSIGNMENT_RULE = 'fifo'

/**
 * 池化派单请求体（`/preview` 与 `/dispatch` **同体**，冻结契约逐字给出四个键）。
 *
 * `pooled: true` = 成批池化派单；**加急插队 = 同一个端点 + 单订单 + `pooled: false`**（一个动作）。
 *
 * 🔴 **逐行必须带 `{orderId, itemId}` 的指派**（issue #6408）：服务端
 * `ProcessingOrderService::buildDesignations` 在指派为空时**直接返回空** ⇒ 没有指派就没有
 * `Designation` ⇒ 池级排料求解器（`StockBatchConsumptionService::plan`）**一次都不跑** ⇒
 * 不落 `stock_batch_consumptions`、不排料、页面「预计节省」恒 `0.00`。实测（300 单四臂对照，云 dev）：
 * 空指派臂消耗行 **0** 行 / Σsaved **0**；逐行指派 + `fifo` 臂 75 行 / **45 米**。
 * ⇒ `batches: []` 是**缺陷形态**、不是「缺省」；`case_ids: PR-081` 的类级自证把它钉住。
 */
export function buildPoolRequest(
  lines: Pick<PoolLine, 'orderId' | 'itemId'>[],
  pooled: boolean,
  /**
   * 外发承接方（issue #7723）：`null`/缺省 = 本厂自做。
   *
   * 🔴 **留空就不带键**（不是带 `null`）—— 请求体上能核验「没选承接方 ⇒ 与改造前逐字相同」
   * （与 `batches` 的既有口径同款）。
   */
  consignee?: { processorSupplierId?: string | null; expectedDeliveryDate?: string | null },
): PoolDispatchRequest {
  return {
    // 🔴 `orderIds` 是**订单集合**，而 `lines` 是**池行**（一张多套订单 = N 行、同一个 `orderId`）
    // ⇒ 必须去重（issue #7904）。服务端是「**一单一加工单**」：`generatePooled` / `preview` 都按
    // `orderIds` 逐份处理，重复单号 = 同一张单被当成 N 张各派一次。
    // 实测后果（用户 2026-10-27 现场「服务器错误」）：第 2 份 insert 撞 `uk_processing_orders_active`，
    // 而 PG 事务已被这条失败语句中止 ⇒ 第 3 份抛 25P02（不是 `DuplicateKeyException`）⇒ 逸出兜底 ⇒ 500；
    // 只有 2 套时更糟：接口 200 + 「合并派单完成：1 单」，整批在提交时静默回滚（一张加工单都没生成）。
    // ⚠️ 去重**只**作用于 `orderIds`：`batches` 仍**逐池行**（少一条 = 那一套不参与排料，`saved` 少算）。
    orderIds: [...new Set(lines.map((l) => l.orderId))],
    batches: lines.map((l) => ({ orderId: l.orderId, itemId: l.itemId })),
    assignmentRule: POOL_ASSIGNMENT_RULE,
    pooled,
    ...(consignee?.processorSupplierId ? { processorSupplierId: consignee.processorSupplierId } : {}),
    ...(consignee?.expectedDeliveryDate ? { expectedDeliveryDate: consignee.expectedDeliveryDate } : {}),
  }
}

/**
 * **成批候选**的唯一取值口径：`groups[].lines`。
 *
 * 🔴 加急行在 `urgentLines`（插队区），**不是**成批候选 —— 把两处合并
 * （「让加急单照旧进池」这个缺陷形态）会让 `pool-groups-section` 里出现加急单号，
 * 而商家一旦勾上它就必然拿到 422。红证见
 * `frontend/admin-web/tests/unit/pages/production-pool-urgent.test.tsx` 的注入式正控。
 */
export function batchGroups(board: PoolBoard | null | undefined): PoolGroup[] {
  return board?.groups ?? []
}

/** 成批候选的订单 id（「加急单不进池」的机器面读数：成批候选 ∩ 加急单 = 空集） */
export function batchCandidateOrderIds(board: PoolBoard | null | undefined): string[] {
  return batchGroups(board).flatMap((g) => (g.lines ?? []).map((l) => l.orderId))
}

/**
 * **「不参与合并、逐单立即派」**的全部行（加急 + 外发）—— 唯一取值口径（issue #7943）。
 *
 * 🔴 顺序 = 两个服务端数组的**拼接序**（加急段在前、外发段在后）：两段各自已按服务端
 * `POOL_LINE_ORDER` 排好 ⇒ 前端**不重排**（「加急优先」体现在这一份顺序里，而不是渲染位置）。
 * 🔴 两段**互斥**：服务端先判 `urgent`、再 `else if (outsourced)`
 * （`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java` 的看板构造）
 * ⇒ 同一行不会出现两次，React key（`orderId-itemId`）不会撞。
 */
export function singleDispatchLines(board: PoolBoard | null | undefined): PoolLine[] {
  return [...(board?.urgentLines ?? []), ...(board?.outsourcedLines ?? [])]
}

/**
 * **一张订单在逐单立即派表里的全部行** —— 「点一行派单」的批次指派取值口径（issue #7968）。
 *
 * 🔴 「立即派单」是**订单级动作**（服务端「一单一加工单」）：请求体的 `orderIds` 是整单，
 * 但 `batches` 是**逐行**的批次指派（`ProcessingOrderService::buildDesignations` 只按 `batches`
 * 里出现的行装配 `Designation`；`stampAssignedBatches` 也只给这些行写快照 `batchNo`）。
 * ⇒ 只带被点的那一行 = **整单派出、只有那一套领料**（用户 2026-10-28 现场：
 * 「一个加急订单有多套成品帘时……只有被选中的那套成品帘指定了批次号，应该要整单都指派」）。
 *
 * ⚠️ 「点哪一行」只决定**派哪张单**，不决定**哪几套领批次** ⇒ 同单的任意一行点下去，请求体都相同。
 * 订单在看板上不存在（已被刷掉 / 刚被派走）⇒ 回空数组，由调用方兜底（不要在这里造行）。
 */
export function singleDispatchLinesOfOrder(
  board: PoolBoard | null | undefined,
  orderId: string,
): PoolLine[] {
  return singleDispatchLines(board).filter((line) => line.orderId === orderId)
}

/**
 * 派单**失败面**是否必须上屏（唯一口径）。
 *
 * 被拒绝的每一次都必须留下**看得见**的文案（PR-080 判据 3「整批显式拒绝，不静默少派」）：
 * 空白 / 缺省的文案**不算上屏** —— 那正是「静默吞掉失败」这一缺陷形态的判据。
 * 红证 = 把它改成 `() => false` ⇒ `production-pool-urgent.test.tsx` 的
 * `pool-dispatch-error` 断言当场红。
 */
export function mustSurfaceDispatchError(message: string | null | undefined): boolean {
  return typeof message === 'string' && message.trim() !== ''
}

/** 等待时长的可读文案（入参 = 服务端 `waitHours`，**不重算**） */
export function formatWaitHours(waitHours: number): string {
  if (!Number.isFinite(waitHours) || waitHours < 0) return '-'
  if (waitHours < 24) return `${trimNumber(waitHours)} 小时`
  const days = Math.floor(waitHours / 24)
  const hours = Math.round(waitHours - days * 24)
  return hours > 0 ? `${days} 天 ${hours} 小时` : `${days} 天`
}

/**
 * 到货日剩余天数的可读文案（入参 = 服务端 `deliveryDaysLeft`，**不重算**）。
 * `null` = 未指定（不猜、不写死默认）。
 */
export function formatDeliveryDaysLeft(daysLeft: number | null | undefined): string {
  if (daysLeft === null || daysLeft === undefined) return '未指定'
  if (daysLeft < 0) return `已逾期 ${Math.abs(daysLeft)} 天`
  if (daysLeft === 0) return '今天到期'
  return `剩 ${daysLeft} 天`
}

/** 到货日（`YYYY-MM-DD`）；`null` = 未指定 */
export function formatRequiredDeliveryDate(date: string | null | undefined): string {
  return date ? date : '未指定'
}

/** 米数（服务端 JSON number，原样渲染、只做展示取整） */
export function formatMeters(meters: number | null | undefined, digits = 2): string {
  if (meters === null || meters === undefined || !Number.isFinite(meters)) return '-'
  return meters.toFixed(digits)
}

/**
 * 成批预览的五行摘要（`label` 与 `value` 一一对应服务端键，**不派生**）。
 *
 * 🔴 **全部五个米数都是服务端聚合**（`ProductionPoolViews.Preview` 里五个字段都是 `BigDecimal`）——
 * `perOrderPlannedMeters` 是**一个数**（= **逐单派**的应领**合计**，对照读数），
 * **不是** orderId → 米数 的映射；预览 API **没有**逐单明细。
 *
 * 🔴 语义上必须分开的两件事：
 * - `savedMeters` = **预计节省** = `formulaMeters − pooledPlannedMeters`（与落账 `Σ saved_meters` 逐值相等）；
 * - `poolingGainMeters` = **池化新增收益** = `perOrderPlannedMeters − pooledPlannedMeters`。
 *   把两者合并成一句「节省 X 米」会让商家以为是池化带来的，其实一部分是 #5158
 *   「单订单内并排」本来就有的旧收益。
 *
 * ⚠️ 两者都是**服务端算好的**：前端在这里相减 = 第二份会漂的口径（本仓库明令禁止）。
 */
export function previewSummaryRows(preview: PoolPreview): { label: string; value: string }[] {
  return [
    { label: '逐单公式米数（对照基线）', value: formatMeters(preview.formulaMeters) },
    { label: '合并后预计领料米数', value: formatMeters(preview.pooledPlannedMeters) },
    { label: '预计节省', value: formatMeters(preview.savedMeters) },
    { label: '对照·逐单派应领', value: formatMeters(preview.perOrderPlannedMeters) },
    { label: '合并新增收益', value: formatMeters(preview.poolingGainMeters) },
  ]
}

/** 去掉 `12.00` → `12`、`12.50` → `12.5`（纯展示，不改数值） */
function trimNumber(value: number): string {
  return String(Math.round(value * 10) / 10)
}
