'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { toast } from 'sonner'
import { workerApi, workerPageCatalogApi } from '@/lib/api'
import { toastRequestError } from '@/lib/api-error'
import { Button, Input, Select, Modal, Table, Badge, Pagination } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { EmployeeStatus, WorkerOperationOption, WorkerProfile } from '@/types'

/**
 * 工人档案（issue #4869）—— **产品路径：第一个工人怎么建出来**。
 *
 * 改前形态：全仓没有任何入口能设 `users.worker_no`（无控制台 / 无接口 / 无种子）
 * ⇒ 工号 + PIN 登录（#4733，早已落码）在真实部署里**永远没有可登录的对象**。
 *
 * 与员工的关系（本组件存在的理由）：
 * - 工人**不是**员工：零**商家后台**菜单权限（工人端菜单是另一回事，见下）、无登录用户名、
 *   只能用工号 + PIN 进工人端扫码报工 ⇒ 不能混进员工列表（那会「看起来像员工」，
 *   点编辑还能改岗位/权限，而那条路根本不成立）。
 *   本面板独立成 Tab；服务端也在 `UserService.getUserPage` 里排除 `role=worker`。
 * - **工人端菜单**（issue #6788；单层口径 issue #6828）：这一位工人在工人端看得见哪几页 = 本档案上的
 *   收窄（不勾 = 全部页面）。本面板只做**选项与回显**，词表与校验全在服务端
 *   （目录端点 `GET /api/admin/worker-pages` + `WorkerPages` + `WorkerAdminService`），
 *   且这**不是**权限码 —— 工人 session 的
 *   `permissions` 恒为 `[]`，藏起菜单 ≠ 挡住接口。
 * - 权限码**复用**员工域（`employee:create` / `employee:list`）—— 新增权限码要走迁移 + 全租户回填，
 *   而工人在产品上就是人事管理的一部分。
 * - 停用 / 启用**复用**既有 `PUT /api/admin/users/{id}/status`（`workerApi.setWorkerStatus`），不另造端点。
 */
/** 工人端菜单的勾选态（建号 / 改菜单共用）：`pages === null` = 未收窄（默认页全勾）。 */
interface WorkerPagesValue {
  pages: string[] | null
  optional: string[]
}

/**
 * 工人端菜单勾选区（issue #6788 建号 / issue #7804 改菜单 —— **同一份渲染**）。
 *
 * 两个弹窗共用它，是因为「改之前能设、改之后设不了」正是 #7804 的病灶：
 * 建号与编辑各写一套勾选逻辑 ⇒ 两边迟早分叉（一处收窄、一处全勾）。
 * 词表与名称仍全部来自服务端目录（前端不维护第二份会漂的页面清单）。
 */
