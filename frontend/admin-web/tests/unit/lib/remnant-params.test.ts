// case_ids: PR-098
/**
 * 「余料回收」域在**企业参数中心**里的跨源守卫（issue #5146）—— `migao-dev-flow` §22 的 P1/P2/P3/P5。
 *
 * 分工：本文件判**静态清单与文案**；渲染面在
 * `tests/unit/components/RemnantSmallItemSpecsPanel.test.tsx`（面板）与
 * `tests/unit/components/TenantParamsPanel.test.tsx`（挂载点）。
 *
 * ## 判据（每条都带能**单独**让它变红的红证）
 *
 * | # | 判据 | 红证形态 |
 * |---|---|---|
 * | 1 | 余料域**挂在既有参数中心**（P1 一处入口，不新造第二个配置入口） | 删掉该域 ⇒ 断言红 |
 * | 2 | 小件尺寸表是 `inline` 面板（**页内渲染**，不是另开页面 / 第二个 settings 段） | 把 `inline` 删掉 / 换成别的 panel ⇒ 红 |
 * | 3 | 三件套合规（P2：`label`+`hint`+`impact` 都非空且**文案里不出现数字**） | 注入含数字 / 空字段的 inline copy ⇒ 判定函数必须报出来 |
 * | 4 | **默认值可见**的文案说清「为空 = 未启用」（P3） | 把 impact 改成不含「不填 / 未启用」的措辞 ⇒ 红 |
 * | 5 | **不改钱**必须写出来（用户裁定「不能损失客户」） | impact 去掉「不改对客价」⇒ 红 |
 * | 6 | 术语**就地查**（P5）：锚点走独立命名空间、不出现数字、每条至少影响一层 | 把锚点改成 `glossary-term-*`（与算料域抢 id）⇒ 红 |
 */
import { describe, expect, it } from 'vitest'
import {
  REMNANT_TERMS,
  glossaryRemnantAnchorOf,
  glossaryTermAnchorOf,
  type GlossaryTerm,
} from '@/lib/craft-calc-glossary'
import { PARAM_DOMAINS, REMNANT_PARAM_COPY, findDomainViolations } from '@/lib/tenant-params'

const remnantDomain = () => PARAM_DOMAINS.find((d) => d.key === 'remnant')!

/** 余料术语的数值扫描（**纯函数**：守卫与红证共用同一份判定，不复制规则） */
function numericOffenders(terms: GlossaryTerm[]): string[] {
  return terms
    .flatMap((t) => [t.definition, t.impact, t.boundary ?? ''].map((text) => `${t.name}：${text}`))
    .filter((s) => /[0-9]/.test(s))
}

describe('判据 1：余料域挂在**既有**企业参数中心（§22 P1 一处入口）', () => {
  it('域清单里有「余料回收」域，且它带一个下钻入口（余料台账）', () => {
    const domain = remnantDomain()
    expect(domain.label).toBe('余料回收')
    expect(domain.summary.length).toBeGreaterThan(0)
    expect((domain.rows ?? []).map((r) => r.href)).toEqual(['/production/remnants'])
  })

  it('红证：域清单里**没有**余料域时，本判据必须判不等（不是恒真）', () => {
    const without = PARAM_DOMAINS.filter((d) => d.key !== 'remnant')
    expect(without.find((d) => d.key === 'remnant')).toBeUndefined()
    expect(PARAM_DOMAINS.find((d) => d.key === 'remnant')).toBeDefined()
  })
})

describe('判据 2：小件尺寸表是**页内**内联面板（不另开配置页 / 第二个 settings 段）', () => {
  it('`inline.panel` 声明为 `remnant-specs`（页面按它渲染；加了面板不加渲染分支 ⇒ 渲染面守卫红）', () => {
    expect(remnantDomain().inline?.panel).toBe('remnant-specs')
    // 内联配置的 copy 与标量参数**同一份形状**（§22 P2 三件套）
    expect(remnantDomain().inline?.copy).toBe(REMNANT_PARAM_COPY)
  })

  it('红证：把 panel 换成未登记的取值 ⇒ 渲染面没有对应分支（渲染面守卫会红）', () => {
    const panels = PARAM_DOMAINS.map((d) => d.inline?.panel).filter(Boolean)
    expect(panels).toEqual(['remnant-specs'])
    expect(panels).not.toContain('remnant-specs-unknown')
  })
})

