// case_ids: OR-040, OR-041
/**
 * 「算料配置」页的**口径与术语说明**（issue #4975）—— 单一真值模块的跨源守卫。
 *
 * 复用既有用例（不新增用例 ID，理由同 `OperationsProvenance.test.tsx` 的先例：新增用例会触发
 * case-trust burn-down 预算 + 与生成物争抢）：
 * - **OR-040** = 下单页系统识别 / 余量常量语义（`HEM_MARGIN` 上下卷边；宽方向的「左右覆盖余量」
 *   `SIDE_MARGIN` 已随 issue #5030 **整体退场**）；
 * - **OR-041** = 算料公式按工艺派生 + 逐片口径 + 向上进位（= 本页这些参数的消费方）。
 *
 * ## 本文件治的缺陷形态（每一条都能单独判红）
 *
 * | # | 判据 | 红证（怎么让它红） |
 * |---|---|---|
 * | 1 | 引擎配置键集 ⊆ 说明键集 | 在 `DEFAULT_CRAFT_CALC_CONFIG` 加一个键而不补文案 ⇒ 红 |
 * | 2 | `side_margin` **整体退场**（键集 / 文案 / types / 引擎配置字典 / 迁移列五处都不存在） | 任一处把它加回来 ⇒ 红（= #5030 的反向守卫） |
 * | 3 | 页面**不再自带第二份口径** | 页面里再出现旧文案字面量 / 不再引用说明模块 ⇒ 红 |
 * | 4 | 引擎配置字典**不再有** `side_margin` 键；**只剩** `hem_margin`（上下卷边） | 把 `"side_margin": SIDE_MARGIN` 加回引擎 ⇒ 红 |
 * | 5 | 说明文案里**不出现数字** | 在任一文案里写死 `0.25` 之类的值 ⇒ 红（数值只许来自真值） |
 * | 6 | 自动推算算例 = **服务端判定**的**逐字转发**（issue #5036 包 2a） | 算例文案自己拼 / 不走服务端返回 ⇒ 红 |
 * | 7 | 拼接 / 接高写明「系统不推算」「不触发工序」 | 删掉任一句 ⇒ 红（**死亡条件**见下） |
 * | 8 | 术语覆盖清单齐全 | 少一个术语 ⇒ 红 |
 *
 * ⚠️ **判据 7 是死亡条件式的**：它钉的是**当下**口径（加工项特征不触发工序）。
 * 一旦 issue #4569 裁定改为「也触发工序」，**这条必须连同文案一起改判** —— 它不是"永真"断言。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { AUTO_FEATURE_NAMES } from '@/lib/craft-auto-features'
import { SPECIAL_OPTIONS } from '@/lib/order-craft-fields'
import {
  AUTO_FEATURE_TERMS,
  CALC_PARAM_COPY,
  CALC_SCALAR_KEYS,
  GLOSSARY_FORMULAS,
  GLOSSARY_EXAMPLE,
  MANUAL_FEATURE_TERMS,
  SPECIAL_OPTION_TERMS,
  TERM_FAMILY,
  buildAutoFeatureExamples,
  glossaryAnchorOf,
  glossaryOptionAnchorOf,
  glossaryTermAnchorOf,
} from '@/lib/craft-calc-glossary'
import type { CraftCalcConfig } from '@/types'

/**
 * 服务端替身返回（判据 6 用）—— **故意**用「只有服务端会产出的措辞」：
 * 若本模块自己拼文案，这三条断言必红（这才是「逐字转发」的判别力）。
 */
const SERVER_FIXED_HEIGHT = [{ name: '超高', source: '推算', reason: '服务端给的超高依据' }]
const SERVER_FIXED_WIDTH = [
  { name: '超宽', source: '推算', reason: '服务端给的超宽依据' },
  { name: '倒幅', source: '推算', reason: '服务端给的倒幅依据' },
]

/** 算料引擎源（**真值源**）：`backend/ai-agent-service/app/tools/curtain_calc.py` */
const CALC_SRC = resolve(__dirname, '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py')
const engineSrc = readFileSync(CALC_SRC, 'utf8')

