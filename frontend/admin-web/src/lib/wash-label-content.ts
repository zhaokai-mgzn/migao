/**
 * 水洗唛**纸面内容**的单一真值（issue #6656）。
 *
 * ## 为什么要有这个模块（根因，实测）
 *
 * 同一条加工单的水洗唛有**两条打印通道**：系统打印（`components/production/TaskCardPrint.tsx`，
 * HTML/CSS + `@page`，用户看到的那张预览）与免驱动直连（`lib/label-print/*`，canvas 位图）。
 * 改动前两边**各写了一份纸面字段**：
 *
 * | 通道 | 字段来源 | 纸面 |
 * |---|---|---|
 * | 系统打印 | 组件内联派生（客户 / 套序 / 部位 / 件名 / 色号 / 用料 / 宽高 / 加工方式 / 订单 / 交期 / 备注 / 算料公式） | 预览那张 |
 * | 直连打印 | `toWashLabelInputs` 只映射 4 个键（码 / 短码 / 件名 / 部位） | 只有二维码 + 短码 + 一行件名 |
 *
 * 用户 2026-10-10 逐字：「**直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的**」
 * ⇒ 两条通道改读**同一份有序行清单**（本模块）。版式差异只允许剩下**纸的物理宽度**：
 * 预览印在 50mm 纸上，而标签机打印头只有 384 点 = 48mm（登记在 `lib/print-media.json` 的
 * `label-50x60.dotGeometry`：「右侧约 2mm 打不到」）。
 *
 * ## 边界（照实登记，不粉饰）
 *
 * - 本模块只管**内容**（印什么、什么顺序、取什么值），不管**排版**：CSS 与 canvas 是两套排版引擎，
 *   折行 / 裁切规则各由渲染器决定；`maxLines` 是给位图渲染器的**行数预算**。
 * - 取值口径**一律复用**既有单一真值：工艺规格走 `lib/craft-display.ts` 的 `craftSpecRows`、
 *   套序走 `components/production/ProductionProgressTable.tsx` 的 `groupBySet` —— 本模块不另写推导
 *   （另写一份 = 又一个「同一真值两处投影」，改一处另一处不会红）。
 */
import { craftSpecRows, type CraftSpecRow } from './craft-display'
import { groupBySet } from '@/components/production/ProductionProgressTable'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

/** 纸面上的**一行**（有序清单的元素） */
export interface WashLabelRow {
  /** 行标识（渲染器据此映射 CSS class / `data-testid` / 省略策略；**不参与纸面内容**） */
  key: WashLabelRowKey
  /**
   * 纸面**逐字**文本（`标签 + 空格 + 值`，已按取值口径格式化）。
   * 🔴 两条通道渲染它，**不得**各自再拼一次前缀（拼第二遍就是第二份真值）。
   */
  text: string
  /** 行数预算：位图渲染器折到第 `maxLines` 行还没完 ⇒ 以省略号收尾（看得见的截断） */
  maxLines: number
}

export type WashLabelRowKey =
  | 'customer'
  | 'setNo'
  | 'positionKind'
  | 'pieceName'
  | 'color'
  | 'meters'
  | 'size'
  | 'craft'
  | 'orderNo'
  | 'delivery'
  | 'remark'
  | 'formula'

/** 纸面行的**行序**（照真实工单：亿家纺织「成品定制」58mm 竖排小票的信息顺序） */
export const WASH_LABEL_ROW_KEYS: readonly WashLabelRowKey[] = [
  'customer',
  'setNo',
  'positionKind',
  'pieceName',
  'color',
  'meters',
  'size',
  'craft',
  'orderNo',
  'delivery',
  'remark',
  'formula',
]

/** 行数预算（件名 / 加工方式 / 备注 / 算料公式可折行；其余单行）—— 与 `TaskCardPrint` 的 clamp 口径同源 */
const MAX_LINES: Record<WashLabelRowKey, number> = {
  customer: 1,
  setNo: 1,
  positionKind: 1,
  pieceName: 2,
  color: 1,
  meters: 1,
  size: 1,
  craft: 2,
  orderNo: 1,
  delivery: 1,
  remark: 2,
  formula: 2,
}

/** 用料 = 面料米数优先；没有则退回加工费米数（两者都是「要用多少料」的同一件事） */
const METERS_LABELS = ['面料米数', '加工费米数']

