// case_ids: OR-040
/**
 * 下单页自动识别的**前端半边**（issue #4526 包 B；issue #5009 = #4976 包 2 **改判**）。
 *
 * 用户 2026-09-19：「**超高 / 超宽是和门幅标准比较的**，客户报的数据和门幅对比后能
 * **自动区分**出来是超高还是超宽，**这个要求做到自动识别**」；
 * 用户 2026-09-21 裁定 **B「判定移到服务端」**（前端只展示服务端结论）。
 *
 * ## 🔴 本文件的职责在 #5009 **改判**（原职责 = 钉前端判定规则，已随实现一起退场）
 *
 * 原文件逐条钉 `detectAutoFeatures` 的判定表。包 2 把判定搬到服务端
 * （`backend/ai-agent-service/app/tools/curtain_calc.py` 的 `detect_auto_features`，
 * 经 `POST /api/admin/orders/craft-calc/auto-features` 暴露）后，**前端不再有判定实现**
 * ⇒ 本文件按**新职责**改判（**不是删掉**，判据强度不降）：
 *
 * | # | 新职责 | 红证（怎么让它红） |
 * |---|---|---|
 * | N1 | **前端不得再有本地判价入口**：模块不导出 `detectAutoFeatures` / `detectAutoFeatureNotices`，代码里不得出现门幅比较 | 把任一判定函数加回来 ⇒ 红 |
 * | N2 | 余量常量仍与引擎**逐值**一致（副本仍在，但**不在取价路径上**） | 常量改 0.31 ⇒ 红 |
 * | N3 | 两个方向**不得合并**（`SIDE_MARGIN` / `HEM_MARGIN` 各自跟自己的引擎常量） | 删掉一个 ⇒ 红 |
 * | N4 | **服务端可能给出的名字/类别必须被前端认得**（golden 表逐行：`name ∈ AUTO_FEATURE_NAMES`、`kind ∈ AUTO_FEATURE_NOTICE_KINDS`） | 引擎加一个新特征名/提示类别 ⇒ 红（否则页面**静默丢项**） |
 * | N5 | `AUTO_FEATURE_NAMES` 与加工项目录（V83）**逐值对齐**（#4592 的 P0：目录里没有的名字进组合键 ⇒ 加工费恒 ¥0.00） | 清单加 `正幅` ⇒ 红 |
 * | N6 | `AUTO_FEATURE_NOTICE_KINDS` 与引擎 `AUTO_FEATURE_NOTICE_KINDS` 逐值一致 | 引擎加类别 ⇒ 红 |
 * | N7 | `parseDoorWidth` 仍**没有缺省门幅**（#4877） | 回退到 2.8 ⇒ 红 |
 *
 * ⚠️ **迁移期等价性**（服务端结论 == 改前前端 `detectAutoFeatures`）由
 * `backend/ai-agent-service/tests/test_production/test_auto_features.py` 的
 * `TestMigrationEquivalence` **逐例逐字**对账（golden 表 = 本仓 `tests/fixtures/auto-features-migration-golden.json`）；
 * 本文件负责**前端腿**：服务端返回的行必须被本模块的清单认得（N4）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  AUTO_FEATURE_NAMES,
  AUTO_FEATURE_NOTICE_KINDS,
  HEM_MARGIN,
  SIDE_MARGIN,
  parseDoorWidth,
} from '@/lib/craft-auto-features'

/** 算料引擎源（真值源）：`backend/ai-agent-service/app/tools/curtain_calc.py` */
const CALC_SRC = resolve(
  __dirname,
  '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py'
)
const source = readFileSync(CALC_SRC, 'utf8')

/**
 * 加工项目录种子（真值源）：`backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql`。
 * issue #4592：自动推导特征会**进加工费组合键** ⇒ 清单里多一个目录没有的名字 = 商家配不出该组合
 * = 组合价永远匹配不到（P0）。
 */
const V83_SEED_SRC = readFileSync(
  resolve(
    __dirname,
    '../../../../../backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql'
  ),
  'utf8'
)

/** 迁移期等价性 golden 表（由**改前**前端实现实际执行捕获；服务端逐字对账在 Python 腿） */
const GOLDEN = JSON.parse(
  readFileSync(
    resolve(__dirname, '../../../../../tests/fixtures/auto-features-migration-golden.json'),
    'utf8'
  )
) as {
  rows: Array<{
    id: string
    auto_features: Array<{ name: string; source: string; reason: string }>
    notices: Array<{ kind: string; reason: string }>
  }>
}

/** 本模块自身（N1 的扫描面） */
const LIB_SRC = resolve(__dirname, '../../../src/lib/craft-auto-features.ts')
const libSrc = readFileSync(LIB_SRC, 'utf8')

/** 去掉 `/* … *\/` 与 `// …` —— N1 只认**代码**（注释里讲历史不算实现） */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

const libCode = stripComments(libSrc)

