/**
 * 「商家在文字框里**明说的硬事实**」的确定性解析（issue #7528）。
 *
 * ## 它解决什么
 *
 * 建品页「拍照 / 上传识别」旁边那个**补充一句**输入框，原先只喂给一次性推理
 * （`backend/ai-agent-service/app/vision/interpret.py`），而那条链路的提示词逐字写着
 * 「它**只当上下文**，不得改变输出格式与铁律」⇒ 商家写的
 * 「货号是 2659，颜色格式是 2659-序号+颜色名，门幅是 2.8 和 3.2」**一个字都落不进表单**：
 * 货号不在识别字段表里、门幅被「推理值不落值」的铁律挡着、颜色命名规则没有落点。
 *
 * ⇒ 本模块把这类**字面事实**从模型链路里**摘出来**，用**确定性窄模式**解析（零 LLM、零网络），
 * 产出第三来源 `[商家填写]`（与 `[图片识别]` 抄的、`[米宝解读]` 推的**都不同**）。
 *
 * ## 三条口径（issue #7528 用户裁定）
 *
 * 1. **只认三类显式说法**：`货号/款号/商品编号 …`、`门幅/幅宽/门宽 …`、`颜色格式/命名 …`；
 *    没有这些关键词的数字串（「这款有 2659 个颜色」）**一格都不产**（宁可少填，不猜）。
 * 2. 🔴 **模型推理填门幅/售价的铁律不动**：本模块是**表单层**的解析，后端契约与
 *    `deep_channel.INTERPRETABLE_KEYS` 白名单**零改动** —— 计划里依旧不会有模型推的门幅值。
 * 3. **不覆盖图上抄到的值**：合并规则在卡片侧（`FormInterpretCard`）——`[图片识别]` 已有值就不动；
 *    `[米宝解读]` 的推断值可被商家明说的字面事实覆盖（人写的 > 模型推的）。
 */
import { SPEC_EN_TO_CN } from './attribute-keys'
import { colorNamesOf, doorWidthsOf } from './image-recognize'
import { COLOR_NAME_MAX } from './product-limits'
import { CUSTOM_OPTION_VALUE, SPEC_ATTRIBUTE_GROUPS } from './product-attribute-options'
import { DOOR_WIDTH_OPTIONS } from './sku-utils'

/** 第三来源标记：**商家在文字里明说的**（区别于「从图上抄的」与「模型推的」） */
export const DECLARED_SOURCE_TAG = '[商家填写]'

/** 「货号 … 2659」——`是 / 为 / 叫 / 冒号` 可有可无；值只吃字母数字与 `-` `_`（到中文或标点即止） */
const CODE_RE = /(?:货号|款号|商品编号)\s*(?:是|为|叫|[:：=])?\s*([A-Za-z0-9][A-Za-z0-9_-]{0,29})/i

/** 「门幅是 2.8 和 3.2」——尾部只吃数字 / 分隔符 / `米`，遇到中文词语即止 */
const WIDTH_RE =
  /(?:门幅|幅宽|门宽)\s*(?:是|为|有|[:：=])?\s*([0-9][0-9.,，、/;；和与及~\-米mM\s]*)/i

/** 「颜色格式 / 颜色命名 / 颜色名称格式 / 颜色规则 …」 */
const COLOR_RULE_RE = /颜色(?:的)?(?:格式|命名|名称格式|命名规则|规则|前缀|编号)/

/** 没有「格式/命名」字样时，仍可能是模板：「颜色」+「序号」+「颜色名」（逐字：`2659-序号+颜色名`） */
const COLOR_TEMPLATE_HINT_RE = /序号/

/** 模板里自带的货号：`颜色格式是 2659-序号+颜色名`（没写货号时靠它） */
const COLOR_TEMPLATE_CODE_RE =
  /颜色[^，。；\n]{0,24}?([A-Za-z0-9][A-Za-z0-9_-]{0,29})\s*[-－—_]\s*序号/

