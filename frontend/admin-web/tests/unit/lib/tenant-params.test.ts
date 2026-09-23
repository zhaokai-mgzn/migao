// case_ids: UI-054
/**
 * 「企业参数中心」参数清单与文案的**跨源守卫**（issue #5131）—— `migao-dev-flow` §22 的三条基线。
 *
 * 分工：本文件判**静态清单与文案**；渲染面在
 * `frontend/admin-web/tests/unit/components/TenantParamsPanel.test.tsx`。
 *
 * ## 判据（每条都带能**单独**让它变红的红证）
 *
 * | # | 判据 | 红证形态 |
 * |---|---|---|
 * | 1 | 文案里**不出现数字**（§22 基线 ①） | 注入 `'超宽阈值 6 米'` ⇒ 扫描必须报出来 |
 * | 2 | 算料域覆盖引擎**全部**配置键（§22 基线 ③，**双向**） | 少挂一个键 ⇒ `missing` 非空；多挂 ⇒ `extra` 非空 |
 * | 3 | 算料文案**不抄第二份**（同一对象引用） | 改成 `{...CALC_PARAM_COPY[k]}` ⇒ 同一性断言红 |
 * | 4 | 新增配置键**默认进「常用」**（排除法，不因忘加清单而消失） | 把某键挪出 advanced 却不在 common ⇒ 红 |
 * | 5 | AI 客服域只列**页面上真的能改**的字段（假清单 = 列了改不了的参数） | 清单与 `AI_PARAM_COPY` 键集不等 ⇒ 红 |
 * | 6 | P3 租户级判据：`source` 三态 | `'stored'` 被判成「在用默认」⇒ 红 |
 */
