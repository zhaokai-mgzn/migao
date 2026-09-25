// @vitest-environment jsdom
// case_ids: PR-080, PR-081, UI-058
//
// 「智能派单」命名与**跨源同构**（issue #5576）：菜单名在仓里有**三份真相**，任一处漏改就会出现
// 「侧边栏看到的名字」与「后端下发的名字」不一致（范式同 `remnants-menu-isomorphic.test.tsx`）。
//
// 命名裁定（用户 2026-09-25）：菜单名 = **智能派单**（原「池看板」——「池」是 pooling 的实现隐喻，
// 不是商家的活儿名）。中途考虑过「智能下料」，但本仓「下料」已被裁定为**车间裁剪工序**
// （`ProductionService` 记着「下料就是加工单的加工环节」= 工序库裁剪组；米宝触发词「这单下料做到哪了」）
// ⇒ 会与「看裁剪进度」撞名，故不用。
//
// 🔴 本判据同时钉住**没改什么**：路由 `/production/pool`、菜单 key `production-pool`、
//    权限码 `processing:manage`、接口路径与 `poolingEnabled`/`pooled` 字段 —— 只改文案，
//    不做路由/契约迁移（先例 = UI-028「角色权限」→「岗位权限」时 URL 与接口不变）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, waitFor } from '@testing-library/react'

const mockGetBoard = vi.fn()
vi.mock('@/lib/api', () => ({
  poolBoardApi: {
    getBoard: (...a: unknown[]) => mockGetBoard(...a),
    preview: vi.fn(),
    dispatch: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn(), dismiss: vi.fn() } }))

import ProductionPoolPage from '@/app/(dashboard)/production/pool/page'

const ROOT = join(process.cwd(), '..', '..')
const MENU_TS = readFileSync(join(process.cwd(), 'src/config/menu.ts'), 'utf-8')
const HEADER = readFileSync(join(process.cwd(), 'src/components/layout/Header.tsx'), 'utf-8')
const API_TS = readFileSync(join(process.cwd(), 'src/lib/api.ts'), 'utf-8')
const MENU_CONTROLLER = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java'), 'utf-8')
const AUTH_SERVICE = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java'), 'utf-8')

const NAME = '智能派单'

beforeEach(() => {
  vi.clearAllMocks()
  mockGetBoard.mockResolvedValue({
    data: { data: { poolingEnabled: false, maxWaitHours: 24, orderCount: 0, lineCount: 0, urgentCount: 0, overdueCount: 0, warnings: [], urgentLines: [], groups: [] } },
  })
})

describe('智能派单：命名与去内部隐喻（issue #5576）', () => {
  it('🔴 页面渲染文本：H1 = 智能派单，且不再出现「池」隐喻（池看板/池化/进池/池内/成批区/加急插队）', async () => {
    const { container } = render(<ProductionPoolPage />)
    await waitFor(() => expect(mockGetBoard).toHaveBeenCalled())
    await waitFor(() => expect(container.textContent ?? '').toContain(NAME))
    const text = container.textContent ?? ''

    expect(text).toContain(NAME)
    // 「池」是 pooling 的实现隐喻 —— 页面上一个都不要有
    expect(text).not.toMatch(/池/)
    for (const oldWord of ['成批区', '加急插队', '一键成批派单', '池化开关']) {
      expect(text, `旧文案「${oldWord}」仍在页面上`).not.toContain(oldWord)
    }
    // 替换后的**人话**读数（不是"删了就算"）：状态条与两个区块都还在、且用商家的话
    for (const plain of ['合并派单开关', '待派订单', '加急订单（不参与合并，立即派）', '可合并的待派订单（按料分组）', '一键合并派单']) {
      expect(text, `缺人话读数「${plain}」`).toContain(plain)
    }
  })

  it('菜单三源同构：config/menu.ts + MenuController + AuthService 三处都叫「智能派单」', () => {
    const menuLine = MENU_TS.split('\n').find((l) => l.includes("key: 'production-pool'"))
    expect(menuLine, 'config/menu.ts 缺 production-pool 菜单项').toBeTruthy()
    expect(menuLine).toContain(`name: '${NAME}'`)
    expect(MENU_CONTROLLER).toContain(`new MenuNode("processing:manage", "${NAME}")`)
    expect(AUTH_SERVICE).toContain(`menuItem("production-pool", "${NAME}", "/production/pool")`)
    // 面包屑同批（页面上的名字与侧边栏一致）
    expect(HEADER).toContain(`{ label: '${NAME}' }`)
  })

  it('🔴 只改文案：路由 / 菜单 key / 权限码 / 接口路径与字段名一律未动（负控）', () => {
    const menuLine = MENU_TS.split('\n').find((l) => l.includes("key: 'production-pool'")) ?? ''
    expect(menuLine).toContain("path: '/production/pool'")
    expect(menuLine).toContain("permissionCode: 'processing:manage'")
    expect(MENU_CONTROLLER).toContain('new MenuNode("processing:manage", "智能派单")')
    // 接口契约（前端调用面）逐字未动
    expect(API_TS).toContain("request.get<ApiResponse<PoolBoard>>('/api/admin/production/pool'")
    expect(API_TS).toContain("'/api/admin/production/pool/preview'")
    expect(API_TS).toContain("'/api/admin/production/pool/dispatch'")
  })
})