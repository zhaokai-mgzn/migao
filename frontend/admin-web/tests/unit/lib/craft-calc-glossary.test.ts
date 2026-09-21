// case_ids: OR-040, OR-041
/**
 * 「算料配置」页的**口径与术语说明**（issue #4975）—— 单一真值模块的跨源守卫。
 *
 * 复用既有用例（不新增用例 ID，理由同 `OperationsProvenance.test.tsx` 的先例：新增用例会触发
 * case-trust burn-down 预算 + 与生成物争抢）：
 * - **OR-040** = 下单页系统识别 / 余量常量语义（`SIDE_MARGIN` 左右覆盖余量 vs `HEM_MARGIN` 上下卷边）；
 * - **OR-041** = 算料公式按工艺派生 + 逐片口径 + 向上进位（= 本页这些参数的消费方）。
 *
 * ## 本文件治的缺陷形态（每一条都能单独判红）
 *
 * | # | 判据 | 红证（怎么让它红） |
 * |---|---|---|
 * | 1 | 引擎配置键集 ⊆ 说明键集 | 在 `DEFAULT_CRAFT_CALC_CONFIG` 加一个键而不补文案 ⇒ 红 |
 * | 2 | `side_margin` 的口径 = **左右覆盖余量** | 把文案改回「定宽买高的上下卷边合计」⇒ 红（= #4940 判据 1） |
 * | 3 | 页面**不再自带第二份口径** | 页面里再出现旧文案字面量 / 不再引用说明模块 ⇒ 红 |
 * | 4 | **引擎那行注释**也不得再说「上下卷边」 | 把引擎注释改回去 ⇒ 红（漂移源头在引擎，不只是页面） |
 * | 5 | 说明文案里**不出现数字** | 在任一文案里写死 `0.25` 之类的值 ⇒ 红（数值只许来自真值） |
 * | 6 | 自动推算算例 = `detectAutoFeatures` 的**真实输出** | 算例文案自己拼 / 与下单页分叉 ⇒ 红 |
 * | 7 | 拼接 / 接高写明「系统不推算」「不触发工序」 | 删掉任一句 ⇒ 红（**死亡条件**见下） |
 * | 8 | 术语覆盖清单齐全 | 少一个术语 ⇒ 红 |
 *
 * ⚠️ **判据 7 是死亡条件式的**：它钉的是**当下**口径（加工项特征不触发工序）。
 * 一旦 issue #4569 裁定改为「也触发工序」，**这条必须连同文案一起改判** —— 它不是"永真"断言。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { AUTO_FEATURE_NAMES, detectAutoFeatures } from '@/lib/craft-auto-features'
import {
  AUTO_FEATURE_TERMS,
  CALC_PARAM_COPY,
  CALC_SCALAR_KEYS,
  GLOSSARY_EXAMPLE,
  GLOSSARY_FORMULAS,
  MANUAL_FEATURE_TERMS,
  TERM_FAMILY,
  buildAutoFeatureExamples,
  glossaryAnchorOf,
  glossaryTermAnchorOf,
} from '@/lib/craft-calc-glossary'
import type { CraftCalcConfig } from '@/types'

/** 算料引擎源（**真值源**）：`backend/ai-agent-service/app/tools/curtain_calc.py` */
const CALC_SRC = resolve(__dirname, '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py')
const engineSrc = readFileSync(CALC_SRC, 'utf8')

/** 「算料配置」tab 所在页面（第二份口径的**可能落点**，必须钉住） */
const PAGE_SRC = resolve(__dirname, '../../../src/app/(dashboard)/production/routings/page.tsx')
const pageSrc = readFileSync(PAGE_SRC, 'utf8')

/** 后端契约类型（`side_margin` 的注释同样在讲口径 ⇒ 也在守卫范围内） */
const TYPES_SRC = resolve(__dirname, '../../../src/types/index.ts')
const typesSrc = readFileSync(TYPES_SRC, 'utf8')

/** 说明模块自身（判据 9 的扫描面） */
const GLOSSARY_SRC = resolve(__dirname, '../../../src/lib/craft-calc-glossary.ts')
const glossarySrc = readFileSync(GLOSSARY_SRC, 'utf8')

/** 测试替身：引擎默认配置（逐值写死 = 「后端会回什么」，判据不从实现推导） */
const ENGINE_DEFAULT_CALC_CONFIG: CraftCalcConfig = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: { standard: { fullness: 2.0, label: '标准工艺' }, economy: { fullness: 1.8, label: '经济工艺' } },
  default_formula: 'pleat',
  side_margin: 0.3,
  meters_rounding_step: 0.1,
}

/** 引擎 `DEFAULT_CRAFT_CALC_CONFIG` 的**键集**（读源，不写死） */
function engineConfigKeys(): string[] {
  const m = engineSrc.match(/DEFAULT_CRAFT_CALC_CONFIG[^=]*=\s*MappingProxyType\(\{([\s\S]*?)\n\}\)/)
  if (!m) throw new Error('curtain_calc.py 里找不到 DEFAULT_CRAFT_CALC_CONFIG 的键块（真值源取不到）')
  return [...m[1].matchAll(/"([a-z_]+)":/g)].map((x) => x[1])
}

