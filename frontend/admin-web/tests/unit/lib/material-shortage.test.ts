// case_ids: MC-182
/**
 * 缺料风险页的口径单点 `frontend/admin-web/src/lib/material-shortage.ts` 的判据（issue #6282）。
 *
 * 为什么单独立一个 **lib 级**文件（而不是只测页面）：Growth Gate 的 `tech-stack.yml` 把
 * `src/lib/*.ts` 映射到 `tests/unit/lib/<name>.test.ts`，而这几条「取值 / 过滤 / 未知语义」
 * 是**纯函数**，页面测只能间接覆盖；且它们正是「最容易写成软断言」的地方
 * （缺口 0 与「读不出」长得很像 —— 前者是事实，后者是**未知**）。
 *
 * ## 判据（每条都会红）
 *
 * - **缺口过滤**：`shortageRows` 只留 `gapMeters > 0`；`0` / 负数 / **缺键** 都不算缺料。
 *   红证：把条件改成 `>= 0` ⇒ ② 红；把缺键当 0 ⇒ ③ 红。
 * - **未知 ≠ 0**：`formatMeters(undefined)` = `未知`、`formatMeters(0)` = `0 米`
 *   —— 两者必须**可区分**（`null` 不回落成 0）。
 * - **交期缺键 ⇒ 紧迫性未知**：不得显示「0 天」；`days === 0` 才是「今天到期」。
 * - **两段披露只在真的有时才出现**：`nonComparable.products === 0` ⇒ `null`；
 *   `historyDepth.sufficient === true` ⇒ `null`（**未知不许被读成达标，达标也不许乱披露**）。
 * - **缺料条数取四档之和**（`blocked/critical/soon/short`），`safe` / `unknown` 不计入。
 * - **档位标签安全**：未知档位 ⇒ `未知`（**不**把内部键原样上屏，§31 P3）。
 */
import { describe, it, expect } from 'vitest'
import {
  DEADLINE_UNKNOWN,
  NO_SHORTAGE,
  UNKNOWN,
  bandCountsText,
  bandLabel,
  deadlineText,
  formatMeters,
  gapMeters,
  historyDepthNote,
  nonComparableNote,
  ordersText,
  shortageCount,
  shortageRows,
  truncationNote,
} from '@/lib/material-shortage'
import type { MaterialShortageView } from '@/types'

const view = (over: Partial<MaterialShortageView> = {}): MaterialShortageView => ({
  view: 'material_shortage',
  tenantId: 1,
  asOf: '2026-10-04',
  rows: [],
  count: 0,
  rowsTotal: 0,
  truncated: false,
  ...over,
})

describe('缺口过滤：默认面只列真正缺的（§31 P1）', () => {
  it('只留 gapMeters > 0；0 / 负 / 缺键 都不算缺料', () => {
    const rows = [
      { productId: 'a', productName: '缺 120', gapMeters: 120 },
      { productId: 'b', productName: '缺 5', gapMeters: 5 },
      { productId: 'c', productName: '刚好够', gapMeters: 0 },
      { productId: 'd', productName: '有余量', gapMeters: -40 },
      { productId: 'e', productName: '读不出' },
    ]
    // 行序原样保留（本函数**不排序**：行序是服务端的契约）
    expect(shortageRows(rows).map((r) => r.productName)).toEqual(['缺 120', '缺 5'])
  })

  it('gapMeters 把缺键 / null / 非数 一律读成 null（未知），不读成 0', () => {
    expect(gapMeters({ gapMeters: 0 })).toBe(0)
    expect(gapMeters({ gapMeters: 12.5 })).toBe(12.5)
    expect(gapMeters({})).toBe(null)
    expect(gapMeters({ gapMeters: null })).toBe(null)
  })

  it('未知 ≠ 0：缺值渲染「未知」，真 0 渲染「0 米」，负值照实', () => {
    expect(formatMeters(undefined)).toBe(UNKNOWN)
    expect(formatMeters(null)).toBe(UNKNOWN)
    expect(formatMeters(0)).toBe('0 米')
    expect(formatMeters(-40)).toBe('-40 米')
    // 千分位 + 至多两位小数（原样渲染服务端值，不四舍五入到 0）
    expect(formatMeters(12540.3)).toBe('12,540.3 米')
    expect(formatMeters(0.004)).toBe('0 米')
  })

  it('影响订单：缺键 ⇒ 未知（不印「0 个订单」）', () => {
    expect(ordersText({ orderCount: 3 })).toBe('3 个订单')
    expect(ordersText({})).toBe(UNKNOWN)
  })
})