/** 取工艺规格行的值（只按标签取，不重算 —— 格式化真值在 `craft-display`） */
function specValue(rows: CraftSpecRow[], ...labels: string[]): string {
  for (const label of labels) {
    const hit = rows.find((row) => row.label === label)
    if (hit) return hit.value
  }
  return ''
}

/** 宽高（= 窗宽 × 窗高；两边都必须是有限数才出 —— 半个尺寸没有意义）⇒ `3×2.75米` */
export function washLabelSize(width?: number | null, height?: number | null): string {
  const ok = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
  return ok(width) && ok(height) ? `${width}×${height}米` : ''
}

/**
 * 加工方式 = 工艺 · 加工类型 · 打开方式 · 定型（**值**一律取自 `craft-display` 的同一份格式化，不重算）。
 *
 * 其中「是否定型」在纸面上按**行业措辞**收成「定型 / 不定型」—— 真实工单就是这么写的
 * （图1「单开-韩褶-定型」、图3「双开韩褶 定高买宽 定型」）；单印一个「是」在纸面上读不出
 * 是哪个字段的「是」。**只映射展示形态，不改值本身**。
 */
export function washLabelCraftMode(item?: ProcessingOrderItem | null): string {
  const rows = craftSpecRows(item)
  const shaped = specValue(rows, '是否定型')
  return [
    specValue(rows, '工艺'),
    specValue(rows, '加工类型'),
    specValue(rows, '打开方式'),
    shaped === '是' ? '定型' : shaped === '否' ? '不定型' : '',
  ]
    .filter((value) => value !== '')
    .join(' · ')
}

/** 用料 = 面料米数优先，退回加工费米数 */
export function washLabelMeters(item?: ProcessingOrderItem | null): string {
  return specValue(craftSpecRows(item), ...METERS_LABELS)
}

/** 备注 = 特殊选项（真实工单的「防翘扣 / 花边」那一类）+ 快照备注（缺值不渲染） */
export function washLabelRemark(item?: ProcessingOrderItem | null): string {
  const special = specValue(craftSpecRows(item), '特殊选项')
  const remark = typeof item?.remark === 'string' ? item.remark.trim() : ''
  return [special, remark].filter((value) => value !== '').join('；')
}

/** 算料公式（用户字段裁定里的「备注（工艺备注 / 算料公式）」） */
export function washLabelFormula(item?: ProcessingOrderItem | null): string {
  return specValue(craftSpecRows(item), '算料公式')
}

export interface WashLabelRowsInput {
  /** 部位（= 商品行）；`null` ⇒ 不出任何行（调用方另出占位，不在这里编造） */
  position?: ProductionPosition | null
  /** 与 `position.order_item_id` 对齐的加工单快照行 */
  item?: ProcessingOrderItem | null
  /** 套序（1 起）：走 `groupBySet`，**与进度表同一份**口径 */
  setNo?: number
  setCount?: number
  /** 加工单公共属性（**每张**标签都呈现） */
  customerName?: string | null
  orderNo?: string | null
  expectedDeliveryDate?: string | null
}

/**
 * 部位 ⇒ 纸面**有序行清单**（两条打印通道的唯一内容真值）。
 *
 * 缺值不渲染：没有对应快照行 / 没有该键 ⇒ 该行**不出现**（纸面不出现 `undefined` / `null` / `NaN`）。
 * 例外 = 件名 / 订单号 / 交期：它们是「这张纸是给谁的」的最小可读集合，缺值如实出 `—`（不编造）。
 */
