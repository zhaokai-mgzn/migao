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

  // ── 判据 8：加工类型显式（不按高度自推） ──
  it('判据 8：加工类型缺失 / 表外 ⇒ **undecidable**（按高度自推 ⇒ 红）', () => {
    for (const mode of [undefined, '', '正幅', '倒幅']) {
      const plan = resolveCutPlan({
        width: 3.0,
        height: 2.75,
        cuttingMode: mode,
        candidates: [2.8, 3.2],
      })
      expect(plan.state).toBe('undecidable')
      expect(plan.state === 'undecidable' && plan.code).toBe('missing-cutting-mode')
    }
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
})
