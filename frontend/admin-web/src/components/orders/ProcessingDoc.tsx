'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import dayjs from 'dayjs'
import { QRCodeSVG } from 'qrcode.react'
import { craftSpecRows } from '@/lib/craft-display'
import { printBodyFontPt, printPageRule } from '@/lib/print-media'
import { cn } from '@/lib/utils'
import type { PrintTarget } from './index'
import type { Order, OrderItem, ProcessingOrder } from '@/types'

/**
 * 加工单（可打印纸质文档 · **A4**，issue #5651）—— 照客户现行实物制式（去 PII 后登记在
 * issue #5651 的实证表 #3；用户 2026-09-26 逐字裁定「要做，新增 A4 加工单打印」）。
 *
 * ## 制式（四段，逐条对实证 #3）
 *
 * ① **表头**：订单日期 / 客户 / 电话 / 地址 / 备注 / **制单人** / **单号** / **交付日期** /
 *    **货运**；**右上角一张 QR**（加工单号码，见下「QR 口径」）；
 * ② **正文**：**按套分块** —— 每块段头 `第N套/共M套`，块内一张 8 列表
 *    （{@link PROCESSING_DOC_COLUMNS}：部位 | 部位信息 | 尺寸 | 组件 | 货号 | 用料 | 批号 | 备注）；
 * ③ **分页**：每套 `break-inside: avoid`（不跨页裁切）、`thead` 用
 *    `display: table-header-group`（长单跨页时**表头重复**，否则第二页起认不出列）；
 * ④ **介质来自矩阵**：`@page` 由 `printPageRule('a4')` 生成，**本组件不写 `@page size`**
 *    （见 `lib/print-media.ts`：介质是参数，不是各写一份的副本）。
 *
 * ## 数据口径（三条硬约束，勿随手改）
 *
 * 1. **展示真值单一来源**：「部位」= `processingInfo.curtainType`；「部位信息」= `craftSpecRows()`
 *    的**同一份**真值（设计文档 §4.9「一份 spec，三处渲染」）—— 本组件不另写推导；
 *    `craftSpecRows` 已丢弃缺值行 ⇒ 纸面**绝不**出现 `undefined` / `null` / `NaN`。
 * 2. 🔴 **缺值不许静默留空**（issue #5651 硬约束）：一律显式占位 `—`；
 *    **本系统没有采集**的字段（制单人 / 批号）另标「未采集」并出一行脚注 ——
 *    二者必须可区分：「客户没填」与「我们没有这个字段」不是一回事（同族判据：
 *    洗水码「静默裁切 = 账实不符的另一种形态」）。
 *    ⚠️ 实测依据：`ProcessingOrderItem`（加工单快照明细）**没有** `batchNo` 列
 *    （`batchNo` 属入库 / 库存批次域），`Order` DTO 也**没有**制单人列 ⇒ 两者是**缺口**，
 *    不是「暂时取不到」。登记在 `docs/design/print-media-matrix.md` 的未核实项。
 * 3. **金额一律不前端现算**：本单据**不印金额**（客户实证 #3 的加工单没有金额列）⇒
 *    天然没有第二份金额真值。加工费口径只在报价单 / 发货单走 `lib/order-amount.ts`。
 *
 * ## 打印隔离（沿用 #4983 / #4965 范式，勿退回旧写法）
 *
 * - 屏幕隐藏、打印可见；portal 到 `document.body` 的直接子级；
 * - 容器带共享标记类 `print-doc`，隔离选择器**恰好**是 `body > *:not(.print-doc)`
 *   （按「自己那一份」写会把同页的兄弟单据整份藏掉，实测过）；
 * - `visibility` 防御**限定本次打印目标** `[data-print-target='processing']`
 *   （不加限定会同特异性覆盖兄弟单据）；
 * - 守卫 = `tests/unit_ci_workflows/test_print_doc_convention_guard.py`。
 *
 * ## QR 口径
 *
 * QR 内容由调用方给（`qrValue`）。**缺码不画假码**（洗水码既有判据）：拿不到值 ⇒ 出一个
 * 虚线占位框 + 「无码」字样，**不**编一个码、也不拿别的串顶替。
 */
