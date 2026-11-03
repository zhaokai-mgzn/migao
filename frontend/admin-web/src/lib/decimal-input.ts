/**
 * 数字录入的统一口径（issue #8004）：**一处解析 + 一处校验 + 一处错误话术**。
 *
 * 病（issue #8004）：存量 `<input type="number">` 在**涉钱 / 涉数量**面会吞精度 ——
 * Chromium 对 `"0."` / `"12."` / `"."` / `"-"` 这类中间态按「非法浮点数」处理
 * （`el.value` 对 `"0."` 返回 `"0"`、对 `"."` 返回 `""`），千分位输入直接不认，
 * 受控回写即吞掉小数点或整段值 ⇒ 商家按错的价下单。
 *
 * 本模块是**唯一**解析/校验/话术实现，由 `frontend/admin-web/src/components/ui/DecimalInput.tsx`
 * 消费（组件只管草稿与上屏，不另写一份口径）。
 *
 * ## 解析口径（接受什么 / 拒绝什么 / 小数位 / 千分位）
 *
 * | 输入 | 结果 | 说明 |
 * |---|---|---|
 * | `1234.56` / `0.1` / `.5` / `0` | `ok` | 规范串 = 去尾随 0 的定点形态（`0.10` ⇒ `0.1`、`.5` ⇒ `0.5`） |
 * | `1,234.56` | `ok`（值 `1234.56`） | **只在千分位分组正确时**接受；`12,34` / `1,2` 不算完整值 |
 * | `12.` / `1,` | `draft`（打字中间态） | 原样留在框里、**不回调**；失焦时收尾成 `12` / `1` |
 * | `-` / `.` | `draft` | 同上；失焦仍解析不出 ⇒ 按 `not-a-number` 出声 |
 * | `12.345`（`decimals = 2`） | `invalid: too-many-decimals` | **拒绝，不替你四舍五入**（静默截断 = 静默改价） |
 * | `-1`（`min = 0`） | `invalid: below-min` | 负数一律拒绝（话术带下限） |
 * | `0`（`min = 0.01`） | `invalid: below-min` | 零按业务口径拒绝（如退款金额） |
 * | 超 `max` | `invalid: above-max` | 上限只在调用方给了 `max` 时才判（不自造业务上限） |
 * | `abc` / `1e3` / `12.3.4` | `invalid: not-a-number` | 指数写法**有意不支持**（`1e3` 在钱上是误输入） |
 * | 空串 | `empty` | 是否合法由调用方的 `allowEmpty` 决定 |
 *
 * 小数位：金额默认 **2**；带小数的数量（米数）由调用方显式给 `decimals`。
 * 数值域：`|v| < 1e15`（再大就超出本模块的定点形态，按 `not-a-number` 拒绝，不谎报）。
 */

/** 解析不出「完整合法值」的原因 —— 每条对应**一句具名话术**（`decimalMessage`） */
export type DecimalRejectReason =
  | 'not-a-number'
  | 'too-many-decimals'
  | 'below-min'
  | 'above-max'
  | 'empty'

export interface DecimalRules {
  /** 小数位上限（金额默认 2） */
  decimals: number
  /** 最小值（含）；金额默认 0 ⇒ 负数一律拒绝 */
  min: number
  /** 最大值（含）；不传 = 不设上限 */
  max?: number
}

/**
 * 一次解释的结果。四态**必须分清**（把 `draft` 读成 `invalid` 会在用户还在敲的时候就报错，
 * 把 `draft` 读成 `ok` 就是「静默变 0」）：
 * - `empty`：空串（还没填）
 * - `draft`：合法中间态（`12.` / `1,` / `-` / `.`）⇒ 原样留在框里，**不回调**
 * - `invalid`：填错了 ⇒ 出声 + 不回调（调用方的值保持上一个有效值）
 * - `ok`：完整合法值 ⇒ 回调 `canonical`
 */
export type DecimalInterpretation =
  | { state: 'empty' }
  | { state: 'draft' }
  | { state: 'invalid'; reason: DecimalRejectReason }
  | { state: 'ok'; value: number; canonical: string }

export const MONEY_RULES: DecimalRules = { decimals: 2, min: 0 }

/** 允许停留在输入框里的字符集（负号 / 逗号也放进来：解析要能把它们**说出来**，而不是静默吞键） */
const DRAFT_CHARS_RE = /^-?[0-9,]*(\.[0-9]*)?$/
/** 千分位分组（只对整数部分判；`1,234,567` 合法、`12,34` 不合法） */
const THOUSANDS_RE = /^\d{1,3}(,\d{3})+$/
/** 完整数值形态（`.5` 也算：用户从点开始敲是常见动作） */
const COMPLETE_RE = /^-?(?:\d+(?:\.\d*)?|\.\d+)$/
/** 本模块的定点数值域上限（再大就出指数形态，`toFixed` 会给出 `1e+21` 这种串） */
const MAX_ABS_VALUE = 1e15

const trimZeros = (s: string) => (s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s)

