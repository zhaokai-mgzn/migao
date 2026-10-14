'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import dayjs from 'dayjs'
import { QRCodeSVG } from 'qrcode.react'
import { freightText } from '@/lib/logistics'
import { orderItemQuantity, orderItemSku, quantityWithUnit } from '@/lib/order-item-sku'
// 工序显示名的**唯一**口径（issue #4621）：纸面**不得**直接渲染工人端变体名（`operation`）
import { operationDisplayName } from '@/lib/operation-display'
// 工序清单的索引 / 状态文案（issue #6901）：与商家端加工单块**同一份**实现
import { operationStatusText, operationsByItem } from '@/lib/operation-list'
import { printBodyFontPt, printPageRule } from '@/lib/print-media'
import { cn } from '@/lib/utils'
import type { PrintTarget } from './index'
import type {
  Order,
  OrderItem,
  ProcessingOrder,
  ProcessingOrderItem,
  ProductionPosition,
} from '@/types'

/**
 * 加工单（可打印纸质文档 · **A4**，issue #5651）—— 照客户现行实物制式（去 PII 后登记在
 * issue #5651 的实证表 #3；用户 2026-09-26 逐字裁定「要做，新增 A4 加工单打印」）。
 *
 * ## 制式（四段，逐条对实证 #3）
 *
 * ① **表头**：订单日期 / 客户 / 电话 / 地址 / 备注 / **制单人** / **单号** / **交付日期** /
 *    **货运**；**右上角一张 QR**（加工单号码，见下「QR 口径」）；
 * ② **正文**：**按套分块** —— 每块段头 `第N套/共M套`，块内一张 9 列表
 *    （{@link PROCESSING_DOC_COLUMNS}：品名 | 货号 | 颜色 | 门幅 | 尺寸 | 数量 | 组件 | 批号 | 备注）
 *    ＋ 一行「工艺：…」（原「部位信息」列的内容，issue #6869）
 *    ＋ 一块「工序清单」（issue #6901，见下「工序清单口径」）；
 *    品名 / 货号 / 颜色 / 门幅 取 `lib/order-item-sku.ts` 的 `orderItemSku()`；
 * ③ **分页**：每套 `break-inside: avoid`（不跨页裁切）、`thead` 用
 *    `display: table-header-group`（长单跨页时**表头重复**，否则第二页起认不出列）；
 * ④ **介质来自矩阵**：`@page` 由 `printPageRule('a4')` 生成，**本组件不写 `@page size`**
 *    （见 `lib/print-media.ts`：介质是参数，不是各写一份的副本）。
 *
 * ## 数据口径（三条硬约束，勿随手改）
 *
 * 1. **展示真值单一来源**：品名 / 货号 / 颜色 / 门幅 取 `lib/order-item-sku.ts` 的
 *    `orderItemSku(item)`（货号真字段是响应里的 `skuCode`；原先读的 `productCode` **不在响应里**
 *    ⇒ 纸面货号恒空，issue #6869 的根因）；「工艺」= `craftSpecRows()` 的**同一份**真值
 *    （设计文档 §4.9「一份 spec，三处渲染」）—— 本组件不另写推导；
 *    「部位」（`curtainType`）**保留在工艺说明里**：issue #4521 移除录入面后它只有纱帘行才有值，
 *    独立成列（旧「部位」列 / 段头「部位：…」）时恒空；
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
 * ## 工序清单口径（issue #6901 —— 工人要按它决定「这张单要做哪几道」）
 *
 * 用户逐字「加工单缺乏订单中的规格尺寸和加工信息，工人需要这些信息+商品信息来决定如何生产」
 * ⇒ 纸面补**逐道工序**：显示名（{@link OPERATIONS_DOC_COLUMNS}）/ 单位 / 应做数量 / 状态。
 * - **取数**：调用方把既有读面 `GET /api/admin/production/orders/{id}/operations`
 *   （`ProductionService#operationView` 的 `positions[].operations[]`）原样传进来
 *   （`operations` prop）—— 本组件**不重算工序、不新造端点、不新造第二份取数**；
 * - **显示名**一律走仓内唯一口径 `lib/operation-display.ts::operationDisplayName()`
 *   （底表已按部位分块 ⇒ 传 `{ logical_name }` 只取逻辑名，不再拼一遍部位）；
 * - **按套对齐**：`position.order_item_id` = 订单行 id（与洗水码/批号**同一把钥匙**）；
 *   对不上 / 该套没有工序实例（订单还没生成加工单）⇒ **整块不出现**（不印空表、不印占位表头）；
 * - **分页**：工序行与明细表同属 `.processing-set`（`break-inside: avoid`）⇒ 不跨页裁切。
 *
 * ## 数量列的单位（issue #6901）
 *
 * 列名原先写死「数量(米)」，而 `quantity` 的单位可能是米/件/套（`OrderItem.unit`）
 * ⇒ **同一行**里列名与值都来自 `lib/order-item-sku.ts::orderItemQuantity()`，
 * 两处不会各写一份（口径收敛在一处）。
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
 * ## QR 口径（issue #6867 起）
 *
 * QR 内容由调用方给（`qrValue`）—— 现在是**加工单级稳定短链** `{base}/o/{短码}`
 * （设计 §11.3：调用方传 `processingOrder.scan_url ?? null`，**不再回落加工单号**；
 * 回落就退回「扫出来只有一串文本」的旧形态）。**前端不拼 URL**（base 是服务端真值）。
 * **缺码不画假码**（洗水码既有判据）：拿不到值 ⇒ 出一个虚线占位框 + 「无码」字样，
 * **不**编一个码、也不拿别的串顶替。
 * 纸面**再印一行人可读短码**（`processingOrder.short_code`，见 `processing-doc-short-code`）
 * —— 设计 §11.7「人可读短码**不是可选项**」：扫码失败 / 相机权限被拒 / 无扫码工具时，
 * 工人手输它 = 扫码（§11.4 的解析形态之一）；缺码印 `—`、**绝不编造**。
 * ⚠️ 上一版这里印的是单号（`docNo`）—— 单号已在表头「单号」格，同纸不重复印同一真值。
 */