/** 门幅的合理区间（米）——超出即不认（`0.5~10`），避免把「20 个色号」当成门幅 */
const WIDTH_MIN = 0.5
const WIDTH_MAX = 10

/**
 * 否定前缀：`不要提花` / `无需遮光` / `非印花` 不计入属性。
 *
 * 只看命中位置**之前最多两个字**（`不要 / 不用 / 无需 / 没有 / 不是 …`）—— 更长就退化成
 * 语法解析，那属于模型的事，而模型那条路径**不许**给这些格填值（本解析器刻意保持极窄）。
 */
const NEGATION_PREFIX = /(?:不要|不用|无需|不需|没有|不是|并非|非|无|不|免|没)$/

/** 颜色命名规则：`<货号>-<序号><颜色名>`（序号 1 起、不补零） */
export interface DeclaredColorRule {
  code: string
}

/** 一个规格属性（`key` = 表单内部英文 key） */
export interface DeclaredAttribute {
  key: string
  value: string
}

/** 从那句文字里解析出的全部字面事实（空串 / 空数组 = 没声明） */
export interface DeclaredFacts {
  skuCode: string
  doorWidths: string[]
  colorRule: DeclaredColorRule | null
  attributes: DeclaredAttribute[]
}

/** 一格「商家填写」（卡片渲染 + 合并进字段计划的中间形状；不含来源，来源由卡片侧统一挂） */
export interface DeclaredCell {
  key: string
  label: string
  value: string
  reason: string
}

/** 解析那句话（纯函数；文本为空 ⇒ 全空，不抛异常） */
export function parseDeclaredFacts(hint: string | null | undefined): DeclaredFacts {
  const text = typeof hint === 'string' ? hint.trim() : ''
  if (!text) return { skuCode: '', doorWidths: [], colorRule: null, attributes: [] }
  const skuCode = codeOf(text)
  return {
    skuCode,
    doorWidths: widthsOf(text),
    colorRule: colorRuleOf(text, skuCode),
    attributes: attributesOf(text),
  }
}

/** 货号：只认 `货号/款号/商品编号` 关键词之后的那一段 */
export function codeOf(text: string): string {
  const hit = CODE_RE.exec(text)
  return hit ? hit[1] : ''
}

/** 门幅：关键词之后的数字串 → 去重 + 区间校验 + 最多 `DOOR_WIDTH_OPTIONS.length` 根 */
export function widthsOf(text: string): string[] {
  const hit = WIDTH_RE.exec(text)
  if (!hit) return []
  // 拆多值 / 归一 `2.8米` → `2.8` 走**既有实现**（与识别预填同一份口径，不另写一份）
  const candidates = doorWidthsOf(hit[1])
  const widths: string[] = []
  for (const width of candidates) {
    const n = Number(width)
    if (!Number.isFinite(n) || n < WIDTH_MIN || n > WIDTH_MAX) continue
    widths.push(width)
    if (widths.length >= DOOR_WIDTH_OPTIONS.length) break
  }
  return widths
}

/** 颜色命名规则：得先有「颜色 + 格式/命名」这类说法，且能拿到一个货号 */
export function colorRuleOf(text: string, skuCode: string): DeclaredColorRule | null {
  if (!text.includes('颜色')) return null
  const declared = COLOR_RULE_RE.test(text) || COLOR_TEMPLATE_HINT_RE.test(text)
  if (!declared) return null
  const code = skuCode || (COLOR_TEMPLATE_CODE_RE.exec(text)?.[1] ?? '')
  return code ? { code } : null
}

/** 规格属性：命中内置选项即选中（组内取第一个命中项；单字选项不参与，中文里太易误命中） */
export function attributesOf(text: string): DeclaredAttribute[] {
  const found: DeclaredAttribute[] = []
  for (const group of SPEC_ATTRIBUTE_GROUPS) {
    for (const option of group.options) {
      const value = option.value
      if (!value || value === CUSTOM_OPTION_VALUE || value.length < 2) continue
      if (!affirmedIndexOf(text, value)) continue
      found.push({ key: group.key, value })
      break
    }
  }
  return found
}

