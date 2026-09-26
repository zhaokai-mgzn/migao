'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import dayjs from 'dayjs'
import {
  isContinuousFeed,
  printBodyFontPt,
  printPageRule,
  printUsableHeightMm,
  type PrintMediaId,
} from '@/lib/print-media'
import { usePaymentQrcodes } from '@/lib/use-payment-qrcodes'
import { cn, resolveImageUrl } from '@/lib/utils'
// 页脚「温馨提示」与报价单**同一句**（#4965）—— 从既有那份 import，不复制一份会漂移的副本
import { QUOTATION_FOOTER_NOTICE } from './QuotationDoc'
import type { PrintTarget } from './index'
import type { Order, OrderItem, PaymentQrcodeMap } from '@/types'

/**
 * 销售单（可打印纸质文档 · **三联纸 241mm × 140mm**，issue #5651）——
 * 照客户现行实物制式（去 PII 后登记在 issue #5651 的实证表 #4）。
 *
 * ## 介质：三联纸（针式点阵 + 连续纸 + 压感复写）
 *
 * 用户 2026-09-26 逐字裁定「**241mm × 140mm（两等分）**」。这是全仓此前**零支持**的第三种
 * 打印介质（`三联` / `针式` / `压感` / `连续纸` 全仓 0 命中），四条技术要点照 issue 口径落实：
 * 1. 🔴 **复写是纸的特性，不是软件的事** —— 一次打印即复写三份 ⇒ 本组件**只渲染一页**
 *    （DOM 里只有**一份** `.sales-sheet`；矩阵的 `carbonCopies: 3` 描述纸，**不是**渲染次数）；
 * 2. **`@page` 按连续纸尺寸**：由 `printPageRule(media)` 生成
 *    （`@page { size: 241mm 140mm; margin: 6mm 12mm; }`）—— 边距与页长是**通用参数 + 待实测**，
 *    登记在 `lib/print-media.json` 的 `pendingMeasurements`（真机参数本机拿不到，**不编造**）；
 * 3. **针打字号独立预算**：正文走矩阵的 `minFontPt`，**不复用 A4 的 6pt 量级**（针打 180dpi
 *    量级，A4 的小字号上去会糊）；❌ 不照 A4 的比例硬套；
 * 4. **走纸与页边距**：连续纸靠**走纸孔**定位 ⇒ 容器按纸固定高度 + `overflow: hidden`
 *    （高度 = `printUsableHeightMm()` = 页长 − 上下边距）—— 内容超高会打到**下一联**，
 *    属「纸面与账目对不上」的一种形态，**不许**靠浏览器自然分页兜。
 *
 * ## 介质是**参数**，不是副本（issue #5651 的核心架构要求）
 *
 * `media` 是 prop（缺省三联纸）：同一份字段映射既能落三联纸、也能落 A4 —— 切介质**只**换
 * 「版面参数」（`@page` / 字号 / 容器高度），**不产生第二份字段映射**。
 * 守卫两处：`test_print_media_matrix_guard.py` C5（列清单全仓只许出现在一个文件）+
 * `tests/unit/components/SalesDoc.test.tsx`（切介质后逐格取值必须逐字相同）。
 *
 * ## 制式（四段，逐条对实证 #4）
 *
 * ① 表头：销售单 / 单号 / 日期 / 客户 / 电话 / 地址 / 订货电话；
 * ② 明细：{@link SALES_DOC_COLUMNS}（序号 | 货号 | 数量 | 单位 | 单价 | 金额 | 备注）——
 *    **商品行粒度**（与报价单的「按套 × 部位」粒度**不是同一个数据投影**，不许互套）；
 * ③ 汇总：上期余额 / 预存抵扣 / 优惠金额 / **本单应收** / 账户余额；
 * ④ 页脚：温馨提示 + 扫码支付 QR（无码 ⇒ 整块不出现，**不画假码**）。
 *
 * ## 金额口径（🔴 三条红线，勿随手改）
 *
 * 1. **一切金额取服务端既有字段**：`order.totalAmount` / `order.discountAmount` /
 *    `order.actualAmount` / `item.unitPrice` / `item.amount` —— 前端**不重算**
 *    （重算 = 第二份真值；红证见 `SalesDoc.test.tsx`：服务端字段与前端求和**故意不同**，
 *    纸面必须印服务端那个）。
 * 2. **上期余额 / 预存抵扣 / 账户余额 = 缺口**：服务端**没有**这三个字段
 *    （`Order` DTO 无、`SystemSettings` 无余额面）⇒ 纸面**显式标注**、**绝不编数**
 *    （登记见 {@link SALES_DOC_MONEY_GAPS}）。缺口不是「暂时取不到」，是**还没有口径**。
 * 3. **订货电话**取 `order.customerPhone`（实证 #4 的栏位位置 = 下单电话口径）；
 *    若现场口径实际是「商户订货热线」，该栏取值需现场确认后改 —— 登记在
 *    `docs/design/print-media-matrix.md` 的未核实项，**不猜**。
 *
 * ## 打印隔离（沿用 #4983 / #4965 范式，勿退回旧写法）
 *
 * portal 到 `document.body`；容器带共享标记类 `print-doc`；隔离选择器**恰好**
 * `body > *:not(.print-doc)`；`visibility` 防御**限定本次打印目标**
 * `[data-print-target='sales']`。守卫 = `test_print_doc_convention_guard.py`。
 *
 * ## 与发货链的关系（**未完成项**，如实登记）
 *
 * 用户裁定销售单要「挂在发货链上」= 随货给客户的那张、数量与**实发**同源。
 *
 * **现状（2026-09-26 复核，如实登记）**：`order_shipment_items`（issue #5648 / PR #5664）
 * **已落 main** —— 它是「这一单实际发了多少」的**唯一真值载体**，且该表**owner 声明**
 * 要求 #5651 **只消费**（读 `OrderShipmentService.readShipment`），不得另建第二份投影。
 * 但它今天**只有工人读面**（`/api/worker/shipment/orders/{orderId}`，工人 session 准入），
 * **admin / 桌面端没有读面** ⇒ 本组件（跑在 admin-web）拿不到实发数量。
 * ⇒ 本版数量取**订单行** `order.items[].quantity`（与报价单 / 发货单**同一份**投影，
 * 不是第二套口径）；⛔ **不**自造发货明细表、也**不**照工人读面猜 DTO 形状。
 * 接线 = 新增 admin 端读面（**后端改动**），不在本 PR（纯前端）范围 —— 见
 * `docs/design/print-media-matrix.md` §6。
 */
