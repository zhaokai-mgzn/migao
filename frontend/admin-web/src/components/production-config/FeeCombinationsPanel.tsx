'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, ChevronDown, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { processingItemApi, productionApi } from '@/lib/api'
import { feeGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type { FeeCombinationsResponse, FeeGaps, ProcessingItem } from '@/types'
import { inputCls, money } from './processing-shared'

/**
 * 「加工项与加工费」域的**加工费组合面板**（issue #6585 从 `ProcessingBoard` 拆出，cut & paste + 补 import）。
 *
 * ## 它回答一个问题
 *
 * 「哪几个加工项一起用时收多少？」—— 选配组合 → 单价 元/米、未定价缺口（辅助告警）、来源徽标。
 * 加工项本身（有哪些 / 怎么归类）在 {@link import('./ProcessingItemsPanel').default}。
 *
 * ## 自包含（issue #6585 的核心 constract）
 *
 * 面板**自己拉自己的数据**：
 * - `productionApi.getFeeCombinations`（组合定价列表）
 * - `productionApi.getFeeGaps`（未定价缺口 —— 辅助信息，失败只在本区提示，不打白屏）
 * - `processingItemApi.getProcessingItems`（「新建组合」的勾选源 —— **目录**）
 *
 * ⇒ 可以单独 `render(<FeeCombinationsPanel />`，也可以被配置指挥台直接挂载。
 * 改组合 / 停用组合后**重取自己的那份**（`loadCombinations` / `loadGaps` / 目录三件都在本面板内闭环）。
 *
 * ## `embedded`（issue #6580 的形态口径，本拆分沿用）
 *
 * `true` = 被配置指挥台挂载 —— 那种形态下本面板**不渲染自己那一层区块标题**「加工费组合」
 * （域面板已给标题与一句话）；其余一律相同。独立路由 / 旧 tab 形态按 `embedded=false` 原样渲染。
 *
 * ## 零行为变更（本拆分**不改一行逻辑/文案/testid**）
 *
 * 对照 v1 `ProcessingBoard` 的 `tab === 'fees'` 分支逐字搬运。两处如实登记的口径差异：
 * ① 勾选源的加工项**目录**（`items`）由本面板自取 —— v1 由 board 的 `loadItems` 喂同一次请求的 `data.items`
 *    （同一端点、同一 `{ page: 1, size: 999 }`、同一错误文案），本面板重取一次同形数据；
 * ② `onLoadingChange` 把 `feesLoading` 上报回 board（其「刷新」按钮 `disabled` 判据不变）。
 */
export default function FeeCombinationsPanel({
  embedded = false,
  onLoadingChange,
  onReloadReady,
}: {
  embedded?: boolean
  /** 把本面板的加载态上报给外层（board 的「刷新」按钮要在**任一**面板加载中时置灰） */
  onLoadingChange?: (loading: boolean) => void
  /** 把本面板的取数入口交给外层（board 的「刷新」按钮要能一键重取**两个**面板） */
  onReloadReady?: (reload: () => void) => void
} = {}) {
  const [combinations, setCombinations] = useState<FeeCombinationsResponse | null>(null)
  const [gaps, setGaps] = useState<FeeGaps | null>(null)
  const [gapsError, setGapsError] = useState('')
  // issue #6532：缺口明细**默认折叠**（常驻面只留一行摘要）—— 页面高度不随未定价组合数增长。
  const [gapsExpanded, setGapsExpanded] = useState(false)
  const [feesLoading, setFeesLoading] = useState(true)
  const [feesError, setFeesError] = useState('')

  /**
   * 勾选源（加工项目录）。v1 它是「加工项面板」的副作用顺带喂进来的；拆分后本面板自取
   * ⇒ 面板可独立挂载（issue #6585 的硬要求），代价是同一目录多取一次（如实登记在上方）。
   */
  const [items, setItems] = useState<ProcessingItem[]>([])
  const [itemsError, setItemsError] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [createPrice, setCreatePrice] = useState('')
  const [feeReasons, setFeeReasons] = useState<string[]>([])
  const [feeSaving, setFeeSaving] = useState(false)

  const [editId, setEditId] = useState<string | null>(null)
  const [editPrice, setEditPrice] = useState('')

  const loadCombinations = useCallback(async () => {
    setFeesLoading(true)
    setFeesError('')
    try {
      const res = await productionApi.getFeeCombinations()
      setCombinations(res.data?.data ?? null)
    } catch (e) {
      // 不 re-throw：本栏自己给可读提示 + 重试入口（re-throw 会变成未处理的 promise rejection，
      // 而「页面已提示」与「控制台报错」同时出现会让排查者误判成第二种故障）
      console.error(e)
      setCombinations(null)
      setFeesError('加工费组合加载失败，请重试')
    } finally {
      setFeesLoading(false)
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

  /** 勾选源目录（与加工项面板同一端点、同一错误文案 —— 两处必须说同一句话） */
  const loadItems = useCallback(async () => {
    try {
      const res = await processingItemApi.getProcessingItems({ page: 1, size: 999 })
      setItems(res.data?.data?.items || [])
      setItemsError('')
    } catch {
      setItems([])
      setItemsError('加工项加载失败，请重试')
    }
  }, [])

  useEffect(() => {
    void loadCombinations()
    void loadGaps()
    void loadItems()
  }, [loadCombinations, loadGaps, loadItems])

  useEffect(() => {
    onLoadingChange?.(feesLoading)
  }, [feesLoading, onLoadingChange])

  useEffect(() => {
    // 面板自带取数 ⇒ 外层的「刷新」只能借这条线（重取组合 + 缺口 + 勾选源目录；卸载时还原成空操作）
    onReloadReady?.(() => {
      void loadCombinations()
      void loadGaps()
      void loadItems()
    })
    return () => onReloadReady?.(() => {})
  }, [loadCombinations, loadGaps, loadItems, onReloadReady])

  // ────────────────────────── 加工费组合 ──────────────────────────

  const rows = combinations?.combinations ?? []
  const gapRows = gaps?.unpriced_combinations ?? []
  const pickedSet = useMemo(() => new Set(picked), [picked])

  const togglePick = (name: string) => {
    setPicked((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]))
  }

  const openCreateCombination = () => {
    setPicked([])
    setCreatePrice('')
    setFeeReasons([])
    setCreateOpen(true)
  }

  const submitCreate = async () => {
    // 空组合**本地先拦**（后端也会拒，但没必要发一个必然 422 的请求）
    if (picked.length === 0) {
      setFeeReasons(['至少选 1 个加工项：加工费按「选配组合」收，没有组合就没有可收的费'])
      return
    }
    if (createPrice.trim() === '' || Number.isNaN(Number(createPrice))) {
      setFeeReasons(['请填写加工费单价（元/米）'])
      return
    }
    setFeeSaving(true)
    setFeeReasons([])
    try {
      await productionApi.createFeeCombination({ items: picked, unit_price: Number(createPrice) })
      setCreateOpen(false)
      await Promise.all([loadCombinations(), loadGaps()])
    } catch (e) {
      // 护栏理由**逐条**展示（不吞后端理由，也不只弹「保存失败」）
      setFeeReasons(feeGuardReasons(e))
    } finally {
      setFeeSaving(false)
    }
  }

  const submitEdit = async (id: string) => {
    const price = Number(editPrice)
    if (editPrice.trim() === '' || Number.isNaN(price)) {
      setFeeReasons(['请填写加工费单价（元/米）'])
      return
    }
    try {
      await productionApi.updateFeeCombination(id, { unit_price: price })
      setEditId(null)
      await loadCombinations()
    } catch (e) {
      setFeeReasons(feeGuardReasons(e))
    }
  }

  const disableCombination = async (id: string) => {
    if (!window.confirm('停用这个加工费组合？停用后下单匹配不再取这一行（历史订单不受影响）。')) return
    try {
      await productionApi.disableFeeCombination(id)
      await loadCombinations()
    } catch (e) {
      setFeeReasons(feeGuardReasons(e))
    }
  }

  return (
    <div className="space-y-4" data-testid="processing-fees">
      {feesError ? (
        <div
          className="flex items-center gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          data-testid="fee-combinations-error"
        >
          <AlertCircle className="h-4 w-4" />
          {feesError}
          <Button variant="secondary" size="sm" onClick={() => void loadCombinations()} data-testid="fee-combinations-retry">
            重试
          </Button>
        </div>
      ) : null}

      {feeReasons.length > 0 ? (
        <div
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          data-testid="fee-combination-guard-reasons"
        >
          <div className="mb-1 font-medium">保存被拒，逐条原因：</div>
          <ul className="list-disc space-y-0.5 pl-5">
            {feeReasons.map((reason, i) => (
              <li key={i} data-testid={`fee-combination-guard-reason-${i}`}>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* ── 主区：组合定价列表 ── */}
      <section className="rounded-lg border border-neutral-200 bg-white" data-testid="fee-combinations">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-100 px-4 py-3">
          <div className="flex items-baseline gap-2">
            {!embedded && (
              <h2 className="text-sm font-medium text-neutral-800" data-testid="fee-combinations-title">
                加工费组合
              </h2>
            )}
            <span className="text-sm text-neutral-500" data-testid="fee-combinations-total">
              {feesLoading ? '加载中…' : `${rows.length}`}
            </span>
          </div>
          <Button size="sm" onClick={openCreateCombination} data-testid="fee-combination-new">
            <Plus className="mr-1.5 h-4 w-4" />
            新建组合
          </Button>
        </div>
        <p className="px-4 pt-3 text-xs text-neutral-500">
          一个组合<strong>一个价</strong>：韩褶+打孔 与 韩褶+打孔+定型 是两个不同的组合，各自定价。
        </p>

        {feesLoading ? (
          <div className="p-6 text-sm text-neutral-500">加载中…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-neutral-500" data-testid="fee-combinations-empty">
            还没有定价的组合：点「新建组合」把常卖的选配（如 韩褶+打孔）定一个价。
          </div>
        ) : (
          <div className="overflow-x-auto">
          <table className="mt-3 w-full text-sm">
            <thead className="bg-neutral-50 text-left text-neutral-500">
              <tr>
                <th className="px-4 py-2 font-medium whitespace-nowrap">选配组合</th>
                <th className="px-4 py-2 font-medium whitespace-nowrap">加工费单价</th>
                <th className="px-4 py-2 font-medium whitespace-nowrap">来源</th>
                <th className="px-4 py-2 font-medium whitespace-nowrap">操作</th>
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
                            setFeeReasons([])
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
                        onClick={() => void disableCombination(id)}
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
          </div>
        )}
      </section>

      {/* ── 次区：未定价缺口（只读告警，不是第二块主操作区）──
          issue #6532（研发模式 §31 P1 常驻面克制）：常驻面 = **一行**（标题 + 计数 + 开关），
          逐条明细**默认折叠且折叠态不渲染** ⇒ 这一段的高度不随未定价组合数增长。
          空态 / 错误态照旧常驻可见（不因折叠把「没有缺口」藏起来）。 */}
      <section className="rounded-lg border border-amber-200 bg-amber-50/40" data-testid="fee-gaps">
        <div
          className={cn(
            'flex items-center justify-between px-4 py-3',
            (gapsError || gapRows.length === 0 || gapsExpanded) && 'border-b border-amber-100',
          )}
        >
          <h2 className="text-sm font-medium text-amber-900">未定价组合（订单里出现过、但这里没有价）</h2>
          <div className="flex items-center gap-3">
            <span className="text-sm text-amber-800" data-testid="fee-gaps-total">
              {gapRows.length}
            </span>
            {!gapsError && gapRows.length > 0 ? (
              <button
                type="button"
                onClick={() => setGapsExpanded((v) => !v)}
                aria-expanded={gapsExpanded}
                data-testid="fee-gaps-toggle"
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-amber-800 transition-colors hover:bg-amber-100 hover:text-amber-900 focus:outline-none focus:ring-2 focus:ring-amber-400/60"
              >
                {gapsExpanded ? '收起' : `查看 ${gapRows.length} 条明细`}
                <ChevronDown
                  className={cn('h-3.5 w-3.5 transition-transform', gapsExpanded && 'rotate-180')}
                />
              </button>
            ) : null}
          </div>
        </div>
        {gapsError ? (
          <div className="p-4 text-sm text-amber-800" data-testid="fee-gaps-unavailable">
            {gapsError}
          </div>
        ) : gapRows.length === 0 ? (
          <div className="p-4 text-sm text-amber-800" data-testid="fee-gaps-empty">
            没有未定价组合（当前成交的选配组合都已定价）。
          </div>
        ) : gapsExpanded ? (
          <ul className="max-h-56 divide-y divide-amber-100 overflow-y-auto">
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
        ) : null}
      </section>

      {/* ── 新建加工费组合 ── */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="新建加工费组合"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void submitCreate()} disabled={feeSaving} data-testid="fee-combination-submit">
              保存
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <div>
            <div className="mb-2 text-sm font-medium text-neutral-700">选配组合（可多选）</div>
            {items.length === 0 ? (
              <div className="text-sm text-neutral-500" data-testid="fee-combination-catalog-empty">
                {/* 目录为空 vs 加载失败**必须分开说**：勾选源与「加工项」tab 同一份目录，
                    把加载失败说成「目录为空」会让商家去建一个其实已经存在的加工项 */}
                {itemsError
                  ? '加工项目录加载失败：请到「加工项」tab 点「重试」后再建组合。'
                  : '加工项目录为空：请先到「加工项」tab 建加工项。'}
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {items.map((item) => (
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
              一个组合<strong>一个价</strong>：韩褶+打孔 与 韩褶+打孔+定型 是两个不同的组合，各自定价。
            </p>
          </div>
        </div>
      </Modal>
    </div>
  )
}
