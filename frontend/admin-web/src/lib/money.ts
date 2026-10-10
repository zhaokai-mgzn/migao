/**
 * 涉钱读数的**唯一**展示口径（issue #6669 第 7 条）。
 *
 * ## 为什么要有这个文件
 *
 * 修前 admin-web 里同一类金额有**两套写法**：财务域 `¥123,456.78`（千分位 + 固定两位小数）、
 * 计件工资 `¥123456.78`（`toFixed(2)`，**无千分位**）—— 计件是工人和商家都盯着看的钱，
 * 同一笔钱在两个页面长得不一样，商家会怀疑系统算错了。
 * 更根本的问题是**两处实现各自维护**：改一处不改另一处就会重新分叉。
 * ⇒ 收敛到本文件一处真值，两侧都 import 它。
 *
 * ## 口径
 *
 * - **固定两位小数**（`minimumFractionDigits: 2`）—— 与财务域既有写法逐字一致；
 * - **千分位**（`toLocaleString('zh-CN')`）；
 * - `null` / `undefined` / 非有限数 ⇒ **空串**（由调用方决定「未定价」怎么表达，
 *   见 `docs/design` 的「未定价 ≠ ¥0.00」口径 —— 本函数**不**替调用方把缺失值说成 0）。
 *
 * 🔴 本函数**不判任何业务口径**（不算钱、不做四舍五入取舍）—— 它只负责「一个数怎么印」。
 */
export function money(value?: number | null): string {
  if (value === undefined || value === null) return ''
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 同 {@link money}，但缺失值印 `—`（表格单元格用；「没有数」不是「0 元」）。 */
export function moneyOrDash(value?: number | null): string {
  const s = money(value)
  return s || '—'
}
