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
 * | 系统打印 | 组件内联派生（订单 / 客户 / 套序 / 部位 / 颜色 / 门幅 / 用料 / 宽高 / 加工方式 / 褶法 / 特殊选项 / 备注） | 预览那张 |
 * | 直连打印 | `toWashLabelInputs` 只映射 4 个键（码 / 短码 / 件名 / 部位） | 只有二维码 + 短码 + 一行件名 |
 *
 * 用户 2026-10-10 逐字：「**直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的**」
 * ⇒ 两条通道改读**同一份有序行清单**（本模块）。版式差异只允许剩下**纸的物理宽度**：
 * 预览印在 50mm 纸上，而标签机打印头只有 384 点 = 48mm（登记在 `lib/print-media.json` 的
 * `label-50x150.dotGeometry`：「右侧约 2mm 打不到」）。
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
  | 'color'
  | 'doorWidth'
  | 'meters'
  | 'size'
  | 'craft'
  | 'pleats'
  | 'orderNo'
  | 'specialOptions'
  | 'remark'

/**
 * 纸面行的**行序**（照真实工单：亿家纺织「成品定制」58mm 竖排小票的信息顺序）。
 *
 * 🔴 **2026-10-25 用户裁定（issue #7776）退场两行**，勿"顺手加回"：
 *   ① **商品名称（件名）** —— 逐字「移除商品名称展示」；
 *   ② **算料公式（褶倍公式）** —— 逐字「移除褶倍公式字段展示」（它是算料引擎的**内部推导**，
 *      车间按纸面裁布用不到；印出来只会占纸面、挤出可读字号）。
 *   同时保留「**货号 / 颜色 / 门幅 + 其余工艺信息**」（用户逐字）：颜色与门幅已在表内，
 *   货号待加工单快照补 `productCode`（后端单，**未在册前不印**——不拿 SKU 组合码冒充货号，issue #7636）。
 */
export const WASH_LABEL_ROW_KEYS: readonly WashLabelRowKey[] = [
  // 🔴 **订单号第一行**（2026-10-26 用户逐字「把订单号放到第一行，客户那一行上面」）；
  // 同批「移除加工单号」「移除交期字段」⇒ 这两行不再存在（加工单号是**内部**编号，纸面只留订单号）。
  'orderNo',
  'customer',
  'setNo',
  'positionKind',
  'color',
  'doorWidth',
  'meters',
  'size',
  'craft',
  'pleats',
  'specialOptions',
  'remark',
]

/**
 * 行数预算（加工方式 / 特殊选项 / 备注可折行；其余单行）—— 与 `TaskCardPrint` 的 clamp 口径同源。
 *
 * 订单号给 2 行：12pt 下 17 位数字 + 「订单」前缀 ≈ 54mm > 版心 47.6mm ⇒ 必须允许**折行**
 * （`break-all`），**绝不**用省略号/裁切（它是纸上唯一的单据身份）。
 */
