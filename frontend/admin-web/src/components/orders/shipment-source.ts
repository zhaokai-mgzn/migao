// case_ids: UI-078, UI-024
/**
 * 发货单来源 → 中文展示名（issue #5939 建面 / issue #6664 第 5 条收口）。
 *
 * 为什么单独成文件：这是**展示口径**（内部键 `worker_photo` 不上屏），
 * 判据需要在**不拉起整页**（那页会连带 `usePrintDoc` / next 路由）的情况下逐值校验。
 * 页面与本模块**同一份**映射 —— 页面直接 import，不另抄一份。
 */

/** 写面 `OrderShipment.source` 的三态 → 中文 */
export const SOURCE_LABEL: Record<string, string> = {
  worker_photo: '工人拍照',
  worker: '工人手工',
  admin: '商家',
}

/** 未知来源**不裸奔内部键**（issue #6664 第 5 条）：落人话兜底「未知来源」 */
export function sourceLabel(source: string | null | undefined): string {
  if (!source) return '未知来源'
  return SOURCE_LABEL[source] ?? '未知来源'
}
