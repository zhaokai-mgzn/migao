'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { processingItemApi, productionApi } from '@/lib/api'
import { feeGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type { FeeCombination, FeeGaps, FeeCombinationsResponse, ProcessingItem } from '@/types'

/**
 * 加工费管理 /production/processing-fees（issue #4386，P1）
 *
 * **用户裁定（2026-09-19）**：「不是每个加工项收取一个费用，而且通常是组合」
 * 「选配完的一个商品**只会收取一种加工费**，然后根据米算出这个商品的加工费」
 * 「这个加工费组合是要**系统根据选配结果自己计算**的，**不可能**是用户直接告诉」
 * ⇒ 本页是**商家配置面**：把「哪几个加工项一起用」组合起来定**一个**价（元/米）。
 * 下单时由系统按选配结果匹配组合取价 —— 顾客/AI 只选配，不告知组合也不告知金额。
 *
 * 契约（冻结，见 issue #4386；**不得自行发明端点/字段名**）：
 *   GET    /api/admin/production/processing-fee-combinations
 *   POST   /api/admin/production/processing-fee-combinations   body {items:[名…], unit_price}
 *   PUT    /api/admin/production/processing-fee-combinations/{id}   body {unit_price}
 *   DELETE /api/admin/production/processing-fee-combinations/{id}   （停用，软删语义）
 *   GET    /api/admin/production/processing-fee-gaps           （未定价组合）
 *   —— 写端点权限 processing:manage。
 *
 * 两处**故意**不做（见 issue #4386「不做」）：
 * ① **不在前端拼 composition_key**：归一化（与书写顺序无关）是服务端的事 —— 前端自己拼会变成
 *    第二份口径，两边一旦漂移就会出现「页面显示一个组合、库里是另一个」的静默错配。
 * ② **不接线计价**：本页只管配置；下单侧取价（`OrderService.sumProcessingFee` / 下单页 /
 *    ai-agent）不在本包（issue #4386 已登记为 follow-up）。
 *
 * 真值源：`docs/design/position-instance-routing-model.md` §0.0 R-b/R-g。
 */

const money = (v?: number | null) => `¥${Number(v ?? 0).toFixed(2)}`

const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'

/**
 * 护栏理由解析（`feeGuardReasons`）**已迁到 `@/lib/production-guard-reasons`** ——
 * route 文件不得导出非框架字段（issue #4412）。
 */

export default function ProcessingFeesPage() {
  const [combinations, setCombinations] = useState<FeeCombinationsResponse | null>(null)
  const [gaps, setGaps] = useState<FeeGaps | null>(null)
  const [gapsError, setGapsError] = useState('')
  const [catalog, setCatalog] = useState<ProcessingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 新建表单
  const [createOpen, setCreateOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [createPrice, setCreatePrice] = useState('')
  const [createReasons, setCreateReasons] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  // 改价（就地编辑）
  const [editId, setEditId] = useState<string | null>(null)
  const [editPrice, setEditPrice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await productionApi.getFeeCombinations()
      setCombinations(res.data?.data ?? null)
    } catch (e) {
      // 不 re-throw：本页自己给可读提示 + 重试入口（re-throw 会变成未处理的 promise rejection，
      // 而「页面已提示」与「控制台报错」同时出现会让排查者误判成第二种故障）
      console.error(e)
      setError('加工费组合加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadGaps = useCallback(async () => {
    setGapsError('')
    try {
      const res = await productionApi.getFeeGaps()
      setGaps(res.data?.data ?? null)
    } catch {
      // 缺口是**辅助**信息：它失败只在缺口区提示，不得把组合列表一起打白屏（同 #4307 的处置）
      setGapsError('缺口数据加载失败，请重试')
    }
  }, [])

  const loadCatalog = useCallback(async () => {
    try {
      const res = await processingItemApi.getProcessingItems({ page: 1, size: 200 })
      setCatalog(res.data?.data?.items ?? [])
    } catch {
      setCatalog([])
    }
  }, [])

  useEffect(() => {
    void load()
    void loadGaps()
    void loadCatalog()
  }, [load, loadGaps, loadCatalog])

  const rows = combinations?.combinations ?? []
  const gapRows = gaps?.unpriced_combinations ?? []

  const pickedSet = useMemo(() => new Set(picked), [picked])

  const togglePick = (name: string) => {
    setPicked((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]))
  }

  const openCreate = () => {
    setPicked([])
    setCreatePrice('')
    setCreateReasons([])
    setCreateOpen(true)
  }

  const submitCreate = async () => {
    // 空组合**本地先拦**（后端也会拒，但没必要发一个必然 422 的请求）
    if (picked.length === 0) {
      setCreateReasons(['至少选 1 个加工项：加工费按「选配组合」收，没有组合就没有可收的费'])
      return
    }
    if (createPrice.trim() === '' || Number.isNaN(Number(createPrice))) {
      setCreateReasons(['请填写加工费单价（元/米）'])
      return
    }
    setSaving(true)
    setCreateReasons([])
    try {
      await productionApi.createFeeCombination({ items: picked, unit_price: Number(createPrice) })
      setCreateOpen(false)
      await Promise.all([load(), loadGaps()])
    } catch (e) {
      // 护栏理由**逐条**展示（不吞后端理由，也不只弹「保存失败」）
      setCreateReasons(feeGuardReasons(e))
    } finally {
      setSaving(false)
    }
  }

  const submitEdit = async (id: string) => {
    const price = Number(editPrice)
    if (editPrice.trim() === '' || Number.isNaN(price)) {
      setCreateReasons(['请填写加工费单价（元/米）'])
      return
    }
    try {
      await productionApi.updateFeeCombination(id, { unit_price: price })
      setEditId(null)
      await load()
    } catch (e) {
      setCreateReasons(feeGuardReasons(e))
    }
  }

  const disable = async (id: string) => {
    if (!window.confirm('停用这个加工费组合？停用后下单匹配不再取这一行（历史订单不受影响）。')) return
    try {
      await productionApi.disableFeeCombination(id)
      await load()
    } catch (e) {
      setCreateReasons(feeGuardReasons(e))
    }
  }

  return (
    <div className="space-y-6 p-6" data-testid="processing-fees-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">加工费管理</h1>
          <p className="mt-1 text-sm text-neutral-500">
            选配组合 → 加工费单价（元/米）。下单时系统按选配结果自动匹配，顾客只选配、不报价。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => void load()} data-testid="fee-combinations-refresh">
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新
          </Button>
          <Button onClick={openCreate} data-testid="fee-combination-new">
            <Plus className="mr-1 h-4 w-4" />
            新建组合
          </Button>
        </div>
      </div>

      {error ? (
        <div
          className="flex items-center gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          data-testid="fee-combinations-error"
        >
          <AlertCircle className="h-4 w-4" />
          {error}
          <Button variant="secondary" size="sm" onClick={() => void load()} data-testid="fee-combinations-retry">
            重试
          </Button>
        </div>
      ) : null}

      {createReasons.length > 0 ? (
        <div
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          data-testid="fee-combination-guard-reasons"
        >
          <div className="mb-1 font-medium">保存被拒，逐条原因：</div>
          <ul className="list-disc space-y-0.5 pl-5">
            {createReasons.map((reason, i) => (
              <li key={i} data-testid={`fee-combination-guard-reason-${i}`}>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* ── 组合列表 ── */}
      <section className="rounded border border-neutral-200 bg-white">
        <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-medium text-neutral-800">加工费组合</h2>
          <span className="text-sm text-neutral-500" data-testid="fee-combinations-total">
            {loading ? '加载中…' : `${rows.length}`}
          </span>
        </div>
        {loading ? (
          <div className="p-6 text-sm text-neutral-500">加载中…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-neutral-500" data-testid="fee-combinations-empty">
            还没有定价的组合：点「新建组合」把常卖的选配（如 韩褶+打孔）定一个价。
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left text-neutral-500">
              <tr>
                <th className="px-4 py-2 font-medium">选配组合</th>
                <th className="px-4 py-2 font-medium">加工费单价</th>
                <th className="px-4 py-2 font-medium">来源</th>
                <th className="px-4 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const id = String(row.id ?? row.composition_key)
                return (
                  <tr key={id} className="border-t border-neutral-100" data-testid={`fee-combination-${id}`}>
                    <td className="px-4 py-2" data-testid={`fee-combination-items-${id}`}>
                      {(row.items ?? []).join(' + ') || row.composition_key}
                    </td>
                    <td className="px-4 py-2" data-testid={`fee-combination-price-${id}`}>
                      {editId === id ? (
                        <input
                          className={cn(inputCls, 'w-28')}
                          value={editPrice}
                          onChange={(e) => setEditPrice(e.target.value)}
                          data-testid={`fee-combination-edit-price-${id}`}
                        />
                      ) : (
                        <>
                          {money(row.unit_price)} <span className="text-neutral-400">{row.unit ?? '元/米'}</span>
                        </>
                      )}
                    </td>
                    <td className="px-4 py-2 text-neutral-500">{row.source ?? '—'}</td>
                    <td className="px-4 py-2">
                      {editId === id ? (
                        <Button size="sm" onClick={() => void submitEdit(id)} data-testid={`fee-combination-edit-submit-${id}`}>
                          保存
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            setCreateReasons([])
                            setEditId(id)
                            setEditPrice(String(row.unit_price ?? ''))
                          }}
                          data-testid={`fee-combination-edit-${id}`}
                        >
                          改单价
                        </Button>
                      )}
                      <Button
                        variant="secondary"
                        size="sm"
                        className="ml-2"
                        onClick={() => void disable(id)}
                        data-testid={`fee-combination-disable-${id}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* ── 缺口区：未定价组合 ── */}
      <section className="rounded border border-amber-200 bg-amber-50/40">
        <div className="flex items-center justify-between border-b border-amber-100 px-4 py-3">
          <h2 className="text-sm font-medium text-amber-900">
            未定价组合（订单里出现过、但这里没有价）
          </h2>
          <span className="text-sm text-amber-800" data-testid="fee-gaps-total">
            {gapRows.length}
          </span>
        </div>
        {gapsError ? (
          <div className="p-4 text-sm text-amber-800" data-testid="fee-gaps-unavailable">
            {gapsError}
          </div>
        ) : gapRows.length === 0 ? (
          <div className="p-4 text-sm text-amber-800" data-testid="fee-gaps-empty">
            没有未定价组合（当前成交的选配组合都已定价）。
          </div>
        ) : (
          <ul className="divide-y divide-amber-100">
            {gapRows.map((gap) => (
              <li key={gap.composition_key} className="px-4 py-3" data-testid={`fee-gap-${gap.composition_key}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-amber-900" data-testid={`fee-gap-items-${gap.composition_key}`}>
                    {(gap.items ?? []).join(' + ')}
                  </span>
                  <span className="text-xs text-amber-800" data-testid={`fee-gap-order-count-${gap.composition_key}`}>
                    订单出现 {gap.order_count} 次
                  </span>
                </div>
                {gap.note ? <p className="mt-1 text-xs text-amber-800">{gap.note}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── 新建组合 ── */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建加工费组合">
        <div className="space-y-4">
          <div>
            <div className="mb-2 text-sm font-medium text-neutral-700">选配组合（可多选）</div>
            {catalog.length === 0 ? (
              <div className="text-sm text-neutral-500" data-testid="fee-combination-catalog-empty">
                加工项目录为空：请先到「加工项管理」建加工项。
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {catalog.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => togglePick(item.name)}
                    className={cn(
                      'rounded border px-3 py-1 text-sm',
                      pickedSet.has(item.name)
                        ? 'border-primary-500 bg-primary-50 text-primary-700'
                        : 'border-neutral-300 bg-white text-neutral-700',
                    )}
                    data-testid={`fee-item-pick-${item.name}`}
                  >
                    {item.name}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <div className="mb-2 text-sm font-medium text-neutral-700">加工费单价（元/米）</div>
            <input
              className={inputCls}
              value={createPrice}
              onChange={(e) => setCreatePrice(e.target.value)}
              placeholder="如 18.00"
              data-testid="fee-combination-price-input"
            />
            <p className="mt-1 text-xs text-neutral-500">
              一个组合**一个价**：韩褶+打孔 与 韩褶+打孔+定型 是两个不同的组合，各自定价。
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void submitCreate()} disabled={saving} data-testid="fee-combination-submit">
              保存
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
