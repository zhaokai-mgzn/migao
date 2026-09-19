/**
 * 工艺规格（craft spec）展示映射 —— **单一真值定义**，多处渲染共用（设计文档 §4.9）。
 *
 * 用户原话（issue #4355）：「这些信息需要在报价单和订单中展示，未来加工单去生产也需要。」
 * §4.9 的一致性硬约束：三处**同一份定义**，不得各写一份推导 ⇒ 本文件就是那份定义：
 *   ① 报价单（C 端 QuotationCard）   ← 渲染 `curtain_calc` 输出（snake_case）
 *   ② 订单（admin-web 详情/明细行）   ← 渲染 `order_items.processing_info`（camelCase）
 *   ③ 加工单（区块/打印/复制全部）     ← 渲染 `items_snapshot`（与 ② 同键名）
 *
 * ⚠️ **本文件在 mini-app / bmini-app / admin-web 三端逐字同源**：三端是独立 npm 工程、
 * 无共享包（与 QuotationCard 等既有跨端重复文件同一处置）。**改一处必须同步另外两处**，
 * 否则就回到「各写一份推导」——那正是 §4.9 要禁止的形态。
 *
 * 两条硬约束（§4.9）：
 * 1. **缺值不渲染**：键缺席 / `null` / 空串 / 非有限数 / 空数组 ⇒ 该行**不出现**；
 *    **绝不**渲染 `undefined` / `null` / `NaN`，也**不补默认值**（存量单没有工艺键 = 未携带，不是错值）。
 * 2. **只做展示**：本文件不推导金额、不加价 —— 拼色/定型/特殊选项加价待客户裁定（issue #4341）。
 *
 * 键名口径（§4.5）：订单/快照层 = camelCase，算料输出（`curtain_calc`）= snake_case。
 * ⇒ 每个字段同时登记两种键名（同一真值的两种载体，**不是**两套定义）。
 */

/** 一行工艺规格（标签 + 已格式化的展示值） */
export interface CraftSpecRow {
  /** 展示标签（§4.9 表左列） */
  label: string
  /** 已格式化的展示值（只由真值渲染，不编默认值） */
  value: string
}

type Formatter = (value: unknown) => string | null

/**
 * 打开方式（§4.2 字段表 A：`openCount` = 1 单开 / 2 双开 / 3 三开 / 4 四开）。
 * 开数是**正整数**不是固定枚举（issue #4387 判据 1）⇒ 表外的开数由 `openCount()` 如实标「N 开」。
 */
const OPEN_COUNT_LABELS: Record<string, string> = {
  '1': '单开',
  '2': '双开',
  '3': '三开',
  '4': '四开',
}

/** 标量直出（数字/布尔/字符串）；数组、对象、空值 ⇒ `null`（不渲染） */
function plainText(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : null
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
  }
  return null
}

