// case_ids: OR-040
/**
 * 下单页**自动识别**（issue #4526 包 B · 设计文档 §5.1 / §5.2 / §9 判据 8）。
 *
 * 用户 2026-09-19：「**超高 / 超宽是和门幅标准比较的**，客户报的数据和门幅对比后能
 * **自动区分**出来是超高还是超宽，**这个要求做到自动识别**」。
 *
 * 冻结规则（设计 §5.2，推理非实证 ⇒ 标注 `source='推算'` + 可配）：
 * ```
 * 门幅 G   = SKU.doorWidth（缺省 2.8 米；窄幅布 1.4）
 * 卷边常量 = 0.3 米（**复用** curtain_calc 既有常量，不新造第二个数）
 * 超高 = (成品高 + 0.3) > G       超宽 = (成品宽 + 0.3) > G     ← 两者独立，可同时为真
 * 倒幅 = (cuttingMode == 定宽买高)  正幅 = (cuttingMode == 定高买宽)  ← 唯一推导，不设手选项
 * ```
 *
 * 红证（实现前）：`@/lib/craft-auto-features` 不存在 ⇒ import 即红（本文件不 mock，直接红在 import 上）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { AUTO_FEATURE_NAMES, HEM_MARGIN, detectAutoFeatures, resolveDoorWidth } from '@/lib/craft-auto-features'

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

/** 判定结果的**名字清单**（判据只关心「识别出了什么」，不关心展示文案） */
const names = (input: Parameters<typeof detectAutoFeatures>[0]) =>
  detectAutoFeatures(input).map((f) => f.name)

describe('卷边常量 —— 复用算料引擎既有常量（不新造第二个数）', () => {
  it('HEM_MARGIN = curtain_calc.HEM_MARGIN（逐值比对，漂移即红）', () => {
    expect(HEM_MARGIN).toBe(pyConst('HEM_MARGIN'))
  })
})

describe('门幅解析（SKU.doorWidth，缺省 2.8 米；窄幅布 1.4）', () => {
  it('解析带单位的门幅（「2.8米」/「1.4米」/「2.8 m」）', () => {
    expect(resolveDoorWidth('2.8米')).toBe(2.8)
    expect(resolveDoorWidth('1.4米')).toBe(1.4)
    expect(resolveDoorWidth('2.8 m')).toBe(2.8)
    expect(resolveDoorWidth('2.8')).toBe(2.8)
  })

  it('缺省 / 不可解析 ⇒ 2.8 米（不是 0，也不是「不判定」——门幅缺省是行业常态）', () => {
    expect(resolveDoorWidth(undefined)).toBe(2.8)
    expect(resolveDoorWidth('')).toBe(2.8)
    expect(resolveDoorWidth('加宽')).toBe(2.8)
    expect(resolveDoorWidth('0')).toBe(2.8)
  })
})

describe('超高 / 超宽 —— 与门幅比较，两者独立（设计 §5.2）', () => {
  it('成品高 + 卷边 > 门幅 ⇒ 超高（6.6×2.6 对 2.8 门幅：2.6+0.3=2.9 > 2.8）', () => {
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8 })).toContain('超高')
  })

  it('成品宽 + 卷边 > 门幅 ⇒ 超宽（6.6+0.3=6.9 > 2.8）', () => {
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8 })).toContain('超宽')
  })

  it('两者**可同时为真**（ERP `韩折+超宽+超高+定型` 佐证 ⇒ 不得互斥）', () => {
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8 })).toEqual(['超宽', '超高'])
  })

  it('两者**都为假** ⇒ 一个都不出现（1.5×1.5 对 2.8 门幅：1.8 / 1.8 都 ≤ 2.8）', () => {
    expect(names({ width: 1.5, height: 1.5, doorWidth: 2.8 })).toEqual([])
  })

  it('只有超高（3.0 高 × 1.5 宽 对 2.8 门幅：高 3.3 > 2.8，宽 1.8 ≤ 2.8）', () => {
    expect(names({ width: 1.5, height: 3.0, doorWidth: 2.8 })).toEqual(['超高'])
  })

  it('只有超宽（1.5 高 × 3.0 宽 对 2.8 门幅：宽 3.3 > 2.8，高 1.8 ≤ 2.8）', () => {
    expect(names({ width: 3.0, height: 1.5, doorWidth: 2.8 })).toEqual(['超宽'])
  })

  it('窄幅布 1.4 门幅：同样的尺寸换门幅 ⇒ 判定跟着变（阈值真的在用门幅，不是写死常数）', () => {
    // 1.5 高 / 1.0 宽：对 1.4 门幅 ⇒ 高 1.8 > 1.4（超高）、宽 1.3 ≤ 1.4（不超宽）
    expect(names({ width: 1.0, height: 1.5, doorWidth: 1.4 })).toEqual(['超高'])
    // 同一尺寸对 2.8 门幅 ⇒ 都不超（门幅是判定的自变量）
    expect(names({ width: 1.0, height: 1.5, doorWidth: 2.8 })).toEqual([])
  })

  it('边界：成品高 + 卷边 **恰好等于**门幅 ⇒ 不判超高（条件是严格大于，与 curtain_calc 的 `<=` 可用条件一致）', () => {
    // 2.5 + 0.3 = 2.8 == 门幅 ⇒ 定高布仍可用 ⇒ 不是超高
    expect(names({ width: 1.0, height: 2.5, doorWidth: 2.8 })).toEqual([])
  })

  it('尺寸缺失 / 非正数 ⇒ **不猜**（那一维不判，绝不补默认尺寸）', () => {
    // 宽缺失 ⇒ 不判超宽，但高那一维**独立**照判（2.6+0.3 > 2.8）
    expect(names({ width: null, height: 2.6, doorWidth: 2.8 })).toEqual(['超高'])
    // 高缺失 ⇒ 不判超高，宽那一维照判
    expect(names({ width: 6.6, height: null, doorWidth: 2.8 })).toEqual(['超宽'])
    // 非正数 = 没填（不当成「0 米宽」去判定）
    expect(names({ width: 0, height: 2.6, doorWidth: 2.8 })).toEqual(['超高'])
    expect(names({ width: Number.NaN, height: 2.6, doorWidth: 2.8 })).toEqual(['超高'])
    // 两维都缺失 ⇒ 一个都不判
    expect(names({ width: null, height: null, doorWidth: 2.8 })).toEqual([])
  })
})

