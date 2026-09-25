'use client'

import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, FolderTree, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { processingCategoryApi, processingItemApi, productionApi } from '@/lib/api'
import { feeGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type {
  FeeCombinationsResponse,
  FeeGaps,
  ProcessingCategory,
  ProcessingItem,
} from '@/types'

/**
 * 加工项管理 /production/processing（issue #4490）
 *
 * **用户裁定（2026-09-19）**：「**加工项**和**加工项费用**这两个我建议**合并成一个菜单**，
 * 也**放到生产管理菜单下**」。
 *
 * 为什么合并：两者是**同一业务域**（加工项及其定价）且共用**同一菜单入口**（节点码自 issue #5291 起 = 读码
 * `production:view`；页内写动作仍是 `processing:manage`），
 * 却被拆在两个菜单组里 —— 「加工项管理」在**商品管理**组、「加工费管理」在**生产管理**组。
 * 加工费组合的定价对象就是加工项本身（`POST /processing-fee-combinations` 的 `items[]` 必须
 * 是加工项目录里活跃的**加工项名**，后端护栏逐条校验），拆开意味着「建组合发现缺加工项要跳到
 * 另一个菜单组去建」——与 #4416（工序库 + 工艺路线）合并的动因同型。
 *
 * 页面形态（**用户总要求**：「别把功能直接平铺到一个页面上，还是需要保证 UI 设计质量的」）：
 * - **两个 tab**（沿用 #4482 在 `/production/routings` 确立的 tab 范式与类名）：
 *   `加工项`（列表 + CRUD + 分类）与 `加工费组合`（选配组合 → 单价 元/米 + 未定价缺口）。
 *   合并仍是**一个菜单入口、一个页面**，只改**内部组织** —— 不是把两个域依次堆进一屏。
 * - **每个 tab 只回答一个问题**：①「我有哪些加工项？」②「哪几个加工项一起用时收多少？」
 * - **一屏一件事**：单 tab 内分主次 —— 主区是列表与主操作（新增加工项 / 新建组合），
 *   次区是只读/低频面（加工分类走**抽屉**、未定价缺口是**辅助告警条**），不做「三块大卡片平铺」。
 * - **空态即引导**（列表空态直接给下一步）、**危险操作二次确认**（删加工项走确认弹窗、
 *   停用组合走 `window.confirm`）、**护栏理由就地展示**（后端 `error.details[].message` 逐条）。
 * - **切 tab 不丢状态**：两栏的 state 都挂在**同一个组件**上，条件渲染不重置它们
 *   （形态同 #4482：编辑中的表单 / 勾选中的组合在切走再切回后仍在）。
 *
 * 契约（冻结，**不得自行发明端点/字段名**）：
 *   GET|POST /api/admin/processing-items            PUT|DELETE /processing-items/{id}
 *   GET|POST /api/admin/processing-categories
 *   GET|POST /api/admin/production/processing-fee-combinations
 *   PUT|DELETE /api/admin/production/processing-fee-combinations/{id}
 *   GET  /api/admin/production/processing-fee-gaps
 *   —— 写端点权限统一 `processing:manage`（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 两处**故意**不做（沿 #4386 的口径，本单不推翻）：
 * ① **不在前端拼 composition_key**：归一化（与书写顺序无关）是服务端的事 —— 前端自己拼会变成
 *    第二份口径，两边一旦漂移就会出现「页面显示一个组合、库里是另一个」的静默错配。
 * ② **不接线计价**：本页只管配置；下单侧取价（`OrderService.sumProcessingFee` / 下单页 /
 *    ai-agent）不在本包。
 *
 * 旧路径：`/processing` 与 `/production/processing-fees` 都改为重定向到本页
 * （照 #4357 的 `/processing-orders` → `/production`、#4416 的 `/production/operations` →
 * `/production/routings` 先例，旧书签/外部深链不 404）。其中加工费那一条带上 `?tab=fees`
 * 直达「加工费组合」—— 后端未定价提示里的链接（`ProcessingFeeCalculator`）指向的就是旧路径。
 */

/**
 * 弹窗内表单数据（加工项）。
 *
 * issue #4882（用户裁定）：加工项的**单价**与**计价方式**整体退场 —— 加工项本身不再持有价，
 * 价只由「加工费组合」（元/米）决定 ⇒ 表单只留名称 / 加工分类 / 优惠。
 */
interface ItemForm {
  name: string
  discount: string
  discountQty: string
  discountRate: string
  categoryId: string
}

/** 优惠类型选项 */
const DISCOUNT_OPTIONS = [
  { value: '', label: '无优惠' },
  { value: 'amount_off', label: '按金额满减' },
]

/** 满X件选项（2-99） */
const QTY_OPTIONS = Array.from({ length: 98 }, (_, i) => ({
  value: String(i + 2),
  label: `满${i + 2}件`,
}))

const EMPTY_FORM: ItemForm = {
  name: '',
  discount: '',
  discountQty: '2',
  discountRate: '',
  categoryId: '',
}

const money = (v?: number | null) => `¥${Number(v ?? 0).toFixed(2)}`

const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'

/** 两个 tab（用户裁定 2026-09-19）：`items` 加工项 / `fees` 加工费组合 */
const TABS = [
  { key: 'items', label: '加工项' },
  { key: 'fees', label: '加工费组合' },
] as const

type TabKey = (typeof TABS)[number]['key']

/**
 * `useSearchParams` 必须包在 Suspense 里（Next 14 的静态预渲染期读 searchParams 会要求边界；
 * 形态照 `app/(dashboard)/chat/page.tsx`）—— 页面本体是纯客户组件，fallback 留空即可。
 */
export default function ProcessingPage() {
  return (
    <Suspense fallback={null}>
      <ProcessingContent />
    </Suspense>
  )
}

function ProcessingContent() {
  const searchParams = useSearchParams()
  /** 默认落在「加工项」（依赖顺序上在前：先有加工项，才能给它组价）；`?tab=fees` 直达第二栏 */
  const [tab, setTab] = useState<TabKey>(searchParams?.get('tab') === 'fees' ? 'fees' : 'items')

  // ── 加工项域 ──
  const [items, setItems] = useState<ProcessingItem[]>([])
  const [categories, setCategories] = useState<ProcessingCategory[]>([])
  const [itemsLoading, setItemsLoading] = useState(true)
  const [itemsError, setItemsError] = useState('')
  const [saving, setSaving] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<ItemForm>(EMPTY_FORM)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)

  /** 加工分类抽屉（次区：分类只用于归类，不占主列表的位置） */
  const [categoryOpen, setCategoryOpen] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [creatingCategory, setCreatingCategory] = useState(false)

  // ── 加工费组合域 ──
  const [combinations, setCombinations] = useState<FeeCombinationsResponse | null>(null)
  const [gaps, setGaps] = useState<FeeGaps | null>(null)
  const [gapsError, setGapsError] = useState('')
  const [feesLoading, setFeesLoading] = useState(true)
  const [feesError, setFeesError] = useState('')

  const [createOpen, setCreateOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [createPrice, setCreatePrice] = useState('')
  const [feeReasons, setFeeReasons] = useState<string[]>([])
  const [feeSaving, setFeeSaving] = useState(false)

  const [editId, setEditId] = useState<string | null>(null)
  const [editPrice, setEditPrice] = useState('')

  /**
   * 加工项 + 加工分类：**一份数据两处用**（列表 + 新建组合的勾选源）。
   * 合并前两个页面各拉一次加工项目录（999 / 200），同一份数据两处渲染 —— 这正是合并要消灭的形态。
   */
  const loadItems = useCallback(async () => {
    setItemsLoading(true)
    setItemsError('')
    const [itemsRes, catsRes] = await Promise.allSettled([
      processingItemApi.getProcessingItems({ page: 1, size: 999 }),
      processingCategoryApi.getProcessingCategories(),
    ])
    if (itemsRes.status === 'fulfilled') {
      setItems(itemsRes.value.data?.data?.items || [])
    } else {
      setItems([])
      setItemsError('加工项加载失败，请重试')
    }
    // 分类只喂表单下拉与抽屉：它失败不得把加工项列表一起打白屏（同 #4307 的处置）
    setCategories(catsRes.status === 'fulfilled' ? catsRes.value.data?.data || [] : [])
    setItemsLoading(false)
  }, [])

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

  useEffect(() => {
    void loadItems()
    void loadCombinations()
    void loadGaps()
  }, [loadItems, loadCombinations, loadGaps])

  const refreshAll = useCallback(async () => {
    await Promise.all([loadItems(), loadCombinations(), loadGaps()])
  }, [loadItems, loadCombinations, loadGaps])

  // ────────────────────────── 加工项：CRUD ──────────────────────────

  const openCreate = () => {
    setEditingId(null)
    // 默认选中第一个加工分类；无分类时留空并在弹窗内引导创建
    setForm({ ...EMPTY_FORM, categoryId: categories[0]?.id || '' })
    setErrors({})
    setFormOpen(true)
  }

  const openEdit = (item: ProcessingItem) => {
    setEditingId(item.id)
    setForm({
      name: item.name,
      discount: '',
      discountQty: '2',
      discountRate: '',
      categoryId: item.categoryId || categories[0]?.id || '',
    })
    setErrors({})
    setFormOpen(true)
  }

  const closeForm = () => {
    if (saving) return
    setFormOpen(false)
  }

  const updateField = <K extends keyof ItemForm>(field: K, value: ItemForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    setErrors((prev) => ({ ...prev, [field]: '' }))
  }

  const validate = (): Record<string, string> => {
    const errs: Record<string, string> = {}
    if (!form.name.trim()) {
      errs.name = '请输入加工项名称'
    } else if (form.name.trim().length > 20) {
      errs.name = '名称不能超过20个字符'
    }

    if (!form.categoryId) {
      errs.categoryId = '请先选择或创建加工分类'
    }

    return errs
  }

  /** 加工分类写路径统一出口（表单内联创建 + 抽屉创建共用，避免第二份实现） */
  const handleCreateCategory = async () => {
    const name = newCategoryName.trim()
    if (!name) {
      toast.error('请输入加工分类名称')
      return
    }
    setCreatingCategory(true)
    try {
      const res = await processingCategoryApi.createProcessingCategory({ name, sort: 0 })
      toast.success('加工分类已创建')
      await loadItems()
      // 自动选中刚创建的分类（表单开着时立刻可用；抽屉场景下 setForm 无害 —— openCreate 会重置）
      const created = res.data?.data
      setForm((prev) => ({ ...prev, categoryId: created?.id || prev.categoryId || categories[0]?.id || '' }))
      setNewCategoryName('')
    } catch (error) {
      console.error('创建加工分类失败:', error)
      toast.error('创建加工分类失败')
    } finally {
      setCreatingCategory(false)
    }
  }

  const handleSubmit = async () => {
    const errs = validate()
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }

    setSaving(true)
    try {
      const payload = {
        name: form.name.trim(),
        categoryId: form.categoryId, // 用户显式选择（此前强取 categories[0] 且新租户为空 → 提交 'default' 报「加工分类不存在」）
        // 单位恒为「米」（#4882）：加工费按米计价是行业口径（#3005），V83 目录 16 项全 per_meter；
        // 计价方式既已整体退场，就没有第二个取值来源 —— 这里不留可变量，也不按计价方式查表。
        unit: '米',
        status: 'active' as const,
      }

      if (editingId) {
        await processingItemApi.updateProcessingItem(editingId, payload)
        toast.success('已更新加工项')
      } else {
        await processingItemApi.createProcessingItem(payload)
        toast.success('已新增加工项')
      }

      setFormOpen(false)
      await loadItems()
    } catch (error) {
      console.error('保存失败:', error)
      toast.error('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const requestDelete = (id: string) => {
    setDeleteTargetId(id)
    setDeleteConfirmOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleteTargetId) return
    try {
      await processingItemApi.deleteProcessingItem(deleteTargetId)
      toast.success('删除成功')
      await loadItems()
    } catch {
      toast.error('删除失败')
    } finally {
      setDeleteConfirmOpen(false)
      setDeleteTargetId(null)
    }
  }

  const categoryNameOf = (item: ProcessingItem) =>
    item.categoryName || categories.find((c) => c.id === item.categoryId)?.name || '—'

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
    <div className="space-y-5 p-6" data-testid="processing-page">
      {/* ── 页头：一件事（这个页面管「加工项」和它的「加工费组合」）── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">加工项管理</h1>
          <p className="mt-1 text-sm text-neutral-500">
            加工项是下单时客户可选的加工服务（如 韩褶、打孔）；加工费按<strong>选配组合</strong>定价（元/米），
            下单时由系统按选配结果自动匹配取价，顾客只选配、不报价。
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void refreshAll()}
          disabled={itemsLoading || feesLoading}
          data-testid="processing-refresh"
        >
          <RefreshCw className={cn('mr-1.5 h-4 w-4', (itemsLoading || feesLoading) && 'animate-spin')} />
          刷新
        </Button>
      </div>

      {/* ── 两个 tab（沿用 #4482 的 tab 范式与类名）── */}
      <div className="flex items-center gap-1 border-b border-neutral-200" role="tablist" data-testid="processing-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            data-testid={`processing-tab-${t.key}`}
            data-state={tab === t.key ? 'active' : 'inactive'}
            onClick={() => setTab(t.key)}
            className={cn(
              '-mb-px border-b-2 px-4 py-2 text-sm transition-colors',
              tab === t.key
                ? 'border-primary-600 font-medium text-primary-700'
                : 'border-transparent text-neutral-500 hover:text-neutral-800',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ══════════════ tab「加工项」：有哪些加工项（CRUD / 分类） ══════════════ */}
      {tab === 'items' && (
        <section className="rounded-lg border border-neutral-200 bg-white" data-testid="processing-items">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-100 px-4 py-3">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-medium text-neutral-800">加工项</h2>
              <span className="text-sm text-neutral-500" data-testid="processing-items-total">
                {items.length} 项
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {/* 次操作：分类只用于归类，走抽屉，不占主列表 */}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setCategoryOpen(true)}
                data-testid="processing-categories-open"
              >
                <FolderTree className="mr-1.5 h-4 w-4" />
                加工分类（{categories.length}）
              </Button>
              <Button size="sm" onClick={openCreate} data-testid="processing-item-new">
                <Plus className="mr-1.5 h-4 w-4" />
                新增加工项
              </Button>
            </div>
          </div>

          {itemsError ? (
            <div className="m-4 flex items-center gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4" />
              <span data-testid="processing-items-error">{itemsError}</span>
              <Button variant="secondary" size="sm" onClick={() => void loadItems()} data-testid="processing-items-retry">
                重试
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="mt-3 w-full border-collapse">
                <thead>
                  <tr className="border-b border-neutral-200 bg-neutral-50/60">
                    <th className="w-[45%] whitespace-nowrap px-4 py-3 text-left text-sm font-semibold text-neutral-900">
                      加工项名称
                    </th>
                    <th className="w-[30%] whitespace-nowrap px-4 py-3 text-left text-sm font-semibold text-neutral-900">
                      加工分类
                    </th>
                    <th className="w-[25%] whitespace-nowrap px-4 py-3 text-left text-sm font-semibold text-neutral-900">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {itemsLoading ? (
                    <tr>
                      <td colSpan={3} className="px-4 py-12 text-center text-neutral-500">
                        <div className="flex items-center justify-center gap-2">
                          <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
                          加载中...
                        </div>
                      </td>
                    </tr>
                  ) : items.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-4 py-12 text-center text-sm text-neutral-400">
                        <span data-testid="processing-items-empty">
                          暂无加工项 —— 点右上「新增加工项」建第一个（如 韩褶、打孔）
                          {categories.length === 0 && '；当前还没有加工分类，可在新增弹窗里直接创建'}
                        </span>
                      </td>
                    </tr>
                  ) : (
                    items.map((item) => (
                      <Fragment key={item.id}>
                        <tr className="border-b border-neutral-100 hover:bg-neutral-50/40" data-testid={`processing-item-${item.id}`}>
                          <td className="px-4 py-3 text-sm text-neutral-900">{item.name}</td>
                          <td className="px-4 py-3 text-sm text-neutral-600">{categoryNameOf(item)}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3 whitespace-nowrap">
                              <button
                                onClick={() => openEdit(item)}
                                className="text-sm text-primary-600 transition-colors hover:text-primary-700 hover:underline"
                              >
                                编辑
                              </button>
                              <button
                                onClick={() => requestDelete(item.id)}
                                className="text-sm text-red-500 transition-colors hover:text-red-600 hover:underline"
                              >
                                删除
                              </button>
                            </div>
                          </td>
                        </tr>
                      </Fragment>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ══════════════ tab「加工费组合」：哪几个加工项一起用时收多少 ══════════════ */}
      {tab === 'fees' && (
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
                <h2 className="text-sm font-medium text-neutral-800">加工费组合</h2>
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
              <table className="mt-3 w-full text-sm">
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
            )}
          </section>

          {/* ── 次区：未定价缺口（只读告警，不是第二块主操作区）── */}
          <section className="rounded-lg border border-amber-200 bg-amber-50/40" data-testid="fee-gaps">
            <div className="flex items-center justify-between border-b border-amber-100 px-4 py-3">
              <h2 className="text-sm font-medium text-amber-900">未定价组合（订单里出现过、但这里没有价）</h2>
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
        </div>
      )}

      {/* ── 抽屉：加工分类（次区，只读列表 + 新建；改/删不在此，后端也未提供）── */}
      <Modal
        open={categoryOpen}
        onClose={() => setCategoryOpen(false)}
        title="加工分类"
        width={480}
        footer={
          <Button variant="secondary" onClick={() => setCategoryOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-3">
          <p className="text-xs text-neutral-500">
            分类只用于给加工项归类（如「基础加工」「窗帘加工」）；加工项必须归属于一个分类。
          </p>
          {categories.length === 0 ? (
            <p className="text-sm text-neutral-500" data-testid="processing-categories-empty">
              还没有加工分类 —— 在下面新建一个。
            </p>
          ) : (
            <ul className="divide-y divide-neutral-100" data-testid="processing-categories-list">
              {categories.map((c) => (
                <li key={c.id} className="py-2 text-sm text-neutral-900" data-testid={`processing-category-${c.id}`}>
                  {c.name}
                </li>
              ))}
            </ul>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              className="h-9 flex-1 rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              placeholder="新分类名称（如：基础加工）"
              value={newCategoryName}
              onChange={(e) => setNewCategoryName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleCreateCategory()}
              data-testid="processing-category-name"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void handleCreateCategory()}
              loading={creatingCategory}
              className="shrink-0"
            >
              创建
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── 新增/编辑加工项弹窗 ── */}
      <Modal
        open={formOpen}
        onClose={closeForm}
        title={editingId ? '编辑加工项' : '新增加工项'}
        width={560}
        maskClosable={!saving}
        footer={
          <>
            <Button variant="secondary" onClick={closeForm} disabled={saving}>
              取消
            </Button>
            <Button onClick={() => void handleSubmit()} loading={saving}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {/* 加工项名称 */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-neutral-800">
              加工项名称<span className="ml-0.5 text-red-500">*</span>
            </label>
            <input
              type="text"
              className={`h-9 w-full rounded border px-3 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                errors.name ? 'border-red-500' : 'border-neutral-300'
              }`}
              placeholder="请输入加工项名称（最多20个字符）"
              maxLength={20}
              value={form.name}
              onChange={(e) => updateField('name', e.target.value)}
            />
            {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name}</p>}
          </div>

          {/* 加工分类（必选：后端加工项强依赖加工分类，新租户从 0 需先建） */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-neutral-800">
              加工分类<span className="ml-0.5 text-red-500">*</span>
            </label>
            {categories.length > 0 ? (
              <select
                className={`h-9 w-full appearance-none rounded border bg-white px-3 pr-8 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                  errors.categoryId ? 'border-red-500' : 'border-neutral-300'
                }`}
                value={form.categoryId}
                onChange={(e) => updateField('categoryId', e.target.value)}
              >
                <option value="" disabled>
                  请选择加工分类
                </option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs text-amber-700">
                  当前还没有加工分类，加工项必须归属于一个加工分类。请先创建：
                </p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    className="h-9 flex-1 rounded border border-amber-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    placeholder="请输入加工分类名称，如：基础加工"
                    value={newCategoryName}
                    onChange={(e) => setNewCategoryName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && void handleCreateCategory()}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void handleCreateCategory()}
                    loading={creatingCategory}
                    className="shrink-0"
                  >
                    创建
                  </Button>
                </div>
              </div>
            )}
            {errors.categoryId && categories.length > 0 && (
              <p className="mt-1 text-xs text-red-600">{errors.categoryId}</p>
            )}
          </div>

          {/* 设置优惠 */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-neutral-800">设置优惠</label>
            <select
              className="h-9 w-full appearance-none rounded border border-neutral-300 bg-white px-3 pr-8 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={form.discount}
              onChange={(e) => updateField('discount', e.target.value)}
            >
              {DISCOUNT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            {form.discount === 'amount_off' && (
              <div className="mt-2 flex items-center gap-2">
                <select
                  className="h-9 appearance-none rounded border border-neutral-300 bg-white px-3 pr-8 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  value={form.discountQty}
                  onChange={(e) => updateField('discountQty', e.target.value)}
                >
                  {QTY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <div className="flex items-center">
                  <input
                    type="text"
                    className="h-9 w-32 rounded-l border border-neutral-300 px-3 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    placeholder="请输入折扣力度"
                    value={form.discountRate}
                    onChange={(e) => updateField('discountRate', e.target.value)}
                  />
                  <span className="flex h-9 items-center rounded-r border border-l-0 border-neutral-300 bg-neutral-50 px-2 text-sm text-neutral-600">
                    折
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </Modal>

      {/* ── 删除确认（危险操作二次确认）── */}
      <Modal
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteConfirmOpen(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()}>
              确定
            </Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-neutral-600">
          删除后，当用户再购买已关联当前加工项的商品时，将不会再看到当前加工项。确定要删除当前加工项吗？
        </p>
      </Modal>

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
                {/* 目录为空 vs 加载失败**必须分开说**：合并后勾选源与「加工项」tab 同一份数据，
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