/** 「算料配置」tab 所在页面（第二份口径的**可能落点**，必须钉住） */
const PAGE_SRC = resolve(__dirname, '../../../src/app/(dashboard)/production/routings/page.tsx')
const pageSrc = readFileSync(PAGE_SRC, 'utf8')

/** 后端契约类型（`hem_margin` 的口径注释在守卫范围内；`side_margin` 应已整体退场） */
const TYPES_SRC = resolve(__dirname, '../../../src/types/index.ts')
const typesSrc = readFileSync(TYPES_SRC, 'utf8')

/** 后端迁移目录 + bootstrap 终态（**反向守卫**：`side_margin` 列不得残留，issue #5030） */
const MIGRATION_DIR = resolve(
  __dirname,
  '../../../../../backend/admin-api/src/main/resources/db/migration-archive'
)
const SCHEMA_SRC = resolve(__dirname, '../../../../../backend/admin-api/src/main/resources/db/init/schema.sql')
const schemaSrc = readFileSync(SCHEMA_SRC, 'utf8')

/** Java 侧（实体 + 写面）—— 键集/字段同属跨源收敛面 */
const JAVA_ENTITY_SRC = resolve(
  __dirname,
  '../../../../../backend/admin-api/src/main/java/com/migao/admin/entity/CraftCalcConfig.java'
)
const JAVA_SERVICE_SRC = resolve(
  __dirname,
  '../../../../../backend/admin-api/src/main/java/com/migao/admin/service/CraftCalcConfigService.java'
)

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
  hem_margin: 0.3,
  meters_rounding_step: 0.1,
  // 🔴 issue #5130：两个**企业阈值**（超宽 / 超高判据）—— 缺了它们，算例的 `given` 渲染不出来
  oversize_width_threshold: 6,
  oversize_height_threshold: 4,
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

/**
 * 引擎侧**非标量**（结构化）配置键 —— 它们不进「标量表单」，故**不在** `CALC_SCALAR_KEYS` 里。
 *
 * 🔴 **这份清单必须显式**（issue #5137）：靠 `CALC_SCALAR_KEYS.includes()` 反推「哪些引擎键是标量」
 * 是**循环定义** —— 被测清单自己定义自己 ⇒「引擎新增标量键而清单没加」这一形态**恒真**（假绿）。
 */
const NON_SCALAR_ENGINE_KEYS = ['per_fold_mixed_times', 'tiers', 'default_formula'] as const