/** 取有限数值（容忍 JSON 里以字符串承载的数字）；其余 ⇒ `null` */
function numeric(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/** 长度（米）：`12.3米` */
function meters(value: unknown): string | null {
  const n = numeric(value)
  return n === null ? null : `${n}米`
}

/** 倍数：`2 倍` */
function times(value: unknown): string | null {
  const n = numeric(value)
  return n === null ? null : `${n} 倍`
}

/** 是否类：`true` → 是 / `false` → 否；其余 ⇒ 不渲染（不把「不知道」渲染成「否」） */
function yesNo(value: unknown): string | null {
  if (value === true || value === 'true') return '是'
  if (value === false || value === 'false') return '否'
  return null
}

/** 打开方式：已知开数用行业文案，未知开数如实标 `N 开` */
function openCount(value: unknown): string | null {
  const n = numeric(value)
  if (n === null) return null
  return OPEN_COUNT_LABELS[String(n)] ?? `${n} 开`
}

/** 特殊选项（19 项，字符串数组）⇒ `加铅线、双褶`；空数组 ⇒ 不渲染 */
function optionList(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const items = value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter((item) => item !== '')
  return items.length > 0 ? items.join('、') : null
}

/**
 * 加工类型（定高买宽 / 定宽买高）。
 *
 * §4.2 的真值来源 = `curtain_calc` 的 `formula_used`：
 * `fixed_height*` → 定高买宽；`fixed_width*` / `roman_panel` → 定宽买高。
 * 订单/快照层已直存中文 `cuttingMode` ⇒ 原样展示。
 * **未知取值一律不渲染**（fail-closed）—— 宁可少一行，也不把内部 formula 代号漏给顾客。
 */
function cuttingMode(value: unknown): string | null {
  const text = plainText(value)
  if (text === null) return null
  if (text.startsWith('fixed_height')) return '定高买宽'
  if (text.startsWith('fixed_width') || text === 'roman_panel') return '定宽买高'
  if (text === '定高买宽' || text === '定宽买高') return text
  return null
}

// ── D6 自动识别（issue #4526 · 设计 §5.1/§5.2）────────────────────────────────
//
// 用户 2026-09-19：「超高 / 超宽是和**门幅标准**比较的，客户报的数据和门幅对比后能
// **自动区分**出来是超高还是超宽，这个要求做到**自动识别**」。
//
// 冻结规则（设计 §5.2）：
//   门幅 G   = SKU.doorWidth（缺省 2.8 米；窄幅布 1.4）
//   卷边常量 = 0.3 米（**复用** `curtain_calc` 既有常量，不新造第二个数）
//   超高 = (成品高 + 0.3) > G      超宽 = (成品宽 + 0.3) > G      ← 两者独立，可同时为真
//   倒幅 = (cuttingMode == 定宽买高)   正幅 = (cuttingMode == 定高买宽)  ← 唯一推导，不设手选项
//
// ⚠️ **本条是推理、非实证**（未从 ERP 供应商处取得判据）⇒ 判定结果一律标 `source: '推算'`，
// 阈值给默认值 + 商家可配，**不假装定论**（照实登记，见设计 §5.2 / §10）。

/**
 * 卷边常量（米）= 算料引擎 `curtain_calc.py` 的 `HEM_MARGIN`（**副本**）。
 *
 * 同步守卫 = `tests/unit/lib/craft-auto-features.test.ts`（逐值读 Python 源比对，漂移即红）——
 * 本仓「副本必须有同步守卫」纪律的落点（同族 #4393 / `PLEAT_FABRIC_PER_FOLD`）。
 */
export const HEM_MARGIN = 0.3

/** 门幅缺省值（米）—— SKU 未携带 `doorWidth` 时的行业常态 */
export const DEFAULT_DOOR_WIDTH = 2.8

/** 自动识别特征名（**推导产生**，不是商家勾选项 —— 判据 8：出现手选项 ⇒ 红） */
export type AutoFeatureName = '超高' | '超宽' | '倒幅' | '正幅' | '定型'

/** 一条自动识别特征（`source` 一律「推算」：推理非实证，照实标注） */
export interface AutoFeature {
  name: AutoFeatureName
  source: '推算'
  /** 可读依据（哪两个数比出来的）—— 商家要能核对判定 */
  reason: string
}

/** 取有限正数（容忍 JSON 里以字符串承载的数字）；其余 ⇒ `null` */
function positiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/** 米数取整到毫米（判定文案用）—— 浮点加法会给出 `6.8999999999999995` 这类值，不能进判定文案 */
function roundMeters(value: number): number {
  return Number(value.toFixed(3))
}

/**
 * 门幅（米）—— 解析 SKU 的 `doorWidth`（可带单位，如 `2.8米`）。
 * 缺席 / 不可解析 / 非正数 ⇒ {@link DEFAULT_DOOR_WIDTH}（不判成 0，也不「不判定」）。
 */
export function resolveDoorWidth(doorWidth: unknown): number {
  if (doorWidth === null || doorWidth === undefined) return DEFAULT_DOOR_WIDTH
  const match = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!match) return DEFAULT_DOOR_WIDTH
  return positiveNumber(match[1]) ?? DEFAULT_DOOR_WIDTH
}

/** 一条自动识别特征入参（尺寸一律米；`doorWidth` 给原始值，本函数负责解析） */
export interface AutoFeatureInput {
  /** 成品宽（米）；缺失 / 非正数 ⇒ 不判超宽 */
  width?: number | null
  /** 成品高（米）；缺失 / 非正数 ⇒ 不判超高 */
  height?: number | null
  /** SKU 门幅（原样传入，本函数用 {@link resolveDoorWidth} 解析） */
  doorWidth?: unknown
  /** 加工类型（定高买宽 / 定宽买高）；未指定 / 表外取值 ⇒ 不推导朝向 */
  cuttingMode?: string
  /** 是否定型（工艺规格 `isShaped`，R9 并入特征）；`true` 才出特征 */
  isShaped?: boolean
}

/**
 * 自动识别（设计 §5.2 冻结规则）—— 纯函数，**不读任何全局状态**。
 *
 * 顺序 = `超宽 → 超高 → 倒幅/正幅 → 定型`（与 ERP 组合名 `韩折+超宽+超高+定型` 同族；
 * 组合键归一化另有唯一实现，此处顺序只为展示稳定）。
 */
