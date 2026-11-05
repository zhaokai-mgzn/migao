/**
 * 下单页的**尺寸自动特征徽标**（超高 / 超宽 / 门幅未维护）—— issue #8725 第一档切片产物。
 *
 * 单一职责：把「这一行尺寸上有系统推算的特征」渲染成**只读徽标**（不含任何裁决入口 ——
 * 采纳 / 不采纳在部位行的自动特征面板里）。组级与行内共用同一实现，避免两份判定各说各话。
 */
import { parseDoorWidth } from '@/lib/craft-auto-features'
import { FONT_PX_10 } from '@/lib/design-tokens'
import { SALE_FORM_FABRIC, type OrderLineItem } from '@/lib/order-create/types'
import { autoFeatureRowsOf } from '@/lib/order-create/calc'

/**
 * **净尺寸**那一行的就地徽标（issue #4658 的放置 × 2026-09-28 的搬迁）——
 * 生效特征名（`超高` / `超宽` / `倒幅` / 派生「拼接」）+ 「门幅未维护」。
 *
 * 商家填尺寸时就看得见系统识别结果（不必翻到下面的推导面板）。
 * 2026-09-28：尺寸从行内「区块 1」提到**组级**（紧跟商品 / 颜色）⇒ 本函数随之提到**模块级**，
 * 由组级与行内**共用同一份判定**（两份就会出现「组头说超高、面板说没有」——本仓明令禁止）。
 *
 * 被**不采纳**的项不出现在徽标里（徽标 = **生效值**，与推导面板读同一份 `autoFeatures`）。
 */
export function sizeAutoBadgesOf(line: OrderLineItem): React.ReactNode {
  if (line.saleForm === SALE_FORM_FABRIC) return null
  const autoFeatures = autoFeatureRowsOf(line).filter((row) => !row.rejected)
  /** 「SKU 未维护门幅」——必须先有一个选中的 SKU（issue #4899：否则「还没选规格」被显示成「未维护」） */
  const doorWidthMissing =
    line.selectedSku !== null && parseDoorWidth(line.selectedSku.doorWidth) === null
  if (autoFeatures.length === 0 && !doorWidthMissing) return null
  return (
    <span data-testid="size-auto-badges" className="flex items-center gap-1 shrink-0">
      {autoFeatures.map((row) => (
        <span
          key={row.name}
          data-testid={`size-auto-badge-${row.name}`}
          title={row.reason}
          className={`rounded border border-amber-200 bg-amber-50 px-1 ${FONT_PX_10} leading-4 text-amber-700`}
        >
          {row.name}
        </span>
      ))}
      {doorWidthMissing && (
        <span
          data-testid="size-door-width-missing"
          title="该 SKU 未维护门幅 —— 系统不按缺省门幅推算（分幅与加工类型判不了；超高/超宽是按净窗宽高与企业阈值判的）"
          className={`rounded border border-neutral-300 bg-neutral-100 px-1 ${FONT_PX_10} leading-4 text-neutral-500`}
        >
          门幅未维护
        </span>
      )}
    </span>
  )
}