function WorkerPagesPicker({
  menuPages,
  optionalPages,
  value,
  onChange,
}: {
  menuPages: { key: string; label: string }[]
  optionalPages: { key: string; label: string }[]
  value: WorkerPagesValue
  onChange: (next: WorkerPagesValue) => void
}) {
  /** 勾选态：`null` = 未收窄 = 全勾（全部默认页面）。 */
  const isChecked = (key: string) => value.pages === null || value.pages.includes(key)

  return (
    <>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-neutral-700">工人端菜单</span>
        <button
          type="button"
          data-testid="worker-pages-select-all"
          onClick={() => onChange({ ...value, pages: null })}
          className="text-xs text-primary-600 hover:text-primary-700 hover:underline"
        >
          默认页面
        </button>
      </div>
      <div className="space-y-1">
        {menuPages.map((page) => (
          <label
            key={page.key}
            className="flex items-center gap-3 p-1.5 rounded hover:bg-neutral-50 cursor-pointer"
            data-testid={`worker-page-option-${page.key}`}
          >
            <input
              type="checkbox"
              className="w-4 h-4"
              checked={isChecked(page.key)}
              onChange={() => {
                // 从「未收窄（全勾）」取消一项 ⇒ 展开成「除这一项外全勾」，而不是空集
                const current = value.pages === null ? menuPages.map((p) => p.key) : value.pages
                onChange({
                  ...value,
                  pages: current.includes(page.key)
                    ? current.filter((k) => k !== page.key)
                    : [...current, page.key],
                })
              }}
            />
            <span className="text-sm text-neutral-800">{page.label}</span>
          </label>
        ))}
      </div>
      {value.pages !== null && value.pages.length === 0 ? (
        <p className="text-xs text-amber-700 mt-1.5" data-testid="worker-pages-empty-hint">
          至少要留一个页面。一页都不留并不是「什么都不显示」——工人端会当成「没读到权限」按全开运行；
          要让这位工人不干活，请改用「停用」。
        </p>
      ) : (
        <p className="text-xs text-neutral-400 mt-1.5">
          只勾这一位工人要用的页面，他就只在工人端看到这些入口；全部勾选 = 默认页面（不含下面单独开放的质检）。
        </p>
      )}

      {/* 逐人开放的能力页（issue #7162）：质检不在默认菜单里，且服务端把这一项当写准入 */}
      {optionalPages.length > 0 && (
        <div className="pt-3 mt-3 border-t border-neutral-100" data-testid="worker-optional-pages">
          <span className="text-sm font-medium text-neutral-700">单独开放</span>
          <div className="space-y-1 mt-1.5">
            {optionalPages.map((page) => (
              <label
                key={page.key}
                className="flex items-center gap-3 p-1.5 rounded hover:bg-neutral-50 cursor-pointer"
                data-testid={`worker-page-optional-${page.key}`}
              >
                <input
                  type="checkbox"
                  className="w-4 h-4"
                  checked={value.optional.includes(page.key)}
                  onChange={() => onChange({
                    ...value,
                    optional: value.optional.includes(page.key)
                      ? value.optional.filter((k) => k !== page.key)
                      : [...value.optional, page.key],
                  })}
                />
                <span className="text-sm text-neutral-800">{page.label}</span>
                <span className="text-xs text-neutral-400">扫水洗唛后录判定、生成质检单</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

interface WorkerProfilesPanelProps {
  /** 是否持有 `employee:create`（无此权限 ⇒ 只读） */
  canWrite: boolean
}

export default function WorkerProfilesPanel({ canWrite }: WorkerProfilesPanelProps) {
  const [workers, setWorkers] = useState<WorkerProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const [keyword, setKeyword] = useState('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | EmployeeStatus>('')
  const [searchStatus, setSearchStatus] = useState<'' | EmployeeStatus>('')

  const [formOpen, setFormOpen] = useState(false)
  // 工人端菜单（issue #6788）：建号时默认**全勾** = 不限制（零回归）；少勾一个 ⇒ 收窄。
  // 工人端菜单（issue #6788）：`pages === null` = **未收窄** = 全勾（= 全部页面，零回归）。
  // 🔴 用 null 而不是 `menuPages.map(...)` 快照：目录还没拉回来时不会把「不限制」误判成空集
  // （空集在工人端会被读成「没读到权限 ⇒ 全开」，与「一页都不给」正好相反）。
  const [form, setForm] = useState<{
    workerNo: string
    name: string
    pin: string
    /** 绑定的逻辑工序（issue #7749）：'' = 不设工序（出入库/仓库等岗位；生产工人留空则扫码后自己选） */
    workerOperation: string
    pages: string[] | null
    /** 逐人开放的能力页键（issue #7162；与 `pages` 分开 ⇒ 默认集合的语义不受影响） */
    optional: string[]
  }>({ workerNo: '', name: '', pin: '', workerOperation: '', pages: null, optional: [] })
  const [creating, setCreating] = useState(false)
  const [togglingId, setTogglingId] = useState<string | null>(null)

  /**
   * 工人端页面目录（键 + 人话名）—— 逐人收窄的**选项来源**（issue #6828）。
   *
   * 🔴 页面词表与名称都取**服务端**（`GET /api/admin/worker-pages`）⇒ 前端不维护第二份会漂的
   * 页面清单；读不到（如当前岗位没有生产域读码）⇒ 留空 = 这一节不显示（**不**自己编一份默认页集）。
   */
  const [menuPages, setMenuPages] = useState<{ key: string; label: string }[]>([])
  /** 默认页面键（未收窄时的勾选态；issue #7162：「未收窄」= 默认页，不含逐人开放的能力页）。 */
  const [defaultPageKeys, setDefaultPageKeys] = useState<string[]>([])
  /** 非默认、逐人开放的能力页（issue #7162：质检 —— 同时是服务端写准入）。 */
  const [optionalPages, setOptionalPages] = useState<{ key: string; label: string }[]>([])
  const [togglingOptional, setTogglingOptional] = useState<string | null>(null)

  // 改菜单（issue #7804）：存量工人的工人端菜单**整集编辑**（默认页收窄 + 单独开放）。
  // 建号时能设、建完就改不了曾是 PG-072 登记的未固化项（用户 2026-10-26：「这个页面不能修改工人菜单」）。
  const [pagesTarget, setPagesTarget] = useState<WorkerProfile | null>(null)
  const [pagesDraft, setPagesDraft] = useState<WorkerPagesValue>({ pages: null, optional: [] })
  const [savingPages, setSavingPages] = useState(false)

  /**
   * 可绑定的**逻辑工序**目录（issue #7749）：选项来源 = 服务端
   * （`GET /api/admin/workers/operations`，人事域读码）—— 前端不维护第二份工序清单。
   * 读不到 / 为空 ⇒ 下拉只剩「不设工序」，并提示先去工序库建工序（不自己编选项）。
   */
  const [operationOptions, setOperationOptions] = useState<WorkerOperationOption[]>([])
  // 改绑工序弹窗（存量工人也能改 —— 只在建号时能设等于「绑错了只能重建档案」）
  const [opTarget, setOpTarget] = useState<WorkerProfile | null>(null)
  const [opValue, setOpValue] = useState('')
  const [savingOp, setSavingOp] = useState(false)

  // 重置 PIN（issue #6432）：弹窗两态 —— ① 输入 / 随机生成新 PIN ② 明文展示新 PIN（只显示这一次）
  const [pinTarget, setPinTarget] = useState<WorkerProfile | null>(null)
  const [pinInput, setPinInput] = useState('')
  const [newPin, setNewPin] = useState<string | null>(null)
  const [resettingPin, setResettingPin] = useState(false)

  const loadWorkers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await workerApi.listWorkers({
        page: current,
        size: pageSize,
        keyword: searchKeyword || undefined,
        status: searchStatus || undefined,
      })
      const data = res.data.data
      setWorkers(data?.items || [])
      setTotal(data?.total || 0)
    } catch (e) {
      toastRequestError(e, '加载工人档案失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchKeyword, searchStatus])

  useEffect(() => {
    loadWorkers()
  }, [loadWorkers])

  /** 拉工人端页面目录（只读）。失败 ⇒ 静默留空（这一节不显示，不影响建号主流程）。 */
  useEffect(() => {
    let alive = true
    workerPageCatalogApi.get()
      .then((res) => {
        const data = res.data?.data
        if (!alive || !data?.pages) return
        // 默认页 / 可选能力页都取服务端（issue #7162）：选择器只列默认页，
        // inspect 这类「逐人开放 + 服务端写准入」的页单独一栏，不与默认集合混在「全勾」里。
        const defaults = data.default_pages?.length ? data.default_pages : data.pages
        const optional = (data.optional_pages ?? []).filter((key) => data.pages.includes(key))
        setDefaultPageKeys(defaults)
        setOptionalPages(optional.map((key) => ({ key, label: data.labels?.[key] || key })))
        setMenuPages(
          data.pages
            .filter((key) => defaults.includes(key))
            .map((key) => ({ key, label: data.labels?.[key] || key })),
        )
      })
      .catch(() => { if (alive) setMenuPages([]) })
    return () => { alive = false }
  }, [])

  /** 拉「可绑定的逻辑工序」目录（只读）。失败 ⇒ 静默留空（下拉只剩「不设工序」，不影响建号主流程）。 */
  useEffect(() => {
    let alive = true
    workerApi.listWorkerOperations()
      .then((res) => {
        if (alive) setOperationOptions(res.data?.data?.operations ?? [])
      })
      .catch(() => { if (alive) setOperationOptions([]) })
    return () => { alive = false }
  }, [])

  const handleSearch = () => {
    setCurrent(1)
    setSearchKeyword(keyword)
    setSearchStatus(statusFilter)
  }

  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setCurrent(1)
    setSearchKeyword('')
    setSearchStatus('')
  }

  const handleOpenCreate = () => {
    // 默认**未收窄**（= 不限制，看全部页面）。存 null 而不是 menuPages 的快照 ⇒ 目录还没拉回来、
    // 或目录在弹窗打开后到达，都不会把「不限制」误判成「一页都没勾」。
    setForm({ workerNo: '', name: '', pin: '', workerOperation: '', pages: null, optional: [] })
    setFormOpen(true)
  }

  /**
   * 这一位工人被收窄到哪几页（人话名）；`null` = **全部页面**。
   *
   * 🔴 空数组（`[]`）也按「全部页面」显示（issue #6828 复核发现显示与契约相反）：写面本就 422 拒空数组
   * （只能来自脏数据 / 直连 DB），而读面 `WorkerPages.effectiveFor` 对「归一后为空集」一律**回落全部页面**
   * （与 worker-h5 的 fail-open 同口径）⇒ 显示必须跟着读面口径走，否则商家看到「未开放任何页面」
   * 而工人实际看到全部四页。
   */
  const menuSummary = (record: WorkerProfile): string | null => {
    const assigned = record.workerPages
    if (assigned == null || assigned.length === 0) return null
    return assigned
      .map((key) => menuPages.find((p) => p.key === key)?.label
        || optionalPages.find((p) => p.key === key)?.label
        || key)
      .join('、')
  }

  /**
   * 表单 → `worker_pages`（issue #7162）：**默认页全选且没开能力页 ⇒ null**（未收窄，存量形态）；
   * 其余情况 ⇒ 逐键列表（默认页的收窄 + 逐人开放的能力页并成一份）。
   */
  const pagesPayload = (pages: string[] | null, optional: string[]): string[] | null => {
    const base = pages === null ? defaultPageKeys : pages
    const selected = [...base, ...optional]
    const sameAsDefault = optional.length === 0
      && selected.length === defaultPageKeys.length
      && defaultPageKeys.every((key) => selected.includes(key))
    return sameAsDefault ? null : selected
  }

  /** 逐人开/关一个**非默认能力页**（issue #7162：质检）。全选默认页且没开 ⇒ 回 null（未收窄）。 */
  const handleToggleOptional = async (record: WorkerProfile, key: string) => {
    if (togglingOptional !== null) return
    setTogglingOptional(record.id)
    try {
      const current = record.workerPages?.length ? record.workerPages : defaultPageKeys
      const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key]
      const sameAsDefault = next.length === defaultPageKeys.length
        && defaultPageKeys.every((k) => next.includes(k))
      await workerApi.updateWorkerPages(record.id, sameAsDefault ? null : next)
      toast.success(record.workerPages?.includes(key) ? '已关闭该能力' : '已开放该能力')
      loadWorkers()
    } catch (e) {
      toastRequestError(e, '设置工人端菜单失败')
    } finally {
      setTogglingOptional(null)
    }
  }

  /**
   * 打开「设置工人端菜单」（issue #7804）：初值 = **该档案当前值**（不是建号那套默认全勾）。
   *
   * 🔴 `null` 与空数组都读作「未收窄」—— 与读面 fail-open（`WorkerPages.effectiveFor` 对归一后
   * 空集回落全部页面）和列表列 `menuSummary` 同口径；否则脏数据会让商家看到「一页都没勾」而
   * 工人实际看到全部页面。
   */
  const handleOpenPages = (record: WorkerProfile) => {
    const assigned = record.workerPages
    setPagesTarget(record)
    setPagesDraft(assigned == null || assigned.length === 0
      ? { pages: null, optional: [] }
      : {
          pages: menuPages.filter((p) => assigned.includes(p.key)).map((p) => p.key),
          optional: optionalPages.filter((p) => assigned.includes(p.key)).map((p) => p.key),
        })
  }

  /**
   * 保存整集页面收窄：空集**就地拦住**（后端也会 422，但「至少留一页」是产品口径，页面先告知）。
   * 全勾默认页且没开能力页 ⇒ 发 `null`（未收窄，与建号同一条 `pagesPayload`）。
   */
  const handleSavePages = async () => {
    if (!pagesTarget) return
    if (pagesDraft.pages !== null && pagesDraft.pages.length === 0) {
      toast.error('至少要留一个页面；要让这位工人不干活，请用「停用」')
      return
    }

    setSavingPages(true)
    try {
      await workerApi.updateWorkerPages(pagesTarget.id, pagesPayload(pagesDraft.pages, pagesDraft.optional))
      toast.success('工人端菜单已更新')
      setPagesTarget(null)
      loadWorkers()
    } catch (e) {
      toastRequestError(e, '设置工人端菜单失败')
    } finally {
      setSavingPages(false)
    }
  }

  /** 建号：工号（租户内唯一）+ 姓名 + PIN + 工人端菜单。冲突由服务端 409 明确拒绝，页面**不**替它改写文案。 */
  const handleCreate = async () => {
    if (!form.workerNo.trim()) { toast.error('请输入工号'); return }
    if (!form.name.trim()) { toast.error('请输入工人姓名'); return }
    // 与后端同一条形态判据：工人端 PIN 输入框是数字键盘（inputmode=numeric）⇒ 含字母的 PIN 打不出来
    if (!/^\d{4,12}$/.test(form.pin.trim())) { toast.error('PIN 必须是 4~12 位数字'); return }
    // 与后端同一条写入判据（422 是兜底，不是第一次告知）：空集在工人端会被读成「没读到权限 ⇒ 全开」
    if (form.pages !== null && form.pages.length === 0) {
      toast.error('至少要留一个页面；要让这位工人不干活，请用「停用」')
      return
    }

    setCreating(true)
    try {
      await workerApi.createWorker({
        workerNo: form.workerNo.trim(),
        name: form.name.trim(),
        pin: form.pin.trim(),
        // null（未收窄）或全勾 ⇒ 发 null = 不限制；只勾了一部分 ⇒ 发那一部分
        workerPages: pagesPayload(form.pages, form.optional),
        // 绑定工序（issue #7749）：空 = 不绑定（扫码后自己选工序的旧行为）
        workerOperation: form.workerOperation.trim() || null,
      })
      toast.success('工人档案已创建，请把工号与 PIN 告知本人')
      setFormOpen(false)
      setForm({ workerNo: '', name: '', pin: '', workerOperation: '', pages: null, optional: [] })
      loadWorkers()
    } catch (e) {
      // 失败**不关弹窗**：工号冲突是可修正的错误；文案由拦截器统一展示服务端原文（UI-024 去重口径）
      toastRequestError(e, '创建工人档案失败')
    } finally {
      setCreating(false)
    }
  }

  const handleToggleStatus = async (worker: WorkerProfile) => {
    if (togglingId !== null) return
    const newStatus: EmployeeStatus = worker.status === 'active' ? 'disabled' : 'active'
    setTogglingId(worker.id)
    try {
      await workerApi.setWorkerStatus(worker.id, newStatus)
      toast.success(newStatus === 'active' ? '已启用' : '已停用（该工人不能再登录工人端）')
      loadWorkers()
    } catch (e) {
      toastRequestError(e, '操作失败')
    } finally {
      setTogglingId(null)
    }
  }

  /** 打开「改工序」弹窗（issue #7749）：[[opValue]] 初值 = 当前绑定（'' = 不设工序）。 */
  const handleOpenOperation = (worker: WorkerProfile) => {
    setOpTarget(worker)
    setOpValue(worker.workerOperation ?? '')
  }

  /** 保存绑定：空 ⇒ 清空（= 回到扫码后自己选工序）。非法工序名由服务端 422 原样展示。 */
  const handleSaveOperation = async () => {
    if (!opTarget) return
    setSavingOp(true)
    try {
      await workerApi.updateWorkerOperation(opTarget.id, opValue.trim() || null)
      toast.success(opValue.trim() ? `已绑定工序：${opValue.trim()}` : '已改为不绑定（扫码后自己选工序）')
      setOpTarget(null)
      loadWorkers()
    } catch (e) {
      toastRequestError(e, '设置工人工序失败')
    } finally {
      setSavingOp(false)
    }
  }

  /**
   * 重置 PIN（issue #6432）：原 PIN 是 BCrypt 哈希、**读不出来** ⇒ 唯一出口 = 设新值并当场展示。
   * pin 留空 ⇒ 交给服务端随机生成 6 位（页面不自己造一套 PIN 规则，形态校验仍以服务端为准）。
   */
  const handleOpenResetPin = (worker: WorkerProfile) => {
    setPinTarget(worker)
    setPinInput('')
    setNewPin(null)
  }

  const handleResetPin = async () => {
    if (!pinTarget) return
    const pin = pinInput.trim()
    if (pin && !/^\d{4,12}$/.test(pin)) { toast.error('PIN 必须是 4~12 位数字'); return }

    setResettingPin(true)
    try {
      const res = await workerApi.resetWorkerPin(pinTarget.id, pin || undefined)
      setNewPin(res.data.data?.pin ?? '')
    } catch (e) {
      // 失败**不关弹窗**、不展示任何 PIN：管理员可改值重试（文案由拦截器统一展示服务端原文，UI-024）
      toastRequestError(e, '重置 PIN 失败')
    } finally {
      setResettingPin(false)
    }
  }

  const columns: TableColumn<WorkerProfile>[] = [
    {
      key: 'workerNo',
      title: '工号',
      width: '140px',
      render: (record) => (
        <span className="font-medium text-neutral-900">{record.workerNo}</span>
      ),
    },
    { key: 'name', title: '姓名', width: '120px', dataIndex: 'name' },
    {
      key: 'workerOperation',
      title: '工序',
      width: '140px',
      render: (record) => (
        record.workerOperation
          ? <span className="text-sm text-neutral-800" data-testid={`worker-operation-${record.id}`}>{record.workerOperation}</span>
          : <span className="text-sm text-neutral-500" data-testid={`worker-operation-${record.id}`} title="出入库/仓库等岗位本来就没有工序">不设工序</span>
      ),
    },
    {
      key: 'workerPages',
      title: '工人端菜单',
      render: (record) => {
        const summary = menuSummary(record)
        if (summary === null) {
          // 未设收窄 = 默认页面（不是「全部能力」：质检页逐人开，issue #7162）
          return <span className="text-sm text-neutral-500" data-testid={`worker-menu-${record.id}`}>默认页面</span>
        }
        return (
          <span className="text-sm text-neutral-700" data-testid={`worker-menu-${record.id}`}>
            {summary}
          </span>
        )
      },
    },
    {
      key: 'status',
      title: '状态',
      width: '100px',
      render: (record) => (
        <Badge variant={record.status === 'active' ? 'success' : 'info'}>
          {record.status === 'active' ? '启用' : '停用'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      title: '操作',
      // 改菜单 / 开质检 / 改工序 / 重置 PIN / 停用 —— 五个文本动作单行不折（issue #7217 的 nowrap 口径）
      width: '320px',
      render: (record) => (
        <div className="flex items-center gap-3 whitespace-nowrap">
          {/* 改菜单（issue #7804）：目录读不到 ⇒ 没有选项可勾 ⇒ 入口不出现（同建号「菜单一节不显示」） */}
          {menuPages.length > 0 && (
            <button
              type="button"
              onClick={() => handleOpenPages(record)}
              disabled={!canWrite}
              data-testid={`worker-set-pages-${record.id}`}
              className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm disabled:text-neutral-400 disabled:no-underline disabled:cursor-not-allowed"
            >
              改菜单
            </button>
          )}
          {optionalPages.map((page) => (
            <button
              key={page.key}
              type="button"
              onClick={() => void handleToggleOptional(record, page.key)}
              disabled={!canWrite || togglingOptional === record.id}
              data-testid={`worker-optional-${page.key}-${record.id}`}
              className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm disabled:text-neutral-400 disabled:no-underline disabled:cursor-not-allowed"
            >
              {record.workerPages?.includes(page.key) ? `关${page.label}` : `开${page.label}`}
            </button>
          ))}
          <button
            type="button"
            onClick={() => handleOpenOperation(record)}
            disabled={!canWrite}
            data-testid={`worker-set-operation-${record.id}`}
            className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm disabled:text-neutral-400 disabled:no-underline disabled:cursor-not-allowed"
          >
            改工序
          </button>
          <button
            type="button"
            onClick={() => handleOpenResetPin(record)}
            disabled={!canWrite}
            className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm disabled:text-neutral-400 disabled:no-underline disabled:cursor-not-allowed"
          >
            重置 PIN
          </button>
          <button
            type="button"
            onClick={() => handleToggleStatus(record)}
            disabled={!canWrite || togglingId === record.id}
            className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm disabled:text-neutral-400 disabled:no-underline disabled:cursor-not-allowed"
          >
            {record.status === 'active' ? '停用' : '启用'}
          </button>
        </div>
      ),
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-neutral-500">
          工人用工号 + PIN 登录工人端扫码报工，不进入管理后台；绑定工序后扫码直接报那一道，不用再选。
          出入库 / 仓库岗位不需要工序，不设即可（用工人端的入库 / 出库功能）。
        </p>
        {canWrite ? (
          <Button onClick={handleOpenCreate}>
            <Plus className="w-4 h-4 mr-1.5" />
            新建工人档案
          </Button>
        ) : (
          <span className="text-xs text-neutral-400">只读</span>
        )}
      </div>

      <div className="bg-neutral-50 p-4 rounded-lg mb-4" data-testid="worker-search-area">
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[200px]">
            <Input
              label="工号/姓名"
              placeholder="输入工号或姓名搜索"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="min-w-[140px]">
            <Select
              label="状态"
              options={[
                { value: '', label: '全部状态' },
                { value: 'active', label: '启用' },
                { value: 'disabled', label: '停用' },
              ]}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as EmployeeStatus | '')}
            />
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <Button variant="secondary" size="sm" onClick={handleReset}>
              重置
            </Button>
            <Button size="sm" onClick={handleSearch}>
              <Search className="w-4 h-4 mr-1.5" />
              查询
            </Button>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-neutral-200 shadow-card">
        <Table<WorkerProfile>
          columns={columns}
          dataSource={workers}
          loading={loading}
          rowKey="id"
          emptyText="还没有工人档案：点右上角「新建工人档案」录入工号与 PIN 即可"
        />
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title="新建工人档案"
        width={520}
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)} disabled={creating}>
              取消
            </Button>
            <Button onClick={handleCreate} loading={creating}>
              创建
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="工号 *"
            placeholder="工人工牌上的工号，如 W-1002"
            value={form.workerNo}
            onChange={(e) => setForm({ ...form, workerNo: e.target.value })}
          />
          <Input
            label="姓名 *"
            placeholder="工人姓名，如 李四"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Input
            label="PIN *"
            type="password"
            inputMode="numeric"
            placeholder="4~12 位数字，工人登录工人端时输入"
            value={form.pin}
            onChange={(e) => setForm({ ...form, pin: e.target.value })}
          />
          <p className="text-xs text-neutral-400">
            工号在您的企业内不能重复；PIN 请当面告知工人（工人端用「工号 + PIN」登录扫工牌报工）。
            工人不会进入管理后台，也拿不到任何菜单权限。
          </p>

          {/* 绑定工序（issue #7749）：一个工人对应一道工序；不绑 = 扫码后自己选（旧行为） */}
          <div className="pt-3 border-t border-neutral-100" data-testid="worker-operation-picker">
            <Select
              label="工序"
              options={[
                { value: '', label: '不设工序（出入库/仓库等岗位）' },
                ...operationOptions.map((op) => ({ value: op.name, label: `${op.name}（${op.group}）` })),
              ]}
              value={form.workerOperation}
              onChange={(e) => setForm({ ...form, workerOperation: e.target.value })}
            />
            <p className="text-xs text-neutral-400 mt-1.5">
              {operationOptions.length === 0
                ? '工序库还没有可用工序 —— 先到「企业基础设置 → 工序与部位单价」建立工序，再回来绑定（出入库/仓库岗位不需要工序，可不设）。'
                : '生产工人：绑定一道工序，扫码直接报工（屏上不再选工序；同一道活按布帘/纱帘拆的多行已合并）。出入库/仓库等岗位：不设工序即可，他们用工人端的入库/出库功能，不参与报工。'}
            </p>
          </div>

          {menuPages.length > 0 && (
            <div className="pt-3 border-t border-neutral-100" data-testid="worker-pages-picker">
              <WorkerPagesPicker
                menuPages={menuPages}
                optionalPages={optionalPages}
                value={form}
                onChange={(next) => setForm({ ...form, ...next })}
              />
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={opTarget !== null}
        onClose={() => setOpTarget(null)}
        title="设置工人工序"
        width={520}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpTarget(null)} disabled={savingOp}>
              取消
            </Button>
            <Button onClick={handleSaveOperation} loading={savingOp}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-4" data-testid="worker-operation-modal">
          <p className="text-sm text-neutral-600">
            工人：
            <span className="font-medium text-neutral-900">
              {opTarget?.workerNo} {opTarget?.name}
            </span>
          </p>
          <Select
            label="工序"
            options={[
              { value: '', label: '不设工序（出入库/仓库等岗位）' },
              ...operationOptions.map((op) => ({ value: op.name, label: `${op.name}（${op.group}）` })),
            ]}
            value={opValue}
            onChange={(e) => setOpValue(e.target.value)}
          />
          <p className="text-xs text-neutral-400">
            生产工人：绑定后扫码自动选中这道工序、直接报工。出入库/仓库等岗位：选「不设工序」即可
            （他们用入库/出库功能，不参与报工）。本件没有这道 / 已做完时，工人屏会如实说明，不会改报别的工序。
          </p>
        </div>
      </Modal>

      {/* 改菜单（issue #7804）：存量工人整集编辑 —— 与建号弹窗**同一份**勾选区 */}
      <Modal
        open={pagesTarget !== null}
        onClose={() => setPagesTarget(null)}
        title="设置工人端菜单"
        width={520}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPagesTarget(null)} disabled={savingPages}>
              取消
            </Button>
            <Button onClick={handleSavePages} loading={savingPages}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-4" data-testid="worker-pages-modal">
          <p className="text-sm text-neutral-600">
            工人：
            <span className="font-medium text-neutral-900">
              {pagesTarget?.workerNo} {pagesTarget?.name}
            </span>
          </p>
          {menuPages.length > 0 && (
            <div className="pt-3 border-t border-neutral-100">
              <WorkerPagesPicker
                menuPages={menuPages}
                optionalPages={optionalPages}
                value={pagesDraft}
                onChange={setPagesDraft}
              />
            </div>
          )}
          <p className="text-xs text-neutral-400">
            保存后立即生效（工人下次进工人端即按新菜单显示）。工人端菜单只决定入口显隐，不是后台权限。
          </p>
        </div>
      </Modal>

      <Modal
        open={pinTarget !== null}
        onClose={() => setPinTarget(null)}
        title={newPin === null ? '重置工人 PIN' : '新 PIN（只显示这一次）'}
        width={520}
        footer={
          newPin === null ? (
            <>
              <Button variant="secondary" onClick={() => setPinTarget(null)} disabled={resettingPin}>
                取消
              </Button>
              <Button onClick={handleResetPin} loading={resettingPin}>
                确认重置
              </Button>
            </>
          ) : (
            <Button onClick={() => setPinTarget(null)}>完成</Button>
          )
        }
      >
        {newPin === null ? (
          <div className="space-y-4">
            <p className="text-sm text-neutral-600">
              工人：
              <span className="font-medium text-neutral-900">
                {pinTarget?.workerNo} {pinTarget?.name}
              </span>
            </p>
            <Input
              label="新 PIN"
              inputMode="numeric"
              placeholder="4~12 位数字；留空则由系统随机生成 6 位"
              value={pinInput}
              onChange={(e) => setPinInput(e.target.value)}
            />
            <p className="text-xs text-neutral-400">
              系统只保存不可逆的加密结果，原 PIN 无法查看 ⇒ 工人忘记时只能重置为新值。
              重置后旧 PIN 立即失效，请当面告知本人。
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="bg-neutral-50 rounded-lg p-4 text-center" data-testid="worker-new-pin">
              <div className="text-xs text-neutral-500 mb-1">新 PIN</div>
              <div className="text-2xl font-semibold tracking-[0.3em] text-neutral-900">{newPin}</div>
            </div>
            <p className="text-xs text-neutral-500">
              关掉本窗口后就查不到了 —— 请立刻告知工人，让他用工号 + 这个 PIN 在工人端登录一次确认可用。
            </p>
          </div>
        )}
      </Modal>
    </div>
  )
}
