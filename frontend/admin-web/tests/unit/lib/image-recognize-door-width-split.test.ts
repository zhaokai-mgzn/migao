// case_ids: PR-022, PR-008, PR-020
/**
 * 图片识别**门幅清单**必须拆成多行规格尺寸（issue #6403 缺陷 1）。
 *
 * 病根（用户 2026-10-06 实测建品页，图 2 + 图 4）：同一张图里**颜色进得来、门幅一个都进不来** ——
 * 识别卡片里门幅那格逐字是 `2.8米和3.2米`（图 4 的红框），而一键填入后页面「规格尺寸 (0)」。
 * 归因 = `frontend/admin-web/src/lib/image-recognize.ts::buildProductPrefill` 把 `door_width`
 * 当**标量**处理（`normalizedDoorWidth(valueOf(fields,'door_width'))` 只产出一个值），
 * 多值串归一后 `Number(...)` 必然 `NaN` ⇒ 整串被丢。而 `color` 走的是**清单**口径
 * （`colorNamesOf` 拆多值 + 去重，issue #6354）—— 同一张图两种口径。
 *
 * 本文件锁三条：
 * ① **实例判据**：多值串（和 / 与 / 顿号 / 斜杠 / 逗号）⇒ 逐根门幅；单值串旧行为**逐字不变**；
 *    非数（`深灰色`）仍必须丢；同一物理门幅去重；SKU 行数 = 颜色数 × 门幅数；
 * ② **类级元守卫（铁律 8）**：`LIST_SEMANTIC_FIELD_KEYS` 登记表 ⇄ 探针表双向相等，且**每一个**
 *    登记为清单语义的识别字段都必须能把多值串拆开 —— 新增同类字段却按标量处理 ⇒ 当场红；
 * ③ **口径单一**：门幅拆分复用颜色那份**唯一**的分隔符表与拆分实现，不得新造第二份。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { buildProductPrefill, COLOR_LIST_SEPARATORS } from '@/lib/image-recognize'
import type { RecognizedField } from '@/lib/api'
import type { ProductFormData } from '@/types'

const TAG = '[图片识别]'

const field = (...keys: Array<[string, string]>): RecognizedField[] =>
  keys.map(([key, value]) => ({ key, label: key, value, source: TAG, reason: null }))

const doorWidthOf = (raw: string): string[] | undefined =>
  buildProductPrefill(field(['door_width', raw])).initialData.doorWidths

describe('图片识别 · 门幅清单拆行（issue #6403 缺陷 1）', () => {
  it('判据 1a：`2.8米和3.2米` ⇒ doorWidths = [2.8, 3.2]（改前 = 一个都进不来）', () => {
    const { initialData, recognizedFields } = buildProductPrefill(
      field(['color', '米白'], ['door_width', '2.8米和3.2米']),
    )

    expect(initialData.doorWidths).toEqual(['2.8', '3.2'])
    // 矩阵行 = 颜色 × 门幅（与 SkuMatrix 每次改动走同一条 rebuildSkus 路径）
    expect(initialData.skus?.map((s) => s.doorWidth)).toEqual(['2.8', '3.2'])
    // 列表字段的徽标只挂一次
    expect(recognizedFields.filter((k) => k === 'door_width')).toHaveLength(1)
  })

  it('判据 1b：顿号 / 斜杠 /「与」/ 中英文逗号 同一份分隔口径', () => {
    expect(doorWidthOf('2.8米、3.2米')).toEqual(['2.8', '3.2'])
    expect(doorWidthOf('2.8/3.2米')).toEqual(['2.8', '3.2'])
    expect(doorWidthOf('2.8米与3.2米')).toEqual(['2.8', '3.2'])
    expect(doorWidthOf('2.8,3.2')).toEqual(['2.8', '3.2'])
    expect(doorWidthOf('2.8米，3.2米')).toEqual(['2.8', '3.2'])
  })

  it('判据 1c（旧行为**一个字都不能变**）：单值串 ⇒ 恰好一根门幅', () => {
    expect(doorWidthOf('2.8米')).toEqual(['2.8'])
    expect(doorWidthOf('门幅2.8米')).toEqual(['2.8'])
    expect(doorWidthOf('2.8')).toEqual(['2.8'])
  })

  it('判据 1d：非数仍必须丢（`深灰色` ⇒ 不写键；混入非数只留数）', () => {
    expect(doorWidthOf('深灰色')).toBeUndefined()
    expect(doorWidthOf('2.8米、深灰色、3.2米')).toEqual(['2.8', '3.2'])
  })

  it('判据 1e：同一物理门幅去重（`2.8` / `2.8米` / `门幅2.8` 是一根）', () => {
    expect(doorWidthOf('2.8、2.8米、门幅2.8')).toEqual(['2.8'])
  })

  it('判据 1f：SKU 行数 = 颜色数 × 门幅数', () => {
    const { initialData } = buildProductPrefill(
      field(['color', '米白、浅灰、深灰'], ['door_width', '2.8米和3.2米']),
    )
    expect(initialData.colors).toHaveLength(3)
    expect(initialData.doorWidths).toEqual(['2.8', '3.2'])
    expect(initialData.skus).toHaveLength(6)
  })

  it('类级元守卫（铁律 8）：登记为清单语义的识别字段，多值串都必须拆开落进表单', async () => {
    const mod = await import('@/lib/image-recognize')
    const keys: readonly string[] =
      (mod as { LIST_SEMANTIC_FIELD_KEYS?: readonly string[] }).LIST_SEMANTIC_FIELD_KEYS ?? []

    // 登记表 ⇄ 本判据的探针表**双向相等**（新增一个清单字段却不接线 / 不登记 ⇒ 红）
    const probes: Record<string, (d: Partial<ProductFormData>) => string[]> = {
      color: (d) => (d.colors ?? []).map((c) => c.colorName),
      door_width: (d) => d.doorWidths ?? [],
    }
    expect([...keys].sort()).toEqual(Object.keys(probes).sort())

    for (const key of keys) {
      const { initialData } = buildProductPrefill(field([key, '2.8、3.2']))
      expect(
        probes[key](initialData),
        `清单语义字段 ${key} 没有把多值串拆开（按标量处理了）`,
      ).toHaveLength(2)
    }
  })

  it('口径单一：门幅拆分复用颜色那份分隔符表，不新造第二份', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/lib/image-recognize.ts'),
      'utf-8',
    )

    // 分隔符表只有一份（`COLOR_LIST_SEPARATORS`）；再声明一个 *SEPARATORS 常量 ⇒ 红
    expect(source.match(/export const \w*SEPARATORS\w* =/g) ?? []).toHaveLength(1)
    expect(String(COLOR_LIST_SEPARATORS)).toBe(String(/[\n,，、]+/))

    // 门幅拆分必须走**共享**实现，且自己不得再写 `.split(`
    const start = source.indexOf('export function doorWidthsOf')
    const end = source.indexOf('export function buildProductPrefill')
    expect(start, 'doorWidthsOf 不存在（门幅仍按标量处理？）').toBeGreaterThan(-1)
    expect(end).toBeGreaterThan(start)
    const body = source.slice(start, end)
    expect(body).toMatch(/listValuesOf|colorNamesOf/)
    expect(body).not.toContain('.split(')
  })
})