interface ProcessingDocProps {
  order: Order
  /** 加工单（订单详情页已加载；缺省 ⇒ 单号回落订单号、交付日期回落要求到货日） */
  processingOrder?: ProcessingOrder | null
  /** 右上 QR 的内容；调用方给不出 ⇒ `null`（出占位框，不画假码） */
  qrValue?: string | null
  /**
   * 本次打印的目标（`'processing'` = 打印本加工单）。**只在为 `'processing'` 时**置位
   * `data-print-target` —— 否则会把同页的发货单 / 报价单 / 销售单重新藏掉（#4965 实测回归）。
   */
  printTarget?: PrintTarget | null
  className?: string
}

/**
 * 加工单正文的列（**全仓唯一一份**，issue #5651 的「同一单据不许有第二份字段映射」）：
 * 表头由它渲染 ⇒ 想加/改列只动这里。守卫 `test_print_media_matrix_guard.py` C5 断言这串
 * 有序标签在 `src/**` 里**恰好出现在一个文件**（复制一份到别的介质变体 ⇒ 必红）。
 */
export const PROCESSING_DOC_COLUMNS = [
  '部位',
  '部位信息',
  '尺寸',
  '组件',
  '货号',
  '用料',
  '批号',
  '备注',
] as const

/** 纸面缺值占位（**显式**：不静默留空） */
export const MISSING = '—'
/** 本系统**未采集**的字段标记（与「客户没填」区分开） */
export const NOT_COLLECTED = '未采集'
/** 本系统未采集、但客户实证制式里有的字段（纸面显式标注，**不编数**） */
export const PROCESSING_DOC_NOT_COLLECTED_FIELDS = ['制单人', '批号'] as const

/** 纸面取文本：非空串 / 有限数 ⇒ 原样；其余 ⇒ `fallback`（缺省 `—`，绝不静默留空） */
export function paperText(value: unknown, fallback: string = MISSING): string {
  if (typeof value === 'string' && value.trim() !== '') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return fallback
}

function formatDate(value?: string | null): string | null {
  if (typeof value !== 'string' || value.trim() === '') return null
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : null
}

