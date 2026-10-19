/**
 * 售卖形态（issue #4493）的**前端唯一读点**（issue #7320）。
 *
 * 为什么需要它：**布料单不涉及加工费** —— 布料行没有加工项、没有工艺规格、没有组合价。
 * 但仓里多处展示此前只按「有没有选配加工项 / `fee_source`」判 ⇒ 每一张布料单都会在订单详情
 * 挂一条「加工费未定价（没有可匹配的组合（缺选配信息））」的假警报，并在「工艺规格」组里
 * 印出「加工费米数」（那是加工费口径的字段）。
 *
 * 判据逐字相等 `'布料'`：与后端 `ProcessingOrderService.SALE_FORM_FABRIC` / 下单页
 * `SALE_FORM_FABRIC` 同一取值（缺键 / 其它取值 ⇒ **不是**布料行，不造值）。
 *
 * ⚠️ 本模块是**展示侧**的唯一读点：写侧（下单页表单态）自己的 `SaleForm` 联合类型留在页面里。
 */
export const SALE_FORM_FABRIC = '布料'

/** 该行的 `processing_info.saleForm` 是否为「布料」（缺键 / 非字符串 / 脏值 ⇒ false）。 */
export function isFabricSaleLine(processingInfo: unknown): boolean {
  if (processingInfo === null || typeof processingInfo !== 'object' || Array.isArray(processingInfo)) {
    return false
  }
  const raw = (processingInfo as Record<string, unknown>).saleForm
  return typeof raw === 'string' && raw.trim() === SALE_FORM_FABRIC
}
