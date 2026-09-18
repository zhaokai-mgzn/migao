'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, ArrowLeft, Printer, RefreshCw, Wrench } from 'lucide-react'
import { Button } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
import { processingOrderStatusChipFor } from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
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
 * 端点：GET /api/admin/production/orders/{orderId}/operations、/piecework（权限 order:list）。
 */
export default function ProcessingOrderProductionPage() {
  const id = useRouteId('id')
  const router = useRouter()

  const [po, setPo] = useState<ProcessingOrder | null>(null)
  const [operations, setOperations] = useState<ProductionOperations | null>(null)
  const [piecework, setPiecework] = useState<PieceworkSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [operationsError, setOperationsError] = useState('')
  const [instantiateError, setInstantiateError] = useState('')
  const [instantiating, setInstantiating] = useState(false)

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

  const progress = operations?.progress
  const percent = Math.min(100, Math.max(0, Math.round(Number(progress?.percent ?? 0))))
  const doneCount = progress?.done ?? 0
  const totalCount = progress?.total ?? 0
  const chip = processingOrderStatusChipFor(po?.status)
  // 存量单恢复路径：无工序实例 且 非终态取消（cancelled 不可重生成）
  const showInstantiate = !operationsError && (operations?.positions?.length ?? 0) === 0 && po?.status !== 'cancelled'

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
              <Button data-testid="production-print-button" onClick={handlePrint}>
                <Printer className="w-4 h-4 mr-1.5" />
                打印任务卡
              </Button>
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
            positions={operations?.positions}
          />
        </>
      )}
    </div>
  )
}