interface ProcessingDocProps {
  order: Order
  /** 加工单（订单详情页已加载；缺省 ⇒ 单号回落订单号、交付日期回落要求到货日） */
  processingOrder?: ProcessingOrder | null
  /** 右上 QR 的内容（**加工单级稳定短链** `{base}/o/{短码}`，issue #6867）；调用方给不出 ⇒ `null`（出占位框，不画假码） */
  qrValue?: string | null
  /**
   * 本订单的**工序清单**（既有读面 `GET /api/admin/production/orders/{id}/operations` 的
   * `positions[]`，issue #6901）。调用方原样传 —— 本组件**不取数、不重算**。
   * 缺省 / 空 / 该套没有工序实例（订单还没生成加工单）⇒ 工序块**整块不出现**。
   */
  operations?: ProductionPosition[] | null
  /**
   * 本次打印的目标（`'processing'` = 打印本加工单）。**只在为 `'processing'` 时**置位
   * `data-print-target` —— 否则会把同页的发货单 / 报价单 / 销售单重新藏掉（#4965 实测回归）。
   */
  printTarget?: PrintTarget | null
  /**
   * **原地渲染**（`true`）而不是 portal 到 `document.body`（issue #5914）—— 只有**打印预览层**
   * 用它：预览要把**同一份单据**摆进真尺寸纸框里，portal 会让它跑到框外（且屏幕态仍是 `display:none`）。
   * 缺省 `false` = 既有行为（portal 到 body，屏幕上隐藏、仅打印呈现）。
   */
  inline?: boolean
  className?: string
}

/**
 * 加工单正文的列（**全仓唯一一份**，issue #5651 的「同一单据不许有第二份字段映射」）：
 * 表头由它渲染 ⇒ 想加/改列只动这里。守卫 `test_print_media_matrix_guard.py` C5 断言这串
 * 有序标签在 `src/**` 里**恰好出现在一个文件**（复制一份到别的介质变体 ⇒ 必红）。
 */
