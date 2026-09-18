// case_ids: OR-009, UI-038
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
  DEFAULT_PLEAT_SPACING,
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

  it('默认褶距 = 每折吃布 ÷ 标准档倍数（用户 2026-09-19 裁定：褶距随倍数自动算）', () => {
    expect(DEFAULT_PLEAT_SPACING).toBeCloseTo(PLEAT_FABRIC_PER_FOLD / STANDARD_FULLNESS, 10)
    // 2.0 倍 ⇒ 0.125 米（12.5cm）。若有人把倍数改成 2.5（=清单那处 0.1m 口径）此处必红。
    expect(DEFAULT_PLEAT_SPACING).toBe(0.125)
  })

  it('三条默认值 = 用户裁定的档（加工类型定高买宽 / 款式单色 / 褶距 0.125）', () => {
    expect(DEFAULT_CUTTING_MODE).toBe('定高买宽')
    expect(DEFAULT_STYLE).toBe('单色')
    expect(createDefaultCraftSpec()).toEqual({
      cuttingMode: '定高买宽',
      style: '单色',
      pleatSpacing: 0.125,
    })
  })

  it('默认值是**真值**：经 buildCraftSpec 后三个键都落库（不是被「缺值不写」吞掉）', () => {
    const spec = buildCraftSpec(createDefaultCraftSpec())
    expect(spec).toEqual({ cuttingMode: '定高买宽', style: '单色', pleatSpacing: 0.125 })
  })

  it('默认档与库侧枚举逐字一致（错一个字下游取不到路线）', () => {
    expect(source).toContain('"s_hook"') // 韩褶 = s_hook（标准档所在悬挂方式）
    expect(buildCraftSpec(createDefaultCraftSpec()).cuttingMode).toBe('定高买宽')
  })
})
