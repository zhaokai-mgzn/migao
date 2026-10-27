'use client'

import { Fragment, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import dayjs from 'dayjs'
import {
  isContinuousFeed,
  printBodyFontPt,
  printContentInsetCss,
  printPageRule,
  printUsableHeightMm,
  type PrintMediaId,
} from '@/lib/print-media'
import { useCompanyName } from '@/lib/use-company-name'
import { orderItemCurtainType, orderItemSku } from '@/lib/order-item-sku'
// 加工项文案的**单一来源**（与发货单 / 加工单 / 报价单同一份构建器，issue #7891）——
// 本组件只渲染它的输出，不另拼一份会漂移的文案。
import { processingPaperLine } from '@/lib/processing-item-text'
import {
  resolveSalesQuantity,
  SALES_QTY_NOT_SHIPPED,
  type OrderShipmentRead,
} from '@/lib/sales-shipment'
import { cn } from '@/lib/utils'
// 页脚「温馨提示」与报价单**同一句**（#4965）—— 从既有那份 import，不复制一份会漂移的副本
import { QUOTATION_FOOTER_NOTICE } from './QuotationDoc'
import type { PrintTarget } from './index'
import type { Order, OrderItem } from '@/types'

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
 *    （`@page { size: 241mm 140mm; margin: 0; }` + 版面内缩 6mm 12mm 走容器 padding；
 *    2026-10-25 起上下边距一律 0 —— 浏览器把页眉页脚画在 `@page` 边距里）—— 边距与页长是**通用参数 + 待实测**，
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
 * ① 表头：企业名称 + 销售单 / 单号 · 日期（**占满整行**）+ 客户 / 电话 / 地址 / 订货电话 ——
 *    左上角那块作业单扫码报工码自 issue #7891 起**迁到加工单**纸面（见下「码已迁到加工单纸面」）；
 * ② 明细：{@link SALES_DOC_COLUMNS}（序号 | 货号 | 颜色 | 门幅 | 帘种 | 数量 | 单位 | 单价 | 金额）——
 *    **商品行粒度**（与报价单的「按套」粒度**不是同一个数据投影**，不许互套）；
 *    每个商品行之后可跟一条**加工项子行**（issue #7891：加工项**绑商品**，见下同名一节）；
 *    货号 / 颜色 / 门幅 取 `lib/order-item-sku.ts` 的 `orderItemSku()`（issue #6869）；
 *    帘种（布帘 / 纱帘）取同一模块的 `orderItemCurtainType()`（issue #7625）；
 *    🔴 「品名」列自 issue #7530 起**退场**（用户 2026-10-23 逐字「销售单不要品名」）——
 *    单据身份由货号 / 颜色 / 门幅承载，不印商品名；
 * ③ 汇总：上期余额 / 预存抵扣 / 优惠金额 / **本单应收** / 账户余额；
 * ④ 页脚：**只留温馨提示**（issue #7589，用户 2026-10-24 逐字「销售单打印处右下角的二维码移除掉」）
 *    —— 收款码**不上销售单**，本组件也不再读它（报价单仍印收款码，那是另一份单据）。
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
 * ## 与发货链的关系（issue #5651 收口：**已接线**）
 *
 * 用户裁定销售单要「挂在发货链上」= 随货给客户的那张、数量与**实发**同源。
 * 2026-09-26 那版**只落了工人读面**（`/api/worker/shipment/orders/{orderId}`，工人 session 准入）
 * ⇒ admin-web 拿不到实发数量，数量列只能退回订单行投影（本文件当时如实登记的未完成项）。
 *
 * **现状（本单补齐）**：后端新增 admin 读面 `GET /api/admin/orders/{id}/shipments`
 * （与工人面**共用** `OrderShipmentService.readShipment` —— 「实发套/件/卷」这个真值的唯一 owner），
 * 本组件经 `shipments` prop 消费它，数量列的取值与**四态**判定全部交给
 * `lib/sales-shipment.ts`（`resolveSalesQuantity`）：
 *
 * | 态 | 数量列印什么 |
 * |---|---|
 * | 已发货（发齐） | **实发数量** |
 * | 部分发货 | 有实发的行印实发；未发行**显式**标「{@link SALES_QTY_NOT_SHIPPED}」 |
 * | 未发货 | 订单数量，且纸面**标明**「这不是实发」 |
 * | 发货明细未取到 | 订单数量，且纸面**标明**「读面没取到」（**不许**冒充「未发货」） |
 *
 * 🔴 **不出现第二份真值**：销售单**不新增**数量口径 —— 有实发就印实发（印的是
 * `order_shipment_items.shipped_quantity`），没有才印订单数量并标明基准；
 * 任何情况下**都不印 0**（`0` = 「实发为零」，与「没有这个数」「这一行没发」是三件事）。
 *
 * 🔴 **`shipments` 是必填 prop**（`null` = 读面没取到，是**调用方要做的决定**）：
 * 让"忘了接读面"在**编译期**就红 —— 那正是本单要修的半成品形态（读面只落了一面）。
 *
 * ## 码已迁到加工单纸面（issue #7891，用户 2026-10-27 逐字「把销售单左上角的扫码报工二维码
 * 迁移到加工单打印上，这样设计才是合理的」）
 *
 * 销售单负责「**随货给客户**」，扫码报工属**车间** ⇒ 码**不上本单**：issue #7530 加在左上角的
 * 整块码（`sales-work-order-qr` / `-svg` / `-label`）连同 `processingOrder` prop 一并退场，
 * 抬头恢复成「企业名称 + 销售单 / 单号 · 日期」**占满整行**（不再为码块留左侧位置）。
 *
 * 码现在由**加工单纸面**（`components/orders/ProcessingDoc.tsx`，同一批已落地「左上角扫码报工码」
 * 一节）承载 —— 原来属于本单的两条口径随码迁过去，**不在本文件复述**（同一件事两处各写一份会漂）：
 * ① 码值**逐字**取服务端下发的 `scan_url`，前端**不拼**（域名 / 路径段是第二份真值）；
 * ② **缺码不画假码**（整块不出现，不画占位框、不回落作业单号）。
 * 两条的判据随实现一起搬到 `ProcessingDoc.test.tsx`，本文件只留**反向**判据：
 * 销售单纸面**不再出现**那块码（`SalesDoc.test.tsx` 的「⑬」）。
 *
 * ✅ 调用点那一包（`OrderDetail.tsx`）已同批删掉两处 `processingOrder` 传参（本组件先删签名、
 * 调用点后收口，两边不互相等）。即便**遗留**调用点还传这个多余 prop，React 也只是忽略它 ——
 * **不会**把码带回纸面（`SalesDoc.test.tsx` 的「⑬ 遗留调用点」就是这条的判据）。
 *
 * ## 加工项**绑商品**（issue #7891）
 *
 * 用户同一次要求逐字「销售单和报价单都缺了加工项」+「发货单的加工项需要和商品绑定，比如如果是
 * 成品帘，一览展示商品，商品下面是加工项，展示内容参考水洗唛的那种格式，还有特殊选项也要放上去，
 * 都放在加工项那一栏里面」。⇒ 每个**商品行之后**追加一条子行
 * （`sales-item-processing-{idx}`、单格 `colSpan` = 全表列数，仍在**同一张** `<table>` 里 ⇒ 与
 * 商品行同一栅格 / 同一张边框），内容 = `processingPaperLine(item.processingInfo)` 的**单行**形态
 * （`加工项：定型、韩褶 各 6.3 · 特殊选项：拼2次-布`）。
 *
 * 1. 🔴 **文案单一来源**：加工项 / 特殊选项**只**从 `lib/processing-item-text.ts` 取
 *    （销售单 / 报价单 / 发货单 / 加工单同一份构建器）—— 本组件**不许**另拼一份
 *    （三份纸各拼一份 = 同一张订单的「做哪些活」在纸上长得不一样）。
 * 2. **布料行 / 存量无加工项的行不出子行**：该函数返回空串即整块不渲染 —— 不印空行，
 *    也**不**印「加工项：—」占位（没有加工项 = 这行本来就没有这栏，不是缺值）。
 * 3. 🔴 **版面预算**：三联纸单联可用高只有 128mm（见上「介质」第 4 点）⇒ 子行必须**单行紧凑**：
 *    `0.85em`、**无背景色**（打印会丢底色）、`break-words` 折行不裁（issue #7715：纸面印全文）。
 *    ⛔ 不为它新增表头 / 列 —— `SALES_DOC_COLUMNS` 是 C5 守卫的唯一真值。
 */
interface SalesDocProps {
  order: Order
  /**
   * 发货读面（`GET /api/admin/orders/{id}/shipments`）—— 数量列的**唯一**实发来源。
   *
   * 🔴 **必填**：`null` = 调不到 / 还没取到（**调用方必须显式做这个决定**）。
   * 缺省值会让「忘了接读面」静默退回订单数量 —— 那正是本单要修的半成品形态。
   * 判定与四态见 `lib/sales-shipment.ts` 的 `resolveSalesQuantity`。
   */
  shipments: OrderShipmentRead | null
  /**
   * 介质（缺省三联纸 241mm × 140mm）。切介质**只**改版面参数，字段映射只有一份
   * （见文件头「介质是参数，不是副本」）。
   */
  media?: PrintMediaId
  /** 本次打印的目标（`'sales'` = 打印本销售单）—— 不加限定会把同页兄弟单据藏掉 */
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
 * 销售单明细的列（**全仓唯一一份**）：表头与每行都由它渲染 ⇒ 想加/改列只动这里。
 * 守卫 `test_print_media_matrix_guard.py` C5 断言这串有序标签在 `src/**` 里**恰好出现在
 * 一个文件** —— 复制一份到「另一个介质的版本」⇒ 必红（介质是参数，不是副本）。
 *
 * issue #6869（用户 2026-10-14 逐字「缺了商品 sku 的信息」）：原列清单
 * `序号|货号|数量|单位|单价|金额|备注` 有两个实测缺陷 ——
 * ① **没有品名 / 颜色 / 门幅**：客户拿这张纸收货，认不出是哪一款布、什么颜色、几米门幅；
 * ② 「货号」读的是一个**不在响应里**的字段 `productCode`（真字段是 `skuCode`）⇒ 它实际回落到
 *    商品名（`productCode || productName`）、而「备注」列印的是 `item.color`（同样不在响应里）
 *    ⇒ 两列一个冒充货号、一个恒空。
 * ⇒ 新列清单只保留**有真值**的列（取值口 = `lib/order-item-sku.ts`）。
 * ⛔ 原「备注」列**直接撤掉**（不换成空列、也不另起备注子行）：它印的 `item.color` 已由
 * 「颜色」列承载，而 `item.specification` 是「品名 + colorName」的同义重复（§31 P2 信息不重复）；
 * 更要紧的是三联纸单联只有 128mm 可用高，多一行子行会挤掉「本单应收 / 页脚提示」
 * （实测 >6 行即溢出被裁，见 `lib/print-media.json` 与 `PrintDocPreview` 的自检）。
 *
 * 🔴 issue #7530（用户 2026-10-23 逐字「销售单不要品名」）：「品名」列**退场** ⇒ 9 列变 8 列。
 * 它承载的信息在纸面上仍有真值——货号 / 颜色 / 门幅 三列合起来足以认出是哪一款布
 * （同一次裁定另一半的左上角扫码报工码，issue #7891 起已**迁到加工单**，见文件头）。
 * issue #7625 又把「帘种」补进门幅之后（8 列变 9 列），之后再没增删列：
 * 加工项走**子行**（`colSpan` = 本列清单长度），⛔ 不为它动这份清单。
 */
export const SALES_DOC_COLUMNS = [
  '序号',
  '货号',
  '颜色',
  '门幅',
  // 帘种（issue #7625，用户 2026-10-24「给所有打印预览表格都加一列用来区分是布帘还是纱帘」）
  '帘种',
  '数量',
  '单位',
  '单价',
  '金额',
] as const

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

/**
 * 金额格式化（含千分位 + 两位小数）。**只做展示格式化，不做任何算术**。
 *
 * 🔴 缺值 ⇒ 显式占位 `—`（**不填 0**）：`0.00` 会被读成「这个数是零」，而「没有这个数」
 * 是另一件事 —— 两者在纸面上必须可分（同族：缺口金额栏标「{@link SALES_DOC_NOT_COLLECTED}」
 * 而不是 `0.00`）。守卫：`tests/unit_ci_workflows/test_shipment_read_surface_guard.py` 的
 * 「数值补位」判据（受管消费方文件里 `?? 0` / `|| 0` 直接进格式化 ⇒ 红）。
 */
function formatAmount(amount?: number): string {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return SALES_DOC_MISSING
  return amount.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatDate(value?: string | null): string | null {
  if (typeof value !== 'string' || value.trim() === '') return null
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : null
}

export default function SalesDoc({
  order,
  shipments,
  media = 'continuous-241x140',
  printTarget,
  inline,
  className,
}: SalesDocProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const companyName = useCompanyName()

  if (!mounted) return null

  const items = order.items || []
  // 🔴 数量列的口径判定（四态 + 逐行取值）全在 lib 里 —— 本组件只渲染结果、不自己判
  const qty = resolveSalesQuantity(items, shipments)
  const continuous = isContinuousFeed(media)
  // 连续纸：容器高度 = 单联可用高度（页长 − 上下边距），超出即裁 —— 绝不跨联
  const sheetHeightMm = continuous ? printUsableHeightMm(media) : null
  const docNo = paperText(order.orderNo)
  const date = formatDate(order.createdAt)
  const hasDiscount = typeof order.discountAmount === 'number'

  const doc = (
    <div
      className={cn('sales-print-area print-doc text-neutral-900', className)}
      {...(printTarget === 'sales' ? { 'data-print-target': 'sales' } : {})}
      data-print-media={media}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。实测（真实 Chromium）：
          订单详情页点「打印发货单」会按销售单的三联纸（241×140）出纸 ⇒ 打废纸。 */}
      {printTarget === 'sales' && <style>{printPageRule(media)}</style>}
      <style>{`
        .sales-print-area { display: none; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          /* 🔴 只有「本次目标」上纸：非目标单据留在 display:none ⇒ 不占版面（不出空白页）、
             也不参与纸型竞争（issue #5914）。 */
          .sales-print-area[data-print-target='sales'] {
            display: block;
            position: static;
            width: 100%;
            /* 🔴 浏览器页眉页脚只画在纸边到版心的那段页边距里。上下边距只要不是 0，就有被画出来的路
               （实测下限 8.7mm 是一条未文档化的分界；三联纸原来写 6mm 12mm，靠「6mm 比它小」侥幸不画）
               ⇒ 2026-10-25 起三联纸也把 @page 边距写成 0，版面内缩 6mm 12mm 由这里承担
               （可用版面 217 × 128mm 逐值不变；issue #7309 立口径，2026-10-25 收口到全矩阵）。
               box-decoration-break: clone 让多页时逐页重复这段内缩。 */
            padding: ${printContentInsetCss(media)};
            -webkit-box-decoration-break: clone;
            box-decoration-break: clone;
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
        }
      `}</style>

      {/* 🔴 **一份** .sales-sheet —— 三联纸的复写由纸承担，软件不渲染三遍（issue #5651） */}
      <div
        className="sales-sheet"
        data-print-sheet
        data-testid="sales-sheet"
        style={sheetHeightMm !== null ? { height: `${sheetHeightMm}mm`, overflow: 'hidden' } : undefined}
      >
        {/* ===== ① 表头（issue #7219：企业名称；issue #7891：抬头占满整行，码已迁到加工单） ===== */}
        {/* 码块（issue #7530 的左上角扫码报工码）自 issue #7891 起**不上销售单** ⇒ 抬头不再为它
            留左侧位置：企业名称 / 销售单 / 单号 · 日期 直接占满整行（单联 128mm 的版面预算见文件头）。 */}
        <div className="mb-1">
          {companyName && (
            <div className="text-center text-[0.9em] font-medium text-neutral-700 mb-0.5" data-testid="doc-company-name">
              {companyName}
            </div>
          )}
          <div className="flex items-baseline justify-between border-b border-neutral-400 pb-1">
            <span className="text-base font-semibold tracking-[0.3em]">销售单</span>
            <span className="text-[0.9em] text-neutral-600">
              单号 {docNo}
              {date ? ` · ${date}` : ''}
            </span>
          </div>
        </div>

        <table className="w-full border-collapse mb-1">
          <tbody>
            <tr>
              <DocCell label="客户" value={order.customerName} testId="sales-customer" />
              <DocCell label="电话" value={order.customerPhone} testId="sales-phone" />
            </tr>
            <tr>
              <DocCell label="地址" value={order.customerAddress} colSpan={3} testId="sales-address" />
            </tr>
            <tr>
              {/* 订货电话：实证 #4 的栏位位置 = 下单电话口径（见文件头口径 3；现场口径存疑已登记） */}
              <DocCell label="订货电话" value={order.customerPhone} colSpan={3} testId="sales-order-phone" />
            </tr>
          </tbody>
        </table>

        {/* ===== ② 明细：商品行粒度（序号|货号|颜色|门幅|帘种|数量|单位|单价|金额；「品名」自 #7530 退场、帘种自 #7625 加入） ===== */}
        {/* 🔴 数量列的**口径**必须印在纸面上（印的是实发还是订单数量、单据处于什么状态）——
            静默留空 / 印 0 都会让「账实不符」在纸上不可判（issue #5651 硬约束）。 */}
        <div className="text-[0.85em] text-neutral-600 mb-0.5" data-testid="sales-qty-basis">
          {qty.basisLabel}
          {qty.unmatchedShippedLines > 0
            ? `；另有 ${qty.unmatchedShippedLines} 行实发明细未挂到订单行（不猜归属，故不在本表）`
            : ''}
        </div>
        <table className="sales-doc-table w-full border-collapse mb-1" style={{ tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <DocTh className="w-[6%]">{SALES_DOC_COLUMNS[0]}</DocTh>
              <DocTh className="w-[13%]">{SALES_DOC_COLUMNS[1]}</DocTh>
              <DocTh className="w-[14%]">{SALES_DOC_COLUMNS[2]}</DocTh>
              <DocTh className="w-[11%]">{SALES_DOC_COLUMNS[3]}</DocTh>
              <DocTh className="w-[8%]">{SALES_DOC_COLUMNS[4]}</DocTh>
              <DocTh align="right" className="w-[9%]">
                {SALES_DOC_COLUMNS[5]}
              </DocTh>
              <DocTh className="w-[8%]">{SALES_DOC_COLUMNS[6]}</DocTh>
              <DocTh align="right" className="w-[13%]">
                {SALES_DOC_COLUMNS[7]}
              </DocTh>
              <DocTh align="right" className="w-[18%]">
                {SALES_DOC_COLUMNS[8]}
              </DocTh>
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
              items.map((item: OrderItem, idx: number) => {
                // 货号 / 颜色 / 门幅 = 纸面身份三件套（issue #6869；「品名」自 #7530 退场）——
                // 唯一取值口，缺值一律显式占位 `—`（不静默留空，见文件头硬约束）
                const sku = orderItemSku(item)
                // 帘种（issue #7625）：布帘 / 纱帘 —— 唯一取值口；布料单没有帘 ⇒ 占位 `—`
                const curtainType = orderItemCurtainType(item)
                // 加工项子行（issue #7891）：文案**只**取 `lib/processing-item-text.ts` 的构建器
                // （销售单 / 报价单 / 发货单 / 加工单同一份）；空串 = 这一行没有加工项
                // （布料行、存量无加工项的订单）⇒ 整块不渲染（不印空行、也不印「加工项：—」）。
                const processingLine = processingPaperLine(item.processingInfo)
                return (
                  <Fragment key={item.id || idx}>
                    <tr data-testid={`sales-item-${idx}`}>
                      <DocTd align="right">{idx + 1}</DocTd>
                      <DocTd testId={`sales-code-${idx}`}>
                        {sku.code || SALES_DOC_MISSING}
                      </DocTd>
                      <DocTd testId={`sales-color-${idx}`}>
                        {sku.color || SALES_DOC_MISSING}
                      </DocTd>
                      <DocTd testId={`sales-door-width-${idx}`}>
                        {sku.doorWidth || SALES_DOC_MISSING}
                      </DocTd>
                      <DocTd testId={`sales-curtain-type-${idx}`}>
                        {curtainType || SALES_DOC_MISSING}
                      </DocTd>
                      {/* 数量：**实发**（后端 admin 读面；真值 owner = `order_shipment_items`）。
                          未发行 ⇒ 显式「未发」；未发货 / 读面没取到 ⇒ 订单数量（口径已印在表上方）。
                          ⛔ 任何情况下都不写 0 —— `0` 会被读成「实发为零」（issue #5651 硬约束）。 */}
                      <DocTd align="right" testId={`sales-qty-${idx}`}>
                        {qty.cells[idx]?.basis === 'shipped' && qty.cells[idx]?.value === null
                          ? SALES_QTY_NOT_SHIPPED
                          : paperText(qty.cells[idx]?.value)}
                      </DocTd>
                      {/* 单位：`OrderItem.quantity` 在本系统**恒为米** —— 发货单表头写的就是
                          「数量(米)」、报价单单价写的是「元/米」⇒ 单位取**同一口径**，
                          不新增字段、也不编一个别单位 */}
                      <DocTd>米</DocTd>
                      <DocTd align="right">{formatAmount(item.unitPrice)}</DocTd>
                      <DocTd align="right" testId={`sales-row-amount-${idx}`}>
                        {formatAmount(item.amount)}
                      </DocTd>
                    </tr>
                    {/* 加工项**绑这个商品**（issue #7891）：紧跟商品行、同一张表内的一条子行
                        （单格 `colSpan` = 全表列数 ⇒ 不新增列、不破坏 C5 的列清单真值）。
                        单行紧凑（0.85em / 无背景色 / 折行不裁）：三联纸单联可用高只有 128mm，
                        多起一段会挤掉「本单应收 / 页脚提示」（见文件头「加工项绑商品」第 3 条）。 */}
                    {processingLine !== '' && (
                      <tr data-testid={`sales-item-processing-${idx}`}>
                        <td
                          colSpan={SALES_DOC_COLUMNS.length}
                          className="border border-neutral-400 px-1.5 py-1 text-[0.85em] text-neutral-700 break-words"
                        >
                          {processingLine}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })
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

        {/* ===== ④ 页脚：只留温馨提示（issue #7589：销售单纸面不印收款码） ===== */}
        <div className="min-w-0 border-t border-neutral-300 pt-1 text-[0.85em] text-neutral-600">
          {QUOTATION_FOOTER_NOTICE}
        </div>
      </div>
    </div>
  )

  // 🔴 预览层里**不 portal**（issue #5914）：同一份单据要摆进真尺寸纸框，portal 会跑到框外
  return inline ? doc : createPortal(doc, document.body)
}

// ========== 打印友好的表格原子（纯边框、无底色，避免打印丢背景） ==========
//
// 🔴 **纸面一律折行印全文，不设省略号**（issue #7715，用户 2026-10-25 逐字
// 「这里打印预览的文字要打印全，不能缩略」）：货号 / 颜色 / 客户 / 地址这些长度不可控的值，
// 旧形态走 `.sales-cut`（`text-overflow: ellipsis` + `nowrap`）—— 客户拿到纸只看到
// 「2659-08 月落雾…」，认不出是哪个花色。现改为 `break-words` 折行：全文上纸，
// 行高由内容决定；纸面超高由既有自检（`PrintDocPreview` 的 `measureSheets`）如实报出，
// **不靠裁切掩盖**（裁掉的那半截恰恰是客户要认的信息）。
// ⚠️ 标签列 / 表头的 `whitespace-nowrap` **不在此列**：它们印的是固定短词（客户 / 门幅 …），
// 不会变长；`nowrap` 只是别让两个字折成两行。

function DocCell({
  label,
  value,
  colSpan = 1,
  testId,
  strong = false,
}: {
  label: string
  value?: string | null
  colSpan?: number
  testId?: string
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
        className={cn('border border-neutral-400 px-1.5 py-1 break-words', strong && 'font-semibold')}
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
  testId,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  testId?: string
}) {
  return (
    <td
      data-testid={testId}
      className={cn(
        'border border-neutral-400 px-1.5 py-1 align-top break-words',
        align === 'right' ? 'text-right' : 'text-left'
      )}
    >
      {children}
    </td>
  )
}
