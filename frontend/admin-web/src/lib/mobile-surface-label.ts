/**
 * 「手机端可见面」标注的**唯一渲染实现**（issue #6759）。
 *
 * ## 它是什么
 *
 * 商家端 H5 / 小程序菜单是**服务端按权限码投影**的（`backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java`，
 * issue #6570 / #6574 用户 2026-10-08 裁定「走 B」）⇒ 「勾这个码 = 员工手机上多一个入口」
 * 这件事**只有服务端知道**。`GET /api/admin/menus` 的节点因此带上 `mobileTitles`
 * （服务端**派生**，见 `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java`
 * 的 `annotateMobileTitles`）。
 *
 * ## 纪律（别在这里长第二份真值）
 *
 * 🔴 本文件**不**包含任何「权限码 → 手机端面」的映射/常量：它只把**服务端给的**
 * `mobileTitles` 追加成一行标注。谁在这里抄一张表，谁就造了第二份会漂的真值
 * （判据 = `tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py`）。
 *
 * 🔴 标注里**不出现权限码字面量**（信息不重复 + 不摆内部标识）：形态固定为
 * ` · 手机端：X`（多个面时用 `、` 连接）；**没有手机端面时不追加任何字符**
 * （纯 PC 权限不产生噪音）。
 */

export const MOBILE_TITLE_PREFIX = '手机端：'
export const MOBILE_TITLE_SEPARATOR = ' · '
const MOBILE_TITLE_JOINER = '、'

/** `GET /api/admin/menus` 的节点里、收集手机端标注所需的最小形状（调用方可直接喂页面状态）。 */
export interface MenuNodeWithMobileTitles {
  code?: string
  /** 菜单名（收表时不用，只为让调用方能把整棵 `TreeNode` 直接喂进来）。 */
  label?: string
  mobileTitles?: readonly string[] | null
  children?: readonly MenuNodeWithMobileTitles[] | null
}

/**
 * 从**整棵**权限树收集 `权限码 → 手机端面中文名`（服务端在节点上标注，前端只收表）。
 *
 * 🔴 为什么必须扫**整棵树**（含顶层独立项）：`dashboard:view`（经营看板）自 issue #7087 起是
 * **顶层一级项**，只扫 `children` 会让手机端「数据」从岗位/员工的手机端清单里**静默消失**
 * （2026-10-18 用户截图：权限列回退成 `dashboard:view` 英文码，同一个树扫描口径）。
 *
 * 同码多节点（#5699/#5291 的有意设计面）取**树序首个带标注**的节点 —— 与服务端
 * `MenuController.annotateMobileTitles` 的「标注只落首承载节点」同一条规则。
 */
export function mobileTitlesByCodeFromTree(
  nodes?: readonly MenuNodeWithMobileTitles[] | null,
): Record<string, string[]> {
  const map: Record<string, string[]> = {}
  const visit = (list?: readonly MenuNodeWithMobileTitles[] | null) => {
    for (const node of list ?? []) {
      const code = node?.code
      const titles = (node?.mobileTitles ?? []).map(t => t.trim()).filter(Boolean)
      if (code && titles.length > 0 && !(code in map)) map[code] = titles
      visit(node?.children)
    }
  }
  visit(nodes)
  return map
}

/**
 * 该节点的手机端标注（**空串** = 没有手机端入口 ⇒ 调用方不追加任何内容）。
 *
 * @param mobileTitles 服务端下发的手机端面中文名（缺省 / 空数组 ⇒ 空串）
 */
export function formatMobileTitles(mobileTitles?: readonly string[] | null): string {
  const titles = (mobileTitles ?? []).map(t => t.trim()).filter(Boolean)
  if (titles.length === 0) return ''
  return `${MOBILE_TITLE_SEPARATOR}${MOBILE_TITLE_PREFIX}${titles.join(MOBILE_TITLE_JOINER)}`
}
