import { redirect } from 'next/navigation'

/**
 * 旧「工序库」入口 → 工艺配置（issue #4416）。
 *
 * 工序库与工艺路线**合并为单一入口** `/production/routings`（菜单项「工艺配置」）：
 * 工序是**原子词汇**、路线是**用工序名拼出的有序序列**，后端护栏把这条先后关系钉死
 * （`ProductionRoutingCommandService.validateSequence`：「工序「X」在工序库中不存在或已停用：
 * **请先在「工序库」新增该工序」」）—— 拆成两个菜单时，建路线发现缺工序要跳到另一个菜单去建。
 *
 * ⇒ 本页不再渲染任何内容，直接重定向到唯一入口（旧书签/外部深链不 404），
 * 照 #4357 的 `/processing-orders` → `/production` 先例。
 *
 * 工序库原有能力（分组目录 / 搜索 / 改单价 / 必完开关 / 作用域 / 新增工序 / 行业模板补套）
 * 已全部并入 `/production/routings` 的**左栏**，见 `production/routings/page.tsx`。
 */
export default function OperationsRedirectPage() {
  redirect('/production/routings')
}