describe('交期：缺键 ⇒ 紧迫性未知（不显示「0 天」）', () => {
  it('四个分支逐字', () => {
    expect(deadlineText(null, null)).toBe(DEADLINE_UNKNOWN)
    expect(deadlineText('2026-10-01', -2)).toBe('2026-10-01（已过 2 天）')
    expect(deadlineText('2026-10-04', 0)).toBe('2026-10-04（今天到期）')
    expect(deadlineText('2026-10-06', 2)).toBe('2026-10-06（2 天后）')
    // 有日期但服务端没给天数（不可比）⇒ 仍是「紧迫性未知」，不猜
    expect(deadlineText('2026-10-06', undefined)).toBe(DEADLINE_UNKNOWN)
  })
})

describe('披露：只在真的有时才出现（未知 ≠ 达标，达标 ≠ 要披露）', () => {
  it('单位不可比：0 个商品 ⇒ 不披露；有 ⇒ 逐字给出两个数', () => {
    expect(nonComparableNote(view())).toBe(null)
    expect(nonComparableNote(view({ nonComparable: { lines: 0, products: 0 } }))).toBe(null)
    expect(nonComparableNote(view({ nonComparable: { lines: 2, products: 1 } }))).toBe(
      '另有 1 个成品（2 行订单）单位不是「米」⇒ 需求与缺口读不出，未计入上面的数字'
    )
    // 平铺冗余键同样可用（服务端两处同值）
    expect(nonComparableNote(view({ nonComparableLines: 5, nonComparableProducts: 3 }))).toBe(
      '另有 3 个成品（5 行订单）单位不是「米」⇒ 需求与缺口读不出，未计入上面的数字'
    )
  })

  it('历史深度：sufficient=false ⇒ 明说「预测层未启用」+ 真实 vs 要求；true ⇒ 不披露', () => {
    expect(historyDepthNote(null)).toBe(null)
    expect(
      historyDepthNote({ weeks: 8, activeWeeks: 8, requiredWeeks: 8, sufficient: true })
    ).toBe(null)
    expect(
      historyDepthNote({ weeks: 3, activeWeeks: 2, requiredWeeks: 8, sufficient: false })
    ).toBe('预测层未启用：真实历史深度 3 周 < 要求 8 周 ⇒ 周消耗速率与预计耗尽日为未知')
  })

  it('截断披露：只有 truncated 才说；不 truncated ⇒ 不出现', () => {
    expect(truncationNote(view())).toBe(null)
    expect(truncationNote(view({ truncated: true, count: 50, rowsTotal: 137 }))).toBe(
      '本页显示前 50 个（共 137 个候选，按紧迫度排序）'
    )
  })
})

describe('条数与档位文案', () => {
  it('缺料条数 = 四档之和（safe / unknown 不计入）', () => {
    expect(
      shortageCount({ blocked: 1, critical: 2, soon: 0, short: 3, safe: 40, unknown: 7 })
    ).toBe(6)
    expect(shortageCount(null)).toBe(0)
    expect(shortageCount({ safe: 9, unknown: 1 })).toBe(0)
  })

  it('六档披露只列非空档，且用商家话（不出现内部档名）', () => {
    expect(bandCountsText(null)).toBe('')
    expect(
      bandCountsText({ blocked: 1, critical: 0, soon: 2, short: 0, safe: 0, unknown: 1 })
    ).toBe('交期已过 1 · 交期临近 2 · 单位不可比 1')
    // 未知档位不原样上屏（§31 P3）
    expect(bandLabel('some_internal_band')).toBe(UNKNOWN)
    expect(bandLabel(null)).toBe(UNKNOWN)
    expect(bandLabel('blocked')).toBe('交期已过')
  })

  it('空态文案是事实陈述（逐字，非「暂无数据」）', () => {
    expect(NO_SHORTAGE).toBe('当前没有缺料')
  })
})
