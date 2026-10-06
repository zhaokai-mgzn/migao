// case_ids: UI-088
//
// 「库存明细」菜单的**三处同构**守卫（issue #6404）—— 与 `shipments-menu-isomorphic.test.ts`
// （UI-078）/ `remnants-menu-isomorphic.test.tsx`（PR-106）同一形态：菜单在仓库里有**三份真相**，
// 任一处漏改都会造成「岗位权限页勾得动、侧边栏看不到」或反过来（#4203 点名的同族坑）：
//   ① frontend/admin-web/src/config/menu.ts            —— 真实侧边栏 + 岗位权限弹窗（渲染用）
//   ② backend/.../controller/MenuController.java       —— 权限多选树（MENU_TREE）
//   ③ backend/.../service/AuthService.java             —— 登录返回的侧边栏菜单（buildMenusByPermissions）
//
// 本文件是**静态文本守卫**：不启动 Spring，因此不可能被「后端没跑起来」掩盖 ——
// 而三处漂移正是那种「本地全绿、线上菜单少了」的形态。全树逐值比对另见
// `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`；本文件钉的是
// **本节点自己的四件事**：三源同构 + 权限同码 + 图标注册 + 面包屑。
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
/** 页面自己的门禁（判据 ② 的真值源）：方法级 `@RequirePermission` —— 菜单必须与它**同码** */
const STOCK_LEDGER_CONTROLLER = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/controller/StockLedgerController.java'),
  'utf-8',
)
const MENU_ICONS = readFileSync(join(process.cwd(), 'src/config/menu-icons.ts'), 'utf-8')
const HEADER = readFileSync(join(process.cwd(), 'src/components/layout/Header.tsx'), 'utf-8')

const PATH = '/stock-ledger'
const NAME = '库存明细'
/**
 * ⚠️ 初版用的是 `ClipboardList` —— `menu-icons.test.ts` 的判据④（issue #5582「图标两两不同」）
 * **当场判红**：`ClipboardList` 已被「订单列表」占用（`ClipboardList → 订单列表、库存明细`）。
 * 该判据要求同屏相邻节点图标不得重复 ⇒ 换成 `ScrollText`（台账/卷册语义），
 * 并按它的出口「**三处同批**」登记：`config/menu.ts` 的 icon 名 + `config/menu-icons.ts` 注册
 * + `tests/setup.ts` 的 lucide 白名单（漏白名单会让任何渲染 Sidebar 的用例当场抛错）。
 */
const ICON = 'ScrollText'