/** 规范串：去千分位 / 去尾随 0 的定点形态（`0.10` ⇒ `0.1`、`1234.56` ⇒ `1234.56`） */
function canonicalOf(value: number, decimals: number): string {
  return trimZeros(value.toFixed(decimals))
}

/**
 * 解释一次输入。
 *
 * @param raw 输入框里的原文
 * @param rules 小数位 / 下限 / 上限
 * @param opts.finalize 失焦收尾：把 `12.` / `1,` 这类「只差收尾」的中间态**收成完整值**；
 *   仍解析不出（`-` / `.`）⇒ `not-a-number`。**默认 false**（打字过程中不许把中间态判成错）
 */
export function interpretDecimal(
  raw: string,
  rules: DecimalRules,
  opts: { finalize?: boolean } = {}
): DecimalInterpretation {
  const finalize = opts.finalize === true
  const text = raw.trim()

  if (text === '') return { state: 'empty' }
  // 非法字符（字母 / 空格 / 第二个小数点 / 指数写法）：立刻出声，不静默忽略
  if (!DRAFT_CHARS_RE.test(text)) return { state: 'invalid', reason: 'not-a-number' }

  // 收尾：`12.` ⇒ `12`、`1,` ⇒ `1`（只在失焦时做 —— 打字时它是合法中间态）
  const body = finalize ? text.replace(/[.,]+$/, '') : text
  if (body === '' || body === '-' || body === '.') {
    return finalize ? { state: 'invalid', reason: 'not-a-number' } : { state: 'draft' }
  }
  // 打字中：尾随小数点 / 逗号 ⇒ 还在敲，不算错也不回调
  if (!finalize && /[.,]$/.test(body)) return { state: 'draft' }

  const [intPart, fracPart = ''] = body.split('.')
  if (intPart.includes(',') && !THOUSANDS_RE.test(intPart)) {
    // 千分位分组不成立：打字中当中间态（`1,2` 还会长），失焦后才算填错
    return finalize ? { state: 'invalid', reason: 'not-a-number' } : { state: 'draft' }
  }

  const clean = body.replace(/,/g, '')
  if (!COMPLETE_RE.test(clean)) return { state: 'invalid', reason: 'not-a-number' }

  const value = Number(clean)
  if (!Number.isFinite(value) || Math.abs(value) >= MAX_ABS_VALUE) {
    return { state: 'invalid', reason: 'not-a-number' }
  }
  // 小数位**按用户敲的位数**判（不是按数值判）：`12.30` 是 2 位、`12.345` 超了
  if (fracPart.length > Math.max(0, Math.trunc(rules.decimals))) {
    return { state: 'invalid', reason: 'too-many-decimals' }
  }
  if (value < rules.min) return { state: 'invalid', reason: 'below-min' }
  if (rules.max !== undefined && value > rules.max) return { state: 'invalid', reason: 'above-max' }

  return { state: 'ok', value, canonical: canonicalOf(value, rules.decimals) }
}

/**
 * 具名话术（**唯一**一份）。三条口径：
 * ① 只说「事实 + 该做什么」（`migao-dev-flow` §31 P4），不堆语气词、不加感叹号；
 * ② 每条都带**口径名**（调用方的 `field`）与**边界数字**，不写「输入有误」这种不可行动的话；
 * ③ 「不替你四舍五入」是**显式承诺**（与 `BatchStocktakeForm` 的既有话术同口径）：
 *    静默把 `12.345` 改成 `12.35` 就是静默改价，涉钱面不许。
 */
export function decimalMessage(
  reason: DecimalRejectReason,
  field: string,
  rules: DecimalRules
): string {
  switch (reason) {
    case 'not-a-number':
      return `${field}只能填数字（千分位逗号会自动去掉；不支持科学计数法）`
    case 'too-many-decimals':
      // `decimals = 0`（件数 / 卷数这类整数格）要说「只能填整数」，不能说「最多 0 位小数」
      return Math.trunc(rules.decimals) <= 0
        ? `${field}只能填整数（系统不会替你四舍五入）`
        : `${field}最多 ${Math.trunc(rules.decimals)} 位小数（系统不会替你四舍五入）`
    case 'below-min':
      return `${field}不能小于 ${canonicalOf(rules.min, Math.max(0, Math.trunc(rules.decimals)))}`
    case 'above-max':
      return `${field}不能超过 ${canonicalOf(rules.max ?? 0, Math.max(0, Math.trunc(rules.decimals)))}`
    case 'empty':
      return `请填写${field}`
  }
}

/**
 * 草稿的**上屏值**（失焦收尾用）：完整值 ⇒ 规范串；否则原样返回（用户敲的东西不许被改小）。
 * 这是「失焦归一化」的唯一实现 —— 只做**收尾**（去尾随小数点 / 千分位），
 * **不做**四舍五入、不做 `min`/`max` 夹紧（夹紧 = 静默改值）。
 */
export function finalizeDraft(raw: string, rules: DecimalRules): { text: string; result: DecimalInterpretation } {
  const result = interpretDecimal(raw, rules, { finalize: true })
  return { text: result.state === 'ok' ? result.canonical : raw.trim(), result }
}