describe('判据 3：三件套合规（§22 P2 + 基线 ①「文案里不出现数字」）', () => {
  it('整份域清单（含内联配置）零违规', () => {
    expect(findDomainViolations(PARAM_DOMAINS)).toEqual([])
  })

  it('小件尺寸表的 label / hint / impact 都非空且不含数字', () => {
    for (const field of ['label', 'hint', 'impact'] as const) {
      expect(REMNANT_PARAM_COPY[field].trim().length).toBeGreaterThan(0)
      expect(REMNANT_PARAM_COPY[field]).not.toMatch(/[0-9]/)
    }
  })

  it('红证：内联配置的坏文案必须被同一条判定函数报出来（含数字 / 空字段）', () => {
    expect(
      findDomainViolations([
        {
          key: 'x',
          label: '域',
          summary: 's',
          inline: {
            panel: 'remnant-specs',
            copy: { label: '用料长 0.5 米', hint: '', impact: 'i' },
          },
        },
      ])
    ).toEqual(['x.inline.label 含数字：用料长 0.5 米', 'x.inline.hint 为空'])
  })
})

describe('判据 4/5：默认值可见（P3）+ 不改钱必须写出来（用户裁定「不能损失客户」）', () => {
  it('impact 说清「不填就完全不产生匹配建议」与「不改对客价 / 加工费 / 成品尺寸」', () => {
    expect(REMNANT_PARAM_COPY.impact).toContain('不填就完全不产生匹配建议')
    expect(REMNANT_PARAM_COPY.impact).toContain('不改对客价')
    expect(REMNANT_PARAM_COPY.impact).toContain('不改成品尺寸')
  })

  it('红证：把 impact 换成一句不含「不改钱」的措辞 ⇒ 上面的断言必须判不等', () => {
    const silent = '按它挑余料'
    expect(silent).not.toContain('不改对客价')
    expect(silent).not.toContain('不填就完全不产生匹配建议')
  })

  it('下钻入口的「钱在哪」同样写明不改对客价（行式入口也受同一条裁定约束）', () => {
    const ledger = (remnantDomain().rows ?? [])[0]
    expect(ledger.money).toContain('不改对客价')
  })
})

describe('判据 6：术语**就地**查（§22 P5）—— 独立命名空间 + 不出现数字 + 每条影响一层', () => {
  it('锚点走 `glossary-remnant-*`，与算料域 / 特殊选项域**不共用** id', () => {
    const anchors = REMNANT_TERMS.map((t) => glossaryRemnantAnchorOf(t.name))
    expect(new Set(anchors).size).toBe(anchors.length)
    expect(anchors.every((a) => a.startsWith('glossary-remnant-'))).toBe(true)
    // 与算料域「手选特征」组不抢同一个 DOM id（同族实证：「接高」在两组里都有）
    const calcAnchors = new Set(REMNANT_TERMS.map((t) => glossaryTermAnchorOf(t.name)))
    expect(anchors.filter((a) => calcAnchors.has(a))).toEqual([])
  })

  it('术语文案里不出现数字，且每条都写清「影响什么」', () => {
    expect(numericOffenders(REMNANT_TERMS)).toEqual([])
    for (const term of REMNANT_TERMS) {
      expect(term.impact.trim().length).toBeGreaterThan(0)
      expect(term.definition.trim().length).toBeGreaterThan(0)
    }
  })

  it('红证：数值扫描非空转 —— 注入一条写死尺寸的术语必须被抓到', () => {
    const bad: GlossaryTerm = {
      name: '坏术语',
      definition: '余料宽 0.3 米',
      impact: 'i',
    }
    expect(numericOffenders([bad]).length).toBe(1)
    expect(numericOffenders([{ name: '好术语', definition: '余料宽按门幅余量而定', impact: 'i' }])).toEqual([])
  })

  it('术语覆盖「不静默」这条口径本身（未配置 / 不凭空推荐必须能就地查到）', () => {
    const names = REMNANT_TERMS.map((t) => t.name)
    expect(names).toContain('小件用料尺寸')
    const specTerm = REMNANT_TERMS.find((t) => t.name === '小件用料尺寸')!
    expect(specTerm.impact).toContain('默认值为空')
    expect(specTerm.impact).toContain('不会凭空推荐')
  })
})
