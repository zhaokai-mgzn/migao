'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Search, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { employeeApi } from '@/lib/api'
import request from '@/lib/request'
import { usePermission } from '@/lib/permission'
import { Button, Input, Select, Modal, Table, Pagination, Badge, PageHeader, PageCard, SearchPanel, SELECT_CONTROL, RowActions, RowActionLink } from '@/components/ui'
import type { TableColumn, SearchFieldSpec } from '@/components/ui'
import type { Employee, EmployeeStatus, EmployeeFormData } from '@/types'
import { TreeCheckbox, type TreeNode } from '@/components/ui/TreeCheckbox'
import DateTimeCell from '@/components/common/DateTimeCell'
import WorkerProfilesPanel from '@/components/employees/WorkerProfilesPanel'
import { mobileTitlesByCodeFromTree } from '@/lib/mobile-surface-label'
import { cn } from '@/lib/utils'

// #2969 岗位=角色体系：岗位列表来自 roleApi.getAllRoles（每岗位含默认权限），不再用硬编码预设
/** 筛选控件统一形态：与 `SearchPanel` 的 `CONTROL_CLASS` 同口径 */
const SEARCH_CONTROL =
  'w-full h-9 px-3 rounded border border-neutral-300 bg-white text-sm text-neutral-900 ' +
  'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ' +
  'placeholder:text-neutral-400'

