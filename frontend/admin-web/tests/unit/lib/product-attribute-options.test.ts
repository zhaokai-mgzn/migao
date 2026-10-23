// case_ids: PR-074
/**
 * 规格属性选项表的**单一真值源守卫**（issue #7528）。
 *
 * 这些选项原先只写在 `components/products/ProductAttributes.tsx` 里；本单把「从商家写的那句话里
 * 认出材质 / 功能 / 工艺 / 风格 / 花型」接进来之后，同一个真值就有了**两个消费点** ——
 * 组件渲染下拉、解析器匹配文字。两处各写一份 = 组件新增一个选项而解析器认不出来
 * （或反过来），**没有任何东西会变红**。
 *
 * 判据（会红）：
 * 1. 选项表结构合法：每组都有可真选的值、同组内值唯一、`CUSTOM_OPTION_VALUE` 只出现在末位；
 * 2. 组 key 全部落在 `SPEC_EN_TO_CN`（中文名真值只有那一处）；
 * 3. 🔴 **类级元守卫**：组件源码里**不许再声明**自己的选项表，且必须从本模块 import ——
 *    注入式反证证明这条能抓到「有人又把表抄回组件里」；
 * 4. 🔴 **双向**：表里每一个能参与匹配的选项（长度 ≥ 2、非哨兵）都必须能被
 *    `lib/declared-facts.ts::attributesOf` 认出来 —— 新增一个选项而解析器跟不上 ⇒ 红。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  CRAFT_OPTIONS,
  CUSTOM_OPTION_VALUE,
  FUNCTION_OPTIONS,
  MATERIAL_OPTIONS,
  PATTERN_OPTIONS,
  SPEC_ATTRIBUTE_GROUPS,
  STYLE_OPTIONS,
  WEIGHT_OPTIONS,
} from '@/lib/product-attribute-options'
import { SPEC_EN_TO_CN } from '@/lib/attribute-keys'
import { attributesOf } from '@/lib/declared-facts'

const COMPONENT = 'src/components/products/ProductAttributes.tsx'
const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')

/** 可参与文字匹配的选项（单字选项刻意不参与：中文里太容易误命中） */
const matchable = (options: Array<{ value: string }>) =>
  options.map((o) => o.value).filter((v) => v && v !== CUSTOM_OPTION_VALUE && v.length >= 2)

describe('判据 1 · 选项表结构（每组都有可真选的值、同组不重、哨兵只在末位）', () => {
  it('六个属性组的键与 `SPEC_EN_TO_CN` 对得上（中文名真值只有一处）', () => {
    expect(SPEC_ATTRIBUTE_GROUPS.map((group) => group.key)).toEqual([
      'weight',
      'material',
      'function',
      'craft',
      'style',
      'pattern',
    ])
    for (const group of SPEC_ATTRIBUTE_GROUPS) {
      expect(Object.keys(SPEC_EN_TO_CN)).toContain(group.key)
    }
  })

  it('每组至少一个可真选的值；同组值唯一；「请选择」只在首位、「其他」只在末位', () => {
    for (const group of SPEC_ATTRIBUTE_GROUPS) {
      const values = group.options.map((option) => option.value)
      expect(values[0]).toBe('')
      expect(values.filter((v) => v === '')).toHaveLength(1)
      expect(values[values.length - 1]).toBe(CUSTOM_OPTION_VALUE)
      expect(new Set(values).size).toBe(values.length)
      expect(matchable(group.options).length).toBeGreaterThan(0)
    }
  })

  it('导出的六张表就是组里那六张（不是第二份副本）', () => {
    const exported = [
      WEIGHT_OPTIONS,
      MATERIAL_OPTIONS,
      FUNCTION_OPTIONS,
      CRAFT_OPTIONS,
      STYLE_OPTIONS,
      PATTERN_OPTIONS,
    ]
    expect(SPEC_ATTRIBUTE_GROUPS.map((group) => group.options)).toEqual(exported)
  })
})

describe('判据 2 · 类级元守卫：组件不许留第二份选项表', () => {
  it('组件源码从本模块 import，且不得再声明 *_OPTIONS 常量', () => {
    const src = read(COMPONENT)
    expect(src).toContain("from '@/lib/product-attribute-options'")
    // 任何 `const X_OPTIONS = [` 形态都算「又抄了一份」
    const redeclared = [...src.matchAll(/const\s+([A-Z][A-Z0-9_]*_OPTIONS)\s*=/g)].map((m) => m[1])
    // 对照组：品牌 / 计价单位**不在**规格属性表里（它们是商品级基础字段，不是「材质/功能/…」那一族）
    expect(redeclared.sort()).toEqual(['BRAND_OPTIONS', 'UNIT_OPTIONS'])
  })

  it('判别力自证：把一张表抄回组件里必须被抓到', () => {
    const injected = read(COMPONENT) + "\nconst MATERIAL_OPTIONS = [{ value: '棉', label: '棉' }]\n"
    const found = [...injected.matchAll(/const\s+([A-Z][A-Z0-9_]*_OPTIONS)\s*=/g)].map((m) => m[1])
    expect(found).toContain('MATERIAL_OPTIONS')
  })
})

describe('判据 3 · 双向：表里每个可匹配选项，解析器都认得出', () => {
  it('逐个选项单独成句 ⇒ 解析出对应的属性键', () => {
    const missed: string[] = []
    for (const group of SPEC_ATTRIBUTE_GROUPS) {
      for (const value of matchable(group.options)) {
        const found = attributesOf(`这款是 ${value}`)
        if (!found.some((attr) => attr.key === group.key && attr.value === value)) {
          missed.push(`${group.key}:${value}`)
        }
      }
    }
    expect(missed).toEqual([])
  })

  it('反证：表里没有的词不会被硬塞进某个属性', () => {
    expect(attributesOf('这款是 大理石纹理')).toEqual([])
  })
})