interface SalesDocProps {
  order: Order
  /**
   * 介质（缺省三联纸 241mm × 140mm）。切介质**只**改版面参数，字段映射只有一份
   * （见文件头「介质是参数，不是副本」）。
   */
  media?: PrintMediaId
  /** 收款码 map；不传 ⇒ 组件在打印时自取（`usePaymentQrcodes`，失败即「无码」） */
  paymentQrcodes?: PaymentQrcodeMap
  /** 本次打印的目标（`'sales'` = 打印本销售单）—— 不加限定会把同页兄弟单据藏掉 */
  printTarget?: PrintTarget | null
  className?: string
}

/**
 * 销售单明细的列（**全仓唯一一份**）：表头与每行都由它渲染 ⇒ 想加/改列只动这里。
 * 守卫 `test_print_media_matrix_guard.py` C5 断言这串有序标签在 `src/**` 里**恰好出现在
 * 一个文件** —— 复制一份到「另一个介质的版本」⇒ 必红（介质是参数，不是副本）。
 */
export const SALES_DOC_COLUMNS = ['序号', '货号', '数量', '单位', '单价', '金额', '备注'] as const

/**
 * 🔴 **服务端未采集**的销售单金额栏（缺口，**不编数**）。
 *
 * 客户实证 #4 的销售单有这三栏，而 MIGAO 今天**没有**它们的口径：
 * `Order` DTO 只有 `totalAmount` / `discountAmount` / `actualAmount`，
 * `SystemSettings` 只有 `companyName` / `logo` / `notificationEnabled` / `code`。
 * ⇒ 纸面以「未采集」显式标注，绝不印 `0.00`（印 0 = 把「没有这个数」画成「余额为零」，
 * 是**编数**）。它们不在主表里，故单独登记成本清单，便于将来口径落地时按清单销账。
 */