export function detectAutoFeatures(input: AutoFeatureInput): AutoFeature[] {
  const features: AutoFeature[] = []
  const doorWidth = resolveDoorWidth(input.doorWidth)

  const width = positiveNumber(input.width)
  if (width !== null && roundMeters(width + HEM_MARGIN) > doorWidth) {
    features.push({
      name: '超宽',
      source: '推算',
      reason: `成品宽 ${width} + 卷边 ${HEM_MARGIN} = ${roundMeters(width + HEM_MARGIN)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  const height = positiveNumber(input.height)
  if (height !== null && roundMeters(height + HEM_MARGIN) > doorWidth) {
    features.push({
      name: '超高',
      source: '推算',
      reason: `成品高 ${height} + 卷边 ${HEM_MARGIN} = ${roundMeters(height + HEM_MARGIN)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  // 倒幅 / 正幅由 `cuttingMode` **唯一推导**（设计 §5.1）—— 设手选项 = 制造第二份冲突口径
  if (input.cuttingMode === '定宽买高') {
    features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
  } else if (input.cuttingMode === '定高买宽') {
    features.push({ name: '正幅', source: '推算', reason: '加工类型 = 定高买宽' })
  }

  // R9：是否定型从「工艺规格字段」并入加工项特征（组合键的构成要素）
  if (input.isShaped === true) {
    features.push({ name: '定型', source: '推算', reason: '工艺规格：是否定型 = 是' })
  }

  return features
}

interface CraftSpecField {
  label: string
  /** 键名别名：订单/快照层 camelCase 在前，算料输出 snake_case 在后 */
  keys: string[]
  format: Formatter
}

/** §4.9「各面应展示的字段」表 —— 顺序即渲染顺序 */
const CRAFT_SPEC_FIELDS: CraftSpecField[] = [
  { label: '部位', keys: ['curtainType', 'curtain_type'], format: plainText },
  { label: '工艺', keys: ['craft'], format: plainText },
  // 加工类型：订单/快照层直存 `cuttingMode`；报价单只有 `formula_used`（§4.2 的真值来源）
  { label: '加工类型', keys: ['cuttingMode', 'cutting_mode', 'formula_used'], format: cuttingMode },
  { label: '打开方式', keys: ['openCount', 'open_count'], format: openCount },
  { label: '是否定型', keys: ['isShaped', 'is_shaped'], format: yesNo },
  { label: '款式', keys: ['style'], format: plainText },
  { label: '特殊选项', keys: ['specialOptions', 'special_options'], format: optionList },
  { label: '总褶数', keys: ['pleatCount', 'pleat_count'], format: plainText },
  { label: '折数（每片）', keys: ['perPanelPleats', 'per_panel_pleats'], format: plainText },
  { label: '褶距', keys: ['pleatSpacing', 'pleat_spacing'], format: meters },
  { label: '幅数', keys: ['panels'], format: plainText },
  { label: '理论褶倍', keys: ['fullness'], format: times },
  { label: '实际褶倍', keys: ['fullnessActual', 'fullness_actual'], format: times },
  { label: '面料米数', keys: ['fabricMeters', 'fabric_meters'], format: meters },
  { label: '加工费米数', keys: ['processingMeters', 'processing_meters'], format: meters },
  { label: '是否对花', keys: ['hasPattern', 'has_pattern'], format: yesNo },
  { label: '花距', keys: ['patternRepeat', 'pattern_repeat'], format: meters },
]

/** 按别名顺序取第一个「存在且非 null/undefined」的键值 */
function pick(source: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    const value = source[key]
    if (value !== undefined && value !== null) return value
  }
  return undefined
}

/**
 * 把一份工艺规格对象渲染为展示行（缺值行被丢弃）。
 *
 * @param source 订单/快照层的 `processingInfo`（camelCase）**或**报价单的 `curtain_calc`
 *               输出（snake_case）—— 同一份定义同时吃两种键名（§4.5）
 * @returns 只含**真有值**的行；无任何工艺键时返回 `[]`
 */
export function craftSpecRows(source: unknown): CraftSpecRow[] {
  if (source === null || typeof source !== 'object' || Array.isArray(source)) return []
  const record = source as Record<string, unknown>
  const rows: CraftSpecRow[] = []
  for (const field of CRAFT_SPEC_FIELDS) {
    const value = field.format(pick(record, field.keys))
    if (value !== null) rows.push({ label: field.label, value })
  }
  return rows
}

/** 该键是否属于工艺规格字段（渲染方据此避免同一真值被重复展示，如订单明细的键值兜底行） */
export function isCraftSpecKey(key: string): boolean {
  return CRAFT_SPEC_FIELDS.some((field) => field.keys.includes(key))
}

/** 一行纯文本（打印/「复制全部」用）：`工艺：韩褶` */
export function craftSpecLine(row: CraftSpecRow): string {
  return `${row.label}：${row.value}`
}
