// case_ids: UI-054
/**
 * 配置主线（configuration mainline）**纯判据**守卫（issue #6573）。
 *
 * 真值模块 = `frontend/admin-web/src/lib/config-readiness.ts`（单一真值：跨页主线与 `routings` 页内五步共用）。
 * 本文件只判**纯函数**（取数、渲染、DOM 一律不在这里 —— 那两半分别在
 * `frontend/admin-web/tests/unit/pages/settings-params.test.tsx` 与
 * `frontend/admin-web/tests/unit/components/ConfigReadinessBar`（经页面渲染）承担）。
 *
 * ## 三条纪律，逐条有判据（这是本文件存在的理由）
 *
 * 1. 🔴 **三态不可互画**：`todo` = 确定的没配；`unknown` = 读不到。读失败 ⇒ `unknown`，
 *    **绝不**降级成 `todo`（把「没读到」画成「没配」）。
 * 2. 🔴 **「取不到」不等于 0**：可选输入用 `null`（不参与判定），不是 `0`（真的是零）。
 *    ⇒ 判据 = `orphans=null` 与 `orphans=3` **结果必须不同**（同值就是某个实现把两者混了）。
 * 3. 🔴 **基础路线判「缺哪条」，不数条数**：`missingBaseRoutesOf` 只能从 `BASE_ROUTE_NAMES` 派生
 *    （本文件**不写第二份**路线名 —— 写第二份正是「同一个概念两个载体」的病根）。
 */
import { describe, expect, it } from 'vitest'
import {
  BASE_ROUTE_NAMES,
  MAINLINE_STEPS,
  judgeBaseRoutesStep,
  judgeConfigSourceStep,
  judgeDefaultRouteStep,
  judgeFeeCombinationsStep,
  judgeOperationsStep,
  judgeProcessingItemsStep,
  judgeRemnantSizesStep,
  missingBaseRoutesOf,
  readinessHeadline,
  statesFromFacts,
  summarizeReadiness,
  type ReadinessState,
} from '@/lib/config-readiness'

/** 主线一步的判定输入（判据里只用到这三项） */
function entry(key: string, state: ReadinessState, blocking = true) {
  return { key, state, blocking }
}

describe('判据 1：算料配置步的三态（source 五值全覆盖）', () => {
  it("stored ⇒ done；'default' ⇒ todo；undefined / null / '' / 'unavailable' ⇒ **unknown**（读不到就说读不到）", () => {
    expect(judgeConfigSourceStep('stored')).toBe('done')
    expect(judgeConfigSourceStep('default')).toBe('todo')
    expect(judgeConfigSourceStep(undefined)).toBe('unknown')
    expect(judgeConfigSourceStep(null)).toBe('unknown')
    expect(judgeConfigSourceStep('')).toBe('unknown')
    expect(judgeConfigSourceStep('unavailable')).toBe('unknown')
  })

  it('🔴 三态不可互画：认不出的 source **绝不**回落成 done 或 todo', () => {
    for (const s of [undefined, null, '', 'unavailable', 'engine', 'STORED']) {
      const state = judgeConfigSourceStep(s)
      expect(state).toBe('unknown')
      expect(state).not.toBe('todo')
      expect(state).not.toBe('done')
    }
  })
})

describe('判据 2：工序与单价步（读失败 ⇒ unknown；未定价 / 孤儿 ⇒ todo）', () => {
  it('readFailed ⇒ unknown（**绝不放行**成 done：读不到不等于「都配好了」）', () => {
    expect(
      judgeOperationsStep({ readFailed: true, total: 0, unpriced: 0, orphans: null })
    ).toBe('unknown')
    // 同一次读失败，即使其余维度的数看着「很齐」，也仍必须是 unknown
    expect(
      judgeOperationsStep({ readFailed: true, total: 9, unpriced: 0, orphans: 0 })
    ).toBe('unknown')
  })

  it('total=0 ⇒ todo（一道工序都没有 = 确定的没配）；unpriced>0 ⇒ todo（有活没价）', () => {
    expect(
      judgeOperationsStep({ readFailed: false, total: 0, unpriced: 0, orphans: null })
    ).toBe('todo')
    expect(
      judgeOperationsStep({ readFailed: false, total: 5, unpriced: 2, orphans: null })
    ).toBe('todo')
  })

  it('orphans>0 ⇒ todo；orphans=0 ⇒ done（有工序、都定价、没有孤儿）', () => {
    expect(
      judgeOperationsStep({ readFailed: false, total: 5, unpriced: 0, orphans: 3 })
    ).toBe('todo')
    expect(
      judgeOperationsStep({ readFailed: false, total: 5, unpriced: 0, orphans: 0 })
    ).toBe('done')
  })

  it('🔴 红证「取不到 ≠ 0」：`orphans=null` **不参与判定**（⇒ done），与 `orphans=3`（⇒ todo）结果不同', () => {
    const base = { readFailed: false, total: 5, unpriced: 0 }
    const unknownOrphans = judgeOperationsStep({ ...base, orphans: null })
    const threeOrphans = judgeOperationsStep({ ...base, orphans: 3 })
    expect(unknownOrphans).toBe('done')
    expect(threeOrphans).toBe('todo')
    // 核心断言：把 `null` 当 `0` 的实现（或用 `?? 0` 兜底的实现）会让两者**相等** ⇒ 当场红
    expect(unknownOrphans).not.toBe(threeOrphans)
  })
})

