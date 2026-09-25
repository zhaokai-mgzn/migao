// case_ids: PR-079
/**
 * 订单级「加急 / 要求到货日」（issue #5177）前端**唯一取值口径**的**注入式红证**（issue #5195）。
 *
 * ## 为什么这个文件必须存在（不是为覆盖率凑数）
 *
 * `.github/cases/product.yml` 的 `PR-079` 在 `data_checks` 散文里**声称了红证**：
 *
 * > 「列表页加急角标随值出现/消失（**红证 = 把缺省改成「总是加急」⇒ 角标断言红**）」
 *
 * 而 `frontend/admin-web/tests/unit/components/OrderTableUrgency.test.tsx` 里 `红证` 命中 = 0
 * —— 判别力此前只存在于措辞里（`migao-acceptance`：不会红的断言 = 空断言）。
 * 本文件用本仓既有范式（`tests/unit/lib/copy-no-markdown-emphasis.test.ts` 的正控/负控 +
 * `tests/unit_ci_workflows/test_case_machine_fail_channel.py` 的 `TestInjectionRedProofs`）
 * 把它落成**能单独变红**的注入式夹具：**同一个判据表达式**分别跑真实实现与变异体。
 *
 * ## 判据分工（DOM 面在别处）
 *
 * - **DOM 面**：`tests/unit/components/OrderTableUrgency.test.tsx`（列表角标逐值）/
 *   `tests/unit/components/OrderUrgencyPanel.test.tsx`（详情徽标正反两态）/
 *   `tests/unit/pages/orders-urgency.test.tsx`（建单请求体「键不存在」）/
 *   `tests/unit/pages/production-pool-urgent.test.tsx`（智能派单插队区角标）。
 * - **源码面（本文件）**：口径的**唯一性**（三处角标 + 一处请求体都走同一份纯函数）
 *   —— 没有这一条，上面的红证与 DOM 面**脱钩**（改坏了纯函数而组件不用它，红证就白证了）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { isUrgentFlag, urgencyRequestFields, urgentBadgeText } from '@/lib/order-urgency'

describe('加急取值口径（PR-079 判据 2：缺省不变）', () => {
  it('只有服务端明确给 `true` 才算加急；缺省 / 字段缺席 / `null` 一律「不加急」', () => {
    expect(urgentBadgeText({ isUrgent: true })).toBe('加急')
    expect(urgentBadgeText({ isUrgent: false })).toBe('不加急')
    expect(urgentBadgeText({})).toBe('不加急')
    expect(urgentBadgeText({ isUrgent: null })).toBe('不加急')
    expect(urgentBadgeText(null)).toBe('不加急')
    expect(urgentBadgeText(undefined)).toBe('不加急')
    expect(isUrgentFlag({ isUrgent: true })).toBe(true)
    expect(isUrgentFlag({ isUrgent: false })).toBe(false)
  })

  it('建单请求体：未勾 / 未填 ⇒ **键不出现**；表达了意图 ⇒ 带键', () => {
    expect(urgencyRequestFields(false, '')).toEqual({})
    expect(Object.keys(urgencyRequestFields(false, ''))).toEqual([])
    expect(urgencyRequestFields(true, '2026-10-01')).toEqual({
      isUrgent: true,
      requiredDeliveryDate: '2026-10-01',
    })
    expect(urgencyRequestFields(true, '')).toEqual({ isUrgent: true })
    expect(urgencyRequestFields(false, '2026-10-01')).toEqual({ requiredDeliveryDate: '2026-10-01' })
  })
})

describe('🔴 红证夹具：PR-079 散文声称的两条红证（issue #5195）', () => {
  /** 三种「缺省/否」输入 —— `OrderTableUrgency.test.tsx` 的 DOM 断言正是对它们成立的 */
  const DEFAULTS: { label: string; src: { isUrgent?: boolean | null } }[] = [
    { label: '服务端明确 false', src: { isUrgent: false } },
    { label: '字段整体缺席（老响应）', src: {} },
    { label: '服务端 null', src: { isUrgent: null } },
  ]

  /** **判据本体**（正控与负控跑同一份）：角标文案必须与服务端真值一致（缺省 ⇒ 不加急） */
  const badgeViolations = (textOf: (s: { isUrgent?: boolean | null }) => string) =>
    DEFAULTS.filter((c) => textOf(c.src) !== '不加急').map((c) => c.label)

  it('① 正控：变异体「总是加急」（丢掉服务端值）⇒ 三条角标判据**逐条**变红', () => {
    const alwaysUrgent = () => '加急' // 单点变异形态：不读服务端值
    expect(badgeViolations(alwaysUrgent)).toEqual([
      '服务端明确 false',
      '字段整体缺席（老响应）',
      '服务端 null',
    ])
  })

  it('② 负控（对照组）：真实实现零违规 —— 红是变异体造成的，不是判据本来就红', () => {
    expect(badgeViolations(urgentBadgeText)).toEqual([])
  })

  /** **判据本体**：未勾 / 未填 ⇒ 请求体里**不得出现**这两个键（`false` / `''` 也不行） */
  const keyLeaks = (build: (isUrgent: boolean, date: string) => Record<string, unknown>) => {
    const body = build(false, '')
    const out: string[] = []
    if (Object.prototype.hasOwnProperty.call(body, 'isUrgent')) {
      out.push('未勾 ⇒ 请求体仍出现 isUrgent 键（把「没填」写成「显式不加急」）')
    }
    if (Object.prototype.hasOwnProperty.call(body, 'requiredDeliveryDate')) {
      out.push('未填 ⇒ 请求体仍出现 requiredDeliveryDate 键（把「未指定」写成显式值）')
    }
    return out
  }

  it('③ 正控：变异体「无条件带键」（= 散文写的 `isUrgent: isUrgent`）⇒ 当场报出两条', () => {
    const alwaysKeys = (isUrgent: boolean, requiredDeliveryDate: string) => ({
      isUrgent,
      requiredDeliveryDate,
    })
    expect(keyLeaks(alwaysKeys)).toEqual([
      '未勾 ⇒ 请求体仍出现 isUrgent 键（把「没填」写成「显式不加急」）',
      '未填 ⇒ 请求体仍出现 requiredDeliveryDate 键（把「未指定」写成显式值）',
    ])
  })

  it('④ 负控（对照组）：真实实现零泄漏 —— 红是变异体造成的，不是判据本来就红', () => {
    expect(keyLeaks(urgencyRequestFields)).toEqual([])
    // 反向：表达了意图就必须带键（否则「不落键」会被「什么都不传」冒充）
    expect(Object.keys(urgencyRequestFields(true, '2026-10-01'))).toEqual([
      'isUrgent',
      'requiredDeliveryDate',
    ])
  })

  it('⑤ 接线：三处角标 + 一处请求体必须走同一份口径（否则上面的红证与 DOM 面脱钩）', () => {
    const consumers: { file: string; call: string }[] = [
      { file: 'src/components/orders/OrderTable.tsx', call: 'urgentBadgeText(order)' },
      { file: 'src/components/orders/OrderUrgencyPanel.tsx', call: 'urgentBadgeText(order)' },
      { file: 'src/app/(dashboard)/production/pool/page.tsx', call: 'urgentBadgeText(line)' },
      {
        file: 'src/app/(dashboard)/orders/new/page.tsx',
        call: '...urgencyRequestFields(isUrgent, requiredDeliveryDate)',
      },
    ]
    const problems: string[] = []
    for (const { file, call } of consumers) {
      const src = readFileSync(join(process.cwd(), file), 'utf-8')
      // 位置性证据：只看 import 语句与调用点（注释里提到模块名不算接线）
      if (!/^\s*import\s+\{[^}]*\}\s+from\s+'@\/lib\/order-urgency'/m.test(src)) {
        problems.push(`${file} 没有 import @/lib/order-urgency`)
      }
      if (!src.includes(call)) problems.push(`${file} 没有调用 ${call}（自己又写了一份口径）`)
    }
    expect(problems).toEqual([])
  })
})
