import { redirect } from 'next/navigation'

/**
 * 旧「加工费管理」入口 → /production/processing?tab=fees（issue #4490）。
 *
 * 「加工费管理」(/production/processing-fees) 与「加工项管理」(/processing) 已**合并为单一入口**
 * `/production/processing`（菜单名「加工项管理」，issue #4542 用户裁定）；本页只做重定向
 * （旧书签/外部深链不 404）。
 *
 * ⚠️ 带上 `?tab=fees` **直达第二个 tab「加工费组合」**：本路径的既有引用方要的正是**定价面** ——
 * 后端未定价提示（`ProcessingFeeCalculator`：「请去「加工费管理」(%s) 为该组合定价」）注入的
 * 就是这个路径，落到默认的「加工项」tab 会让人以为链接失效。
 *
 * 加工费组合原有能力（组合列表 / 新建组合 / 改单价 / 停用二次确认 / 护栏理由逐条 /
 * 未定价缺口）已全部并入 `/production/processing` 的第二个 tab。
 */
export default function ProcessingFeesRedirectPage() {
  redirect('/production/processing?tab=fees')
}
