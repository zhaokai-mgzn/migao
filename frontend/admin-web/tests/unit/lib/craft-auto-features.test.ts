// case_ids: OR-040
/**
 * 下单页**自动识别**（issue #4526 包 B · 设计文档 §5.1 / §5.2 / §9 判据 8）。
 *
 * 用户 2026-09-19：「**超高 / 超宽是和门幅标准比较的**，客户报的数据和门幅对比后能
 * **自动区分**出来是超高还是超宽，**这个要求做到自动识别**」。
 *
 * 冻结规则（设计 §5.2，推理非实证 ⇒ 标注 `source='推算'` + 可配）：
 * ```
 * 门幅 G = SKU.doorWidth（缺省 2.8 米；窄幅布 1.4）
 * 🔴 两个方向**各自**受门幅约束，取决于加工类型（issue #4661，用户 2026-09-20 裁定
 *    「定高买宽的话就不用算超宽，定宽买高就不用算超高」）：
 *      定高买宽 ⇒ **只判超高** = (成品高 + HEM_MARGIN)  > G   ← 宽按米买，无上限
 *      定宽买高 ⇒ **只判超宽** = (成品宽 + SIDE_MARGIN) × **褶倍** > G  ← **分幅**判据（#4662）
 *      缺失/表外 ⇒ 两个都不判（保守，不猜朝向）
 *      ⚠️ **褶倍缺失 / 非正 ⇒ 不判超宽**（#4662：不拿一个假褶倍去判价）+ 显式说明（不静默）
 * 余量常量（米，**算料引擎副本**，各自与真值源对齐、**不混用**）：
 *      SIDE_MARGIN = 0.3（左右覆盖余量，宽方向）  HEM_MARGIN = 0.3（上下卷边，高方向）
 * 倒幅 = (cuttingMode == 定宽买高)  ← 唯一推导，不设手选项
 * 正幅 = (cuttingMode == 定高买宽)  ← **不推导**（issue #4592）：正幅是窗帘常态、且**不在**
 *                                     `processing_items` 目录（V83）里 ⇒ 推出它 = 默认订单的
 *                                     组合键永远匹配不到价 ⇒ 加工费恒 ¥0.00（P0）
 * ```
 *
 * 红证（issue #4661，修复前实测）：① 定高买宽 + 窗宽超门幅 ⇒ 推了 `['超宽','超高']`；
 * ② 定宽买高 + 窗高超门幅 ⇒ 推了 `['超宽','超高','倒幅']`；③ 加工类型缺失 ⇒ 推了 `['超宽','超高']`。
 *
 * 红证（issue #4662，修复前实测）：① **韩褶大窗**（宽 1.5 × 褶倍 2.0 + 左右余量 0.3 = 3.6 米 > 门幅 2.8）
 * 改前只比 `1.5 + 0.3 = 1.8 ≤ 2.8` ⇒ **不报超宽**（该报不报 ⇒ 加工费组合键少一项）；
 * ② **几何矛盾**（定高买宽 + 成品高 2.6 + 卷边 0.3 = 2.9 > 门幅 2.8）改前**零提示**
 * ⇒ 前端推算（超高）与算料引擎实际计算（几何回落 ⇒ 定宽买高）**静默不一致**。
 *
 * 红证（issue #4526，实现前）：`@/lib/craft-auto-features` 不存在 ⇒ import 即红（本文件不 mock，直接红在 import 上）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  AUTO_FEATURE_NAMES,
  HEM_MARGIN,
  SIDE_MARGIN,
  detectAutoFeatureNotices,
  detectAutoFeatures,
  resolveDoorWidth,
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
 * = 组合价永远匹配不到（P0）。本文件据此把「清单 ↔ 目录」钉成**逐值对齐**。
 */
const V83_SEED_SRC = readFileSync(
  resolve(
    __dirname,
    '../../../../../backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql'
  ),
  'utf8'
)

/** 从 Python 源里取一个模块级浮点常量（取不到 ⇒ 直接失败，不静默跳过） */
function pyConst(name: string): number {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, 'm'))
  if (!m) throw new Error(`curtain_calc.py 里找不到常量 ${name}（本守卫必须能读到真值）`)
  return Number(m[1])
}

