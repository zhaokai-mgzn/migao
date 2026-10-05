// case_ids: PR-008, PR-020
/**
 * 图片识别**色号清单**必须拆成多行颜色（issue #6354）。
 *
 * 病根（用户 2026-10-05 实测建品页）：内核按顿号给出一整串色号（一张色卡实测
 * **16 个 / 127 字符**），前端把它当**一个** `colorName` ⇒ 颜色行名称框 `maxLength = 30`
 * 把它**静默截断**成 `2699-01、2699-02、2699-03、`（第 4 个色号只剩半截），
 * 且 SKU 矩阵只出 1 行（应为 颜色 × 门幅 = 16 行）。
 *
 * 本文件锁两条：
 * ① **实例判据**：真实 16 色号载荷 ⇒ 16 行颜色 / 16 行 SKU，且每行能进输入框（≤ 30 字符）；
 * ② **类级元守卫**：`buildProductPrefill` 产出的**每一个**颜色名都不得超上限 —— 谁把拆分去掉
 *    （或把上限改小而不改这里）⇒ 必红，报出**是哪一个颜色名**超了。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { buildProductPrefill, COLOR_LIST_SEPARATORS } from '@/lib/image-recognize'
import { COLOR_NAME_MAX, MAX_COLORS } from '@/lib/product-limits'
import type { RecognizedField } from '@/lib/api'

const TAG = '[图片识别]'

/** 用户实测载荷（逐字取自识别报告面板）：16 个色号、顿号分隔、共 127 字符 */
const SIXTEEN_CODES = Array.from({ length: 16 }, (_, i) => `2699-${String(i + 1).padStart(2, '0')}`)
const RECOGNIZED_COLOR_LIST = SIXTEEN_CODES.join('、')

const colorField = (value: string): RecognizedField[] => [
  { key: 'color', label: '颜色', value, source: TAG, reason: null },
]

describe('图片识别 · 色号清单拆行 (#6354)', () => {
  it('16 个色号的真实载荷 ⇒ 16 行颜色 + 16 行 SKU（改前 = 1 行 / 127 字符被输入框削成 30）', () => {
    const { initialData, recognizedFields } = buildProductPrefill([
      ...colorField(RECOGNIZED_COLOR_LIST),
      { key: 'door_width', label: '门幅', value: '3.2', source: TAG, reason: null },
    ])

    expect(initialData.colors?.map((c) => c.colorName)).toEqual(SIXTEEN_CODES)
    expect(initialData.skus).toHaveLength(SIXTEEN_CODES.length)
    // 回退护栏：矩阵行必须挂在刚建的颜色上（否则矩阵里是另一套颜色）
    expect(initialData.skus?.map((s) => s.colorName)).toEqual(SIXTEEN_CODES)
    // 徽标只挂一次（列表字段，不是每行一枚）
    expect(recognizedFields.filter((k) => k === 'color')).toHaveLength(1)
  })

  it('类级元守卫：预填产出的**每一个**颜色名都能进表单（> COLOR_NAME_MAX 即红）', () => {
    const { initialData } = buildProductPrefill(colorField(RECOGNIZED_COLOR_LIST))

    const tooLong = (initialData.colors || []).filter((c) => c.colorName.length > COLOR_NAME_MAX)
    expect(
      tooLong.map((c) => `${c.colorName}(${c.colorName.length})`),
      `以下颜色名超过表单上限 ${COLOR_NAME_MAX}，会被输入框静默截断`,
    ).toEqual([])
  })

  it('分隔口径与 SkuMatrix「批量输入颜色」同一套（改一处忘一处 ⇒ 红）', () => {
    const skuMatrix = readFileSync(
      resolve(process.cwd(), 'src/components/products/SkuMatrix.tsx'),
      'utf-8',
    )
    // 人工批量录入那条路径的分隔符（BatchColorInput 的 handleApply）
    expect(skuMatrix).toContain(String(COLOR_LIST_SEPARATORS))
    // 上限只有一个定义点：组件里不得再写死 30/200
    expect(skuMatrix).toMatch(/from '@\/lib\/product-limits'/)
  })

  it('封顶 MAX_COLORS；逐字重复去重（不猜、不改写颜色名）', () => {
    const over = Array.from({ length: MAX_COLORS + 5 }, (_, i) => `C${i}`)
    const { initialData } = buildProductPrefill(colorField(over.join('、')))
    expect(initialData.colors).toHaveLength(MAX_COLORS)

    const dup = buildProductPrefill(colorField('2699-01、2699-01、 2699-02 、2699-02'))
    expect(dup.initialData.colors?.map((c) => c.colorName)).toEqual(['2699-01', '2699-02'])
  })

  it('混合分隔符（换行 / 中文逗号 / 英文逗号 / 顿号）都拆得开', () => {
    const { initialData } = buildProductPrefill(colorField('A、B\nC，D,E'))
    expect(initialData.colors?.map((c) => c.colorName)).toEqual(['A', 'B', 'C', 'D', 'E'])
  })
})
