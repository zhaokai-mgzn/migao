// case_ids: OR-039
/**
 * 工艺 → 用料公式 / 悬挂方式的**同步守卫**（issue #4527 追加裁定）。
 *
 * 用户 2026-09-19 追加裁定逐字：「**韩折用韩折公式算布料，打孔按倍数法算布料，默认选择 2 倍**」
 * ⇒ 公式**由工艺推导**。
 *
 * 病根（同族 #4393 / #4420：`craft-display` / 默认档常量的多份副本无同步守卫）：
 * 前端 `craft-calc-request.ts` 必须知道「韩褶 → pleat / 打孔 → fullness」才能凑出入参，
 * 而**权威表在算料引擎** `curtain_calc.py` 的 `CRAFT_FORMULA` / `CRAFT_MOUNTING`。
 * 两边各写一份、没有守卫 ⇒ 改一处忘一处 ⇒ **静默算错布料**（页面按韩褶口径发请求、后端按打孔口径算）。
 *
 * 本文件把「副本」变成「**有守卫的副本**」：逐值读 `curtain_calc.py` 源文件比对，漂移即红。
 * 红证（实现前）：`CRAFT_CALC_FORMULA_BY_CRAFT` / `CRAFT_CALC_MOUNTING_BY_CRAFT` 不存在 ⇒ import 即红；
 * 把任一侧的「打孔 → fullness」改成 pleat ⇒ 本文件红。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  CRAFT_CALC_FORMULA_BY_CRAFT,
  CRAFT_CALC_FORMULA_FULLNESS,
  CRAFT_CALC_FORMULA_PLEAT,
  CRAFT_CALC_MOUNTING_BY_CRAFT,
} from '@/lib/craft-calc-request'

/** 算料引擎源（真值源）：`backend/ai-agent-service/app/tools/curtain_calc.py` */
const CALC_SRC = resolve(
  __dirname,
  '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py'
)

const source = readFileSync(CALC_SRC, 'utf8')

/** 从 Python 源里取 `NAME = { "键": 值, ... }` 形态的字面量映射（取不到 ⇒ 直接失败，不静默跳过） */
function pyStrMap(name: string): Record<string, string> {
  const m = source.match(new RegExp(`${name}\\s*:\\s*Dict\\[str, str\\]\\s*=\\s*\\{([^}]*)\\}`, 's'))
  if (!m) throw new Error(`curtain_calc.py 里找不到映射 ${name}（本守卫必须能读到真值）`)
  const out: Record<string, string> = {}
  for (const line of m[1].split('\n')) {
    const kv = line.match(/"([^"]+)"\s*:\s*([A-Z_]+|"[^"]+")/)
    if (!kv) continue
    const value = kv[2].startsWith('"') ? kv[2].slice(1, -1) : pyConst(kv[2])
    out[kv[1]] = value
  }
  return out
}

/** Python 源里的模块级字符串常量（如 FORMULA_PLEAT = "pleat"） */
function pyConst(name: string): string {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*"([^"]+)"`, 'm'))
  if (!m) throw new Error(`curtain_calc.py 里找不到常量 ${name}（本守卫必须能读到真值）`)
  return m[1]
}

describe('工艺 → 公式 / 悬挂方式：前端副本与算料引擎真值源同步（issue #4527）', () => {
  it('公式名常量逐值一致（pleat / fullness）', () => {
    expect(CRAFT_CALC_FORMULA_PLEAT).toBe(pyConst('FORMULA_PLEAT'))
    expect(CRAFT_CALC_FORMULA_FULLNESS).toBe(pyConst('FORMULA_FULLNESS'))
    expect(CRAFT_CALC_FORMULA_PLEAT).toBe('pleat')
    expect(CRAFT_CALC_FORMULA_FULLNESS).toBe('fullness')
  })

  it('CRAFT_FORMULA 逐值一致：韩褶 → 韩折公式 / 打孔 → 褶倍数公式', () => {
    const py = pyStrMap('CRAFT_FORMULA')
    expect(Object.keys(py).sort()).toEqual(Object.keys(CRAFT_CALC_FORMULA_BY_CRAFT).sort())
    expect(CRAFT_CALC_FORMULA_BY_CRAFT).toEqual(py)
    // 逐值写死（判据不依赖实现）：改任一侧 ⇒ 红
    expect(CRAFT_CALC_FORMULA_BY_CRAFT).toEqual({ 韩褶: 'pleat', 打孔: 'fullness' })
  })

  it('CRAFT_MOUNTING 逐值一致：韩褶 → s_hook / 打孔 → eyelet', () => {
    const py = pyStrMap('CRAFT_MOUNTING')
    expect(Object.keys(py).sort()).toEqual(Object.keys(CRAFT_CALC_MOUNTING_BY_CRAFT).sort())
    expect(CRAFT_CALC_MOUNTING_BY_CRAFT).toEqual(py)
    expect(CRAFT_CALC_MOUNTING_BY_CRAFT).toEqual({ 韩褶: 's_hook', 打孔: 'eyelet' })
  })

  it('打孔默认 2 倍**复用**标准档倍数（真值源里不新造第二个 2.0 字面量）', () => {
    // 打孔 → eyelet ⇒ DEFAULT_FULLNESS["eyelet"] 必须等于 DEFAULT_CRAFT_TIERS["standard"].fullness
    const m = source.match(/"eyelet"\s*:\s*([0-9.]+)/)
    const tier = source.match(/"standard"\s*:\s*\{\s*"fullness"\s*:\s*([0-9.]+)/)
    if (!m || !tier) throw new Error('curtain_calc.py 里找不到 eyelet 默认倍数 / standard 档倍数')
    expect(Number(m[1])).toBe(2.0)
    expect(Number(tier[1])).toBe(2.0)
  })
})
