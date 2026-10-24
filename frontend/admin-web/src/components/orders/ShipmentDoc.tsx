'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Order, OrderItem, LogisticsInfo, OrderProcessingItem } from '@/types'
import type { PrintTarget } from './index'
import { printBodyFontPt, printContentInsetCss, printPageRule } from '@/lib/print-media'
import { useCompanyName } from '@/lib/use-company-name'
import { orderItemSku } from '@/lib/order-item-sku'
import { cn, formatFullDateTime } from '@/lib/utils'

/**
 * 发货单（可打印纸质文档，issue #3768 / UI-040）
 *
 * 设计要点（都是踩过的约束，勿随手改）：
 * 1. **屏幕隐藏、打印可见**：发货页/订单详情页已有各自的屏幕布局，再显示一份会重复；
 *    本组件自带 `display:none` + `@media print` 覆盖，保证屏幕上零视觉改动、
 *    打印时**只有**这份文档。
 * 2. **portal 到 body + display:none 隔离**（issue #3896：打印出空白第二页）：
 *    单据经 `createPortal` 渲染为 `document.body` 的直接子级，打印 CSS 用
 *    `body > *:not(.shipment-print-area) { display: none !important; }` 把整页外壳藏掉 ——
 *    **display:none 不占版面高度**，分页只按单据自身高度计算；
 *    旧方案 `body * { visibility: hidden }` 隐藏的元素**仍占高度**，底层页面（订单详情/
 *    发货页整页布局，含表单/按钮）高于一页 A4 时按隐藏内容高度分页 → 第 2 页空白。
 *    （注意：`.shipment-print-area` 必须是 portal 容器本身的 class，不能再包一层别的
 *    class/div，否则上面的选择器选不中。）
 *    **visibility 防御（勿删）**：订单详情页的 `ProcessingOrderBlock` 仍用旧的
 *    `@media print { body * { visibility: hidden } }` 做打印隔离，会把本单据一起藏成
 *    invisible（补打纸面空白，issue #3912 回归）；故 print 块内必须显式恢复
 *    `.shipment-print-area, .shipment-print-area * { visibility: visible; }` ——
 *    它只影响单据自身可见性，不占版面高度，与 display:none 隔离不冲突。
 *    🔴 **同页多单据的两条硬约束**（issue #4965，CI `Demo path specs` 实测红后修正 —— 别退回旧写法）：
 *    订单详情页同时挂着报价单（`QuotationDoc`），两者都是 `document.body` 的「直接子级」。旧写法在
 *    这种共存下**两条都错**：① 隔离选择器 `body > *:not(.shipment-print-area)` 会把**兄弟单据**
 *    也选进来 ⇒ `display:none !important` 把对方整份藏掉；② 两份无限定 `visibility: visible`
 *    **同特异性**、后渲染者胜 ⇒ 后挂的报价单把本单据藏成 invisible（实测 `toBeVisible()` 红）。
 *    ⇒ 修法：隔离选择器排除所有打印单据（`body > *:not(.print-doc)`，两份容器都带 `print-doc` 标记类）；
 *    visibility 防御限定本次打印目标（`.shipment-print-area[data-print-target='shipment'], …`，
 *    由调用方在打印时置位）。
 * 3. **不得放进 Modal**：`Modal` 面板是 `max-h-full` + 内部 `overflow-y-auto`，
 *    打印只会打出可视区那一屏（多页明细会被裁掉）。故调用方一律渲染在页面级。
 * 4. **每页只挂一份**：`.shipment-print-area` 是全局选择器，挂两份会打印出两套单据。
 * 5. 数据全部取自订单本身（明细不可变，见 OrderItemImmutabilityTest/PG-014），
 *    不需要快照表 —— 这是「发货单不建实体」的依据。
 * 6. 运单号未产生时留空线（纸面手写），不编造。
 * 7. **发货人栏「-」口径**（issue #3818 裁定）：存量已发货订单 `shipper_name` 为 NULL/空
 *    （历史上从未采集）→ 纸面发货人栏显示「-」，与 #3768 判据一致；**不得**留白、
 *    不得 undefined/null。与第 6 条区分：留空只给「运单号/物流公司」（发货前手写用）。
 * 8. 🔴 **缺值不许印成 0**（issue #6720）：行级 `unitPrice` / `quantity` / `amount` 与合计
 *    在缺值时一律印 `—`（`SHIPMENT_DOC_MISSING`），**不印 `0.00` / `0`**；**真 0 仍印 `0.00`**。
 *    范式就地照抄：第 6 条（无物流 ⇒ 留空供手写）、第 7 条（发货人缺 ⇒ `-`）、
 *    `SalesDoc` 的 `SALES_DOC_MISSING`。判据 = `frontend/admin-web/tests/unit/components/ShipmentDoc.test.tsx`
 *    的「缺值不印 0」一组 + 类级守卫 `frontend/admin-web/tests/unit/lib/print-doc-paper.test.ts`。
 *    🔴 **聚合求和要区分「未知」与「0」**（issue #6731）：数量 / 金额两个合计走 `sumOrUnknown`
 *    （任一行不可知 ⇒ 合计印 `—`），**不得**用 `reduce(… || 0)` 把缺的那行摊成 0。
 *    但 **加工费合计有意仍是 `reduce(… || 0)`** —— 加工费缺席的含义**就是 0**（存量单没有该
 *    字段），后端同口径；改它会把已知的 0 报成不可知（假 `—`）。差别写在下面那行的注释里。
 */
