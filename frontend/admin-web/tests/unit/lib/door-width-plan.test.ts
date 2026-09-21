// case_ids: OR-040
/**
 * 门幅选择规则（issue #4877）—— 下单页**在候选门幅里求可行解 + 取最省**的纯函数。
 *
 * 用户 2026-09-21 裁定（逐字）：
 * > 「『**最优』= 可行集里取最小门幅（最省料），定宽买高则取分幅最少**，这个是最贴近实际的」
 * > 「**如果所有门幅都不满足，那必然走接高**」
 * > 「**顾客给的高都是成品高**」
 * > 「**默认都能倒幅**」
 * > 「**（门幅有效余量）有必要**」
 * > 「**加工类型是显式输入：定高买宽 + 高度超限 ⇒ 接高；倒幅只在显式选『定宽买高』时用（系统永不自己改判）**」
 * > 「**没有一个行业通用公式能替人拍板，能被机械化的只有「可行 / 不可行 + 哪个最省」**」
 *
 * ## 判定（与 `docs/curtain-fabric-quote-rules.md` §3 / `curtain_calc.py` 同源）
 * ```
 * g_eff(g) = 标称门幅 − 有效余量（缩水/边损/对花回；缺省 0）
 * 定高买宽: 可行 = { g | H + HEM_MARGIN ≤ g_eff(g) }；空 ⇒ needs_splice，非空 ⇒ 取 min(可行)
 * 定宽买高: 幅数 p(g) = ceil(窗宽 × 褶倍 ÷ g_eff(g))；取 p 最小者，并列取较小 g
 * 加工类型缺失/表外 ⇒ undecidable（裁定 6：**不替调用方猜朝向**）
 * ```
 * ⚠️ 余量常量**只剩高方向**：`craft-auto-features.ts` 的 `HEM_MARGIN`（上下卷边，副本有跨语言守卫），
 * 本模块**不新造第二个 0.3**；宽方向**没有余量**（用户 2026-09-21 裁定，issue #5030：
 * 订单宽 = **净窗宽** ⇒ 成品宽 = 净窗宽、用料 = 窗宽 × 褶倍）；加工类型常量同样复用
 * （措辞不得成为第二份判据）。
 *
 * ## 红证（每条判据必须有能**单独**把它判红的变异）
 * - 判据 1（空 ⇒ 接高）：把「可行集为空」改成「回退最小门幅」⇒ 红；
 * - 判据 2（取最小可行）：把 `min` 换成 `max` ⇒ 红；
 * - 判据 3（分幅最少）：把「取 p 最小」改成「取 p 最大」⇒ 红；
 * - 判据 4（并列取较小门幅）：把并列规则改成较大 ⇒ 红；
 * - 判据 5（缺门幅不默认 2.8）：引入 `?? 2.8` ⇒ 红；
 * - 判据 6（有效门幅）：忽略 `allowance`（当 0）⇒ 红；
 * - 判据 7（成品高直接用）：对 H 做任何扣减 ⇒ 红；
 * - 判据 8（加工类型显式）：按高度自推加工类型 ⇒ 红。
 *
 * ## issue #5020 改判：**加工类型缺失 ⇒ 自动推导**（原判据 8 的「缺失 ⇒ undecidable」按设计已作废）
 *
 * 用户 2026-09-21 改判口径（以 issue #5020 为准，覆盖旧裁定「系统永不自己改判」）：
 * ```
 * 定高买宽可行（成品高 + HEM_MARGIN ≤ 门幅有效值）⇒ 取**可行集里最小门幅**；加工类型 = 定高买宽
 * 否则                                            ⇒ **倒幅**（分幅最少；并列取较小门幅）；加工类型 = 定宽买高
 * 接高                                            ⇒ **不参与自动比较**（接高 = 上下拼接、横缝可见；
 *                                                    行业实践是超高窗走倒幅把竖缝藏进褶皱）
 * 人工覆盖：显式传 定高买宽 / 定宽买高 ⇒ 按所选走（显式「定高买宽」而高度超限 ⇒ needs_splice）
 * ```
 * ⇒ `cuttingMode` 变**可选**，缺失时按上表推导并在返回值里带出 `effectiveCuttingMode`；
 * **表外取值仍 fail-closed**（`undecidable` / `missing-cutting-mode`，不猜）。
 *
 * 红证（改前实测）：`cuttingMode: undefined` ⇒ 改前一律 `undecidable`（`missing-cutting-mode`）
 * ⇒ 判据 1~3 与 5 全红；`effectiveCuttingMode` 改前**不存在** ⇒ 取到 `undefined` ⇒ 判据 1/2/5 红。
 *
 * ## issue #5038 改判：分幅数改**毫米整数**除法（与引擎同式）
 *
 * 用户/issue 实测的分叉：总用料**恰为门幅整数倍**时，浮点 `ceil(need / g_eff)` 会多算 1 幅
 * （`(1.1 + 0.3) × 2 = 2.8000000000000003` ⇒ 浮点 2 幅 / 引擎 1 幅），而幅数进 `(panels, 门幅)`
 * 双键排序 ⇒ 还会**翻转选中的门幅**。修法 = 与引擎 `-(-_mm(total) // max(1, _mm(ge)))` 同式的
 * 毫米整数除法 + 候选过滤补成引擎同式（`g_eff ≤ 0` 剔除，全剔除 ⇒ fail-closed）。
 *
 * 红证（改前实测，本文件新增的 golden 组）：`W=1.1 / 门幅 2.8 / 褶倍 2` 改前 `panels === 2`（真值 1）；
 * `W=3.9 / [2.8]` 改前 4（真值 3）；`W=1.1 / [1.4]` 改前 3（真值 2）；`W=3.9 / [1.4]` 改前 7（真值 6）；
 * `[2.8, 3.2]` 改前选中 **3.2**（真值 2.8）；`allowance ≥ 门幅` 改前**不报** `undecidable`（出 `Infinity`/垃圾幅数）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { resolveCutPlan, judgeDoorWidthChoice } from '@/lib/door-width-plan'
import { HEM_MARGIN } from '@/lib/craft-auto-features'

/** 前端门幅库源（反向守卫用）：`frontend/admin-web/src/lib/craft-auto-features.ts` */
const LIB_SRC = resolve(__dirname, '../../../src/lib/craft-auto-features.ts')

