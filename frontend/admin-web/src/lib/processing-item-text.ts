/**
 * 「一个**商品行**的加工项」在纸面上的**单一文案真值**（issue #7891，用户 2026-10-27 逐字
 * 「发货单的加工项需要和商品绑定，比如如果是成品帘，一览展示商品，商品下面是加工项，
 * 展示内容参考水洗唛的那种格式，还有特殊选项也要放上去，都放在加工项那一栏里面」）。
 *
 * ## 为什么要有这个模块（不是"抽个工具函数"）
 *
 * 用户同一次要求里点名了三份纸：**销售单 / 报价单**（原先**没有**加工项）与**发货单**
 * （原先把加工项压成表外一行、**不绑商品**）。三份纸各拼一份文案 = 三份会漂的口径
 * （同一张订单的"做哪些活"在不同纸上长得不一样）。⇒ 加工项文案只在这里拼一次，
 * 三份纸都只**渲染它的结果**。
 *
 * ## 取值口径（全部复用既有单一真值，本模块不另写推导）
 *
 * | 纸面内容 | 真值源 |
 * |---|---|
 * | 加工项清单 | `OrderItem.processingInfo.processingItems[]`（写侧单点 `buildLineProcessingInfo`） |
 * | 加工项数量 | 同数组的 `quantity`（缺值 ⇒ `—`，**不印 0**） |
 * | 特殊选项 | `craftRowsWithoutDoorWidth()` 的「特殊选项」行（`lib/order-item-sku.ts` 的 sanctioned 读取口 ——
 *   与订单详情 / 加工单纸面同一份格式化；它排除「门幅」行，那件事实在明细表里已有自己的列） |
 *
 * ## 文案形态（issue #7605 的既有裁定照旧，勿退回旧写法）
 *
 * - 数量**全等** ⇒ `定型、韩褶 各 6.3`（数字只说一遍，用户要的省法）
 * - 数量**不等** / 有缺值 ⇒ `定型 6.3 + 韩褶 2`（缺值项仍印 `—`，不静默吞掉）
 * - 单项 ⇒ `定型 6.3`（不写「各」——「定型 各 6.3」是病句）
 * - 🔴 **不采用** `（A+B）×6`：① 纯文本有运算优先级歧义；② 纸面上与「加工费合计」并排会诱导
 *   客户拿它去乘出加工费（真值 = 加工费组合价 元/米 × 加工费米数）；③ 各加工项数量可以不等、
 *   也可以缺 ⇒ 无条件提公因子 = 把不等的数压成一个 = 报错数。
 *
 * 判据：`frontend/admin-web/tests/unit/lib/processing-item-text.test.ts`；
 * 类级守卫 = `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 的 C9。
 */
import { craftRowsWithoutDoorWidth } from './order-item-sku'

/** 纸面缺值占位（与 `ShipmentDoc.SHIPMENT_DOC_MISSING` / `SalesDoc.SALES_DOC_MISSING` 同一字符） */
export const PROCESSING_TEXT_MISSING = '—'

/** 加工项行的一行（来源形态；只读 `name` / `quantity`，多余键不参与纸面） */
export interface ProcessingItemLike {
  name?: string
  quantity?: number | null
}

/** 纸面的一行（水洗唛式 `标签` + `值`，渲染方决定分隔符与字体） */
export interface ProcessingPaperRow {
  label: '加工项' | '特殊选项'
  value: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * `processingInfo` 的**读入归一**：对象直接用；JSON 字符串先解析（历史/自定义查询路径会下发串，
 * 见 `EditOrderContentModal` 的同一处理）；解析不了 ⇒ `null`（**不猜**，当没有加工项信息）。
 */
function asInfoRecord(info: unknown): Record<string, unknown> | null {
  if (typeof info === 'string') {
    const text = info.trim()
    if (text === '') return null
    try {
      const parsed: unknown = JSON.parse(text)
      return isRecord(parsed) ? parsed : null
    } catch {
      return null
    }
  }
  return isRecord(info) ? info : null
}

/** 数量取形：非有限数 ⇒ `null`（缺值 = 没记过这个数，**不是** 0） */
function paperNumber(value?: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 加工项数量的纸面取形（缺值 ⇒ `—`；真 0 仍印 `0`） */
export function formatProcessingQty(qty?: number | null): string {
  const value = paperNumber(qty)
  return value === null ? PROCESSING_TEXT_MISSING : String(value)
}

/**
 * 加工项清单的一行文案（见文件头的三态）。
 *
 * 🔴 构建器里**不得**出现 `×`（守卫 C9 判红）：纸面上的「×N」会被读成乘法。
 */
export function processingItemsText(items: readonly ProcessingItemLike[]): string {
  const rows = items.filter((item): item is ProcessingItemLike & { name: string } => {
    return typeof item?.name === 'string' && item.name.trim() !== ''
  })
  if (rows.length === 0) return ''
  const names = rows.map((item) => item.name.trim())
  const qty = rows.map((item) => formatProcessingQty(item.quantity))
  const uniform =
    qty.length > 1 && !qty.includes(PROCESSING_TEXT_MISSING) && qty.every((q) => q === qty[0])
  if (uniform) return `${names.join('、')} 各 ${qty[0]}`
  return names.map((name, idx) => `${name} ${qty[idx]}`).join(' + ')
}

/** 该商品行的加工项（`processingInfo.processingItems[]`；缺键 / 形态不对 ⇒ 空数组） */
export function processingItemsOf(info: unknown): ProcessingItemLike[] {
  const record = asInfoRecord(info)
  if (!record) return []
  const list = Array.isArray(record.processingItems) ? record.processingItems : []
  return list.filter(isRecord).map((row) => ({
    name: typeof row.name === 'string' ? row.name : undefined,
    quantity: typeof row.quantity === 'number' ? row.quantity : null,
  }))
}

/**
 * 该商品行的**特殊选项**（走 `craftRowsWithoutDoorWidth()` 的同一份格式化 —— camelCase
 * `specialOptions` 与 snapshot 口径 `special_options` 两个别名都由 `craft-display` 登记，
 * 本模块不另读键；⚠️ 用 sanctioned 读取口而不是直调 `craftSpecRows()` —— 后者有
 * `tests/unit/craft-spec-row-source-guard.test.ts` 的取值口台账在管）。
 */
export function specialOptionsTextOf(info: unknown): string {
  const record = asInfoRecord(info)
  if (!record) return ''
  const row = craftRowsWithoutDoorWidth(record).find((entry) => entry.label === '特殊选项')
  return row ? row.value : ''
}

/**
 * 纸面的有序行清单（水洗唛式 `标签 值`）：只有**真有值**的行才出。
 * 全都没有 ⇒ `[]`（调用方据此**整块不渲染** —— 布料行、存量无加工项的行都走这条）。
 */
export function processingPaperRows(info: unknown): ProcessingPaperRow[] {
  const rows: ProcessingPaperRow[] = []
  const itemsText = processingItemsText(processingItemsOf(info))
  if (itemsText !== '') rows.push({ label: '加工项', value: itemsText })
  const optionsText = specialOptionsTextOf(info)
  if (optionsText !== '') rows.push({ label: '特殊选项', value: optionsText })
  return rows
}

/**
 * 单行形态（窄纸面：三联纸销售单这类，一行放得下就别起两行）：
 * `加工项：定型、韩褶 各 6.3 · 特殊选项：拼2次-布`；全都没有 ⇒ `''`。
 */
export function processingPaperLine(info: unknown): string {
  return processingPaperRows(info)
    .map((row) => `${row.label}：${row.value}`)
    .join(' · ')
}
