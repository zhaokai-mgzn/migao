import { redirect } from 'next/navigation'

/**
 * 旧「加工项管理」入口 → 加工项与加工费（issue #4490）。
 *
 * 「加工项管理」(/processing，商品管理组) 与「加工费管理」(/production/processing-fees，生产管理组)
 * **合并为单一菜单入口** `/production/processing`（菜单名「加工项与加工费」，归**生产管理**组）：
 * 两者是同一权限码（`processing:manage`）、同一业务域（加工项及其定价）——
 * 加工费组合的 `items[]` 必须取自加工项目录的活跃加工项，拆在两个菜单组里意味着
 * 「建组合发现缺加工项要跳到另一个菜单组去建」。
 *
 * ⇒ 本页不再渲染任何内容，直接重定向到唯一入口（旧书签/外部深链不 404），
 * 照 #4357 的 `/processing-orders` → `/production`、#4416 的 `/production/operations` →
 * `/production/routings` 先例。
 *
 * 加工项原有能力（列表 / 新增 / 编辑 / 删除二次确认 / 加工分类 / 计价方式 / 优惠设置）
 * 已全部并入 `/production/processing` 的**第一个 tab「加工项」**，
 * 见 `production/processing/page.tsx`。
 */
export default function ProcessingRedirectPage() {
  redirect('/production/processing')
}
