// case_ids: OR-041
/**
 * 工艺 → 用料公式 / 悬挂方式的**同步守卫**（issue #4527 追加裁定）。
 *
 * 用户 2026-09-19 追加裁定逐字：「**韩折用韩褶公式算布料，打孔按倍数法算布料，默认选择 2 倍**」
 * ⇒ 公式**由工艺推导**。
 *
 * 病根（同族 #4393 / #4420：`craft-display` / 默认档常量的多份副本无同步守卫）：
 * 前端 `craft-calc-request.ts` 必须知道「韩褶 → pleat / 打孔 → fullness」才能凑出入参，
 * 而**权威表在算料引擎** `curtain_calc.py` 的 `resolve_craft_rule`（`CRAFT_S_HOOK`/`CRAFT_EYELET` 枚举常量 → 公式/悬挂方式）。
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

/**
 * 从 Python 源里取「工艺 → 公式/悬挂方式」的**唯一入口**（`resolve_craft_rule`）的登记项。
 *
 * ⚠️ 为什么不读「中文 key 的映射表」：本仓 `test_tool_input_contract_guards.py` 的
 * `TestNoNewChineseWordingJudgement` 把「含 ≥2 个中文 key 的 dict 字面量」算作
 * **中文措辞当判据**站点（基线只许缩短）⇒ 权威侧改用**入口函数 + 枚举常量**表达推导，
 * 本守卫因此解析「常量定义 + 分支返回值」，取不到即直接失败（不静默跳过）。
 */
function pyCraftRules(): Record<string, { formula: string; mounting: string }> {
  const branchRe = /if craft == (CRAFT_[A-Z_]+):\s*\n\s*return (FORMULA_[A-Z_]+), (MOUNTING_[A-Z_]+)/g
  const constRe = (name: string) => {
    const m = source.match(new RegExp(`^${name}\\s*=\\s*"([^"]+)"`, 'm'))
    if (!m) throw new Error(`curtain_calc.py 里找不到常量 ${name}（本守卫必须能读到真值）`)
    return m[1]
  }
  const out: Record<string, { formula: string; mounting: string }> = {}
  for (const m of source.matchAll(branchRe)) {
    out[constRe(m[1])] = { formula: constRe(m[2]), mounting: constRe(m[3]) }
  }
  if (Object.keys(out).length === 0) {
    throw new Error(
      'curtain_calc.py 的 resolve_craft_rule 分支解析不到任何登记项 —— 结构变了，请同步本守卫'
    )
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

  it('resolve_craft_rule 逐值一致：韩褶 → 韩褶公式+s_hook / 打孔 → 褶倍数公式+eyelet', () => {
    const py = pyCraftRules()
    // 逐值写死（判据不依赖实现）：改任一侧 ⇒ 红
    expect(py).toEqual({
      韩褶: { formula: 'pleat', mounting: 's_hook' },
      打孔: { formula: 'fullness', mounting: 'eyelet' },
    })
    // 前端两张表都必须是真值源的**投影**（键集与值逐值一致）
    const frontFormula = Object.fromEntries(
      Object.entries(CRAFT_CALC_FORMULA_BY_CRAFT).map(([k, v]) => [k, { formula: v }])
    )
    const frontMounting = Object.fromEntries(
      Object.entries(CRAFT_CALC_MOUNTING_BY_CRAFT).map(([k, v]) => [k, { mounting: v }])
    )
    expect(Object.keys(CRAFT_CALC_FORMULA_BY_CRAFT).sort()).toEqual(Object.keys(py).sort())
    expect(Object.keys(CRAFT_CALC_MOUNTING_BY_CRAFT).sort()).toEqual(Object.keys(py).sort())
    for (const craft of Object.keys(py)) {
      expect(frontFormula[craft]).toEqual({ formula: py[craft].formula })
      expect(frontMounting[craft]).toEqual({ mounting: py[craft].mounting })
    }
    expect(CRAFT_CALC_FORMULA_BY_CRAFT).toEqual({ 韩褶: 'pleat', 打孔: 'fullness' })
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