export function washLabelRows(input: WashLabelRowsInput): WashLabelRow[] {
  const position = input.position ?? null
  if (!position) return []

  const rows: WashLabelRow[] = []
  /**
   * 🔴 判空看的是**值**、不是拼好的整行 —— 只有「整行 trim 后为空」才算缺值，会把
   * `宽高 ` / `用料 ` 这种**只剩前缀**的空壳行印到纸面上（缺值不渲染是硬口径）。
   */
  const push = (key: WashLabelRowKey, value: string, prefix = '') => {
    const trimmed = (value ?? '').trim()
    if (trimmed === '') return
    rows.push({ key, text: prefix === '' ? trimmed : `${prefix} ${trimmed}`, maxLines: MAX_LINES[key] })
  }

  push('customer', input.customerName ?? '', '客户')

  const setNo = Number.isFinite(input.setNo) ? Number(input.setNo) : 1
  const setCount = Number.isFinite(input.setCount) ? Number(input.setCount) : 1
  push('setNo', `第 ${setNo} 套 / 共 ${setCount} 套`)

  push('positionKind', position.position_kind ?? '', '部位')

  // 件名：部位名优先，退回商品名（纸面要能认出「这一张是给哪一件的」）
  const pieceName = (position.position_name || position.product_name || '').trim()
  push('pieceName', pieceName === '' ? '—' : pieceName)

  // 色号已含在件名里 ⇒ 不重复渲染（50mm 下仍保留这条去重：恢复独立渲染只是把同名信息多印一遍）
  const colorName = typeof input.item?.colorName === 'string' ? input.item.colorName.trim() : ''
  if (colorName !== '' && !pieceName.includes(colorName)) push('color', colorName, '色号')

  push('meters', washLabelMeters(input.item), '用料')
  push('size', washLabelSize(position.width, position.height), '宽高')
  push('craft', washLabelCraftMode(input.item), '加工方式')

  push('orderNo', (input.orderNo ?? '').trim() || '—', '订单')
  push('delivery', (input.expectedDeliveryDate ?? '').trim() || '—', '交期')
  push('remark', washLabelRemark(input.item), '备注')

  // 算料公式**不带前缀**（形态本身就是 `韩褶公式：…`，再加「算料公式」是重复）
  push('formula', washLabelFormula(input.item))

  // 行序是纸面契约：即使某几行缺席，剩下的也必须按 `WASH_LABEL_ROW_KEYS` 排
  const order = new Map(WASH_LABEL_ROW_KEYS.map((key, index) => [key, index]))
  return rows.sort((a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0))
}

/** 直连通道一张标签要打的东西（= 表头 + 有序行 + 底部码/短码） */
export interface WashLabelInput {
  /** 二维码内容（该部位自己的 `scan_url ?? part_token`）；`null` ⇒ **不画假码**（出占位框） */
  qrValue: string | null
  /** 人可读短码（**底部大字**、纸面的手输降级入口） */
  shortCode: string
  /** 表头：加工单号（纸面**主标识**，7pt 粗体） */
  processingOrderNo?: string
  /** 正文行（有序，来自 {@link washLabelRows}） */
  rows?: WashLabelRow[]
  /** 缺码时的占位文案（默认「待生成」） */
  qrPlaceholderHint?: string
}

export interface WashLabelSource {
  processingOrderNo?: string | null
  orderNo?: string | null
  customerName?: string | null
  expectedDeliveryDate?: string | null
  positions?: ProductionPosition[] | null
  items?: ProcessingOrderItem[] | null
}

/**
 * 加工单 ⇒ 直连通道的**逐张**输入（**单一处**映射：页面与测试都走它，不各写一份）。
 *
 * - 码 = `scan_url ?? part_token`，两者都没有 ⇒ `null`（**不画假码**，与 `TaskCardPrint` 同口径）
 * - 短码缺失 ⇒ `'—'`（纸面如实显示「没有」，**不编造**）
 * - 套序走 `groupBySet`（与进度表 / 系统打印**同一份**实现）
 * - 0 个部位 ⇒ 空数组（**不造占位**：直连入口据此禁用，不是打一张空白纸）
 */
export function toWashLabelInputs(source: WashLabelSource = {}): WashLabelInput[] {
  const positions = source.positions ?? []
  const setViews = groupBySet(positions)
  /** 快照行按 `itemId` 索引（= `order_items.id` 主键，也是 `position.order_item_id` 的来源） */
  const itemsById = new Map<string, ProcessingOrderItem>()
  for (const item of source.items ?? []) {
    const id = (item as ProcessingOrderItem & { itemId?: string }).itemId
    if (id) itemsById.set(id, item)
  }

  return positions.map((position, index) => {
    const item = position.order_item_id ? itemsById.get(position.order_item_id) : undefined
    const setView = setViews[index]
    return {
      qrValue: position.scan_url ?? position.part_token ?? null,
      shortCode: (position.part_short_code ?? '').trim() || '—',
      processingOrderNo: (source.processingOrderNo ?? '').trim() || undefined,
      qrPlaceholderHint: undefined,
      rows: washLabelRows({
        position,
        item,
        setNo: (setView?.setIndex ?? 0) + 1,
        setCount: setView?.setCount ?? 1,
        customerName: source.customerName,
        orderNo: source.orderNo,
        expectedDeliveryDate: source.expectedDeliveryDate,
      }),
    }
  })
}