export default function EmployeesPage() {
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('employee:create') // 新增/编辑/删除/禁用均需 employee:create

  // 列表状态
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<EmployeeStatus | ''>('')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [searchStatus, setSearchStatus] = useState<EmployeeStatus | ''>('')

  // 菜单权限树
  const [menuTree, setMenuTree] = useState<TreeNode[]>([])

  // 岗位下拉数据源（岗位=角色体系 #2969，role.permissions 即岗位默认权限）
  const [positionOptions, setPositionOptions] = useState<{ name: string; code: string; permissionCodes: string[] }[]>([])
  /**
   * 岗位清单**读失败**的显式状态（issue #6663）。
   * 为什么必须有它：岗位用 `Select`（**不能手输**）⇒ 读失败时下拉空着 ⇒ **建不出员工**，
   * 而改前这里是**空 catch**（注释还写着「岗位为空时可手输」—— 与事实相反）。
   */
  const [positionsError, setPositionsError] = useState('')

  // 新增/编辑对话框
  const [formOpen, setFormOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    phone: '',
    position: '',
    role: '',
    permissions: [] as string[],
    // #5485：员工登录账号（用户名 + 初始密码）。用户名租户内唯一，重名由服务端 422。
    username: '',
    password: '',
  })

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null)
  const [deleting, setDeleting] = useState(false)

  // 重置密码（#5485：管理员重置 = 员工忘记密码时的找回路径；重置后强制改密）
  const [resetTarget, setResetTarget] = useState<Employee | null>(null)
  const [resetPasswordValue, setResetPasswordValue] = useState('')
  const [resetting, setResetting] = useState(false)

  // 内联状态切换 loading（按 ID 防止双击）
  const [togglingId, setTogglingId] = useState<number | null>(null)

  // 员工 / 工人档案分两个面（issue #4869）：工人复用 users 表但**不是**员工
  //（零菜单权限、无登录用户名、只能用工号 + PIN 进工人端扫码报工）⇒ 混在同一张表里会
  //「看起来像员工」（点编辑还能改岗位/权限，而那条路对工人根本不成立）。
  const [activeTab, setActiveTab] = useState<'employee' | 'worker'>('employee')

  // 加载菜单权限树
  useEffect(() => {
    request.get('/api/admin/menus').then((res: any) => {
      const data = res.data?.data || res.data || []
      setMenuTree(Array.isArray(data) ? data : [])
    }).catch(() => {
      toast.error('加载菜单权限失败，请刷新重试')
    })
  }, [])

  // 加载岗位列表（#2969：岗位=角色体系，岗位默认权限 = role.permissions 的 code 列表）
  // ⚠️ 抽成 useCallback 是为了给失败态一个**重试出口**（`employees-positions-retry`）—— 见下面渲染面
  const loadPositions = useCallback(async () => {
    try {
      const res: any = await employeeApi.loadPositions()
      const data = Array.isArray(res?.data?.data) ? res.data.data : (Array.isArray(res?.data) ? res.data : [])
      setPositionOptions((data as any[]).map((r: any) => ({
        name: r.name || r.code,
        code: r.code,
        permissionCodes: (r.permissions || []).map((p: any) => p.code).filter(Boolean),
      })))
      setPositionsError('')
    } catch (e) {
      // 🔴 issue #6663：改前这里是**空 catch**，注释说「岗位为空时可手输」—— 而现实相反：
      // 岗位用的是 `Select`（**不能手输**）⇒ 岗位选项空 ⇒ **建不出员工**，且页面一言不发。
      // 读失败必须说出来 + 给重试出口（范式：dashboard/page.tsx 的失败/空态分离）。
      setPositionsError('岗位清单读取失败 —— 可能是网络或服务暂时不可用')
      toastRequestError(e, '岗位清单读取失败，请稍后重试')
    }
  }, [])

  useEffect(() => {
    void loadPositions()
  }, [loadPositions])

  // 从 menuTree 中提取 code → 中文 label 的映射 + 叶子节点总数
  //
  // 🔴 2026-10-18（用户截图：「权限」列出现英文权限码）：改前**只扫 children**，
  // 而「经营看板」自 issue #7087 起是**顶层独立项**（`MenuController` 顶层直接构造的菜单节点）
  // ⇒ 这类码没有中文名，权限列回退成内部码上屏（§31 P3「不摆内部标识」）。
  // ⚠️ 本条注释**不写出那个码**：它是 `AdminGate.ADMIN_PERMISSION_CODES` 的成员，而该集合要求
  //    前端**任一文件至多出现 1 个成员**（`tests/unit_ci_workflows/test_mibao_chat_gate.py` 判据 ②）
  //    —— 本页已有 `employee:create` 这类码，再写一个就红。
  // 顶层独立项与组内项一样是**可勾选的叶子**（`TreeCheckbox` 对无 children 的节点取自身 code），
  // 所以它们同时进 labelMap 与叶子计数 —— 两处口径必须同源，否则「全部权限」徽章会算错。
  const { permissionLabelMap, totalLeafCount } = useMemo(() => {
    const map: Record<string, string> = {}
    let count = 0
    // 同码多节点按设计存在（#5699/#5291）：labelMap 首见优先，不被后到同码节点覆盖（issue #6083）
    const take = (code: string, label: string) => { if (!(code in map)) map[code] = label }
    menuTree.forEach(p => {
      const children = p.children || []
      if (children.length === 0) {
        take(p.code, p.label)
        count++
        return
      }
      children.forEach(c => { take(c.code, c.label); count++ })
    })
    return { permissionLabelMap: map, totalLeafCount: count }
  }, [menuTree])

  /**
   * 岗位展示名（2026-10-18 用户逐字：「这里的岗位不要用英文」）。
   *
   * `users.position` 有两种历史写法：**岗位名**（员工管理页建号，如「客服」）与**角色码**
   * （API / 回归脚本建号，如 `knowledge_editor`）。后者原样上屏 = 把内部标识摆给商家看（§31 P3）。
   * 角色码 → 岗位名的真值**只在服务端**：优先用该行下发的 `roles`（`{ code, name }`，`user_roles` 的投影），
   * 其次用页面已加载的岗位清单（`/api/admin/roles/all`）；前端**不另建**「码 → 岗位名」字典。
   */
  const positionLabelOf = (record: Employee): string => {
    const raw = (record.position || '').trim()
    if (!raw) return ''
    const role = (record.roles || []).find(r => r.code === raw || r.name === raw)
    if (role?.name) return role.name
    return positionOptions.find(p => p.code === raw || p.name === raw)?.name || raw
  }

  /**
   * 手机端菜单（2026-10-18 用户逐字：「员工管理里面不能设置手机端的菜单权限？」）。
   *
   * 手机端可见面由**同一批权限码**派生（issue #6570「走 B」/ #6574 / #6759）—— 服务端在
   * `GET /api/admin/menus` 的节点上把「权限码 → 手机端面中文名」标注下发，这里只**收表**，
   * 不自建映射（判据 = `tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py`）。
   * 🔴 必须扫**整棵树**（含顶层独立项）：「经营看板」（手机端底栏「数据」）就挂在顶层。
   */
  const mobileMenuEntries = useMemo(
    () => Object.entries(mobileTitlesByCodeFromTree(menuTree)),
    [menuTree],
  )

  /** 列表读失败（与「暂无数据」互斥，issue #6714）：故障不是业务事实 */
  const [loadFailed, setLoadFailed] = useState(false)

  // 加载员工列表
  const loadEmployees = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
        keyword: searchKeyword || undefined,
        status: searchStatus || undefined,
      }

      const res = await employeeApi.getEmployees(params as Parameters<typeof employeeApi.getEmployees>[0])
      const data = res.data.data
      setEmployees(data?.items || [])
      setTotal(data?.total || 0)
      setLoadFailed(false)
    } catch (e) {
      // 读面失败**不清零**（保留上次成功值）、只标失败态 —— 故障 ≠「没有员工」（issue #6714）
      setLoadFailed(true)
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchKeyword, searchStatus])

  useEffect(() => {
    loadEmployees()
  }, [loadEmployees])

  // 搜索
  const handleSearch = () => {
    setCurrent(1)
    setSearchKeyword(keyword)
    setSearchStatus(statusFilter)
  }

  // 重置
  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setCurrent(1)
    setSearchKeyword('')
    setSearchStatus('')
  }

  // 打开新增对话框
  const handleAdd = () => {
    setEditingEmployee(null)
    setFormData({ name: '', phone: '', position: '', role: '', permissions: [], username: '', password: '' })
    setFormOpen(true)
  }

  // #2969 选岗位自动带出该岗位默认权限（仍可手动增删自定义）；切换岗位则重置为新岗位默认
  // 岗位=角色体系：前端仍不传 role（#2907 去角色化契约），后端按岗位名解析角色并关联 user_roles
  const handlePositionChange = (name: string) => {
    const pos = positionOptions.find(p => p.name === name || p.code === name)
    const defaultPerms = pos ? [...pos.permissionCodes] : []
    // 编辑时仅当岗位变更才重置权限树（用户已确认：改岗位则重置为新岗位默认）
    setFormData(prev => ({
      ...prev,
      position: name,
      role: '',
      permissions: defaultPerms,
    }))
  }

  // 打开编辑对话框
  const handleEdit = (employee: Employee) => {
    setEditingEmployee(employee)
    setFormData({
      name: employee.name,
      phone: employee.phone || '',
      // 岗位回填用**展示名**：存量行存的是角色码时，直接回填码会让「岗位」下拉匹配不到任何选项
      position: positionLabelOf(employee),
      role: employee.role || (employee.roles?.[0]?.code as string) || '',
      permissions: employee.permissions || [],
      // #5485：登录账号取 employeeUsername（⚠️ `username` 在列表里仍是手机号，不能拿来当账号）
      username: employee.employeeUsername || '',
      // 密码不回显（后端也不下发）；留空 = 不改密码
      password: '',
    })
    setFormOpen(true)
  }

  // 提交表单
  const handleSubmit = async () => {
    if (!formData.name.trim()) { toast.error('请输入姓名'); return }
    if (!formData.phone.trim()) { toast.error('请输入手机号'); return }
    // #5485：新建必须同时给「用户名 + 初始密码」—— 没有账号的员工**根本登不进来**
    // （存量账号不自动迁移，管理员补设前无法登录是预期行为；新员工别制造下一个这样的账号）
    if (!editingEmployee) {
      if (!formData.username.trim()) { toast.error('请设置登录用户名'); return }
      if (!formData.password) { toast.error('请设置初始密码'); return }
    }
    if (!formData.position.trim()) { toast.error('请选择岗位'); return }

    // 「角色」字段已从表单移除（#2907）：新建时不传 role，由后端按岗位解析（#2969 岗位=角色体系）；
    // 账号权限由下方权限树直接分配（快照式：保存勾选=员工权限）。编辑时回传员工原角色码，避免角色被重置。
    const payload: EmployeeFormData = {
      name: formData.name,
      phone: formData.phone,
      position: formData.position,
      permissions: formData.permissions,
    }
    if (formData.role) payload.role = formData.role
    // 编辑时留空 = 不改（用户名留空不发送，避免把已有账号清掉）
    const username = formData.username.trim()
    if (username) payload.username = username
    if (formData.password) payload.password = formData.password

    setFormLoading(true)
    try {
      if (editingEmployee) {
        await employeeApi.updateEmployee(editingEmployee.id, payload)
        toast.success('编辑成功')
      } else {
        await employeeApi.createEmployee(payload)
        toast.success('创建成功，该员工首次登录需修改密码')
      }
      setFormOpen(false)
      loadEmployees()
    } catch (e) {
      // Error handled by API layer（用户名租户内重复 → 服务端 422，message 已由拦截器提示）
    } finally {
      setFormLoading(false)
    }
  }

  // 重置密码（#5485）：重置后该员工下次登录**必须先改密**（后端强制置标记）
  const handleResetPassword = async () => {
    if (!resetTarget) return
    if (!resetPasswordValue) { toast.error('请输入新的初始密码'); return }
    setResetting(true)
    try {
      await employeeApi.resetPassword(resetTarget.id, { newPassword: resetPasswordValue })
      toast.success('密码已重置，请告知员工：下次登录需先修改密码')
      setResetTarget(null)
      setResetPasswordValue('')
      loadEmployees()
    } catch (e) {
      // Error handled by API layer（弱密码 → 422，服务端 message 可直接展示）
    } finally {
      setResetting(false)
    }
  }

  // 删除
  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await employeeApi.deleteEmployee(deleteTarget.id)
      toast.success('删除成功')
      setDeleteTarget(null)
      loadEmployees()
    } catch (e) {
      // Error handled by API layer
    } finally {
      setDeleting(false)
    }
  }

  // 内联状态切换（直接调 API，无弹窗）
  const handleToggleStatus = async (employee: Employee) => {
    if (togglingId !== null) return // 防止双击
    const newStatus: EmployeeStatus = employee.status === 'active' ? 'disabled' : 'active'
    const actionLabel = newStatus === 'active' ? '启用' : '禁用'
    setTogglingId(employee.id)
    try {
      await employeeApi.toggleEmployeeStatus(employee.id, newStatus)
      toast.success(`已${actionLabel}`)
      loadEmployees()
    } catch (e) {
      toast.error(`操作失败`)
    } finally {
      setTogglingId(null)
    }
  }

  // 表格列定义
  const columns: TableColumn<Employee>[] = [
    {
      key: 'index',
      title: '序号',
      width: '70px',
      render: (_record, index) => (
        <span className="text-neutral-500">{(current - 1) * pageSize + index + 1}</span>
      ),
    },
    {
      key: 'name',
      title: '姓名',
      width: '140px',
      render: (record) => (
        <button
          onClick={() => canWrite && handleEdit(record)}
          disabled={!canWrite}
          className="text-primary-600 hover:text-primary-700 hover:underline text-sm font-medium disabled:cursor-default"
        >
          {record.name}
        </button>
      ),
    },
    { key: 'phone', title: '手机号', dataIndex: 'phone', width: '140px' },
    {
      // #5485：登录账号。⚠️ 列表里 `username` **仍是手机号**（后端未动），
      // 登录用的用户名是 `employeeUsername` —— 显示错了等于让管理员对着手机号去猜账号。
      key: 'employeeUsername',
      title: '登录账号',
      width: '150px',
      render: (record) => (
        record.employeeUsername
          ? <span className="text-sm text-neutral-700">{record.employeeUsername}</span>
          : <span className="text-neutral-400 text-sm">未设置</span>
      ),
    },
    {
      key: 'position',
      title: '岗位',
      width: '100px',
      render: (record) => (
        <span className="text-sm text-neutral-700">{positionLabelOf(record) || '-'}</span>
      ),
    },
    {
      key: 'permissions',
      title: '权限',
      width: '200px',
      render: (record) => {
        const codes: string[] = record.permissions || []
        if (codes.length === 0) return <span className="text-neutral-400 text-sm">未分配</span>
        // 拥有全部权限时折叠为单个标签
        if (totalLeafCount > 0 && codes.length >= totalLeafCount) {
          return <Badge variant="success">全部权限</Badge>
        }
        const labels = codes.map(c => permissionLabelMap[c] || c).slice(0, 3)
        return (
          <div className="flex flex-wrap gap-1">
            {labels.map((l, i) => <Badge key={i} variant="info">{l}</Badge>)}
            {codes.length > 3 && <span className="text-xs text-neutral-400">+{codes.length - 3}</span>}
          </div>
        )
      },
    },
    {
      key: 'status',
      title: '状态',
      width: '90px',
      render: (record) => {
        const isToggling = togglingId === record.id
        return (
        <button
          type="button"
          onClick={() => canWrite && handleToggleStatus(record)}
          disabled={!canWrite || isToggling}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed ${
            record.status === 'active' ? 'bg-primary-600' : 'bg-neutral-300'
          }`}
          title={!canWrite ? '无权限' : isToggling ? '处理中...' : record.status === 'active' ? '点击禁用' : '点击启用'}
        >
          <span
            className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
              record.status === 'active' ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
        )
      },
    },
    {
      key: 'createdAt',
      title: '创建时间',
      width: '180px',
      render: (record) => <DateTimeCell value={record.createdAt} />,
    },
    {
      key: 'actions',
      title: '操作',
      width: '140px',
      render: (record) =>
        canWrite ? (
          // 行内动作的唯一形态（#8039）：主行动「编辑」+ ⋯ 收「重置密码 / 删除」。
          // 危险动作仍走页内既有确认弹窗（`deleteTarget` / `resetTarget`），本组件不弹确认。
          <RowActions
            testId={`employee-actions-${record.id}`}
            menuTestId={`employee-row-menu-${record.id}`}
            items={[
              {
                key: 'reset-password',
                label: '重置密码',
                testId: `employee-reset-password-${record.id}`,
                onClick: () => {
                  setResetTarget(record)
                  setResetPasswordValue('')
                },
              },
              {
                key: 'delete',
                label: '删除',
                danger: true,
                testId: `employee-delete-${record.id}`,
                onClick: () => setDeleteTarget(record),
              },
            ]}
          >
            <RowActionLink data-testid={`employee-edit-${record.id}`} onClick={() => handleEdit(record)}>
              编辑
            </RowActionLink>
          </RowActions>
        ) : (
          <span className="text-xs text-neutral-400">只读</span>
        ),
    },
  ]

  const searchPanelFields: SearchFieldSpec[] = [
    {
      key: 'keyword',
      label: '姓名/手机号',
      control: (
        <input
          type="text"
          placeholder="输入姓名或手机号搜索"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          className={SEARCH_CONTROL}
        />
      ),
    },
    {
      key: 'status',
      label: '状态',
      control: (
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as EmployeeStatus | '')}
          className={cn(SELECT_CONTROL, 'w-full')}
        >
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="disabled">禁用</option>
        </select>
      ),
    },
  ]


  return (
    <div className="p-6 space-y-4">
      {/* 页面标题 */}
      <PageHeader
        title="员工管理"
        subtitle="管理系统用户和员工账号"
        actions={activeTab === 'employee' && (canWrite ? (
          <Button onClick={handleAdd}>
            <Plus className="w-4 h-4 mr-1.5" />
            新增员工
          </Button>
        ) : (
          <span className="text-xs text-neutral-400">仅拥有 employee:create 权限的员工可管理账号</span>
        ))}
      />

      {/* 两个面分开（issue #4869）：工人不是员工 —— 各有各的列表与入口 */}
      <PageCard padded={false}>
      <div className="flex items-center gap-1 border-b border-neutral-200 px-2">
        <button
          type="button"
          onClick={() => setActiveTab('employee')}
          className={`px-4 py-2 -mb-px text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'employee'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-neutral-500 hover:text-neutral-700'
          }`}
        >
          员工
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('worker')}
          className={`px-4 py-2 -mb-px text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'worker'
              ? 'border-primary-600 text-primary-600'
              : 'border-transparent text-neutral-500 hover:text-neutral-700'
          }`}
        >
          工人档案
        </button>
      </div>
      </PageCard>

      {activeTab === 'worker' ? (
        <PageCard>
          <WorkerProfilesPanel canWrite={canWrite} />
        </PageCard>
      ) : (
      <div className="space-y-4">
      {/* 搜索筛选栏 */}
      <SearchPanel
        fields={searchPanelFields}
        onSearch={handleSearch}
        onReset={handleReset}
        loading={loading}
      />

      {/* 🔴 issue #6714：读失败 ⇒ 常驻失败面 + 真重发（与表格的「暂无数据」**互斥**）。
          修前失败只 toast（≈4s 消失），屏上留着「暂无数据」+「共 0 条」两处事实性断言。 */}
      {!loading && loadFailed && (
        <div
          data-testid="employees-load-failed"
          role="alert"
          className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 mb-4 text-sm text-red-700"
        >
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="flex-1">员工加载失败 —— 不是没有员工，是没读到。请检查网络后重试</span>
          <button
            type="button"
            data-testid="employees-load-failed-retry"
            onClick={() => void loadEmployees()}
            className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
          >
            重试
          </button>
        </div>
      )}

      {/* 表格 */}
      <PageCard testId="employees-empty">
        <Table<Employee>
          columns={columns}
          dataSource={employees}
          loading={loading}
          rowKey="id"
          /* 🔴 issue #6728：读失败 ⇒ 表体**不得**印「暂无数据」（那是「没有员工」的事实性断言，
             而真相是**没读到**）。共享 `frontend/admin-web/src/components/ui/Table.tsx` 的默认
             `emptyText = '暂无数据'` 是**全站默认值**（改它会波及几十张表）⇒ 本单只在**页面级**覆盖：
             失败时空串（失败原因由上方常驻失败面说），读成功才回落到默认「暂无数据」。 */
          emptyText={loadFailed ? '' : '暂无数据'}
        />
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          totalReliable={!loadFailed}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </PageCard>

      {/* 新增/编辑对话框 */}
      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingEmployee ? '编辑员工' : '新增员工'}
        width={520}
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)} disabled={formLoading}>
              取消
            </Button>
            <Button onClick={handleSubmit} loading={formLoading}>
              {editingEmployee ? '保存' : '创建'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="姓名 *"
            placeholder="请输入姓名"
            value={formData.name}
            onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
          />
          <Input
            label="手机号 *"
            placeholder="请输入手机号"
            value={formData.phone}
            onChange={(e) => setFormData(prev => ({ ...prev, phone: e.target.value }))}
          />
          <Input
            label={editingEmployee ? '登录用户名（留空不改）' : '登录用户名 *'}
            placeholder="员工登录账号，如 zhangsan"
            value={formData.username}
            onChange={(e) => setFormData(prev => ({ ...prev, username: e.target.value }))}
          />
          <Input
            label={editingEmployee ? '重置密码（留空不改）' : '初始密码 *'}
            type="password"
            placeholder={editingEmployee ? '留空则保持原密码' : '请输入初始密码'}
            value={formData.password}
            onChange={(e) => setFormData(prev => ({ ...prev, password: e.target.value }))}
          />
          <p className="-mt-2 text-xs text-neutral-400">
            员工用「<span className="text-neutral-500">用户名@企业编码</span>」+ 密码登录（企业编码见「企业基础信息」）。
            用户名在企业内不能重复；<span className="text-neutral-500">员工首次登录需修改密码</span>后才能使用其他功能。
          </p>
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1">岗位 *</label>
            <Select
              placeholder="请选择岗位"
              options={positionOptions.map(p => ({ value: p.name, label: p.name }))}
              value={formData.position}
              onChange={(e) => handlePositionChange(e.target.value)}
            />
            {positionsError ? (
              /* 🔴 失败态 ≠ 空态（issue #6663）：下拉读不到 ⇒ 必须说出来 + 重试，
                 否则商家只会看到「请选择岗位」却一个选项都没有，且**根本建不出员工**。 */
              <div
                data-testid="employees-positions-error"
                className="mt-1.5 flex items-start gap-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700"
              >
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                <span className="flex-1">岗位清单读取失败 —— 可能是网络或服务暂时不可用</span>
                <button
                  type="button"
                  data-testid="employees-positions-retry"
                  onClick={() => void loadPositions()}
                  className="flex-shrink-0 rounded border border-red-300 px-1.5 py-0.5 font-medium text-red-700 hover:bg-red-100"
                >
                  重新加载
                </button>
              </div>
            ) : (
              <p className="text-xs text-neutral-400 mt-1">选择岗位后自动带出该岗位默认权限，可再手动调整</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-2">账号权限 *</label>
            {menuTree.length > 0 ? (
              <div className="max-h-[360px] overflow-y-auto border border-neutral-200 rounded-lg p-3">
                <TreeCheckbox
                  tree={menuTree}
                  selected={formData.permissions}
                  onChange={(codes) => setFormData(prev => ({ ...prev, permissions: codes }))}
                />
              </div>
            ) : (
              <span className="text-sm text-neutral-400">加载菜单权限中...</span>
            )}
          </div>
          {/* 手机端菜单（2026-10-18 用户：「员工管理里面不能设置手机端的菜单权限？」）——
              手机端入口由**同一批权限码**派生，这里只是把它作为一个可操作的投影面摆出来：
              勾选 = 授予该码（与上方账号权限**同一份**状态，不产生第二套授权）。
              清单与面名**全部来自服务端**（`mobileTitles`），前端不建「码 → 面名」表。 */}
          {mobileMenuEntries.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 mb-2">手机端菜单</label>
              <div
                data-testid="employees-mobile-menus"
                className="grid grid-cols-2 gap-x-3 gap-y-2 rounded-lg border border-neutral-200 p-3"
              >
                {mobileMenuEntries.map(([code, titles]) => (
                  <label key={code} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.permissions.includes(code)}
                      onChange={(e) => setFormData(prev => ({
                        ...prev,
                        permissions: e.target.checked
                          ? (prev.permissions.includes(code) ? prev.permissions : [...prev.permissions, code])
                          : prev.permissions.filter(c => c !== code),
                      }))}
                      className="h-4 w-4 flex-shrink-0 rounded border-neutral-300 text-primary-600 focus:ring-primary-500"
                    />
                    <span className="text-sm text-neutral-600">{titles.join('、')}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-neutral-400 mt-1">
                这部分与上方账号权限是同一份授权：勾选即开通手机端入口，取消即关闭。
              </p>
            </div>
          )}
        </div>
      </Modal>

      {/* 删除确认对话框 */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={handleDelete} loading={deleting}>
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-neutral-600">
          确定要删除员工 <span className="font-medium text-neutral-900">{deleteTarget?.name}</span> 吗？此操作不可撤销。
        </p>
      </Modal>

      {/* 重置密码对话框（#5485：员工忘记密码时的找回路径 —— 本议题不做员工自助找回） */}
      <Modal
        open={!!resetTarget}
        onClose={() => setResetTarget(null)}
        title="重置员工密码"
        footer={
          <>
            <Button variant="secondary" onClick={() => setResetTarget(null)} disabled={resetting}>
              取消
            </Button>
            <Button onClick={handleResetPassword} loading={resetting}>
              确认重置
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-neutral-600">
            为 <span className="font-medium text-neutral-900">{resetTarget?.name}</span> 设置一个新的初始密码。
            重置后请告知员工：<span className="text-neutral-900">下次登录需先修改密码</span>才能使用其他功能。
          </p>
          <Input
            label="新的初始密码 *"
            type="password"
            placeholder="请输入新的初始密码"
            value={resetPasswordValue}
            onChange={(e) => setResetPasswordValue(e.target.value)}
          />
        </div>
      </Modal>
      </div>
      )}
    </div>
  )
}
