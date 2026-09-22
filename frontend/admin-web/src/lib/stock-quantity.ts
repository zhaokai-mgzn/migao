/**
 * 库存数量口径的**前端单一真值**（issue #5063：库存米数小数化，0.1 米粒度；
 * issue #5153：下限由「≥1 米」放宽为「> 0 米」）。
 *
 * 后端已把库存/数量列升到 `NUMERIC(12,1)`，admin-api 的入库校验是
 * 「**> 0 米**且**最多 1 位小数**」。前端必须与后端**同一判据**，否则会出现两种坏形态：
 *   ① 前端比后端松 ⇒ 用户白填一遍，到提交才 400；
 *   ② 前端比后端紧 ⇒ 合法的数值被挡在门外（用户裁定「不能损失客户」）。
 *
 * 🔴 **② 的真实受害形态就是 0.5 米的尾料**（issue #5153 / GAP-12）：用户逐字说
 * 「当前企业剩余了**大量的 0.5 米左右**的批次布料」，而改前前后端都写着 `≥1`
 * ⇒ 这些实物批次**连登记都进不来**（挡在门外 = 看不见 = 假真值）。
 * 下限与粒度是**同一个判据的两半**：`> 0` 加上「最多 1 位小数」⇒ 合法值恒 `≥ 0.1` 米
 * ⇒ 这里**不写** `0.1` 这个字面量下限（写了就是第二处口径，迟早漂移）。
 *
 * 铁律：**不静默取整 / 不截断** —— 超过 1 位小数一律**显式拒绝**（fail-closed）。
 * 静默把 2.755 收成 2.8 会让账面库存与实物对不上，而库存是照米数对账的。
 *
 * 纯函数（不读 state、不发请求），单测直接断言：
 *   tests/unit/lib/stock-quantity.test.ts（case_ids: PR-046, PR-048, PR-061）
 */

/** 拒绝时给用户看的话（页面接在「<行名>的」后面直接 toast）。**可行动**：说清下限、位数与例子。 */
export const STOCK_QUANTITY_RULE =
  '数量必须大于 0，最多 1 位小数（库存按 0.1 米粒度记：0.5 米的尾料可以、0 与 2.755 不行）'

/**
 * 小数位数。**先按字符串数**，取不到才回退数值判定 —— 因为：
 *   `0.1 * 10 === 1.0000000000000002`、`2.7 * 10 === 27.000000000000004`，
 * 直接拿 `n * 10` 判会把**合法的一位小数**误杀（浮点噪声不是用户填错）；
 * 而字符串里的小数位正是用户**真正敲进去**的位数，没有二进制噪声。
 */
function decimalPlaces(text: string): number {
  const plain = /^[+-]?(\d+)?(?:\.(\d+))?$/.exec(text)
  if (plain && (plain[1] || plain[2])) return (plain[2] ?? '').length
  // 科学计数法（`1.5e2` / `1e-1`）：字符串里看不出「小数点后几位」⇒ 回退 `Number.isInteger(n * 10)`
  return Number.isInteger(Number(text) * 10) ? 1 : 2
}

/**
 * 判一个库存数量输入能否提交。
 *
 * 下限 = **大于 0**（issue #5153 起；改前是 `≥1`，把 0.5 米的尾料挡在门外）。
 * 粒度 = 最多 1 位小数（**没有**因为放宽下限而放宽）。
 *
 * @returns `null` = 通过；否则 = 拒绝原因（**可直接展示**给用户）。
 */
export function checkStockQuantity(raw: string | number): string | null {
  const text = (typeof raw === 'string' ? raw : String(raw)).trim()
  if (text === '') return STOCK_QUANTITY_RULE
  const n = Number(text)
  // `!(n > 0)` 而非 `n <= 0`：NaN 也要走拒绝分支（`NaN <= 0` 是 false，会漏过去）
  if (!Number.isFinite(n) || !(n > 0)) return STOCK_QUANTITY_RULE
  return decimalPlaces(text) > 1 ? STOCK_QUANTITY_RULE : null
}

/**
 * 展示口径：最多 1 位小数、去掉尾随 `.0`（`60.5` → `"60.5"`、`10` → `"10"`、`null` → `"-"`）。
 * 直接把原值渲染会把浮点毛刺（`2.7000000000000002`）打到屏幕上，商家会以为系统算错了。
 */
export function formatStockQuantity(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-'
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return '-'
  return String(Math.round(n * 10) / 10)
}