describe('库存明细菜单三处同构（issue #6404 / UI-088）', () => {
  it('① 三份源都有该节点，名称/路径逐字一致（漏任一处 ⇒ 岗位权限页与真实侧边栏漂移）', () => {
    const line = MENU_TS.split('\n').find((l) => l.includes(`path: '${PATH}'`))
    expect(line, 'config/menu.ts 缺 /stock-ledger 菜单项').toBeTruthy()
    expect(line).toContain(`name: '${NAME}'`)
    expect(line).toContain(`icon: '${ICON}'`)

    expect(MENU_CONTROLLER).toContain(`new MenuNode("product:list", "${NAME}")`)
    // 必须真的挂进「仓储与物料」组（只声明不挂 = 岗位权限页上看不到）
    expect(MENU_CONTROLLER).toMatch(
      /new MenuNode\("inventory-center", "仓储与物料", List\.of\([^)]*\bprLedger\b[^)]*\)\)/,
    )
    // 负控：不得**同时**留在生产管理组
    expect(MENU_CONTROLLER).not.toMatch(
      /new MenuNode\("production-center", "生产管理", List\.of\([^)]*\bprLedger\b[^)]*\)\)/,
    )

    // ③ AuthService：id/名称/路径三处一起钉（图标是**前端专属**，服务端不下发 icon ⇒ 这里不钉）
    expect(AUTH_SERVICE).toContain(`menuItem("stock-ledger", "${NAME}", "${PATH}")`)
    // 且该节点必须落在**「仓储与物料」组的 children 装配区间内**
    const invStart = AUTH_SERVICE.indexOf('List<UserInfoResponse.MenuItem> inventoryChildren')
    const invEnd = AUTH_SERVICE.indexOf('menuGroup("inventory-center"')
    expect(invStart, 'AuthService 找不到 inventoryChildren 装配点（解析失配 ⇒ 红，不得静默通过）').toBeGreaterThan(-1)
    expect(invEnd).toBeGreaterThan(invStart)
    const inventoryBlock = AUTH_SERVICE.slice(invStart, invEnd)
    expect(inventoryBlock).toContain(`menuItem("stock-ledger", "${NAME}", "${PATH}")`)
    // 负控：它不得出现在生产管理组的装配区间里
    const prodStart = AUTH_SERVICE.indexOf('List<UserInfoResponse.MenuItem> productionChildren')
    const prodEnd = AUTH_SERVICE.indexOf('menuGroup("production-center"')
    expect(prodEnd).toBeGreaterThan(prodStart)
    expect(AUTH_SERVICE.slice(prodStart, prodEnd)).not.toContain('stock-ledger')
  })

  it('② 权限不放宽：菜单权限码 == StockLedgerController 的 @RequirePermission（同一个判据）', () => {
    const m = STOCK_LEDGER_CONTROLLER.match(/@RequirePermission\("([^"]+)"\)/)
    expect(m, 'StockLedgerController 找不到 @RequirePermission（解析失配 ⇒ 红，不得静默空跑）').toBeTruthy()
    const pageGate = m![1]
    // 门禁自己先自证：本端点复用商品域读码，**不新造**（新码今天无人持有 ⇒ 菜单对所有人不可见）
    expect(pageGate).toBe('product:list')
    expect(MENU_TS).toContain(`path: '${PATH}', permissionCode: '${pageGate}'`)
    // AuthService 侧同码：该 `add(...)` 必须落在**以该码为条件的那个 if 块**里
    //（取「它之前最近的一个权限判定」⇒ 与注释长度无关，不会因为上文多写几行注释而假红）
    const idx = AUTH_SERVICE.indexOf('menuItem("stock-ledger"')
    expect(idx).toBeGreaterThan(-1)
    const lastGate = AUTH_SERVICE.lastIndexOf('if (isAll || permissions.contains(', idx)
    expect(lastGate, '找不到该节点所属的权限门控（解析失配 ⇒ 红，不得静默通过）').toBeGreaterThan(-1)
    expect(AUTH_SERVICE.slice(lastGate, lastGate + 120)).toContain(
      `permissions.contains("${pageGate}")`,
    )
  })

  it('③ 图标已进菜单图标注册表（漏注册不报错，只会静默回落 BarChart3）', () => {
    expect(MENU_ICONS).toMatch(/^\s*ScrollText,$/m)
    const mapBlock = MENU_ICONS.slice(
      MENU_ICONS.indexOf('export const menuIconMap'),
      MENU_ICONS.indexOf('export function resolveMenuIcon'),
    )
    expect(mapBlock.length).toBeGreaterThan(0)
    expect(mapBlock).toMatch(/^\s*ScrollText,$/m)
    // 第三处：lucide 的**显式白名单**（`tests/setup.ts` 用白名单 mock 了 lucide-react）——
    // 漏登记会让任何渲染 Sidebar 的用例抛 `No "X" export is defined on the "lucide-react" mock`
    const SETUP = readFileSync(join(process.cwd(), 'tests/setup.ts'), 'utf-8')
    expect(SETUP).toMatch(/^\s*ScrollText: iconStub\(/m)
  })

  it('④ 面包屑：/stock-ledger ⇒「仓储与物料 / 库存明细」（末项 == 侧边栏菜单名，§15.2）', () => {
    const crumb = HEADER.split('\n').find((l) => l.includes(`startsWith('${PATH}')`))
    expect(crumb, 'Header.tsx 缺 /stock-ledger 面包屑条目').toBeTruthy()
    expect(crumb).toContain(`label: '${NAME}'`)
    expect(crumb).toContain("label: '仓储与物料'")
  })
})
