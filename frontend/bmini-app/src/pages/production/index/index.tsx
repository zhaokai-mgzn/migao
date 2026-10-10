import { useCallback, useEffect, useRef, useState } from 'react'
import { View, Text, Button, Input, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import {
  completeByScan,
  getOrderOperations,
  getOrderPiecework,
  getWorkerOrderOperations,
  newReportRequestId,
  reportInFlightLock,
  reportOperationFree,
  scanResolve,
  shipOrder,
  shipWorkerOrder,
  type OrderOperations,
  type PieceworkSummary,
  type ProductionOperation,
  type ProductionPosition,
  type ReportPayload,
  type ScanOperationView,
  type ScanOverviewOperationView,
  type ScanResolveResult,
  type ScanSetOverviewView,
  type WorkLogRow,
} from '../../../services/productionService'
import { WorkerBar } from '../../../components/WorkerBar'
import { hasWorkerSession } from '../../../utils/workerSession'
import {
  PRODUCTION_WORKER_LOGIN_REQUIRED,
  WORKER_TAB_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import { operationDisplayName } from '../../../utils/operationDisplayName'
import { parseOrderIdFromQr, resolveOrderIdFromParams } from '../../../utils/productionQr'
import { canUseNativeScan, H5_SCAN_PHOTO_FAILED_HINT, H5_SCAN_PHOTO_HINT } from '../../../utils/platform'
// 非微信浏览器的扫码降级 = **复用**拍照入库那套本机解码（issue #5750）：
// 同一条链在任何浏览器（含 iOS Safari）都能用，且 0 次 LLM。
import { decodeQrFromImageData, loadPixelsFromFileH5 } from '../../../utils/inbound/barcodeDecode'
import {
  appendWorkLog,
  cacheOrderOperations,
  enqueuePendingReport,
  flushPendingReports,
  getCachedOrderOperations,
  listPendingReports,
  listWorkLogs,
  type WorkLogEntry,
} from '../../../utils/productionOffline'
import './index.scss'

/** 计件单价/金额展示（元，工序库口径；两位小数） */
function formatPrice(value: number | string): string {
  return Number(value || 0).toFixed(2)
}

/** 数量展示（去掉整数的小数尾巴：11 → 「11」而不是「11.0000000001」） */
function formatQty(value: number | string): string {
  return String(Number(value || 0))
}

/**
 * 本套工序明细 ⇒ 渲染分组（issue #4967 交付物 2）。
 *
 * <p>🔴 <b>缺值不渲染</b>：`set_overview` 缺失 / `positions` 为空 / 某部位没有任何带
 * `operation_id` 的工序 ⇒ 该组（或整块）**不产出**，绝不渲染「undefined 米 / ¥NaN」这种假数据。
 * 数据**只**来自服务端（`ProductionScanService#setOverview`）—— 页面不自己聚合、不另拉一份列表
 * 再按套重排（那就是第二份口径）。</p>
 */
function scanOverviewGroups(
  overview?: ScanSetOverviewView | null,
): Array<{ key: string; positionName: string; operations: ScanOverviewOperationView[] }> {
  const positions = overview?.positions
  if (!Array.isArray(positions)) return []
  return positions
    .map((position, index) => ({
      key: position.order_item_id || `${position.position_name || 'pos'}-${index}`,
      positionName: position.position_name || position.position_kind || '',
      operations: (position.operations || []).filter((operation) => operation?.operation_id),
    }))
    .filter((group) => group.operations.length > 0)
}

/** 报工明细时间（MM-DD HH:mm） */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * 操作记录的统一展示行（issue #4347 §3.2）。
 *
 * <p>两个来源：**服务端** `work_logs`（全单流水，换设备也在）与**本机** `WorkLogEntry`
 * （只在离线时兜底）。两者字段名不同 ⇒ 在这里收敛成同一形态，渲染处不再分支
 * （两处各写一份渲染必然漂移）。</p>
 */
interface DisplayLog {
  key: string
  workerName: string
  operation: string
  qty: number | string
  unit: string
  /** 毫秒时间戳；服务端给 ISO 串，本机给 number */
  at: number
}

function toDisplayLogs(serverLogs: WorkLogRow[] | undefined, localLogs: WorkLogEntry[]): DisplayLog[] {
  if (serverLogs && serverLogs.length > 0) {
    return serverLogs.map((row, index) => ({
      key: `${row.created_at ?? ''}-${row.operation_name}-${index}`,
      workerName: row.worker_name || '未署名',
      operation: row.operation_name,
      qty: row.qualified_qty,
      // 服务端流水不带单位（单位属工序实例）；留空而不是编一个
      unit: '',
      at: row.created_at ? Date.parse(row.created_at) : Number.NaN,
    }))
  }
  return localLogs.map((log) => ({
    key: log.requestId,
    workerName: log.worker_name || '未署名',
    operation: log.operation,
    qty: log.qty,
    unit: log.unit,
    at: log.createdAt,
  }))
}

/**
 * 本次可报的剩余数量 = 应做 − 已报（下限 0）。
 *
 * 未报过的工序 = 应做数量 ⇒ 与真值源「默认 = 应做数量、上限 = 应做数量」一致；
 * 已报过则默认剩余，避免默认值一报就撞服务端上限（服务端判据 `done_qty + qty ≤ qty`）。
 */
function remainingQty(operation: ProductionOperation): number {
  const remaining = Number(operation.qty || 0) - Number(operation.done_qty || 0)
  return remaining > 0 ? remaining : 0
}

/**
 * 工序显示名（issue #4963）：走**唯一**口径 ——
 * `frontend/bmini-app/src/utils/operationDisplayName.ts`（与 worker-h5 直接 import 的
 * `frontend/shared/operation-display.mjs` 逐字同语义；逐值等价由
 * `tests/unit_ci_workflows/test_operation_display_name_guard.py` 的 C7 钉住，改一份不改另两份 ⇒ 红）。
 *
 * 改前这里自拼 `[logical_name, position].filter(Boolean).join(' · ') || '工序'`，与 web/worker-h5
 * 在三种输入下渲染不同：① 缺 `logical_name` 时只显示部位（如「布帘」）而不退回快照名原文；
 * ② 键值带空白不 trim；③ 全缺时**编占位名**「工序」而不是给空串（调用方按空态渲染）。
 */
function operationLabel(operation: {
  operation?: string | null
  logical_name?: string | null
  position?: string | null
}): string {
  return operationDisplayName(operation)
}

/**
 * 工序选择器的标题 —— **与 `/w/`（worker-h5）逐字同源**（issue #6638）。
 *
 * <p>两个工人面是**同一个交互的两份实现**：老形态是「系统推一道 + 一行小字『不是这道？改』」，
 * 而车间工序本来就**不按固定顺序**做（用户 2026-10-10 逐字：「工人无法选取某个工序报工，
 * 因为工序不是固定顺序的」）—— 把正常动作写成「例外」入口是错的。这里改判为**正常的工序选择器**：
 * 候选含系统推断那道（显式选中）+ 全部备选，点哪道就领哪道。</p>
 *
 * <p>🔴 判据 = `frontend/bmini-app/tests/production-scan-complete.test.tsx` 的两条
 * （候选与选中态 / 与 `/w/` 文案逐字同源）—— 任一侧改文案而另一侧没改 ⇒ 红。</p>
 */
export const SCAN_OPERATION_PICKER_TITLE = '选工序（点哪道就领哪道）'

/** 选择器里的一个候选 = 系统推断那道 或 服务端给的备选。 */
type OperationChoice =
  | NonNullable<ScanResolveResult['operation']>
  | ScanResolveResult['alternatives'][number]

/**
 * 可选的工序候选 = **系统推断的那道 + 服务端给的备选**（与 `/w/` 同口径）。
 *
 * <p>🔴 选择器里必须**包含当前这道**：不含它，工人就看不出系统给他推的是哪道，
 * 也就无从判断"要不要改成别的"。改前只列备选，正是这个毛病。</p>
 */
function pickableOperations(view: ScanResolveResult): OperationChoice[] {
  const candidates: OperationChoice[] = []
  if (view.operation) candidates.push(view.operation)
  for (const alternative of view.alternatives ?? []) candidates.push(alternative)
  return candidates.filter((candidate) => !!candidate?.operation_id)
}

/** 按 id 在本单工序列表里找该工序（A 模式离线兜底要用它的 `done_qty` 算剩余数量）。 */
function findOperation(
  detail: OrderOperations | null,
  operationId: string,
): ProductionOperation | undefined {
  for (const position of detail?.positions || []) {
    const found = position.operations.find((item) => item.id === operationId)
    if (found) return found
  }
  return undefined
}

/** 该工序的累计计件金额（服务端 `piecework.per_operation` 按工序名给；没有则不展示） */
function pieceworkOf(summary: PieceworkSummary | null, operationName: string): number | null {
  const found = summary?.per_operation?.find((item) => item.operation === operationName)
  return found ? Number(found.amount) : null
}

/**
 * 部位规格摘要（issue #4347 §3.1）：工人要能核对自己做的是哪一件。
 *
 * <p>口径：**只显示服务端真的给了的键**（缺键就不显示）—— 不补默认值、不显示占位符。
 * 后端在订单行取不到时一个规格键都不加（脏数据），此时这里自然什么都不显示。</p>
 */
function specSummary(position: ProductionPosition): string[] {
  const parts: string[] = []
  const size = [position.width, position.height].filter(
    (v) => v !== null && v !== undefined && v !== '',
  )
  if (size.length > 0) parts.push(`尺寸 ${size.join(' × ')}`)
  if (position.craft) parts.push(String(position.craft))
  if (position.openCount !== null && position.openCount !== undefined && position.openCount !== '') {
    parts.push(`开数 ${position.openCount}`)
  }
  if (position.cuttingMode) parts.push(String(position.cuttingMode))
  if (position.isShaped !== null && position.isShaped !== undefined) {
    parts.push(position.isShaped ? '定型' : '不定型')
  }
  if (position.fullness !== null && position.fullness !== undefined && position.fullness !== '') {
    parts.push(`褶倍 ${position.fullness}`)
  }
  const meters = position.fabric_meters ?? position.processingMeters
  if (meters !== null && meters !== undefined && meters !== '') {
    parts.push(`用料 ${meters} 米`)
  }
  // 批次指派（issue #5145 阶段 1）：服务端**只在真的指派过批次时**才下发这两键
  // ⇒ 缺键 = 未指派（不是缺数据）。两键必须都在才追加（只有一个 ⇒ 不显示半句话）。
  const { batch_no: batchNo, batch_meters: batchMeters } = position
  const hasBatchNo = batchNo !== null && batchNo !== undefined && batchNo !== ''
  const hasBatchMeters =
    batchMeters !== null && batchMeters !== undefined && batchMeters !== ''
  if (hasBatchNo && hasBatchMeters) parts.push(`批次 ${batchNo} 裁 ${batchMeters} 米`)
  return parts
}

/**
 * 工人端扫码报工（issue #3997，M4-G-3；issue #4206 补齐弱网降级/数量可改/计件与明细/带参直达）
 *
 * 链路：扫一扫 / 手输单号 / **带参跳转直达** → 本单工序（按部位分组，含应做数量/单位/单价）
 *   → 改「完成数量」（默认 = 应做数量，上限 = 应做数量）→「完成报工」
 *   → 刷新进度 + 计件金额累计 + 本单报工明细 → 全部活跃工序实例报满（#4961 口径） → 「✅ 订单生产完成」。
 *
 * 弱网降级（issue #4206）：`loadOrder` 成功即把待做清单落本机 storage，断网时命中缓存仍出清单
 * （显式标注离线，不冒充服务端真值）；报工**传输层**失败进本机队列，联网后自动补传
 * （复用同一幂等键 ⇒ 服务端不重复计件）。
 *
 * 报工失败只展示后端 message，**不清空列表**（工人可继续报其它工序）。
 */
export default function ProductionPage() {
  const { user } = useAuthStore()
  /**
   * 本机有没有工人身份（issue #6467 判据 3）—— **写入口的渲染前提**。
   *
   * <p>报工写面只认工号 + PIN 签发的工人 session（服务端 `resolveIdentity` 读
   * `X-Worker-Session-Id`）：没有它时渲染写入口 = 用户点一次换一个 401
   * （现场实测：管理员在 H5 点「完成报工」→ 401 → 请求层把商家登录态清掉、踢回登录页，
   * 重登再点仍然如此）。⇒ 没有身份就**不给写入口**，改为可行动的引导。</p>
   */
  const workerReady = hasWorkerSession()
  const [detail, setDetail] = useState<OrderOperations | null>(null)
  const [manualId, setManualId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  /** 发货（issue #4483 = #4347 §二.2）：工人自己录单号并发货，不等管理端 */
  const [trackingNo, setTrackingNo] = useState('')
  const [shipping, setShipping] = useState(false)
  const [shipped, setShipped] = useState(false)
  const [orderCompleted, setOrderCompleted] = useState(false)
  /**
   * 报工在飞锁（issue #4116 §5-1）：值 = 正在报工的工序 id（null = 空闲）。
   * 锁本体在 `productionService.reportInFlightLock`（可被单测直接证明「第二笔被拒」）；
   * 这里只持有它的**可见面**：按钮 disabled + 「报工中…」文案。
   * 为什么必须有：工人手快连点两次「完成报工」会发出**两个**请求（各自一个幂等键 ⇒
   * 服务端按幂等键去重挡不住），一次报工就被记两遍。服务端侧另有幂等键与数量上限两道
   * （见 ProductionService.report）。
   */
  const [reportingId, setReportingId] = useState<string | null>(null)
  /** 各工序的「完成数量」输入（缺省 = 剩余应做数量；报工成功后清空以回到新的默认值） */
  const [qtyInputs, setQtyInputs] = useState<Record<string, string>>({})
  /** 计件金额累计（本单 total + 每工序 per_operation；服务端口径，与两套账分离） */
  const [piecework, setPiecework] = useState<PieceworkSummary | null>(null)
  /** 本单报工明细（人/工序/数量/时间；本机持久化，离线也看得到） */
  const [workLogs, setWorkLogs] = useState<WorkLogEntry[]>([])
  /** 待补传条数（> 0 时页面提示，工人知道报工没丢） */
  const [pendingCount, setPendingCount] = useState(0)
  /** 当前离线态（本次展示的是本机缓存的待做清单，不是服务端真值） */
  const [offline, setOffline] = useState(false)
  /**
   * A 模式一屏（切片 ②）：扫新码后的「工序 + 应做数量 + 【完成】」。
   *
   * <p>设计 §4.1：一次扫码 = 1 步 —— 找到哪一套窗/哪个部位/该做哪一道都由**码 + 系统推断**给出；
   * 唯一的额外交互是「不是这道？改」（只在需要时才点）。`null` = 没有在屏的一屏。</p>
   */
  const [scanScreen, setScanScreen] = useState<{ token: string; view: ScanResolveResult } | null>(
    null,
  )
  /** 深链只处理一次（避免 React 严格模式/重复挂载时重复请求） */
  const launchedRef = useRef(false)

  /** 刷新计件金额累计（失败不影响工序列表：计件展示是增强，不是主路径） */
  const refreshPiecework = useCallback(async (orderId: string) => {
    const res = await getOrderPiecework(orderId)
    if (res?.success && res.data) setPiecework(res.data)
  }, [])

  /** 补传离线队列（复用幂等键）+ 把结果反映到页面（明细/待补传条数/被拒原因） */
  const flushQueue = useCallback(async (orderId: string) => {
    const result = await flushPendingReports()
    setPendingCount(listPendingReports().length)
    if (result.sent.length > 0) setWorkLogs(listWorkLogs(orderId))
    if (result.rejected.length > 0) {
      const [first] = result.rejected
      setError(`补传被拒：${first.operationName}（${first.message}），请重新报工`)
    }
  }, [])

  /** 拉取工序列表（扫码成功 / 手输查单 / 深链直达共用） */
  const loadOrder = useCallback(
    async (rawId: string) => {
      const orderId = (rawId || '').trim()
      if (!orderId) {
        Taro.showToast({ title: '请输入加工单号', icon: 'none' })
        return
      }
      setLoading(true)
      setError('')
      // 🔴 读面按**本机有没有工人身份**分流（issue #5647 G4）：
      //  · 有工人 session ⇒ `GET /api/worker/production/orders/{id}/operations`（工人路径）——
      //    一张只登录了工号 + PIN 的车间设备没有商家会话，走 `/api/admin/**` 必然 401、页面全空；
      //    而工人被 `ADMIN_API_REJECTED_ROLES` 拒在 `/api/admin/**` 外（零商家权限，#4727）
      //    ⇒ 「给工人商家权限」这条出路不存在。
      //  · 无工人 session（纯商家设备）⇒ 保持 `/api/admin/**` **逐字不变**（商家打不开 = 红线）。
      // 两条路读的是服务端**同一份**读面（`ProductionService#getOperations`）⇒ 字段面逐字同源。
      const res = hasWorkerSession()
        ? await getWorkerOrderOperations(orderId)
        : await getOrderOperations(orderId)
      if (!res.success || !res.data) {
        // 只有**传输层**失败才用本机缓存顶（断网/超时）；服务端明确答复「不存在/无权限」时
        // 不得拿旧缓存冒充真值（否则工人会对着已作废的清单报工）
        const cached = res.offline ? getCachedOrderOperations(orderId) : null
        setLoading(false)
        if (!cached) {
          setError(res.message || '未找到该加工单，请确认单号')
          return
        }
        // 弱网降级（issue #4206）：命中本机缓存 ⇒ 仍出待做清单，但**显式标注离线**
        setDetail(cached)
        setManualId(orderId)
        setOffline(true)
        setWorkLogs(listWorkLogs(orderId))
        setPendingCount(listPendingReports().length)
        return
      }
      setLoading(false)
      setDetail(res.data)
      setManualId(orderId)
      setOffline(false)
      cacheOrderOperations(orderId, res.data)
      setWorkLogs(listWorkLogs(orderId))
      // 有网 ⇒ 顺手补传（队列里的东西不该等到下一次断网才走）
      await flushQueue(orderId)
      await refreshPiecework(orderId)
    },
    [flushQueue, refreshPiecework],
  )

  /** 深链/带参跳转直达（issue #4206 判据 4）：`?order_id=…` / `?qr=…` / `?token=…` */
  useEffect(() => {
    if (launchedRef.current) return
    launchedRef.current = true
    const params = (Taro.getCurrentInstance?.() as any)?.router?.params
    const orderId = resolveOrderIdFromParams(params)
    if (orderId) void loadOrder(orderId)
  }, [loadOrder])

  /**
   * 扫码结果 → 页面（**原生扫码与拍照识别共用这一条**）。
   *
   * <p>三级优先（与后端「新码优先，未命中只回落」逐字同序）：</p>
   * <ol>
   *   <li><b>新码</b>（套 × 部位）⇒ 出 **A 模式一屏**（工序 + 应做数量 + 【完成】），
   *       同时把本单工序/进度/明细拉到屏下方；</li>
   *   <li><b>旧码</b>（加工单级）⇒ 显式提示「必须选部位」并带出本单工序
   *       —— 🔴 绝不默认取第 1 套（默认 = 把进度/计件记到错的窗上）；</li>
   *   <li>其余（码里带加工单号/单号本身）⇒ 既有形态，逐道报工。</li>
   * </ol>
   */
  const resolveScannedCode = useCallback(
    async (raw: string) => {
      const scan = await scanResolve(raw)
      if (scan?.success && scan.data) {
        const view = scan.data
        if (view.granularity === 'set_position') {
          setScanScreen({ token: raw, view })
          setError('')
          if (view.order_id) await loadOrder(view.order_id)
          return
        }
        if (view.order_id) {
          // 旧码只到加工单级 ⇒ 部位**必须**由工人选（绝不默认取第 1 套）。用 toast 提示而不是
          // setError：loadOrder 自己也会写 error（单号不存在等），两处都写 error 会互相覆盖。
          Taro.showToast({ title: '旧码不含套号/部位：请选择部位后报工', icon: 'none' })
          await loadOrder(view.order_id)
          return
        }
      }
      const orderId = parseOrderIdFromQr(raw)
      if (!orderId) {
        Taro.showToast({ title: '无法识别该二维码，请手动输入单号', icon: 'none' })
        return
      }
      await loadOrder(orderId)
    },
    [loadOrder],
  )

  /**
   * 非微信浏览器（含 iPhone Safari）的降级：**拍照识别**（issue #5750）。
   *
   * <p>此前这里只有一条路：toast「当前浏览器不支持扫码，请在手输框输入加工单号」——
   * 而「在不在微信里」与手机品牌无关 ⇒ iPhone / Android / 桌面浏览器**一视同仁**都要手敲单号。</p>
   *
   * <p>现在：`Taro.chooseImage`（h5 真实实现，拉起相机/相册）→ `<img>`/canvas 取像素 →
   * `jsQR` **本机解码**（0 次 LLM）→ 解出来的原文交给 {@link resolveScannedCode}
   * —— 与原生扫码**同一条**识别链，不平行造第二条。</p>
   */
  const handlePhotoScan = useCallback(async () => {
    Taro.showToast({ title: H5_SCAN_PHOTO_HINT, icon: 'none' })
    try {
      const res: any = await Taro.chooseImage({ count: 1, sourceType: ['camera', 'album'] })
      // h5：`tempFiles[].originalFileObj` 是真 File（优先用它，免得再走一次 blob URL 拉取）；
      // 小程序侧只有路径 ⇒ 回落 `tempFilePaths[0]`。
      const src = res?.tempFiles?.[0]?.originalFileObj || res?.tempFilePaths?.[0]
      const pixels = src ? await loadPixelsFromFileH5(src) : null
      const text = pixels ? decodeQrFromImageData(pixels) : null
      if (!text) {
        // 取消 / 没权限 / 照片里没码：一律给**可行动**文案（重拍 + 手输），不静默
        Taro.showToast({ title: H5_SCAN_PHOTO_FAILED_HINT, icon: 'none' })
        return
      }
      await resolveScannedCode(text)
    } catch {
      Taro.showToast({ title: H5_SCAN_PHOTO_FAILED_HINT, icon: 'none' })
    }
  }, [resolveScannedCode])

  /**
   * 扫一扫（切片 ② A 模式接线）。
   *
   * <p>微信内置浏览器 ⇒ `Taro.scanCode` 原生通道；其余 h5 环境 ⇒ {@link handlePhotoScan}。
   * issue #5650 的「先判平台再调」保持不变：纯浏览器下调 `Taro.scanCode` 只会「什么都没发生」。</p>
   */
  const handleScan = useCallback(async () => {
    if (!canUseNativeScan()) {
      await handlePhotoScan()
      return
    }

    try {
      const res = await Taro.scanCode({ scanType: ['qrCode'] })
      const raw = String(res?.result || '').trim()
      if (!raw) {
        Taro.showToast({ title: '无法识别该二维码，请手动输入单号', icon: 'none' })
        return
      }
      await resolveScannedCode(raw)
    } catch {
      Taro.showToast({ title: '扫码未完成，请手动输入单号', icon: 'none' })
    }
  }, [handlePhotoScan, resolveScannedCode])

  /**
   * 逐道「完成报工」—— 报工页的写入口（issue #5647 G10 → **issue #6598 改口径**）。
   *
   * <p>🔴 <b>2026-10-09 用户裁定（逐字）</b>：「当前工人报工只能按固定顺序报工，这个设计是不对的，
   * <b>允许工人自由报工</b>」；开放范围当场选定 = <b>整张加工单内任选任意工序（不扫码也能自由报）</b>。
   * 看到该现象的链路 = 扫码报工（扫部位任务码后系统只给「下一道」，要给「不是这道？改」才换得了）。</p>
   *
   * <p>于是本函数有**两条**写路，判别键 = 本部位有没有任务码：</p>
   * <ol>
   *   <li><b>有码</b>（{@code position.part_token}）⇒ {@code completeByScan}：
   *       <b>扫码保留为快捷定位</b>（服务端按码校验归属，跨部位 ⇒ 422），不是唯一入口；</li>
   *   <li><b>无码</b> ⇒ {@code reportOperationFree}：工序由工人在本单清单里<b>显式选</b>，
   *       服务端仍校验「属于本加工单 + 未软删 + 同租户」。</li>
   * </ol>
   *
   * <p>两条路收口在服务端**同一份**记账实现（{@code ProductionService.applyReport}：
   * CAS 推进 + {@code done_at} + 完工判定）⇒ 读数逐值一致，不新造第二份口径。</p>
   *
   * <p>⚠️ <b>已作废的旧判据（留痕，不删）</b>：改前这里写的是「<b>没有码就不提供写入口</b>」，
   * 理由是「退回 URL 定工序 = 把防呆整条绕开」。🔴 该理由与今日代码不符：那条路走的就是同一份
   * {@code applyReport}（{@code done_at} / 一次事务 / CAS 一处不差），归属校验走
   * {@code ProductionService.requireActiveOperation}（同租户 + 未软删 + 属于本加工单）。
   * ⇒ 「必须落在本次扫码码内」这一条按用户裁定<b>放开</b>；而「<b>工序必须显式确定</b>」
   * （issue #4694 硬约束）与「写入口只在有工人身份时渲染」（issue #6467）<b>一条都没放宽</b>。</p>
   *
   * <p>数量默认 = 剩余应做，可改；前端守上限，服务端仍兜底。失败只展示后端 message，不清空列表。</p>
   */
  const handleReport = useCallback(
    async (position: ProductionPosition, operation: ProductionOperation) => {
      if (!detail) return
      // 纵深：写入口本就只在有工人身份时渲染（见 JSX），这里再兜一道 ——
      // 绝不用「没有工人身份」的请求去换一个必然的 401（issue #6467）
      if (!workerReady) return
      const orderId = detail.order_id
      const token = position.part_token
      const remaining = remainingQty(operation)
      const typed = qtyInputs[operation.id]
      const qty = typed === undefined || typed === '' ? remaining : Number(typed)
      // 数量上限（issue #4206 判据 1）：前端先拦一道，服务端 assertWithinPlannedQty 仍兜底。
      // 已报满的工序直接说清楚（旧行为是发一个必然被服务端拒的请求换回等价文案）
      if (remaining <= 0) {
        setError('该工序已报满，无需重复报工')
        return
      }
      if (!Number.isFinite(qty) || qty <= 0) {
        setError('完成数量必须大于 0')
        return
      }
      if (qty > remaining) {
        setError(
          `数量超上限：本次最多可报 ${formatQty(remaining)}${operation.unit}`
            + `（应做 ${formatQty(operation.qty)} − 已报 ${formatQty(operation.done_qty)}）`,
        )
        return
      }
      // in-flight 锁（issue #4116 §5-1）：连点第二次直接丢弃 —— 不发第二个请求。
      // 测试前置：锁是模块级单例（跨用例残留），故用例之间必须 `reportInFlightLock.release()`
      // 复位；此处**不做**兜底复位 —— 兜底会掩盖「上一次报工没走完 finally」的真实缺陷。
      if (!reportInFlightLock.tryAcquire()) return
      const requestId = newReportRequestId()
      // 🔴 身份**不在请求体里**（issue #4733）：worker_id/worker_name 已从契约移除，
      // 服务端从工人 session（X-Worker-Session-Id）解身份 —— 前端传什么都不影响「这笔活记到谁头上」。
      const payload: ReportPayload = {
        qty,
        qualified_qty: qty,
        work_type: 'normal',
      }
      setReportingId(operation.id)
      setError('')
      try {
        // 有码 ⇒ 扫码端点（按码定位部位）；无码 ⇒ 无码端点（工序由工人显式选，issue #6598）
        const res = token
          ? await completeByScan(token, operation.id, requestId, payload)
          : await reportOperationFree(orderId, operation.id, requestId, payload)
        if (!res.success) {
          if (res.offline) {
            // 弱网降级：进本机队列（幂等键 + 报工凭证随队列项落盘，补传复用它们 ⇒ 不会重复计件）
            enqueuePendingReport({
              requestId,
              // 🔴 issue #6598：无码条目必须**显式**标记 —— 否则补传会把「本来就不需要码」
              // 误判成「旧版本缺凭证」而出队丢弃（静默丢单）。
              kind: token ? 'scan' : 'free',
              token: token || '',
              orderId,
              operationId: operation.id,
              operationName: operation.operation,
              unit: operation.unit,
              payload,
              // 工人在界面上确认过数量 ⇒ 补传原样发出（与在线逐字同形）
              sendQty: true,
              createdAt: Date.now(),
            })
            setPendingCount(listPendingReports().length)
            setError(`${res.message}——已存入本机待补传队列，联网后自动补传（不会重复计件）`)
            return
          }
          setError(res.message || '报工失败，请重试')
          return
        }
        appendWorkLog(orderId, {
          requestId,
          // 本机缓存里的展示名取**服务端回执**（res.data.worker_name）而不是请求体：
          // 请求体已不含身份，而服务端才知道这笔到底记到了谁头上
          worker_name: res.data?.worker_name || '未署名',
          operation: operation.operation,
          qty,
          unit: operation.unit,
          createdAt: Date.now(),
        })
        setWorkLogs(listWorkLogs(orderId))
        setQtyInputs((prev) => {
          const next = { ...prev }
          delete next[operation.id]
          return next
        })
        if (res.data?.order_completed) setOrderCompleted(true)
        // 复用同一入口刷新进度（报工成功才刷新；回放结果同样刷新以对齐服务端真值）
        await loadOrder(orderId)
      } finally {
        // 任何出口（成功/失败/抛错）都必须解锁，否则一次网络异常会把按钮永久锁死
        reportInFlightLock.release()
        setReportingId(null)
      }
    },
    [detail, user, qtyInputs, loadOrder, workerReady],
  )

  /**
   * A 模式【完成】（切片 ② / 设计 §4.1）：一屏上的工序 ⇒ 一次事务（明细 + CAS + done_at + 完工）。
   *
   * <p>数量**不传**（服务端缺省取「剩余应做」——「报工只确认，不手工心算」）；
   * 身份**不传**（服务端从工人 session 解）；幂等键随请求头走，重试复用它。</p>
   *
   * <p>弱网降级：**复用既有补传队列**（幂等键 + 报工凭证入队，补传复用 ⇒ 不会重复计件），补传走
   * **同一条** {@code /scan/complete} 端点（issue #5647 G10 起写面只有这一条路）。</p>
   */
  const handleScanComplete = useCallback(async () => {
    if (!scanScreen) return
    // 纵深：同 handleReport —— 无工人身份绝不发写请求（issue #6467）
    if (!workerReady) return
    const { token, view } = scanScreen
    const operation = view.operation
    // 未确定工序 ⇒ 屏上根本不渲染【完成】（见 JSX）⇒ 这里再兜一道，绝不带 null 去报工
    if (!operation) return
    const orderId = view.order_id
    // 本机展示/离线补传要用的数量：优先按本单工序列表算剩余（= 服务端缺省口径），列表还没到时退回应做
    const known = findOperation(detail, operation.operation_id)
    const qty = known ? remainingQty(known) : Number(operation.qty || 0)
    // in-flight 锁（issue #4116 §5-1）：连点第二次直接丢弃 —— 不发第二个请求
    if (!reportInFlightLock.tryAcquire()) return
    const requestId = newReportRequestId()
    setReportingId(operation.operation_id)
    setError('')
    try {
      const res = await completeByScan(token, operation.operation_id, requestId)
      if (!res.success) {
        if (res.offline) {
          const payload: ReportPayload = { qty, qualified_qty: qty, work_type: 'normal' }
          enqueuePendingReport({
            requestId,
            token,
            orderId,
            operationId: operation.operation_id,
            operationName: operationLabel(operation),
            unit: operation.unit || '',
            payload,
            // 在线路径**不传数量**（服务端取剩余应做）⇒ 补传也不传，逐字同形
            sendQty: false,
            createdAt: Date.now(),
          })
          setPendingCount(listPendingReports().length)
          setError(`${res.message}——已存入本机待补传队列，联网后自动补传（不会重复计件）`)
          return
        }
        setError(res.message || '报工失败，请重试')
        return
      }
      appendWorkLog(orderId, {
        requestId,
        // 展示名取**服务端回执**（请求体不含身份，服务端才知道这笔记到了谁头上）
        worker_name: res.data?.worker_name || '未署名',
        operation: operationLabel(operation),
        qty,
        unit: operation.unit || '',
        createdAt: Date.now(),
      })
      setWorkLogs(listWorkLogs(orderId))
      if (res.data?.order_completed) setOrderCompleted(true)
      // 一屏闭环（设计 §4.1 ⑥）：服务端给了「下一道」⇒ 就地换到屏上（工人不用重新扫码）；
      // 本套做完 ⇒ 收屏。刷新本单进度/明细与「下一道」同源，避免屏上/列表两处口径不一致。
      const next = res.data?.next_operation
      setScanScreen(
        next
          ? {
              token,
              view: {
                ...view,
                operation: next,
                alternatives: [],
                set_progress: res.data?.set_progress ?? view.set_progress,
                // 本套明细（issue #4967 交付物 2）：回执原样透传（与解析面同一份口径）
                set_overview: res.data?.set_overview ?? view.set_overview,
                completed: res.data?.set_completed ?? false,
              },
            }
          : null,
      )
      await loadOrder(orderId)
    } finally {
      // 任何出口（成功/失败/抛错）都必须解锁，否则一次网络异常会把按钮永久锁死
      reportInFlightLock.release()
      setReportingId(null)
    }
  }, [scanScreen, detail, loadOrder, workerReady])

  /** 「不是这道？改」（设计 §3.3）：显式指定工序 ⇒ **服务端**校验它属于本次扫码的部位/套 */
  const handlePickAlternative = useCallback(
    async (operationId: string) => {
      if (!scanScreen) return
      const res = await scanResolve(scanScreen.token, operationId)
      if (res.success && res.data) {
        setScanScreen({ token: scanScreen.token, view: res.data })
        setError('')
        return
      }
      setError(res.message || '该工序不可选，请重新扫码')
    },
    [scanScreen],
  )

  /** 服务端是否给了操作记录（决定标题口径：全单流水 vs 本机兜底） */
  const serverLogsAvailable = (detail?.work_logs?.length ?? 0) > 0
  const displayLogs = toDisplayLogs(detail?.work_logs, workLogs)
  /**
   * 发货（issue #4483 = #4347 §二.2）：录货运单号 ⇒ 订单 shipped。
   *
   * <p>后端是**原子入口**（记物流 + 流转状态一次完成），故这里只调一次 ——
   * 分两次调用中间失败会产生「有单号但没发货」或「发货了没单号」的静默不一致。</p>
   *
   * <p>🔴 **端点按本机身份分流**（issue #6472，S1）：工人身份（{@link hasWorkerSession}，
   * 单一真值）⇒ 走 `POST /api/worker/shipment/orders/{id}/ship`（`/api/admin/**` 把 `worker`
   * 放进拒绝集合 ⇒ 纯工人设备打商家端点**必 403**，见 issue #5648）；无工人身份（纯商家设备）
   * ⇒ 商家端点 `shipOrder` **逐字不变**。两条路都读服务端同一张发货单链
   * （`OrderShipmentService`）⇒ 落库形状同源，不新造第二个发货实现。</p>
   *
   * <p>失败只展示后端 message（守卫/状态不符都由后端判定并指名原因），**不猜**。</p>
   */
  const handleShip = useCallback(async () => {
    if (!detail) return
    const no = trackingNo.trim()
    if (!no) {
      setError('请先填写货运单号')
      return
    }
    setShipping(true)
    setError('')
    try {
      // 工人身份 ⇒ 工人端点（实发明细由读面 `positions` 映射，见 `workerShipItems`）；
      // 商家身份 ⇒ 商家端点（body 只有单号/承运商，一字不变）。
      const res = hasWorkerSession()
        ? await shipWorkerOrder(detail.order_id, no, detail.positions)
        : await shipOrder(detail.order_id, no)
      if (!res.success) {
        setError(res.message || '发货失败，请重试')
        return
      }
      setShipped(true)
      setTrackingNo('')
    } finally {
      setShipping(false)
    }
  }, [detail, trackingNo])

  /**
   * 「去登录工人身份」（issue #6467 判据 3）：跳**登录页的工人入口**
   * （`/pages/auth/login/index?tab=worker`，路由常量 = `utils/inbound/gaps.ts` 单一真值）。
   *
   * <p>不去 `switchTab`、也不跳独立的 `pages/worker/login/index`：前者落商家 tabBar、
   * 后者与登录页的工人 tab 是同一个身份链的第二个入口（入口越少越不会被走错）。</p>
   */
  const handleGoWorkerLogin = useCallback(() => {
    Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  const positions = detail?.positions || []
  const progress = detail?.progress
  const percent = progress?.percent ?? 0
  const isCompleted =
    orderCompleted || (!!progress && progress.total > 0 && progress.done >= progress.total)

  /** 数量输入的当前值（未输入时 = 剩余应做数量） */
  const qtyValueOf = (operation: ProductionOperation): string => {
    const typed = qtyInputs[operation.id]
    return typed === undefined ? String(remainingQty(operation)) : typed
  }

  return (
    <ScrollView scrollY className='production-page'>
      {/* 顶部：扫一扫 + 手输单号兜底 */}
      <View className='production-scan-bar'>
        <Button className='production-scan-bar__btn' onClick={handleScan}>
          扫一扫
        </Button>
        <Text className='production-scan-bar__hint'>扫描加工单二维码，自动带出本单工序</Text>
      </View>

      <View className='production-manual'>
        <Input
          className='production-manual__input'
          value={manualId}
          placeholder='或手输加工单号'
          onInput={(event) => setManualId(event.detail.value)}
        />
        <Button className='production-manual__btn' onClick={() => loadOrder(manualId)}>
          查单
        </Button>
      </View>

      {/* 弱网降级（issue #4206）：离线态必须显式标注，不得把本机缓存冒充服务端真值 */}
      {offline && (
        <View className='production-offline'>
          <Text className='production-offline__text'>
            {`离线模式：展示本机缓存的待做清单${
              pendingCount > 0 ? `（待补传 ${pendingCount} 条报工）` : ''
            }`}
          </Text>
        </View>
      )}

      {error !== '' && (
        <View className='production-error'>
          <Text className='production-error__text'>{error}</Text>
        </View>
      )}

      {/* 🔴 无工人身份 ⇒ 不给写入口，改为可行动的引导（issue #6467 判据 3）：
          报工写面只认工号 + PIN 签发的工人 session —— 显示写入口只会换回一个 401
          （现场实测：管理员在 H5 点「完成报工」→ 401 → 请求层清商家登录态 + 踢回登录页）。
          有工人身份时本块**不渲染**，页面逐字保持原状。 */}
      {!workerReady && (
        <View className='production-worker-login-required'>
          <Text className='production-worker-login-required__text'>
            {PRODUCTION_WORKER_LOGIN_REQUIRED}
          </Text>
          <Button className='production-worker-login-required__btn' onClick={handleGoWorkerLogin}>
            去登录工人身份
          </Button>
        </View>
      )}

      {/* A 模式一屏（切片 ② / 设计 §4.1）：工序 + 应做数量 ⇒【开工】；工序选择器**常驻**（不是"例外"入口） */}
      {scanScreen && (
        <View className='production-scan-screen'>
          <Text className='production-scan-screen__title'>
            {[scanScreen.view.set_no, scanScreen.view.position?.position_name]
              .filter(Boolean)
              .join(' · ')}
          </Text>
          {scanScreen.view.operation ? (
            <View className='production-scan-screen__body'>
              <Text className='production-scan-screen__operation'>
                {`${operationLabel(scanScreen.view.operation)} · 应做 ${formatQty(
                  scanScreen.view.operation.qty,
                )}${scanScreen.view.operation.unit || ''}`}
              </Text>
              {scanScreen.view.operation.rerouted && (
                <Text className='production-scan-screen__note'>
                  {`本部位已做完，系统换到套级工序（承载部位：${
                    scanScreen.view.operation.carrier?.position_name || '见任务卡'
                  }）`}
                </Text>
              )}
              {/* 未定价 ≠ 0（issue #4696）：显式标注，可照常完工但不产生计件金额 */}
              {scanScreen.view.operation.unit_price === null && (
                <Text className='production-scan-screen__note'>
                  该工序未定价（≠ ¥0.00）：可照常完工，但不产生计件金额
                </Text>
              )}
              {/* 【开工】= 工人写入口（`scan/complete`）：只在有工人身份时渲染（issue #6467） */}
              {workerReady ? (
                <Button
                  className='production-scan-screen__btn'
                  disabled={reportingId !== null}
                  onClick={handleScanComplete}
                >
                  {reportingId === scanScreen.view.operation.operation_id ? '领活中…' : '开工'}
                </Button>
              ) : null}
              {/* 工序选择器（issue #6638，与 `/w/` 同形）：候选 = 系统推断那道 + 全部备选，
                  当前那道显式选中。点别的候选 ⇒ 既有「一键改」（归属仍由**服务端**校验）；
                  点**当前已选中**那道 ⇒ 不发请求（它不是"再查一次"的开关）。 */}
              {pickableOperations(scanScreen.view).length > 1 && (
                <View className='production-scan-screen__alts'>
                  <Text className='production-scan-screen__alts-title'>{SCAN_OPERATION_PICKER_TITLE}</Text>
                  {pickableOperations(scanScreen.view).map((choice) => {
                    const selected = choice.operation_id === scanScreen.view.operation?.operation_id
                    return (
                      <Text
                        key={choice.operation_id}
                        className={`production-scan-screen__alt${
                          selected ? ' production-scan-screen__alt--on' : ''
                        }`}
                        onClick={() => {
                          if (!selected) handlePickAlternative(choice.operation_id)
                        }}
                      >
                        {`${operationLabel(choice)} · ${formatQty(choice.qty)}${choice.unit || ''}`}
                      </Text>
                    )
                  })}
                </View>
              )}
            </View>
          ) : (
            <Text className='production-scan-screen__note'>本套工序都已被领走，无需再领</Text>
          )}
          {/* 本套工序明细（issue #4967 交付物 2）：工人一眼看到「这一套还有哪几道没做」。
              数据**只**来自服务端 `set_overview`（本套 → 部位 → 工序），页面不自己聚合；
              缺值不渲染（不出现 undefined 米 / ¥NaN）。 */}
          {scanOverviewGroups(scanScreen.view.set_overview).length > 0 && (
            <View className='production-scan-overview'>
              <Text className='production-scan-overview__title'>
                {`第 ${scanScreen.view.set_no ?? ''} 套 · 本套工序`}
              </Text>
              {scanOverviewGroups(scanScreen.view.set_overview).map((group) => (
                <View key={group.key} className='production-scan-overview__pos'>
                  <Text className='production-scan-overview__pos-name'>{group.positionName}</Text>
                  {group.operations.map((operation) => (
                    <View key={operation.operation_id} className='production-scan-overview__op'>
                      <Text className='production-scan-overview__op-name'>
                        {/* 本行**只**渲染逻辑名（不拼部位）：总览**已按部位分组**（组头
                            `production-scan-overview__pos-name` 就是部位），逐行再拼一次是重复。
                            ⇒ issue #4963 登记为「**有意的分组上下文**」而非漏网消费面：
                            部位在本块内可见，不属 #4630「改了面、判据全绿」的形态。
                            其余显示名消费面（主屏 / 回执「下一道」/ 计件行）一律走
                            `operationDisplayName`（`frontend/bmini-app/src/utils/operationDisplayName.ts`）。 */}
                        {`${operation.logical_name || ''} · 应做 ${formatQty(operation.qty)}${
                          operation.unit || ''
                        }`}
                      </Text>
                      <Text className='production-scan-overview__op-meta'>
                        {`${
                          operation.unit_price === null || operation.unit_price === undefined
                            ? '未定价'
                            : `¥${formatPrice(operation.unit_price)}/${operation.unit || ''}`
                        } · ${operation.status === 'done' ? '已领' : '待领'} · 已报 ${formatQty(
                          operation.done_qty,
                        )}${operation.unit || ''}`}
                      </Text>
                    </View>
                  ))}
                </View>
              ))}
            </View>
          )}
        </View>
      )}

      {loading && (
        <View className='production-loading'>
          <Text>加载工序中...</Text>
        </View>
      )}

      {!loading && !detail && (
        <View className='production-empty'>
          <Text>扫码或输入加工单号后显示本单工序</Text>
        </View>
      )}

      {detail && (
        <View className='production-detail'>
          {/* 进度 */}
          <View className='production-progress'>
            <Text className='production-progress__text'>
              {`已完 ${progress?.done ?? 0}/${progress?.total ?? 0} 道 · ${percent}%`}
            </Text>
            <View className='production-progress__track'>
              <View className='production-progress__fill' style={{ width: `${percent}%` }} />
            </View>
            {piecework && (
              <Text className='production-progress__piecework'>
                {`本单累计计件 ¥${formatPrice(piecework.total)}`}
              </Text>
            )}
          </View>

          {isCompleted && (
            <View className='production-completed'>
              <Text className='production-completed__text'>✅ 订单生产完成</Text>
            </View>
          )}

          {/* 发货（issue #4483 = #4347 §二.2）：全部活跃工序实例报满（#4961 口径）后才出现 ——
              门禁由后端判定（含加工项订单必须有 completed 加工单），前端只呈现入口。 */}
          {isCompleted && !shipped && (
            <View className='production-ship'>
              <Text className='production-ship__title'>发货</Text>
              <View className='production-ship__row'>
                <Input
                  className='production-ship__input'
                  value={trackingNo}
                  placeholder='货运单号'
                  onInput={(event) => setTrackingNo(event.detail.value)}
                />
                <Button
                  className='production-ship__btn'
                  disabled={shipping}
                  onClick={handleShip}
                >
                  {shipping ? '发货中…' : '发货'}
                </Button>
              </View>
              <Text className='production-ship__hint'>
                填写货运单号即完成发货（承运商取本单已记录的物流方式）
              </Text>
            </View>
          )}

          {shipped && (
            <View className='production-completed'>
              <Text className='production-completed__text'>✅ 已发货</Text>
            </View>
          )}

          {/* 工序列表（按部位分组） */}
          {positions.map((position) => (
            <View key={position.position_name} className='production-position'>
              <Text className='production-position__name'>{position.position_name}</Text>
              {/* 规格摘要（issue #4347 §3.1）：核对「做的是哪一件」。缺键不显示（不补默认值） */}
              {specSummary(position).length > 0 && (
                <Text className='production-position__spec'>{specSummary(position).join(' · ')}</Text>
              )}
              {/* 🔴 本部位没有任务码 ⇒ **报工入口照旧在**（issue #6598，2026-10-09 用户裁定
                  「允许工人自由报工」，开放范围 = 整张加工单内任选任意工序、不扫码也能自由报）。
                  改前这里渲染的是「本部位暂无任务码，无法报工 —— 请让管理端重新生成本单任务码」
                  （issue #5647 G10 的口径）⇒ 那条判据已作废：无码时按钮改走
                  `reportOperationFree`（工序由工人显式选，服务端仍校验归属 / 未软删 / 同租户），
                  服务端记账与扫码路**同一份实现**。任务码从此只是**扫码快捷定位**，不是写入门槛。 */}
              {position.operations.map((operation) => {
                // 🔴 计件查找键 = **逻辑工序名**（`per_operation[].operation` 是逻辑名，如 `精裁`），
                // 不是 `operation` 快照名（`精裁-布`）—— 改前拿快照名去比 ⇒ 永远查不到 ⇒
                // 「累计计件」那一行静默消失（零报错、零判据）。显示名与查找键是**两件事**。
                const amount = pieceworkOf(piecework, operation.logical_name ?? operation.operation)
                return (
                  <View key={operation.id} className='operation-item'>
                    <View className='operation-item__body'>
                      {/* 显示名走**唯一**口径（issue #4963）：逻辑名 · 部位 */}
                      <Text className='operation-item__name'>{operationDisplayName(operation)}</Text>
                      <Text className='operation-item__meta'>
                        {`应做 ${operation.qty}${operation.unit} · ¥${formatPrice(operation.unit_price)}`}
                      </Text>
                      <Text className='operation-item__done'>
                        {`已报 ${operation.done_qty}${operation.unit}`}
                      </Text>
                      {amount !== null && (
                        <Text className='operation-item__piecework'>
                          {`累计计件 ¥${formatPrice(amount)}`}
                        </Text>
                      )}
                    </View>
                    <View className='operation-item__actions'>
                      {/* 数量可改（issue #4206 判据 1）：默认 = 应做数量，上限 = 应做数量 */}
                      <View className='operation-item__qty'>
                        {/* 数量可改（issue #4206 判据 1）：默认 = 应做数量，上限 = 应做数量。
                            issue #5198：键盘类型改 `digit` —— 微信小程序的 `number` 键盘**没有小数点键**，
                            而报工数量按米常有小数（如 60.5 米）⇒ 改前小数点根本打不出来。 */}
                        <Input
                          className='operation-item__qty-input'
                          type='digit'
                          placeholder='完成数量'
                          value={qtyValueOf(operation)}
                          onInput={(event) =>
                            setQtyInputs((prev) => ({ ...prev, [operation.id]: event.detail.value }))
                          }
                        />
                        <Text className='operation-item__qty-unit'>{operation.unit}</Text>
                      </View>
                      <Text className='operation-item__qty-hint'>
                        {`本次最多 ${formatQty(remainingQty(operation))}${operation.unit}`}
                      </Text>
                      {/* disabled = in-flight 锁的可见面（issue #4116 §5-1）：报工期间不可再点。
                          写入口只在**有工人身份**（issue #6467）时才有：没有工人身份时写请求必然 401。
                          🔴 issue #6598 起**不再要求 `part_token`**（用户裁定「允许工人自由报工」）：
                          有码走 `completeByScan`（扫码快捷定位），无码走 `reportOperationFree`
                          （工序由工人显式选）—— 判别在 `handleReport` 里，两路共用同一份服务端记账。
                          ⚠️ 本处的身份闸门刻意与同文件「扫码一屏」那处**写法不同**（这里用短路
                          `&&`、那里用三元）：两处由此可被文本判据**各自定位** ——
                          `frontend/bmini-app/tests/worker-surface-ledger.json` 给「无码自由报工」
                          这条写路登记的独有记号就是本处这一行，摘掉它即判红并具名到该写路。 */}
                      {workerReady && (
                        <Button
                          className='operation-item__btn'
                          disabled={reportingId !== null}
                          onClick={() => handleReport(position, operation)}
                        >
                          {reportingId === operation.id ? '报工中…' : '完成报工'}
                        </Button>
                      )}
                    </View>
                  </View>
                )
              })}
            </View>
          ))}

          {/* 操作记录（真值源 §5：操作记录 = 报工明细，实证「蒋雪云-定型 11.00」带时间戳）。
              优先**服务端全单流水**（换设备也在、看得到别人报的工序）；
              离线（服务端没给）时退回本机缓存，并显式标注 —— 不把本机冒充服务端真值。 */}
          {displayLogs.length > 0 && (
            <View className='production-logs'>
              <Text className='production-logs__title'>
                {serverLogsAvailable ? '本单操作记录' : '本单报工明细（本机）'}
              </Text>
              {displayLogs.map((log) => (
                <Text key={log.key} className='production-logs__item'>
                  {`${log.workerName} · ${log.operation} · ${formatQty(log.qty)}${log.unit}`
                    + (Number.isNaN(log.at) ? '' : ` · ${formatTime(log.at)}`)}
                </Text>
              ))}
            </View>
          )}
        </View>
      )}
    </ScrollView>
  )
}