const MAX_LINES: Record<WashLabelRowKey, number> = {
  orderNo: 2,
  customer: 1,
  setNo: 1,
  positionKind: 1,
  color: 1,
  doorWidth: 1,
  meters: 1,
  size: 1,
  craft: 2,
  pleats: 1,
  specialOptions: 2,
  remark: 2,
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

/**
 * 特殊选项（真实工单的「加logo条 / 防翘扣 / 花边」那一类，如参考工单的
 * 「加logo条,防翘扣」）—— 单独成行，**不再**与备注合并（用户 2026-10-25 逐字
 * 「把特殊选项，备注也加上」：两者是不同来源的两种事实，合并后纸上分不出哪句是哪类）。
 */
export function washLabelSpecialOptions(item?: ProcessingOrderItem | null): string {
  return specValue(craftSpecRows(item), '特殊选项')
}

/** 备注 = 快照备注（`processing_info.remark`，自由文本；缺值不渲染） */
export function washLabelRemark(item?: ProcessingOrderItem | null): string {
  return typeof item?.remark === 'string' ? item.remark.trim() : ''
}

/**
 * **褶法** = 是否采用韩褶公式 + 韩褶的折数（**一个字段**，用户 2026-10-26 逐字
 * 「要体现出是否采用的韩褶公式以及韩褶的折数，用一个字段表示即可」）。
 *
 * 取值（**只读既有键、不重算**）：
 * - `韩褶公式`（褶数法，`calc` 侧产 `pleat_count`）⇒ `韩褶 52折`；折数缺失 ⇒ `韩褶`（**不编数**）
 * - `褶倍数公式`（倍数法）⇒ `倍数法`
 * - 两者都判不出来（老快照缺 `formula_text` 且无 `pleat_count`）⇒ **空串**（该行不印，不猜）
 *
 * 🔴 **为什么按 `formula_text` 前缀判**：加工单快照的算料输出键族（`ProcessingOrderService` 的
 * `CALC_OUTPUT_SNAPSHOT_KEYS`）里**没有** `formula`（`pleat|fullness`）这个键，只有
 * `formula_text` + `pleat_count`。而 `formula_text` 本身是算料引擎产出的**可读公式串**
 * （`韩褶公式：…` / `褶倍数公式：…`），纸面原本就印它 ⇒ 判它没有引入第二份真值。
 * `pleat_count` 只在褶数法产出（倍数法无褶数）⇒ 拿它兜底，老快照也能判出「韩褶」。
 *
 * 字段名为何叫「褶法」：它既不是纯折数（还有「是否韩褶公式」这一层），
 * 也不是纯算法名（纸上要给车间看折数）⇒ 取「褶的做法」这一层语义，纸面上读作
 * `褶法 韩褶 52折` / `褶法 倍数法`。
 */
/** 正整数读取口（容忍 JSON 里以字符串承载的数字；与 `craft-display` 的 `numeric()` 同口径） */
function positiveInt(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : null
}

export function washLabelPleats(item?: ProcessingOrderItem | null): string {
  const formulaText = typeof item?.formula_text === 'string' ? item.formula_text.trim() : ''
  const count = positiveInt(item?.pleat_count)
  if (formulaText.startsWith('褶倍数')) return '倍数法'
  if (formulaText.startsWith('韩褶') || count !== null) return count !== null ? `韩褶 ${count}折` : '韩褶'
  return ''
}

/**
 * 一张水洗唛**印几份** = 该商品的「打开方式」开数（`openCount`：1 单开 / 2 双开 / 3 三开 / 4 四开）。
 *
 * 用户 2026-10-26 逐字：「如果订单是双开的要打印两份，单开的要打印1份，三开打印3份，4开打印4份，
 * 这个都要在打印预览中默认设置好」。
 *
 * 🔴 **份数口径只有这一处**：系统打印（`TaskCardPrint` 逐张展开）与蓝牙直连
 * （`toWashLabelInputs` 展开）都读它 —— 各写一份 ⇒ 两条通道出纸张数会不一样。
 * 开数是**正整数**不是固定枚举（issue #4387）⇒ 表外开数如实 N 份；缺值 / 非法值 ⇒ 1 份。
 */
export function washLabelCopies(item?: ProcessingOrderItem | null): number {
  // 开数在订单侧是数字；存量/透传也可能以字符串承载（与 `craft-display` 的数字容忍同口径）
  return positiveInt(item?.openCount) ?? 1
}

/**
 * 纸面**抬头**：企业名 + 副标题（用户 2026-10-25 裁定照参考工单的
 * 「亿家纺织 / 成品定制」形态加抬头）。企业名缺值 ⇒ **整块不渲染**（不印空行、
 * 不印「未设置」—— 纸面是给客户看的）。
 */
export const WASH_LABEL_COMPANY_SUBTITLE = '成品定制'

export function washLabelCompanyName(companyName?: string | null): string {
  return typeof companyName === 'string' ? companyName.trim() : ''
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
  /** 纸面抬头：企业名（缺值 ⇒ 抬头块整块不渲染） */
  companyName?: string | null
  orderNo?: string | null
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

  // 🔴 订单号 = **第一行**（2026-10-26 用户逐字「把订单号放到第一行，客户那一行上面」）；
  // 缺值如实出 `—`（它是「这张纸是给谁的」的最小可读集合之一，不编造、也不留空行）。
  push('orderNo', (input.orderNo ?? '').trim() || '—', '订单')

  push('customer', input.customerName ?? '', '客户')

  const setNo = Number.isFinite(input.setNo) ? Number(input.setNo) : 1
  const setCount = Number.isFinite(input.setCount) ? Number(input.setCount) : 1
  push('setNo', `第 ${setNo} 套 / 共 ${setCount} 套`)

  push('positionKind', position.position_kind ?? '', '部位')

  // 🔴 商品名称（件名）**已退场**（issue #7776，用户 2026-10-25 逐字「移除商品名称展示」）：
  // 纸面改印「这一件用的是什么布」—— 颜色 / 门幅（+ 其余工艺信息），而不是商品名。
  // 原「色号已含在件名里 ⇒ 不重复渲染」的去重随件名一起退场：件名不在了，颜色必须**恒印**。
  const colorName = typeof input.item?.colorName === 'string' ? input.item.colorName.trim() : ''
  push('color', colorName, '颜色')

  // 门幅：快照落的是 SKU 原串（`2.8米` / `2.8` 两种形态都有）⇒ 只补单位、不改数值（缺值不渲染）
  const doorWidth = typeof input.item?.doorWidth === 'string' ? input.item.doorWidth.trim() : ''
  push('doorWidth', /^[0-9.]+$/.test(doorWidth) ? `${doorWidth}米` : doorWidth, '门幅')

  push('meters', washLabelMeters(input.item), '用料')
  push('size', washLabelSize(position.width, position.height), '宽高')
  push('craft', washLabelCraftMode(input.item), '加工方式')
  // 褶法 = 是否韩褶公式 + 折数（同一个字段；2026-10-26 用户裁定）
  push('pleats', washLabelPleats(input.item), '褶法')

  // 🔴 交期行**已退场**（2026-10-26 用户逐字「移除交期字段」）。
  push('specialOptions', washLabelSpecialOptions(input.item), '特殊选项')
  push('remark', washLabelRemark(input.item), '备注')

  // 🔴 算料公式（褶倍公式）**已退场**（issue #7776，用户 2026-10-25 逐字「移除褶倍公式字段展示」）。

  // 行序是纸面契约：即使某几行缺席，剩下的也必须按 `WASH_LABEL_ROW_KEYS` 排
  const order = new Map(WASH_LABEL_ROW_KEYS.map((key, index) => [key, index]))
  return rows.sort((a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0))
}

/** 直连通道一张标签要打的东西（= 有序行 + 底部二维码） */
export interface WashLabelInput {
  /** 二维码内容（该部位自己的 `scan_url ?? part_token`）；`null` ⇒ **不画假码**（出占位框） */
  qrValue: string | null
  /** 纸面抬头：企业名（缺值 ⇒ 抬头块整块不渲染；副标题见 {@link WASH_LABEL_COMPANY_SUBTITLE}） */
  companyName?: string
  /** 正文行（有序，来自 {@link washLabelRows}） */
  rows?: WashLabelRow[]
  /** 缺码时的占位文案（默认「待生成」） */
  qrPlaceholderHint?: string
}

export interface WashLabelSource {
  /** 纸面抬头的企业名（调用方从 `useCompanyName()` 取；缺值 ⇒ 抬头不渲染） */
  companyName?: string | null
  orderNo?: string | null
  customerName?: string | null
  positions?: ProductionPosition[] | null
  items?: ProcessingOrderItem[] | null
}

/**
 * 加工单 ⇒ 直连通道的**逐张**输入（**单一处**映射：页面与测试都走它，不各写一份）。
 *
 * - 码 = `scan_url ?? part_token`，两者都没有 ⇒ `null`（**不画假码**，与 `TaskCardPrint` 同口径）
 * - 套序走 `groupBySet`（与进度表 / 系统打印**同一份**实现）
 * - **份数 = 开数**（{@link washLabelCopies}）：双开商品 ⇒ 同一张纸出两份（与系统打印同一份口径）
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

  const labels: WashLabelInput[] = []
  positions.forEach((position, index) => {
    const item = position.order_item_id ? itemsById.get(position.order_item_id) : undefined
    const setView = setViews[index]
    const label: WashLabelInput = {
      qrValue: position.scan_url ?? position.part_token ?? null,
      companyName: washLabelCompanyName(source.companyName) || undefined,
      qrPlaceholderHint: undefined,
      rows: washLabelRows({
        position,
        item,
        setNo: (setView?.setIndex ?? 0) + 1,
        setCount: setView?.setCount ?? 1,
        customerName: source.customerName,
        orderNo: source.orderNo,
      }),
    }
    // 🔴 份数 = 开数（2026-10-26 用户裁定）：两条通道读**同一个**函数，不各算一份
    for (let copy = 0; copy < washLabelCopies(item); copy += 1) labels.push(label)
  })
  return labels
}
