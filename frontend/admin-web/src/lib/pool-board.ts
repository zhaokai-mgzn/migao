/**
 * 池看板 / 池化派单的**纯前端薄助手**（issue #5177）。
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
import type { PoolDispatchRequest, PoolPreview } from '@/types'

/**
 * 池化派单请求体（`/preview` 与 `/dispatch` **同体**，冻结契约逐字给出四个键）。
 *
 * `pooled: true` = 成批池化派单；**加急插队 = 同一个端点 + 单订单 + `pooled: false`**（一个动作）。
 */
export function buildPoolRequest(orderIds: string[], pooled: boolean): PoolDispatchRequest {
  return { orderIds, batches: [], assignmentRule: null, pooled }
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
    { label: '预计领料米数（池化后）', value: formatMeters(preview.pooledPlannedMeters) },
    { label: '预计节省', value: formatMeters(preview.savedMeters) },
    { label: '对照·逐单派应领', value: formatMeters(preview.perOrderPlannedMeters) },
    { label: '池化新增收益', value: formatMeters(preview.poolingGainMeters) },
  ]
}

/** 去掉 `12.00` → `12`、`12.50` → `12.5`（纯展示，不改数值） */
function trimNumber(value: number): string {
  return String(Math.round(value * 10) / 10)
}
