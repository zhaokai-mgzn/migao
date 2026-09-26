'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { craftSpecRows } from '@/lib/craft-display'
import { lineSubtotal } from '@/lib/order-amount'
import { usePaymentQrcodes } from '@/lib/use-payment-qrcodes'
import { resolveImageUrl } from '@/lib/utils'
// 「算料输出」行的标签（原始输入 vs 算料输出的分组口径）—— 从既有那份 import，
// 不复制一份会漂移的副本（见文件头第 5 条）
import { CALC_OUTPUT_LABELS } from './OrderItemList'
import type { PrintTarget } from './index'
import type { Order, OrderItem, PaymentQrcodeMap } from '@/types'

/**
 * 报价单（可打印纸质文档，issue #4965）—— 照真实报价单 A4 制式（亿家纺织 CSO260918-03182）。
 *
 * 用户诉求（2026-09-21，逐字）：「这是从订单上打印的报价单，用来发给客户的，也可用于生产，
 * 这是 A4 大小，这个用来参考设计我们的打印制式」。四段制式：
 *   ① 表头：报价单 / 单号 / 货运 / 客户·电话·地址 / 备注
 *   ② 正文：**每个商品行自成一套**（用户裁定 ②）—— 段头 `第N套/共M套` + `本套金额`，
 *      每段一张 10 列表：部位 | 部位信息 | 部位备注 | 宽*高 | 组件 | 货号 | 用料 | 价格 | 小计 | 备注
 *   ③ 汇总：本单总金额 / 优惠金额 / 本单应收
 *   ④ 页脚：温馨提示常量 + 右下扫码支付码
 *
 * 打印隔离沿用项目既有范式（见 `components/orders/ShipmentDoc.tsx` 文件头的 6 条约束）：
 * 1. **屏幕隐藏、打印可见**：订单详情页已有自己的屏幕布局，再显示一份会重复；本组件自带
 *    `display:none` + `@media print` 覆盖 ⇒ 屏幕上零视觉改动、打印时**只有**这份单据。
 * 2. **portal 到 body + display:none 隔离**：单据经 `createPortal` 渲染为 `document.body`
 *    的直接子级，打印 CSS 用 `body > *:not(.quotation-print-area) { display: none !important; }`
 *    把整页外壳藏掉 —— **display:none 不占版面高度**，分页只按单据自身高度计算
 *    （旧方案 `visibility:hidden` 隐藏的元素仍占高度，底层页面高于一页 A4 时第 2 页空白，
 *    issue #3896）。注意 `.quotation-print-area` 必须是 portal 容器本身的 class，不能再包一层。
 *    🔴 **同页多单据的两条硬约束**（issue #4965，CI `Demo path specs` 实测红后修正 —— 别退回旧写法）：
 *    订单详情页**同时挂着**发货单（`ShipmentDoc`）与本报价单，两者都是 `document.body` 的**直接子级**
 *    （§范式 2 的物理前提）。旧写法（各自 `body > *:not(.<自己>-print-area)` + 无限定
 *    `visibility: visible`）在这种同页共存下**两条都错**，且错误方向相反：
 *    ① **互相 `display:none`**：`body > *:not(.quotation-print-area)` 会把**兄弟单据**
 *       （`.shipment-print-area`）也选进来 ⇒ `display:none !important` 把对方整份藏掉
 *       （实测：点「打印发货单」时发货单 `display:none` ⇒ `toBeVisible()` 红）；
 *    ② **visibility 后渲染者胜**：两份 `visibility: visible` 防御**同特异性**，后挂的报价单
 *       把发货单重新藏成 invisible。
 *    ⇒ 修法（两条一起）：**隔离选择器排除所有打印单据**（`body > *:not(.print-doc)`，两份单据的
 *    容器都带 `print-doc` 标记类 ⇒ 它们互不隐藏；其余外壳一律 `display:none` 不占版面高度）；
 *    **visibility 防御限定本次打印目标**（`.quotation-print-area[data-print-target='quotation'], …`，
 *    由调用方在打印时置位，见 `PrintTarget` / `OrderDetail` 的 `printTarget`）。
 * 3. **不得放进 Modal**：`Modal` 面板是 `max-h-full` + 内部 `overflow-y-auto`，打印只会打出
 *    可视区那一屏（多页明细被裁）。故调用方一律渲染在页面级。
 * 4. **每页只挂一份**：`.quotation-print-area` 是全局选择器，挂两份会打印出两套单据。
 *
 * 数据口径（四条硬约束，勿随手改）：
 * 5. **展示真值单一来源**：`部位` = `processingInfo.curtainType`；`部位信息` / `部位备注` 一律
 *    取自 `lib/craft-display.ts` 的 `craftSpecRows()`（设计文档 §4.9「一份 spec，三处渲染」），
 *    本组件**不另写一份推导**；「部位」行已有自己的列 ⇒ 从两列里排除（同一真值不重复印）；
 *    两列的切分沿用既有「原始输入 / 算料输出」分组（§4.3 表 B）。
 *    `craftSpecRows` 已丢弃缺值行 ⇒ 键缺席 / null / 空串 / 空数组的行不出现，
 *    纸面**绝不**出现 `undefined` / `null` / `NaN`。
 * 6. **金额口径单一来源**：行小计 = `lib/order-amount.ts` 的 `lineSubtotal(item)`
 *    （= `subtotal + processingFee`，与 `OrderItemList` **同一份**）；汇总三个数字只读订单字段
 *    （`totalAmount` / `discountAmount` / `actualAmount`），**不自己求和**。
 * 7. **我们没有的字段一律不印**（用户裁定 ①）：上期余额 / 预存抵扣 / 账户余额 / 交付日期 /
 *    制单人 —— 缺值不渲染，不编值、不留空标签。⚠️ 与参照物的一处**有意差异**：参照物把加工费
 *    并进面料单价，而我们 `unitPrice` 与 `processingFee` 是**两笔真实金额** ⇒ 必须分别列示
 *    （面料行 + 加工费行），否则商家对不上账。
 * 8. **没有收款码 ⇒ 整块不出现、不画假码**（`imageUrl` 缺席即视为无码）。
 */
