// case_ids: UI-117
/**
 * 「默认岗位默认菜单」的派生实现（issue #7146）。
 *
 * ## 这条判据要治什么
 *
 * 用户 2026-10-17 逐字：「手机端可见面要不要作为『默认岗位默认菜单』的一部分，当然需要，
 * **把 PC 和手机端当一个整体**」。改前：岗位卡片上的「默认可用模块」是**散文清单**，
 * 只抄后台侧边栏菜单（`#7111`），手机端一个字都没有；而手机端菜单是**另一份投影**
 * （`MobileSurfaces`，服务端按同一批权限码现算）⇒ 商家在岗位页看不到「这个岗位在手机上能看到什么」。
 *
 * ## 本模块的形状（为什么是纯函数 + 单一真值）
 *
 * 输入 = ① 该岗位的默认权限码（来自 `GET /api/admin/roles` 的 `permissions[].code`）
 *      ② 服务端下发的 `码 → 手机端面中文名`（`GET /api/admin/menus` 的 `mobileTitles`，
 *         真值 = `backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java`）
 * 输出 = `{ backend: 菜单项名[], mobile: 面名[] }`。
 *
 * 🔴 本模块**不含**任何「权限码 → 菜单名 / 手机端面名」的字面表：
 *   · 后台名取自 `@/config/menu`（三源同构的前端真值源）；
 *   · 手机端名只透传服务端给的 `mobileTitles`。
 * 谁在这里抄一张表，谁就造了第二份会漂的真值
 * （判据 = `tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py` 判据 3）。
 *
 * ## 覆盖边界（照实登记）
 *
 * - 只覆盖**菜单态**（哪些入口可见）；不覆盖手机端写动作（写码另由商家在权限树逐人勾）。
 * - 底栏（`TABS`）里「问黄金策 / 我的」无码 ⇒ 不属任何岗位的「默认菜单」差异，调用方不列；
 *   有码的底栏项（数据 / 坐席）会以面名的形式出现在 `mobile` 里（同 `MobileSurfaces` 投影）。
 */
import { describe, it, expect } from 'vitest'
import { deriveRoleDefaultMenu, roleDefaultMenuSummary } from '@/lib/role-default-menu'
import { menuGroups, standaloneHeadItems, standaloneTopItems, standaloneItems } from '@/config/menu'

/** 服务端 `mobileTitles` 的真语料形状（真值 = `MobileSurfaces`；夹具只用于证明「透传、不自造」）。 */
const MOBILE_TITLES: Record<string, string[]> = {
  'dashboard:view': ['数据'],
  'agent:session': ['坐席'],
  'after_sales:view': ['售后处理'],
  'processing:view': ['智能派单'],
  'inbound:view': ['入库过账'],
  'production:view': ['计件工资报表', '生产待办'],
}

describe('deriveRoleDefaultMenu（后台 + 手机端 = 一份默认菜单）', () => {
  it('同一批权限码同时投影出后台菜单项与手机端入口', () => {
    const menu = deriveRoleDefaultMenu(
      ['dashboard:view', 'agent:session', 'knowledge:view', 'customer:view', 'processing:view', 'inbound:view', 'after_sales:view'],
      MOBILE_TITLES,
    )
    // 后台：与侧边栏菜单名逐字一致（真值 = @/config/menu）
    expect(menu.backend).toEqual(
      expect.arrayContaining(['经营看板', '在线接待', '知识库', '客户列表', '智能派单', '入库单', '售后工单']),
    )
    // 手机端：服务端给什么就是什么（本模块不自造名字）
    expect(menu.mobile).toEqual(['数据', '坐席', '售后处理', '智能派单', '入库过账'])
  })

  it('手机端面名逐字取自服务端下发（夹具改名 ⇒ 输出跟着改，证明不是本地表）', () => {
    const menu = deriveRoleDefaultMenu(['processing:view'], { 'processing:view': ['派单（服务端改名）'] })
    expect(menu.mobile).toEqual(['派单（服务端改名）'])
  })

  it('没有手机端可见面的岗位 ⇒ mobile 为空（不是「全给」）', () => {
    const menu = deriveRoleDefaultMenu(['knowledge:view', 'product:list'], MOBILE_TITLES)
    expect(menu.mobile).toEqual([])
    expect(menu.backend).toEqual(expect.arrayContaining(['知识库', '商品管理']))
  })

  it('通配 `*`（管理员）⇒ 后台全部菜单项 + 全部手机端面（同一份通配语义）', () => {
    const menu = deriveRoleDefaultMenu(['*'], MOBILE_TITLES)
    const allCoded = [
      ...standaloneHeadItems,
      ...menuGroups.flatMap(g => g.children),
      ...standaloneTopItems,
      ...standaloneItems,
    ].filter(i => i.permissionCode)
    expect(menu.backend.length).toBe(allCoded.length)
    expect(menu.backend).toEqual(expect.arrayContaining(['经营看板', '商品管理', '企业基础设置']))
    expect(menu.mobile).toEqual(expect.arrayContaining(['数据', '坐席', '售后处理', '智能派单', '入库过账']))
  })

  it('同一个面由多个权限码承载时只出现一次（不按节点重复）', () => {
    // `production:view` 在树上由「作业看板 / 计件工资 / 企业基础设置」三处承载 —— 面名不得重复
    const menu = deriveRoleDefaultMenu(['production:view', 'processing:view'], MOBILE_TITLES)
    expect(menu.mobile.filter(t => t === '计件工资报表')).toHaveLength(1)
    expect(menu.mobile.filter(t => t === '生产待办')).toHaveLength(1)
  })

  it('无码 / 空码集 ⇒ 后台与手机端都为空（fail-closed，不猜）', () => {
    expect(deriveRoleDefaultMenu([], MOBILE_TITLES)).toEqual({ backend: [], mobile: [] })
  })

  it('摘要行把两面放进同一句（§31 P2：同卡不重复摆两套清单）', () => {
    const menu = deriveRoleDefaultMenu(['dashboard:view', 'processing:view'], MOBILE_TITLES)
    expect(roleDefaultMenuSummary(menu)).toBe('默认菜单：后台 2 项 · 手机端 2 个入口')
  })
})
