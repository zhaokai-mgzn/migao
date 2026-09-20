'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, ArrowLeft, Copy, Printer, QrCode, RefreshCw, ShieldOff, Wrench } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { Button, Modal } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { cn, formatFullDateTime } from '@/lib/utils'
import { chipToneClasses } from '@/lib/status-chip'
import { processingOrderStatusChipFor } from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { useRouteId } from '@/lib/use-route-id'
import { routeSourceNotice } from '@/lib/route-source'
import ProductionProgressTable from '@/components/production/ProductionProgressTable'
import PieceworkTable from '@/components/production/PieceworkTable'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import type { PieceworkSummary, ProcessingOrder, ProductionOperations, StuckPointsReport } from '@/types'

/**
 * 加工单生产明细（issue #4000，M4-H 按需单据渲染）
 *
 * 路由：/processing-orders/{id}/production（id = 加工单号/订单号/UUID，按既有 useRouteId 读法）
 * 数据：加工单详情（头部：加工单号/订单号/状态/交期）+ 生产工序树（进度条/工序进度表）
 *       + 计件汇总；任务卡随页面挂载（屏幕隐藏、打印显形）→「打印任务卡」交车间扫码报工。
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §4 计件 / §5 扫码报工闭环。
 * 端点：GET /api/admin/production/orders/{orderId}/operations、/piecework（权限 order:list）；
 *       POST .../qr-token/revoke（issue #4240，**方法级 processing:manage** —— 与其它端点的类级
 *       order:list 不同口径，入口必须按同一码显隐，否则无权限角色会看到按钮却 403）。
 */