export default function ProcessingDoc({
  order,
  processingOrder,
  qrValue,
  printTarget,
  className,
}: ProcessingDocProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (!mounted) return null

  const items = order.items || []
  const docNo = paperText(processingOrder?.processingOrderNo ?? order.orderNo)
  // 交付日期：加工单的交期优先，缺则回落到订单的「要求到货日」（#5177）—— 都是服务端字段
  const delivery = formatDate(processingOrder?.expectedDeliveryDate ?? order.requiredDeliveryDate)
  const orderDate = formatDate(order.createdAt)
  // 货运：物流方式 + 物流公司（与报价单同一口径；两者都缺 ⇒ 显式占位）
  const freight = [order.logisticsType, order.logisticsCompany]
    .map((value) => (typeof value === 'string' ? value.trim() : ''))
    .filter((value) => value !== '')
    .join(' · ')

  return createPortal(
    <div
      className={cn('processing-print-area print-doc text-neutral-900', className)}
      data-print-media="a4"
      {...(printTarget === 'processing' ? { 'data-print-target': 'processing' } : {})}
    >
      <style>{`
        .processing-print-area { display: none; }
        ${printPageRule('a4')}
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          .processing-print-area {
            display: block;
            position: static;
            width: 100%;
            font-size: ${printBodyFontPt('a4')}pt;
          }
          /* 防御：页面其他组件残留的 "body * { visibility: hidden }" 打印隔离会连同本单据
             一起藏掉（补打纸面空白）—— 必须显式恢复；⚠️ 限定本次打印目标，否则会把同页的
             发货单 / 报价单 / 销售单藏掉（#4965 实测回归）。 */
          .processing-print-area[data-print-target='processing'],
          .processing-print-area[data-print-target='processing'] * { visibility: visible; }
          /* ③ 分页：每套一块、不跨页裁切；表头在每一页重复（长单第二页起仍认得出列） */
          .processing-set { break-inside: avoid; page-break-inside: avoid; }
          .processing-doc-table thead { display: table-header-group; }
          .processing-doc-table tr { break-inside: avoid; page-break-inside: avoid; }
        }
      `}</style>

      {/* ===== ① 表头（左：9 栏；右上：QR） ===== */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-center text-xl font-semibold tracking-[0.5em] mb-1">加工单</div>
          <table className="w-full border-collapse mb-2">
            <tbody>
              <tr>
                <DocCell label="订单日期" value={orderDate} />
                <DocCell label="单号" value={docNo} />
              </tr>
              <tr>
                <DocCell label="客户" value={order.customerName} />
                <DocCell label="电话" value={order.customerPhone} />
              </tr>
              <tr>
                <DocCell label="地址" value={order.customerAddress} colSpan={3} />
              </tr>
              <tr>
                <DocCell label="交付日期" value={delivery} />
                <DocCell
                  label="制单人"
                  value={paperText(null, NOT_COLLECTED)}
                  testId="processing-doc-creator"
                />
              </tr>
              <tr>
                <DocCell label="货运" value={freight} colSpan={3} />
              </tr>
              {paperText(order.remark, '') !== '' && (
                <tr>
                  <DocCell label="备注" value={order.remark} colSpan={3} />
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 右上 QR：**缺码不画假码**（洗水码既有判据）—— 拿不到值就出虚线占位框 */}
        <div className="shrink-0 text-center">
          {qrValue ? (
            <QRCodeSVG value={qrValue} size={64} level="M" title={qrValue} data-testid="processing-doc-qr" />
          ) : (
            <div
              data-testid="processing-doc-qr-placeholder"
              className="flex h-[22mm] w-[22mm] items-center justify-center border border-dashed border-neutral-400 text-center text-[7pt] text-neutral-500"
            >
              无码
            </div>
          )}
          <div className="text-[7pt] text-neutral-500 mt-0.5">{docNo}</div>
        </div>
      </div>

      {/* ===== ② 正文：按套分块（每块一张 8 列表） ===== */}
      {items.length === 0 ? (
        <div className="border border-neutral-400 px-2 py-3 text-center text-neutral-500">
          该订单暂无商品明细，无加工内容可打印
        </div>
      ) : (
        items.map((item: OrderItem, idx: number) => (
          <SetBlock key={item.id || idx} item={item} index={idx} total={items.length} />
        ))
      )}

      {/* 缺口脚注：把「我们没有这个字段」写在纸面上，免得被读成「客户没填」 */}
      <div className="mt-2 text-[7pt] text-neutral-600" data-testid="processing-doc-gap-note">
        说明：{PROCESSING_DOC_NOT_COLLECTED_FIELDS.join(' / ')} 本系统未采集（纸面标「
        {NOT_COLLECTED}」占位，不编数）。
      </div>
    </div>,
    document.body
  )
}

// ========== 每套（= 每个商品行）一段 ==========

function SetBlock({ item, index, total }: { item: OrderItem; index: number; total: number }) {
  const info = (item.processingInfo ?? {}) as Record<string, unknown>
  const part = paperText(info.curtainType, '')
  // 部位信息 = craftSpecRows 的同一份真值（§4.9）；排除「部位」行（它已有自己的列，
  // 重复印同一真值只是噪音 —— 与报价单同一处理）
  const specRows = craftSpecRows(item.processingInfo).filter((row) => row.label !== '部位')
  const infoText = specRows.map((row) => `${row.label}：${row.value}`).join('\n')
  const width = typeof item.width === 'number' && Number.isFinite(item.width) ? item.width : null
  const height = typeof item.height === 'number' && Number.isFinite(item.height) ? item.height : null
  // 尺寸：两边都是有限数才出（半个尺寸没有意义）
  const size = width !== null && height !== null ? `${width}×${height}` : ''
  // 组件：面料行 = componentRole（缺省即主布）
  const componentRole = paperText(info.componentRole, '主布')
  // 货号 = productCode + colorName（各自缺则只印有的那个）
  const code = [item.productCode, info.colorName]
    .map((value) => (typeof value === 'string' ? value.trim() : ''))
    .filter((value) => value !== '')
    .join(' ')
  // 用料 = 该行数量（米）；缺 ⇒ 显式占位
  const meters = typeof item.quantity === 'number' && Number.isFinite(item.quantity) ? String(item.quantity) : MISSING
  const remark = paperText(item.specification, '')

  return (
    <div className="processing-set mb-3" data-testid={`processing-doc-set-${index}`}>
      <div className="font-semibold mb-1">
        第{index + 1}套/共{total}套
        {part !== '' && <span className="ml-2 text-neutral-600">部位：{part}</span>}
      </div>
      {/* table-layout: fixed —— 列宽由表头声明的百分比决定（auto 布局按内容分配，
          长工艺文案会把列撑歪，纸面每单都可能不一样） */}
      <table className="processing-doc-table w-full border-collapse" style={{ tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <DocTh className="w-[8%]">{PROCESSING_DOC_COLUMNS[0]}</DocTh>
            <DocTh className="w-[26%]">{PROCESSING_DOC_COLUMNS[1]}</DocTh>
            <DocTh className="w-[11%]">{PROCESSING_DOC_COLUMNS[2]}</DocTh>
            <DocTh className="w-[9%]">{PROCESSING_DOC_COLUMNS[3]}</DocTh>
            <DocTh className="w-[14%]">{PROCESSING_DOC_COLUMNS[4]}</DocTh>
            <DocTh align="right" className="w-[8%]">
              {PROCESSING_DOC_COLUMNS[5]}
            </DocTh>
            <DocTh className="w-[10%]">{PROCESSING_DOC_COLUMNS[6]}</DocTh>
            <DocTh className="w-[14%]">{PROCESSING_DOC_COLUMNS[7]}</DocTh>
          </tr>
        </thead>
        <tbody>
          <tr>
            <DocTd>{part || MISSING}</DocTd>
            <DocTd>{infoText || MISSING}</DocTd>
            <DocTd>{size || MISSING}</DocTd>
            <DocTd>{componentRole}</DocTd>
            <DocTd>{code || MISSING}</DocTd>
            <DocTd align="right">{meters}</DocTd>
            {/* 🔴 批号：`ProcessingOrderItem`（加工单快照明细）**没有**该列 ⇒ 显式标「未采集」，
                绝不编一个批号、也不留空（见文件头第 2 条） */}
            <DocTd testId="processing-doc-batch">{NOT_COLLECTED}</DocTd>
          </tr>
          {remark !== '' && (
            <tr>
              <DocTd>{''}</DocTd>
              <DocTd colSpan={7}>{`备注：${remark}`}</DocTd>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ========== 打印友好的表格原子（纯边框、无底色，避免打印丢背景） ==========

function DocCell({
  label,
  value,
  colSpan = 1,
  testId,
}: {
  label: string
  value?: string | null
  colSpan?: number
  testId?: string
}) {
  return (
    <>
      <td className="border border-neutral-400 px-2 py-1.5 w-20 text-neutral-500 whitespace-nowrap">
        {label}
      </td>
      {/* 缺值一律显式占位（`—` / 「未采集」）—— 不静默留空（issue #5651 硬约束） */}
      <td className="border border-neutral-400 px-2 py-1.5 break-words" colSpan={colSpan} data-testid={testId}>
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
  colSpan,
  testId,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  colSpan?: number
  testId?: string
}) {
  return (
    <td
      colSpan={colSpan}
      data-testid={testId}
      className={cn(
        'border border-neutral-400 px-1.5 py-1 align-top break-words whitespace-pre-line',
        align === 'right' ? 'text-right' : 'text-left'
      )}
    >
      {children}
    </td>
  )
}