describe('判据 3：两条基础路线（判「缺哪条」，不数条数）', () => {
  it('missingBaseRoutesOf 的名字一律取自 BASE_ROUTE_NAMES（本文件不写第二份清单）', () => {
    expect(BASE_ROUTE_NAMES).toHaveLength(2)
    expect(missingBaseRoutesOf([...BASE_ROUTE_NAMES])).toEqual([])
    expect(missingBaseRoutesOf([])).toEqual([...BASE_ROUTE_NAMES])
    expect(missingBaseRoutesOf([BASE_ROUTE_NAMES[0]])).toEqual([BASE_ROUTE_NAMES[1]])
    expect(missingBaseRoutesOf([BASE_ROUTE_NAMES[1]])).toEqual([BASE_ROUTE_NAMES[0]])
  })

  it('🔴 商家自建路线**不顶替**基础路线（数条数会把它判成「齐」—— 用户实测踩到过）', () => {
    expect(missingBaseRoutesOf(['商家自建路线'])).toEqual([...BASE_ROUTE_NAMES])
    expect(
      missingBaseRoutesOf(['商家自建路线', BASE_ROUTE_NAMES[0], BASE_ROUTE_NAMES[1]])
    ).toEqual([])
  })

  it('judgeBaseRoutesStep：两条齐 ∧ 无空壳 ⇒ done；缺一条 / 有空壳 ⇒ todo', () => {
    expect(judgeBaseRoutesStep([])).toBe('done')
    expect(judgeBaseRoutesStep([], 0)).toBe('done')
    expect(judgeBaseRoutesStep(missingBaseRoutesOf([]))).toBe('todo')
    expect(judgeBaseRoutesStep([BASE_ROUTE_NAMES[0]])).toBe('todo')
    expect(judgeBaseRoutesStep([], 1)).toBe('todo')
  })
})

describe('判据 4：默认路线（恰好一条才算完成）', () => {
  it('1 条 ⇒ done；0 条（派不出去）与 ≥2 条（兜底终点不确定）⇒ todo', () => {
    expect(judgeDefaultRouteStep(1)).toBe('done')
    expect(judgeDefaultRouteStep(0)).toBe('todo')
    expect(judgeDefaultRouteStep(2)).toBe('todo')
    expect(judgeDefaultRouteStep(5)).toBe('todo')
  })
})

describe('判据 5：加工费组合（读面没取到 ⇒ unknown；有组合且无缺口 ⇒ done）', () => {
  it('任一读面为 null ⇒ unknown（缺口语义在服务端，前端不重算、也不当作 0）', () => {
    expect(judgeFeeCombinationsStep(null, 0)).toBe('unknown')
    expect(judgeFeeCombinationsStep(3, null)).toBe('unknown')
    expect(judgeFeeCombinationsStep(null, null)).toBe('unknown')
  })

  it('(0, 0) ⇒ todo（一个组合都没有）；(3, 2) ⇒ todo（有组合但订单里出现过没价的）；(3, 0) ⇒ done', () => {
    expect(judgeFeeCombinationsStep(0, 0)).toBe('todo')
    expect(judgeFeeCombinationsStep(0, 2)).toBe('todo')
    expect(judgeFeeCombinationsStep(3, 2)).toBe('todo')
    expect(judgeFeeCombinationsStep(3, 0)).toBe('done')
  })
})