interface QuotationDocProps {
  order: Order
  /**
   * 收款码（`GET /api/admin/settings/payment-qrcodes` 的 map）。
   * 不传 ⇒ 组件自取；取不到/为空 ⇒ 页脚支付块整块不出现。
   */
  paymentQrcodes?: PaymentQrcodeMap
  /**
   * 本次打印的目标（`'quotation'` = 打印本报价单）。**只在为 `'quotation'` 时**置位
   * `data-print-target`，让 visibility 防御只作用于本单据 —— 否则会把同页的发货单
   * （`ShipmentDoc`）重新藏掉（issue #4965 实测回归，见文件头第 2 条）。
   */
  printTarget?: PrintTarget | null
  className?: string
}

/** 温馨提示常量（照参照物口径逐字，勿改写） */
export const QUOTATION_FOOTER_NOTICE =
  '收到货后先验货，若有质量问题务必在七天内联系客服，如已开剪不予退换！'

function formatAmount(amount?: number): string {
  return (amount ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** 非空字符串（trim 后）；空串/null/undefined ⇒ null（缺值不渲染） */
function textOrNull(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** 有限数值 ⇒ 原样；其余 ⇒ null */
function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const PAYMENT_TYPE_LABELS: Record<string, string> = {
  wechat: '微信',
  alipay: '支付宝',
}

export default function QuotationDoc({
  order,
  paymentQrcodes,
  printTarget,
  className,
}: QuotationDocProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted（未挂载返回 null）
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  // 收款码读取口：与销售单（#5651）**同一份**实现（`lib/use-payment-qrcodes.ts`）——
  // 口径（调用方注入优先 / 打印时自取 / 失败或为空即「无码」）见该文件头，
  // **不在组件里再写一遍**（同一件事实两处各写一次 ⇒ 将来改一处、另一处静默不一致）。
  const qrcodes = usePaymentQrcodes(paymentQrcodes)

  if (!mounted) return null

  const items = order.items || []
  const qrEntries = Object.entries(qrcodes)
    .map(([type, qr]) => ({
      type,
      label: PAYMENT_TYPE_LABELS[type] || type,
      imageUrl: resolveImageUrl(qr?.imageUrl),
      payeeName: textOrNull(qr?.payeeName),
    }))
    .filter((entry) => entry.imageUrl !== '')

  // 货运：物流方式（`order.logisticsType`）+ 物流公司（`order.logisticsCompany`，issue #4874）。
  // 两者都缺 ⇒ 该栏不印（不编值、不留空标签）。
  // ⚠️ 这里**原样印**取值、不套 `logisticsTypeLabel()` 的「未知 ⇒ 快递」兜底 ——
  // 报价单是给客户的**报价凭证**，不能把一个未知/自定义的物流方式印成「快递」（编值）。
  const logisticsType = textOrNull(order.logisticsType)
  const logisticsCompany = textOrNull(order.logisticsCompany)
  const freight = [logisticsType, logisticsCompany].filter(Boolean).join(' · ')
  const remark = textOrNull(order.remark)
  const hasDiscount = typeof order.discountAmount === 'number'

  return createPortal(
    <div
      className={className ? `quotation-print-area print-doc ${className}` : 'quotation-print-area print-doc'}
      {...(printTarget === 'quotation' ? { 'data-print-target': 'quotation' } : {})}
    >
      <style>{`
        .quotation-print-area { display: none; }
        @page { size: A4; margin: 12mm; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          .quotation-print-area {
            display: block;
            position: static;
            width: 100%;
            font-size: 12px;
          }
          /* 防御：页面其他组件（如 ProcessingOrderBlock）残留的
             "body * { visibility: hidden }" 打印隔离会连同本单据一起藏掉
             ——必须显式恢复单据自身可见（见文件头第 2 条）。
             ⚠️ 限定 [data-print-target='quotation']：本页同时挂着发货单，两条
             visibility: visible 同特异性 ⇒ 后渲染者胜，不加限定会把发货单藏掉
             （issue #4965 实测回归）。 */
          .quotation-print-area[data-print-target='quotation'],
          .quotation-print-area[data-print-target='quotation'] * { visibility: visible; }
          .quotation-set { break-inside: avoid; }
        }
      `}</style>

      {/* ===== ① 表头 ===== */}
      <div className="text-center text-xl font-semibold tracking-[0.5em] mb-1">报价单</div>
      <div className="text-center text-xs text-neutral-500 mb-3">{order.orderNo}</div>

      <table className="w-full border-collapse mb-3">
        <tbody>
          <tr>
            <DocCell label="客户" value={order.customerName} />
            <DocCell label="电话" value={order.customerPhone} />
          </tr>
          <tr>
            <DocCell label="地址" value={order.customerAddress} colSpan={3} />
          </tr>
          {freight !== '' && (
            <tr>
              <DocCell label="货运" value={freight} colSpan={3} />
            </tr>
          )}
        </tbody>
      </table>

      {remark && (
        <div className="border border-neutral-400 px-2 py-1.5 mb-3">
          <span className="text-neutral-500">备注：</span>
          <span className="whitespace-pre-wrap">{remark}</span>
        </div>
      )}

      {/* ===== ② 正文：每个商品行自成一套（用户裁定 ②，不做樘窗分组） ===== */}
      {items.map((item: OrderItem, idx: number) => (
        <SetBlock key={item.id || idx} item={item} index={idx} total={items.length} />
      ))}

      {/* ===== ③ 汇总：只读订单字段，不自己求和 ===== */}
      <table className="w-full border-collapse mb-3">
        <tbody>
          <tr>
            <td className="border border-neutral-400 px-2 py-1.5 w-28 text-neutral-500">
              本单总金额
            </td>
            <td className="border border-neutral-400 px-2 py-1.5 text-right">
              {formatAmount(order.totalAmount)}
            </td>
          </tr>
          {/* 优惠金额：缺值 ⇒ 该行不印（不印 ¥0.00 假优惠） */}
          {hasDiscount && (
            <tr>
              <td className="border border-neutral-400 px-2 py-1.5 text-neutral-500">优惠金额</td>
              <td className="border border-neutral-400 px-2 py-1.5 text-right">
                {formatAmount(order.discountAmount)}
              </td>
            </tr>
          )}
          <tr>
            <td className="border border-neutral-400 px-2 py-1.5 text-neutral-500">本单应收</td>
            <td className="border border-neutral-400 px-2 py-1.5 text-right font-semibold">
              {formatAmount(order.actualAmount)}
            </td>
          </tr>
        </tbody>
      </table>

      {/* ===== ④ 页脚：温馨提示 + 扫码支付码（无码 ⇒ 整块不出现） ===== */}
      <div className="flex items-end justify-between gap-4 border-t border-neutral-300 pt-2">
        <div className="text-xs text-neutral-600">{QUOTATION_FOOTER_NOTICE}</div>
        {qrEntries.length > 0 && (
          <div className="flex items-end gap-3 shrink-0">
            {qrEntries.map((entry) => (
              <div key={entry.type} className="text-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={entry.imageUrl}
                  alt={`${entry.label}收款码`}
                  className="w-[22mm] h-[22mm] object-contain border border-neutral-300"
                />
                <div className="text-[10px] text-neutral-500 mt-0.5">{entry.label}</div>
                {entry.payeeName && (
                  <div className="text-[10px] text-neutral-500">{entry.payeeName}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

// ========== 每套（= 每个商品行）一段 ==========

function SetBlock({ item, index, total }: { item: OrderItem; index: number; total: number }) {
  const info = (item.processingInfo ?? {}) as Record<string, unknown>

  // 部位 = 部位自己的名字（与洗水码「商品行 = 部位」同粒度）
  const part = textOrNull(info.curtainType)
  // 部位信息 / 部位备注 = craftSpecRows 的**同一份真值**（§4.9）——
  // 排除「部位」行（它已有自己的列，重复印同一真值只是噪音）；
  // 其余按「算料输出」与否分列（分组口径与 OrderItemList 同一份 CALC_OUTPUT_LABELS）
  const specRows = craftSpecRows(item.processingInfo).filter((row) => row.label !== '部位')
  const infoRows = specRows.filter((row) => !CALC_OUTPUT_LABELS.has(row.label))
  const remarkRows = specRows.filter((row) => CALC_OUTPUT_LABELS.has(row.label))

  // 组件：面料行 = componentRole（缺省即主布）/ 加工费行 = 加工费
  const componentRole = textOrNull(info.componentRole) || '主布'
  // 货号 = productCode + colorName（各自缺则只印有的那个；都缺 ⇒ 不印）
  const code = [textOrNull(item.productCode), textOrNull(info.colorName)]
    .filter(Boolean)
    .join(' ')
  const width = numberOrNull(item.width)
  const height = numberOrNull(item.height)
  const size = width !== null && height !== null ? `${width}×${height}` : null
  const quantity = numberOrNull(item.quantity)
  const processingFee = numberOrNull(item.processingFee) ?? 0
  const spec = textOrNull(item.specification)

  return (
    <div className="quotation-set mb-3">
      <div className="flex items-center justify-between font-semibold mb-1">
        <span>
          第{index + 1}套/共{total}套
        </span>
        <span>本套金额 {formatAmount(lineSubtotal(item))}</span>
      </div>
      {/* table-layout: fixed —— 列宽由表头声明的百分比决定（auto 布局按内容分配，
          长工艺文案会把列撑歪，纸面每单都可能不一样） */}
      <table className="w-full border-collapse" style={{ tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <DocTh className="w-[7%]">部位</DocTh>
            <DocTh className="w-[14%]">部位信息</DocTh>
            <DocTh className="w-[14%]">部位备注</DocTh>
            <DocTh className="w-[9%]">宽*高</DocTh>
            <DocTh className="w-[7%]">组件</DocTh>
            <DocTh className="w-[11%]">货号</DocTh>
            <DocTh align="right" className="w-[8%]">
              用料
            </DocTh>
            <DocTh align="right" className="w-[9%]">
              价格
            </DocTh>
            <DocTh align="right" className="w-[10%]">
              小计
            </DocTh>
            <DocTh className="w-[11%]">备注</DocTh>
          </tr>
        </thead>
        <tbody>
          {/* 面料行 */}
          <tr>
            <DocTd>{part || ''}</DocTd>
            <DocTd>{rowsText(infoRows)}</DocTd>
            <DocTd>{rowsText(remarkRows)}</DocTd>
            <DocTd>{size || ''}</DocTd>
            <DocTd>{componentRole}</DocTd>
            <DocTd>{code}</DocTd>
            <DocTd align="right">{quantity ?? ''}</DocTd>
            <DocTd align="right">{formatAmount(item.unitPrice)}</DocTd>
            <DocTd align="right">{formatAmount(item.subtotal)}</DocTd>
            <DocTd>{spec || ''}</DocTd>
          </tr>
          {/* 加工费行：processingFee > 0 才出（与参照物的**有意差异**：我们两笔真实金额
              必须分别列示，否则商家对不上账 —— 见文件头第 7 条） */}
          {processingFee > 0 && (
            <tr>
              <DocTd>{part || ''}</DocTd>
              <DocTd>{''}</DocTd>
              <DocTd>{''}</DocTd>
              <DocTd>{''}</DocTd>
              <DocTd>加工费</DocTd>
              <DocTd>{code}</DocTd>
              <DocTd align="right">{quantity ?? ''}</DocTd>
              <DocTd align="right">{formatAmount(processingFee)}</DocTd>
              <DocTd align="right">{formatAmount(processingFee)}</DocTd>
              <DocTd>{''}</DocTd>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ========== 打印友好的表格原子（纯边框、无底色，避免打印丢背景） ==========

/** 一组 craftSpecRows ⇒ 换行拼接（缺值行已由 craftSpecRows 丢弃 ⇒ 空组为空串） */
function rowsText(rows: { label: string; value: string }[]): string {
  return rows.map((row) => `${row.label}：${row.value}`).join('\n')
}

function DocCell({
  label,
  value,
  colSpan = 1,
}: {
  label: string
  value?: string
  colSpan?: number
}) {
  return (
    <>
      <td className="border border-neutral-400 px-2 py-1.5 w-20 text-neutral-500 whitespace-nowrap">
        {label}
      </td>
      <td className="border border-neutral-400 px-2 py-1.5" colSpan={colSpan}>
        {value || ''}
      </td>
    </>
  )
}

function DocTh({
  children,
  align = 'left',
  className,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  className?: string
}) {
  return (
    <th
      className={[
        'border border-neutral-400 px-1.5 py-1 font-semibold whitespace-nowrap',
        align === 'right' ? 'text-right' : 'text-left',
        className || '',
      ].join(' ')}
    >
      {children}
    </th>
  )
}

function DocTd({
  children,
  align = 'left',
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
}) {
  return (
    <td
      className={[
        'border border-neutral-400 px-1.5 py-1 align-top break-words whitespace-pre-line',
        align === 'right' ? 'text-right' : 'text-left',
      ].join(' ')}
    >
      {children}
    </td>
  )
}