describe('门幅选择规则 resolveCutPlan（issue #4877）', () => {
  // ── 判据 1/2：定高买宽 —— 可行集取最小；空 ⇒ 接高 ──
  it('判据 2：候选 {2.8, 3.2} + 成品高 2.75 ⇒ 选 **3.2**（可行集里最小）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.8, 3.2],
    })
    expect(plan.state).toBe('single_panel')
    expect(plan.state === 'single_panel' && plan.doorWidth).toBe(3.2)
  })

  it('判据 2（反向）：候选 {3.2, 3.4} ⇒ 仍取 **3.2**（取更大门幅 ⇒ 红）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [3.4, 3.2],
    })
    expect(plan.state === 'single_panel' && plan.doorWidth).toBe(3.2)
  })

  it('判据 1：候选 {2.8} + 成品高 2.75 ⇒ **needs_splice**（缺口 = 2.75 + 0.3 − 2.8），不许回退 2.8 出数', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.8],
      openCount: 2,
    })
    expect(plan.state).toBe('needs_splice')
    if (plan.state !== 'needs_splice') throw new Error('unreachable')
    expect(plan.gapMeters).toBeCloseTo(2.75 + HEM_MARGIN - 2.8, 6)
    // 需接片数 = 开数（每片都要接一条）
    expect(plan.panelCount).toBe(2)
  })

  it('判据 1（边界）：成品高 + 卷边 **恰好等于** 有效门幅 ⇒ 可行（≥ 判据，不是 >）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.75 + HEM_MARGIN],
    })
    expect(plan.state).toBe('single_panel')
  })

  // ── 判据 3/4：定宽买高 —— 分幅最少；并列取较小门幅 ──
  it('判据 3：定宽买高 {2.8, 3.4} + 宽 3.0 × 2 倍 ⇒ 取 **3.4**（2 幅 < 3 幅）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      fullness: 2,
      cuttingMode: '定宽买高',
      candidates: [2.8, 3.4],
    })
    expect(plan.state).toBe('single_panel')
    if (plan.state !== 'single_panel') throw new Error('unreachable')
    expect(plan.doorWidth).toBe(3.4)
    expect(plan.panels).toBe(2)
  })

  it('判据 4：分幅数并列 ⇒ 取**较小**门幅（不占宽幅布）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      fullness: 2,
      cuttingMode: '定宽买高',
      candidates: [3.4, 2.8],
    })
    // ceil((3.0 + 0.3) × 2 ÷ 2.8) = 3；÷ 3.4 = 2 ⇒ 不并列，先确认这一档
    expect(plan.state === 'single_panel' && plan.doorWidth).toBe(3.4)
    const tie = resolveCutPlan({
      width: 1.0,
      height: 2.75,
      fullness: 2,
      cuttingMode: '定宽买高',
      candidates: [2.8, 3.0],
    })
    // ceil((1.0 + 0.3) × 2 ÷ 2.8) = ceil(0.93) = 1；÷ 3.0 = 1 ⇒ 并列 ⇒ 取较小 2.8
    expect(tie.state === 'single_panel' && tie.doorWidth).toBe(2.8)
    expect(tie.state === 'single_panel' && tie.panels).toBe(1)
  })

  // ── 判据 5：缺门幅 ⇒ undecidable（不得默认 2.8） ──
  it('判据 5：候选为空 ⇒ **undecidable**（默认 2.8 继续推算 ⇒ 红）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [],
    })
    expect(plan.state).toBe('undecidable')
    expect(plan.state === 'undecidable' && plan.code).toBe('no-door-width')
  })

  it('判据 5（不可解析）：候选里的 `2.8米` 走同一份解析（与 SKU 门幅同源）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: ['2.8米', '3.2米'],
    })
    expect(plan.state === 'single_panel' && plan.doorWidth).toBe(3.2)
  })

  // ── 判据 6：有效门幅（缩水/边损） ──
  it('判据 6：标称 2.8 + 有效余量 0.05 ⇒ g_eff = 2.75 ⇒ 可行集为空（当 0 算 ⇒ 红）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.8],
      allowance: 0.05,
    })
    expect(plan.state).toBe('needs_splice')
  })

  // ── 判据 7：成品高直接用（不扣离地/轨道） ──
  it('判据 7：门幅恰为 成品高 + 卷边 ⇒ 可行（对 H 做任何扣减 ⇒ 红）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [3.05],
    })
    expect(plan.state).toBe('single_panel')
    expect(plan.state === 'single_panel' && plan.reason).toContain('2.75')
  })

  // ── 判据 8（**issue #5020 改判**）：加工类型缺失 ⇒ **自动推导**；表外 ⇒ 仍 fail-closed ──
  //
  // 旧断言（改前）：「缺失 / 表外 ⇒ 一律 `undecidable`（`missing-cutting-mode`）」——
  // 该断言按 #5020 的**新口径已作废**（缺失 ⇒ 推导），故拆成两条：
  // ① 缺失 ⇒ 自动推导（判据 1~3、5）；② 表外 ⇒ 仍 `undecidable`（判据 6，不放宽）。
  it('判据 1：未指定加工类型 + 候选 {2.8,3.2} + 成品高 2.75 ⇒ 自动解 = **3.2 门幅 + 定高买宽**', () => {
    // 2.75 + 0.3 = 3.05 > 2.8（该档判需接高）但 ≤ 3.2 ⇒ 定高买宽可行 ⇒ 取**可行集里最小门幅** = 3.2
    const plan = resolveCutPlan({ width: 3.0, height: 2.75, candidates: [2.8, 3.2] })
    expect(plan.state).toBe('single_panel')
    if (plan.state !== 'single_panel') throw new Error('unreachable')
    expect(plan.doorWidth).toBe(3.2)
    expect(plan.panels).toBe(1)
    // 返回值必须**带出推导出的加工类型**（新增字段；既有字段语义不变）
    expect(plan.effectiveCuttingMode).toBe('定高买宽')
    // 反向：把自动解改成「取 2.8」（= 忽略可行性、只看最小候选）⇒ 本条必红
    expect(plan.doorWidth).not.toBe(2.8)
  })

  it('判据 2：未指定 + 可行集为空（成品高 3.0）⇒ **倒幅**（分幅最少；并列取较小门幅）', () => {
    // 3.0 + 0.3 = 3.3 > 3.2 = max(g_eff) ⇒ 定高买宽可行集为空 ⇒ 倒幅
    // ceil(3.0 × 2 ÷ 2.8) = ceil(2.143) = 3 幅；÷ 3.2 = ceil(1.875) = 2 幅
    // ⚠️ #5030 改判：宽方向去掉 0.3 后 3.0×2 = 6.0 —— 2.8 门幅 3 幅、3.2 门幅 **2 幅**（旧式 6.6 时两者都是 3 幅）。
    // ⇒ 本条现在钉的是**分幅最少**（2 幅 < 3 幅 ⇒ 取 3.2），不再是「并列取较小」。
    const tie = resolveCutPlan({ width: 3.0, height: 3.0, fullness: 2, candidates: [2.8, 3.2] })
    expect(tie.state).toBe('single_panel')
    if (tie.state !== 'single_panel') throw new Error('unreachable')
    expect(tie.effectiveCuttingMode).toBe('定宽买高')
    expect(tie.doorWidth).toBe(3.2)
    expect(tie.panels).toBe(2)

    // 分幅数**并列**时取较小门幅（不占宽幅布）：宽 1.5 ⇒ 3.0 ÷ 2.8 = 2 幅、÷ 3.2 = 1 幅（不并列）；
    // 宽 4.0 ⇒ 8.0 ÷ 2.8 = 3 幅、÷ 3.2 = 3 幅 ⇒ **并列** ⇒ 取较小 2.8
    const fewer = resolveCutPlan({ width: 4.0, height: 3.0, fullness: 2, candidates: [2.8, 3.2] })
    expect(fewer.state === 'single_panel' && fewer.doorWidth).toBe(2.8)
    expect(fewer.state === 'single_panel' && fewer.panels).toBe(3)

    // 单候选档（判据 2 字面形态）：{2.8} ⇒ 3 幅
    const single = resolveCutPlan({ width: 3.0, height: 3.0, fullness: 2, candidates: [2.8] })
    expect(single.state === 'single_panel' && single.panels).toBe(3)
    expect(single.state === 'single_panel' && single.effectiveCuttingMode).toBe('定宽买高')
  })

  it('判据 3：**不自动选接高** —— 接高更省（8.25 < 9.9）仍返回**倒幅**', () => {
    // 成品高 3.0 > 2.8 − 0.3 = 2.5 ⇒ 定高买宽不可行；按用户裁定的用料对比（本单**不实现**用料公式，
    // 只在注释里登记口径）：接高 8.25 米 < 倒幅 ceil(2.75 × 2 ÷ 2.8) = 2 幅 × 3.3 = 6.6 米。
    // （#5030 改判：分幅数由 3 幅变 2 幅 —— 宽方向去掉 0.3 后 2.75×2 = 5.5。）
    // ⇒ 即使接高更省，自动解**仍必须是倒幅**（接高 = 上下拼接、横缝可见；行业实践是超高窗走倒幅
    //   把竖缝藏进褶皱）—— `needs_splice` **不得自动出现**。
    const plan = resolveCutPlan({ width: 2.75, height: 3.0, fullness: 2, candidates: [2.8], openCount: 2 })
    expect(plan.state).toBe('single_panel')
    if (plan.state !== 'single_panel') throw new Error('unreachable')
    expect(plan.effectiveCuttingMode).toBe('定宽买高')
    expect(plan.doorWidth).toBe(2.8)
    expect(plan.panels).toBe(2)
    expect(plan.state).not.toBe('needs_splice')
  })

  it('判据 4：显式传 `定高买宽` 而高度超限 ⇒ 仍 `needs_splice`（人工覆盖路径保留）', () => {
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.8],
      openCount: 2,
    })
    expect(plan.state).toBe('needs_splice')
    if (plan.state !== 'needs_splice') throw new Error('unreachable')
    expect(plan.gapMeters).toBeCloseTo(0.25, 6)
    expect(plan.effectiveCuttingMode).toBe('定高买宽')
  })

  it('判据 5：显式传 `定宽买高` ⇒ 倒幅（人工覆盖生效，不被自动推导顶掉）', () => {
    // 成品高 2.4 时定高买宽本可行（2.4 + 0.3 = 2.7 ≤ 2.8）⇒ 若自动推导盖过显式选择，本条必红
    const plan = resolveCutPlan({
      width: 3.0,
      height: 2.4,
      fullness: 2,
      cuttingMode: '定宽买高',
      candidates: [2.8, 3.2],
    })
    expect(plan.state).toBe('single_panel')
    if (plan.state !== 'single_panel') throw new Error('unreachable')
    expect(plan.effectiveCuttingMode).toBe('定宽买高')
    // ceil(3.0 × 2 ÷ 2.8)=3、ceil(3.0 × 2 ÷ 3.2)=2 ⇒ 取分幅最少 = 3.2（2 幅）；
    // **不是**定高买宽的 2.8 单幅（panels=1）—— 显式选择必须压过自动推导。
    // （#5030 改判：旧式 6.6 时两者都是 3 幅 ⇒ 并列取 2.8；去掉 0.3 后不再是并列。）
    expect(plan.doorWidth).toBe(3.2)
    expect(plan.panels).toBe(2)
  })

  it('判据 6：表外取值（「正幅」/「倒幅」）⇒ **undecidable**（fail-closed 不放宽）', () => {
    for (const mode of ['正幅', '倒幅']) {
      const plan = resolveCutPlan({
        width: 3.0,
        height: 2.75,
        cuttingMode: mode,
        candidates: [2.8, 3.2],
      })
      expect(plan.state).toBe('undecidable')
      expect(plan.state === 'undecidable' && plan.code).toBe('missing-cutting-mode')
    }
    // 边界：**空串 = 「没给」**（`undefined` / `''` 同义）⇒ 走自动推导，不算「表外」
    expect(
      resolveCutPlan({ width: 3.0, height: 2.75, cuttingMode: '', candidates: [2.8, 3.2] }).state
    ).toBe('single_panel')
  })

  it('判据 7：缺尺寸 / 缺褶倍 / 缺门幅 ⇒ 仍 `undecidable`（既有 fail-closed 不得放宽）', () => {
    // 缺门幅（自动推导也一样不判）
    const noWidth = resolveCutPlan({ width: 3.0, height: 2.75, candidates: [] })
    expect(noWidth.state).toBe('undecidable')
    expect(noWidth.state === 'undecidable' && noWidth.code).toBe('no-door-width')

    // 缺成品高：**两个方向都判不了** ⇒ 自动推导不得凭空选一个方向
    const noHeight = resolveCutPlan({ width: 3.0, height: null, candidates: [3.2] })
    expect(noHeight.state).toBe('undecidable')
    expect(noHeight.state === 'undecidable' && noHeight.code).toBe('missing-size')

    // 缺成品宽：定高买宽可行时按定高买宽判（不需要宽）；**不可行 ⇒ 要倒幅 ⇒ 缺宽判不了**
    const autoOkNoWidthDim = resolveCutPlan({ width: null, height: 2.4, candidates: [2.8, 3.2] })
    expect(autoOkNoWidthDim.state === 'single_panel' && autoOkNoWidthDim.effectiveCuttingMode).toBe(
      '定高买宽'
    )
    const needWidth = resolveCutPlan({ width: null, height: 3.0, fullness: 2, candidates: [2.8] })
    expect(needWidth.state).toBe('undecidable')
    expect(needWidth.state === 'undecidable' && needWidth.code).toBe('missing-size')

    // 缺褶倍：倒幅算不出分幅数 ⇒ 不判（不拿假褶倍判价）
    const noFullness = resolveCutPlan({ width: 3.0, height: 3.0, candidates: [2.8] })
    expect(noFullness.state).toBe('undecidable')
    expect(noFullness.state === 'undecidable' && noFullness.code).toBe('missing-fullness')

    // 显式档的既有 fail-closed 原样保留
    expect(
      resolveCutPlan({ width: 3.0, height: 2.75, cuttingMode: '定宽买高', candidates: [3.2] }).state
    ).toBe('undecidable')
  })

  // ── 尺寸/褶倍缺失 ⇒ 不猜 ──
  it('判据 8（续）：成品高/宽缺失 ⇒ undecidable；定宽买高缺褶倍 ⇒ undecidable（不拿假褶倍判价）', () => {
    expect(
      resolveCutPlan({ width: 3.0, height: null, cuttingMode: '定高买宽', candidates: [3.2] }).state,
    ).toBe('undecidable')
    const noFullness = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定宽买高',
      candidates: [3.2],
    })
    expect(noFullness.state).toBe('undecidable')
    expect(noFullness.state === 'undecidable' && noFullness.code).toBe('missing-fullness')
  })

  // ── 真单回归（亿家纺织 CSO260918-03182） ──
  it('真单回归：3.0×2.75 双开 定高买宽 —— 门幅 3.2 ⇒ 单幅可做；门幅只有 2.8 ⇒ 需接高', () => {
    const ok = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [3.2],
      openCount: 2,
    })
    expect(ok.state).toBe('single_panel')
    expect(ok.state === 'single_panel' && ok.doorWidth).toBe(3.2)

    const splice = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.8],
      openCount: 2,
    })
    expect(splice.state).toBe('needs_splice')
    expect(splice.state === 'needs_splice' && splice.gapMeters).toBeCloseTo(0.25, 6)
  })

  it('判据 6（常量同源）：本模块**不新造** 0.3 —— 只复用 craft-auto-features 的**高方向**常量', () => {
    // 🔴 #5030 改判：宽方向已**没有**余量常量（原先这里还断言 `SIDE_MARGIN > 0`）⇒
    // 改成**同强度的反向守卫**：该常量不得复活（在 `craft-auto-features.ts` 加回 export ⇒ 红）。
    const lib = readFileSync(LIB_SRC, 'utf8')
    expect(lib).not.toContain('export const SIDE_MARGIN')
    expect(HEM_MARGIN).toBeGreaterThan(0)
    const byHeight = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.75 + HEM_MARGIN],
    })
    expect(byHeight.state).toBe('single_panel')
    // 宽方向**零余量**的直接判据：3.0 × 2 ÷ 3.05 = ceil(1.967…) = **2 幅**。
    // 若有人把「+ 0.3」加回宽方向 ⇒ 3.3 × 2 ÷ 3.05 = ceil(2.164…) = 3 幅 ⇒ 本条红。
    const byWidth = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      fullness: 2,
      cuttingMode: '定宽买高',
      candidates: [2.75 + HEM_MARGIN],
    })
    expect(byWidth.state === 'single_panel' && byWidth.panels).toBe(2)
  })
})

