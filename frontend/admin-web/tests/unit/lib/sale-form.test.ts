// case_ids: UI-076, OR-039
/**
 * 售卖形态「布料」的**前端唯一读点**（issue #7320）。
 *
 * 背景：布料单不涉及加工费，但定价引擎与多处展示都只按「有没有选配加工项 / fee_source」判
 * ⇒ 每一张布料单都会在订单详情挂一条「加工费未定价（缺选配信息）」的假警报，并在「工艺规格」
 * 组里印出「加工费米数」。本模块给出**唯一**的 `isFabricSaleLine`，展示侧一律经它判型。
 *
 * 类级判据（本文件最后一条）：`'布料'` 字面量的比较**只许**出现在本模块与下单页（那里是表单态
 * 自己的 `SaleForm` 联合类型），别处再写一份 `=== '布料'` ⇒ 红。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { SALE_FORM_FABRIC, isFabricSaleLine } from '@/lib/sale-form'

const SRC = join(process.cwd(), 'src')

/** 允许出现 `'布料'` 字面量比较的文件（相对 src）—— 本模块 + 下单页（表单态常量 + 展示标签） */
const FABRIC_LITERAL_ALLOW = new Set(['lib/sale-form.ts', 'app/(dashboard)/orders/new/page.tsx'])

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (full.endsWith('.ts') || full.endsWith('.tsx')) out.push(full)
  }
  return out
}

describe('lib/sale-form — 布料行的唯一读点（issue #7320）', () => {
  it('saleForm 逐字等于「布料」才算；缺键 / 成品帘 / 脏值一律 false', () => {
    expect(SALE_FORM_FABRIC).toBe('布料')
    expect(isFabricSaleLine({ saleForm: '布料' })).toBe(true)
    expect(isFabricSaleLine({ saleForm: ' 布料 ' })).toBe(true)
    expect(isFabricSaleLine({ saleForm: '成品帘' })).toBe(false)
    expect(isFabricSaleLine({})).toBe(false)
    expect(isFabricSaleLine({ saleForm: null })).toBe(false)
    expect(isFabricSaleLine({ saleForm: 123 })).toBe(false)
    expect(isFabricSaleLine(null)).toBe(false)
    expect(isFabricSaleLine('{"saleForm":"布料"}')).toBe(false)
  })

  it('类级：`布料` 字面量比较只许出现在本模块与下单页', () => {
    const offenders = walk(SRC)
      .filter((file) => !FABRIC_LITERAL_ALLOW.has(relative(SRC, file).split('\\').join('/')))
      .filter((file) => /['"]布料['"]/.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SRC, file))
    expect(offenders).toEqual([])
  })
})
