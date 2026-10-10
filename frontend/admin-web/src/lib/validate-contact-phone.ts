/**
 * 官网「联系电话」口径（issue #6665 第 7 条）。
 *
 * 为什么单独成一个纯函数：原正则 `/^[\d\-+() ]{7,20}$/`（写在联系页表单组件里）只认**半角**
 * ⇒ 把两类真实 B 端号码判成「请输入有效的电话号码」：
 *   · `13800000000转123`（手机 + 分机）—— 正则不含 `转`；
 *   · `（0571）88886666`（全角括号总机）—— 正则不含全角括号。
 * 号码口径与 UI 形态无关（留言表单已按用户裁定隐藏，2026-10-10），所以判据留在纯函数上：
 * 表单重启（用户给出真实联系方式 / 留言接口上线）时直接复用，不用重写一遍校验。
 *
 * 处理顺序：① NFKC 归一（全角 → 半角）② 去掉分隔符（空格 / 连字符 / 括号）
 * ③ 分机号切开（`转` / `转接` / `#` / `x`）④ 判「主号位数 + 分机位数」。
 */

/** 主号最少位数（固话总机 7~8 位、手机 11 位、带国际前缀更长）。 */
const MIN_MAIN_DIGITS = 7
/** 主号最多位数（含 `+86` 这类国家码时的上限）。 */
const MAX_MAIN_DIGITS = 20
/** 分机号最多位数。 */
const MAX_EXT_DIGITS = 10

/** NFKC 归一：全角数字 / 括号 / 空格 / 加号统一成半角。 */
function toHalfWidth(value: string): string {
  return value.normalize('NFKC')
}

/** 分机号分隔符（`转` / `转接` / `#` / `x`）—— 取**第一个**命中处切开。 */
const EXT_SEPARATOR = /转接|转|#|x/i

/**
 * 解析出 {main, ext, hasExt}。
 * `hasExt` 与「ext 非空」分开记：**写了分隔符却没写分机号**（`13800000000转`）是笔误，必须判非法 ——
 * 若只看 ext 是否非空，切完空串就会静默退化成「主号合法」而放行。
 */
function parse(raw: string): { main: string; ext: string; hasExt: boolean } | null {
  const src = toHalfWidth(raw).trim()
  if (!src) return null
  const extIdx = src.search(EXT_SEPARATOR)
  const hasExt = extIdx >= 0
  const head = (hasExt ? src.slice(0, extIdx) : src).replace(/^#+/, '')
  const tail = hasExt ? src.slice(extIdx).replace(EXT_SEPARATOR, '') : ''
  const main = head.replace(/[\s()\-]/g, '')
  // 允许的字符集封闭：主号只允许数字 / 前导 +；分机号只允许数字
  if (!/^\+?[0-9]*$/.test(main) || !/^[0-9]*$/.test(tail)) return null
  return { main: main.replace(/^\+/, ''), ext: tail, hasExt }
}

/**
 * 归一化成「可落库的规范形态」：`13800000000.123`（有分机）/ `13800000000`（无分机）/
 * 非法输入返回空串。不修改传入值。
 */
export function normalizeContactPhone(raw: string): string {
  if (typeof raw !== 'string') return ''
  const parsed = parse(raw)
  if (!parsed) return ''
  return parsed.hasExt ? `${parsed.main}.${parsed.ext}` : parsed.main
}

/** 是否是企业会真实使用 / 收到的联系电话形态。 */
export function isValidContactPhone(raw: string): boolean {
  if (typeof raw !== 'string') return false
  const parsed = parse(raw)
  if (!parsed) return false
  const { main, ext, hasExt } = parsed
  if (main.length < MIN_MAIN_DIGITS || main.length > MAX_MAIN_DIGITS) return false
  if (hasExt) {
    if (!ext) return false // `13800000000转` —— 写了分机分隔符却没有分机号
    if (ext.length > MAX_EXT_DIGITS) return false
  }
  return true
}