describe('判据 6：汇总读数（summarizeReadiness）', () => {
  it('三态计数 / 完成数 / 阻断未完成数逐值正确；下一步 = 第一个 todo', () => {
    const summary = summarizeReadiness([
      entry('operations', 'done'),
      entry('routings', 'unknown'),
      entry('default-route', 'todo'),
      entry('calc', 'done', false),
    ])
    expect(summary).toEqual({
      done: 2,
      todo: 1,
      unknown: 1,
      total: 4,
      nextKey: 'default-route',
      blockingLeft: 2,
    })
  })

  it('没有 todo 时下一步取第一个 unknown（确定的缺口优先，但「读不到」也要有去处）', () => {
    const summary = summarizeReadiness([
      entry('operations', 'done'),
      entry('routings', 'unknown'),
      entry('default-route', 'unknown'),
    ])
    expect(summary.nextKey).toBe('routings')
    expect(summary.todo).toBe(0)
    expect(summary.unknown).toBe(2)
  })

  it('全完成 ⇒ nextKey=null、blockingLeft=0；非阻断步未完成**不**计入 blockingLeft', () => {
    const allDone = summarizeReadiness(MAINLINE_STEPS.map((s) => entry(s.key, 'done', s.blocking)))
    expect(allDone.nextKey).toBeNull()
    expect(allDone.blockingLeft).toBe(0)
    expect(allDone.done).toBe(MAINLINE_STEPS.length)

    const calcOnly = summarizeReadiness(
      MAINLINE_STEPS.map((s) => entry(s.key, s.key === 'calc' ? 'todo' : 'done', s.blocking))
    )
    expect(calcOnly.nextKey).toBe('calc')
    expect(calcOnly.blockingLeft).toBe(0) // 算料是非阻断步：没配不挡业务
  })

  it('空清单 ⇒ 全 0 且 nextKey=null（不 NaN、不谎报「已完成」）', () => {
    expect(summarizeReadiness([])).toEqual({
      done: 0,
      todo: 0,
      unknown: 0,
      total: 0,
      nextKey: null,
      blockingLeft: 0,
    })
  })
})

describe('判据 7：常驻面摘要文案（readinessHeadline，§31 P1/P4）', () => {
  const done = (key: string) => entry(key, 'done')

  it('全完成 ⇒ 明说「配置已完成 N/N」（不含「下一步」）', () => {
    const summary = summarizeReadiness(MAINLINE_STEPS.map((s) => done(s.key)))
    const text = readinessHeadline(summary, null)
    expect(text).toContain('配置已完成')
    expect(text).toContain(`${summary.done}/${summary.total}`)
    expect(text).not.toContain('下一步')
    expect(text).not.toContain('未配置')
  })

  it('有缺口 ⇒ 含完成数、未配置条数与「下一步「<步名>」」', () => {
    const summary = summarizeReadiness([
      done('operations'),
      entry('routings', 'todo'),
      entry('default-route', 'done'),
      entry('fee-combinations', 'todo'),
      entry('calc', 'done', false),
    ])
    const text = readinessHeadline(summary, '工艺路线')
    expect(text).toContain('配置完成 3/5')
    expect(text).toContain('2 项未配置')
    expect(text).toContain('下一步「工艺路线」')
  })

  it('缺口全是「读不到」⇒ 说的是「读不到（刷新可重试）」，**不**说成「未配置」（三态不互画）', () => {
    const summary = summarizeReadiness([done('operations'), entry('routings', 'unknown')])
    const text = readinessHeadline(summary, '工艺路线')
    expect(text).toContain('读不到')
    expect(text).toContain('刷新可重试')
    expect(text).not.toContain('未配置')
    // §31 P4 语调：只陈述事实 + 该做什么 —— 不堆惊叹号
    expect(text).not.toContain('！')
    expect(text).not.toContain('!')
  })
})

