// case_ids: UI-082
import { describe, it, expect } from 'vitest'
import { menuGroups, standaloneHeadItems, standaloneItems, standaloneTopItems } from '@/config/menu'
import {
  capabilityDomains,
  menuItemCount,
  standaloneEntries,
} from '@/components/corporate/capability-map'

/**
 * 官网「能力地图」× 后台菜单的**同源判据**（issue #6291，铁律 8 的类级元守卫）。
 *
 * 病根：官网文案与产品现实脱节，从来不是「有人写错了一句话」，而是**两处各写一份、
 * 谁改了都不会变红**。本判据把 `frontend/admin-web/src/components/corporate/capability-map.ts`
 * 与 `frontend/admin-web/src/config/menu.ts` 钉在一起：
 *
 * - 后台**改了 / 删了 / 加了**菜单项 ⇒ 官网能力地图必须同批跟上，否则本用例当场红；
 * - 官网**自己编一个不存在的功能名**（把没做的事写上去）⇒ 同样当场红。
 *
 * 它只判「名字层面」的同源；每个能力点的**描述措辞**是否属实由页面用例与人工评审承担
 * （如实登记的未固化项，见 PR #6292 的「类级固化声明」）。
 *
 * ══════════════════════════════════════════════════════════════════════════════
 * 🔴 2026-10-17（issue #7087）新增的**官网独有文案台账**（两处，具名、只许缩短）
 * ══════════════════════════════════════════════════════════════════════════════
 *
 * `capability-map.ts` 是**登录前的企业官网营销页**（不是侧边栏菜单）：它的能力域分组是
 * **排版面**，与 `menu.ts` 的侧边栏分组只是**当时同形**。issue #7087 撤掉了「工作台」组与
 * 「每日简报」菜单项 ⇒ 这**两个字符串**在后台已无同名菜单/组，但它们是否该从**官网**撤掉是
 * **产品口径判断**（本轮任务明确：不擅自大改官网文案）⇒ 这里**保留现状**，并把差值**具名登记**
 * 成台账，而不是把判据放宽成「官网爱写什么写什么」：
 *
 *   · 台账**只许缩短** —— 台账里的名字一旦在后台重新出现（菜单名/组名），下面「台账不得藏漂移」
 *     那两条当场红，逼你把该条从他的台账里删掉（而不是留着掩盖真实漂移）；
 *   · 台账里的名字必须**真的在官网出现** —— 官网哪天自己删了它，同样当场红（防止台账腐烂成
 *     「一条永远为真、永远没人看」的豁免）；
 *   · 除台账外的**全部**名字仍走严格双向相等（后台 ⊄ 官网 / 官网 ⊄ 后台 都红）。
 *
 * 未裁定项（交人工）：官网要不要保留「工作台」这个能力域名、「每日简报」这个能力条目？
 * 见交付报告「需裁定」一节；本轮**不动官网文案**。
 */
const SITE_ONLY_ITEM_NAMES: readonly string[] = ['每日简报']
const SITE_ONLY_DOMAIN_NAMES: readonly string[] = ['工作台']

describe('官网能力地图 × 后台菜单（config/menu.ts）同源', () => {
  const menuItemNames = [
    // 🔴 2026-10-17（issue #7087）：**最前席位**（`standaloneHeadItems`，如「经营看板」）必须计入 ——
    // 漏了这个数组，「经营看板」会被当成「官网编造的功能名」而**假红**（判据的面必须与菜单同步演进）。
    ...standaloneHeadItems.map((item) => item.name),
    ...menuGroups.flatMap((group) => group.children.map((item) => item.name)),
    ...standaloneTopItems.map((item) => item.name),
    ...standaloneItems.map((item) => item.name),
  ]
  const menuGroupNames = menuGroups.map((group) => group.name)
  const siteItemNames = [
    ...capabilityDomains.flatMap((domain) => domain.items.map((item) => item.name)),
    ...standaloneEntries.map((item) => item.name),
  ]
  const siteDomainNames = capabilityDomains.map((domain) => domain.name)

  it('官网能力地图不得编造后台没有的功能名（台账外一名都不许差）', () => {
    const fabricated = siteItemNames.filter(
      (name) => !menuItemNames.includes(name) && !SITE_ONLY_ITEM_NAMES.includes(name),
    )
    expect(fabricated).toEqual([])
  })

  it('后台每个菜单项都必须在官网能力地图里有位置（否则官网漏讲能力）', () => {
    const missing = menuItemNames.filter((name) => !siteItemNames.includes(name))
    expect(missing).toEqual([])
  })

  it('官网能力域分组名 = 后台分组名 ∪ 具名台账；台账外不得编造', () => {
    const fabricatedGroups = siteDomainNames.filter(
      (name) => !menuGroupNames.includes(name) && !SITE_ONLY_DOMAIN_NAMES.includes(name),
    )
    expect(fabricatedGroups).toEqual([])
  })

  it('🔴 台账不得藏漂移（只许缩短）：台账里的名字在后台**存在**或在官网**不存在** ⇒ 当场红', () => {
    // ① 台账项不得是后台**真实存在**的菜单名/组名 —— 否则它已经不是「官网独有」，
    //    留着就是拿台账掩盖一次真实漂移（口径：只许缩短）。
    expect(SITE_ONLY_ITEM_NAMES.filter((n) => menuItemNames.includes(n))).toEqual([])
    expect(SITE_ONLY_DOMAIN_NAMES.filter((n) => menuGroupNames.includes(n))).toEqual([])
    // ② 台账项必须**真的在官网出现** —— 否则台账腐烂成一条永远为真的豁免，没人会去删它。
    for (const n of SITE_ONLY_ITEM_NAMES) expect(siteItemNames).toContain(n)
    for (const n of SITE_ONLY_DOMAIN_NAMES) expect(siteDomainNames).toContain(n)
    // ③ 台账**确实在起作用**（否则上面几条的「∪ 台账」是空跑）：两个名单都不是空的
    expect(SITE_ONLY_ITEM_NAMES.length).toBeGreaterThan(0)
    expect(SITE_ONLY_DOMAIN_NAMES.length).toBeGreaterThan(0)
  })

  it('官网展示的菜单项总数由数据算出来（不写死）且 = 后台菜单总数 + 台账条数', () => {
    expect(menuItemCount).toBe(siteItemNames.length)
    expect(menuItemCount).toBe(menuItemNames.length + SITE_ONLY_ITEM_NAMES.length)
    // 反恒真：后台菜单面本身不是空的、且台账只占其中**少数**（不是「台账吞掉全部差异」的形态）
    expect(menuItemNames.length).toBeGreaterThan(SITE_ONLY_ITEM_NAMES.length)
    // 分组面同理（台账只许是**个别**分组名，不能变成「官网分组随便写」）
    expect(menuGroupNames.length).toBeGreaterThanOrEqual(siteDomainNames.length - SITE_ONLY_DOMAIN_NAMES.length)
    expect(siteDomainNames).toHaveLength(menuGroupNames.length + SITE_ONLY_DOMAIN_NAMES.length)
  })
})
