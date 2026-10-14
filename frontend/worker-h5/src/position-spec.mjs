// case_ids: PG-046, PG-018
//
// 工人端**部位规格**的标签 / 单位 / 格式化口径 —— **唯一一份**（母单 #6901，面①）。
//
// 为什么要有这个模块（issue #6901 的病灶形态）：工人端有两屏都在展示「这个部位是什么规格」——
//   屏 A = 扫后报工屏（`src/render.mjs`，数据 = 服务端 `set_overview.positions[]`，**snake_case** 键）
//   屏 B = 机台屏一 订单详情（`src/machine.mjs::detailRows`，数据 = `/api/worker/production/cutting-height`
//          的 `positions[]`，**同一套 snake_case 键** + 机台自己的 `brand` / `cutting_height` …）
// 两屏各写一份标签表 = 第二份口径（「实际褶倍」一屏叫 X、另一屏叫 Y；一处改成整数、另一处仍是三位小数）
// —— 漂移的那一份**不会变红**（本仓库反复复发的形态）。
// ⇒ 标签 / 单位 / 格式化只在本模块写一次，两屏都调它。
//
// 🔴 数值形态是**机台屏的既有真值**（`fmtNumber` 三位小数 · `EMPTY = '—'`），本模块**逐字搬用**、
//    不为了让报工屏好看而改动机台屏的读数（2026-10-14 集成侧硬要求）。
//
// 🔴 缺值两条口径**分开**（都是既有口径，不要合并）：
//    · 机台屏（`kvRows`）：缺值渲染 `—`（给机器旁的人「这一格没填」的显式读数）；
//    · 报工屏（`specRows`）：缺值**不渲染该行**（工人手机上不摆空占位）。
//    两者共用同一份**标签/单位**，差别只在「缺值怎么呈现」——这是**有意**的两态，不是两份口径。

/** 缺值显示（**显式**：缺就显示这个，绝不猜 0 —— 给机器的值偏小 = 裁短 = 事故）。 */
export const EMPTY = '—'

/** 机器屏精度（三位小数 = mm；服务端 `rounding.digits` 是唯一真值，这里只是渲染兜底）。 */
export const DEFAULT_DIGITS = 3

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

/** HTML 转义（本模块自用；`render.mjs` / `machine.mjs` 各自的 `esc` 语义逐字相同）。 */
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c])

/** 数值 → 固定位数文本；`null` / 非数 ⇒ {@link EMPTY}（不显示 0）。 */
export function fmtNumber(value, digits = DEFAULT_DIGITS) {
  if (value === null || value === undefined || value === '') return EMPTY
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : EMPTY
}

/** 缺值兜底：空串 / null / undefined ⇒ {@link EMPTY}。 */
export function dataOr(value) {
  if (value === null || value === undefined) return EMPTY
  const text = String(value).trim()
  return text === '' ? EMPTY : text
}

/**
 * 一个规格键的展示口径。
 *
 * @typedef {object} PositionSpecKey
 * @property {string} key    wire 键名（**snake_case**，与服务端 `getOperations.positions[]` 逐字同名）
 * @property {string} label  屏上标签
 * @property {string} [unit] 单位（缺值不显示单位）
 * @property {'raw'|'m'|'number'|'int'|'bool'} [format] 数值呈现口径（缺省 `raw`）
 */

/** @type {PositionSpecKey[]} */
export const POSITION_SPEC_KEYS = [
  // ── 组 1 商品身份 ──
  { key: 'product_name', label: '商品名称' },
  { key: 'sku', label: '货号' },
  { key: 'color_name', label: '颜色' },
  { key: 'door_width', label: '门幅' },
  { key: 'selling_method', label: '售卖方式' },
  { key: 'unit', label: '数量单位' },
  // ── 组 2 规格尺寸 ──
  { key: 'width', label: '宽', unit: '米', format: 'm' },
  { key: 'height', label: '高', unit: '米', format: 'm' },
  // ── 组 3 加工信息 ──
  { key: 'curtain_type', label: '部位' },
  { key: 'craft', label: '安装工艺' },
  { key: 'cutting_mode', label: '加工类型' },
  { key: 'open_count', label: '开数', format: 'int' },
  { key: 'is_shaped', label: '是否定型', format: 'bool' },
  { key: 'style', label: '款式' },
  { key: 'fullness', label: '理论褶倍', unit: '倍', format: 'number' },
  { key: 'fullness_actual', label: '实际褶倍', unit: '倍', format: 'number' },
  { key: 'pleat_count', label: '总褶数', format: 'int' },
  { key: 'per_panel_pleats', label: '每片褶数', format: 'int' },
  { key: 'panels', label: '幅数', format: 'int' },
  { key: 'has_pattern', label: '是否对花', format: 'bool' },
  { key: 'pattern_repeat', label: '花距', format: 'number' },
  { key: 'formula', label: '用料公式' },
  { key: 'craft_tier', label: '算料档位' },
  { key: 'special_options', label: '特殊选项' },
  // ── 组 4 算料 / 排料 ──
  { key: 'fabric_meters', label: '面料米数', unit: '米', format: 'm' },
  { key: 'processing_meters', label: '加工费米数', unit: '米', format: 'm' },
  { key: 'formula_text', label: '算料公式' },
  // ── 组 5 派工 ──
  { key: 'batch_no', label: '批号' },
  { key: 'batch_meters', label: '指派米数', unit: '米', format: 'm' },
  { key: 'component_role', label: '组件' },
  // ── 组 6 部位备注（issue #5685；机台面用 `position_remark` 这个键名，本表按扫码面口径登记）──
  { key: 'remark', label: '部位备注' },
]

