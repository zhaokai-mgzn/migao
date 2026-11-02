// 池化派单读面的行类型（issue #7091 拆出本文件）。
//
// 为什么单独一个文件：`src/types/index.ts` 是**冻结文件**（`tests/unit_ci_workflows/loc_freeze_ledger.json`
// 只许向下，issue #8166）⇒ 新增字段另立模块，由 `@/types` 转发（消费方导入路径不变）。

/**
 * 池内一行（`PoolLine`）—— `GET /api/admin/production/pool` 的
 * `urgentLines[]` 与 `groups[].lines[]` 共用同一结构。
 *
 * 🔴 **顺序由服务端唯一确定**（到货日升序 null 最后 → waitHours 降序 → waitingSince 升序 →
 * orderId 升序）：前端**按接口给的数组顺序渲染，不得重排**（在浏览器里再排一次 = 第二份会漂的口径）。
 */
export interface PoolLine {
  orderId: string
  orderNo: string
  itemId: string
  productId: string
  productName: string
  skuCode?: string | null
  requiredMeters: number
  /** ISO offset datetime（`waitHours` 的取数起点） */
  waitingSince: string
  waitHours: number
  overdue: boolean
  /** 非空列 ⇒ 服务端**总是**下发（缺省 false = 不加急） */
  isUrgent: boolean
  /** 外发加工标记（V194，issue #7746 后续）：true ⇒ 不进池、进外发区、派单必须选承接方。 */
  isOutsourced?: boolean
  /**
   * 到货日 `YYYY-MM-DD`。
   * 🔴 后端 Jackson 配了 `default-property-inclusion: non_null` ⇒ **未指定时这个键整个缺席**
   * （不是 `null`）⇒ 渲染必须把「缺席」与「null」当同一件事（`?? null` / 可选链），
   * 且**不得**把日期串过 `new Date(...)`（服务端时区 Asia/Shanghai，会整体差一天）。
   */
  requiredDeliveryDate?: string | null
  /** 到货日 − 今天（天）；负数 = 已逾期；**未指定时键缺席**；服务端算，前端不重算 */
  deliveryDaysLeft?: number | null
  /**
   * **库存可满足性**（issue #7091，服务端只读字段）：本行需求能否被某个库存批次裁出。
   *
   * 语义 = 派工前 fail-closed 判据的那一个条件（服务端同源的余量派生点 + 同一条 SKU 一致性口径）
   * ⇒ `false` = 勾上它点「一键合并派单」必被拒（服务端拒绝整批，不静默少派）。
   * 🔴 缺席（老服务端 / 桩数据）= **不可判定** ⇒ 一律按可派处理（缺字段不制造假阻塞）。
   */
  stockSatisfiable?: boolean
}