/** 从 Python 源里取一个模块级浮点常量（取不到 ⇒ 直接失败，不静默跳过） */
function pyConst(name: string): number {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, 'm'))
  if (!m) throw new Error(`curtain_calc.py 里找不到常量 ${name}（本守卫必须能读到真值）`)
  return Number(m[1])
}

/** 从 Python 源里取一个模块级字符串元组常量（N6 的基准；取不到 ⇒ 直接失败） */
function pyStrTuple(name: string): string[] {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*\\(([\\s\\S]*?)\\)`, 'm'))
  if (!m) throw new Error(`curtain_calc.py 里找不到元组常量 ${name}（本守卫必须能读到真值）`)
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1])
}

describe('N1 前端**不再有本地判价入口**（issue #5009 = #4976 包 2）', () => {
  it('模块不再导出 detectAutoFeatures / detectAutoFeatureNotices（判定唯一实现在引擎）', () => {
    // 红证：把任一个判定函数加回 `craft-auto-features.ts` ⇒ 本条红
    //（那时前端就有第二份判定 —— `hem_margin` 可配后必然与引擎判出两套结论）
    expect(libCode).not.toContain('detectAutoFeatures')
    expect(libCode).not.toContain('detectAutoFeatureNotices')
  })

  it('模块代码里不得出现门幅比较 / 余量算式（判定才需要它们）', () => {
    // 红证：把 `height + HEM_MARGIN > doorWidth` 这类判据加回来 ⇒ 红
    expect(libCode).not.toMatch(/>\s*doorWidth/)
    expect(libCode).not.toMatch(/HEM_MARGIN\s*[+\-*/]/)
    expect(libCode).not.toMatch(/SIDE_MARGIN\s*[+\-*/]/)
  })

  it('下单页不再引用判定函数（判定来源只能是服务端）', () => {
    // ⚠️ 去掉注释再扫：本页的**注释**里会出现这两个名字（讲「已退场」），那不算实现
    const pageSrc = stripComments(
      readFileSync(resolve(__dirname, '../../../src/app/(dashboard)/orders/new/page.tsx'), 'utf8')
    )
    // 红证：`orders/new` 再 import / 调用 `detectAutoFeatures` 构造组合键 ⇒ 红（#5009 判据 4）
    expect(pageSrc).not.toContain('detectAutoFeatures')
    expect(pageSrc).not.toContain('detectAutoFeatureNotices')
  })
})

describe('N2 / N3 余量常量 —— 仍是引擎副本，但**不在取价路径上**', () => {
  it('SIDE_MARGIN（宽方向）= curtain_calc.SIDE_MARGIN（逐值比对，漂移即红）', () => {
    expect(SIDE_MARGIN).toBe(pyConst('SIDE_MARGIN'))
  })

  it('HEM_MARGIN（高方向）= curtain_calc.HEM_MARGIN（逐值比对，漂移即红）', () => {
    expect(HEM_MARGIN).toBe(pyConst('HEM_MARGIN'))
  })

  it('#4661 两个方向各自导出、不合并（删掉 SIDE_MARGIN ⇒ 红）', () => {
    // 红证（issue #4661，修复前必红）：修复前本模块**没有** SIDE_MARGIN，
    // 且宽方向用的就是 HEM_MARGIN（两处同值 0.3 ⇒ 数值断言抓不到混用）⇒ 判据落在**名字**上。
    expect(libCode).toContain('export const SIDE_MARGIN')
    expect(libCode).toContain('export const HEM_MARGIN')
  })

  it('#5009 消费方白名单：余量常量只允许门幅规则（door-width-plan）读 —— 取价路径不得读', () => {
    // 红证：`orders/new/page.tsx` 再读 HEM_MARGIN / SIDE_MARGIN 判价 ⇒ 红
    //（判定在服务端；前端常量副本在 `hem_margin` 可配后必然与引擎判出两套结论）
    const pageSrc = stripComments(
      readFileSync(resolve(__dirname, '../../../src/app/(dashboard)/orders/new/page.tsx'), 'utf8')
    )
    expect(pageSrc).not.toContain('HEM_MARGIN')
    expect(pageSrc).not.toContain('SIDE_MARGIN')
    // 白名单消费方必须**真的**在读（否则常量成了死代码，本守卫失去判别力）
    const planSrc = readFileSync(resolve(__dirname, '../../../src/lib/door-width-plan.ts'), 'utf8')
    expect(planSrc).toContain('HEM_MARGIN')
    expect(planSrc).toContain('SIDE_MARGIN')
  })
})

describe('N4 服务端可能给出的名字/类别，前端必须认得（否则静默丢项）', () => {
  it('golden 表非空且覆盖「未知态」样本（反恒真下界）', () => {
    expect(GOLDEN.rows.length).toBeGreaterThanOrEqual(20)
    expect(GOLDEN.rows.some((r) => r.auto_features.length === 0)).toBe(true)
    expect(GOLDEN.rows.some((r) => r.notices.some((n) => n.kind === 'missing-door-width'))).toBe(true)
  })

  it('每一条服务端特征名都落在 AUTO_FEATURE_NAMES 里（页面据此过滤，落在外面 = 被静默丢弃）', () => {
    const names = new Set(GOLDEN.rows.flatMap((r) => r.auto_features.map((f) => f.name)))
    expect(names.size).toBeGreaterThan(0)
    for (const name of names) {
      // 红证：引擎新推一个特征名而前端清单没跟上 ⇒ 页面把它丢掉 = 组合键少一项（改钱）
      expect(AUTO_FEATURE_NAMES as readonly string[]).toContain(name)
    }
  })

  it('每一条服务端提示类别都落在 AUTO_FEATURE_NOTICE_KINDS 里（否则商家看不见「这里本该判」）', () => {
    const kinds = new Set(GOLDEN.rows.flatMap((r) => r.notices.map((n) => n.kind)))
    expect(kinds.size).toBeGreaterThan(0)
    for (const kind of kinds) {
      expect(AUTO_FEATURE_NOTICE_KINDS as readonly string[]).toContain(kind)
    }
  })

  it('服务端的 reason 是**可核对依据**（含真实数字与「门幅」），不是固定串', () => {
    const reasons = GOLDEN.rows.flatMap((r) => r.auto_features.map((f) => f.reason))
    expect(reasons.length).toBeGreaterThan(0)
    // 红证：把 reason 换成固定串 ⇒ 红（判据要能自证 —— 商家要能核对哪两个数比出来的）
    expect(reasons.some((x) => /\d/.test(x) && x.includes('门幅'))).toBe(true)
  })
})

describe('N5 / N6 清单与真值源逐值对齐', () => {
  // 红证（issue #4592，修复前必红）：修复前 `AUTO_FEATURE_NAMES` = [..., '正幅']，
  // 而 V83 目录只种了 3 项 ⇒ 下面的 `toEqual` 必红。
  // 判据形态 = **逐值对齐**（清单 == 目录里标着「自动推导特征」的那几行，双向、按序）。
  it('#4592 清单与加工项目录（V83）**逐值对齐** —— 目录里没有的名字不得进组合键', () => {
    const autoRowsInCatalog = [...V83_SEED_SRC.matchAll(
      /\('(\d+)'::text,\s*'([^']+)'::text,\s*NULL::varchar\(16\),\s*'自动推导特征/g
    )].map((m) => m[2])
    // 目录侧自证：解析出的正是 V83 已种的三项（解析失配 ⇒ 本守卫必须红，不静默空跑）
    expect(autoRowsInCatalog).toEqual(['超高', '超宽', '倒幅'])
    expect(AUTO_FEATURE_NAMES).toEqual(autoRowsInCatalog)
    // 「正幅」两侧都没有：目录没种 ⇒ 清单不得有（P0 的根因就是这个不对称）
    expect(V83_SEED_SRC).not.toContain("'正幅'")
    expect(AUTO_FEATURE_NAMES).not.toContain('正幅')
    // `定型` 是**手选**加工项（#4566），不是自动推导特征
    expect(AUTO_FEATURE_NAMES).not.toContain('定型')
  })

  it('#5009 提示类别清单 == 引擎 AUTO_FEATURE_NOTICE_KINDS（逐值、按序）', () => {
    const engineKinds = pyStrTuple('AUTO_FEATURE_NOTICE_KINDS')
    // 解析自证：引擎侧必须真的声明了这三个（解析失配 ⇒ 红，不静默空跑）
    expect(engineKinds).toEqual(['missing-door-width', 'missing-fullness', 'cutting-mode-conflict'])
    expect([...AUTO_FEATURE_NOTICE_KINDS]).toEqual(engineKinds)
  })
})

describe('N7 门幅解析（SKU.doorWidth；**缺省已删除** —— 解析不到 ⇒ `null`）', () => {
  it('解析带单位的门幅（「2.8米」/「1.4米」/「2.8 m」）', () => {
    expect(parseDoorWidth('2.8米')).toBe(2.8)
    expect(parseDoorWidth('1.4米')).toBe(1.4)
    expect(parseDoorWidth('2.8 m')).toBe(2.8)
    expect(parseDoorWidth('2.8')).toBe(2.8)
  })

  // 红证（issue #4877，改前必红）：改前这四个输入都返回**缺省门幅 2.8**，判定面据此判超高/超宽
  // （真单实测：门幅 2.8 / 3.2 之差 = 「需接高」vs「单幅可做」两种相反结论）。
  it('#4877 缺失 / 不可解析 / 非正 ⇒ `null`（解析回退到任何默认值 ⇒ 红）', () => {
    expect(parseDoorWidth(undefined)).toBeNull()
    expect(parseDoorWidth(null)).toBeNull()
    expect(parseDoorWidth('')).toBeNull()
    expect(parseDoorWidth('暂无')).toBeNull()
    expect(parseDoorWidth('0')).toBeNull()
  })
})