describe('客服所选门幅 ⇒ 相对规则解的提示 judgeDoorWidthChoice（issue #4877）', () => {
  const base = { width: 3.0, height: 2.75, candidates: [2.8, 3.2] as const }

  it('选了**非最优**（可行但更宽）⇒ `suboptimal` + 建议文案点名规则解', () => {
    const judged = judgeDoorWidthChoice(
      { ...base, cuttingMode: '定高买宽' },
      3.4, // 不在候选集里也不影响判定：只要比规则解宽就是「占了宽幅布」
    )
    expect(judged.verdict).toBe('suboptimal')
    expect(judged.suggestion).toContain('3.2 米门幅')
  })

  it('选了**规则解** ⇒ `optimal` 且**不给建议**（不 nag）', () => {
    const judged = judgeDoorWidthChoice({ ...base, cuttingMode: '定高买宽' }, 3.2)
    expect(judged.verdict).toBe('optimal')
    expect(judged.suggestion).toBeNull()
  })

  it('所选门幅**单幅做不出** ⇒ `infeasible`（比非最优更强：先告警「需接高」）', () => {
    const judged = judgeDoorWidthChoice({ ...base, cuttingMode: '定高买宽' }, 2.8)
    expect(judged.verdict).toBe('infeasible')
    expect(judged.suggestion).toContain('需接高')
    expect(judged.suggestion).toContain('3.2 米门幅')
  })

  it('定宽买高：所选门幅分幅更多 ⇒ `suboptimal`，文案给出**多买的幅数**', () => {
    const judged = judgeDoorWidthChoice(
      { width: 3.0, height: 2.75, fullness: 2, cuttingMode: '定宽买高', candidates: [2.8, 3.4] },
      2.8,
    )
    expect(judged.verdict).toBe('suboptimal')
    expect(judged.suggestion).toContain('少 1 幅')
  })

  it('定宽买高：分幅数**并列**（米数相同）⇒ `optimal`（挑哪个门幅是库存/单价的事，不 nag）', () => {
    const judged = judgeDoorWidthChoice(
      { width: 1.0, height: 2.75, fullness: 2, cuttingMode: '定宽买高', candidates: [2.8, 3.0] },
      3.0,
    )
    expect(judged.verdict).toBe('optimal')
    expect(judged.suggestion).toBeNull()
  })

  it('未选门幅 / 门幅未维护 / 规则不可判定 ⇒ `unknown`（没有可比对象 ⇒ 不提示最优）', () => {
    expect(judgeDoorWidthChoice({ ...base, cuttingMode: '定高买宽' }, undefined).verdict).toBe('unknown')
    expect(judgeDoorWidthChoice({ ...base, cuttingMode: '定高买宽' }, '加宽').verdict).toBe('unknown')
    expect(
      judgeDoorWidthChoice({ ...base, cuttingMode: '定高买宽', candidates: [] }, 2.8).verdict,
    ).toBe('unknown')
  })

  // ── issue #5020：judgeDoorWidthChoice 与 resolveCutPlan **同步**（它内部调后者） ──
  it('判据 5（判定同步）：未指定加工类型 + 显式倒幅档 ⇒ 按**推导出的**加工类型给建议', () => {
    // 成品高 3.0 ⇒ 自动解 = 定宽买高 + 分幅最少；客服选 2.8 而规则解是 3.2
    // （#5030：去掉 0.3 后 6.0 ÷ 2.8 = 3 幅、6.0 ÷ 3.2 = 2 幅 ⇒ 规则解 3.2）⇒ 提示多买的幅数
    const judged = judgeDoorWidthChoice(
      { width: 3.0, height: 3.0, fullness: 2, candidates: [2.8, 3.2] },
      2.8
    )
    expect(judged.plan.state === 'single_panel' && judged.plan.effectiveCuttingMode).toBe('定宽买高')
    expect(judged.plan.state === 'single_panel' && judged.plan.doorWidth).toBe(3.2)
    expect(judged.verdict).toBe('suboptimal')
    expect(judged.suggestion).toContain('少 1 幅')
  })

  it('判据 5（判定同步）：未指定 + 高度超限 + 显式 `定宽买高` ⇒ 给分幅建议、**不给**「需接高」告警', () => {
    // 客服按倒幅选了 2.8，即便 2.75 + 0.3 > 2.8 也不该报「需接高」——
    // 改前 `judgeDoorWidthChoice` 读 `input.cuttingMode`（undefined）⇒ 走进定宽买高的分支是巧合，
    // 但读 `input.cuttingMode === '定高买宽'` 的判据在**显式倒幅**时才是真分歧点。
    // 🔴 #5030 改判：去掉 0.3 后 3.0×2 = 6.0 ⇒ 选 2.8 = 3 幅、规则解 3.2 = 2 幅
    // ⇒ 所选**不再是规则解**（旧式 6.6 时两者都是 3 幅 ⇒ optimal）⇒ 现在应给「少 1 幅」建议。
    // 判据强度不变：仍是 `toBe('suboptimal')` 精确断言 + 反向断言「不得出现接高告警」。
    const judged = judgeDoorWidthChoice(
      { width: 3.0, height: 2.75, fullness: 2, cuttingMode: '定宽买高', candidates: [2.8, 3.2] },
      2.8
    )
    expect(judged.verdict).toBe('suboptimal')
    expect(judged.suggestion).toContain('少 1 幅')
    expect(judged.suggestion).not.toContain('需接高')
  })
})