/**
 * 这段话里是否**肯定地**提到了某个值（`true` = 出现且前面不是否定词）。
 *
 * 只做「前一个字」的否定判断（`不要提花` / `非印花`）—— 更复杂的语义解析属于模型的事，
 * 而模型那条路径**不允许**给这些格填值（本模块刻意保持极窄）。
 */
function affirmedIndexOf(text: string, value: string): boolean {
  let from = 0
  for (;;) {
    const index = text.indexOf(value, from)
    if (index < 0) return false
    const before = text.slice(Math.max(0, index - 2), index)
    if (!NEGATION_PREFIX.test(before)) return true
    from = index + value.length
  }
}

/** 解析结果 → 可合并进字段计划的格子（顺序：货号 / 门幅 / 规格属性） */
export function declaredCellsOf(facts: DeclaredFacts): DeclaredCell[] {
  const cells: DeclaredCell[] = []
  if (facts.skuCode) {
    cells.push({
      key: 'sku_code',
      label: '货号',
      value: facts.skuCode,
      reason: `按你写的「货号 ${facts.skuCode}」`,
    })
  }
  if (facts.doorWidths.length > 0) {
    cells.push({
      key: 'door_width',
      label: '门幅',
      value: facts.doorWidths.join('、'),
      reason: `按你写的门幅 ${facts.doorWidths.join('、')}`,
    })
  }
  for (const attribute of facts.attributes) {
    // 🔴 第二道闸：只认登记过的规格属性键（`SPEC_EN_TO_CN`）。售价 / 门幅之外的任何键都不从这里出 ——
    // 涉钱面不许被「一句话」带进表单（判据见 `tests/unit/lib/declared-facts.test.ts` 的类级守卫）。
    if (!Object.prototype.hasOwnProperty.call(SPEC_EN_TO_CN, attribute.key)) continue
    cells.push({
      key: attribute.key,
      label: SPEC_EN_TO_CN[attribute.key],
      value: attribute.value,
      reason: `按你写的「${attribute.value}」`,
    })
  }
  return cells
}

/**
 * 按命名规则改写**识别到的颜色串**（`01米白、02雾霾蓝` → `2659-1米白、2659-2雾霾蓝`）。
 *
 * 序号 **1 起、不补零**，并**丢掉图上原有的序号**（用户 2026-10-23 裁定）。
 * `null` = 不改（没给规则 / 没有颜色 / 有任何一个颜色改名后超过输入框上限 ——
 * 超长会被 `maxLength` **静默削断**，那比不改更糟：留下一条半截颜色名）。
 */
export function renamedColorValue(
  raw: string,
  rule: DeclaredColorRule | null,
): string | null {
  if (!rule || !raw) return null
  const names = colorNamesOf(raw)
  if (names.length === 0) return null
  const renamed: string[] = []
  for (let index = 0; index < names.length; index += 1) {
    const next = `${rule.code}-${index + 1}${baseColorName(names[index], rule.code)}`
    if (Array.from(next).length > COLOR_NAME_MAX) return null
    renamed.push(next)
  }
  return renamed.join('、')
}

/**
 * 颜色名去掉**货号前缀**与**图上原序号**（`2659-01米白` / `01米白` → `米白`）。
 *
 * 幂等：同一串上跑两次结果相同（改名后再改不会叠成 `2659-1-1米白`）。
 */
export function baseColorName(name: string, code: string): string {
  let base = name.trim()
  if (code && base.startsWith(`${code}-`)) base = base.slice(code.length + 1)
  const stripped = base.replace(/^0*\d+\s*[-_、.．:：]?\s*/, '').trim()
  return stripped || base
}

export const __testing = { COLOR_RULE_RE, COLOR_TEMPLATE_CODE_RE, WIDTH_RE, CODE_RE }
