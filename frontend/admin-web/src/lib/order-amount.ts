/**
 * 订单**行金额口径单一真值**（issue #4965）。
 *
 * 用户 2026-09-21 裁定（报价单 issue #4965）：「本套金额 = `subtotal + processingFee`，
 * **与 `OrderItemList` 的行小计口径同一份**，勿各算一套」。
 *
 * 本文件就是那一份 —— 屏幕（订单详情明细行）与纸面（报价单每套表 / 本套金额）
 * 必须调用它，**不得**在渲染处各写一次 `item.subtotal + item.processingFee`：
 * 两处各写一次时，将来任何一处口径变化（例如加工费纳入方式调整）都会让
 * 「屏幕显示的金额」与「打给客户的纸面金额」静默不一致 —— 而商家是照纸面对账的。
 *
 * 口径（与后端一致，勿自行加价/推导）：
 * - `subtotal` = 面料行小计（元）
 * - `processingFee` = **行级落库**的加工费（issue #4406：组合价 × 加工费米数），缺省按 0
 * - 行小计 = 两者之和；**不**参与汇总（订单级数字只读订单字段，见 `QuotationDoc` 汇总段）
 *
 * ## 两个口径，**只在「面料小计不可知」这一格分叉**（issue #6731）
 *
 * | 面 | 函数 | 面料小计不可知时的行为 |
 * |---|---|---|
 * | 屏幕（订单详情明细行 `OrderItemList`） | `lineSubtotal` | 折 0（既有口径，issue #6720 裁定**不改屏幕**） |
 * | 纸面（报价单 `QuotationDoc`） | `paperLineSubtotal` | 返回 `null` ⇒ 印 `—`（**未知不得印成确定值**） |
 *
 * 两者逐值相同、**只有这一格不同**，并有一条表驱动判据把这张分叉表钉住
 * （`tests/unit/lib/order-amount.test.ts`）—— 谁改动任一侧都会当场红，必须回来重新裁定。
 * 🔴 **不要**把 `lineSubtotal` 也改成严格口径：那会改掉屏幕侧的显示值（本单边界明令不动屏幕）。
 */
import type { OrderItem } from '@/types'

/**
 * 行小计（元）= 面料小计 + 该行加工费。缺 `processingFee` ⇒ 按 0（存量单没有该字段）。
 *
 * 🔴 **`null` = 「算不出来」，不是 0**（issue #6720）：`subtotal` 也缺（后端
 * `OrderDetailResponse.OrderItemResponse.amount` 走的是 `unitPrice × quantity`，两者都为
 * null 时回落 `subtotal`，而 `subtotal` 同样可为 null；全局 Jackson
 * `default-property-inclusion: non_null` ⇒ 这两个键在响应里**整个缺席**）⇒ 返回 `null`，
 * 由**展示方**决定怎么印（纸面 `QuotationDoc` 印 `—`；屏幕 `OrderItemList` 保持原有 `¥0.00`
 * 外观，**本单不改屏幕口径**）。
 *
 * ⚠️ 别把这里改回 `|| 0`：那会把「没有这个数」折成「余额为零」，而这张数是**打给客户对账**的
 * （同族硬约束 = `SalesDoc` 的 `formatAmount`：缺值印 `—`、真 0 仍印 `0.00`）。
 */
export function lineSubtotal(item: Pick<OrderItem, 'subtotal' | 'processingFee'>): number | null {
  const subtotal = typeof item.subtotal === 'number' && Number.isFinite(item.subtotal) ? item.subtotal : 0
  const processingFee =
    typeof item.processingFee === 'number' && Number.isFinite(item.processingFee) ? item.processingFee : 0
  if (item.subtotal == null && item.processingFee == null) return null
  return subtotal + processingFee
}

/**
 * **纸面**行小计（元）= `subtotal + processingFee`，**任一加数不可知 ⇒ 和不可知**（`null`）
 * —— issue #6731。
 *
 * 为什么与 `lineSubtotal` 不同（第 ①~④ 条是**可达性**，不是口味）：
 * ① 存量 `order_items.subtotal` 可为 NULL（`backend/admin-api/src/main/resources/db/init/schema.sql`
 *    的 `subtotal DECIMAL(12,2)` 无 NOT NULL / DEFAULT；2026-05-31 `e1f31f351` 之前
 *    `OrderService.createOrder` 把请求里的 subtotal 原样落库 → 请求侧当时可选 → NULL 落库；
 *    该提交**不带回填迁移**）；
 * ② `processingFee` **恒为 number**（`OrderService.convertToDetailResponse`：
 *    `fee == null ⇒ BigDecimal.ZERO` 也照样 `set`）⇒ 存量行拿到的是 `processingFee: 0`；
 * ③ 全局 Jackson `default-property-inclusion: non_null` ⇒ `subtotal` 为 null 时**键整个缺席**
 *    ⇒ 前端拿到 `undefined`；
 * ④ ⇒ 「`subtotal` 不可知 + `processingFee = 0`」= **真形态**。旧写法 `0 + 0` 会让纸面印出
 *    `本套金额 0.00`，而**同一张纸**那一行的「小计」栏印 `—` = 自相矛盾（未知被印成确定值）。
 *
 * ⚠️ **`processingFee` 缺省仍按 0**（不是「不可知」）：那是本文件既有的**存量单口径**
 * （「存量单没有该字段」= 当时没有加工费这回事 ⇒ 真值就是 0），改它会制造**假 `—`**。
 * 这条不对称由 `assertAggregateUnknownIsContagious` 的样本矩阵**显式钉住**。
 */
export function paperLineSubtotal(item: {
  /** ⚠️ 形参按**运行时可缺席**声明（`OrderItem.subtotal` 的类型是必填的，那是类型在说谎：
   *  存量行的该列可为 NULL，后端 `non_null` 让键整个缺席）—— 这正是本函数存在的理由。 */
  subtotal?: number
  processingFee?: number
}): number | null {
  if (typeof item.subtotal !== 'number' || !Number.isFinite(item.subtotal)) return null
  return item.subtotal + (typeof item.processingFee === 'number' && Number.isFinite(item.processingFee) ? item.processingFee : 0)
}