export const PROCESSING_DOC_COLUMNS = [
  '品名',
  '货号',
  '颜色',
  '门幅',
  '尺寸',
  '数量',
  '组件',
  '批号',
  '备注',
] as const

/**
 * 工序清单块的列（issue #6901）—— 与 `PROCESSING_DOC_COLUMNS` **不是**同一串标签
 * ⇒ 打印介质守卫 C5（「每个单据的列清单在 `src/**` 里恰好命中一个文件」）不受影响。
 */
export const OPERATIONS_DOC_COLUMNS = ['工序', '名称', '应做', '状态'] as const

/** 工序主列（显示名）占的细列数：其余两列各占 1（合计 = 表头 9 列，issue #6595 的列数不变量） */
const OPERATIONS_NAME_SPAN = PROCESSING_DOC_COLUMNS.length - (OPERATIONS_DOC_COLUMNS.length - 1)

/**
 * 工序清单的索引 / 状态文案（issue #6901）**在本模块转出**：纸面单据的公开面就是本文件，
 * 消费方（`ProcessingOrderBlock`、各单据测试）从**同一处**取，不各自 import 两份路径。
 * 实现只有一份 = `frontend/admin-web/src/lib/operation-list.ts`。
 */
export { operationsByItem, operationStatusText } from '@/lib/operation-list'

/** 纸面缺值占位（**显式**：不静默留空） */
export const MISSING = '—'
/** 本系统**未采集**的字段标记（与「客户没填」区分开） */
export const NOT_COLLECTED = '未采集'
/**
 * 本系统**未采集**、但客户实证制式里有的字段（纸面显式标注，**不编数**）。
 *
 * 🔴 **现在是空的**（2026-10-01，issue #5914）：原先登记的「制单人 / 批号」两条**已经落地**，
 * 纸面必须印**真值** —— 继续标「未采集」= 把「系统有」说成「系统没有」（纸面在说假话）：
 * - 制单人：`orders.created_by_name`（V142 / issue #5835 起建单时写入）⇒ 读 `order.createdByName`；
 * - 批号：加工单快照键 `batchNo`（`stampAssignedBatches` 指派批次时写入）⇒ 读快照行的 `batchNo`。
 *
 * 两者**缺值**时纸面印 `—`（= 客户没填 / 未指派），与「我们没有这个字段」是两件事。
 * 将来新增真缺口**登记进本清单**（纸面标「未采集」）。
 */
export const PROCESSING_DOC_NOT_COLLECTED_FIELDS: readonly string[] = []

/**
 * 快照行 id 的读取口（与洗水码**同一口径**）：后端 `buildSnapshot` 无条件落 `itemId`
 * （= `order_items.id`），用它把**快照行**与订单商品行对齐；对不上 ⇒ 该行不猜（印 `—`）。
 */
type SnapshotRow = ProcessingOrderItem & { itemId?: string }

