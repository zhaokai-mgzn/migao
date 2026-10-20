/**
 * 订单列表的「下单时间」窗口解析（issue #7404：用户裁定「需要做个兜底，不允许查全部」「最多回溯近 3 年」）。
 *
 * <p>为什么要兜底：下单时间范围在页面上是**可清空**的两个原生日期输入，清空后请求就不带日期参数；
 * 而关键词是 `LIKE '%kw%'`（客户名 / 电话 / 订单号三列 OR）⇒ 无时间谓词时后端要在**本租户全部订单**
 * 上逐行匹配，分页每翻一页还要再来一次同样的 `COUNT(*)`。</p>
 *
 * <p>口径与后端 `OrderService.resolveListWindow` **同一条**（`DEFAULT_LOOKBACK_MONTHS = 36`）：
 * 没有起点 ⇒ 起点 = 终止日（没给就是今天）− 36 个月；没有终点 ⇒ 终点 = 今天。
 * 显式选了日期就**原样透传**（要查三年前的某一单，自己选日期即可）。</p>
 */

/** 与 `backend/admin-api/.../OrderService.java` 的 `DEFAULT_LOOKBACK_MONTHS` 同值（改动要两边一起改）。 */
export const ORDER_LOOKBACK_MONTHS = 36

export function formatYmd(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export interface OrderDateWindow {
  startDate: string
  endDate: string
  /** true = 两端都没选、窗口是**兜底**出来的（调用方据此把输入框回填成实际查询的区间） */
  filled: boolean
}

/**
 * 把「页面上选的下单时间」解析成**实际要查**的区间。
 *
 * @param startDate 页面上的开始日期（`YYYY-MM-DD`，可空）
 * @param endDate   页面上的结束日期（`YYYY-MM-DD`，可空）
 * @param today     业务「今天」（注入以便单测；默认取本机今天）
 */
export function resolveOrderDateWindow(
  startDate: string,
  endDate: string,
  today: Date = new Date(),
): OrderDateWindow {
  if (startDate || endDate) {
    return { startDate, endDate, filled: false }
  }
  const start = new Date(today)
  start.setMonth(start.getMonth() - ORDER_LOOKBACK_MONTHS)
  return { startDate: formatYmd(start), endDate: formatYmd(today), filled: true }
}
