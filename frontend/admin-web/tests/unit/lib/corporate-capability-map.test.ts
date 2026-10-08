// case_ids: UI-082
import { describe, it, expect } from 'vitest'
import { menuGroups, standaloneItems, standaloneTopItems } from '@/config/menu'
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
 */
describe('官网能力地图 × 后台菜单（config/menu.ts）同源', () => {
  const menuItemNames = [
    ...menuGroups.flatMap((group) => group.children.map((item) => item.name)),
    ...standaloneTopItems.map((item) => item.name),
    ...standaloneItems.map((item) => item.name),
  ]
  const menuGroupNames = menuGroups.map((group) => group.name)
  const siteItemNames = [
    ...capabilityDomains.flatMap((domain) => domain.items.map((item) => item.name)),
    ...standaloneEntries.map((item) => item.name),
  ]

  it('官网能力地图不得编造后台没有的功能名', () => {
    const fabricated = siteItemNames.filter((name) => !menuItemNames.includes(name))
    expect(fabricated).toEqual([])
  })

  it('后台每个菜单项都必须在官网能力地图里有位置（否则官网漏讲能力）', () => {
    const missing = menuItemNames.filter((name) => !siteItemNames.includes(name))
    expect(missing).toEqual([])
  })

  it('官网的六个能力域分组名与后台分组名逐字一致', () => {
    const fabricatedGroups = capabilityDomains
      .map((domain) => domain.name)
      .filter((name) => !menuGroupNames.includes(name))
    expect(fabricatedGroups).toEqual([])
  })

  it('官网展示的菜单项总数由数据算出来（不写死）且等于后台菜单总数', () => {
    expect(menuItemCount).toBe(siteItemNames.length)
    expect(menuItemCount).toBe(menuItemNames.length)
  })
})