/** `m` 是**机器精度**（三位小数）的别名 —— 机台屏的既有读数，不得改成两位。 */
const digitsOfFormat = (format) => (format === 'm' ? DEFAULT_DIGITS : null)

/**
 * 一个值按口径 → 屏上文本；**缺值 ⇒ {@link EMPTY}**（绝不出 `undefined` / `null` / `NaN`）。
 *
 * <p>数值路径**先判数值再格式化**（同机台屏 `kvRows` 的判据）：`"2.5"` 这类字符串照旧按数字显示，
 * `'定高买宽'` 这类非数文本原样显示（不折成 `NaN`）。</p>
 */
export function formatSpecValue(value, format) {
  if (value === null || value === undefined) return EMPTY
  if (format === 'bool') return value === true ? '是' : value === false ? '否' : EMPTY
  if (value !== '' && Number.isFinite(Number(value))) {
    if (format === 'int') return String(Math.trunc(Number(value)))
    if (format === 'm') return fmtNumber(value, DEFAULT_DIGITS)
    if (format === 'number') return String(Number(value))
    return String(Number(value))
  }
  return dataOr(value)
}

/**
 * **报工屏的「本部位生产信息」块不渲染**的键（母单 #6901）。
 *
 * <p>本表仍**登记**它们（后端 {@code PositionDetailFields.DETAIL_KEYS} 里有，后端守卫要求本表 ⊇ 那份
 * 键集 ⇒ 缺一个就红），只是**这一块不重复上屏**：</p>
 * <ul>
 *   <li>{@code remark}（部位备注）—— 工人端另有一条**更精确**的呈现（`render.mjs::positionRemark`：
 *       「部位备注：<原文>」紧跟**它自己那个部位**的标题，issue #5685 的既有判据逐字钉住）。
 *       在规格块里再印一遍 = 同一屏同一事实两次（`migao-dev-flow` §31 P2）。</li>
 * </ul>
 */
export const SCAN_BLOCK_EXCLUDED_KEYS = new Set(['remark'])

/**
 * 一个部位 → **报工屏**的行（缺值**不渲染**：整行不出现 ⇒ 工人手机上不摆空占位）。
 *
 * <p>键集 = **本表**（{@link POSITION_SPEC_KEYS}，白名单驱动）—— 服务端 `set_overview.positions[]`
 * 里本表没登记的键**不上屏**：上屏得给它一个人话标签，而「不知道它的人话名」时只能印原始键名
 * ⇒ 内部标识上工人屏（`migao-dev-flow` §31 P3 明令禁止）。</p>
 *
 * <p>🔴 <b>但「没登记」不会静默漏掉</b>：服务端给 `positions[]` 追加新规格键而本表没跟上 ⇒
 * 判据**变红**（后端 `backend/admin-api/src/test/java/com/migao/admin/service/PositionDetailFieldsTest.java`
 * 拿**真源**的键集逐键比对本表 ⇒ 未登记即红）。这是本单要治的「加了一个字段，某一屏静默缺失」的收口。</p>
 *
 * @param {object} position 服务端下发的部位对象（snake_case 键）
 * @returns {{key: string, label: string, text: string}[]}
 */
export function specRows(position) {
  const rows = []
  for (const spec of POSITION_SPEC_KEYS) {
    if (SCAN_BLOCK_EXCLUDED_KEYS.has(spec.key)) continue
    const shown = formatSpecValue(position?.[spec.key], spec.format)
    if (shown === EMPTY) continue
    rows.push({ key: spec.key, label: spec.label, text: `${shown}${spec.unit ?? ''}` })
  }
  // ⚠️ **未知键不上屏、也不静默消失**：服务端将来给 `positions[]` 追加新规格键时，两屏都**不会**显示它，
  // 但**判据会红**（`tests/worker-h5-position-spec.test.mjs` 拿真实服务端键集逐键比对本表 ⇒
  // 「未登记即红」）。这是**有意**取舍：宁可让工人看到一个「占位不明的原始键名」之前先让 CI 说话
  // —— 上屏内部键名违反产品口径（`migao-dev-flow` §31 P3 不摆内部标识）。
  return rows
}

/**
 * 裁高值取整位数（服务端 `rounding.digits`；缺 ⇒ 三位小数 —— 机器屏口径）。
 *
 * <p>原在 `machine.mjs`，随本模块搬迁：它读的 `rounding` 是**机台屏**的位置块，不属规格表；
 * 放这里只为让两屏共用同一份 `DEFAULT_DIGITS`（不新增第二份默认值）。</p>
 */
export function digitsOf(position) {
  const digits = Number(position?.rounding?.digits)
  return Number.isInteger(digits) && digits >= 0 && digits <= 3 ? digits : DEFAULT_DIGITS
}