describe('算料配置页·口径与术语说明（issue #4975）', () => {
  it('判据 1：引擎每个配置键都有页面文案（新增键不补文案 ⇒ 红）', () => {
    const missing = engineConfigKeys().filter((k) => !(k in CALC_PARAM_COPY))
    // 注入：在引擎 DEFAULT_CRAFT_CALC_CONFIG 里加 `"hem_margin": HEM_MARGIN,` 而不补文案 ⇒ 本断言红
    expect(missing).toEqual([])
  })

  // 🔴 **issue #5137 修正（独立核验红证）**：原实现是
  // `engineConfigKeys().filter((k) => CALC_SCALAR_KEYS.includes(k))` —— **先取交集再比较**
  // ⇒ 「引擎有而清单没有」这个方向**恒真**。实测形态：注入新引擎键 + 补 `CALC_PARAM_COPY` 文案、
  // 但**不加进 `CALC_SCALAR_KEYS`** ⇒ 本文件 26/26 全绿（守卫对最该抓的形态失灵）。
  // 修法 = 用**显式**的非标量清单反推「哪些引擎键是标量」，**不拿被守卫的清单自己定义自己**。
  it('判据 1b：引擎标量键集 ↔ 说明模块的标量清单 **双向相等**（少一个 = 表单少一个输入框）', () => {
    const engineScalarKeys = engineConfigKeys().filter(
      (k) => !(NON_SCALAR_ENGINE_KEYS as readonly string[]).includes(k)
    )
    expect([...CALC_SCALAR_KEYS].sort()).toEqual(engineScalarKeys.sort())
    // 🔴 #5030 反向守卫：`side_margin` 已从两侧键集退场 —— 任一侧加回 ⇒ 本断言红
    expect([...CALC_SCALAR_KEYS]).not.toContain('side_margin')
    expect(engineConfigKeys()).not.toContain('side_margin')
  })

  // 🔴 **判据 1b 的红证**（issue #5137）：证明上面那条**不是空断言** ——
  // 把「引擎标量键集」做坏（多一个 `brand_new_scalar`）⇒ **同一个比较式必须不等**。
  // ⚠️ 这条红证在**修正前**的写法下会**失败**（旧式取交集 ⇒ 恒相等）⇒ 它对本修正是有判别力的。
  it('判据 1b 红证：引擎多一个标量键而清单没加 ⇒ 同一比较式必须判不等', () => {
    const injected = [...engineConfigKeys(), 'brand_new_scalar']
    const engineScalarKeys = injected.filter(
      (k) => !(NON_SCALAR_ENGINE_KEYS as readonly string[]).includes(k)
    )
    expect(engineScalarKeys).toContain('brand_new_scalar')
    expect([...CALC_SCALAR_KEYS].sort()).not.toEqual(engineScalarKeys.sort())
  })

  // 🔴 **issue #5137 补一条此前全仓没有的守卫**：`CALC_PARAM_COPY` 的键集必须被
  // 「标量键 ∪ 非标量键」**盖住** —— 否则文案表会出现**两边都没有**的孤儿键（各自漂移）。
  it('判据 1c：`CALC_PARAM_COPY` 的键集必须 ⊆ 标量键 ∪ 非标量键（不得有孤儿文案）', () => {
    const allowed = new Set<string>([...CALC_SCALAR_KEYS, ...NON_SCALAR_ENGINE_KEYS])
    const orphans = Object.keys(CALC_PARAM_COPY).filter((k) => !allowed.has(k))
    expect(orphans).toEqual([])
    // 反向自证（守卫非空转）：往「两边都没有」塞一个键 ⇒ 必须被抓出来
    expect([...allowed, 'ghost_key'].filter((k) => !allowed.has(k))).toEqual(['ghost_key'])
    // 且两个方向都要在面内：真实存在的非标量键确实是**允许**的（不是把面收成「仅标量键」）
    expect(Object.keys(CALC_PARAM_COPY)).toContain(NON_SCALAR_ENGINE_KEYS[1])
  })

  // 🔴 issue #5030 改判（用户 2026-09-21 裁定：「订单里的宽和高是窗户的宽高」⇒ 用料 = 窗宽 × 褶倍，
  // 不再另加左右覆盖余量）。原判据 2「`side_margin` 的口径 = 左右覆盖余量」的**前提已消失**
  // （键与常量都没了）⇒ 改成**同强度的反向守卫**：五处都不得再有这个键。
  // 红证（逐处可单独判红）：① `CALC_SCALAR_KEYS` 加回 `'side_margin'`；② `CALC_PARAM_COPY` 加回条目；
  // ③ `types/index.ts` 加回 `side_margin: number`；④ 引擎 `DEFAULT_CRAFT_CALC_CONFIG` 加回该键；
  // ⑤ 新增迁移里再出现 `ADD COLUMN … side_margin`。
  it('判据 2：`side_margin` **整体退场** —— 键集 / 文案 / types / 引擎配置字典都不存在（#5030 反向守卫）', () => {
    expect([...CALC_SCALAR_KEYS]).not.toContain('side_margin')
    expect(Object.keys(CALC_PARAM_COPY)).not.toContain('side_margin')
    expect(typesSrc).not.toContain('side_margin')
    expect(engineConfigKeys()).not.toContain('side_margin')
    // 反向自证（守卫非空转）：同一形态的**仍在场**的键必须能被这些断言面看见
    expect(typesSrc).toContain('hem_margin')
    expect(engineConfigKeys()).toContain('hem_margin')
  })

  it('判据 2b：高方向的 `hem_margin`（上下卷边）**仍在场**且口径未变（#5030 只退场宽方向）', () => {
    const copy = CALC_PARAM_COPY.hem_margin
    const text = `${copy.label}${copy.hint}${copy.impact}`
    // 注入：把 `hem_margin` 也一起删掉（或把文案改成宽方向语义）⇒ 红
    expect(text).toContain('上下卷边')
    expect(text).toContain('高方向')
    // 引擎侧自证：常量定义行与语义注释逐字一致（读源，不抄现值）
    const line = engineSrc.split('\n').find((l) => /^HEM_MARGIN\s*=/.test(l))
    if (!line) throw new Error('curtain_calc.py 里找不到 HEM_MARGIN 的常量定义行')
    expect(line).toContain('上下卷边')
  })

  it('判据 2c：后端侧 `side_margin` 同样退场 —— 迁移 / bootstrap schema / Java 实体与写面（#5030）', () => {
    // 迁移目录：不得有任何**新增**迁移再建/再写这一列。
    // ⚠️ V80 是**历史**建表迁移（当时的快照就是有这一列），V112 才是删它的那一条 ⇒ 只钉
    // 「V80 之后的文件里再出现 ADD COLUMN / INSERT 该列」这一形态（拿 V80 当 offender = 假红）。
    const migrationFiles = readdirSync(MIGRATION_DIR).filter((f) => f.endsWith('.sql'))
    // 自证解析面非空（目录读错 ⇒ 本守卫必须红，不静默空跑）
    expect(migrationFiles.length).toBeGreaterThan(50)
    const V80 = 'V80__create_craft_calc_configs.sql'
    expect(migrationFiles).toContain(V80)
    // V80 确实建过这一列（否则「后续不得再出现」这条判据就失去了前提，会变成空断言）
    expect(readFileSync(resolve(MIGRATION_DIR, V80), 'utf8')).toMatch(/side_margin\s+NUMERIC/i)
    const offenders = migrationFiles
      .filter((f) => f !== V80)
      .filter((f) => {
        // 只看**可执行 SQL**（行首非注释）—— 注释里写回滚样例（V112 就有）不算复活
        const executable = readFileSync(resolve(MIGRATION_DIR, f), 'utf8')
          .split('\n')
          .filter((l) => !/^\s*--/.test(l))
          .join('\n')
        return /ADD COLUMN[^;]*side_margin/i.test(executable)
      })
    expect(offenders).toEqual([])
    // 删列那一条必须在（回滚/重放路径靠它；删掉 ⇒ 存量库永远带着一列无消费者的参数）
    expect(migrationFiles).toContain('V112__drop_craft_calc_side_margin.sql')
    // bootstrap 终态：`side_margin` 只许出现在注释里（真实列定义形如 `side_margin NUMERIC(6,3)`）
    expect(schemaSrc).not.toMatch(/^\s*side_margin\s+[A-Z]/m)
    expect(schemaSrc).toContain('hem_margin')
    // Java 实体 + 写面：字段与键集都不得残留
    const javaEntity = readFileSync(JAVA_ENTITY_SRC, 'utf8')
    const javaService = readFileSync(JAVA_SERVICE_SRC, 'utf8')
    expect(javaEntity).not.toContain('sideMargin')
    expect(javaService).not.toContain('side_margin')
    // 反向自证：同一个写面的**仍在场**的键必须能被看见（否则上面两条是空断言）
    expect(javaService).toContain('hem_margin')
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

  // 🔴 #5030 改判：原判据 3b 钉的是「types 里 `side_margin` 的注释口径」—— 该字段已删 ⇒
  // 前提消失 ⇒ 改成**同强度的反向守卫**：types 里不得再有这个字段/标识。
  it('判据 3b：后端契约类型里 `side_margin` 字段**已删**（不得残留字段或注释）（#5030）', () => {
    expect(typesSrc).not.toContain('side_margin')
    // 反向自证：同一接口里**仍在场**的高方向字段必须能被看见（否则上一条是空断言）
    expect(typesSrc).toContain('hem_margin: number')
  })

  // 🔴 #5030 改判：原判据 4 钉「引擎配置字典里 side_margin 那行注释不得说『上下卷边』」——
  // 该键已从 `DEFAULT_CRAFT_CALC_CONFIG` 删除 ⇒ 前提消失 ⇒ 改成**同强度的反向守卫**。
  it('判据 4：引擎配置字典里**不再有** `side_margin` 键；只剩 `hem_margin`（#5030）', () => {
    expect(engineConfigKeys()).not.toContain('side_margin')
    expect(engineSrc).not.toContain('"side_margin"')
    // 反向自证：高方向那行仍在（否则「没有 side_margin」可能只是整块被删）
    const line = engineSrc.split('\n').find((l) => l.includes('"hem_margin": HEM_MARGIN'))
    if (!line) throw new Error('curtain_calc.py 里找不到 DEFAULT_CRAFT_CALC_CONFIG 的 hem_margin 行')
    expect(line).toContain('上下卷边')
  })

  it('判据 5：说明文案里不出现数字（数值一律由真值渲染 ⇒ 杜绝第二份口径）', () => {
    const offenders = allCopyStrings().filter((s) => /[0-9]/.test(s))
    // 注入：把 hint 写成「每折吃布 0.25 米」⇒ 本断言红
    expect(offenders).toEqual([])
  })

  it('判据 6：算例 reason **逐字转发**服务端返回（本模块不自己拼 —— issue #5036 包 2a）', () => {
    const config = ENGINE_DEFAULT_CALC_CONFIG
    const byName = Object.fromEntries(
      buildAutoFeatureExamples(config, SERVER_FIXED_HEIGHT, SERVER_FIXED_WIDTH).map((e) => [e.name, e.reason])
    )
    // 注入：算例文案改成自己拼（不走服务端返回）⇒ 下面三条红
    expect(byName['超高']).toBe('服务端给的超高依据')
    expect(byName['超宽']).toBe('服务端给的超宽依据')
    expect(byName['倒幅']).toBe('服务端给的倒幅依据')
  })

  it('判据 6b：算例覆盖三个自动推算特征，且顺序与 AUTO_FEATURE_NAMES 同源', () => {
    const names = buildAutoFeatureExamples(
      ENGINE_DEFAULT_CALC_CONFIG,
      SERVER_FIXED_HEIGHT,
      SERVER_FIXED_WIDTH
    ).map((e) => e.name)
    // 注入：把「超宽」举例删掉 / 顺序与清单分叉 ⇒ 红
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

  it('判据 9：说明模块不得复活「缺省门幅」；特征判据**不得**再引用门幅 / 褶倍（#4877 + #5130 反向守卫）', () => {
    // 注入：在说明模块里写回 `DEFAULT_DOOR_WIDTH` / `resolveDoorWidth` ⇒ 前两条红
    expect(glossarySrc).not.toContain('DEFAULT_DOOR_WIDTH')
    expect(glossarySrc).not.toContain('resolveDoorWidth')
    // 🔴 **issue #5130 改判**：旧判据钉的是「算例用的门幅必须明说『随商品而变』+『没有缺省门幅』」——
    // 算例的 `doorWidth` 已随判定面改判**删除**（判定面不再读门幅）⇒ 该前提消失。
    // 改成**同强度的反向守卫**：`超高` / `超宽` 的**判据文案**里不得再出现「门幅」或「褶倍」
    // （旧判据「与门幅比 / 含褶倍」复活 ⇒ 红），且必须写明判据是「**阈值**」（企业参数）。
    const terms = [...AUTO_FEATURE_TERMS].map((t) => `${t.criterion ?? ''}${t.boundary ?? ''}`).join('')
    // 反向自证：正文字面里仍有「门幅」这个概念可被扫到（否则 `not.toContain` 是空断言）
    expect(glossarySrc).toContain('门幅')
    expect(terms).toContain('阈值')
    expect(terms).not.toContain('门幅')
    expect(terms).not.toContain('褶倍')
    // 算例的示例门幅常量也不得回来（`GLOSSARY_EXAMPLE` 里那个字段已删，取的是净窗宽 / 净窗高）
    expect(GLOSSARY_EXAMPLE).not.toHaveProperty('doorWidth')
    expect(GLOSSARY_EXAMPLE.width).toBeGreaterThan(0)
    expect(GLOSSARY_EXAMPLE.height).toBeGreaterThan(0)
  })
})

// ────────────────────────── 特殊选项术语（issue #4986） ──────────────────────────

/** 工序路线真值源：`SPECIAL_OPTION_ROUTINGS` = 特殊选项 → 条件工序的**唯一**映射 */
const ROUTING_SRC = resolve(__dirname, '../../../../../backend/ai-agent-service/app/production/routing.py')
const routingSrc = readFileSync(ROUTING_SRC, 'utf8')

/** 从真值源里取「特殊选项 → 条件工序 + 锚点」（读源，不写死任何一条） */
function routingEntries(): Record<string, { operation: string; after: string }> {
  const block = routingSrc.match(/SPECIAL_OPTION_ROUTINGS[^=]*=\s*\{([\s\S]*?)\n\}/)
  if (!block) throw new Error('routing.py 里找不到 SPECIAL_OPTION_ROUTINGS（真值源取不到）')
  const out: Record<string, { operation: string; after: string }> = {}
  for (const m of block[1].matchAll(/"([^"]+)":\s*\{"operation":\s*"([^"]+)",\s*"after":\s*"([^"]+)"\}/g)) {
    out[m[1]] = { operation: m[2], after: m[3] }
  }
  return out
}

describe('特殊选项术语（issue #4986）', () => {
  /**
   * 剔除文案里的**标识符**（选项名 / 工序名 / 锚点工序名）—— 它们本身可能含数字
   * （`拼1次-布`），但那不是「写死了数值」。判据 6 的扫描面 = 剔除后的**剩余文本**。
   */
  function withoutIdentifiers(text: string): string {
    let out = text
    for (const id of SPECIAL_OPTION_TERMS.flatMap((t) => [t.name, t.operation ?? '', t.after ?? ''])) {
      if (id !== '') out = out.split(id).join('')
    }
    return out
  }

  /**
   * 变体名 → **逻辑名**（`拼1次-布` ⇒ `拼1次`）。
   *
   * 真值源 `SPECIAL_OPTION_ROUTINGS` 给的是**变体名**（按部位派生），而前端**只许写逻辑名**
   * （硬编码变体名 = 把部位写死）—— 守卫 `tests/unit_ci_workflows/test_op_name_registry_guard.py`
   * 判据① 直接判红（本模块第一版就是被它抓到的）。
   */
  function logicalOf(name: string): string {
    return name.split('-')[0]
  }

  it('判据 1：六个术语逐字取自真实特殊选项清单（清单改名/删项 ⇒ 红）', () => {
    const missing = SPECIAL_OPTION_TERMS.map((t) => t.name).filter(
      (n) => !(SPECIAL_OPTIONS as readonly string[]).includes(n)
    )
    // 注入：把「一分为二」从 SPECIAL_OPTIONS 删掉（或说明里写错一个字）⇒ 红
    expect(missing).toEqual([])
    // 用户点名的就是这六个（多一个/少一个 ⇒ 红）
    expect(SPECIAL_OPTION_TERMS.map((t) => t.name)).toEqual([
      '拼1次',
      '拼2次',
      '拼3次',
      '接高',
      '双眼皮接高',
      '一分为二',
    ])
  })

  it('判据 2：说明里的工序映射与 routing.py 逐值一致（**逻辑名**；改一处必红）', () => {
    const entries = routingEntries()
    for (const term of SPECIAL_OPTION_TERMS) {
      if (term.operation === null) {
        // 不加工序的选项**不得**出现在映射表里（否则说明与实现相反）
        expect(Object.keys(entries)).not.toContain(term.name)
        continue
      }
      // 注入：把「接高」的锚点从 精裁 改成 布三边 ⇒ 下面两条红
      expect(term.operation).toBe(logicalOf(entries[term.name].operation))
      expect(term.after).toBe(logicalOf(entries[term.name].after))
    }
  })

  it('判据 2b：说明里**不得出现变体名**（部位后缀 `-布` / `-纱` / `-帘头` / `-布料`）', () => {
    // 与 Python 守卫 test_op_name_registry_guard.py 判据① 同口径（前端源码全域扫描）——
    // 本模块第一版把「拼1次-布」写进说明，正是被那条守卫抓到的。
    const offenders = SPECIAL_OPTION_TERMS.flatMap((t) => [
      t.operation ?? '',
      t.after ?? '',
      t.definition,
      t.impact,
      t.boundary ?? '',
    ]).filter((s) => /-(布|纱|帘头|布料)/.test(s))
    expect(offenders).toEqual([])
  })

  it('判据 3：拼3次写明「用料系数未登记 ⇒ 不插值、不静默退回单色」', () => {
    const t = SPECIAL_OPTION_TERMS.find((x) => x.name === '拼3次')
    if (!t) throw new Error('特殊选项术语里缺「拼3次」')
    const text = `${t.impact}${t.boundary ?? ''}`
    // 注入：把这段边界删掉 ⇒ 红（商家会以为拼3次与拼2次一样有系数）
    expect(text).toContain('未登记')
    expect(text).toContain('不插值')
  })

  it('判据 4：双眼皮接高 = 与「接高」同一道工序 + 含义待查明', () => {
    const a = SPECIAL_OPTION_TERMS.find((x) => x.name === '接高')
    const b = SPECIAL_OPTION_TERMS.find((x) => x.name === '双眼皮接高')
    if (!a || !b) throw new Error('特殊选项术语里缺「接高」或「双眼皮接高」')
    // 注入：给「双眼皮接高」编一道自己的工序 ⇒ 红（真值源里它映射到同一道）
    expect(b.operation).toBe(a.operation)
    expect(b.after).toBe(a.after)
    // 含义未查明 ⇒ 照实写，不凭字面推
    expect(b.boundary ?? '').toContain('待查明')
  })

  it('判据 5：一分为二 = 不加工序 / 只有历史计件系数（三层写清）', () => {
    const t = SPECIAL_OPTION_TERMS.find((x) => x.name === '一分为二')
    if (!t) throw new Error('特殊选项术语里缺「一分为二」')
    // 注入：给它写一道工序 / 加上「用料」层 ⇒ 红
    expect(t.operation).toBeNull()
    expect(t.layers).toEqual(['计件'])
    // 自 #4589 起零消费（新报工不乘、历史快照仍乘）—— 不写这句会让商家以为现在还乘系数
    expect(`${t.definition}${t.impact}${t.boundary ?? ''}`).toContain('零消费')
  })

  it('判据 6：文案里不出现**数值**（沿用 #4975 的纪律）', () => {
    // ⚠️ 选项名 / 工序名**本身**含数字（`拼1次-布`）—— 它们是**标识符**、不是数值
    // ⇒ 扫描前先剔除全部标识符（否则是**误红**：把正确的工序名判成"写死了数字"）
    const offenders = SPECIAL_OPTION_TERMS.flatMap((t) =>
      [t.definition, t.impact, t.boundary ?? ''].map(withoutIdentifiers)
    ).filter((s) => /[0-9]/.test(s))
    expect(offenders).toEqual([])
  })

  it('判据 6b：数值扫描**非空转**（注入一个数值 ⇒ 必须被抓到）', () => {
    // 红证卫生（本仓纪律）：断言要能红 —— 把 0.65 这类**数值**写进文案即命中
    expect(/[0-9]/.test(withoutIdentifiers('拼色每折吃布 0.65 米'))).toBe(true)
    // 反向：合法文案（只含标识符）不得被误判
    expect(/[0-9]/.test(withoutIdentifiers('插条件工序「拼1次-布」'))).toBe(false)
  })

  it('判据 7：每个术语至少影响一层（不许出现「什么都不影响」的说明）', () => {
    for (const t of SPECIAL_OPTION_TERMS) {
      expect(t.layers.length).toBeGreaterThan(0)
    }
  })

  it('判据 8：锚点走**独立命名空间**（「接高」两组都有 ⇒ 不能共用 id）', () => {
    const anchors = SPECIAL_OPTION_TERMS.map((t) => glossaryOptionAnchorOf(t.name))
    expect(new Set(anchors).size).toBe(anchors.length)
    // 注入：把特殊选项也挂到 `glossary-term-*` ⇒ 与「手选特征」组的「接高」抢同一个 DOM id ⇒ 红
    const manual = MANUAL_FEATURE_TERMS.map((t) => glossaryTermAnchorOf(t.name))
    expect(anchors.filter((a) => manual.includes(a))).toEqual([])
  })
})
