'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, ArrowLeft, Printer, RefreshCw, ShieldOff, Wrench } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
import { processingOrderStatusChipFor } from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { useRouteId } from '@/lib/use-route-id'
import ProductionProgressTable from '@/components/production/ProductionProgressTable'
import PieceworkTable from '@/components/production/PieceworkTable'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import type { PieceworkSummary, ProcessingOrder, ProductionOperations } from '@/types'

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

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    setOperationsError('')
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
  // 工序还在但码没了 = 刚撤销过 ⇒ 任务卡占位文案不得再指向本页不存在的「补生成工序」
  const qrPlaceholderHint =
    positionCount > 0 && !operations?.qr_token ? '二维码已撤销（旧码已失效）' : undefined

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

          {/* 工序进度（按部位分组 + 必完工序标记） */}
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
            </div>
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
