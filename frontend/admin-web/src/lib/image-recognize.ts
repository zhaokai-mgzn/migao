/**
 * 图片识别结果的**表单预填映射**（issue #5321 包 1「页面快通道」）—— 纯函数，不碰 React。
 *
 * 🔴 **不落库**：识别结果只填表，提交永远是人的动作 —— 本模块只产出
 * `ProductFormData` 的部分初值 / 收货信息的部分改写，**不请求任何写端点**。
 *
 * 口径（冻结契约，见 `lib/api.ts` 的 `imageRecognizeApi`）：
 * - `value` 非空 = 预填候选，`source` 恒为 `[图片识别]`；
 * - `value === null` = 内核**有意留空**（不确定的宁可不填）⇒ **绝不写进表单**，
 *   只在识别结果面板里连 `reason` 一起展示给商家看。
 */
import type { RecognizedField } from './api'
import type { ProductColor, ProductFormData } from '@/types'
import { nextTempId, normalizeDoorWidth, rebuildSkus } from './sku-utils'

/** 预填来源标记（与内核返回的 `source` 逐字一致 —— 徽标文案单一事实源，不另写一份） */
export const RECOGNIZE_SOURCE_TAG = '[图片识别]'

/** 有值的字段 = 预填候选（`value: null` 的字段**不在其中**，见文件头口径） */
export function filledFields(fields: RecognizedField[]): RecognizedField[] {
  return (fields || []).filter(
    (f) => typeof f.value === 'string' && f.value.trim() !== '',
  )
}

/** 取「有值」字段本身（拿得到 `label`）；空值字段一律视为不存在 */
function pickField(fields: RecognizedField[], key: string): RecognizedField | undefined {
  return (fields || []).find(
    (f) => f.key === key && typeof f.value === 'string' && f.value.trim() !== '',
  )
}

/** 取「有值」字段的值（已 trim）；空值字段返回 `''` */
function valueOf(fields: RecognizedField[], key: string): string {
  const hit = pickField(fields, key)
  return hit && typeof hit.value === 'string' ? hit.value.trim() : ''
}

/**
 * 门幅归一（`'门幅2.8米'` → `'2.8'`，复用 SKU 矩阵同一实现）+ **只收数字**：
 * 预填绝不能把「深灰色」这类识别结果塞进门幅列（那会造出一个假 SKU 维度）。
 */
function normalizedDoorWidth(raw: string): string {
  const v = normalizeDoorWidth(raw)
  return v !== '' && Number.isFinite(Number(v)) ? v : ''
}

export interface ProductPrefill {
  /** 传给 `<ProductForm initialData={...} />` 的初值（**只含能安全映射的键**） */
  initialData: Partial<ProductFormData>
  /** 实际预填的**响应字段键**，供表单渲染 `[图片识别]` 徽标（`recognized-marker-<key>`） */
  recognizedFields: string[]
}

/**
 * 商品侧映射（**只映射能从既有代码论证的键**，映射不到的宁可不填 —— 见下表）：
 *
 * | 响应 key | 表单字段 | 依据 |
 * |---|---|---|
 * | `name` | `name`（商品标题） | 同名直填 |
 * | `material` / `craft` | `specifications.material` / `.craft` | `ProductAttributes` 读的是**英文 key**（`lib/attribute-keys.ts`：表单内部英文 key、提交时 `toChineseSpecKeys` 转中文落库）⇒ 只有英文 key 才**在表单里看得见**，且落库口径仍是「材质 / 工艺」 |
 * | `color` | `colors[].colorName` | `ProductColor` 需要 `id` ⇒ 复用 SkuMatrix「添加颜色」同一条路径的 `nextTempId()` |
 * | `door_width` | `doorWidths[]` | 经 `normalizeDoorWidth` 归一（与门幅下拉选项同口径） |
 * | `price` | **不映射**（有意） | `ProductFormData.price` 只是 `derivePrice(skus, price)` 的**兜底值**，商品页上**没有任何控件显示它** ⇒ 预填了商家看不见也改不了（「看得见才敢提交」）⇒ 留给商家在 SKU 矩阵里按门幅填 |
 */
