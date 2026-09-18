import { redirect } from 'next/navigation'

/**
 * 旧「加工单」列表入口 → 生产看板（issue #4357）。
 *
 * 原列表页与「生产看板」/production 是**同一实体、同一端点**（processingOrderApi.list）的
 * 两份渲染；#4357 把「加工单」菜单并入生产管理组并与看板合并为单一入口
 * ⇒ 本页不再渲染列表，直接重定向到唯一入口（旧书签/外部深链不 404）。
 *
 * ⚠️ 子路由 /processing-orders/{id}/production（生产明细）**不随菜单移除**，
 * 仍由看板行内「生产明细」按钮进入 —— 故本目录不能整体删除。
 * 列表页原有能力（关键词/状态筛选、重置、商品与数量快照摘要、查看跳订单详情、
 * 加载失败重试、筛选空态、请求时序保护）已全部并入 /production，见 production/page.tsx。
 */
export default function ProcessingOrdersPage() {
  redirect('/production')
}