/** 说明模块里**全部静态文案**（判据 5 的扫描面；算例数字**不在**其中 —— 那些由真值渲染） */
function allCopyStrings(): string[] {
  const out: string[] = []
  for (const c of Object.values(CALC_PARAM_COPY)) out.push(c.label, c.hint, c.impact)
  for (const t of [...AUTO_FEATURE_TERMS, ...MANUAL_FEATURE_TERMS, ...TERM_FAMILY]) {
    out.push(t.definition, t.impact, t.criterion ?? '', t.boundary ?? '')
  }
  for (const f of GLOSSARY_FORMULAS) out.push(f.name, f.formula, f.note)
  return out
}

describe('算料配置页·口径与术语说明（issue #4975）', () => {
  it('判据 1：引擎每个配置键都有页面文案（新增键不补文案 ⇒ 红）', () => {
    const missing = engineConfigKeys().filter((k) => !(k in CALC_PARAM_COPY))
    // 注入：在引擎 DEFAULT_CRAFT_CALC_CONFIG 里加 `"hem_margin": HEM_MARGIN,` 而不补文案 ⇒ 本断言红
    expect(missing).toEqual([])
  })

  it('判据 1b：六个标量键与说明模块的标量清单**逐值一致**（少一个 = 表单少一个输入框）', () => {
    const engineScalarKeys = engineConfigKeys().filter((k) => CALC_SCALAR_KEYS.includes(k as never))
    expect([...CALC_SCALAR_KEYS].sort()).toEqual(engineScalarKeys.sort())
  })

  it('判据 2：side_margin 的口径是「左右覆盖余量」，不是「上下卷边」（issue #4940）', () => {
    const copy = CALC_PARAM_COPY.side_margin
    const text = `${copy.label}${copy.hint}${copy.impact}`
    // 注入：把 hint 改回「定宽买高的上下卷边合计」⇒ 下面两条红（这正是改前的线上文案）
    expect(text).toContain('左右')
    expect(text).not.toContain('上下卷边')
  })

  it('判据 2b：上下卷边归 hem_margin 语义 —— SIDE_MARGIN 常量行讲的是左右余量（读源自证）', () => {
    const line = engineSrc.split('\n').find((l) => /^SIDE_MARGIN\s*=/.test(l))
    if (!line) throw new Error('curtain_calc.py 里找不到 SIDE_MARGIN 的常量定义行')
    // 判据的基准取自引擎自己的语义注释 ⇒ 文案不可能比引擎"更对"
    expect(line).toContain('左右覆盖余量')
    expect(line).not.toContain('上下卷边')
  })

  it('判据 3：页面不再自带第二份口径（改成引用说明模块 + 文案由模块派生）', () => {
    // 注入：把页面里的 CALC_PARAM_COPY 换回自带数组 ⇒ 第一条红
    expect(pageSrc).toContain('CALC_PARAM_COPY')
    // 注入：把 `CALC_SCALAR_KEYS.map(...)` 换回手写数组（= 页面又持有第二份文案）⇒ 红
    expect(pageSrc).toContain('CALC_SCALAR_KEYS.map')
    // 注入：把旧 hint 抄回页面（`hint: '定宽买高的上下卷边合计'`）⇒ 红
    //（页面注释里**引用**旧文案作为历史记录是允许的 ⇒ 只钉"作为字段值出现"这一形态）
    expect(pageSrc).not.toContain("hint: '定宽买高的上下卷边合计'")
    // 参数旁的「说明」锚点必须由 f.anchor 驱动（而不是手写死的 id 列表）
    expect(pageSrc).toContain('f.anchor')
  })

  it('判据 3b：后端契约类型里 side_margin 的注释同口径（第三处漂移点）', () => {
    const line = typesSrc.split('\n').find((l) => l.includes('side_margin: number'))
    if (!line) throw new Error('types/index.ts 里找不到 side_margin 字段')
    // 注释在字段**上一行**
    const idx = typesSrc.split('\n').indexOf(line)
    const comment = typesSrc.split('\n')[idx - 1]
    expect(comment).toContain('左右')
    expect(comment).not.toContain('上下卷边')
  })

  it('判据 4：引擎配置字典里 side_margin 那行注释也不得再说「上下卷边」', () => {
    const line = engineSrc.split('\n').find((l) => l.includes('"side_margin": SIDE_MARGIN'))
    if (!line) throw new Error('curtain_calc.py 里找不到 DEFAULT_CRAFT_CALC_CONFIG 的 side_margin 行')
    // 注入：把这行注释改回「# 定宽买高上下卷边（米）」⇒ 本断言红（改前实测即此形态）
    expect(line).toContain('左右')
    expect(line).not.toContain('上下卷边')
  })

  it('判据 5：说明文案里不出现数字（数值一律由真值渲染 ⇒ 杜绝第二份口径）', () => {
    const offenders = allCopyStrings().filter((s) => /[0-9]/.test(s))
    // 注入：把 hint 写成「每折吃布 0.25 米」⇒ 本断言红
    expect(offenders).toEqual([])
  })

  it('判据 6：自动推算算例 = detectAutoFeatures 的真实输出（与下单页同源同函数）', () => {
    const config = ENGINE_DEFAULT_CALC_CONFIG
    const byName = Object.fromEntries(buildAutoFeatureExamples(config).map((e) => [e.name, e.reason]))

    const expectedHeight = detectAutoFeatures({
      height: GLOSSARY_EXAMPLE.height,
      doorWidth: GLOSSARY_EXAMPLE.doorWidth,
      cuttingMode: '定高买宽',
    }).find((f) => f.name === '超高')
    const expectedWidth = detectAutoFeatures({
      width: GLOSSARY_EXAMPLE.width,
      fullness: config.tiers.standard.fullness,
      doorWidth: GLOSSARY_EXAMPLE.doorWidth,
      cuttingMode: '定宽买高',
    })
    if (!expectedHeight) throw new Error('举例输入没能推出「超高」—— 举例参数已失效（判据失去意义）')

    // 注入：算例文案改成自己拼（不调 detectAutoFeatures）⇒ 下面三条红
    expect(byName['超高']).toBe(expectedHeight.reason)
    expect(byName['超宽']).toBe(expectedWidth.find((f) => f.name === '超宽')?.reason)
    expect(byName['倒幅']).toBe(expectedWidth.find((f) => f.name === '倒幅')?.reason)
  })

  it('判据 6b：算例覆盖三个自动推算特征，且顺序与 AUTO_FEATURE_NAMES 同源', () => {
    const names = buildAutoFeatureExamples(ENGINE_DEFAULT_CALC_CONFIG).map((e) => e.name)
    // 注入：把「超宽」举例删掉 / 举例宽度改到推不出来 / 顺序与清单分叉 ⇒ 红
    expect(names).toEqual([...AUTO_FEATURE_NAMES])
  })

  it('判据 7：拼接 / 接高写明「系统不推算」+「不触发工序」（死亡条件绑 #4569）', () => {
    const joined = MANUAL_FEATURE_TERMS.map((t) => `${t.definition}${t.impact}${t.boundary ?? ''}`).join('')
    // 注入：删掉「系统不推算」⇒ 红（否则商家以为勾了加工项就会自动排工序）
    expect(joined).toContain('系统不推算')
    // ⚠️ 死亡条件：issue #4569 一旦裁定「加工项也触发工序」⇒ 本断言必须改判（当前口径 = 只计价）
    expect(joined).toContain('不触发工序')
  })

  it('判据 7b：接高的「双眼皮接高」照实写「待查明」，不凭字面编解释', () => {
    const jiegao = MANUAL_FEATURE_TERMS.find((t) => t.name === '接高')
    if (!jiegao) throw new Error('手选术语里缺「接高」')
    expect(jiegao.boundary ?? '').toContain('待查明')
  })

  it('判据 8：术语覆盖清单齐全（自动推算三项 + 手选两项 + 近义词族）', () => {
    // 注入：删掉任一条 ⇒ 对应断言红
    expect(AUTO_FEATURE_TERMS.map((t) => t.name).slice().sort()).toEqual([...AUTO_FEATURE_NAMES].slice().sort())
    expect(MANUAL_FEATURE_TERMS.map((t) => t.name).slice().sort()).toEqual(['拼接', '接高'])
    const family = TERM_FAMILY.map((t) => t.name)
    for (const name of ['正幅', '定型', '拼色', '拼N次', '对缝']) {
      expect(family).toContain(name)
    }
  })

  it('判据 8b：每个术语 / 参数都有唯一锚点（页面「说明」链接不会指空）', () => {
    const anchors = [
      ...Object.keys(CALC_PARAM_COPY).map(glossaryAnchorOf),
      ...[...AUTO_FEATURE_TERMS, ...MANUAL_FEATURE_TERMS, ...TERM_FAMILY].map((t) =>
        glossaryTermAnchorOf(t.name)
      ),
    ]
    expect(new Set(anchors).size).toBe(anchors.length)
    expect(anchors.every((a) => a.startsWith('glossary-'))).toBe(true)
  })

  it('判据 9：说明模块不得复活「缺省门幅」（issue #4877 的反向守卫）', () => {
    // 注入：在说明模块里写回 `DEFAULT_DOOR_WIDTH` / `resolveDoorWidth` ⇒ 前两条红
    expect(glossarySrc).not.toContain('DEFAULT_DOOR_WIDTH')
    expect(glossarySrc).not.toContain('resolveDoorWidth')
    // 算例用的门幅必须**明说**「随商品而变」+「没有缺省门幅」，否则它会被读成缺省门幅
    const terms = [...AUTO_FEATURE_TERMS].map((t) => `${t.criterion ?? ''}${t.boundary ?? ''}`).join('')
    expect(terms).toContain('没有缺省门幅')
  })
})