function snapshotIndex(processingOrder?: ProcessingOrder | null): Map<string, ProcessingOrderItem> {
  const index = new Map<string, ProcessingOrderItem>()
  for (const row of processingOrder?.items ?? []) {
    const id = (row as SnapshotRow).itemId
    if (id) index.set(id, row)
  }
  return index
}

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
  operations,
  printTarget,
  inline,
  className,
}: ProcessingDocProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (!mounted) return null

  const items = order.items || []
  // 制单人 = 服务端真值（`orders.created_by_name`）；缺值 = 存量单 / 匿名下单（**不是**「没这个字段」）
  const creator = paperText(order.createdByName)
  // 批号 = 加工单**快照**行的 `batchNo`（按 `itemId` 与商品行对齐；对不上 ⇒ 该行不猜）
  const snapshots = snapshotIndex(processingOrder)
  // 工序清单按 `order_item_id`（= 订单行 id）索引 —— 与洗水码 / 批号**同一把钥匙**（issue #6901）
  const operationsIndex = operationsByItem(operations)
  const docNo = paperText(processingOrder?.processingOrderNo ?? order.orderNo)
  // 交付日期：加工单的交期优先，缺则回落到订单的「要求到货日」（#5177）—— 都是服务端字段
  const delivery = formatDate(processingOrder?.expectedDeliveryDate ?? order.requiredDeliveryDate)
  const orderDate = formatDate(order.createdAt)
  // 货运：物流方式 + 物流公司（与报价单**同一份**实现）。两者都缺 ⇒ 显式占位。
  // 🔴 issue #6869：原先**原样拼**后端枚举 ⇒ 纸面印出 `express · 顺丰速运`
  // （用户逐字「不要用英文，人家看不懂」）。
  const freight = freightText(order.logisticsType, order.logisticsCompany)

  const doc = (
    <div
      className={cn('processing-print-area print-doc text-neutral-900', className)}
      data-print-sheet
      data-print-media="a4"
      {...(printTarget === 'processing' ? { 'data-print-target': 'processing' } : {})}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。实测（真实 Chromium）：
          订单详情页点「打印发货单」会按销售单的三联纸（241×140）出纸 ⇒ 打废纸。 */}
      {printTarget === 'processing' && <style>{printPageRule('a4')}</style>}
      <style>{`
        .processing-print-area { display: none; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          /* 🔴 只有「本次目标」上纸（issue #5914）—— 非目标单据不占版面、不抢纸型。 */
          .processing-print-area[data-print-target='processing'] {
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
                <DocCell label="制单人" value={creator} testId="processing-doc-creator" />
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
          {/* 🔴 人可读短码（issue #6867，设计 §11.7「不是可选项」）：扫码失败 / 相机权限被拒 /
              手上没有扫码工具时，工人**手输它 = 扫码**（§11.4 的四形态解析）。
              取值 = `processingOrder.short_code`（服务端真值）—— 缺码印 `—`、**绝不编造**，
              与上面「缺码不画假码」同一口径（别拿 `docNo` / 订单号顶上去：那会印出一个**扫不开也输不进**的码）。
              形态照 `TaskCardPrint` 的 `task-card-label-short-code-*`（同款范式）。
              ⚠️ 上一版这里印的是 `docNo` —— 而单号早在表头「单号」格印过（同纸不重复印同一真值）。 */}
          <div
            className="mt-0.5 font-mono text-[8pt] font-bold"
            data-testid="processing-doc-short-code"
          >
            {paperText(processingOrder?.short_code)}
          </div>
        </div>
      </div>

      {/* ===== ② 正文：按套分块（每块一张 8 列表） ===== */}
      {items.length === 0 ? (
        <div className="border border-neutral-400 px-2 py-3 text-center text-neutral-500">
          该订单暂无商品明细，无加工内容可打印
        </div>
      ) : (
        items.map((item: OrderItem, idx: number) => (
          <SetBlock
            key={item.id || idx}
            item={item}
            snapshot={item.id ? snapshots.get(item.id) : undefined}
            operations={item.id ? operationsIndex.get(item.id) : undefined}
            index={idx}
            total={items.length}
          />
        ))
      )}

      {/* 缺口脚注：把「我们没有这个字段」写在纸面上，免得被读成「客户没填」。
          🔴 清单为空（= 已无缺口）时**整块不出现** —— 一句「没有缺口」的脚注只是在占纸面。 */}
      {PROCESSING_DOC_NOT_COLLECTED_FIELDS.length > 0 && (
        <div className="mt-2 text-[7pt] text-neutral-600" data-testid="processing-doc-gap-note">
          说明：{PROCESSING_DOC_NOT_COLLECTED_FIELDS.join(' / ')} 本系统未采集（纸面标「
          {NOT_COLLECTED}」占位，不编数）。
        </div>
      )}
    </div>
  )

  // 🔴 预览层里**不 portal**（issue #5914）：同一份单据要摆进真尺寸纸框，portal 会跑到框外
  return inline ? doc : createPortal(doc, document.body)
}

// ========== 每套（= 每个商品行）一段 ==========

/** 列位（按 {@link PROCESSING_DOC_COLUMNS} 的顺序取，**不写魔数** —— 列序调整时这里会一起错） */
const COL_QUANTITY = PROCESSING_DOC_COLUMNS.indexOf('数量')
const COL_BATCH = PROCESSING_DOC_COLUMNS.indexOf('批号')

function SetBlock({
  item,
  snapshot,
  operations,
  index,
  total,
}: {
  item: OrderItem
  /** 该商品行对应的加工单**快照行**（批号从这里读；对不上 ⇒ `undefined`，不猜） */
  snapshot?: ProcessingOrderItem
  /** 该商品行的**工序实例**（读面 `positions[]` 里 `order_item_id` 命中的那一组；无 ⇒ 工序块不出现） */
  operations?: ProductionPosition
  index: number
  total: number
}) {
  const info = (item.processingInfo ?? {}) as Record<string, unknown>
  // 商品身份（品名 / 货号 / 颜色 / 门幅）—— **唯一**取值口，见文件头第 1 条
  const sku = orderItemSku(item)
  // 工艺说明 = craftSpecRows 的同一份真值（§4.9）—— 「门幅」已由 orderItemSku 排除（有独立的列）；
  // ⚠️ 「部位」（curtainType）**保留**在这里：issue #4521 移除录入面后它只有纱帘行才有值，
  // 旧「部位」列/段头「部位：…」对普通订单恒空（用户原话「报价单展示部位是啥意思」）。
  const craftText = sku.specRows.map((row) => `${row.label}：${row.value}`).join('；')
  const width = typeof item.width === 'number' && Number.isFinite(item.width) ? item.width : null
  const height = typeof item.height === 'number' && Number.isFinite(item.height) ? item.height : null
  // 尺寸：两边都是有限数才出（半个尺寸没有意义）
  const size = width !== null && height !== null ? `${width}×${height}` : ''
  // 组件：面料行 = componentRole（缺省即主布）
  const componentRole = paperText(info.componentRole, '主布')
  // 数量 + 单位（issue #6901）：**一个**取值口（`lib/order-item-sku.ts`）同时喂「列名」与「值」——
  // 原先列名写死「数量(米)」而 `quantity` 的单位可能是件/套（快照行 `unit`）
  // ⇒ 同一行里列名与值各说一份单位。缺值 ⇒ 显式占位 `—`（不静默留空）。
  const quantity = orderItemQuantity({ quantity: item.quantity, unit: snapshot?.unit })
  // 列名按本行的单位：有单位 ⇒ `数量(米)`，没采集到 ⇒ 只写 `数量`（**不编「米」**）
  const quantityLabel = quantity.unit
    ? `${PROCESSING_DOC_COLUMNS[COL_QUANTITY]}(${quantity.unit})`
    : PROCESSING_DOC_COLUMNS[COL_QUANTITY]
  // 工序清单（issue #6901）：**逐道**印显示名 / 应做 / 状态；空 ⇒ `operationsRow` 为 null ⇒ 整块不出现
  const operationsRows = (operations?.operations ?? []).map((op, i) => (
    <tr key={op.id ?? i} data-testid="processing-doc-operation">
      <DocTd colSpan={OPERATIONS_NAME_SPAN} testId="processing-doc-operation-name">
        {paperText(operationDisplayName(op), MISSING)}
      </DocTd>
      <DocTd testId="processing-doc-operation-qty">
        {quantityWithUnit({ quantity: op.qty, unit: op.unit }) || MISSING}
      </DocTd>
      <DocTd testId="processing-doc-operation-status">{operationStatusText(op.status)}</DocTd>
    </tr>
  ))

  return (
    <div className="processing-set mb-3" data-testid={`processing-doc-set-${index}`}>
      <div className="font-semibold mb-1">
        第{index + 1}套/共{total}套
      </div>
      {/* table-layout: fixed —— 列宽由表头声明的百分比决定（auto 布局按内容分配，
          长工艺文案会把列撑歪，纸面每单都可能不一样） */}
      <table className="processing-doc-table w-full border-collapse" style={{ tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <DocTh className="w-[16%]">{PROCESSING_DOC_COLUMNS[0]}</DocTh>
            <DocTh className="w-[11%]">{PROCESSING_DOC_COLUMNS[1]}</DocTh>
            <DocTh className="w-[8%]">{PROCESSING_DOC_COLUMNS[2]}</DocTh>
            <DocTh className="w-[7%]">{PROCESSING_DOC_COLUMNS[3]}</DocTh>
            <DocTh className="w-[10%]">{PROCESSING_DOC_COLUMNS[4]}</DocTh>
            <DocTh align="right" className="w-[11%]">
              {quantityLabel}
            </DocTh>
            <DocTh className="w-[8%]">{PROCESSING_DOC_COLUMNS[6]}</DocTh>
            <DocTh className="w-[17%]">{PROCESSING_DOC_COLUMNS[7]}</DocTh>
            <DocTh className="w-[12%]">{PROCESSING_DOC_COLUMNS[8]}</DocTh>
          </tr>
        </thead>
        <tbody>
          <tr>
            <DocTd>{sku.name || MISSING}</DocTd>
            <DocTd>{sku.code || MISSING}</DocTd>
            <DocTd>{sku.color || MISSING}</DocTd>
            <DocTd>{sku.doorWidth || MISSING}</DocTd>
            <DocTd>{size || MISSING}</DocTd>
            <DocTd align="right">{quantity.quantity ?? MISSING}</DocTd>
            <DocTd>{componentRole}</DocTd>
            {/* 批号 = 快照行的 `batchNo`（指派批次时写入）。缺值印 `—`（= 未指派），
                与「我们没有这个字段」是两件事（issue #5914；登记见 PROCESSING_DOC_NOT_COLLECTED_FIELDS） */}
            <DocTd testId="processing-doc-batch">{paperText(snapshot?.batchNo)}</DocTd>
            {/* 备注 = 商家手写的**行级备注**（`processingInfo.remark`，issue #5685「这个数字怎么来的」
                —— 车间要按它核算法）。缺值**留空**（纸面留白供手写）。 */}
            <DocTd>{paperText(info.remark, '')}</DocTd>
          </tr>
          {/* 工艺说明行：整行承载原「部位信息」列（issue #6869）；首格 = 行标签「工艺」。
              🔴 整行必须占满 9 列（1 + `colSpan` 8）—— 少一格 ⇒ 那一列在数据行没有单元格、
              也就没有边框（issue #6595 实测形态）。 */}
          {craftText !== '' && (
            <tr>
              <DocTd>工艺</DocTd>
              <DocTd colSpan={8}>{craftText}</DocTd>
            </tr>
          )}
          {/* 工序清单（issue #6901）：**这一套要做哪几道** —— 显示名 / 应做（数量+单位）/ 状态。
              🔴 整块由 `operationsRows.length > 0` 决定：无工序实例（订单还没生成加工单 /
              该行对不上 `order_item_id`）⇒ **整块不出现**（不印空表、不印占位表头）。
              行标签 + 子表头 + 每道一行：整行占满 9 列（1 + colSpan 8，issue #6595 的列数不变量）。 */}
          {operationsRows.length > 0 && (
            <>
              <tr data-testid="processing-doc-operations">
                <DocTd>{OPERATIONS_DOC_COLUMNS[0]}</DocTd>
                <DocTd colSpan={OPERATIONS_NAME_SPAN}>{OPERATIONS_DOC_COLUMNS[1]}</DocTd>
                <DocTd align="right">{OPERATIONS_DOC_COLUMNS[2]}</DocTd>
                <DocTd>{OPERATIONS_DOC_COLUMNS[3]}</DocTd>
              </tr>
              {operationsRows}
            </>
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
