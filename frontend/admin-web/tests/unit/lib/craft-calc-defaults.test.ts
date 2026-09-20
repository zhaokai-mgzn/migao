// case_ids: OR-035, OR-038
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为
// （默认档常量的**有守卫副本**：逐值读 curtain_calc.py 比对）。改用 **OR-035**（本 PR 新增）。
/**
 * 下单页默认档 + 算料常量的**同步守卫**（issue #4420）。
 *
 * 病根（同族 #4393：`craft-display` 三份副本无同步守卫）：前端一旦自己写一份算料常量，
 * 库侧改了而前端不跟 ⇒ **静默漂移**（页面显示的用料/褶距与实际加工单不一致，且没有任何东西变红）。
 *
 * 本文件把「副本」变成「**有守卫的副本**」：逐值读 `curtain_calc.py` 源文件比对，
 * 漂移即红。**不是**「与源码等值」的形态判据 —— 取的是**值级**比对（读真值源，不抄现值）。
 *
 * 红证（实现前）：`@/lib/order-craft-fields` 无这四个常量 ⇒ import 即红。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  DEFAULT_CUTTING_MODE,
  DEFAULT_STYLE,
  PLEAT_FABRIC_PER_FOLD,
  STANDARD_FULLNESS,
  buildCraftSpec,
  createDefaultCraftSpec,
} from '@/lib/order-craft-fields'

/** 算料引擎源（真值源）：`backend/ai-agent-service/app/tools/curtain_calc.py` */
const CALC_SRC = resolve(
  __dirname,
  '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py'
)

const source = readFileSync(CALC_SRC, 'utf8')

/** 从 Python 源里取一个模块级浮点常量（取不到 ⇒ 直接失败，不静默跳过） */
function pyConst(name: string): number {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, 'm'))
  if (!m) throw new Error(`curtain_calc.py 里找不到常量 ${name}（本守卫必须能读到真值）`)
  return Number(m[1])
}

describe('下单页默认档与算料引擎常量同步（issue #4420）', () => {
  it('每折吃布 = curtain_calc.PLEAT_FABRIC_PER_FOLD（真值源 §8：0.25 米/折）', () => {
    expect(PLEAT_FABRIC_PER_FOLD).toBe(pyConst('PLEAT_FABRIC_PER_FOLD'))
  })

  it('标准档倍数 = DEFAULT_CRAFT_TIERS.standard.fullness', () => {
    const m = source.match(/"standard"\s*:\s*\{\s*"fullness"\s*:\s*([0-9.]+)/)
    if (!m) throw new Error('curtain_calc.py 里找不到 DEFAULT_CRAFT_TIERS.standard.fullness')
    expect(STANDARD_FULLNESS).toBe(Number(m[1]))
  })

  // ⚠️ issue #4874：原「默认褶距 = 每折吃布 ÷ 标准档倍数（0.125）」判据**随字段退场**
  // （用户 2026-09-21「移除订单的工艺规格中的褶距字段」）——`DEFAULT_PLEAT_SPACING` 已从
  // `lib/order-craft-fields.ts` **删除**（模块导出清单的反向断言见 `order-craft-fields.test.ts`
  // 的 `#4874` 组）。这里保留的仍是**有守卫的**算料常量（每折吃布 / 标准档倍数）——
  // 它们是引擎侧真值的前端副本，**没有**随褶距退场（§4662 的超宽判据仍读 `STANDARD_FULLNESS`）。

  it('默认值 = 用户裁定的档（加工类型定高买宽 / 款式单色 / 对花否）', () => {
    expect(DEFAULT_CUTTING_MODE).toBe('定高买宽')
    expect(DEFAULT_STYLE).toBe('单色')
    // issue #4521：**部位不再进默认档**（主帘缺省即布帘）。
    // issue #4566：**`craft` / `isShaped` 也不再进默认档** —— 用户 2026-09-19 裁定
    // 「工艺规格中的**工艺，定型**……直接通过加工项来勾选」⇒ 它们由**加工项**派生
    // （工艺 = 勾选的工艺项的 `craftHint`；定型 = 「定型」加工项的勾选态）。
    // 前端**不得**再补一份默认工艺/默认定型 —— 那正是让 ERP「工艺+特征」组合名匹配不上的口径。
    // issue #4874：**褶距已整体移除**；`formula` / `craftTier` **不进**本默认档 ——
    // 它们是**读面取值**（公式取算料配置的 `default_formula`、档位取 `tiers` 的键，
    // 由页面侧 `derivedCraftSpec` 解析后经 `buildCraftSpec` 落库），前端不持有第二份真值。
    expect(createDefaultCraftSpec()).toEqual({
      cuttingMode: '定高买宽',
      style: '单色',
      hasPattern: false,
    })
    expect(createDefaultCraftSpec()).not.toHaveProperty('craft')
    expect(createDefaultCraftSpec()).not.toHaveProperty('isShaped')
    expect(createDefaultCraftSpec()).not.toHaveProperty('pleatSpacing')
    expect(createDefaultCraftSpec()).not.toHaveProperty('formula')
    expect(createDefaultCraftSpec()).not.toHaveProperty('craftTier')
  })

  it('默认值是**真值**：经 buildCraftSpec 后各键都落库（不是被「缺值不写」吞掉）', () => {
    const spec = buildCraftSpec(createDefaultCraftSpec())
    expect(spec).toEqual({
      cuttingMode: '定高买宽',
      style: '单色',
      hasPattern: false,
    })
    // 部位**不在**默认档里（issue #4521）：写它 = 给主帘留一条被标成纱帘的口子
    expect(spec).not.toHaveProperty('curtainType')
    // #4566：工艺 / 定型同样不在（真值来源是加工项，不是本默认档）
    expect(spec).not.toHaveProperty('craft')
    expect(spec).not.toHaveProperty('isShaped')
    // #4874：褶距的**写键整个退场**（存量单读侧仍容错，但新单不再落这个键）
    expect(spec).not.toHaveProperty('pleatSpacing')
  })

  it('默认档与库侧枚举逐字一致（错一个字下游取不到路线）', () => {
    expect(source).toContain('"s_hook"') // 韩褶 = s_hook（标准档所在悬挂方式）
    expect(buildCraftSpec(createDefaultCraftSpec()).cuttingMode).toBe('定高买宽')
  })
})
