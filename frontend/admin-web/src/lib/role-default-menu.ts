/**
 * 「默认岗位默认菜单」的派生实现（issue #7146）—— **后台与手机端是一份菜单的两次投影**。
 *
 * ## 为什么有本模块（用户的裁定）
 *
 * 用户 2026-10-17 逐字：「手机端可见面要不要作为『默认岗位默认菜单』的一部分，当然需要，
 * **把 PC 和手机端当一个整体**」。
 *
 * 改前：岗位卡片上的「默认可用模块」是 `roles.description` 里的**散文清单**（`#7111`），
 * 只抄后台侧边栏菜单 —— 手机端（`MobileSurfaces`，服务端按**同一批权限码**现算）一个字都没有；
 * 而且散文会漂（`#7087` 撤掉「每日简报」菜单后 7/8 条描述仍点名它，见 #7139）。
 * 改后：描述只留「职责」（散文），**默认菜单一律派生** —— 一份真值（权限码）投影出两面。
 *
 * ## 真值只有一份（别在这里长第二张表）
 *
 * - 输入 ① = 该岗位的默认权限码（`GET /api/admin/roles` 的 `permissions[].code`）；
 * - 输入 ② = 服务端下发的 `码 → 手机端面中文名`
 *   （`GET /api/admin/menus` 的 `mobileTitles`，派生自
 *   `backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java`）；
 * - 后台名字取自 `@/config/menu`（与 `MenuController` / `AuthService` 三源同构的前端真值源）。
 *
 * 🔴 **本模块不含任何「权限码 → 菜单名 / 手机端面名」的字面表**：谁在这里抄一张表，
 * 谁就造了第二份会漂的真值（判据 = `tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py`）。
 *
 * ## 覆盖边界（照实登记）
 *
 * - 只覆盖**菜单态**（这个岗位在两端各能看到什么）；**不改授权**：手机端写动作仍由商家在权限树逐人勾
 *   （用户 2026-10-17 裁定「不动授权（零 delta）」）。
 * - 手机端底栏里**无码**的两项（登录即可见）不属任何岗位的差异 ⇒ 不进本表；有码的底栏项
 *   （数据 / 坐席）会以面名形式出现（与 `MobileSurfaces` 的投影口径一致）。
 */
import type { MenuItem } from '@/config/menu'
import { menuGroups, standaloneHeadItems, standaloneItems, standaloneTopItems } from '@/config/menu'

/** 「默认菜单」= 后台菜单项名 + 手机端可见面名（顺序 = 菜单树序）。 */
export interface RoleDefaultMenu {
  backend: string[]
  mobile: string[]
}

/** 四个梯队里**带权限码**的菜单项（尾部「通知中心」无码 ⇒ 不属任何岗位的默认菜单差异）。 */
function codedMenuItems(): MenuItem[] {
  return [
    ...standaloneHeadItems,
    ...menuGroups.flatMap(group => group.children),
    ...standaloneTopItems,
    ...standaloneItems,
  ].filter(item => Boolean(item.permissionCode))
}

/**
 * 由「岗位默认权限码 × 服务端 `mobileTitles`」派生默认菜单（纯函数；注入式红证就是喂改过的输入）。
 *
 * @param codes              该岗位的权限码（`*` = 管理员通配 ⇒ 全给）
 * @param mobileTitlesByCode 服务端下发的 `码 → 手机端面中文名`（缺省 = 无手机端信息 ⇒ `mobile` 为空）
 */
export function deriveRoleDefaultMenu(
  codes: readonly string[],
  mobileTitlesByCode: Readonly<Record<string, readonly string[]>> = {},
): RoleDefaultMenu {
  const wildcard = codes.includes('*')
  const granted = new Set(codes)
  const backend: string[] = []
  const mobile: string[] = []
  const seenTitles = new Set<string>()
  for (const item of codedMenuItems()) {
    const code = item.permissionCode as string
    if (!wildcard && !granted.has(code)) continue
    backend.push(item.name)
    // 同一个面由多个码/多个节点承载时只出现一次（`production:view` 在树上有三处承载）
    for (const raw of mobileTitlesByCode[code] ?? []) {
      const title = raw.trim()
      if (title && !seenTitles.has(title)) {
        seenTitles.add(title)
        mobile.push(title)
      }
    }
  }
  return { backend, mobile }
}

/**
 * 卡片上的**一行摘要**（§31 P1 常驻面克制 / P2 信息不重复）：默认收起，展开才看清单。
 * 数字全部由派生结果算出（不写死）。
 */
export function roleDefaultMenuSummary(menu: RoleDefaultMenu): string {
  return `默认菜单：后台 ${menu.backend.length} 项 · 手机端 ${menu.mobile.length} 个入口`
}