export const SALES_DOC_MONEY_GAPS = ['上期余额', '预存抵扣', '账户余额'] as const

/** 纸面缺值占位（**显式**：不静默留空，issue #5651 硬约束） */
export const SALES_DOC_MISSING = '—'
/** 本系统**未采集**的字段标记（与「客户没填」区分开） */
export const SALES_DOC_NOT_COLLECTED = '未采集'

/** 纸面取文本：非空串 / 有限数 ⇒ 原样；其余 ⇒ `fallback`（缺省 `—`） */
function paperText(value: unknown, fallback: string = SALES_DOC_MISSING): string {
  if (typeof value === 'string' && value.trim() !== '') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return fallback
}

/** 金额格式化（含千分位 + 两位小数）。**只做展示格式化，不做任何算术** */
function formatAmount(amount?: number): string {
  return (amount ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatDate(value?: string | null): string | null {
  if (typeof value !== 'string' || value.trim() === '') return null
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : null
}

const PAYMENT_TYPE_LABELS: Record<string, string> = {
  wechat: '微信',
  alipay: '支付宝',
}

export default function SalesDoc({
  order,
  media = 'continuous-241x140',
  paymentQrcodes,
  printTarget,
  className,
}: SalesDocProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const qrcodes = usePaymentQrcodes(paymentQrcodes)

  if (!mounted) return null

  const items = order.items || []
  const continuous = isContinuousFeed(media)
  // 连续纸：容器高度 = 单联可用高度（页长 − 上下边距），超出即裁 —— 绝不跨联
  const sheetHeightMm = continuous ? printUsableHeightMm(media) : null
  const qrEntries = Object.entries(qrcodes)
    .map(([type, qr]) => ({
      type,
      label: PAYMENT_TYPE_LABELS[type] || type,
      imageUrl: resolveImageUrl(qr?.imageUrl),
      payeeName: paperText(qr?.payeeName, ''),
    }))
    .filter((entry) => entry.imageUrl !== '')

  const docNo = paperText(order.orderNo)
  const date = formatDate(order.createdAt)
  const hasDiscount = typeof order.discountAmount === 'number'

  return createPortal(
    <div
      className={cn('sales-print-area print-doc text-neutral-900', className)}
      {...(printTarget === 'sales' ? { 'data-print-target': 'sales' } : {})}
      data-print-media={media}
    >
      <style>{`
        .sales-print-area { display: none; }
        ${printPageRule(media)}
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          .sales-print-area {
            display: block;
            position: static;
            width: 100%;
            font-size: ${printBodyFontPt(media)}pt;
          }
          /* 防御：页面其他组件残留的 "body * { visibility: hidden }" 打印隔离会连同本单据
             一起藏掉 —— 必须显式恢复；⚠️ 限定本次打印目标，否则会把同页的发货单 /
             报价单 / 加工单藏掉（#4965 实测回归）。 */
          .sales-print-area[data-print-target='sales'],
          .sales-print-area[data-print-target='sales'] * { visibility: visible; }
          /* 🔴 连续走纸：单据本体固定为「单联」高度 + overflow:hidden ⇒ 浏览器不会再分页
             （自然分页会让后半截打到下一联 = 跨联错位）。复写三份由压感纸承担，DOM 只有一份。 */
          .sales-sheet { break-inside: avoid; page-break-inside: avoid; }
          .sales-doc-table thead { display: table-header-group; }
          /* 长名截断可见（省略号），不是静默裁掉（issue #5651 硬约束） */
          .sales-cut { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        }
        .sales-cut { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      `}</style>

      {/* 🔴 **一份** .sales-sheet —— 三联纸的复写由纸承担，软件不渲染三遍（issue #5651） */}
      <div
        className="sales-sheet"
        data-testid="sales-sheet"
        style={sheetHeightMm !== null ? { height: `${sheetHeightMm}mm`, overflow: 'hidden' } : undefined}
      >
        {/* ===== ① 表头 ===== */}
        <div className="flex items-baseline justify-between border-b border-neutral-400 pb-1 mb-1">
          <span className="text-base font-semibold tracking-[0.3em]">销售单</span>
          <span className="text-[0.9em] text-neutral-600">
            单号 {docNo}
            {date ? ` · ${date}` : ''}
          </span>
        </div>

        <table className="w-full border-collapse mb-1">
          <tbody>
            <tr>
              <DocCell label="客户" value={order.customerName} testId="sales-customer" cut />
              <DocCell label="电话" value={order.customerPhone} testId="sales-phone" />
            </tr>
            <tr>
              <DocCell label="地址" value={order.customerAddress} colSpan={3} testId="sales-address" cut />
            </tr>
            <tr>
              {/* 订货电话：实证 #4 的栏位位置 = 下单电话口径（见文件头口径 3；现场口径存疑已登记） */}
              <DocCell label="订货电话" value={order.customerPhone} colSpan={3} testId="sales-order-phone" />
            </tr>
          </tbody>
        </table>

        {/* ===== ② 明细：商品行粒度（序号|货号|数量|单位|单价|金额|备注） ===== */}
        <table className="sales-doc-table w-full border-collapse mb-1" style={{ tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <DocTh className="w-[6%]">{SALES_DOC_COLUMNS[0]}</DocTh>
              <DocTh className="w-[20%]">{SALES_DOC_COLUMNS[1]}</DocTh>
              <DocTh align="right" className="w-[9%]">
                {SALES_DOC_COLUMNS[2]}
              </DocTh>
              <DocTh className="w-[8%]">{SALES_DOC_COLUMNS[3]}</DocTh>
              <DocTh align="right" className="w-[13%]">
                {SALES_DOC_COLUMNS[4]}
              </DocTh>
              <DocTh align="right" className="w-[16%]">
                {SALES_DOC_COLUMNS[5]}
              </DocTh>
              <DocTh className="w-[28%]">{SALES_DOC_COLUMNS[6]}</DocTh>
            </tr>
          </thead>
          <tbody data-testid="sales-doc-body">
            {items.length === 0 ? (
              <tr>
                <td
                  className="border border-neutral-400 px-1.5 py-2 text-center text-neutral-500"
                  colSpan={SALES_DOC_COLUMNS.length}
                >
                  该订单暂无商品明细
                </td>
              </tr>
            ) : (
              items.map((item: OrderItem, idx: number) => (
                <tr key={item.id || idx} data-testid={`sales-item-${idx}`}>
                  <DocTd align="right">{idx + 1}</DocTd>
                  {/* 货号：productCode 优先，缺则回落到商品名（两者都缺 ⇒ 显式占位） */}
                  <DocTd cut>{paperText(item.productCode || item.productName)}</DocTd>
                  {/* 数量 / 单价 / 金额**全部取服务端字段**，前端不重算（文件头口径 1） */}
                  <DocTd align="right">{paperText(item.quantity)}</DocTd>
                  {/* 单位：`OrderItem.quantity` 在本系统**恒为米** —— 发货单表头写的就是
                      「数量(米)」、报价单单价写的是「元/米」⇒ 单位取**同一口径**，
                      不新增字段、也不编一个别单位 */}
                  <DocTd>米</DocTd>
                  <DocTd align="right">{formatAmount(item.unitPrice)}</DocTd>
                  <DocTd align="right" testId={`sales-row-amount-${idx}`}>
                    {formatAmount(item.amount)}
                  </DocTd>
                  <DocTd cut>{paperText(item.color, '')}</DocTd>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* ===== ③ 汇总：金额一律读服务端字段；缺口栏显式标注、不编数 ===== */}
        <table className="w-full border-collapse mb-1">
          <tbody>
            <tr>
              <DocCell label="本单总金额" value={formatAmount(order.totalAmount)} testId="sales-total" />
              <DocCell
                label="优惠金额"
                value={hasDiscount ? formatAmount(order.discountAmount) : SALES_DOC_MISSING}
                testId="sales-discount"
              />
            </tr>
            <tr>
              <DocCell
                label="本单应收"
                value={formatAmount(order.actualAmount)}
                testId="sales-total-due"
                strong
              />
              <DocCell
                label="账户余额"
                value={SALES_DOC_NOT_COLLECTED}
                testId="sales-account-balance"
              />
            </tr>
            <tr>
              <DocCell label="上期余额" value={SALES_DOC_NOT_COLLECTED} testId="sales-prev-balance" />
              <DocCell label="预存抵扣" value={SALES_DOC_NOT_COLLECTED} testId="sales-prepay" />
            </tr>
          </tbody>
        </table>
        <div className="text-[0.85em] text-neutral-600 mb-1" data-testid="sales-gap-note">
          注：{SALES_DOC_MONEY_GAPS.join(' / ')} 本系统未采集（纸面标「{SALES_DOC_NOT_COLLECTED}
          」占位，不编数）。
        </div>

        {/* ===== ④ 页脚：温馨提示 + 扫码支付 QR（无码 ⇒ 整块不出现，不画假码） ===== */}
        <div className="flex items-end justify-between gap-3 border-t border-neutral-300 pt-1">
          <div className="min-w-0 text-[0.85em] text-neutral-600">{QUOTATION_FOOTER_NOTICE}</div>
          {qrEntries.length > 0 && (
            <div className="flex shrink-0 items-end gap-2">
              {qrEntries.map((entry) => (
                <div key={entry.type} className="text-center">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={entry.imageUrl}
                    alt={`${entry.label}收款码`}
                    data-testid={`sales-qr-${entry.type}`}
                    className="h-[18mm] w-[18mm] border border-neutral-300 object-contain"
                  />
                  <div className="text-[0.75em] text-neutral-500">{entry.label}</div>
                  {entry.payeeName !== '' && (
                    <div className="text-[0.75em] text-neutral-500">{entry.payeeName}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ========== 打印友好的表格原子（纯边框、无底色，避免打印丢背景） ==========

function DocCell({
  label,
  value,
  colSpan = 1,
  testId,
  cut = false,
  strong = false,
}: {
  label: string
  value?: string | null
  colSpan?: number
  testId?: string
  /** 长值截断**可见**（CSS 省略号）—— 不是静默裁切 */
  cut?: boolean
  strong?: boolean
}) {
  return (
    <>
      <td className="w-16 border border-neutral-400 px-1.5 py-1 whitespace-nowrap text-neutral-500">
        {label}
      </td>
      <td
        colSpan={colSpan}
        data-testid={testId}
        className={cn(
          'border border-neutral-400 px-1.5 py-1',
          cut && 'sales-cut',
          strong && 'font-semibold'
        )}
      >
        {/* 缺值一律显式占位（`—` / 「未采集」）—— 不静默留空（issue #5651 硬约束）：
            空串 / 全空白串同属「没有值」，走同一个 `paperText` 口径 */}
        {paperText(value)}
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
      className={cn(
        'border border-neutral-400 px-1.5 py-1 font-semibold whitespace-nowrap',
        align === 'right' ? 'text-right' : 'text-left',
        className
      )}
    >
      {children}
    </th>
  )
}

function DocTd({
  children,
  align = 'left',
  cut = false,
  testId,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  cut?: boolean
  testId?: string
}) {
  return (
    <td
      data-testid={testId}
      className={cn(
        'border border-neutral-400 px-1.5 py-1 align-top',
        align === 'right' ? 'text-right' : 'text-left',
        cut ? 'sales-cut' : 'break-words'
      )}
    >
      {children}
    </td>
  )
}
