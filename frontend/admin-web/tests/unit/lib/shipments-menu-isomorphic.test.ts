// case_ids: UI-078
//
// 「发货单」菜单的**三处同构**守卫（issue #5939）—— 与 `inbound-menu-isomorphic.test.ts`（PR-038）
// 同一形态：菜单在仓库里有**三份真相**，任一处漏改都会造成「岗位权限页勾得动、侧边栏看不到」
// 或反过来（#4203 点名的同族坑）：
//   ① frontend/admin-web/src/config/menu.ts            —— 真实侧边栏 + 岗位权限弹窗（渲染用）
//   ② backend/.../controller/MenuController.java       —— 权限多选树（MENU_TREE）
//   ③ backend/.../service/AuthService.java             —— 登录返回的侧边栏菜单（buildMenusByPermissions）
//
// 本文件是**静态文本守卫**：不启动 Spring，因此不可能被「后端没跑起来」掩盖 ——
// 而三处漂移正是那种「本地全绿、线上菜单少了」的形态。全树逐值比对另见
// `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`；本文件钉的是
// **本节点自己的三件事**：组归属（仓储与物料，与「入库单」同组同序）、路径、权限码。
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { menuGroups } from '@/config/menu'

const ROOT = join(process.cwd(), '..', '..')
const GROUP_KEYS = new Set(menuGroups.map((g) => g.key))
const MENU_TS = readFileSync(join(process.cwd(), 'src/config/menu.ts'), 'utf-8')
const MENU_CONTROLLER = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java'),
  'utf-8',
)
const AUTH_SERVICE = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java'),
  'utf-8',
)

/**
 * 某个下标**之前**最近一次出现的**组** key（用于判定节点归属哪个组）。
 *
 * ⚠️ 不能只取「最近一次 `key:`」—— 菜单项本身也有 `key:`（如 `key: 'shipments'`），
 * 那会把节点自己的 key 当成组名（本单实测：`enclosingGroupKey` 曾返回 `'shipments'`）。
 * 故只用**真实组 key 集合**过滤（真值源 = `menu.ts` 的 `menuGroups`，不另抄一份组名表）。
 */
function enclosingGroupKey(src: string, index: number): string | null {
  const before = src.slice(0, index)
  const groups = Array.from(before.matchAll(/key: '([a-z-]+)'/g))
    .map((m) => m[1])
    .filter((k) => GROUP_KEYS.has(k))
  return groups.length > 0 ? groups[groups.length - 1] : null
}

describe('发货单菜单三处同构（UI-078 / issue #5939）', () => {
  it('① 前端 config/menu.ts：路径 /shipments、权限码 order:list、图标 Truck，且落在「仓储与物料」组、紧跟「入库单」', () => {
    const idx = MENU_TS.indexOf("path: '/shipments'")
    expect(idx, 'config/menu.ts 缺 /shipments 菜单项 —— 大菜单里就看不到发货单').toBeGreaterThan(-1)
    const line = MENU_TS.slice(MENU_TS.lastIndexOf('\n', idx) + 1, MENU_TS.indexOf('\n', idx))
    expect(line).toContain("name: '发货单'")
    // 🔴 权限码取**既有** order:list（不新造 shipment:view —— 新码没人持有 ⇒ 菜单对所有人不可见）
    expect(line).toContain("permissionCode: 'order:list'")
    expect(line).toContain("icon: 'Truck'")
    expect(enclosingGroupKey(MENU_TS, idx)).toBe('inventory-center')

    // 与「入库单」同序：入库单在前、发货单紧随其后（进 → 出 的动线）
    const inboundIdx = MENU_TS.indexOf("path: '/inbound-orders'")
    expect(inboundIdx).toBeGreaterThan(-1)
    const between = MENU_TS.slice(inboundIdx, idx)
    expect(between).not.toContain("path: '/production/remnants'")
  })

  it('② MenuController 的权限树有该节点，且挂在「仓储与物料」组内（岗位权限页勾得动）', () => {
    expect(MENU_CONTROLLER).toContain('new MenuNode("order:list", "发货单")')
    // 必须真的挂进「仓储与物料」组（只声明不挂 = 岗位权限页看不到）
    expect(MENU_CONTROLLER).toMatch(
      /new MenuNode\("inventory-center", "仓储与物料", List\.of\([^)]*\bi2\b[^)]*\)\)/,
    )
    // 负控：不得挂进「交易管理」组（订单列表在那边 ⇒ 挂错组 = 同一件事两个入口）
    expect(MENU_CONTROLLER).not.toMatch(
      /new MenuNode\("trade-center", "交易管理", List\.of\([^)]*\bi2\b[^)]*\)\)/,
    )
  })

  it('③ AuthService.buildMenusByPermissions 有该节点（真实侧边栏看得到），码与①同源', () => {
    expect(AUTH_SERVICE).toContain('menuItem("shipments", "发货单", "/shipments")')
    // 🔴 必须落在 `order:list` 的**自己的 if** 里：塞进别的码的判定会让持有 order:list 的人看不到菜单
    const idx = AUTH_SERVICE.indexOf('menuItem("shipments", "发货单", "/shipments")')
    const window = AUTH_SERVICE.slice(Math.max(0, idx - 400), idx)
    expect(window).toContain('permissions.contains("order:list")')
    // 且属于仓储与物料组的 children（不是 tradeChildren）
    const groupIdx = AUTH_SERVICE.indexOf('menuGroup("inventory-center", "仓储与物料", inventoryChildren)')
    expect(groupIdx, 'AuthService 必须把该节点并进「仓储与物料」组').toBeGreaterThan(-1)
    expect(AUTH_SERVICE.indexOf('inventoryChildren.add(menuItem("shipments"')).toBeGreaterThan(-1)
  })

  it('④ 三处路径/码逐字一致（漂移即红 —— 这是「勾得动但看不到」的唯一样态）', () => {
    // 前端与 AuthService 的路径逐字一致
    expect(MENU_TS).toContain("path: '/shipments'")
    expect(AUTH_SERVICE).toContain('"/shipments"')
    // 三处的码：前端节点码 / MenuController 节点码 / AuthService 判定码
    expect(MENU_TS).toContain("permissionCode: 'order:list'")
    expect(MENU_CONTROLLER).toContain('new MenuNode("order:list", "发货单")')
    expect(AUTH_SERVICE).toContain('permissions.contains("order:list")')
  })
})