// ── 跨语言 golden 算例表（issue #5038）：分幅数必须与引擎**逐值相等** ──────────────
/**
 * 共享 golden 算例表 = `tests/fixtures/panels-cross-language-golden.json`（**三侧共读**同一份输入与期望值）：
 * ① **引擎腿**（跑真引擎）`backend/ai-agent-service/tests/test_curtain_calc_fabric_plan.py`；
 * ② **静态腿** `tests/unit_ci_workflows/test_panels_cross_language_algorithm_guard.py`
 *    （照源复算 + 钉 TS 源码里**不再出现浮点直除形态**）；
 * ③ **本文件**（跑真 TS）。
 *
 * 三侧任一漂移即红 ⇒ 这才是「TS 与引擎 panels 逐值相等」的**可执行**判据
 * （改前只有常量级守卫 `test_hem_margin_cross_language_drift.py`，它覆盖不到算法）。
 *
 * ⚠️ 本表只钉**取整口径**（浮点 vs 毫米整数）；A 通路与 B1/B2 的 `side_margin` 差异是**另一件事**，
 * 登记在 `docs/design/craft-calc-and-fabric-routing.md` §4.5（issue #4760），不在本组范围。
 */
interface GoldenCase {
  id: string
  why: string
  width: number
  height: number
  fullness: number
  allowance: number
  candidates: number[]
  expected: {
    state: 'single_panel' | 'undecidable'
    panelsPerCandidate?: number[]
    chosenDoorWidth?: number
    chosenPanels?: number
  }
}

