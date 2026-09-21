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
 * 定宽买高: 幅数 p(g) = ceil((W + SIDE_MARGIN) × 褶倍 ÷ g_eff(g))；取 p 最小者，并列取较小 g
 * 加工类型缺失/表外 ⇒ undecidable（裁定 6：**不替调用方猜朝向**）
 * ```
 * ⚠️ 余量常量**复用** `craft-auto-features.ts` 的 `SIDE_MARGIN` / `HEM_MARGIN`（副本有跨语言守卫），
 * 本模块**不新造第二个 0.3**；加工类型常量同样复用（措辞不得成为第二份判据）。
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
 */
import { describe, it, expect } from 'vitest'

import { resolveCutPlan, judgeDoorWidthChoice } from '@/lib/door-width-plan'
import { HEM_MARGIN, SIDE_MARGIN } from '@/lib/craft-auto-features'

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
    // ceil((3.0 + 0.3) × 2 ÷ 2.8) = ceil(2.357) = 3 幅；÷ 3.2 = ceil(2.0625) = 3 幅
    // ⇒ **并列取较小门幅** = 2.8（不占宽幅布）
    const tie = resolveCutPlan({ width: 3.0, height: 3.0, fullness: 2, candidates: [2.8, 3.2] })
    expect(tie.state).toBe('single_panel')
    if (tie.state !== 'single_panel') throw new Error('unreachable')
    expect(tie.effectiveCuttingMode).toBe('定宽买高')
    expect(tie.doorWidth).toBe(2.8)
    expect(tie.panels).toBe(3)

    // 分幅数不并列时取**分幅最少**（3 幅 < 4 幅）：宽 5.0 ⇒ ceil(10.6/2.8)=4、ceil(10.6/3.2)=4 并列；
    // 宽 3.3 ⇒ ceil(7.2/2.8)=3、ceil(7.2/3.2)=3 并列 ⇒ 用 4.0 宽拿非并列档：ceil(8.6/2.8)=4、ceil(8.6/3.2)=3
    const fewer = resolveCutPlan({ width: 4.0, height: 3.0, fullness: 2, candidates: [2.8, 3.2] })
    expect(fewer.state === 'single_panel' && fewer.doorWidth).toBe(3.2)
    expect(fewer.state === 'single_panel' && fewer.panels).toBe(3)

    // 单候选档（判据 2 字面形态）：{2.8} ⇒ 3 幅
    const single = resolveCutPlan({ width: 3.0, height: 3.0, fullness: 2, candidates: [2.8] })
    expect(single.state === 'single_panel' && single.panels).toBe(3)
    expect(single.state === 'single_panel' && single.effectiveCuttingMode).toBe('定宽买高')
  })

  it('判据 3：**不自动选接高** —— 接高更省（8.25 < 9.9）仍返回**倒幅**', () => {
    // 成品高 3.0 > 2.8 − 0.3 = 2.5 ⇒ 定高买宽不可行；按用户裁定的用料对比（本单**不实现**用料公式，
    // 只在注释里登记口径）：接高 8.25 米 < 倒幅 ceil((2.75 + 0.3) × 2 ÷ 2.8) = 3 幅 × 3.3 = 9.9 米。
    // ⇒ 即使接高更省，自动解**仍必须是倒幅**（接高 = 上下拼接、横缝可见；行业实践是超高窗走倒幅
    //   把竖缝藏进褶皱）—— `needs_splice` **不得自动出现**。
    const plan = resolveCutPlan({ width: 2.75, height: 3.0, fullness: 2, candidates: [2.8], openCount: 2 })
    expect(plan.state).toBe('single_panel')
    if (plan.state !== 'single_panel') throw new Error('unreachable')
    expect(plan.effectiveCuttingMode).toBe('定宽买高')
    expect(plan.doorWidth).toBe(2.8)
    expect(plan.panels).toBe(3)
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
    // ceil(6.6/2.8)=3、ceil(6.6/3.2)=3 ⇒ 并列取较小 2.8；**不是**定高买宽的 2.8 单幅（panels=1）
    expect(plan.panels).toBe(3)
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

  it('判据 6（常量同源）：本模块**不新造** 0.3 —— 用 craft-auto-features 的副本常量', () => {
    // 同一份入参，两方向的余量语义不同（宽 SIDE_MARGIN / 高 HEM_MARGIN），今天的值都是 0.3
    expect(SIDE_MARGIN).toBeGreaterThan(0)
    expect(HEM_MARGIN).toBeGreaterThan(0)
    const byHeight = resolveCutPlan({
      width: 3.0,
      height: 2.75,
      cuttingMode: '定高买宽',
      candidates: [2.75 + HEM_MARGIN],
    })
    expect(byHeight.state).toBe('single_panel')
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
    // 成品高 3.0 ⇒ 自动解 = 定宽买高 + 分幅最少；客服选 2.8 而规则解是 3.2 ⇒ 提示多买的幅数
    const judged = judgeDoorWidthChoice(
      { width: 4.0, height: 3.0, fullness: 2, candidates: [2.8, 3.2] },
      2.8
    )
    expect(judged.plan.state === 'single_panel' && judged.plan.effectiveCuttingMode).toBe('定宽买高')
    expect(judged.verdict).toBe('suboptimal')
    expect(judged.suggestion).toContain('少 1 幅')
  })

  it('判据 5（判定同步）：未指定 + 高度超限 + 显式 `定宽买高` ⇒ 不给「需接高」告警（那是定高买宽的解）', () => {
    // 客服按倒幅选了 2.8（规则解），即便 2.75 + 0.3 > 2.8 也不该报「需接高」——
    // 改前 `judgeDoorWidthChoice` 读 `input.cuttingMode`（undefined）⇒ 走进定宽买高的分支是巧合，
    // 但读 `input.cuttingMode === '定高买宽'` 的判据在**显式倒幅**时才是真分歧点。
    const judged = judgeDoorWidthChoice(
      { width: 3.0, height: 2.75, fullness: 2, cuttingMode: '定宽买高', candidates: [2.8, 3.2] },
      2.8
    )
    expect(judged.verdict).toBe('optimal')
    expect(judged.suggestion).toBeNull()
  })
})
