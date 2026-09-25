// case_ids: PR-106
/**
 * 余料台账进侧边栏 —— **三处同构 + 权限同码 + 图标注册 + 真的点得到**（issue #5191）。
 *
 * ## 病根（issue #5191：同批新页入口口径不一致）
 *
 * `/production/remnants`（余料台账，V122 / issue #5146）**存在且可达**，但只能从
 * 「企业参数中心 → 余料回收」域的 `rows[].href` 下钻进入；而**同期新增**的
 * `/production/pool`（智能派单 #5177）/ `/production/saving-board`（省料看板 #5159）都进了侧边栏
 * ⇒ 口径不一致。用户裁定**补菜单**（不登记成「有意不进侧边栏」）。
 *
 * ## 为什么必须有这条守卫
 *
 * 菜单在仓库里有**三份真相**，任一处漏改都会造成「岗位权限页勾得动、侧边栏看不到」或反过来
 *（#4203 点名的同族坑）：
 *   ① `frontend/admin-web/src/config/menu.ts`  —— **真实侧边栏**（`Sidebar.tsx` 只读它）+ 岗位权限弹窗
 *   ② `backend/.../controller/MenuController.java` 的 `MENU_TREE` —— `GET /api/admin/menus`（岗位权限页消费）
 *   ③ `backend/.../service/AuthService.java` 的 `buildMenusByPermissions` —— 登录后下发的菜单
 * 三处各自的测试都只看自己 ⇒ **谁都不会因为别人漏改而变红**（本守卫是那个「别人」）。
 *
 * ## 判据（四条，各自能单独变红）
 *
 * ① **三处同构**：三份源里都有 `production-remnants` 节点，且 path / 名称逐字一致；
 * ② **权限不放宽**：菜单项的权限码 == `RemnantController` 类级 `@RequirePermission` 的码
 *    （同码 = 菜单可见性与页面门禁**同一个判据**；换成别的码就会造出「看得到点不进」或「有权限却看不到」）；
 * ③ **图标注册**：`frontend/admin-web/src/config/menu-icons.ts` 的 `menuIconMap` 里有该图标
 *    （#5271 前内联在 `Sidebar.tsx`；漏注册**不会报错**，只会静默回落 BarChart3）；
 * ④ **真的点得到**：渲染真实 `<Sidebar />` ⇒ 该权限下展开「仓储与物料」组能看到「余料台账」
 *    且 `href = /production/remnants`；**负控**：没有 `processing:manage` 时**不得**出现
 *    （证明开启菜单没有顺手放宽门禁）。
 */
import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen, cleanup, within, fireEvent } from '@testing-library/react'
import React from 'react'

const ROOT = join(process.cwd(), '..', '..')
const MENU_TS = readFileSync(join(process.cwd(), 'src/config/menu.ts'), 'utf-8')
const SIDEBAR = readFileSync(join(process.cwd(), 'src/components/layout/Sidebar.tsx'), 'utf-8')
/** issue #5271：图标注册表（原内联在 `Sidebar.tsx` 的 `iconMap`） */
const MENU_ICONS = readFileSync(join(process.cwd(), 'src/config/menu-icons.ts'), 'utf-8')
const HEADER = readFileSync(join(process.cwd(), 'src/components/layout/Header.tsx'), 'utf-8')
const MENU_CONTROLLER = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java'),
  'utf-8',
)
const AUTH_SERVICE = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java'),
  'utf-8',
)
/** 页面自己的门禁（判据 ② 的真值源）：类级 @RequirePermission —— 菜单必须与它**同码** */
const REMNANT_CONTROLLER = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/controller/RemnantController.java'),
  'utf-8',
)

const PATH = '/production/remnants'
const NAME = '余料台账'

// ── Sidebar 渲染所需替身（与 menu-breadcrumb-coverage.test.tsx 同族）──
let mockPermissions: string[] = []
vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({ user: { name: '测试用户', permissions: mockPermissions } }),
}))
vi.mock('next/navigation', () => ({ usePathname: () => '/production' }))
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))
vi.mock('@/lib/api', () => ({
  briefingApi: { getConfig: () => Promise.resolve({ data: { data: { enabled: false } } }) },
}))

import Sidebar from '@/components/layout/Sidebar'

