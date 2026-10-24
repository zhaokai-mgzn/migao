/**
 * 盘点读面的前端形状（issue #7373 P1-1 段 2 后端 / 段 3 前端页面）。
 *
 * 真值 owner = `backend/admin-api` 的 `StocktakeView`（字段名逐字对齐，不另造口径）：
 * `bookQty` = **出任务当刻**的**剩余米数**快照（issue #7618 起；改前是原始入库量），`countedQty` / `diffQty` 为 `null` = **还没数**
 * （`null` 与 `0` 是两件事：没数 ≠ 数出来是 0）。
 */
export type StocktakeStatus = 'counting' | 'completed' | 'cancelled'

export interface StocktakeLine {
  batchId: number
  batchNo: string | null
  skuCode: string | null
  /** 盘点当刻的**剩余米数**（派生 = 入库米数 − 已派工消耗；快照，不随后续入库变化）。 */
  bookQty: number | null
  /** 实盘量；`null` = 还没数。 */
  countedQty: number | null
  /** 差异 = 实盘 − 账面，**服务端算**；`null` = 还没数。 */
  diffQty: number | null
}

export interface Stocktake {
  id: string
  stocktakeNo: string
  warehouseId: number
  /** 列表/详情接口**不回填**仓编码（服务端 `view(.., null, ..)`）⇒ 页面自己按 id 查名。 */
  warehouseCode: string | null
  status: StocktakeStatus
  note: string | null
  completedAt: string | null
  /** 列表接口返回**空数组**（只回单头）；逐批次明细走 `GET /api/admin/stocktakes/{id}`。 */
  items: StocktakeLine[]
}

/** 仓库（V182，issue #7373 段 1）：盘点必须落在**具体某个仓**上。 */
export interface Warehouse {
  id: number
  code: string
  name: string
  warehouseType?: string
  isDefault?: boolean
  status?: string
  remark?: string | null
}