interface ShipmentDocProps {
  order: Order
  /** 已发货订单的物流（补打时传入）；发货前不传 = 运单号栏留空供纸面填写 */
  logistics?: Pick<LogisticsInfo, 'logisticsCompany' | 'trackingNo' | 'shipperName'> | null
  /** 发货页当前输入的发货人（尚未保存也要印在纸面），优先于 order.logistics */
  shipperName?: string
  /**
   * 本次打印的目标（`'shipment'` = 打印本发货单）。**只在为 `'shipment'` 时**置位
   * `data-print-target`，让 visibility 防御只作用于本单据 —— 否则会把同页的报价单
   * （`QuotationDoc`）重新藏掉（issue #4965 实测回归，见文件头第 2 条）。
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
 * 🔴 **缺值不许在纸面上印成 `0`**（issue #6720）—— 与 `SalesDoc` 的 `SALES_DOC_MISSING`
 * 同一口径（那一份是纸面族的既有范式）：`0.00` 会被读成「这个数是零」，
 * 而「没有这个数」是另一件事 —— 这张纸是**客户拿到手的凭证**，两者在纸面上必须可分。
 *
 * 可达性（不是纸面洁癖）：后端 `OrderDetailResponse.OrderItemResponse.amount` = 行
 * `unitPrice × quantity`，两者都为 null 时回落 `subtotal`；而全局 Jackson
 * `default-property-inclusion: non_null` ⇒ `amount` / `quantity` 为 null 时**键整个缺席**，
 * 前端拿到的就是 `undefined`。故「缺值」在本系统是**真形态**，不是理论分支。
 *
 * 真值 `0` 仍印 `0.00`（真 0 ≠ 未知）—— 判据里两条一起钉（issue #6720 反向对照）。
 */
export const SHIPMENT_DOC_MISSING = '—'

/** 纸面取形（`formatAmount` / `formatQty` 共用）：非有限数 ⇒ 「留白」由调用方决定 */
function paperNumber(value?: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function formatAmount(amount?: number | null): string {
  const value = paperNumber(amount)
  if (value === null) return SHIPMENT_DOC_MISSING
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function formatQty(qty?: number | null): string {
  const value = paperNumber(qty)
  return value === null ? SHIPMENT_DOC_MISSING : String(value)
}

/**
 * 「加工项」一行的文案（issue #7605，用户 2026-10-24 逐字「这里的加工项应该改成A+B 然后乘以数量
 * 是否更好，或者你是否有更好的展示方案」⇒ 裁定 = 按数据二态）。
 *
 * 两种形态（按**数据**选，不按猜测）：
 * - 数量**全等** ⇒ `定型、韩褶 各 6` —— 数字只说一遍（用户要的省法）
 * - 数量**不等** / 有缺值 ⇒ `定型 6 + 韩褶 2`（缺值项仍印 `—`，不静默吞掉）
 * - 单项 ⇒ `定型 6`（不写「各」——「定型 各 6」是病句）
 *
 * 🔴 **不采用** `（A+B）×6` 这类"提公因子再乘"：① 纯文本有运算优先级歧义（`定型 + 韩褶×6`）；
 * ② 它与同行「加工费合计（元）」并排，会诱导客户按 ×N 去乘出一个**算不出来**的数（加工费真值 =
 * 加工费组合价 元/米 × 加工费米数，**不是**这些加工项数量相乘）；③ 各加工项的 `quantity`
 * **可以不等、也可以缺**（后端 `non_null` 让键整个缺席）⇒ 无条件提公因子 = 把不等的数压成一个 = 报错数。
 *
 * 单位「米」**只在区头出现一次**（`加工项（数量：米）`）⇒ 行内不再逐项重复单位、也不再出现 `×`。
 * ⚠️ 单位口径沿用旧表头「数量(米)」：本行消费的 `OrderProcessingItem` **没有** `unit` 字段
 * （只有 `ProcessingItemSnapshot` 有）—— 将来出现按件/按孔的加工项，需**后端先补字段**再改口径。
 */
export function processingItemsText(items: readonly OrderProcessingItem[]): string {
  const qty = items.map((it) => formatQty(it.quantity))
  const uniform = qty.length > 1 && !qty.includes(SHIPMENT_DOC_MISSING) && qty.every((q) => q === qty[0])
  if (uniform) return `${items.map((it) => it.name).join('、')} 各 ${qty[0]}`
  return items.map((it, idx) => `${it.name} ${qty[idx]}`).join(' + ')
}

/** 纸面合计：**有任一缺值 ⇒ 合计不可知**（不拿「缺的行按 0 算」的假合计糊纸面，issue #6720） */
function sumOrUnknown(values: readonly (number | undefined)[]): number | null {
  let sum = 0
  for (const value of values) {
    const n = paperNumber(value)
    if (n === null) return null
    sum += n
  }
  return sum
}

export default function ShipmentDoc({
  order,
  logistics,
  shipperName,
  printTarget,
  inline,
  className,
}: ShipmentDocProps) {
  const companyName = useCompanyName()
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted（未挂载返回 null）
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (!mounted) return null

  const items = order.items || []
  const processingItems = order.processingItems || []

  // 🔴 合计 = 逐行**全有值**才算得出来（issue #6720）：任一行的 `quantity` / `amount` 缺，
  //    合计就印 `—` —— 否则「一行没数」会被静默摊进合计，纸面报给客户一个**假总额**。
  const totalQty = sumOrUnknown(items.map((it) => it.quantity))
  const totalAmount = sumOrUnknown(items.map((it) => it.amount))
  // 加工费合计（元）：真值源 = **行级落库的 `processingFee`**（issue #4406：组合价 × 加工费米数）。
  // ⚠️ 不得再按 `processingItems[].amount` 求和 —— issue #4882 起该字段已从后端
  // `ProcessingItemBrief` 退场（只剩 id/name/quantity）⇒ 旧写法会让纸面恒印 0.00
  // （「本来就不收加工费」与「算不出来」长得一样，属静默改钱的外观）。
  //    ⚠️ 这里是 `reduce(… || 0)` 而**不是** `sumOrUnknown`，是有意的（issue #6731 同类普查的结论）：
  //    加工费**缺席的含义就是 0**（存量单没有该字段 ⇒ 当时没有加工费这回事），后端也是同一口径
  //    （`OrderService.convertToDetailResponse`：`fee == null ⇒ BigDecimal.ZERO` 照样 set）
  //    ⇒ 对它折 0 是**正确**的算术；改成「缺 ⇒ 合计印 —」反而是把已知的 0 报成不可知（假 —）。
  //    与上面两个合计的区别：`quantity` / `amount` 缺席的含义是「**没记过这个数**」（后端 non_null
  //    让键整个缺席）⇒ 那两个必须走 `sumOrUnknown`。
  const processingFeeTotal = items.reduce((sum, it) => sum + (it.processingFee || 0), 0)

  const shipper = (shipperName || logistics?.shipperName || '').trim()
  const company = (logistics?.logisticsCompany || '').trim()
  const trackingNo = (logistics?.trackingNo || '').trim()

  const doc = (
    <div
      className={cn('shipment-print-area print-doc text-neutral-900', className)}
      data-print-sheet
      {...(printTarget === 'shipment' ? { 'data-print-target': 'shipment' } : {})}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。实测（真实 Chromium）：
          订单详情页点「打印发货单」会按销售单的三联纸（241×140）出纸 ⇒ 打废纸。 */}
      {printTarget === 'shipment' && <style>{printPageRule('a4')}</style>}
      <style>{`
        .shipment-print-area { display: none; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          /* 🔴 只有「本次目标」上纸（issue #5914）；正文字号取介质矩阵（9pt = 12px，与原值同尺寸） */
          .shipment-print-area[data-print-target='shipment'] {
            display: block;
            position: static;
            width: 100%;
            /* 🔴 浏览器页眉页脚（版式日期 / 文档标题 / 页面 URL / 页码）只画在纸边到版心的
               那段页边距里 ⇒ A4 的纸型边距写成 0（介质矩阵），版面内缩 12mm 改由这里承担（issue #7309）。
               box-decoration-break: clone 让第 2 页起也重复这段内缩
               （实测：不 clone 时 padding-top 不重复，内容贴到纸边）。 */
            padding: ${printContentInsetCss('a4')};
            -webkit-box-decoration-break: clone;
            box-decoration-break: clone;
            font-size: ${printBodyFontPt('a4')}pt;
          }
          /* 防御：页面其他组件（如 ProcessingOrderBlock）残留的
             "body * { visibility: hidden }" 打印隔离会连同本单据一起藏掉
             （补打纸面 invisible）——必须显式恢复单据自身可见（见文件头第 2 条）。
             ⚠️ 限定 [data-print-target='shipment']：订单详情页同时挂着报价单，
             两条 visibility: visible 同特异性 ⇒ 后渲染者胜，不加限定会被报价单藏掉
             （issue #4965 实测回归）。 */
          .shipment-print-area[data-print-target='shipment'],
          .shipment-print-area[data-print-target='shipment'] * { visibility: visible; }
        }
      `}</style>

      {companyName && (
        <div className="text-center text-sm font-medium text-neutral-700 mb-0.5" data-testid="doc-company-name">
          {companyName}
        </div>
      )}
      <div className="text-center text-xl font-semibold tracking-[0.5em] mb-1">发货单</div>
      <div className="text-center text-xs text-neutral-500 mb-4">{order.orderNo}</div>

      <table className="w-full border-collapse mb-3">
        <tbody>
          <tr>
            <DocCell label="订单号" value={order.orderNo} />
            <DocCell label="下单时间" value={formatFullDateTime(order.createdAt)} />
          </tr>
          <tr>
            {/* 存量订单 shipper_name 为 NULL/空 ⇒ 纸面显示「-」（#3818 裁定；见文件头第 7 条）。
                只有这一栏走「-」，运单号/物流公司仍留空供纸面手写（第 6 条） */}
            <DocCell label="发货人" value={shipper || '-'} />
            <DocCell label="打印时间" value={formatFullDateTime(new Date().toISOString())} />
          </tr>
        </tbody>
      </table>

      <SectionTitle>收货信息</SectionTitle>
      <table className="w-full border-collapse mb-4">
        <tbody>
          <tr>
            <DocCell label="收货人" value={order.customerName} />
            <DocCell label="联系电话" value={order.customerPhone} />
          </tr>
          <tr>
            <td className="border border-neutral-400 px-2 py-1.5" colSpan={4}>
              <span className="text-neutral-500">收货地址：</span>
              {order.customerAddress || ''}
            </td>
          </tr>
        </tbody>
      </table>

      <SectionTitle>商品明细</SectionTitle>
      {/* table-layout: fixed —— 列宽由表头声明的百分比决定（auto 布局按内容分配，
          长商品名/长地址会把列撑歪，纸面每单都可能不一样）；配合表头 whitespace-nowrap 防折行 */}
      <table className="w-full border-collapse mb-2" style={{ tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <DocTh className="w-[26%]">商品</DocTh>
            <DocTh className="w-[9%]">货号</DocTh>
            <DocTh className="w-[9%]">颜色</DocTh>
            <DocTh className="w-[12%]">门幅</DocTh>
            <DocTh align="right" className="w-[13%]">单价(元/米)</DocTh>
            <DocTh align="right" className="w-[11%]">数量(米)</DocTh>
            <DocTh align="right" className="w-[14%]">金额(元)</DocTh>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td className="border border-neutral-400 px-2 py-3 text-center text-neutral-500" colSpan={7}>
                暂无商品明细
              </td>
            </tr>
          )}
          {items.map((item: OrderItem, idx: number) => {
            // 纸面身份四件套取 `lib/order-item-sku.ts`（issue #6869）：原先读的
            // `item.productCode` / `item.color` / `item.specification` **都不在响应里**
            // ⇒ 货号 / 颜色 / 规格 三列在真单上恒空（「缺了商品 sku 的信息」的同族形态）。
            const sku = orderItemSku(item)
            return (
              <tr key={item.id || idx}>
                <DocTd>{sku.name}</DocTd>
                <DocTd>{sku.code}</DocTd>
                <DocTd>{sku.color}</DocTd>
                <DocTd>{sku.doorWidth}</DocTd>
                <DocTd align="right">{formatAmount(item.unitPrice)}</DocTd>
                <DocTd align="right">{formatQty(item.quantity)}</DocTd>
                <DocTd align="right">{formatAmount(item.amount)}</DocTd>
              </tr>
            )
          })}
          {items.length > 0 && (
            <tr>
              <td className="border border-neutral-400 px-2 py-1.5 text-right font-semibold" colSpan={5}>
                合计
              </td>
              <DocTd align="right" bold>
                {formatQty(totalQty)}
              </DocTd>
              <DocTd align="right" bold>
                {formatAmount(totalAmount)}
              </DocTd>
            </tr>
          )}
        </tbody>
      </table>

      {processingItems.length > 0 && (
        <>
          <SectionTitle>加工项（数量：米）</SectionTitle>
          {/* issue #4882：**单价列退场** —— 数据源 `ProcessingItemBrief.unitPrice` 已从后端 DTO 删除
              ⇒ 新单恒为空/0，逐项印价必然误导（与 R10「价只在组合上」同因）；逐项 `金额` 同因退场
              （`amount` 亦随 DTO 删除，印出来只会是 0.00）。
              **保留**「做了哪几项加工、各多少」：送货单是给客户/仓库的**实物凭证**，这是它的核对价值
              （数量单位沿用旧表头「数量(米)」的口径；压成一行后不再逐项重复单位）。
              加工费总额走行级落库 `processingFee` 汇总（不是逐项金额相加）。
              🔴 issue #7275（用户 2026-10-18 逐字「加工项表格应该用一行表达，这样节省空间，比如改成a+b+c这样？」）：
              逐项一张表在纸面吃掉半屏 ⇒ 压成**一行**，加工费合计同行右对齐
              （内容过长时自动折行 —— `flex-wrap`，不裁掉任何一项）。
              🔴 issue #7605（用户 2026-10-24）：一行的**写法**改成按数据二态 —— 数量全等 ⇒
              `定型、韩褶 各 6`；不等 ⇒ `定型 6 + 韩褶 2`；单位提到区头一次、行内不再出现 `×`
              （理由见 `processingItemsText()` 的注释：`（A+B）×6` 有运算优先级歧义，且会诱导客户
              拿它去乘出加工费）。
              逐项名称 / 数量仍是服务端快照真值（不聚合重名行、不重算）；缺数量仍印 `—`。 */}
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border border-neutral-400 px-2 py-1.5 mb-2">
            <span className="break-words" data-testid="shipment-processing-items">
              {processingItemsText(processingItems)}
            </span>
            <span className="font-semibold whitespace-nowrap">
              加工费合计（元）：{formatAmount(processingFeeTotal)}
            </span>
          </div>
        </>
      )}

      <SectionTitle>备注</SectionTitle>
      <div className="border border-neutral-400 px-2 py-2 mb-4 min-h-[40px] whitespace-pre-wrap">
        {order.remark || ''}
      </div>

      <SectionTitle>物流</SectionTitle>
      <table className="w-full border-collapse">
        <tbody>
          <tr>
            <DocCell label="物流公司" value={company || undefined} />
            <DocCell label="运单号" value={trackingNo || undefined} />
          </tr>
        </tbody>
      </table>
    </div>
  )

  // 🔴 预览层里**不 portal**（issue #5914）：同一份单据要摆进真尺寸纸框，portal 会跑到框外
  return inline ? doc : createPortal(doc, document.body)
}

// ========== 打印友好的表格原子（纯边框、无底色，避免打印丢背景） ==========

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="font-semibold mb-1">{children}</div>
}

function DocCell({ label, value }: { label: string; value?: string }) {
  return (
    <>
      <td className="border border-neutral-400 px-2 py-1.5 w-24 text-neutral-500 whitespace-nowrap">{label}</td>
      <td className="border border-neutral-400 px-2 py-1.5">{value || ''}</td>
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
        'border border-neutral-400 px-2 py-1.5 font-semibold whitespace-nowrap',
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
  bold = false,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  bold?: boolean
}) {
  return (
    <td
      className={cn(
        'border border-neutral-400 px-2 py-1.5',
        align === 'right' ? 'text-right' : 'text-left',
        bold && 'font-semibold'
      )}
    >
      {children}
    </td>
  )
}
