'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, ArrowLeft, Printer, RefreshCw, ShieldOff, Wrench } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { cn, formatFullDateTime } from '@/lib/utils'
import { chipToneClasses } from '@/lib/status-chip'
import { orderKindOf, processingOrderStatusChipFor } from '@/lib/processing-order'
import { orderApi, processingOrderApi, processingOrderSetApi, productionApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { useRouteId } from '@/lib/use-route-id'
import { routeSourceNotice } from '@/lib/route-source'
// 工序显示名的**唯一**口径（`逻辑名 · 部位`）：本页此前在「卡在哪」那一行为手拼了一份，
// 与同页进度表（`ProductionProgressTable` → 同一份 helper）**两套口径**
// ⇒ `logical_name` 缺失时会渲染成 ` · 布帘` 或 `—`，而进度表渲染的是快照名原文。
import { operationDisplayName } from '@/lib/operation-display'
import ProductionProgressTable from '@/components/production/ProductionProgressTable'
import ProcessingOrderActions from '@/components/production/ProcessingOrderActions'
import QualityCheckPanel from '@/components/production/QualityCheckPanel'
import PieceworkTable from '@/components/production/PieceworkTable'
import CutPlanTable from '@/components/production/CutPlanTable'
import PrintDocPreview from '@/components/orders/PrintDocPreview'
// 加工单（A4）纸面自 issue #7870 起在**本页**打印（用户 2026-10-26「加工单打印移到加工单和洗水唛
// 放一起，也想订单一样统一收口到打印按钮」）—— 与洗水唛同一个预览层，靠单据标签切换。
// 🔴 同一份组件、同一份字段映射：订单详情页打印的那张纸就是这张（不另写一套纸面）。
import ProcessingDoc from '@/components/orders/ProcessingDoc'
// 加工费组合（= `processingItems[].name` 集合；超高/超宽/倒幅所在）—— 取值口径唯一一份（issue #7833）
import { processingComboTextOfRows } from '@/lib/processing-combo'
// 工艺规格（含「特殊选项」那一行）的**唯一**取值定义（设计 §4.9）—— 屏幕/纸面/订单详情同源
// （issue #7851：页头按商品行展示特殊选项，不在这里再拼一份 `join('、')`）
import { craftSpecRows } from '@/lib/craft-display'
import { PRINT_TARGET_SPECS, printTargetTitle, usePrintDoc, type PrintTarget } from '@/lib/print-doc'
import TaskCardPrint from '@/components/production/TaskCardPrint'
// 免驱动直连打印（issue #6439）：**不做打印机定制功能** —— 通道层与机型无关，本页只接一条
// 「直连打印机」入口；部位 ⇒ 洗水码数据的映射走单一处 `toWashLabelInputs`（页面不另写一份）
import DirectLabelPrint from '@/components/production/DirectLabelPrint'
import { toWashLabelInputs } from '@/lib/wash-label-content'
// 纸面抬头（企业名）与四张 A4/三联纸单据**同一份**读取口（issue #7219；2026-10-25 洗水唛也用）
import { useCompanyName } from '@/lib/use-company-name'
import type {
  Order,
  PieceworkSummary,
  ProcessingOrder,
  ProcessingOrderItem,
  ProcessingOrderSetRow,
  ProductionOperations,
  StuckPointsReport,
} from '@/types'

/**
 * 该快照行的「特殊选项」展示文本（`拼1次、接高`）；缺键 / 空数组 / 全空白 ⇒ **空串**（调用方据此整行不渲染）。
 *
 * 取值走设计 §4.9 的**同一份定义** `craftSpecRows()`（`特殊选项` 那一行由它格式化：去空、`、` 连接）
 * —— 订单详情 / 加工单纸面 / 本页屏幕**同源**（与组合键 `processingComboTextOfRows` 同一处置）。
 */
function specialOptionsTextOf(item: ProcessingOrderItem): string {
  return craftSpecRows(item).find((row) => row.label === '特殊选项')?.value ?? ''
}

/**
 * 逐行的「特殊选项」行（**缺值行整块不出现**，`—` 与空块都不写）。
 *
 * 行身份 = `商品名（颜色）`（与「复制全部」文本 `toPlainText` 的既有形态一致）；
 * 两者都缺时退回空串（只显示该行的选项，不编造行号）。
 */
function specialOptionRowsOf(items?: ProcessingOrderItem[]): { key: string; item: string; options: string }[] {
  return (items ?? []).flatMap((item, index) => {
    const options = specialOptionsTextOf(item)
    if (!options) return []
    const name = (item.productName ?? '').trim()
    const color = (item.colorName ?? '').trim()
    return [{ key: item.itemId ?? `item-${index}`, item: name && color ? `${name}（${color}）` : name || color, options }]
  })
}

/**
 * 精裁输出清单一次性拉取的套数上限（服务端 `size` 上限 = 100，超出按上限收敛不报错）。
 * 🔴 超出时**显式提示被截断**（`cutPlanTotal > cutPlanSets.length`）—— 静默少显示几套
 * 会让裁床按一份不完整的清单下料，那是本仓最忌的静默错误。
 */
const CUT_PLAN_SET_PAGE_SIZE = 100

/**
 * 面料单**只有一张纸**（issue #7891，用户 2026-10-27 逐字「面料单不能打印水洗唛，应该打印加工单」）：
 * A4 那张作业单；洗水唛整份**不进**这一层（连入口都不留）。
 * 提成模块级常量：① 让下面的 `printDocs` 只表达「哪几型有哪几张纸」；② 「面料单 = 一份纸」这条口径
 * 只有一处字面量（散进三目里就没人找得到）。
 */
const FABRIC_PRINT_DOCS: readonly PrintTarget[] = ['processing']

/**
 * 加工单生产明细（issue #4000，M4-H 按需单据渲染）
 *
 * 路由：/processing-orders/{id}/production（id = 加工单号/订单号/UUID，按既有 useRouteId 读法）
 * 数据：加工单详情（头部：加工单号/订单号/状态/交期）+ 生产工序树（进度条/工序进度表）
 *       + 计件汇总；两份纸随页面挂载（屏幕隐藏、打印显形）→ 页头**一个**「打印」入口，
 *       进来在单据标签里选「水洗唛（任务卡）」或「加工单（A4）」（issue #7870）。
 * 🔴 **面料单没有水洗唛**（issue #7891，用户 2026-10-27 逐字「面料单不能打印水洗唛，应该打印加工单」）：
 *    `order_kind === 'outbound'`（只做裁剪的面料单）⇒ 本页**不挂**任务卡、打印层里**没有**水洗唛那一份，
 *    只剩一张 A4 纸 —— 它的纸面名 =「面料单」（不是「加工单」，也**不是**「裁剪单」，
 *    真值 = `lib/processing-order.ts` 的 `WORK_ORDER_DOC_TITLES`）。
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §4 计件 / §5 扫码报工闭环。
 * 端点：GET /api/admin/production/orders/{orderId}/operations、/piecework（权限 order:list）；
 *       POST .../qr-token/revoke（issue #4240，**方法级 processing:manage** —— 与其它端点的类级
 *       order:list 不同口径，入口必须按同一码显隐，否则无权限角色会看到按钮却 403）。
 */
export default function ProcessingOrderProductionPage() {
  const id = useRouteId('id')
  const router = useRouter()
  const { has: hasPermission } = usePermission()
  /**
   * 加工单（A4）纸面的**读面码** = `order:detail`（`GET /api/admin/orders/{id}`）。
   *
   * 纸面读的是订单字段（客户/地址/货运/制单人/商品行…）——「展示真值单一来源」要求它取
   * **同一份**订单详情 DTO，不另外拼一套快照映射。⇒ 无本码的岗位（如质检员 `inspector`：
   * 只有 `production:view`）**不请求、不渲染**这张纸（洗水唛照旧可用）：入口同码显隐，
   * 避免「按钮可见却 403」。
   */
  const canReadOrderDetail = hasPermission('order:detail')

  const [po, setPo] = useState<ProcessingOrder | null>(null)
  // 加工单（A4）纸面的数据（issue #7870）：订单详情读面；`null` = 本页没有这张纸
  const [printOrder, setPrintOrder] = useState<Order | null>(null)
  const [operations, setOperations] = useState<ProductionOperations | null>(null)
  const [piecework, setPiecework] = useState<PieceworkSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [operationsError, setOperationsError] = useState('')
  const [instantiateError, setInstantiateError] = useState('')
  const [instantiating, setInstantiating] = useState(false)
  // 撤销二维码（issue #4240）：二次确认弹窗 + 成功可见反馈
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [revoking, setRevoking] = useState(false)
  const [revokeError, setRevokeError] = useState('')
  const [revokedNotice, setRevokedNotice] = useState('')
  // 重新生成二维码（issue #4287，撤销的**恢复半边**）：撤销后旧纸作废，但商家必须还能发新码。
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateError, setRegenerateError] = useState('')
  const [regeneratedNotice, setRegeneratedNotice] = useState('')
  // 未定价实例补价（issue #4709 C）：状态 + 结果反馈（补了几道 / 还有几道没定价）
  const [repricing, setRepricing] = useState(false)
  const [repriceError, setRepriceError] = useState('')
  const [repriceNotice, setRepriceNotice] = useState('')
  // 「卡在哪」卡点报表（切片 ③，issue #4776；只读；设计 §6）
  const [stuckPoints, setStuckPoints] = useState<StuckPointsReport | null>(null)
  const [stuckPointsError, setStuckPointsError] = useState('')
  // 精裁输出清单（issue #5693）：按**加工单号**取该单各套的清单（行粒度 = 套 × 部位）。
  // 数据源 = 服务端唯一实现（后端 `ProcessingSetReadService`）—— 与工人端扫码详情**同一份**；
  // 前端不算第二份、不做单位换算。`cutPlanTotal` 只用于「被截断」的显式提示。
  const [cutPlanSets, setCutPlanSets] = useState<ProcessingOrderSetRow[]>([])
  const [cutPlanTotal, setCutPlanTotal] = useState(0)
  const [cutPlanError, setCutPlanError] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    setOperationsError('')
    setStuckPointsError('')
    setCutPlanError('')
    try {
      const detailRes = await processingOrderApi.detail(id)
      const detail = detailRes.data?.data ?? null
      if (!detail) {
        setPo(null)
        setError('未找到该加工单')
        return
      }
      setPo(detail)

      // 加工单（A4）纸面（issue #7870）：读**订单详情**（与订单详情页打印同一份 DTO）。
      // 失败只影响这一张纸（洗水唛照旧可打），**不**改变页面其余部分的可用性 ⇒ 单独 try + 静默降级。
      if (canReadOrderDetail && detail.orderId) {
        try {
          const orderRes = await orderApi.getOrder(detail.orderId)
          setPrintOrder(orderRes.data?.data ?? null)
        } catch (e) {
          console.error(e)
          setPrintOrder(null)
        }
      } else {
        setPrintOrder(null)
      }

      // 生产端点按**订单 id**（production/orders/{orderId}/...）取；加工单详情已带 orderId
      const orderId = detail.orderId
      if (!orderId) {
        setOperationsError('该加工单未关联订单，无法加载工序进度')
        return
      }
      // 工序与计件互不依赖：一条失败不应把另一条也吞掉（页面不白屏）
      const [opsRes, pieceRes] = await Promise.allSettled([
        productionApi.getOrderOperations(orderId),
        productionApi.getPiecework(orderId),
      ])
      if (opsRes.status === 'fulfilled') {
        setOperations(opsRes.value.data?.data ?? null)
        setInstantiateError('')
      } else {
        setOperations(null)
        setOperationsError('工序进度加载失败，请稍后重试')
      }
      setPiecework(pieceRes.status === 'fulfilled' ? pieceRes.value.data?.data ?? null : null)

      // 卡点报表（切片 ③，issue #4776）：按**加工单 id** 取（不是订单 id）——
      // 报表是「按套 × 工序」的，加工单才是套的归属。失败不吞掉上面两条（页面不白屏）。
      try {
        const stuckRes = await productionApi.getStuckPoints(detail.id)
        setStuckPoints(stuckRes.data?.data ?? null)
        setStuckPointsError('')
      } catch (e) {
        console.error(e)
        setStuckPoints(null)
        setStuckPointsError('卡点报表加载失败，请稍后重试')
      }

      // 精裁输出清单（issue #5693）：按**加工单号**取该单各套的清单（行粒度 = 套 × 部位）。
      // 单独一条 try：清单失败不吞掉工序/计件/卡点（页面不白屏）。
      try {
        const setsRes = await processingOrderSetApi.list({
          processingOrderNo: detail.processingOrderNo,
          size: CUT_PLAN_SET_PAGE_SIZE,
        })
        const items = setsRes.data?.data?.items ?? []
        setCutPlanSets(items)
        setCutPlanTotal(setsRes.data?.data?.total ?? items.length)
        setCutPlanError('')
      } catch (e) {
        console.error(e)
        setCutPlanSets([])
        setCutPlanTotal(0)
        setCutPlanError('精裁输出清单加载失败，请稍后重试')
      }
    } catch (e) {
      console.error(e)
      setPo(null)
      setError('加载加工单失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [id, canReadOrderDetail])

  useEffect(() => {
    load()
  }, [load])

  /**
   * 补生成工序（issue #4202 前端半边）：存量加工单（生成于「生成加工单即自动实例化」之前）
   * 工序实例与 qr_token 双空，此前**没有任何 UI 入口**能触达 instantiate 端点。
   * 冻结契约：positions 变为可选 —— 空 body ⇒ 服务端按订单自动派生工序；已有实例时幂等空操作。
   */
  const handleInstantiate = async () => {
    if (!po?.orderId) return
    setInstantiating(true)
    setInstantiateError('')
    try {
      await productionApi.instantiate(po.orderId)
      await load()
    } catch (e) {
      console.error(e)
      setInstantiateError('补生成工序失败，请稍后重试')
    } finally {
      setInstantiating(false)
    }
  }

  /**
   * 按当前价重算未定价工序实例（issue #4709 C）—— 商家视角的真问题：
   * 商家在「工艺配置 → 工艺路线」的部位价目矩阵里补了价，而**已实例化**的旧单快照仍是
   * `NULL`（未定价）⇒ 工人那批活的钱**算不出来**。重新实例化**不是**可用路径
   * （签名把 `null` 与 `0` 视为同形 ⇒ 不触发；`null → 非 0` 触发但会软删重插 + 报工进度清零）。
   * 端点只补 `NULL`、已有价（含显式定价 0 元）一律不动、报工进度不清零；写面 ⇒ 按同码显隐。
   */
  const handleReprice = async () => {
    if (!po?.orderId) return
    setRepricing(true)
    setRepriceError('')
    setRepriceNotice('')
    try {
      const res = await productionApi.repriceUnpricedInstances(po.orderId)
      const data = res.data?.data
      const filled = data?.filled ?? 0
      const still = data?.still_unpriced ?? 0
      setRepriceNotice(
        still > 0
          ? `已补 ${filled} 道工序的单价；仍有 ${still} 道未定价 —— 请先去部位价目矩阵定价`
          : `已按当前价补齐 ${filled} 道未定价工序，之后的报工按补上的单价计件`,
      )
      await load()
    } catch (e) {
      console.error(e)
      setRepriceError('重算未定价工序失败，请稍后重试')
    } finally {
      setRepricing(false)
    }
  }

  /**
   * 作业单两型（issue #7891，用户 2026-10-27 逐字「面料单不能打印水洗唛，应该打印加工单」）：
   * 面料单（`order_kind === 'outbound'`）只做裁剪，**没有水洗唛** ⇒ 本页对它的打印入口收敛成
   * 只有一张 A4 纸（纸面名 =「面料单」，真值 = `lib/processing-order.ts` 的 `WORK_ORDER_DOC_TITLES`）。
   * 缺键 / `null` ⇒ 按加工单处理（存量单口径 = `orderKindOf` 的同一把尺）。
   *
   * ⚠️ 必须在 `usePrintDoc(...)` **之前**求值：缺省纸要按两型给（下面那条注释），
   * 而 `const` 在声明前读取就是 TDZ 报错。
   */
  const isFabricOrder = po ? orderKindOf(po) === 'outbound' : false
  /** 作业单两型（给纸面名用）：`null` = 加工单读面还没回来 / 缺键（⇒「加工单」） */
  const docKind = po ? orderKindOf(po) : null

  // 🔴 走共享打印入口（issue #5914）：`window.print()` 只在 target 提交之后调用
  // 缺省目标 = 洗水唛（Ctrl+P 与改前行为一致）；加工单（A4）自 issue #7870 起与本页同层，
  // 靠预览层的单据标签切换（`docs` / `selectPreview`）。
  // 🔴 面料单的缺省纸（issue #7891）：洗水唛**整块不挂**，本页只剩那张 A4「面料单」⇒
  // 缺省目标必须跟着作业单两型走（`usePrintDoc` 在「还没打印过」时会跟随入参变化）——
  // 否则面料单上不点按钮直接 Ctrl+P 会**一张纸都不出**（首帧 `po` 还没回来，缺省仍是 `labels`）。
  const { printTarget, previewTarget, requestPrint, openPreview, selectPreview, closePreview } =
    usePrintDoc(isFabricOrder ? 'processing' : 'labels')

  /**
   * 本层可打印的单据（issue #7870）：洗水唛（默认）+ 加工单。
   * 没有订单详情可读 ⇒ 只有洗水唛一份（`docs.length === 1` ⇒ 预览层不出现标签行，与改前一致）。
   */
  const printDocs = useMemo<readonly PrintTarget[]>(
    () =>
      isFabricOrder
        ? printOrder
          ? FABRIC_PRINT_DOCS
          : []
        : printOrder
          ? ['labels', 'processing']
          : ['labels'],
    [isFabricOrder, printOrder],
  )

  /** 预览层当前这份纸（`PRINT_TARGET_SPECS` 是纸型唯一真值；没选 ⇒ 默认洗水唛 / 面料单则是 A4） */
  const previewDocTarget: PrintTarget = previewTarget ?? (isFabricOrder ? 'processing' : 'labels')
  /** 标题按作业单两型给名（issue #7891：成品帘 ⇒「加工单」、面料单 ⇒「面料单」） */
  const previewTitle = printTargetTitle(previewDocTarget, docKind)
  const previewMedia = PRINT_TARGET_SPECS[previewDocTarget].media

  /**
   * 打印留痕（**唯一一处**：fire-and-forget，失败不得阻断打印）。
   * 🔴 两条打印通道（系统打印 / 免驱动直连，issue #6439）**共用**它 ——
   * 「打印必留痕」不因为换了条路就少记一次；反过来说，换通道**不换纪律**。
   */
  const recordPrintOnce = useCallback(() => {
    if (po?.orderId) {
      productionApi.recordPrint(po.orderId).catch(() => {})
    }
  }, [po?.orderId])

  /**
   * 预览层里点「打印」：置位本次目标 ⇒ 由 `usePrintDoc` 在**提交之后**开印。
   *
   * 🔴 打印留痕只记**洗水唛（任务卡）**那一次（issue #7870）：`print_count` 的口径是
   * 「任务卡打了几张」，打 A4 加工单不该把它加一。
   * ⚠️ 计数仍在「真的开印」那一刻 —— 只看了预览没打纸的时候**不该**记账。
   */
  const printPreviewDoc = () => {
    if (!previewTarget) return
    if (previewTarget === 'labels') recordPrintOnce()
    requestPrint(previewTarget)
  }

  /** 预览页脚「蓝牙无线打印」要的水洗唛数据（部位 + 快照行 ⇒ 纸面行清单，走**单一处**映射；issue #6439 → #6656 → #7288）
   *
   * 🔴 与系统打印（`TaskCardPrint`）传的是**同一份**数据源：改动前这里只传了 4 个键
   * （码 / 短码 / 件名 / 部位）⇒ 直连打出来的纸面比预览少十行（issue #6656 的根因）。 */
  // 纸面抬头：企业名（缺值 ⇒ 抬头块整块不渲染）
  const companyName = useCompanyName()
  const washLabels = useMemo(
    () =>
      toWashLabelInputs({
        companyName,
        // 单号 = 加工单号（issue #7833：17 位订单号退出纸面）
        processingOrderNo: po?.processingOrderNo,
        customerName: po?.customerName,
        positions: operations?.positions,
        items: po?.items,
      }),
    [companyName, operations, po],
  )

  /** 点页头「打印」：先看纸面自检（标签纸型没配好 = 整卷打废）；默认洗水唛
   *  🔴 面料单**没有**洗水唛（issue #7891）⇒ 它的缺省纸就是那张「面料单」（A4）。 */
  const handlePrint = () => openPreview(isFabricOrder ? 'processing' : 'labels')

  /**
   * 撤销二维码（issue #4240，真值源 §1「token 化、可撤销」）：二次确认后置空 token
   * ⇒ 已打印的旧码立即失效（工人扫旧码报工 404），再刷新页面回到占位态。
   * 安全相关写操作，端点方法级 processing:manage ⇒ 入口同码显隐。
   */
  const handleRevoke = async () => {
    if (!po?.orderId) return
    setRevoking(true)
    setRevokeError('')
    try {
      await productionApi.revokeQrToken(po.orderId)
      setRevokeOpen(false)
      setRevokedNotice('二维码已撤销，已打印的旧码立即失效')
      await load()
    } catch (e) {
      console.error(e)
      setRevokeError('撤销二维码失败，请稍后重试')
    } finally {
      setRevoking(false)
    }
  }

  /**
   * 重新生成二维码（issue #4287）：撤销把 `qr_token` 与每张部位码都置空，此前页面上**没有**任何
   * 入口能再发码（#4949 只能写免责声明）⇒ 这里补上恢复路径。
   *
   * 🔴 走**窄**接口 `.../qr-token/regenerate`（只补缺失的码）：**不得**复用 `instantiate`
   * —— 它的幂等判据是工序签名（含单价），工序库改价后一点「重新生成」就会软删旧实例、
   * 把 `done_qty` 清零 ⇒ 连带清掉该单的计件工资（计件 = Σ 合格数 × 单价 × 系数）。
   */
  const handleRegenerate = async () => {
    if (!po?.orderId) return
    setRegenerating(true)
    setRegenerateError('')
    try {
      const res = await productionApi.regenerateQrToken(po.orderId)
      const partCodes = res.data?.data?.part_codes ?? 0
      // 撤销提示与重发提示互斥（避免同屏同时出现「已撤销」与「已重新生成」两句）
      setRevokedNotice('')
      setRegeneratedNotice(
        partCodes > 0
          ? `已重新生成二维码（含 ${partCodes} 张部位码），请重新打印任务卡`
          : '已重新生成二维码，请重新打印任务卡',
      )
      await load()
    } catch (e) {
      console.error(e)
      setRegenerateError('重新生成二维码失败，请稍后重试')
    } finally {
      setRegenerating(false)
    }
  }

  // 逐行的「特殊选项」（issue #7851）：服务端按 `specialOptions` **插工序 + 计件** ⇒
  // 车间在「工序进度」看到 `拼1次-布` / `接高-布`，页头必须说得出这几道活来自哪一行。
  // 缺键 / 空数组 ⇒ 该行整块不渲染（`specialOptionRowsOf` 已丢弃）。
  const specialOptionRows = useMemo(() => specialOptionRowsOf(po?.items), [po])

  const progress = operations?.progress
  const percent = Math.min(100, Math.max(0, Math.round(Number(progress?.percent ?? 0))))
  const doneCount = progress?.done ?? 0
  const totalCount = progress?.total ?? 0
  const chip = processingOrderStatusChipFor(po?.status)
  const positionCount = operations?.positions?.length ?? 0
  // 存量单恢复路径：无工序实例 且 非终态取消（cancelled 不可重生成）
  const showInstantiate = !operationsError && positionCount === 0 && po?.status !== 'cancelled'
  // 撤销入口：有可撤销的码 + 持有 processing:manage（客服/销售/财务看不到，避免按钮可见却 403）
  const canRevoke = hasPermission('processing:manage') && !!operations?.qr_token
  // 重新生成入口（issue #4287）：工序还在、码没了（= 撤销后）⇒ 才出现重发对象（不对有效码重发，
  // 那会静默作废已打印的纸）；cancelled 单不重发（避免又印出可扫的任务卡）。与 revoke 同权限码。
  const canRegenerate =
    hasPermission('processing:manage') &&
    positionCount > 0 &&
    !operations?.qr_token &&
    po?.status !== 'cancelled'
  // 工序还在但码没了 = 刚撤销过 ⇒ 任务卡占位文案不得再指向本页不存在的「补生成工序」。
  // issue #4946：洗水码粒度 = 商品行 ⇒ 该文案**逐张**生效（哪张缺码就写在哪张上）。
  const qrPlaceholderHint =
    positionCount > 0 && !operations?.qr_token
      ? '二维码已撤销（旧码已失效）—— 在本页点「重新生成二维码」可发新码'
      : undefined
  // 未定价工序实例（issue #4709 C）：有未定价实例 ⇒ 给「按当前价重算」入口。
  // 没有这个入口时，商家定价后**已实例化的旧单**永远算不出钱（且界面只说「未定价」、不给动作）。
  // 判据与后端同口径（V90 三态）：`price_state === 'unpriced'` 或单价为 null ⇒ 未定价；
  // **价 0 不算未定价**（显式定价 0 元，是有价）。
  const unpricedCount = (operations?.positions ?? []).reduce(
    (sum, set) =>
      sum +
      (set.operations ?? []).filter((op) => op.price_state === 'unpriced' || op.unit_price == null)
        .length,
    0,
  )
  // 写面端点方法级 processing:manage ⇒ 入口同码显隐（无权限角色不该看到按钮却 403）
  const canReprice = hasPermission('processing:manage') && unpricedCount > 0
  // 路线来源提示（issue #4307 交付物 2 / #4308 P1「静默回落」的用户侧可观测面）：
  // 四态 —— default 全不命中 / partial 只命中一维 / missing_route 两维命中但库里没路线。
  const routeNotice = routeSourceNotice(po?.routeSource, po?.routeKey, po?.routeRequestedKey)

  return (
    <div className="p-6 space-y-4">
      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500" data-testid="production-loading">
          <RefreshCw className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-neutral-200 bg-white py-10"
          data-testid="production-error"
        >
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-neutral-600">{error}</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => router.push('/processing-orders')}>
              返回列表
            </Button>
            <Button size="sm" data-testid="production-retry-button" onClick={load}>
              重试
            </Button>
          </div>
        </div>
      )}

      {!loading && !error && po && (
        <>
          {/* 头部：加工单号 / 订单号 / 状态 / 进度 / 交付日期 */}
          <div
            className="rounded-lg border border-neutral-200 bg-white p-5"
            data-testid="production-header"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <Button
                  variant="secondary"
                  size="sm"
                  aria-label="返回加工单列表"
                  onClick={() => router.push('/processing-orders')}
                >
                  <ArrowLeft className="w-4 h-4" />
                </Button>
                <div>
                  <h1 className="text-xl font-semibold text-neutral-900">加工单生产明细</h1>
                  <p className="mt-0.5 text-sm text-neutral-500">
                    加工单号
                    <span className="ml-2 font-medium text-neutral-900" data-testid="production-processing-order-no">
                      {po.processingOrderNo}
                    </span>
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                                {canRegenerate && (
                  <Button
                    size="sm"
                    disabled={regenerating}
                    loading={regenerating}
                    data-testid="production-regenerate-button"
                    onClick={handleRegenerate}
                  >
                    {!regenerating && <RefreshCw className="w-4 h-4 mr-1.5" />}
                    重新生成二维码
                  </Button>
                )}
                {canRevoke && (
                  <Button
                    variant="danger"
                    size="sm"
                    data-testid="production-revoke-button"
                    onClick={() => {
                      setRevokeError('')
                      setRevokedNotice('')
                      setRevokeOpen(true)
                    }}
                  >
                    <ShieldOff className="w-4 h-4 mr-1.5" />
                    撤销二维码
                  </Button>
                )}
                {/* 面料单不印水洗唛（issue #7891，用户 2026-10-27 逐字「面料单不能打印水洗唛，
                    应该打印加工单」）：只做裁剪的面料单没有洗水唛，纸上就是那张「面料单」（A4）
                    —— 入口旁一句话说清，免得车间找不到任务卡。 */}
                {isFabricOrder && (
                  <span className="text-xs text-neutral-500" data-testid="production-fabric-doc-hint">
                    面料单不印水洗唛 —— 打印只出「面料单」
                  </span>
                )}
                {/* 无 A4 可打（无 `order:detail`）且是面料单 ⇒ 连入口都不给（点开只会是空层） */}
                {(!isFabricOrder || printOrder) && (
                  <Button data-testid="production-print-button" onClick={handlePrint}>
                    <Printer className="w-4 h-4 mr-1.5" />
                    打印
                  </Button>
                )}
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <div className="text-xs text-neutral-500">订单号</div>
                <div className="mt-1 text-sm text-neutral-900" data-testid="production-order-no">
                  {po.orderNo ?? '—'}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500">状态</div>
                <div className="mt-1" data-testid="production-status">
                  <StatusBadge label={chip.label} color={chipToneClasses[chip.tone]} dot />
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500">交付日期</div>
                <div className="mt-1 text-sm text-neutral-900" data-testid="production-delivery-date">
                  {po.expectedDeliveryDate ?? '—'}
                </div>
              </div>
              {/* 加工费组合（issue #7833）：用户 2026-10-26 逐字「加工单有超高倒幅，但是在加工单的
                  各个环节都没有体现出来」⇒ 生产明细页页头一眼可见（整单并集，逐行明细在下面的部位区）。
                  取值 = 加工单**快照**行的 `processingItems[].name`（组合键真值源），缺 ⇒ 如实 `—`。 */}
              <div>
                <div className="text-xs text-neutral-500">加工费组合</div>
                <div className="mt-1 text-sm text-neutral-900" data-testid="production-processing-combo">
                  {processingComboTextOfRows(po.items) || '—'}
                </div>
              </div>
              <div>
                <div className="text-xs text-neutral-500">工序进度</div>
                <div className="mt-1 flex items-center gap-2">
                  <div
                    role="progressbar"
                    aria-valuenow={percent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="工序进度"
                    className="h-2 w-full max-w-[160px] overflow-hidden rounded-full bg-neutral-100"
                  >
                    <div className="h-full rounded-full bg-primary-600" style={{ width: `${percent}%` }} />
                  </div>
                  <span className="text-sm text-neutral-700 whitespace-nowrap" data-testid="production-progress-text">
                    {percent}%（已完成 {doneCount}/{totalCount} 道工序）
                  </span>
                </div>
              </div>
            </div>

            {/* 特殊选项（issue #7851）：服务端按 `specialOptions` 插工序 + 计件 ⇒ 页头必须按**商品行**
                说清「这几道活来自哪一行」。与「加工费组合」同一个块、同一套排版语言（label 小字 + 值正文），
                🔴 缺键 / 空数组 ⇒ **那一行整块不出现**（存量单未携带 ≠ `—`；也不留空块）。 */}
            {specialOptionRows.length > 0 && (
              <div className="mt-4 border-t border-neutral-200 pt-3" data-testid="production-special-options">
                <div className="text-xs text-neutral-500">特殊选项</div>
                <ul className="mt-1 space-y-1">
                  {specialOptionRows.map((row) => (
                    <li
                      key={row.key}
                      className="flex flex-wrap items-baseline gap-x-2"
                      data-testid="production-special-options-row"
                    >
                      <span className="text-xs text-neutral-500" data-testid="production-special-options-item">
                        {row.item}
                      </span>
                      <span className="text-sm text-neutral-900" data-testid="production-special-options-value">
                        {row.options}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* 作业单状态动作（issue #7634）：从销售订单「作业单」块搬来 —— 发加工 / 开始加工 /
              加工完成 / 取消 只在生产侧发生，订单详情只读。 */}
          <div
            className="rounded-lg border border-neutral-200 bg-white p-4"
            data-testid="production-actions-panel"
          >
            <h2 className="mb-3 text-sm font-medium text-neutral-900">作业单状态</h2>
            <ProcessingOrderActions po={po} onChanged={(next) => setPo(next)} />
          </div>

          {/* 路线来源提示（issue #4307）：default 高亮警示，partial 提示 —— 不得静默 */}
          {routeNotice && (
            <div
              className={cn(
                'rounded-lg border px-4 py-3 text-sm',
                routeNotice.tone === 'warning'
                  ? 'border-amber-300 bg-amber-50 text-amber-800'
                  : 'border-neutral-300 bg-neutral-50 text-neutral-700',
              )}
              data-testid={`production-route-${routeNotice.key}`}
            >
              <p className="flex items-center gap-2 font-medium">
                <AlertCircle className="w-4 h-4" />
                {routeNotice.title}
              </p>
              <p className="mt-1 text-xs opacity-90" data-testid={`production-route-${routeNotice.key}-detail`}>
                {routeNotice.detail}
              </p>
            </div>
          )}

          {/* 撤销成功反馈（issue #4240）：可见的「已撤销」，与占位态同时出现 */}
          {revokedNotice && (
            <p
              className="flex items-center gap-2 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700"
              data-testid="production-revoke-success"
            >
              <ShieldOff className="w-4 h-4" />
              {revokedNotice}
            </p>
          )}

          {/* 重新发码反馈（issue #4287）：撤销后恢复路径的可见结果 */}
          {regeneratedNotice && (
            <p
              className="flex items-center gap-2 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700"
              data-testid="production-regenerate-success"
            >
              <RefreshCw className="w-4 h-4" />
              {regeneratedNotice}
            </p>
          )}
          {regenerateError && (
            <p
              className="flex items-center gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
              data-testid="production-regenerate-error"
            >
              <AlertCircle className="w-4 h-4" />
              {regenerateError}
            </p>
          )}

          {/* 工序进度（按**套**分组：一套窗 = 一套，issue #4686；组头标「第 N 套 / 共 M 套」+ 必完工序标记） */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-medium text-neutral-900">工序进度</h2>
              {/* 存量加工单恢复路径（issue #4202）：无工序实例且非取消态时补生成 */}
              {showInstantiate && (
                <Button
                  size="sm"
                  disabled={instantiating}
                  loading={instantiating}
                  data-testid="production-instantiate-button"
                  onClick={handleInstantiate}
                >
                  {!instantiating && <Wrench className="w-4 h-4 mr-1.5" />}
                  补生成工序
                </Button>
              )}
              {/* 未定价实例的显式补价入口（issue #4709 C）：商家在矩阵里补了价之后，
                  已实例化的旧单必须**有动作可做**，否则工人那批活的钱算不出来。
                  只补 NULL、已有价（含显式定价 0 元）一律不动、报工进度不清零。 */}
              {canReprice && (
                <Button
                  size="sm"
                  disabled={repricing}
                  loading={repricing}
                  data-testid="production-reprice-button"
                  onClick={handleReprice}
                >
                  {!repricing && <RefreshCw className="w-4 h-4 mr-1.5" />}
                  按当前价重算未定价（{unpricedCount} 道）
                </Button>
              )}
            </div>
            {repriceError && (
              <p
                className="mb-3 flex items-center gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                data-testid="production-reprice-error"
              >
                <AlertCircle className="w-4 h-4" />
                {repriceError}
              </p>
            )}
            {repriceNotice && (
              <p
                className="mb-3 flex items-center gap-2 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700"
                data-testid="production-reprice-notice"
              >
                <RefreshCw className="w-4 h-4" />
                {repriceNotice}
              </p>
            )}
            {instantiateError && (
              <p
                className="mb-3 flex items-center gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                data-testid="production-instantiate-error"
              >
                <AlertCircle className="w-4 h-4" />
                {instantiateError}
              </p>
            )}
            {operationsError ? (
              <div
                className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-6 text-sm text-neutral-600"
                data-testid="production-operations-error"
              >
                <AlertCircle className="w-4 h-4 text-red-500" />
                {operationsError}
              </div>
            ) : (
              <ProductionProgressTable positions={operations?.positions} />
            )}
          </div>

          {/* 精裁输出清单（issue #5693）：给裁床的「裁多长（米）× 几片」。
              数据 = 服务端唯一实现（`ProcessingSetReadService`，与工人端扫码详情**同一份**
              `set_overview.cut_plan`）—— 本页只渲染，不算法、不折算单位。
              算不出来的格子留空 + 原因（服务端 `missing_reason`），**不**用 0 冒充。 */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="production-cut-plan">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-base font-medium text-neutral-900">精裁输出清单</h2>
              <span className="text-xs text-neutral-500">
                按套 × 货号 · 每行给出从哪一批裁多少布；算不出来的留空（不造数）
              </span>
            </div>
            {cutPlanError ? (
              <div
                className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-6 text-sm text-neutral-600"
                data-testid="production-cut-plan-error"
              >
                <AlertCircle className="w-4 h-4 text-red-500" />
                {cutPlanError}
              </div>
            ) : (
              <>
                {cutPlanTotal > cutPlanSets.length && (
                  <p className="mb-2 text-xs text-neutral-500" data-testid="production-cut-plan-truncated">
                    本单共 {cutPlanTotal} 套，这里只显示前 {cutPlanSets.length} 套（请分页核对后再下料）
                  </p>
                )}
                <CutPlanTable sets={cutPlanSets} />
              </>
            )}
          </div>

          {/* 计件汇总 */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <h2 className="mb-3 text-base font-medium text-neutral-900">计件汇总</h2>
            <PieceworkTable summary={piecework} />
          </div>

          {/* 「卡在哪」（切片 ③，issue #4776；设计 §6）：🔴 A 模式**只查「没开工」那一种**
              （裁定②-3）—— 「开了没完」属 C 模式（未落码），不在本面板。
              等待时长 = 上道 **done_at** 起算（不用 updated_at：它会被任何更新污染）。
              阈值来源随响应给出（threshold_source）⇒「阈值从哪来」不静默。 */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="production-stuck-points">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-base font-medium text-neutral-900">卡在哪</h2>
              <span className="text-xs text-neutral-500">
                只看还没开工的单；<strong>等待超过 {stuckPoints?.threshold_hours ?? '—'} 小时</strong>就列在这里（
                {stuckPoints?.threshold_source === 'history' ? '按历史中位数' : '按系统默认值'}）
              </span>
            </div>
            {stuckPointsError ? (
              <div
                className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-6 text-sm text-neutral-600"
                data-testid="production-stuck-points-error"
              >
                <AlertCircle className="w-4 h-4 text-red-500" />
                {stuckPointsError}
              </div>
            ) : (
              <>
                <p className="mb-2 text-xs text-neutral-500" data-testid="production-stuck-points-states">
                  本单工序三态：没开工 {stuckPoints?.states?.not_started ?? 0} 道 · 做了一半{' '}
                  {stuckPoints?.states?.in_progress ?? 0} 道 · 已完成 {stuckPoints?.states?.completed ?? 0} 道
                </p>
                {(stuckPoints?.stuck_total ?? 0) === 0 ? (
                  <p className="text-sm text-neutral-500" data-testid="production-stuck-points-empty">
                    没有「上道已交、这道没人扫」的工序
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {(stuckPoints?.stuck ?? []).map((row) => {
                      // 显示名走**唯一**口径 `operationDisplayName`（不在这里再拼一份）；
                      // 两个键都缺时退回既有空态符 `—`（不编占位工序名）。
                      const op = row.operation
                      return (
                        <li
                          key={`${row.set_id ?? ''}-${op?.operation_id ?? ''}`}
                          className="flex flex-wrap items-center justify-between gap-2 rounded border border-neutral-200 px-3 py-2 text-sm"
                          data-testid="production-stuck-points-row"
                        >
                          <span className="text-neutral-900">
                            <span className="font-medium">{row.set_no ?? row.processing_order_id ?? '—'}</span>
                            <span className="mx-1 text-neutral-400">·</span>
                            {operationDisplayName(op) || '—'}
                          </span>
                          <span className="text-red-600">
                            等了 {(row.stalled_hours ?? 0).toFixed(1)} 小时
                            {row.predecessor?.done_at
                              ? `（上道 ${formatFullDateTime(row.predecessor.done_at)} 完成）`
                              : ''}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </>
            )}
          </div>

          {/* 质检区（issue #7140 = #5652 的**商家面**）：按成品帘记录判定（谁检的 / 何时 / 合格·返工·报废 / 原因）。
              🔴 **只在持 `production:inspect` 时渲染**（判定属独立质检员岗位 + 管理员；用户 2026-10-17
              裁定「保持现状」⇒ 不是所有人都该看到这一区，也不是所有人都能录）。权限门在**调用方**
              —— `QualityCheckPanel` 自己不判码（避免两处口径）。
              ⚠️ 数据来自质检记录读面（按本单过滤），与「工序进度」「计件」并列、**不互相改写**：
              报工 = 数量事实，质检 = 成品帘判定（#5652 的两套口径并存）。 */}
          {hasPermission('production:inspect') && po?.id && (
            <div className="rounded-lg border border-neutral-200 bg-white p-5">
              <QualityCheckPanel processingOrderId={po.id} positions={operations?.positions} />
            </div>
          )}

          {/* 可打印水洗唛（issue #4946：一个商品行/部位一张；issue #7816 起纸型固定 50mm×150mm、
              份数 = 开数；码 = 该部位自己的 scan_url）；屏幕隐藏（display:none），点「打印任务卡」时只打印它
              🔴 面料单**整块不挂**（issue #7891，用户 2026-10-27 逐字「面料单不能打印水洗唛」）——
              不是藏起来，是不存在（藏起来仍会被 Ctrl+P 打出去）。 */}
          {!isFabricOrder && (
            <TaskCardPrint
              processingOrderNo={po.processingOrderNo}
              // 加工单公共属性：**每张**洗水码都要呈现
              customerName={po.customerName}
              positions={operations?.positions}
              qrPlaceholderHint={qrPlaceholderHint}
              // 工艺摘要（issue #4355）真值来源 = 加工单快照明细，按 order_item_id 逐张对齐
              items={po.items}
              printTarget={printTarget}
            />
          )}

          {/* 纸质作业单（A4，issue #7870）：与任务卡同范式 —— 屏幕隐藏、打印显形；
              预览实例**不传** `printTarget` ⇒ 不上纸，只有本次目标那一份上纸。
              纸面名按两型（issue #7891）：成品帘 ⇒「加工单」、面料单 ⇒「面料单」（组件内取真值）。 */}
          {printOrder && <ProcessingDoc order={printOrder} processingOrder={po} printTarget={printTarget} />}

          {/* 打印前的**纸面自检层**（issue #5914）：标签 50×150mm 的纸型没配好 = 整卷打废，
              所以洗水码也走「先看纸面再打」。预览实例**不传 printTarget** ⇒ 不上纸。

              🔴 免驱动直连（Web Bluetooth，issue #6439）那条通道的入口**在这个弹层的页脚**
              （issue #7288：用户 2026-10-18「做到水洗唛打印预览中，在右下角加个按钮叫蓝牙无线打印」）
              —— 与「打印」并排，两条通道在同一个视野里：预览里看到的就是要打的那张纸。
              两条通道的能力面与边界见 `frontend/admin-web/src/lib/label-print/capability.ts`。 */}
          <PrintDocPreview
            target={previewTarget}
            // 标题按作业单两型给名（issue #7891）：面料单的 A4 纸叫「面料单」，不叫「加工单」
            title={previewTitle}
            media={previewMedia}
            onPrint={printPreviewDoc}
            onClose={closePreview}
            docs={printDocs}
            onSelect={selectPreview}
            // 标签名与标题同源（issue #7891）：面料单那一份纸在标签上也必须叫「面料单」
            titleOf={(target) => printTargetTitle(target, docKind)}
            actions={
              // 蓝牙无线打印只服务洗水唛（标签纸）；A4 加工单走系统打印 + 驱动（同一台机器）
              previewTarget === 'labels' ? (
                <DirectLabelPrint
                  labels={washLabels}
                  onRecordPrint={recordPrintOnce}
                />
              ) : null
            }
          >
            {previewTarget === 'labels' && (
              <TaskCardPrint
                processingOrderNo={po.processingOrderNo}
                customerName={po.customerName}
                positions={operations?.positions}
                qrPlaceholderHint={qrPlaceholderHint}
                items={po.items}
                inline
              />
            )}
            {previewTarget === 'processing' && printOrder && (
              <ProcessingDoc order={printOrder} processingOrder={po} inline />
            )}
          </PrintDocPreview>

                    {/* 撤销二维码二次确认（issue #4240）：确认后才发请求 */}
          <Modal
            open={revokeOpen}
            onClose={() => {
              if (!revoking) setRevokeOpen(false)
            }}
            title="撤销二维码"
            footer={
              <div className="flex justify-end gap-2">
                <Button
                  variant="secondary"
                  disabled={revoking}
                  data-testid="production-revoke-cancel"
                  onClick={() => setRevokeOpen(false)}
                >
                  取消
                </Button>
                <Button
                  variant="danger"
                  loading={revoking}
                  data-testid="production-revoke-confirm"
                  onClick={handleRevoke}
                >
                  确认撤销
                </Button>
              </div>
            }
          >
            <div className="space-y-2 text-sm">
              <p className="text-neutral-600">
                确认撤销加工单{' '}
                <span className="font-medium text-neutral-900">{po.processingOrderNo}</span> 的二维码吗？
              </p>
              <p className="text-neutral-500">
                撤销后<span className="font-medium text-neutral-900">已打印的二维码立即失效</span>
                （工人扫旧码报工将失败）—— 包括每张水洗唛上的部位码。
              </p>
              {/* issue #4287：本页**有**重新发码入口了（撤销后出现「重新生成二维码」）⇒
                  #4949 那句「撤销后本页无法重新发码」的免责声明**不再为真**，必须撤掉
                  （否则它本身就是一句假话）；改为如实说明恢复路径与代价（需重新打印）。 */}
              <p className="text-neutral-500" data-testid="production-revoke-reissue-hint">
                撤销后旧码立即失效，但可以重新发码：本页会出现
                <span className="font-medium text-neutral-900">「重新生成二维码」</span>
                ，发新码后需重新打印任务卡。
              </p>
              {revokeError && (
                <p
                  className="flex items-center gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-red-600"
                  data-testid="production-revoke-error"
                >
                  <AlertCircle className="w-4 h-4" />
                  {revokeError}
                </p>
              )}
            </div>
          </Modal>
        </>
      )}
    </div>
  )
}
