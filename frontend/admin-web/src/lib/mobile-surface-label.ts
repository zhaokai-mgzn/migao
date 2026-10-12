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