describe('倒幅 / 正幅 —— 由 cuttingMode 唯一推导（不设手选项）', () => {
  it('定宽买高 ⇒ 倒幅（布旋转 90°，门幅变宽度方向）', () => {
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '定宽买高' })).toContain('倒幅')
  })

  it('定高买宽 ⇒ 正幅', () => {
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '定高买宽' })).toContain('正幅')
  })

  it('两个推导**互斥**（同一 cuttingMode 不可能既倒又正）', () => {
    const inverted = names({ width: 1.5, height: 1.5, cuttingMode: '定宽买高' })
    const upright = names({ width: 1.5, height: 1.5, cuttingMode: '定高买宽' })
    expect(inverted).not.toContain('正幅')
    expect(upright).not.toContain('倒幅')
  })

  it('cuttingMode 未指定 / 表外取值 ⇒ 不推导（fail-closed，不猜一个朝向）', () => {
    expect(names({ width: 1.5, height: 1.5 })).toEqual([])
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '斜着裁' })).toEqual([])
  })
})

describe('来源标注 —— `source=推算`（设计 §5.2：本条是推理非实证，不假装定论）', () => {
  it('每条自动特征都带来源「推算」+ 可读依据（哪两个数比出来的）', () => {
    const features = detectAutoFeatures({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高' })
    expect(features.map((f) => f.source)).toEqual(['推算', '推算', '推算'])
    expect(features.find((f) => f.name === '超高')?.reason).toBe('成品高 2.6 + 卷边 0.3 = 2.9 米 > 门幅 2.8 米')
    expect(features.find((f) => f.name === '超宽')?.reason).toBe('成品宽 6.6 + 卷边 0.3 = 6.9 米 > 门幅 2.8 米')
    expect(features.find((f) => f.name === '倒幅')?.reason).toBe('加工类型 = 定宽买高')
  })
})

describe('自动特征不是可手选项（判据 8：手选项 ⇒ 红）', () => {
  it('自动识别的特征名只可能是 超高 / 超宽 / 倒幅 / 正幅 这四个（推导产生，非商家勾选）', () => {
    const all = detectAutoFeatures({ width: 6.6, height: 2.6, doorWidth: 1.4, cuttingMode: '定宽买高' })
    expect(all.map((f) => f.name)).toEqual(['超宽', '超高', '倒幅'])
  })

  // issue #4566（用户 2026-09-19 裁定「工艺规格中的**工艺，定型**……直接通过加工项来勾选」）：
  // `定型` 是**手选**加工项，不再是自动推导特征 —— 其勾选态单独派生 `isShaped`。
  // 本清单同时是下单页滤出「手选列表」的**单一真值**（目录里必须存在这些项，
  // 但下单页的手选控件必须没有它们）。
  it('#4566 自动推导特征清单 = 超高/超宽/倒幅/正幅（**不含定型**）', () => {
    expect(AUTO_FEATURE_NAMES).toEqual(['超高', '超宽', '倒幅', '正幅'])
    expect(AUTO_FEATURE_NAMES).not.toContain('定型')
  })

  it('#4566 `定型` 不再由本模块推导：多传 `isShaped` 也不产出 `定型` 特征', () => {
    // 红证（实现前）：`detectAutoFeatures({ isShaped: true, ... })` 会产出 `定型`（R9 旧口径）。
    const names = detectAutoFeatures({
      width: 6.6,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定高买宽',
      // @ts-expect-error 入参类型已删掉 `isShaped`（#4566）；刻意多传，验证它不再影响结果
      isShaped: true,
    }).map((f) => f.name)
    expect(names).toEqual(['超宽', '超高', '正幅'])
  })
})