describe('判据 8：主线目录（MAINLINE_STEPS）的形态', () => {
  it('恰好 7 步、键唯一，且顺序 = 依赖顺序（加工项在加工费组合之前；issue #6579 接上两步）', () => {
    expect(MAINLINE_STEPS.map((s) => s.key)).toEqual([
      'operations',
      'routings',
      'default-route',
      'processing-items',
      'fee-combinations',
      'remnant-sizes',
      'calc',
    ])
    expect(new Set(MAINLINE_STEPS.map((s) => s.key)).size).toBe(MAINLINE_STEPS.length)
  })

  it('每步都有 label / why / impact / href（Href 是站内深链）；阻断步 = 工序 / 路线 / 默认路线 / 加工费组合', () => {
    for (const s of MAINLINE_STEPS) {
      expect(s.label.length).toBeGreaterThan(0)
      expect(s.why.length).toBeGreaterThan(0)
      expect(s.impact.length).toBeGreaterThan(0)
      expect(s.href.startsWith('/')).toBe(true)
    }
    expect(MAINLINE_STEPS.filter((s) => s.blocking).map((s) => s.key)).toEqual([
      'operations',
      'routings',
      'default-route',
      'fee-combinations',
    ])
  })

  it('算料步的去处就是本页（`/settings/params`）—— 主线与菜单项指向同一个入口', () => {
    expect(MAINLINE_STEPS.find((s) => s.key === 'calc')?.href).toBe('/settings/params')
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 9：服务端事实 → 三态（`statesFromFacts`，issue #6579）
//
// 为什么这条是「只发一个请求」的**判据面**：聚合端点只给事实，三态怎么从事实推出来
// 必须**仍然只有一处**（本模块）。下面每条都用「事实」当输入，而不是三态当输入 ——
// 这样翻译逻辑一改，断言当场红；服务端若偷偷给三态字符串，也不会被采信（末条）。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 9：服务端事实 → 三态（statesFromFacts）', () => {
  /** 一份「全配好」的事实载荷（形状 = 端点 `data.steps`）。 */
  const healthyFacts = () => ({
    operations: { facts: { total: 2, unpriced: 0, orphans: 0 }, href: '/production/routings' },
    routings: { facts: { missing_base_routes: [] }, href: '/production/routings' },
    'default-route': { facts: { count: 1 }, href: '/production/routings' },
    'processing-items': { facts: { total: 4, active: 3 }, href: '/settings?domain=processing-items' },
    'fee-combinations': { facts: { combinations: 3, gaps: 0 }, href: '/production/processing-fees' },
    calc: { facts: { source: 'stored' }, href: '/settings/params' },
  })

  it('全绿事实 ⇒ 六步全 done；**载荷里没有** remnant-sizes ⇒ 不产出那个键（不是 unknown）', () => {
    const states = statesFromFacts(healthyFacts())
    expect(states).toEqual({
      operations: 'done',
      routings: 'done',
      'default-route': 'done',
      'processing-items': 'done',
      'fee-combinations': 'done',
      calc: 'done',
    })
    expect(Object.prototype.hasOwnProperty.call(states, 'remnant-sizes')).toBe(false)
  })

  it('跨码步骤在载荷里（持 processing:manage）⇒ 产出它的三态', () => {
    const states = statesFromFacts({
      ...healthyFacts(),
      'remnant-sizes': { facts: { configured: true, items: 2 }, href: '/settings?domain=remnant-sizes' },
    })
    expect(states['remnant-sizes']).toBe('done')
  })

  it('🔴 facts **缺键** ⇒ unknown，**绝不**降级成 todo（读不到 ≠ 没配）', () => {
    const states = statesFromFacts({
      ...healthyFacts(),
      operations: { facts: { total: 2 }, href: '/production/routings' },
      'fee-combinations': { facts: { combinations: 3 }, href: '/production/processing-fees' },
      'processing-items': { facts: { total: 4 }, href: '/settings?domain=processing-items' },
    })
    expect(states.operations).toBe('unknown')
    expect(states['fee-combinations']).toBe('unknown')
    expect(states['processing-items']).toBe('unknown')
  })

  it('🔴 服务端若给三态字符串（`done`）当事实 ⇒ 也读成 unknown（三态不被采信）', () => {
    const states = statesFromFacts({
      ...healthyFacts(),
      calc: { facts: { source: 'done' }, href: '/settings/params' },
    })
    expect(states.calc).toBe('unknown')
  })

  it('整个请求没拿到（`undefined` / `null`）⇒ 空对象（渲染面按「全部读不到」处理）', () => {
    expect(statesFromFacts(undefined)).toEqual({})
    expect(statesFromFacts(null)).toEqual({})
  })

  it('「有工序、未定价、孤儿」三个事实逐条驱动第 ① 步（不是只看总数）', () => {
    expect(
      statesFromFacts({ ...healthyFacts(), operations: { facts: { total: 2, unpriced: 1, orphans: 0 } } })
        .operations,
    ).toBe('todo')
    expect(
      statesFromFacts({ ...healthyFacts(), operations: { facts: { total: 2, unpriced: 0, orphans: 1 } } })
        .operations,
    ).toBe('todo')
    expect(
      statesFromFacts({ ...healthyFacts(), operations: { facts: { total: 0, unpriced: 0, orphans: 0 } } })
        .operations,
    ).toBe('todo')
  })

  it('加工项：全停用 ⇒ todo；余料尺寸：未配置 ⇒ todo（两步的口径各判一次）', () => {
    expect(judgeProcessingItemsStep({ total: 3, active: 0 })).toBe('todo')
    expect(judgeProcessingItemsStep({ total: 0, active: 0 })).toBe('todo')
    expect(judgeProcessingItemsStep({ total: 3, active: 1 })).toBe('done')
    expect(judgeRemnantSizesStep({ configured: false, items: 0 })).toBe('todo')
    expect(judgeRemnantSizesStep({ configured: true, items: 1 })).toBe('done')
  })
})