export default function ProcessingOrderProductionPage() {
  const id = useRouteId('id')
  const router = useRouter()
  const { has: hasPermission } = usePermission()

  const [po, setPo] = useState<ProcessingOrder | null>(null)
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
  // 未定价实例补价（issue #4709 C）：状态 + 结果反馈（补了几道 / 还有几道没定价）
  const [repricing, setRepricing] = useState(false)
  const [repriceError, setRepriceError] = useState('')
  const [repriceNotice, setRepriceNotice] = useState('')
  // 生成二维码（测试用，issue #4726，A 档）：把**加工单号**画成纯文本码供端到端联调。
  // **纯前端渲染 + 零写请求**（不碰 qr_token，不调任何端点）。
  const [testQrOpen, setTestQrOpen] = useState(false)
  const [testQrCopied, setTestQrCopied] = useState(false)
  // 「卡在哪」卡点报表（切片 ③，issue #4776；只读；设计 §6）
  const [stuckPoints, setStuckPoints] = useState<StuckPointsReport | null>(null)
  const [stuckPointsError, setStuckPointsError] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    setOperationsError('')
    setStuckPointsError('')
    try {
      const detailRes = await processingOrderApi.detail(id)
      const detail = detailRes.data?.data ?? null
      if (!detail) {
        setPo(null)
        setError('未找到该加工单')
        return
      }
      setPo(detail)

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
    } catch (e) {
      console.error(e)
      setPo(null)
      setError('加载加工单失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [id])

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

  /** 打印任务卡：先上报打印计数（fire-and-forget，失败不得阻断打印），再打印。 */
  const handlePrint = () => {
    if (po?.orderId) {
      productionApi.recordPrint(po.orderId).catch(() => {})
    }
    window.print()
  }

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
   * 生成二维码（测试用，issue #4726，A 档 = 加工单号纯文本码）。
   *
   * 用户诉求（2026-09-20）：「加个按钮生成二维码，这样就能串联起来扫码生产&计件，主要是用来测试」。
   * 串联链路 = 屏幕出码 → 任意扫码工具读到**加工单号** → 工人在 bmini 报工页
   * （frontend/bmini-app/src/pages/production/index）**手动输入**单号 → 报工 → 计件。
   *
   * ⚠️ 与「打印任务卡」的码**不是同一个**：任务卡印的是后端 `qr_token`（token 化、可撤销，扫码报工的
   * 权威入口）；本按钮是**纯前端**把加工单号画成码 —— 只读、不写库、既不生成也不撤销 token。
   * ⚠️ 限制：工人端**无登录** ⇒ 计件归属靠 worker_id/worker_name，可能落「未署名」或商家账号
   * ⇒ 发工资对不上人（#4716 解决）；A 档**不是**「扫一下就进」，B 档小程序码才是。
   */
  const openTestQr = () => {
    setTestQrCopied(false)
    setTestQrOpen(true)
  }

  /** 复制单号（工人粘进 bmini 报工页的单号输入框）；剪贴板不可用只记日志，不阻断弹层。 */
  const copyTestQrNo = () => {
    navigator.clipboard
      .writeText(po?.processingOrderNo ?? '')
      .then(() => setTestQrCopied(true))
      .catch((e) => console.error('Clipboard write failed:', e))
  }

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
  // 生成二维码（测试用，issue #4726）：与「撤销二维码」同级显隐（同为 processing:manage 口径，
  // 避免无权限角色看到按钮却 403；本入口本身不调端点，但保持同一码以免口径分叉）
  const canTestQr = hasPermission('processing:manage')
  // 工序还在但码没了 = 刚撤销过 ⇒ 任务卡占位文案不得再指向本页不存在的「补生成工序」
  const qrPlaceholderHint =
    positionCount > 0 && !operations?.qr_token ? '二维码已撤销（旧码已失效）' : undefined
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
                {canTestQr && (
                  <Button
                    variant="secondary"
                    size="sm"
                    data-testid="production-test-qr-button"
                    onClick={openTestQr}
                  >
                    <QrCode className="w-4 h-4 mr-1.5" />
                    生成二维码（测试用）
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
                <Button data-testid="production-print-button" onClick={handlePrint}>
                  <Printer className="w-4 h-4 mr-1.5" />
                  打印任务卡
                </Button>
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
                A 模式 · 只查「没开工」；阈值 {stuckPoints?.threshold_hours ?? '—'} 小时（
                {stuckPoints?.threshold_source === 'history' ? '历史中位数' : '系统兜底默认值'}）
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
                    {(stuckPoints?.stuck ?? []).map((row) => (
                      <li
                        key={`${row.set_id ?? ''}-${row.operation?.operation_id ?? ''}`}
                        className="flex flex-wrap items-center justify-between gap-2 rounded border border-neutral-200 px-3 py-2 text-sm"
                        data-testid="production-stuck-points-row"
                      >
                        <span className="text-neutral-900">
                          <span className="font-medium">{row.set_no ?? row.processing_order_id ?? '—'}</span>
                          <span className="mx-1 text-neutral-400">·</span>
                          {row.operation?.position
                            ? `${row.operation?.logical_name ?? ''} · ${row.operation.position}`
                            : (row.operation?.logical_name ?? '—')}
                        </span>
                        <span className="text-red-600">
                          等了 {(row.stalled_hours ?? 0).toFixed(1)} 小时
                          {row.predecessor?.done_at
                            ? `（上道 ${formatFullDateTime(row.predecessor.done_at)} 完成）`
                            : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>

          {/* 可打印任务卡：屏幕隐藏（display:none），点「打印任务卡」时只打印它 */}
          <TaskCardPrint
            processingOrderNo={po.processingOrderNo}
            orderNo={po.orderNo}
            qrToken={operations?.qr_token}
            qrPlaceholderHint={qrPlaceholderHint}
            positions={operations?.positions}
            // 工艺规格真值来源 = 加工单快照明细（issue #4355 / 设计文档 §4.9 ③）
            items={po.items}
          />

          {/* 生成二维码（测试用，issue #4726）：A 档 = 加工单号纯文本码（只读、零写请求） */}
          <Modal
            open={testQrOpen}
            onClose={() => setTestQrOpen(false)}
            title="生成二维码（测试用）"
            footer={
              <div className="flex justify-end gap-2">
                <Button
                  variant="secondary"
                  data-testid="production-test-qr-close"
                  onClick={() => setTestQrOpen(false)}
                >
                  关闭
                </Button>
                <Button data-testid="production-test-qr-copy" onClick={copyTestQrNo}>
                  <Copy className="w-4 h-4 mr-1.5" />
                  {testQrCopied ? '已复制' : '复制单号'}
                </Button>
              </div>
            }
          >
            <div className="space-y-3 text-sm">
              <p
                className="flex items-start gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-amber-800"
                data-testid="production-test-qr-notice"
              >
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>
                  <span className="font-medium">测试用</span>：二维码内容 = 加工单号（纯文本），
                  工人扫码后需在报工页<span className="font-medium">手动输入</span>单号，
                  不是「扫一下就进」。
                </span>
              </p>
              <div className="flex flex-col items-center gap-2">
                <QRCodeSVG
                  value={po.processingOrderNo}
                  size={180}
                  level="M"
                  title={po.processingOrderNo}
                  data-testid="production-test-qr-code"
                  className="border border-neutral-300 p-1"
                />
                <p className="font-medium text-neutral-900" data-testid="production-test-qr-order-no">
                  {po.processingOrderNo}
                </p>
              </div>
              <p className="text-xs text-neutral-500">
                本码只读生成：不写入、不撤销任何数据，与任务卡的报工码（qr_token）互不影响。
                计件归属仍按工人署名（工人端暂无登录），发工资前请核对报工人。
              </p>
            </div>
          </Modal>

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
                （工人扫旧码报工将失败），需要继续报工时请重新生成二维码。
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
