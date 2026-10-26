// case_ids: BM-014, BM-015, BM-025
/**
 * 工人工作台**入口显隐**判据（issue #7812）—— 让商家后台的「设置工人端菜单」真正生效。
 *
 * ## 病灶（商家 2026-10-26 反馈）
 *
 * 后台勾了才该出现 / 才该消失的入口，在 bmini 工作台是**无条件渲染**的 ⇒ 那个开关对
 * `/b/` 与小程序**完全不生效**（只在 H5 `/w/` 生效）。工人看到的是「菜单怎么点都没变」。
 *
 * ## 三条口径（与 H5 `/w/` 既有语义同源，`frontend/worker-h5/src/render.mjs::effectivePages`）
 *
 * 1. **页面键 = 后端 `WorkerPages` 的闭词表**（`report` / `piecework` / `order` / `cut_calc` /
 *    `shipment` / `inspect`）；端侧只按字符串消费，**不**自己发明键；
 * 2. 🔴 **fail-open**：读不到（网络 / 5xx / 非数组）或读到了空数组 ⇒ **按全开渲染**。
 *    把「开关没读到」变成「活干不了」是更坏的失败（工人手上那台设备是他的生产工具）；
 * 3. **显隐 ≠ 访问拦截**：菜单藏起来只是不显示入口，直接打开页面照旧可用（2026-09-29 用户裁定）。
 *
 * ## 无键的入口
 *
 * 「拍照入库」「补打入库标签」是工人面**固有**能力（后端没有对应的页面键）⇒ **恒显示**，
 * 不参与本判据（`ALWAYS_VISIBLE` 只作登记，不参与计算）。
 */

/** 后端 `WorkerPages` 的闭词表（本文件只**消费**；新增键以后端为准）。 */
export const WORKER_MENU_KEYS = {
  /** 扫码报工（P2a，本包新增的页） */
  report: 'report',
  /** 我的计件 */
  piecework: 'piecework',
  /** 订单 / 套号明细 */
  order: 'order',
  /** 裁高计算（一体机） */
  cutCalc: 'cut_calc',
  /** 拍照发货 */
  shipment: 'shipment',
  /** 质检（逐人开，不在默认集合里） */
  inspect: 'inspect',
} as const

/**
 * 「待发货单」的页面键（**由 #7813 在后端新增**）。
 *
 * ⚠️ 本包（P2a）**先不**拿它门控那张卡：后端还不回这个键时门控 ⇒ 卡片恒隐藏
 * （P1a #7808 刚上线的入口会「上线即消失」）。#7813 合入后把那处 `TODO(#7813)` 换成本键即可。
 */
export const TO_SHIP_PAGE_KEY = 'to_ship'

/** 工人面固有入口（后端无页面键 ⇒ 恒显示；仅登记，不参与计算）。 */
export const ALWAYS_VISIBLE = ['拍照入库', '补打入库标签'] as const

/**
 * 本机可显示的菜单键集合。
 *
 * @param pages   `/api/worker/me` 的 `pages`（`null` = 还没读到 / 读到坏值）
 * @param unread  是否**读不到**（网络 / 5xx / 形状不对）
 * @returns 可显示键的集合；`unread` 或空集 ⇒ **全开**
 */
export function visibleMenuKeys(pages: string[] | null | undefined, unread = false): Set<string> {
  const all = new Set<string>(Object.values(WORKER_MENU_KEYS))
  all.add(TO_SHIP_PAGE_KEY)
  if (unread) return all
  if (!Array.isArray(pages) || pages.length === 0) return all
  return new Set(pages.filter((key) => typeof key === 'string'))
}

/** 单个键是否可显示（fail-open 同上）。 */
export function menuVisible(
  pages: string[] | null | undefined,
  unread: boolean,
  key: string,
): boolean {
  return visibleMenuKeys(pages, unread).has(key)
}