export function buildProductPrefill(fields: RecognizedField[]): ProductPrefill {
  const initialData: Partial<ProductFormData> = {}
  const recognizedFields: string[] = []

  const name = valueOf(fields, 'name')
  if (name) {
    initialData.name = name
    recognizedFields.push('name')
  }

  // 规格属性：表单内部英文 key（material / craft），提交时由 ProductForm 转中文落库
  const specifications: Record<string, string> = {}
  for (const key of ['material', 'craft']) {
    const v = valueOf(fields, key)
    if (v) {
      specifications[key] = v
      recognizedFields.push(key)
    }
  }
  if (Object.keys(specifications).length > 0) {
    initialData.specifications = specifications
  }

  const colorName = valueOf(fields, 'color')
  const doorWidth = normalizedDoorWidth(valueOf(fields, 'door_width'))
  const colors: ProductColor[] = colorName ? [{ id: nextTempId(), colorName }] : []
  const doorWidths: string[] = doorWidth ? [doorWidth] : []
  if (colors.length > 0) {
    initialData.colors = colors
    recognizedFields.push('color')
  }
  if (doorWidths.length > 0) {
    initialData.doorWidths = doorWidths
    recognizedFields.push('door_width')
  }
  if (colors.length > 0 || doorWidths.length > 0) {
    // 与 SkuMatrix 每次改动走同一条路径：矩阵行 = 颜色 × 门幅（价格/库存留 0，由商家填）
    initialData.skus = rebuildSkus(colors, doorWidths, [])
  }

  return { initialData, recognizedFields }
}

/** 订单侧**当前值**（判断「这个字段是不是还空着」的依据） */
export interface OrderPrefillCurrent {
  customerName: string
  customerPhone: string
  customerAddress: string
  remark: string
}

export interface OrderPrefill {
  /** 缺省 = **不改这个字段**（键不出现即不动） */
  customerName?: string
  customerPhone?: string
  customerAddress?: string
  remark?: string
  /** 实际预填的**页面字段名**（`customerName` / …），供 `recognized-marker-*` 徽标 */
  recognizedFields: string[]
}

/** 明细/数量/规格 —— 本包**不进 lineItems**（要选真 SKU，超出包 1 范围）⇒ 拼一行进备注 */
const ORDER_DETAIL_KEYS = ['items', 'quantity', 'spec'] as const

/**
 * 订单侧映射。
 *
 * 🔴 **只在字段当前为空时才填**（不覆盖用户已输入的内容）：订单侧填错收货信息
 * = 货发到错的人手上 ⇒ 「宁可不填」优于「覆盖」；填过的字段配 `[图片识别]` 徽标提醒复核。
 * `customer_phone` **原样使用**（内核已归一为 11 位）。
 * `items` / `quantity` / `spec` **不动 lineItems**，拼一行 `[图片识别] 商品明细：…；数量：…；规格：…`
 * 追加进备注（已有同一行则不重复追加）。
 */
export function buildOrderPrefill(
  fields: RecognizedField[],
  current: OrderPrefillCurrent,
): OrderPrefill {
  const prefill: OrderPrefill = { recognizedFields: [] }

  const fillBlank = (
    responseKey: string,
    pageKey: 'customerName' | 'customerPhone' | 'customerAddress',
    currentValue: string,
  ) => {
    const v = valueOf(fields, responseKey)
    if (!v || currentValue.trim() !== '') return
    prefill[pageKey] = v
    prefill.recognizedFields.push(pageKey)
  }

  fillBlank('customer_name', 'customerName', current.customerName)
  fillBlank('customer_phone', 'customerPhone', current.customerPhone)
  fillBlank('customer_address', 'customerAddress', current.customerAddress)

  // 明细 / 数量 / 规格：标签取响应里的 `label`（口径由内核给，前端不另写一份文案）
  const parts: string[] = []
  for (const key of ORDER_DETAIL_KEYS) {
    const hit = pickField(fields, key)
    if (hit && typeof hit.value === 'string') {
      parts.push(`${hit.label || key}：${hit.value.trim()}`)
    }
  }
  if (parts.length > 0) {
    const line = `${RECOGNIZE_SOURCE_TAG} ${parts.join('；')}`
    if (!current.remark.includes(line)) {
      prefill.remark = current.remark.trim() ? `${current.remark.trimEnd()}\n${line}` : line
      prefill.recognizedFields.push('remark')
    }
  }

  return prefill
}