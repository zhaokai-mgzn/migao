// case_ids: PR-106, MC-019
/**
 * 菜单图标注册表守卫（issue #5271，挂在 PR-106「菜单三源同构 / 图标注册」与
 * MC-019「图标维度的归属裁决」上）。
 *
 * ## 病根（本文件存在的唯一理由）
 *
 * 重设计前 `Sidebar.tsx` 里内联 `iconMap[item.icon] || BarChart3` —— **漏注册不报错**：
 * 菜单照常渲染、没有任何东西变红，只是那一项的图标**静默回落**成柱状图
 * （`remnants-menu-isomorphic.test.tsx` 的注释里逐字记着这个形态）。
 * issue #5271 把注册表抽成 `frontend/admin-web/src/config/menu-icons.ts`（纯数据 + 纯函数）
 * ⇒ 「`menu.ts` 出现的每个图标名都已注册」变成**可判定**的。
 *
 * ## 判据（三条，各带判别力）
 *
 *   ① **正向不漏**：`menu.ts` 里出现的**每个**图标名都在 `menuIconMap` 注册
 *      （同时按「真实对象」与「源码文本」两条路径取，避免只测一条路径而漏掉另一条）；
 *   ② **反向无死映射**：`menuIconMap` 里不得有 `menu.ts` 用不到的键（双向相等）——
 *      死映射不是「无害冗余」：它会让「图标已注册」的判据把**用不到的**名字也算进注册面；
 *   ③ **注入式红证**：把某个 icon 名改成**未注册值** ⇒ ① 的检查函数当场判红
 *      （证明 ① 不是恒真断言；红证落在**源码文本**上，避开「判据被自己的文案喂绿」）。
 *
 * ⚠️ 图标维度的**归属裁决**（MC-019）：图标是**前端专属**（服务端不下发 icon）⇒
 * 本文件的真值源就是 `menu.ts` + `menu-icons.ts` 两个前端文件，**不比对服务端**
 * （服务端比对在 `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { menuGroups, standaloneItems, type MenuItem } from '@/config/menu'
import { menuIconMap, resolveMenuIcon, registeredIconNames } from '@/config/menu-icons'

const MENU_TS = readFileSync(join(process.cwd(), 'src/config/menu.ts'), 'utf-8')

const allItems = (): MenuItem[] => [
  ...menuGroups.map((g) => ({ key: g.key, name: g.name, icon: g.icon, path: '' }) as MenuItem),
  ...menuGroups.flatMap((g) => g.children),
  ...standaloneItems,
]

/** 源码文本里的图标名（判据 ①/③ 的独立取数路径 —— 不依赖 TS 运行时对象） */
function iconNamesFromSource(src: string): string[] {
  return Array.from(src.matchAll(/icon:\s*'([^']+)'/g)).map((m) => m[1])
}

/** 「未注册的图标名」检查器（判据 ① 与 ③ 共用同一个函数 ⇒ 红证才有判别力） */
function unregisteredIcons(names: string[], registered: readonly string[]): string[] {
  const set = new Set(registered)
  return names.filter((n) => !set.has(n))
}

describe('菜单图标注册表（issue #5271 / PR-106 / MC-019）', () => {
  it('判据① 正向不漏：`menu.ts` 的每个图标名都已注册（漏注册 = 静默回落 BarChart3）', () => {
    // 面非空自检：解析失灵（0 条）时下面的断言会恒真 ⇒ 先自证
    expect(iconNamesFromSource(MENU_TS).length).toBeGreaterThanOrEqual(24)
    expect(allItems().length).toBe(28) // 7 组头 + 20 组内项 + 1 独立项

    const usedFromSource = Array.from(new Set(iconNamesFromSource(MENU_TS)))
    const usedFromObjects = Array.from(new Set(allItems().map((i) => i.icon)))
    expect(usedFromSource.sort()).toEqual(usedFromObjects.sort())
    expect(unregisteredIcons(usedFromSource, registeredIconNames())).toEqual([])
  })

  it('判据② 反向无死映射：`menuIconMap` 的键集合 == `menu.ts` 用到的图标名集合（双向相等）', () => {
    const used = Array.from(new Set(allItems().map((i) => i.icon))).sort()
    // 面非空自检 + 精确相等：既拦「漏注册」也拦「用不到的死映射」
    expect(registeredIconNames().length).toBeGreaterThanOrEqual(24)
    expect([...registeredIconNames()].sort()).toEqual(used)
    expect(registeredIconNames().filter((n) => !used.includes(n))).toEqual([])
  })

  it('`resolveMenuIcon` 取到的是**该名字自己的**组件（未注册才回落），且回落值是显式参数', () => {
    const Recycle = menuIconMap['Recycle']
    expect(resolveMenuIcon('Recycle')).toBe(Recycle)
    const fallback = menuIconMap['Bell']
    // 未注册名 ⇒ 用传入的 fallback（默认 LayoutDashboard，此处显式传以证明参数生效）
    expect(resolveMenuIcon('NotRegisteredIcon', fallback)).toBe(fallback)
    expect(resolveMenuIcon('NotRegisteredIcon')).toBe(menuIconMap['LayoutDashboard'])
  })

  it('判据③ 注入式红证：把 `icon: \'Recycle\'` 改成未注册值 ⇒ 判据① 的检查函数当场返回该名字', () => {
    const injected = MENU_TS.replace("icon: 'Recycle'", "icon: 'InjectedNotRegistered'")
    // 注入生效自证：源文本确实被改了（否则下面的红证是空跑）
    expect(injected).not.toBe(MENU_TS)
    expect(iconNamesFromSource(injected)).toContain('InjectedNotRegistered')

    // 未注入 ⇒ 检查器返回空（绿）
    expect(unregisteredIcons(iconNamesFromSource(MENU_TS), registeredIconNames())).toEqual([])
    // 注入后 ⇒ 同一检查器**只**报出被注入的那个名字（判别力落在被注入的那一项上）
    expect(unregisteredIcons(iconNamesFromSource(injected), registeredIconNames())).toEqual([
      'InjectedNotRegistered',
    ])
  })

  it('判据③ 反向红证：删掉一个注册项 ⇒ 判据① 报出「已注册面有、注册表无」的那个名字', () => {
    const registeredWithoutRecycle = registeredIconNames().filter((n) => n !== 'Recycle')
    expect(registeredWithoutRecycle).toHaveLength(registeredIconNames().length - 1)
    expect(unregisteredIcons(iconNamesFromSource(MENU_TS), registeredWithoutRecycle)).toEqual(['Recycle'])
  })
})