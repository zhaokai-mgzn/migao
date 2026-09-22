// case_ids: PR-046, PR-048
//
// 库存数量口径的**纯函数**单测（issue #5063：库存米数小数化，0.1 米粒度）。
//   本文件直接断言 `src/lib/stock-quantity.ts`，不经页面 —— 判据的**唯一真值**在这里，
//   页面（tests/unit/pages/inbound-orders-decimal.test.tsx）只验证它被接进了提交前校验。
//   PR-045 = 库存米数支持 1 位小数（入库 60.5 米被接受）；PR-047 = 超 1 位小数显式拒绝（fail-closed）。
import { describe, it, expect } from 'vitest'
import { checkStockQuantity, formatStockQuantity, STOCK_QUANTITY_RULE } from '@/lib/stock-quantity'

describe('checkStockQuantity —— ≥1 且最多 1 位小数（PR-045 / PR-047）', () => {
  // PR-045：1 位小数（含小数部分为 0 的整数）必须通过 —— 这是本单的**新增能力**，
  // 改前判据是 `Number.isInteger(q)`，这几条会全红。
  it.each([
    ['60.5 米（用户裁定里点名的例子）', '60.5'],
    ['10（整数，逐值不变）', '10'],
    ['2.7', '2.7'],
    ['1', '1'],
    ['8.7（8.7 * 10 = 87.00000000000001 的浮点陷阱值）', '8.7'],
    ['1.1', '1.1'],
    ['60.5（数值入参，不是字符串）', 60.5],
    ['2.7（数值入参）', 2.7],
    ['10（数值入参）', 10],
    ['1.5e2 = 150（科学计数法，走数值回退判定）', '1.5e2'],
    ['1.55e1 = 15.5（科学计数法 + 1 位小数）', '1.55e1'],
    ['999.9（三位整数 + 1 位小数，位数判据不看整数部分）', '999.9'],
    // ⚠️ `2.7000000000000002` 这个**字面量就是 double 2.7**（`=== 2.7` 为 true，最短表示就是 "2.7"）
    //    ⇒ 它本身是合法的一位小数，**必须通过**。「毛刺」那一面见下面拒绝组里的 `1.1 + 2.2`。
    ['2.7000000000000002（= double 2.7，最短表示 "2.7"）', 2.7000000000000002],
  ])('%s ⇒ 通过（null）', (_name, value) => {
    expect(checkStockQuantity(value)).toBeNull()
  })

  // PR-047：超过 1 位小数 ⇒ **显式拒绝**（fail-closed），文案必须说清位数与粒度，
  // 且**不得**静默取整（取整的判定会返回 null = 放行 ⇒ 这条必红）。
  it.each([
    ['2.755', '2.755'],
    ['1.05', '1.05'],
    ['1.25', '1.25'],
    ['12.34', '12.34'],
    ['2.755（数值入参）', 2.755],
    ['1.055e1 = 10.55（科学计数法 + 2 位小数）', '1.055e1'],
    // 真正的浮点毛刺（`0.1 + 0.3` 家族）：最短表示 16 位小数 ⇒ 字符串判据拒绝它。
    // ⚠️ 这条同时是「为什么必须**先按字符串**判」的证据：`3.3000000000000003 * 10 === 33` 恰好是整数，
    //    只按 `Number.isInteger(n * 10)` 判会把它当合法的一位小数放行。
    ['1.1 + 2.2 = 3.3000000000000003（浮点毛刺）', 1.1 + 2.2],
  ])('%s ⇒ 拒绝，且文案可行动（含「1 位小数」）', (_name, value) => {
    const reason = checkStockQuantity(value)
    expect(reason).toBe(STOCK_QUANTITY_RULE)
    expect(reason).toContain('1 位小数')
    expect(reason).toContain('≥1')
  })

  // 下限仍是 ≥1（本单只放开小数位，不放宽下限）—— 删掉下限判据这条必红。
  it.each([
    ['0.5（一位小数但不足 1 米）', '0.5'],
    ['0.1（浮点陷阱值：0.1 * 10 = 1.0000000000000002，仍须因 < 1 被拒）', '0.1'],
    ['0', '0'],
    ['0（数值入参）', 0],
    ['-1', '-1'],
  ])('%s ⇒ 拒绝', (_name, value) => {
    expect(checkStockQuantity(value)).toBe(STOCK_QUANTITY_RULE)
  })

  it.each([
    ['空字符串（未填）', ''],
    ['只有空格', '   '],
    ['非数字', 'abc'],
    ['NaN 数值', NaN],
    ['Infinity', Infinity],
  ])('%s ⇒ 拒绝（不能拿 NaN 去建单）', (_name, value) => {
    expect(checkStockQuantity(value)).toBe(STOCK_QUANTITY_RULE)
  })
})

describe('formatStockQuantity —— 最多 1 位小数、去尾随 .0（PR-045）', () => {
  it.each([
    ['60.5', 60.5, '60.5'],
    ['10（整数逐值不变）', 10, '10'],
    ['2.7000000000000002（= double 2.7 ⇒ 干净渲染 2.7）', 2.7000000000000002, '2.7'],
    ['1.1 + 2.2 = 3.3000000000000003（真毛刺 ⇒ 收敛到 3.3）', 1.1 + 2.2, '3.3'],
    ['73.80000000000001（毛刺形态的聚合值 ⇒ 73.8）', 73.80000000000001, '73.8'],
    ['0.1 + 0.2 = 0.30000000000000004 ⇒ 0.3', 0.1 + 0.2, '0.3'],
    ['字符串 "2.70" ⇒ 2.7', '2.70', '2.7'],
    ['60.55（两位小数 ⇒ 四舍五入到 1 位）', 60.55, '60.6'],
    ['0', 0, '0'],
  ])('%s', (_name, value, expected) => {
    expect(formatStockQuantity(value)).toBe(expected)
  })

  it.each([
    ['null', null],
    ['undefined', undefined],
    ['空字符串', ''],
    ['NaN', NaN],
    ['非数字字符串', 'abc'],
  ])('%s ⇒ 占位符「-」（不把 NaN 打到屏幕上）', (_name, value) => {
    expect(formatStockQuantity(value as number | string | null | undefined)).toBe('-')
  })
})