const GOLDEN = JSON.parse(
  readFileSync(
    resolve(__dirname, '../../../../../tests/fixtures/panels-cross-language-golden.json'),
    'utf8'
  )
) as { cases: GoldenCase[] }

describe('跨语言 golden 算例表：分幅数与引擎逐值相等（issue #5038）', () => {
  it('算例表非空、候选已升序去重（两侧按下标对齐 ⇒ 前提必须成立）', () => {
    expect(GOLDEN.cases.length).toBeGreaterThanOrEqual(10)
    for (const c of GOLDEN.cases) {
      expect(c.candidates, c.id).toEqual([...c.candidates].sort((a, b) => a - b))
      expect(new Set(c.candidates).size, c.id).toBe(c.candidates.length)
    }
  })

  for (const c of GOLDEN.cases) {
    it(`${c.id}：${c.why}`, () => {
      const plan = resolveCutPlan({
        width: c.width,
        height: c.height,
        fullness: c.fullness,
        cuttingMode: '定宽买高',
        candidates: c.candidates,
        allowance: c.allowance,
      })
      if (c.expected.state === 'undecidable') {
        // 候选全被有效余量剔除 ⇒ 与引擎同为 fail-closed（改前出 `Infinity` / 负幅数被兜成 1 幅 ⇒ 红）
        expect(plan.state).toBe('undecidable')
        expect(plan.state === 'undecidable' && plan.code).toBe('no-door-width')
        return
      }
      expect(plan.state).toBe('single_panel')
      if (plan.state !== 'single_panel') throw new Error('unreachable')
      expect(plan.doorWidth).toBe(c.expected.chosenDoorWidth)
      expect(plan.panels).toBe(c.expected.chosenPanels)
      // 逐候选幅数（与引擎腿同口径）：单候选调用一次即可测得
      c.candidates.forEach((doorWidth, i) => {
        const one = resolveCutPlan({
          width: c.width,
          height: c.height,
          fullness: c.fullness,
          cuttingMode: '定宽买高',
          candidates: [doorWidth],
          allowance: c.allowance,
        })
        expect(one.state === 'single_panel' && one.panels, `${c.id} 门幅 ${doorWidth}`).toBe(
          c.expected.panelsPerCandidate?.[i]
        )
      })
    })
  }

  it('判据 5：`allowance ≥ 门幅` ⇒ `undecidable`（改前 `Math.ceil(need / 0) = Infinity` 静默产出垃圾）', () => {
    const zero = resolveCutPlan({
      width: 1.1,
      height: 3.0,
      fullness: 2,
      cuttingMode: '定宽买高',
      candidates: [2.8],
      allowance: 2.8,
    })
    expect(zero.state).toBe('undecidable')
    expect(zero.state === 'undecidable' && zero.code).toBe('no-door-width')
    // 负有效门幅同样 fail-closed（改前 `Math.max(1, ceil(need / 负数)) = 1` 幅 = 垃圾）
    expect(
      resolveCutPlan({
        width: 1.1,
        height: 3.0,
        fullness: 2,
        cuttingMode: '定宽买高',
        candidates: [2.8],
        allowance: 3.0,
      }).state
    ).toBe('undecidable')
    // 反向护栏：余量**小于**门幅时不得误剔（把过滤写成 `≥` 或写成恒真 ⇒ 红）
    expect(
      resolveCutPlan({
        width: 1.1,
        height: 3.0,
        fullness: 2,
        cuttingMode: '定宽买高',
        candidates: [2.8],
        allowance: 2.79,
      }).state
    ).toBe('single_panel')
  })

  it('判定同步：`judgeDoorWidthChoice` 的「所选门幅要几幅」也走毫米整数除法（改前多报 1 幅）', () => {
    // 所选 1.4（不在候选集里）：真值 ceil(2800 / 1400) = 2 幅；浮点 ceil(2.8000000000000003 / 1.4) = 3 幅
    const judged = judgeDoorWidthChoice(
      {
        width: 1.1,
        height: 3.0,
        fullness: 2,
        cuttingMode: '定宽买高',
        candidates: [2.8, 3.2],
      },
      1.4
    )
    expect(judged.plan.state === 'single_panel' && judged.plan.panels).toBe(1)
    expect(judged.verdict).toBe('suboptimal')
    expect(judged.suggestion).toContain('少 1 幅')
    expect(judged.suggestion).not.toContain('少 2 幅')
  })
})
