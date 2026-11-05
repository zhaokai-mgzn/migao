/**
 * 下单页的**布料行**（售卖形态 = 布料）—— issue #8725 第一档切片产物。
 *
 * 单一职责：按米卖布时那一行的**米数 / 单价 / 卷数 / 卷长**录入与体积差提示。
 * 不出现宽高 / 工艺规格 / 部位行 / 加工项 / 加工费（issue #4493：布料单无加工）。
 */
import { NumberInput } from '@/components/ui'
import { type OrderLineItem } from '@/lib/order-create/types'
import { Label } from '@/components/orders/order-create/primitives'

/**
 * **布料行**（issue #4493，用户裁定「如果是布料下单就**无加工**了」）：
 * 只有 **米数 / 单价** —— 不出现宽高 / 工艺规格 / 部位行 / 加工项 / 加工费。
 *
 * 为什么不复用部位行：部位行整套（工艺规格 8 项 + 宽高 + 加工项 + 算料）对布料**全是噪音**，
 * 而且宽高对布料没有意义（布料按米卖，没有成品尺寸）。
 */
export function FabricRow({
  line,
  errors,
  specPicker,
  onChangeQty,
  onChangePrice,
  onChangeRollCount,
  onChangeRollLength,
}: {
  line: OrderLineItem
  errors: Record<string, string>
  /**
   * **门幅 / 规格**节点（2026-09-30 第四批）—— 由组级传入的**唯一一份** JSX。
   * 布料没有「用料与规格」这一步，但「按什么规格买」仍是这一行的输入 ⇒ 与数量 / 单价同一行。
   */
  specPicker?: React.ReactNode
  onChangeQty: (q: number) => void
  onChangePrice: (p: number) => void
  /** **卷数**（issue #5846）：`null` = 留空 ⇒ 该键不进 payload（服务端按货号卷长派生） */
  onChangeRollCount: (n: number | null) => void
  /** **每卷实际米数**（issue #5846）：默认带出商品 `products.roll_length_m` */
  onChangeRollLength: (n: number | null) => void
}) {
  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]
  const errRollCount = errors[`line_${line.id}_rollCount`]
  const errRollLength = errors[`line_${line.id}_rollLengthM`]
  const inputClass =
    'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'

  // ===== 整卷售卖（issue #5846，用户 2026-10-01 裁定 A）=====
  // 「整卷合计 = 卷数 × 每卷实际米数」与行米数的差额**实时显示**；整卷合计 > 行米数（负差额）
  // ⇒ **显式标红**，由人决定改哪一个 —— 页面**不自动改写** `quantity`（静默改数是红线）。
  const rollsFilled = typeof line.rollCount === 'number'
  const rollsTotal =
    rollsFilled && typeof line.rollLengthM === 'number'
      ? Math.round(line.rollCount! * line.rollLengthM * 100) / 100
      : null
  const rollDiff = rollsTotal === null ? null : Math.round((Number(line.quantity) - rollsTotal) * 100) / 100
  const rollShort = rollDiff !== null && rollDiff < 0
  return (
    <div className="rounded-lg border border-neutral-200 p-3">
      <div className={'grid gap-4 ' + (specPicker ? 'sm:grid-cols-3' : 'grid-cols-2')}>
        {specPicker && <div>{specPicker}</div>}
        <div>
          <Label required>数量</Label>
          {/* 布料行的数字框同样换掉（issue #5202）：吞键缺陷与帘行同源；#5210 起 = 共享 `NumberInput` */}
          <NumberInput
            value={line.quantity}
            onChange={(next) => onChangeQty(next ?? 0)}
            decimals={3}
            placeholder="米"
            aria-label="数量"
            className={inputClass}
          />
          {errQty && <p className="mt-1 text-sm text-red-600">{errQty}</p>}
        </div>
        <div>
          <Label required>单价 (¥/米)</Label>
          <NumberInput
            value={line.unitPrice}
            onChange={(next) => onChangePrice(next ?? 0)}
            decimals={3}
            aria-label="单价 (¥/米)"
            className={inputClass}
          />
          {errPrice && <p className="mt-1 text-sm text-red-600">{errPrice}</p>}
        </div>
        {/* ===== 整卷售卖：卷数 + 每卷实际米数（issue #5846）=====
            复用既有列 `order_items.roll_count` / `roll_length_m`（不加迁移）。
            🔴 **两格各自独立**（用户 2026-10-01 二次裁定**取消「成对」契约**）：给哪个发哪个，
            缺的那一半由服务端**回落**（显式 ?? 货号卷长），回落不到 ⇒ 保持 NULL（不猜）。
            「卷数填了但每卷米数留空」也是合法的（服务端回落货号卷长）。
            ⚠️ 不给 `decimals={0}`：那会把 2.5 **静默改成 3**（`NumberInput` 失焦归一化）；
            卷数非整数由下面的校验**显式拒绝**，人看得见自己填的是什么。 */}
        <div>
          <Label>卷数</Label>
          <NumberInput
            value={line.rollCount}
            onChange={onChangeRollCount}
            placeholder="留空 = 按米自动分配"
            aria-label="卷数"
            className={inputClass}
          />
          {errRollCount && (
            <p data-testid="roll-count-error" className="mt-1 text-sm text-red-600">
              {errRollCount}
            </p>
          )}
        </div>
        <div>
          <Label>每卷米数</Label>
          <NumberInput
            value={line.rollLengthM}
            onChange={onChangeRollLength}
            placeholder="每卷实际米数"
            aria-label="每卷米数"
            className={inputClass}
          />
          {errRollLength && (
            <p data-testid="roll-length-error" className="mt-1 text-sm text-red-600">
              {errRollLength}
            </p>
          )}
        </div>
      </div>
      {rollsTotal !== null && rollDiff !== null && (
        <p
          data-testid="roll-diff"
          className="mt-2 text-xs text-neutral-500 tabular-nums"
        >
          整卷合计 {line.rollCount} × {line.rollLengthM} = {rollsTotal} 米；行米数 {line.quantity} 米；
          差额 {rollDiff} 米
        </p>
      )}
      {rollShort && rollDiff !== null && (
        <p data-testid="roll-diff-warning" className="mt-1 text-xs text-red-600">
          整卷合计 {rollsTotal} 米 ＞ 行米数 {line.quantity} 米（差 {Math.round(-rollDiff * 100) / 100} 米）
          —— 请确认改「数量」还是改「卷数 / 每卷米数」；系统不会自动改数量
        </p>
      )}
      <p className="mt-1.5 text-xs text-neutral-400">
        布料按米计价：没有加工费，也不生成加工单
        {!rollsFilled && '；未填卷数 ⇒ 由系统按每卷米数（默认取货号卷长）自动分配整卷 / 散剪'}
      </p>
    </div>
  )
}
