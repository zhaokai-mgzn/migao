import { useCallback, useEffect, useRef, useState } from 'react'
import { View, Text, Button, Input, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import {
  getOrderOperations,
  getOrderPiecework,
  newReportRequestId,
  reportInFlightLock,
  reportOperation,
  type OrderOperations,
  type PieceworkSummary,
  type ProductionOperation,
  type ReportPayload,
} from '../../../services/productionService'
import { parseOrderIdFromQr, resolveOrderIdFromParams } from '../../../utils/productionQr'
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

/** 报工明细时间（MM-DD HH:mm） */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
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

/** 该工序的累计计件金额（服务端 `piecework.per_operation` 按工序名给；没有则不展示） */
function pieceworkOf(summary: PieceworkSummary | null, operationName: string): number | null {
  const found = summary?.per_operation?.find((item) => item.operation === operationName)
  return found ? Number(found.amount) : null
}

/**
 * 工人端扫码报工（issue #3997，M4-G-3；issue #4206 补齐弱网降级/数量可改/计件与明细/带参直达）
 *
 * 链路：扫一扫 / 手输单号 / **带参跳转直达** → 本单工序（按部位分组，含应做数量/单位/单价）
 *   → 改「完成数量」（默认 = 应做数量，上限 = 应做数量）→「完成报工」
 *   → 刷新进度 + 计件金额累计 + 本单报工明细 → 必完工序全绿 → 「✅ 订单生产完成」。
 *
 * 弱网降级（issue #4206）：`loadOrder` 成功即把待做清单落本机 storage，断网时命中缓存仍出清单
 * （显式标注离线，不冒充服务端真值）；报工**传输层**失败进本机队列，联网后自动补传
 * （复用同一幂等键 ⇒ 服务端不重复计件）。
 *
 * 报工失败只展示后端 message，**不清空列表**（工人可继续报其它工序）。
 */
export default function ProductionPage() {
  const { user } = useAuthStore()
  const [detail, setDetail] = useState<OrderOperations | null>(null)
  const [manualId, setManualId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
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
      const res = await getOrderOperations(orderId)
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

  /** 扫一扫（失败/无相机时走手输单号兜底） */
  const handleScan = useCallback(async () => {
    try {
      const res = await Taro.scanCode({ scanType: ['qrCode'] })
      const orderId = parseOrderIdFromQr(res?.result || '')
      if (!orderId) {
        Taro.showToast({ title: '无法识别该二维码，请手动输入单号', icon: 'none' })
        return
      }
      await loadOrder(orderId)
    } catch {
      Taro.showToast({ title: '扫码未完成，请手动输入单号', icon: 'none' })
    }
  }, [loadOrder])

  /** 完成报工（数量默认 = 应做数量，可改；前端守上限，服务端仍兜底） */
  const handleReport = useCallback(
    async (operation: ProductionOperation) => {
      if (!detail) return
      const orderId = detail.order_id
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
      const payload: ReportPayload = {
        worker_id: user?.id || '',
        worker_name: user?.nickname || '',
        qty,
        qualified_qty: qty,
        work_type: 'normal',
      }
      setReportingId(operation.id)
      setError('')
      try {
        const res = await reportOperation(orderId, operation.id, payload, requestId)
        if (!res.success) {
          if (res.offline) {
            // 弱网降级：进本机队列（幂等键随队列项落盘，补传复用它 ⇒ 不会重复计件）
            enqueuePendingReport({
              requestId,
              orderId,
              operationId: operation.id,
              operationName: operation.operation,
              unit: operation.unit,
              payload,
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
          worker_name: payload.worker_name,
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
    [detail, user, qtyInputs, loadOrder],
  )

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

          {/* 工序列表（按部位分组） */}
          {positions.map((position) => (
            <View key={position.position_name} className='production-position'>
              <Text className='production-position__name'>{position.position_name}</Text>
              {position.operations.map((operation) => {
                const amount = pieceworkOf(piecework, operation.operation)
                return (
                  <View key={operation.id} className='operation-item'>
                    <View className='operation-item__body'>
                      <Text className='operation-item__name'>{operation.operation}</Text>
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
                        <Input
                          className='operation-item__qty-input'
                          type='number'
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
                      {/* disabled = in-flight 锁的可见面（issue #4116 §5-1）：报工期间不可再点 */}
                      <Button
                        className='operation-item__btn'
                        disabled={reportingId !== null}
                        onClick={() => handleReport(operation)}
                      >
                        {reportingId === operation.id ? '报工中…' : '完成报工'}
                      </Button>
                    </View>
                  </View>
                )
              })}
            </View>
          ))}

          {/* 报工明细（真值源 §5：操作记录 = 报工明细，实证「蒋雪云-定型 11.00」带时间戳） */}
          {workLogs.length > 0 && (
            <View className='production-logs'>
              <Text className='production-logs__title'>本单报工明细</Text>
              {workLogs.map((log) => (
                <Text key={log.requestId} className='production-logs__item'>
                  {`${log.worker_name || '未署名'} · ${log.operation} · ${formatQty(log.qty)}${log.unit}`
                    + ` · ${formatTime(log.createdAt)}`}
                </Text>
              ))}
            </View>
          )}
        </View>
      )}
    </ScrollView>
  )
}
