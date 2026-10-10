/**
 * 枚举「显示名」的**唯一出口**（issue #6668 盲区①）。
 *
 * ## 病灶（为什么不能写 `LABELS[x] || x`）
 *
 * 服务端新增一个枚举值（`finance` 加一种支付方式、`production` 加一种报废原因）时，
 * 前端查表**查不到** —— 而 `LABELS[x] || x` 的兜底是**原始标识**：
 * 商家看见的是 `wechat_pay_v2` / `a61daac3-…` 这种机器值，不是人话。
 * 这类形态还有一个更隐蔽的性质：**源码字面量扫描器扫不到**（左半边是变量），
 * 静态守卫也扫不到（整个表达式是二元运算，不是纯成员链）⇒ 它落在两张网中间，
 * 一直到现在都**没有任何东西会因此变红**（判据 = `frontend/admin-web/scripts/enum-fallback-scan.mjs`）。
 *
 * ## 口径
 *
 * 1. **未知值 ⇒ 人话兜底**（`其他` 一类），**绝不回显入参**；
 * 2. 入参缺失 / 空白 ⇒ 走**调用方给的空值文案**（默认 `—`，与表格单元格口径一致：
 *    「没有值」不是「其他」）；
 * 3. 已登记的映射值**逐字返回**（不受兜底影响）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 本模块**不判业务**：不决定某个值该怎么叫（那是各域词典的事）；
 * - 它只保证**出口安全**：调用方拿不到「入参本身」。把 `LABELS[x] || x` 换成
 *   `displayEnum(LABELS, x)` 是**语义不变**的改动（已知值一模一样），
 *   变的只有未命中时的那个字符串 —— 这正是修复形态。
 */

export type EnumLabelMap = Record<string, string | undefined>

/** 未知枚举值的**默认人话兜底**（中性、不撒谎、不暴露机器值） */
export const ENUM_UNKNOWN_LABEL = '其他'

/** 缺值（`''` / `null` / `undefined` / 纯空白）的默认文案 —— 与表格单元格口径一致 */
export const ENUM_EMPTY_LABEL = '—'

/**
 * 服务端枚举标识 → 显示名。
 *
 * @param labels 该域的**显示名字典**（键 = 服务端标识）
 * @param value 服务端下发的标识（可能是本前端还不认识的新值）
 * @param fallback 未知值的人话兜底（默认 `其他`）
 * @param emptyLabel 缺值文案（默认 `—`）
 */
export function displayEnum(
  labels: EnumLabelMap,
  value: string | null | undefined,
  fallback: string = ENUM_UNKNOWN_LABEL,
  emptyLabel: string = ENUM_EMPTY_LABEL,
): string {
  const key = typeof value === 'string' ? value.trim() : ''
  if (key === '') return emptyLabel
  const hit = labels[key]
  if (typeof hit === 'string' && hit.trim() !== '') return hit
  return fallback
}