describe('余料台账菜单三处同构（PR-106 / issue #5191）', () => {
  it('① 三份源都有该节点，名称/路径逐字一致（漏任一处 ⇒ 岗位权限页与真实侧边栏漂移）', () => {
    const line = MENU_TS.split('\n').find((l) => l.includes(`path: '${PATH}'`))
    expect(line, 'config/menu.ts 缺 /production/remnants 菜单项').toBeTruthy()
    expect(line).toContain(`name: '${NAME}'`)
    expect(line).toContain("icon: 'Recycle'")
    // ② 的静态半边：前端权限码与页面门禁同码
    expect(line).toContain("permissionCode: 'processing:manage'")

    expect(MENU_CONTROLLER).toContain(`new MenuNode("processing:manage", "${NAME}")`)
    // 必须真的挂进「仓储与物料」组（只声明不挂 = 岗位权限页上看不到）
    // issue #5271：本项随「面料进出与消耗」动线**从生产管理组移入新组**（`inventory-center`）
    expect(MENU_CONTROLLER).toMatch(
      /new MenuNode\("inventory-center", "仓储与物料", List\.of\([^)]*\bprRemnants\b[^)]*\)\)/,
    )
    // 负控：不得**同时**留在生产管理组
    expect(MENU_CONTROLLER).not.toMatch(
      /new MenuNode\("production-center", "生产管理", List\.of\([^)]*\bprRemnants\b[^)]*\)\)/,
    )
    // ② AuthService：id/名称/路径三处一起钉。
    // 🔴 issue #5217 裁决：**图标是前端专属** —— 服务端不下发 icon，故这里**不钉服务端图标**
    // （服务端图标字段实测无人消费、只会与前端漂移：`production-piecework` 前端 Calculator /
    // 服务端 Coins）。图标真值源 = 上面 `MENU_TS` 的 `icon: 'Recycle'`，服务端**不得**长回该字段。
    expect(AUTH_SERVICE).toContain(`menuItem("production-remnants", "${NAME}", "${PATH}")`)
    expect(AUTH_SERVICE).not.toMatch(/menuItem\("[^"]+", "[^"]+", "[^"]+", "[^"]+"\)/)
    // 且该节点必须落在**「仓储与物料」组的 children 装配区间内**（取该组 children 起点到
    // `menus.add(menuGroup("inventory-center"…))` 之间）—— 只声明不挂 = 侧边栏看不到。
    const invStart = AUTH_SERVICE.indexOf('List<UserInfoResponse.MenuItem> inventoryChildren')
    const invEnd = AUTH_SERVICE.indexOf('menuGroup("inventory-center"')
    expect(invStart, 'AuthService 找不到 inventoryChildren 装配点（解析失配 ⇒ 红，不得静默通过）').toBeGreaterThan(-1)
    expect(invEnd).toBeGreaterThan(invStart)
    const inventoryBlock = AUTH_SERVICE.slice(invStart, invEnd)
    expect(inventoryBlock).toContain(`menuItem("production-remnants", "${NAME}", "${PATH}")`)
    expect(inventoryBlock).toContain('permissions.contains("processing:manage")')
    // 负控：它不得出现在生产管理组的装配区间里
    const prodStart = AUTH_SERVICE.indexOf('List<UserInfoResponse.MenuItem> productionChildren')
    const prodEnd = AUTH_SERVICE.indexOf('menuGroup("production-center"')
    expect(prodEnd).toBeGreaterThan(prodStart)
    expect(AUTH_SERVICE.slice(prodStart, prodEnd)).not.toContain('production-remnants')
  })

  it('② 权限不放宽：菜单权限码 == RemnantController 的类级 @RequirePermission（同一个判据）', () => {
    const m = REMNANT_CONTROLLER.match(/@RequirePermission\("([^"]+)"\)/)
    expect(m, 'RemnantController 找不到类级 @RequirePermission（解析失配 ⇒ 红，不得静默空跑）').toBeTruthy()
    const pageGate = m![1]
    // 页面门禁自己先自证非空
    expect(pageGate).toBe('processing:manage')
    expect(MENU_TS).toContain(`path: '${PATH}', permissionCode: '${pageGate}'`)
    // AuthService 侧同码：该 `add(...)` 必须落在**以 processing:manage 为条件的那个 if 块**里
    //（取「它之前最近的一个权限判定」⇒ 与注释长度无关，不会因为上文多写几行注释而假红）
    const idx = AUTH_SERVICE.indexOf('menuItem("production-remnants"')
    expect(idx).toBeGreaterThan(-1)
    const lastGate = AUTH_SERVICE.lastIndexOf('if (isAll || permissions.contains(', idx)
    expect(lastGate, '找不到该节点所属的权限门控（解析失配 ⇒ 红，不得静默通过）').toBeGreaterThan(-1)
    expect(AUTH_SERVICE.slice(lastGate, lastGate + 120)).toContain(
      `permissions.contains("${pageGate}")`,
    )
  })

  it('③ 图标已进菜单图标注册表（漏注册不报错，只会静默回落 BarChart3）', () => {
    // issue #5271：图标注册从 `Sidebar.tsx` 的**内联 `iconMap`** 抽成独立模块
    // `frontend/admin-web/src/config/menu-icons.ts`（单源 + 可判定）⇒ 本判据**跟着对象走**
    // （保留、不删）：断言 `Recycle` 既被 import 又被登记进 `menuIconMap`。
    expect(MENU_ICONS).toMatch(/^\s*Recycle,$/m)
    const mapBlock = MENU_ICONS.slice(
      MENU_ICONS.indexOf('export const menuIconMap'),
      MENU_ICONS.indexOf('export function resolveMenuIcon'),
    )
    expect(mapBlock.length).toBeGreaterThan(0)
    expect(mapBlock).toMatch(/^\s*Recycle,$/m)
    // 负控（防「双源」）：`Sidebar.tsx` 不得再内联该注册行（它只应从注册表取图标）
    expect(SIDEBAR).not.toMatch(/^\s*Recycle,$/m)
    // 面包屑末项必须与菜单名逐字一致（§15.2；PG-038 对**所有**菜单项做通用判据，这里点名本项）
    const crumb = HEADER.split('\n').find((l) => l.includes(`startsWith('${PATH}')`))
    expect(crumb, 'Header.tsx 缺 /production/remnants 面包屑条目').toContain(`label: '${NAME}'`)
    // issue #5271：本项随动线搬进「仓储与物料」组 ⇒ 面包屑组名也跟着改（§15.2 组名与菜单一致）
    expect(crumb).toContain("label: '仓储与物料'")
  })

  it('④ 真的点得到：有 processing:manage 时**展开「仓储与物料」**后出现「余料台账」→ /production/remnants', async () => {
    mockPermissions = ['processing:manage']
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    // issue #5271：分组默认只展开**当前路由所在组**，而本文件 mock 的 pathname 是 `/production`
    //（属「生产管理」组）⇒ 「仓储与物料」默认收起。按新交互**先展开该组**再断言（强度不变）。
    fireEvent.click(screen.getByTestId('sidebar-group-toggle-inventory-center'))
    expect(screen.getByTestId('sidebar-group-toggle-inventory-center').getAttribute('aria-expanded')).toBe('true')
    const link = await screen.findByRole('link', { name: NAME })
    expect(link.getAttribute('href')).toBe(PATH)
    cleanup()
  })

  it('④ 负控：没有 processing:manage ⇒ 该入口**不出现**（开菜单不得顺手放宽门禁）', async () => {
    mockPermissions = ['order:list']
    const { container } = render(<Sidebar collapsed={false} onToggle={() => {}} />)
    // 自证渲染面非空：先展开「交易管理」（order:list 下唯一可见的分组），菜单渲染失败时
    // queryByRole 恒 null = 空断言
    fireEvent.click(screen.getByTestId('sidebar-group-toggle-trade-center'))
    expect(within(container).getByRole('link', { name: '订单列表' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: NAME })).toBeNull()
    // 更强的负控：整组都不在（组内 3 项全被过滤 ⇒ 空组剔除）—— 不是「渲染了但看不见」
    expect(screen.queryByText('仓储与物料')).toBeNull()
    expect(screen.queryByTestId('sidebar-group-toggle-inventory-center')).toBeNull()
    cleanup()
  })

  it('④ 负控（同组混权）：有 inbound:view、无 processing:manage ⇒ 组在、入库单在，余料台账**不在**', async () => {
    // 「入库单」与「余料台账」同组但权限码不同（inbound:view vs processing:manage）——
    // 这条证明**同组不等于同权**：开菜单没有顺手把 processing:manage 的项带出来。
    mockPermissions = ['inbound:view']
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    fireEvent.click(screen.getByTestId('sidebar-group-toggle-inventory-center'))
    expect(await screen.findByRole('link', { name: '入库单' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: NAME })).toBeNull()
    expect(within(screen.getByText('仓储与物料').closest('[data-group-key]') as HTMLElement)
      .queryAllByRole('link')).toHaveLength(1)
    cleanup()
  })
})