import { describe, expect, it } from 'vitest'
import { CALC_PARAM_COPY, CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'
import {
  AI_PARAM_COPY,
  PARAM_DOMAINS,
  calcKeySetDiff,
  findCopyViolations,
  findDomainViolations,
  isUsingEngineDefault,
  scalarCountOf,
} from '@/lib/tenant-params'

const calcDomain = () => PARAM_DOMAINS.find((d) => d.key === 'calc')!

describe('判据 1：文案里不出现数字（§22 基线 ①）', () => {
  it('本模块全部文案合规（AI 客服 copy + 四个域的 label/summary/入口文案）', () => {
    expect(findCopyViolations(AI_PARAM_COPY)).toEqual([])
    expect(findDomainViolations(PARAM_DOMAINS)).toEqual([])
  })

  it('红证：注入含数字 / 空字段的文案 ⇒ 扫描必须逐条判出来', () => {
    expect(
      findCopyViolations({ bad: { label: '超宽阈值 6 米', hint: 'h', impact: 'i' } })
    ).toEqual(['bad.label 含数字：超宽阈值 6 米'])
    expect(findCopyViolations({ bad: { label: '好', hint: '', impact: 'i' } })).toEqual([
      'bad.hint 为空',
    ])
    // 域面：label 含数字 / href 不是站内路径 / 缺「钱在哪」—— 三种各判一次
    expect(findDomainViolations([{ key: 'k', label: '域1', summary: 's' }])).toEqual([
      '域 k.label 含数字：域1',
    ])
    expect(
      findDomainViolations([
        {
          key: 'k',
          label: '域',
          summary: 's',
          rows: [{ label: '入口', href: 'no-slash', hint: 'h', money: 'm' }],
        },
      ])
    ).toEqual(['域 k 的入口 入口 的 href 必须以 / 开头'])
  })
})

describe('判据 2：算料域覆盖引擎全部配置键（§22 基线 ③，双向）', () => {
  it('common ∪ advanced 与 CALC_SCALAR_KEYS **双向相等**', () => {
    expect(calcKeySetDiff(PARAM_DOMAINS, CALC_SCALAR_KEYS)).toEqual({ missing: [], extra: [] })
  })

  it('红证：漏挂一个键 ⇒ missing 非空；多挂一个键 ⇒ extra 非空', () => {
    const dropped = PARAM_DOMAINS.map((d) =>
      d.key === 'calc' ? { ...d, common: (d.common ?? []).slice(0, 1) } : d
    )
    expect(calcKeySetDiff(dropped, CALC_SCALAR_KEYS).missing.length).toBeGreaterThan(0)
    // 引擎多一个键而本模块没挂 ⇒ missing（商家**看不见**这个参数）
    expect(calcKeySetDiff(PARAM_DOMAINS, [...CALC_SCALAR_KEYS, 'ghost_key']).missing).toEqual([
      'ghost_key',
    ])
    // 本模块挂了引擎没有的键 ⇒ extra（凭空多一个参数）
    const polluted = PARAM_DOMAINS.map((d) =>
      d.key === 'calc'
        ? {
            ...d,
            common: [
              ...(d.common ?? []),
              { key: 'ghost_key', copy: { label: '幽灵', hint: 'h', impact: 'i' } },
            ],
          }
        : d
    )
    expect(calcKeySetDiff(polluted, CALC_SCALAR_KEYS).extra).toEqual(['ghost_key'])
  })
})

describe('判据 3：算料文案取自唯一真值模块（不抄第二份）', () => {
  it('每条的 copy 与 CALC_PARAM_COPY 是**同一对象**（拷贝一份就会漂）', () => {
    const calc = calcDomain()
    const all = [...(calc.common ?? []), ...(calc.advanced ?? [])]
    expect(all.length).toBe(CALC_SCALAR_KEYS.length)
    for (const p of all) {
      expect(p.copy).toBe(CALC_PARAM_COPY[p.key])
    }
  })

  it('红证：改成浅拷贝 ⇒ 同一性断言必红', () => {
    const calc = calcDomain()
    const cloned = (calc.common ?? []).map((p) => ({ key: p.key, copy: { ...p.copy } }))
    expect(cloned[0].copy).not.toBe(CALC_PARAM_COPY[cloned[0].key])
    expect(cloned[0].copy).toEqual(CALC_PARAM_COPY[cloned[0].key])
  })
})

describe('判据 4：新增配置键默认进「常用」（排除法）', () => {
  it('只有登记在册的键落「高级」，其余一律「常用」', () => {
    const calc = calcDomain()
    const advancedKeys = (calc.advanced ?? []).map((p) => p.key)
    const commonKeys = (calc.common ?? []).map((p) => p.key)
    expect([...advancedKeys].sort()).toEqual(['meters_rounding_step', 'min_fullness'])
    for (const k of CALC_SCALAR_KEYS) {
      if (!advancedKeys.includes(k)) expect(commonKeys).toContain(k)
    }
  })

  it('红证：把某键从两个清单里都拿掉 ⇒ 判据 2 的 missing 非空（即它不会「静默消失」）', () => {
    const calc = calcDomain()
    const holed = PARAM_DOMAINS.map((d) =>
      d.key === 'calc'
        ? { ...d, advanced: (d.advanced ?? []).filter((p) => p.key !== 'min_fullness') }
        : d
    )
    expect(calcKeySetDiff(holed, CALC_SCALAR_KEYS).missing).toEqual(['min_fullness'])
    expect((calc.common ?? []).some((p) => p.key === 'min_fullness')).toBe(false)
  })
})

describe('判据 5：AI 客服域只列「页面上真的能改」的字段', () => {
  it('清单 = AI_PARAM_COPY 的键集（列一个改不了的参数 = 假清单）', () => {
    const ai = PARAM_DOMAINS.find((d) => d.key === 'ai')!
    expect((ai.common ?? []).map((p) => p.key)).toEqual(Object.keys(AI_PARAM_COPY))
    expect(findCopyViolations(AI_PARAM_COPY)).toEqual([])
  })

  it('红证：清单里塞一个 copy 表里没有的键 ⇒ 键集断言红', () => {
    const ai = PARAM_DOMAINS.find((d) => d.key === 'ai')!
    const polluted = [...(ai.common ?? []), { key: 'ghost', copy: { label: 'x', hint: 'y', impact: 'z' } }]
    expect(polluted.map((p) => p.key)).not.toEqual(Object.keys(AI_PARAM_COPY))
  })
})

describe('判据 6：P3「默认值可见」的租户级判据', () => {
  it("source 为 stored ⇒ 已配置；default / 缺失 ⇒ 在用引擎默认值", () => {
    expect(isUsingEngineDefault('stored')).toBe(false)
    expect(isUsingEngineDefault('default')).toBe(true)
    expect(isUsingEngineDefault(undefined)).toBe(true)
    expect(isUsingEngineDefault(null)).toBe(true)
  })
})

describe('判据 7：域结构（§22 P1 分组）', () => {
  it('五个域按序、key 唯一、label/summary 非空；算料域计数 = 引擎键数', () => {
    // issue #5146：新增「余料回收」域（小件用料尺寸表的**唯一**配置入口，§22 P1）——
    // 插在 AI 客服之后、加工费之前（标量域相邻，行式配置域在后）。
    expect(PARAM_DOMAINS.map((d) => d.key)).toEqual(['calc', 'ai', 'remnant', 'fee', 'craft'])
    expect(new Set(PARAM_DOMAINS.map((d) => d.key)).size).toBe(PARAM_DOMAINS.length)
    for (const d of PARAM_DOMAINS) {
      expect(d.label.trim().length).toBeGreaterThan(0)
      expect(d.summary.trim().length).toBeGreaterThan(0)
    }
    expect(scalarCountOf(calcDomain())).toBe(CALC_SCALAR_KEYS.length)
    // 行式配置域（加工费）没有标量参数 —— 按键取，不靠位置（#5146 插入新域后就踩过这一格）
    expect(scalarCountOf(PARAM_DOMAINS.find((d) => d.key === 'fee')!)).toBe(0)
  })
})
