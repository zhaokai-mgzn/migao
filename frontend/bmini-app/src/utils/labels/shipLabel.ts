/**
 * 发货联（整套出库单，issue #7761 / #7786）的**行清单** —— bmini（小程序 / `/b` / 手持终端）侧。
 *
 * ## 与 `/w/` 是**同一份行语义**（issue #8287）
 *
 * 行序 / 文案 / 缺值规则逐条对齐 `frontend/worker-h5/src/shipment.mjs` 的 `buildShipLabelRows`：
 * 单号 → 收货人 → 电话 → 地址 → （帘种 / 安装小区 / 安装位置）→ 物流类型 → 物流公司 → 下单日期 → 套数 → 备注。
 * 判据 = `tests/ship-label-rows-parity.test.ts`：**现取** `/w/` 的实现跑同一组 fixture，逐行比对
 * —— 任一侧改了行序 / 缺值规则 / 日期口径而另一侧没跟 ⇒ 红（不是两份各自绿）。
 *
 * ## 三条来源纪律
 *
 * 1. **值只取服务端下发的行字段**（`GET /api/worker/shipment/orders` 的 `items[]`）；
 * 2. **缺值印 `—`**（不是 0 / 空串 / 「未知」）；可选附注（帘种 / 安装小区 / 安装位置 / 备注）
 *    **缺值整行不印**（50mm 版心不拿空行吃行高）；
 * 3. **下单日期按业务时区 Asia/Shanghai**取日：`2026-09-01T16:30:00Z` ⇒ `2026-09-02`
 *    （按 UTC 切字符串会少一天 —— 车间会当成另一天的货）。
 */
import { ROWS_LABEL_MISSING, type RowsLabelRow, type RowsLabelSpec } from './rowsLabel'

/** 缺值占位（与发货单纸面 / H5 同口径）。 */
export const SHIP_LABEL_MISSING = ROWS_LABEL_MISSING

/** 业务时区（与服务端 `businessClock` 同口径）：Asia/Shanghai = UTC+8（无夏令时）。 */
const SHANGHAI_OFFSET_MINUTES = 8 * 60

/** 发货联需要的最小行字段面（`GET /api/worker/shipment/orders` 的 `items[]`）。 */
export interface ReadyShipmentOrderLike {
  order_id?: string | null
  order_no?: string | null
  created_at?: string | null
  customer_name?: string | null
  customer_phone?: string | null
  customer_address?: string | null
  logistics_type?: string | null
  logistics_type_label?: string | null
  logistics_company?: string | null
  total_sets?: number | null
  completed_sets?: number | null
  remark?: string | null
  /** 随货标识（issue #7856）：服务端按部位序去重、`/` 连接；缺值 = 该行不印 */
  curtain_types?: string | null
  install_community?: string | null
  install_rooms?: string | null
}

/** 值 → 纸面文本：去空白后为空 ⇒ `—`（缺值不编造）。 */
export function textOrMissing(value: unknown): string {
  const text = value == null ? '' : String(value).trim()
  return text === '' ? SHIP_LABEL_MISSING : text
}

/** 可选附注：去空白后为空 ⇒ `''`（调用方据此**整行不印**）。 */
function optionalText(value: unknown): string {
  return value == null ? '' : String(value).trim()
}

/** 物流类型：服务端已给展示名就照用；没给 ⇒ `—`，**绝不回退「快递」**。 */
export function shipLogisticsTypeText(order: ReadyShipmentOrderLike | null | undefined): string {
  return textOrMissing(order?.logistics_type_label)
}

/** 套数：只读服务端给的 `total_sets` / `completed_sets`，不自己数（第二份完工口径）。 */
export function setsText(order: ReadyShipmentOrderLike | null | undefined): string {
  const total = Number(order?.total_sets)
  const completed = Number(order?.completed_sets)
  if (!Number.isFinite(total) || total <= 0) return SHIP_LABEL_MISSING
  if (!Number.isFinite(completed)) return SHIP_LABEL_MISSING
  if (completed === total) return `${total} 套（全完工）`
  return `${completed}/${total} 套`
}

/**
 * 下单日期：`created_at`（ISO / 带偏移）⇒ `YYYY-MM-DD`，按**业务时区**取日。
 * 缺值 / 坏值 ⇒ `—`（不猜今天、不印 `Invalid Date`）。
 */
export function shipLabelDateText(value: unknown): string {
  const raw = value == null ? '' : String(value).trim()
  if (raw === '') return SHIP_LABEL_MISSING
  const at = new Date(raw)
  if (Number.isNaN(at.getTime())) return SHIP_LABEL_MISSING
  const local = new Date(at.getTime() + SHANGHAI_OFFSET_MINUTES * 60 * 1000)
  const year = local.getUTCFullYear()
  const month = String(local.getUTCMonth() + 1).padStart(2, '0')
  const day = String(local.getUTCDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * 发货联的**行清单**（唯一真值）：屏幕预览、打印、判据都读它。
 *
 * 行序 = 拣货 / 贴箱的人从上到下核对的顺序（与 `/w/` 逐行相同）。
 * 🔴 **不重复印「客户」**：本系统的客户 = 收货人，同一个人印两遍只是白吃版心。
 */
export function buildShipLabelRows(order: ReadyShipmentOrderLike | null | undefined): RowsLabelRow[] {
  const rows: RowsLabelRow[] = [
    { key: 'order_no', label: '订单号', value: textOrMissing(order?.order_no) },
    { key: 'consignee', label: '收货人', value: textOrMissing(order?.customer_name) },
    { key: 'customer_phone', label: '电话', value: textOrMissing(order?.customer_phone) },
    {
      key: 'customer_address',
      label: '地址',
      value: textOrMissing(order?.customer_address),
      multiline: true,
    },
  ]
  for (const [key, label, value, multiline] of [
    ['curtain_types', '帘种', optionalText(order?.curtain_types)],
    ['install_community', '安装小区', optionalText(order?.install_community)],
    ['install_rooms', '安装位置', optionalText(order?.install_rooms), true],
  ] as const) {
    if (value !== '') {
      rows.push({ key, label, value, ...(multiline ? { multiline: true } : {}) })
    }
  }
  rows.push(
    { key: 'logistics_type', label: '物流类型', value: shipLogisticsTypeText(order) },
    { key: 'logistics_company', label: '物流公司', value: textOrMissing(order?.logistics_company) },
    { key: 'order_date', label: '下单日期', value: shipLabelDateText(order?.created_at) },
    { key: 'sets', label: '套数', value: setsText(order) },
  )
  const remark = optionalText(order?.remark)
  if (remark !== '') {
    rows.push({ key: 'remark', label: '备注', value: remark, multiline: true })
  }
  return rows
}

/** 纸面输入：标题「发货联」+ 行清单；纸长按内容撑开（介质 `lengthMm` 的上下限）。 */
export function shipLabelSpec(order: ReadyShipmentOrderLike | null | undefined): RowsLabelSpec {
  return {
    title: '发货联',
    rows: buildShipLabelRows(order),
    shortCode: null,
  }
}
