// case_ids: UI-054
/**
 * 配置指挥台的**域目录单一真值模块**守卫（issue #6580；设计真值源
 * `docs/design/enterprise-settings-redesign.md`）。
 *
 * ## 为什么这份清单值得单独钉
 *
 * 页面左栏的四个区 / 八个域**只从这里渲染**（`frontend/admin-web/src/app/(dashboard)/settings/page.tsx`
 * 不写死任何域名字面量）。若没有本文件，「少了一个域」「域的 key 被改名（旧 URL `?domain=` 就失效）」
 * 「某个区空掉」都不会有任何东西变红 —— 而它们都是**用户直接看得见**的形态缺陷。
 *
 * 红证形态：
 * - 把 `CONFIG_DOMAINS` 少写一个域 ⇒ 判据 1 的「八个 key 逐字齐全」必红；
 * - 把某个域的 `key` 改名（如 `remnant-sizes` → `remnantSizes`）⇒ 判据 1 必红（URL 契约随之失效）；
 * - 把某一域挂到一个不存在的区 / 让某区没有域 ⇒ 判据 2 必红。
 */
import { describe, expect, it } from 'vitest'
import {
  CONFIG_DOMAINS,
  CONFIG_ZONES,
  domainsOfZone,
  findDomain,
  mainlineStepsOfDomain,
} from '@/lib/config-center-domains'
import { MAINLINE_STEPS, worstState } from '@/lib/config-readiness'

/** 设计真值源给出的**逐字**域 key（这份清单是 URL 契约，改它 = 旧链接失效） */
const EXPECTED_KEYS = [
  'calc',
  'processing-fee',
  'craft-route',
  'remnant-sizes',
  'enterprise',
  'ai',
  'worker-pages',
  'notifications',
] as const

describe('判据 1：域目录 —— 八个 key **逐字**齐全、顺序即依赖顺序', () => {
  it('`CONFIG_DOMAINS` 的 key 序列与设计真值源逐字一致（改名/漏项 ⇒ 红）', () => {
    expect(CONFIG_DOMAINS.map((d) => d.key)).toEqual([...EXPECTED_KEYS])
  })

  it('每个域的 key / label / summary / requiredCode 都非空（空 ⇒ 页面渲染出空白）', () => {
    for (const d of CONFIG_DOMAINS) {
      expect(d.key, JSON.stringify(d)).toBeTruthy()
      expect(d.label.trim(), d.key).toBeTruthy()
      expect(d.summary.trim(), d.key).toBeTruthy()
      expect(d.requiredCode.trim(), d.key).toBeTruthy()
    }
  })

  it('key 不重复（重复 ⇒ 同一个 testid/URL 指向两个域）', () => {
    expect(new Set(CONFIG_DOMAINS.map((d) => d.key)).size).toBe(CONFIG_DOMAINS.length)
  })
})

describe('判据 2：区 — 四区都有域、域都挂在存在的区（不许空区/幽灵区）', () => {
  it('区 key 与顺序逐字（quote / production / material / tenant）', () => {
    expect(CONFIG_ZONES.map((z) => z.key)).toEqual(['quote', 'production', 'material', 'tenant'])
  })

  it('每个域所属区都真实存在（幽灵区 ⇒ 该域永远不被渲染）', () => {
    const zoneKeys = new Set(CONFIG_ZONES.map((z) => z.key))
    for (const d of CONFIG_DOMAINS) {
      expect(zoneKeys.has(d.zone), `${d.key} 挂在未知区 ${d.zone}`).toBe(true)
    }
  })

  it('四区**都不为空**、且区内的域数之和 = 域总数（不重复挂、不漏挂）', () => {
    for (const z of CONFIG_ZONES) {
      expect(domainsOfZone(z.key).length, `区 ${z.key} 是空的`).toBeGreaterThan(0)
    }
    const total = CONFIG_ZONES.reduce((n, z) => n + domainsOfZone(z.key).length, 0)
    expect(total).toBe(CONFIG_DOMAINS.length)
  })
})

describe('判据 3：查域 / 主线步骤映射（页面与徽标都取这里）', () => {
  it('`findDomain` 命中登记的 key，未知 key 返回 `undefined`（**不编**一个默认域）', () => {
    for (const d of CONFIG_DOMAINS) {
      expect(findDomain(d.key)).toBe(d)
    }
    expect(findDomain('nope')).toBeUndefined()
    expect(findDomain(null)).toBeUndefined()
  })

  it('域声明的 `mainlineSteps` 必须**逐条**真实存在于 `MAINLINE_STEPS`（打错字 ⇒ 徽标永远「读不到」）', () => {
    const stepKeys = new Set(MAINLINE_STEPS.map((s) => s.key))
    for (const d of CONFIG_DOMAINS) {
      for (const step of mainlineStepsOfDomain(d)) {
        expect(stepKeys.has(step), `${d.key} 声明了不存在的步骤 ${step}`).toBe(true)
      }
    }
  })

  it('只有**真被主线覆盖**的域才声明 mainlineSteps（算料域被 `calc` 步覆盖即为例）', () => {
    // 正控：算料域有徽标来源
    expect(mainlineStepsOfDomain(findDomain('calc')!)).toEqual(['calc'])
    // 一个域覆盖**多步**（「工艺与路线」= 工序 + 路线 + 默认路线）⇒ 徽标取**最差**那一步，见下条
    expect(mainlineStepsOfDomain(findDomain('craft-route')!)).toEqual([
      'operations',
      'routings',
      'default-route',
    ])
    // 反面：企业信息不在主线里 ⇒ 不声明（编读数 = 第二份会漂的口径）
    expect(mainlineStepsOfDomain(findDomain('enterprise')!)).toEqual([])
  })

  it('🔴 一个域覆盖多步 ⇒ 徽标取**最差**（`todo` > `unknown` > `done`）：报「已配置」会让人漏掉没配的那一步', () => {
    // 判据本身住在 `@/lib/config-readiness`（三态的唯一家），这里只钉住它对这个域的取值
    expect(worstState(['done', 'todo', 'done'])).toBe('todo')
    expect(worstState(['done', 'unknown'])).toBe('unknown')
    expect(worstState(['done', 'done'])).toBe('done')
    // 主线没覆盖 ⇒ 不编读数（不显示徽标）
    expect(worstState([])).toBeNull()
    expect(worstState([undefined, undefined])).toBeNull()
  })
})