/** 判定结果的**名字清单**（判据只关心「识别出了什么」，不关心展示文案） */
const names = (input: Parameters<typeof detectAutoFeatures>[0]) =>
  detectAutoFeatures(input).map((f) => f.name)

describe('余量常量 —— 两个方向各自复用算料引擎的**对应**常量（不新造数、也不混用）', () => {
  it('SIDE_MARGIN（宽方向）= curtain_calc.SIDE_MARGIN（逐值比对，漂移即红）', () => {
    expect(SIDE_MARGIN).toBe(pyConst('SIDE_MARGIN'))
  })

  it('HEM_MARGIN（高方向）= curtain_calc.HEM_MARGIN（逐值比对，漂移即红）', () => {
    expect(HEM_MARGIN).toBe(pyConst('HEM_MARGIN'))
  })

  // 红证（issue #4661，修复前必红）：修复前本模块**没有** SIDE_MARGIN，且宽方向用的就是
  // HEM_MARGIN（`reason` 写「卷边 0.3」）⇒ 下面两条必红。
  // ⚠️ 注入式红证（把「两处都用 HEM_MARGIN」注回去）：两个常量**同值 0.3** ⇒ 数值断言**抓不到**
  //    混用，故判据落在**语义**上 —— `reason` 必须逐方向说出余量的**名字**
  //    （宽 = 左右余量 / 高 = 上下卷边）。注入后 `超宽` 的 reason 变回「卷边 0.3」⇒ 红。
  it('#4661 宽方向说「左右余量」、高方向说「上下卷边」（常量语义不混用）', () => {
    const features = detectAutoFeatures({
      width: 6.6,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定宽买高',
      // #4662：超宽判据已含褶倍 ⇒ 不给褶倍就不判超宽（这条判据要能拿到 reason 必须给）
      fullness: 2.0,
    })
    const wide = features.find((f) => f.name === '超宽')!.reason
    expect(wide).toContain(`左右余量 ${SIDE_MARGIN}`)
    expect(wide).not.toContain('卷边')
    const tall = detectAutoFeatures({
      width: 1.0,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定高买宽',
    }).find((f) => f.name === '超高')!.reason
    expect(tall).toContain(`上下卷边 ${HEM_MARGIN}`)
    expect(tall).not.toContain('左右余量')
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

describe('超高 / 超宽 —— 与门幅比较，**按加工类型分流**（issue #4661）', () => {
  it('定高买宽 + 成品高 + 上下卷边 > 门幅 ⇒ 超高（6.6×2.6 对 2.8 门幅：2.6+0.3=2.9 > 2.8）', () => {
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' })).toContain('超高')
  })

  // 红证（issue #4661，修复前必红）：修复前不看 cuttingMode ⇒ 推了 `['超宽','超高']`。
  // 危害：定高买宽的大窗被推成「超宽」⇒ 进加工费组合键 ⇒ **价算错**（且商家无法纠正，见 #4657）。
  it('#4661 定高买宽 + 窗宽超门幅 ⇒ **不推超宽**（宽按米买，无上限；只有高受门幅约束）', () => {
    const got = names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' })
    expect(got).not.toContain('超宽')
    expect(got).toEqual(['超高'])
  })

  // #4662：判据已含褶倍 ⇒ 调用方**必须**给褶倍（缺 ⇒ 不判超宽）；此处按标准档 2.0 倍。
  it('#4661 定宽买高 + 窗宽超门幅 ⇒ 推超宽（(6.6+0.3)×2 = 13.8 > 2.8）', () => {
    expect(
      names({ width: 6.6, height: 1.0, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })
    ).toContain('超宽')
  })

  // 红证（issue #4661，修复前必红）：修复前推了 `['超宽','超高','倒幅']`。
  // 危害：定宽买高的高**按米买**（分幅数 × 高），不受门幅约束 ⇒ 推「超高」是凭空多一项加工费。
  it('#4661 定宽买高 + 窗高超门幅 ⇒ **不推超高**（高按米买；只有宽受门幅约束）', () => {
    const got = names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })
    expect(got).not.toContain('超高')
    expect(got).toEqual(['超宽', '倒幅'])
  })

  it('两者**不互斥**：同一尺寸换加工类型 ⇒ 各自方向都判得出来（判据不因分流而失效）', () => {
    // 定高买宽：高 2.9 > 2.8 ⇒ 超高；宽不判（即便 6.9 > 2.8）
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual(['超高'])
    // 定宽买高：(6.6+0.3)×2 = 13.8 > 2.8 ⇒ 超宽（+ 倒幅）；高不判
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })).toEqual([
      '超宽',
      '倒幅',
    ])
  })

  it('两者**都为假** ⇒ 一个都不出现（1.5×1.5 对 2.8 门幅：1.8 / 1.8 都 ≤ 2.8）', () => {
    expect(names({ width: 1.5, height: 1.5, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual([])
  })

  it('只有超高（3.0 高 × 1.5 宽 对 2.8 门幅：高 3.3 > 2.8，宽 1.8 ≤ 2.8）', () => {
    expect(names({ width: 1.5, height: 3.0, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual(['超高'])
  })

  it('只有超宽（1.5 高 × 3.0 宽 对 2.8 门幅：(3.0+0.3)×2 = 6.6 > 2.8，高 1.8 ≤ 2.8）', () => {
    expect(names({ width: 3.0, height: 1.5, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })).toEqual([
      '超宽',
      '倒幅',
    ])
  })

  it('窄幅布 1.4 门幅：同样的尺寸换门幅 ⇒ 判定跟着变（阈值真的在用门幅，不是写死常数）', () => {
    // 1.5 高 / 1.0 宽：对 1.4 门幅 ⇒ 高 1.8 > 1.4（超高）、宽 1.3 ≤ 1.4（不超宽）
    expect(names({ width: 1.0, height: 1.5, doorWidth: 1.4, cuttingMode: '定高买宽' })).toEqual(['超高'])
    // 同一尺寸对 2.8 门幅 ⇒ 都不超（门幅是判定的自变量）
    expect(names({ width: 1.0, height: 1.5, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual([])
  })

  it('边界：成品高 + 上下卷边 **恰好等于**门幅 ⇒ 不判超高（条件是严格大于，与 curtain_calc 的 `<=` 可用条件一致）', () => {
    // 2.5 + 0.3 = 2.8 == 门幅 ⇒ 定高布仍可用 ⇒ 不是超高
    expect(names({ width: 1.0, height: 2.5, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual([])
  })

  it('尺寸缺失 / 非正数 ⇒ **不猜**（那一维不判，绝不补默认尺寸）', () => {
    // 宽缺失 ⇒ 不判超宽（该方向本就只属定宽买高）；高那一维**独立**照判（2.6+0.3 > 2.8）
    expect(names({ width: null, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual(['超高'])
    // 高缺失 ⇒ 不判超高；宽那一维照判（定宽买高：(6.6+0.3)×2 = 13.8 > 2.8）
    expect(
      names({ width: 6.6, height: null, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })
    ).toEqual(['超宽', '倒幅'])
    // 非正数 = 没填（不当成「0 米宽」去判定）
    expect(names({ width: 0, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual(['超高'])
    expect(names({ width: Number.NaN, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual(['超高'])
    // 两维都缺失 ⇒ 一个都不判
    expect(names({ width: null, height: null, doorWidth: 2.8, cuttingMode: '定宽买高' })).toEqual(['倒幅'])
    expect(names({ width: null, height: null, doorWidth: 2.8, cuttingMode: '定高买宽' })).toEqual([])
  })

  // 红证（issue #4661，修复前必红）：修复前推了 `['超宽','超高']`。
  // 冻结口径（issue #4661 判据 3）：加工类型缺失/表外 ⇒ **两个方向都不判**（保守，不猜朝向）。
  // ⚠️ 若用户后续裁定「缺失时默认按定高买宽」，须另单改（本单不猜）。
  it('#4661 加工类型缺失 / 表外取值 ⇒ **超宽与超高都不推**（不猜朝向）', () => {
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8 })).toEqual([])
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '斜着裁' })).toEqual([])
    expect(names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '' })).toEqual([])
  })

  it('取整到毫米：reason 里不出现浮点长尾（6.8999999999999995 / 13.799999999999999）', () => {
    const reason = detectAutoFeatures({
      width: 6.6,
      height: 1.0,
      doorWidth: 2.8,
      cuttingMode: '定宽买高',
      fullness: 2.0,
    }).find((f) => f.name === '超宽')!.reason
    expect(reason).toContain('= 6.9 米')
    expect(reason).toContain('= 13.8 米')
    expect(reason).not.toMatch(/\d\.\d{4,}/)
  })
})

describe('#4662 「超宽」判据**含褶倍**（与算料引擎算分幅的口径一致）', () => {
  /**
   * 真值源（算料引擎 `curtain_calc.py` 的**定宽买高**分支）：
   * `panels = math.ceil((window_width + cfg["side_margin"]) * fullness / fabric_width)`
   * ⇒ 「要分幅」⟺ `(窗宽 + 左右余量) × 褶倍 > 门幅` —— **这才是真正多花钱的地方**
   * （用户 2026-09-20 裁定 A：「超宽」要含褶倍）。
   */
  it('#4662 判据与引擎**同源**：定宽买高分支逐字就是 (宽 + side_margin) × fullness ÷ 门幅（漂移即红）', () => {
    // 逐字读真值源（不是抄现值）：引擎改了分幅公式而前端不跟 ⇒ 本断言必红
    expect(source).toContain(
      'panels = math.ceil((window_width + cfg["side_margin"]) * fullness / fabric_width)'
    )
    // 定高可用条件（几何矛盾提示的依据）：`高 + HEM_MARGIN <= 门幅` ⇒ 定高买宽，否则回落定宽买高
    expect(source).toContain('if window_height + HEM_MARGIN <= fabric_width:')
  })

  // 红证（issue #4662，修复前实测）：宽 1.5 × 褶倍 2.0 ⇒ 分幅 3.6 米 > 门幅 2.8 ⇒ **该报**；
  // 而改前只比 `1.5 + 0.3 = 1.8 ≤ 2.8` ⇒ **不报**（韩褶大窗该报却不报 ⇒ 组合键少一项 ⇒ 价算错）。
  // 下面第一行就是「改前判据」的自证（不是空断言：1.8 确实 ≤ 2.8 ⇒ 旧口径必然不报）。
  it('#4662 韩褶大窗（1.5 宽 × 2.0 褶倍 + 0.3 余量 = 3.6 > 2.8）⇒ 推超宽', () => {
    expect(1.5 + SIDE_MARGIN).toBeLessThanOrEqual(2.8) // 改前判据：不报（红证自证）
    expect(
      names({ width: 1.5, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })
    ).toContain('超宽')
  })

  it('#4662 依据里看得见褶倍与乘积（商家要能核对「为什么判它超宽」）', () => {
    const reason = detectAutoFeatures({
      width: 1.5,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定宽买高',
      fullness: 2.0,
    }).find((f) => f.name === '超宽')!.reason
    expect(reason).toContain('× 褶倍 2')
    expect(reason).toContain('= 3.6 米 > 门幅 2.8 米')
    expect(reason).not.toMatch(/\d\.\d{4,}/)
  })

  it('#4662 边界：乘积**恰好等于**门幅 ⇒ 不判超宽（严格大于 = 引擎的幅数只有 1 幅）', () => {
    // (1.0 + 0.3) × 1.0 = 1.3 == 门幅 ⇒ ceil(1.3/1.3) = 1 幅 ⇒ 不分幅 ⇒ 不判
    // （引擎实测：`calculate_fabric_meters(1.0, 2.6, 1.0, 1.3)` ⇒ `fixed_width` / 1 幅）
    expect(
      names({ width: 1.0, height: 1.5, doorWidth: 1.3, cuttingMode: '定宽买高', fullness: 1.0 })
    ).toEqual(['倒幅'])
  })

  // 🔴 「与算料引擎逐项对齐」的**边界红证**（#4662 实测发现的脱钩）：
  // 引擎 `panels = ceil((1.1 + 0.3) × 2.0 ÷ 2.8)` = ceil(2.8000000000000003 / 2.8) = **2 幅**
  // （米数 5.8 而非 2.9 ⇒ 翻倍）。若判据**先取整到毫米再比**（2.8 > 2.8 = false）⇒ 判「不超宽」= 漏报。
  // ⇒ 判据必须是**原始浮点**的乘积比较（与引擎同一表达式、同一浮点语义）。
  it('#4662 浮点边界与引擎一致：宽 1.1 × 褶倍 2.0 ÷ 门幅 2.8 ⇒ 引擎 2 幅 ⇒ 判超宽（先取整会漏报）', () => {
    const features = detectAutoFeatures({
      width: 1.1,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定宽买高',
      fullness: 2.0,
    })
    expect(features.map((f) => f.name)).toEqual(['超宽', '倒幅'])
    // 依据要能**自证**：取整会把严格大于抹平 ⇒ 照实给全精度（否则文案是「2.8 米 > 门幅 2.8 米」）
    expect(features.find((f) => f.name === '超宽')!.reason).toContain('= 2.8000000000000003 米 > 门幅 2.8 米')
    // 反向自证：取整后的值确实「看不出」大于门幅 ⇒ 上面那条断言不是空断言
    expect(Number(((1.1 + SIDE_MARGIN) * 2.0).toFixed(3))).toBeLessThanOrEqual(2.8)
  })

  // 口径（issue #4662）：褶倍缺失 / 非正 ⇒ **不判超宽**（不猜一个褶倍去判价），且**界面显式说明**。
  it('#4662 褶倍缺失 / 非正数 ⇒ 不判超宽 + 显式提示「缺褶倍 ⇒ 未判超宽」', () => {
    // 高 2.6 + 0.3 = 2.9 > 2.8 ⇒ 与「定宽买高」几何一致 ⇒ 只该出**缺褶倍**这一条提示
    const noFullness = { width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高' }
    expect(names(noFullness)).toEqual(['倒幅'])
    expect(detectAutoFeatureNotices(noFullness)).toEqual([
      { kind: 'missing-fullness', reason: expect.stringContaining('缺褶倍 ⇒ 未判超宽') },
    ])
    for (const fullness of [null, undefined, 0, -2, Number.NaN]) {
      expect(names({ ...noFullness, fullness })).toEqual(['倒幅'])
    }
  })

  // 褶倍是**自变量**（不是「把阈值调大」）：同一宽高换褶倍 ⇒ 判定跟着变。
  // 引擎读数（`calculate_fabric_meters(1.5, 2.6, N, 2.8)`）：N=1.5 ⇒ 2.7 ⇒ 1 幅（不超宽）；
  // N=2.0 ⇒ 3.6 ⇒ 2 幅（超宽）。1.5+0.3=1.8 ≤ 2.8 ⇒ **旧判据两个都不报** ⇒ 本条是 #4662 的语义红证。
  it('#4662 褶倍是自变量：1.5 倍（2.7 ≤ 2.8）不判超宽；2.0 倍（3.6 > 2.8）判超宽', () => {
    const base = { width: 1.5, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高' as const }
    expect(names({ ...base, fullness: 1.5 })).toEqual(['倒幅'])
    expect(names({ ...base, fullness: 2.0 })).toEqual(['超宽', '倒幅'])
  })

  it('#4662 反向护栏：含褶倍**不改变**分流语义（定宽买高 ⇒ 超宽 + 倒幅，不出超高）', () => {
    expect(
      names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定宽买高', fullness: 2.0 })
    ).toEqual(['超宽', '倒幅'])
    // 定高买宽**不看**褶倍（宽按米买、无上限）⇒ 传了褶倍也不多出「超宽」
    expect(
      names({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽', fullness: 2.0 })
    ).toEqual(['超高'])
  })

  it('#4662 褶倍只进**宽**方向：高方向的依据仍是「上下卷边 HEM_MARGIN」（常量语义分方向不回退）', () => {
    const tall = detectAutoFeatures({
      width: 1.0,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定高买宽',
      fullness: 2.0,
    }).find((f) => f.name === '超高')!.reason
    expect(tall).toContain(`上下卷边 ${HEM_MARGIN}`)
    expect(tall).not.toContain('褶倍')
  })
})

describe('#4662 加工类型**几何矛盾** ⇒ 显式提示（裁定 C：推算以商家选的为准，矛盾必须说出来）', () => {
  /**
   * 真值源（算料引擎 `curtain_calc.py`）：`if window_height + HEM_MARGIN <= fabric_width:` ⇒
   * **定高买宽**，否则 **定宽买高 + 告警**（「成品高 … 超过门幅 … 的定高上限，已按定宽布（买高）计算」）。
   * 引擎**不接收**商家的 `cuttingMode`（`calculate_fabric_meters` 按几何分支，`internal.py` 的入参里没有它）
   * ⇒ 商家手选的档位与引擎实际算的档位**可能不一致**，本组就是那个不一致的判据 + 显式提示。
   *
   * 红证（issue #4662，修复前实测）：改前 `detectAutoFeatureNotices` **不存在**（import 即红）；
   * 页面**零提示** ⇒ 商家以为按「定高买宽」做，引擎实际按「定宽买高」分幅 ⇒ 静默不一致。
   */
  it('#4662 定高买宽 + 高 + 卷边 > 门幅 ⇒ 提示「系统实际会按定宽买高算」', () => {
    const notices = detectAutoFeatureNotices({
      width: 6.6,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定高买宽',
    })
    expect(notices).toHaveLength(1)
    expect(notices[0].kind).toBe('cutting-mode-conflict')
    expect(notices[0].reason).toContain('系统实际会按定宽买高算')
    // 依据说清（哪两个数比出来的）+ 门幅前提可见（前端**不编**口径）
    expect(notices[0].reason).toContain('成品高 2.6 + 上下卷边 0.3 = 2.9 米')
    expect(notices[0].reason).toContain('门幅 2.8 米')
  })

  it('#4662 提示**不改变推算**（以商家选的为准）：特征仍是「超高」，不冒出超宽/倒幅', () => {
    const input = { width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '定高买宽' }
    expect(names(input)).toEqual(['超高'])
    expect(detectAutoFeatureNotices(input)).toHaveLength(1)
    // 提示**不是特征** ⇒ 不得进 AUTO_FEATURE_NAMES（它进加工费组合键；目录里没有的名字 = 价恒 ¥0.00）
    expect(AUTO_FEATURE_NAMES).toEqual(['超高', '超宽', '倒幅'])
  })

  it('#4662 反向也提示：定宽买高 + 高 + 卷边 ≤ 门幅 ⇒ 系统实际会按定高买宽算', () => {
    const notices = detectAutoFeatureNotices({
      width: 1.5,
      height: 1.5,
      doorWidth: 2.8,
      cuttingMode: '定宽买高',
      fullness: 2.0,
    })
    expect(notices.map((n) => n.kind)).toEqual(['cutting-mode-conflict'])
    expect(notices[0].reason).toContain('系统实际会按定高买宽算')
  })

  it('#4662 几何一致 ⇒ **零提示**（不制造噪音；反向护栏，改前即绿）', () => {
    // 定高买宽 + 高不超门幅；定宽买高 + 高超门幅 —— 两种「与几何一致」的档位
    expect(
      detectAutoFeatureNotices({ width: 1.5, height: 1.5, doorWidth: 2.8, cuttingMode: '定高买宽' })
    ).toEqual([])
    expect(
      detectAutoFeatureNotices({
        width: 6.6,
        height: 2.6,
        doorWidth: 2.8,
        cuttingMode: '定宽买高',
        fullness: 2.0,
      })
    ).toEqual([])
    // 边界：高 + 卷边 **恰好等于**门幅 ⇒ 定高布仍可用（引擎 `<=`）⇒ 定高买宽一致
    expect(
      detectAutoFeatureNotices({ width: 1.0, height: 2.5, doorWidth: 2.8, cuttingMode: '定高买宽' })
    ).toEqual([])
  })

  it('#4662 高缺失 / 加工类型缺失 ⇒ 不提示（没有依据就不下结论，不猜）', () => {
    expect(
      detectAutoFeatureNotices({ width: 6.6, height: null, doorWidth: 2.8, cuttingMode: '定高买宽' })
    ).toEqual([])
    expect(detectAutoFeatureNotices({ width: 6.6, height: 2.6, doorWidth: 2.8 })).toEqual([])
    expect(
      detectAutoFeatureNotices({ width: 6.6, height: 2.6, doorWidth: 2.8, cuttingMode: '斜着裁' })
    ).toEqual([])
  })
})

describe('倒幅 —— 由 cuttingMode 唯一推导（不设手选项）；正幅（定高买宽）**不推导**', () => {
  it('定宽买高 ⇒ 倒幅（布旋转 90°，门幅变宽度方向）', () => {
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '定宽买高' })).toContain('倒幅')
  })

  // 红证（issue #4592，修复前必红）：修复前 `定高买宽 ⇒ 正幅`，而 `正幅` 不在
  // `processing_items` 目录（V83 只有 超高/超宽/倒幅）⇒ 商家配不出该组合 ⇒ 组合键永远
  // 匹配不到价 ⇒ 加工费恒 ¥0.00。默认加工类型就是「定高买宽」⇒ **每一张默认订单**都中招。
  it('定高买宽 ⇒ **不推出正幅**（用户裁定「正幅不用作为加工项的加项」）', () => {
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '定高买宽' })).not.toContain('正幅')
    // 常态（定高买宽）+ 尺寸不超门幅 ⇒ **一条特征都没有**（不再靠「正幅」把只读块撑出来）
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '定高买宽' })).toEqual([])
  })

  it('`倒幅` 只在定宽买高出现；定高买宽不推导任何朝向特征（两个推导不再「二选一」）', () => {
    const inverted = names({ width: 1.5, height: 1.5, cuttingMode: '定宽买高' })
    const upright = names({ width: 1.5, height: 1.5, cuttingMode: '定高买宽' })
    expect(inverted).toEqual(['倒幅'])
    expect(upright).toEqual([])
  })

  it('cuttingMode 未指定 / 表外取值 ⇒ 不推导（fail-closed，不猜一个朝向）', () => {
    expect(names({ width: 1.5, height: 1.5 })).toEqual([])
    expect(names({ width: 1.5, height: 1.5, cuttingMode: '斜着裁' })).toEqual([])
    // issue #4661：缺失/表外时**超宽与超高同样不推**（不只是朝向不推）—— 见上面 #4661 那条
  })
})

describe('来源标注 —— `source=推算`（设计 §5.2：本条是推理非实证，不假装定论）', () => {
  it('每条自动特征都带来源「推算」+ 可读依据（哪两个数比出来的）', () => {
    // 6.6×2.6 对 2.8 门幅：定宽买高 ⇒ 超宽（(6.6+0.3)×2 = 13.8 > 2.8）+ 倒幅（高不判 —— #4661）
    const fixedWidth = detectAutoFeatures({
      width: 6.6,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定宽买高',
      fullness: 2.0,
    })
    expect(fixedWidth.map((f) => f.source)).toEqual(['推算', '推算'])
    // #4662：依据里含**褶倍与乘积**（那才是「要分幅」的判据 —— 商家要能核对为什么判它超宽）
    expect(fixedWidth.find((f) => f.name === '超宽')?.reason).toBe(
      '成品宽 6.6 + 左右余量 0.3 = 6.9 米 × 褶倍 2 = 13.8 米 > 门幅 2.8 米'
    )
    expect(fixedWidth.find((f) => f.name === '倒幅')?.reason).toBe('加工类型 = 定宽买高')

    // 定高买宽 ⇒ 超高（2.9 > 2.8），余量名换「上下卷边」（issue #4661：常量语义分方向）
    const fixedHeight = detectAutoFeatures({
      width: 6.6,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定高买宽',
    })
    expect(fixedHeight.map((f) => f.source)).toEqual(['推算'])
    expect(fixedHeight.find((f) => f.name === '超高')?.reason).toBe(
      '成品高 2.6 + 上下卷边 0.3 = 2.9 米 > 门幅 2.8 米'
    )
  })
})

describe('自动特征不是可手选项（判据 8：手选项 ⇒ 红）', () => {
  it('自动识别的特征名只可能是 超高 / 超宽 / 倒幅 这三个（推导产生，非商家勾选）', () => {
    // issue #4661：单次调用**最多**只能推两个方向中的一个（按加工类型分流）⇒ 用两次调用凑齐三名，
    // 并逐条钉住「哪个加工类型推哪几个」。
    const fixedWidth = detectAutoFeatures({
      width: 6.6,
      height: 2.6,
      doorWidth: 1.4,
      cuttingMode: '定宽买高',
      fullness: 2.0,
    })
    expect(fixedWidth.map((f) => f.name)).toEqual(['超宽', '倒幅'])
    const fixedHeight = detectAutoFeatures({
      width: 6.6,
      height: 2.6,
      doorWidth: 1.4,
      cuttingMode: '定高买宽',
    })
    expect(fixedHeight.map((f) => f.name)).toEqual(['超高'])
  })

  // 红证（issue #4592，修复前必红）：修复前 `AUTO_FEATURE_NAMES` = [..., '正幅']，
  // 而 V83 目录只种了 3 项 ⇒ 下面的 `toEqual` 必红。
  // 判据形态 = **逐值对齐**（清单 == 目录里标着「自动推导特征」的那几行，双向、按序），
  // 不是「清单 ⊆ 目录」—— 后者放不出「目录多了一项而清单少推」的偏差。
  it('#4592 清单与加工项目录（V83）**逐值对齐** —— 目录里没有的名字不得进组合键', () => {
    const autoRowsInCatalog = [...V83_SEED_SRC.matchAll(
      /\('(\d+)'::text,\s*'([^']+)'::text,\s*NULL::varchar\(16\),\s*'自动推导特征/g
    )].map((m) => m[2])
    // 目录侧自证：解析出的正是 V83 已种的三项（解析失配 ⇒ 本守卫必须红，不静默空跑）
    expect(autoRowsInCatalog).toEqual(['超高', '超宽', '倒幅'])
    // 清单侧：推导出的特征名与目录**逐值一致**（顺序也一致 —— 组合键归一化另有唯一实现）
    expect(AUTO_FEATURE_NAMES).toEqual(autoRowsInCatalog)
    // 「正幅」两侧都没有：目录没种 ⇒ 清单不得推（P0 的根因就是这个不对称）
    expect(V83_SEED_SRC).not.toContain("'正幅'")
    expect(AUTO_FEATURE_NAMES).not.toContain('正幅')
  })

  // issue #4566（用户 2026-09-19 裁定「工艺规格中的**工艺，定型**……直接通过加工项来勾选」）：
  // `定型` 是**手选**加工项，不再是自动推导特征 —— 其勾选态单独派生 `isShaped`。
  // 本清单同时是下单页滤出「手选列表」的**单一真值**（目录里必须存在这些项，
  // 但下单页的手选控件必须没有它们）。
  it('#4566 自动推导特征清单 = 超高/超宽/倒幅（**不含定型、也不含正幅**）', () => {
    expect(AUTO_FEATURE_NAMES).toEqual(['超高', '超宽', '倒幅'])
    expect(AUTO_FEATURE_NAMES).not.toContain('定型')
    // issue #4592：正幅是窗帘常态、不在加工项目录里 ⇒ 不得作为组合键加项
    expect(AUTO_FEATURE_NAMES).not.toContain('正幅')
  })

  it('#4566 `定型` 不再由本模块推导：多传 `isShaped` 也不产出 `定型` 特征', () => {
    // 红证（实现前）：`detectAutoFeatures({ isShaped: true, ... })` 会产出 `定型`（R9 旧口径）。
    const names = detectAutoFeatures({
      width: 1.0,
      height: 2.6,
      doorWidth: 2.8,
      cuttingMode: '定高买宽',
      // @ts-expect-error 入参类型已删掉 `isShaped`（#4566）；刻意多传，验证它不再影响结果
      isShaped: true,
    }).map((f) => f.name)
    // issue #4661：定高买宽只判高方向 ⇒ 只出 `超高`（宽 1.3 ≤ 2.8 本就不超宽）
    expect(names).toEqual(['超高'])
  })
})
