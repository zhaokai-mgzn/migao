// case_ids: PR-038
//
// PR-038（issue #5034，V111）：入库单菜单的**三处同构**守卫。
//
// 为什么要有这条：菜单在仓库里有**三份真相**，任一处漏改都会造成「岗位权限页勾得动、
// 侧边栏看不到」或反过来（#4203 点名的同族坑，前端 config/menu.ts 的注释里也逐字写了这条约束）：
//   ① frontend/admin-web/src/config/menu.ts            —— 真实侧边栏 + 岗位权限弹窗（渲染用）
//   ② backend/.../controller/MenuController.java       —— 权限多选树（MENU_TREE）
//   ③ backend/.../service/AuthService.java             —— 登录返回的侧边栏菜单（buildMenusByPermissions）
//
// 本文件是**静态文本守卫**：读三份源文件，断言「入库单」节点在每份里都存在，且
// path / 权限码一致（**图标是前端专属** —— 服务端不下发该字段，issue #5217 裁决，
// 故图标只在判据① 的前端侧钉）。它不启动 Spring，因此不可能被「后端没跑起来」掩盖 ——
// 而三处漂移正是那种「本地全绿、线上菜单少了」的形态。
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = join(process.cwd(), '..', '..')
const MENU_TS = readFileSync(join(process.cwd(), 'src/config/menu.ts'), 'utf-8')
const MENU_CONTROLLER = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java'),
  'utf-8',
)
const AUTH_SERVICE = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java'),
  'utf-8',
)

describe('入库单菜单三处同构（PR-038 / issue #5034）', () => {
  it('① 前端 config/menu.ts 有入库单节点：路径 /inbound-orders、权限码 inbound:view、图标 PackageOpen', () => {
    const line = MENU_TS.split('\n').find((l) => l.includes("path: '/inbound-orders'"))
    expect(line, 'config/menu.ts 缺 /inbound-orders 菜单项').toBeTruthy()
    expect(line).toContain("name: '入库单'")
    expect(line).toContain("permissionCode: 'inbound:view'")
    expect(line).toContain("icon: 'PackageOpen'")
  })

  it('② MenuController 的权限树有 inbound:view 节点（岗位权限页勾得动）', () => {
    expect(MENU_CONTROLLER).toContain('new MenuNode("inbound:view", "入库单")')
    // 必须真的挂进「生产管理」组（只声明不挂 = 页面上看不到）。
    // issue #4440：判据**只钉本用例真正关心的事**（入库单 i1 挂在该组内），**不**把整张节点表抄进来 ——
    // 抄整表会让任何**与本用例无关**的组内增删（如 #4416「工序库」+「工艺路线」合并为「工艺配置」）
    // 都把这条例红，报出的是**假回归**（本 PR 首轮 CI 实测：`List.of(pr1, pr2, pr3, pr4, i1)` 判红）。
    // 节点表的**逐一精确性**另有置信来源：Java `MenuControllerTest`（labels + codes 双列表精确断言）、
    // `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`（三份源逐值相等）。
    expect(MENU_CONTROLLER).toMatch(
      /new MenuNode\("production", "生产管理", List\.of\([^)]*\bi1\b[^)]*\)\)/,
    )
  })

  it('③ AuthService.buildMenusByPermissions 有入库单节点（真实侧边栏看得到），且与①同路径', () => {
    // 🔴 issue #5217 裁决：**图标是前端专属**（服务端不下发 icon）—— 故这里只钉 id/名称/路径。
    // 图标真值源 = 判据① 的 `MENU_TS` 行（`icon: 'PackageOpen'`）；服务端**不得**长回该字段
    // （实测无人消费、只会与前端漂移）。
    expect(AUTH_SERVICE).toContain('menuItem("inbound-orders", "入库单", "/inbound-orders")')
    expect(AUTH_SERVICE).not.toMatch(/menuItem\("[^"]+", "[^"]+", "[^"]+", "[^"]+"\)/)
  })

  it('权限码边界：入库单用 inbound:view（不挪用 processing:manage / product:list）', () => {
    // 侧边栏节点的权限判定必须是 inbound:view —— 挪用了别的码会让「有入库权限的人看不到菜单」。
    // 判据取「同一个 if 块」：节点前后 400 字符内必须出现 inbound:view 的权限判定
    // （窗口按 800 字符取，容得下本节点上方那段解释性注释）。
    const idx = AUTH_SERVICE.indexOf('menuItem("inbound-orders"')
    expect(idx).toBeGreaterThan(-1)
    const window = AUTH_SERVICE.slice(Math.max(0, idx - 800), idx + 200)
    expect(window).toContain('permissions.contains("inbound:view")')
    // 前端也不得把入库单挂到别的权限码下
    expect(MENU_TS).not.toMatch(/path: '\/inbound-orders'[^\n]*permissionCode: 'processing:manage'/)
  })
})
