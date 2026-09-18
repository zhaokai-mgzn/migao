'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, Check, Pencil, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { Button } from '@/components/ui'
import { productionApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { CatalogOperation, OperationsCatalog, RoutingsResponse } from '@/types'

/**
 * 工序库 /production/operations（issue #4203 菜单入口 + #4204 前端半边）
 *
 * 数据源（后端既有只读消费者，本页是其**首个**前端消费者）：
 * - GET /api/admin/production/operations-catalog → 按分组（裁剪/车位/后道/其他）的工序目录
 * - GET /api/admin/production/routings → 6 条 部位×工艺 路线（布帘·韩褶 = 11 道）
 * 写路径：PUT /api/admin/production/operations/{id}（改单价 / 必完开关；权限 processing:manage）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库（属性含计件单价、必完开关）/ §3 工艺路线。
 * 口径说明：`is_must_finish`（此工序必须完成才可打包）与 `is_start_marker`（标记生产开始）
 * 是**两个**属性，展示与开关只作用于前者，不混用（避免把首工序误当完工门槛）。
 */
function formatMoney(value?: number | null): string {
  return `¥${Number(value ?? 0).toFixed(2)}`
}

export default function OperationsCatalogPage() {
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /** 单价行内编辑（同一时刻只编辑一行；draft 为输入框字符串） */
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    // 两条只读端点互不依赖：路线失败不该把工序库也吞掉（页面不白屏）
    const [catalogRes, routingRes] = await Promise.allSettled([
      productionApi.getOperationsCatalog(),
      productionApi.getRoutings(),
    ])
    if (catalogRes.status === 'fulfilled') {
      setCatalog(catalogRes.value.data?.data ?? null)
    } else {
      setCatalog(null)
      setError('工序库加载失败，请稍后重试')
    }
    setRoutings(routingRes.status === 'fulfilled' ? routingRes.value.data?.data ?? null : null)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const groups = useMemo(() => catalog?.groups ?? [], [catalog])
  const total = catalog?.total ?? 0

  /** 写路径统一出口：成功 toast + 重新拉取（结果可见），失败可读提示且不假装成功。 */
  const submit = async (id: number, payload: Parameters<typeof productionApi.updateOperation>[1]) => {
    setBusy(true)
    try {
      await productionApi.updateOperation(id, payload)
      toast.success('工序已更新')
      setEditingId(null)
      await load()
    } catch (e) {
      toastRequestError(e, '工序更新失败')
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (op: CatalogOperation) => {
    setEditingId(op.id)
    setDraft(String(op.unit_price ?? 0))
  }

  const savePrice = (op: CatalogOperation) => {
    const value = Number(draft)
    if (draft.trim() === '' || Number.isNaN(value)) {
      toast.error('请输入有效单价')
      return
    }
    submit(op.id, { unit_price: value })
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">工序库</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            工序分组 · 计件单价 · 必完开关；调价只影响新报工（历史报工按当时价）
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
          刷新
        </Button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500" data-testid="operations-catalog-loading">
          <RefreshCw className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-neutral-200 bg-white py-10"
          data-testid="operations-catalog-error"
        >
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-neutral-600">{error}</p>
          <Button size="sm" onClick={load}>
            重试
          </Button>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* 工序目录（按分组） */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="mb-3 flex items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">工序目录</h2>
              <span className="text-sm text-neutral-500">
                共 <span data-testid="operations-catalog-total">{total}</span> 道工序
              </span>
            </div>

            {groups.length === 0 ? (
              <p className="py-8 text-center text-sm text-neutral-400" data-testid="operations-catalog-empty">
                暂无工序数据
              </p>
            ) : (
              <div className="space-y-5">
                {groups.map((g) => (
                  <div key={g.group} data-testid={`operation-group-${g.group}`}>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-sm font-medium text-neutral-900">{g.group}</span>
                      <span className="text-xs text-neutral-400">{g.operations.length} 道</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                            <th className="py-2 pr-4 font-medium">工序名称</th>
                            <th className="py-2 pr-4 font-medium">部位</th>
                            <th className="py-2 pr-4 font-medium">单位</th>
                            <th className="py-2 pr-4 font-medium">计件单价</th>
                            <th className="py-2 pr-4 font-medium">必完</th>
                            <th className="py-2 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {g.operations.map((op) => (
                            <tr
                              key={op.id}
                              className="border-b border-neutral-100 last:border-0"
                              data-testid={`operation-row-${op.id}`}
                            >
                              <td className="py-2.5 pr-4 text-neutral-900">
                                {op.name}
                                {op.is_start_marker && (
                                  <span className="ml-2 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500">
                                    首工序
                                  </span>
                                )}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-600">{op.position ?? '—'}</td>
                              <td className="py-2.5 pr-4 text-neutral-600">{op.unit ?? '—'}</td>
                              <td className="py-2.5 pr-4 text-neutral-900">
                                {editingId === op.id ? (
                                  <span className="flex items-center gap-1.5">
                                    <input
                                      value={draft}
                                      inputMode="decimal"
                                      aria-label={`${op.name} 计件单价`}
                                      data-testid={`operation-price-input-${op.id}`}
                                      onChange={(e) => setDraft(e.target.value)}
                                      onKeyDown={(e) => e.key === 'Enter' && savePrice(op)}
                                      className="h-8 w-24 rounded border border-neutral-300 bg-white px-2 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                                    />
                                    <button
                                      type="button"
                                      aria-label="保存单价"
                                      data-testid={`operation-price-save-${op.id}`}
                                      disabled={busy}
                                      onClick={() => savePrice(op)}
                                      className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
                                    >
                                      <Check className="w-4 h-4" />
                                    </button>
                                    <button
                                      type="button"
                                      aria-label="取消"
                                      onClick={() => setEditingId(null)}
                                      className="rounded p-1 text-neutral-500 hover:bg-neutral-100"
                                    >
                                      <X className="w-4 h-4" />
                                    </button>
                                  </span>
                                ) : (
                                  <span className="flex items-center gap-1.5">
                                    <span>{formatMoney(op.unit_price)}</span>
                                    <button
                                      type="button"
                                      aria-label={`编辑 ${op.name} 单价`}
                                      data-testid={`operation-price-edit-${op.id}`}
                                      onClick={() => startEdit(op)}
                                      className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
                                    >
                                      <Pencil className="w-3.5 h-3.5" />
                                    </button>
                                  </span>
                                )}
                              </td>
                              <td className="py-2.5 pr-4">
                                <input
                                  type="checkbox"
                                  aria-label={`${op.name} 必须完成才可打包`}
                                  data-testid={`operation-must-finish-${op.id}`}
                                  checked={!!op.is_must_finish}
                                  disabled={busy}
                                  onChange={(e) => submit(op.id, { is_must_finish: e.target.checked })}
                                  className="h-4 w-4 accent-primary-600"
                                />
                              </td>
                              <td className="py-2.5 text-xs text-neutral-400">
                                {op.is_start_marker ? '标记生产开始' : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 工艺路线（部位 × 工艺 → 工序序列） */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="mb-3 flex items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">工艺路线</h2>
              <span className="text-sm text-neutral-500">
                共 <span data-testid="routings-total">{routings?.total ?? 0}</span> 条
              </span>
            </div>

            {(routings?.routings ?? []).length === 0 ? (
              <p className="py-8 text-center text-sm text-neutral-400" data-testid="routings-empty">
                暂无工艺路线
              </p>
            ) : (
              <div className="space-y-4">
                {(routings?.routings ?? []).map((routing) => {
                  const key = `${routing.curtain_type}-${routing.craft}`
                  return (
                    <div key={key} className="rounded-lg border border-neutral-200 p-4" data-testid={`routing-${key}`}>
                      <div className="mb-2 flex flex-wrap items-baseline gap-2">
                        <span className="text-sm font-medium text-neutral-900">
                          {routing.curtain_type} · {routing.craft}
                        </span>
                        <span className="text-xs text-neutral-400">{routing.operation_count} 道工序</span>
                      </div>
                      <ol className="flex flex-wrap gap-1.5">
                        {(routing.operations ?? []).map((step) => (
                          <li
                            key={step.seq}
                            data-testid={`routing-step-${key}-${step.seq}`}
                            className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs text-neutral-700"
                          >
                            <span className="mr-1 text-neutral-400">{step.seq}.</span>
                            {step.operation}
                            <span className="ml-1.5 text-neutral-400">
                              {step.unit ?? '—'} · {formatMoney(step.unit_price)}
                            </span>
                            {step.is_must_finish && <span className="ml-1.5 text-amber-600">必完</span>}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
