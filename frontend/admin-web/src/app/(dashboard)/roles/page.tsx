'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Pencil, Trash2, Shield, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { roleApi, permissionApi, workerPageCatalogApi } from '@/lib/api'
import request from '@/lib/request'
import { Button, Input, Modal, Badge, PageHeader, PageCard } from '@/components/ui'
import type { Role, Permission, WorkerPageCatalogResponse } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
import { formatMobileTitles, mobileTitlesByCodeFromTree } from '@/lib/mobile-surface-label'
// issue #7146：默认菜单 = **后台 + 手机端**（一份权限码集的两面投影，纯函数、无本地字面表）
import { deriveRoleDefaultMenu, roleDefaultMenuSummary } from '@/lib/role-default-menu'
// #3002 权限分配与真实菜单一致：复用侧边栏菜单配置做单一来源，
// 弹窗分组/名称 = 侧边栏菜单分组/菜单项，避免展示旧口径权限目录
import { menuGroups, standaloneHeadItems, standaloneTopItems } from '@/config/menu'

/**
 * 描述超过这个长度才给「展开」（issue #7111）：卡片默认 `line-clamp-2`，短描述本来就不被截断，
 * 给它一个「展开」按钮只是噪音。
 */
const DESCRIPTION_TOGGLE_MIN_CHARS = 60

export default function RolesPage() {
  // 岗位列表
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(false)
  /**
   * 岗位清单**读失败**的显式状态（issue #6663）。
   * 为什么必须有它：改前 catch 只 `toast.error` 而 `roles` 保持 `[]` ⇒ 页面落到「暂无岗位」，
   * **故障被画成业务事实**（商家以为这个企业没有岗位）。范式照抄
   * `src/app/(dashboard)/dashboard/page.tsx` 的失败/空态分离（issue #5792 ④）。
   */
  const [loadError, setLoadError] = useState('')
  /** 权限目录读失败的显式状态 —— 目录读不到 ⇒ 权限树勾不出东西，也不得装作「没有权限可分配」 */
  const [permError, setPermError] = useState('')

  // 所有权限
  const [allPermissions, setAllPermissions] = useState<Permission[]>([])

  /**
   * `权限码 → 手机端可见面中文名`（issue #6759）。
   *
   * 🔴 **它不是第二份真值**：这里**只在运行时持有服务端下发的**标注
   * （`GET /api/admin/menus` 的 `mobileTitles`，服务端由 `MobileSurfaces` 派生），
   * 前端**没有任何**「码 → 手机端面」的常量表（判据 =
   * tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py）。
   * 读不到 ⇒ 空表 ⇒ 权限树照常渲染、只是没有手机端标注（**不阻塞权限分配**）。
   */
  const [mobileTitlesByCode, setMobileTitlesByCode] = useState<Record<string, string[]>>({})

  // 新增/编辑对话框
  const [formOpen, setFormOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    code: '',
    description: '',
    permissionIds: [] as string[],
  })

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null)
  const [deleting, setDeleting] = useState(false)

  /**
   * 岗位**描述展开态**（issue #7111）。
   *
   * 默认描述统一成「职责 + 默认可用模块」后普遍超过卡片的两行（`line-clamp-2`）⇒ 不展开
   * 等于**没写**。口径 = §31 P1「常驻面克制」：默认收起、逐卡按需展开（不把 8 张卡撑高）。
   */
  const [expandedDescriptions, setExpandedDescriptions] = useState<string[]>([])
  const toggleDescription = useCallback((roleId: string) => {
    setExpandedDescriptions(prev =>
      prev.includes(roleId) ? prev.filter(id => id !== roleId) : [...prev, roleId]
    )
  }, [])

  /**
   * 「默认菜单」展开态（issue #7146）。
   *
   * 一个岗位的默认菜单可能 19 项（管理员）⇒ 常驻展开会把 8 张卡撑成一面墙（§31 P1）。
   * 默认收起，只留一行摘要（后台 N 项 · 手机端 M 个入口）。
   */
  const [expandedMenus, setExpandedMenus] = useState<string[]>([])
  const toggleMenu = useCallback((roleId: string) => {
    setExpandedMenus(prev =>
      prev.includes(roleId) ? prev.filter(id => id !== roleId) : [...prev, roleId]
    )
  }, [])

  /** 该岗位的默认权限码（读面回的是权限对象；写面保存的是 ID）。 */
  const codesOfRole = useCallback(
    (role: Role) => (role.permissions || []).map(p => p.code).filter((c): c is string => Boolean(c)),
    [],
  )
  /**
   * 该岗位的「默认菜单」= 后台 + 手机端（issue #7146）。
   * 两面都由同一批权限码派生：后台名取 `@/config/menu`，手机端名只透传服务端 `mobileTitles`。
   */
  const menuOfRole = useCallback(
    (role: Role) => deriveRoleDefaultMenu(codesOfRole(role), mobileTitlesByCode),
    [codesOfRole, mobileTitlesByCode],
  )

  /**
   * 工人端页面目录（issue #7146，用户裁定「加一张只读『工人』卡」）。
   *
   * 工人不是 `roles` 行：`permissions` 恒为 `[]`、后台菜单 0；工人端 5 个页面键由
   * `users.worker_pages` **逐人**收窄（`WorkerPages` 一处真值）。本页只**只读展示**默认全集
   * （页键与人话名都取 `GET /api/admin/worker-pages`，前端不维护第二份词表）。
   */
  const [workerCatalog, setWorkerCatalog] = useState<WorkerPageCatalogResponse | null>(null)
  const [workerCatalogError, setWorkerCatalogError] = useState('')
  const loadWorkerCatalog = useCallback(async () => {
    setWorkerCatalogError('')
    try {
      const res = await workerPageCatalogApi.get()
      const data = res.data.data
      setWorkerCatalog({ pages: data?.pages || [], labels: data?.labels || {} })
    } catch {
      // 🔴 读失败 ≠ 没有页面：工人端页面目录挂生产域读码，缺码 / 网络失败都会走到这里
      setWorkerCatalog(null)
      setWorkerCatalogError('工人端页面目录读取失败 —— 可能是网络或服务暂时不可用')
    }
  }, [])

  // 加载岗位列表
  const loadRoles = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const res = await roleApi.getRoles({ page: 1, size: 100 })
      const data = res.data.data
      // 兼容分页和数组响应
      if (Array.isArray(data)) {
        setRoles(data)
      } else {
        setRoles(data?.items || [])
      }
    } catch (e) {
      // 🔴 读失败 ⇒ 显式失败态（**不要**只 toast 就把清单留空：那会画成「暂无岗位」）
      setLoadError('岗位加载失败 —— 可能是网络或服务暂时不可用')
      toastRequestError(e, '岗位加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  // 加载权限列表
  const loadPermissions = useCallback(async () => {
    setPermError('')
    try {
      const res = await permissionApi.getPermissions()
      const perms = (res.data.data || []) as any[]
      // RBAC 修复：后端字段为 resourceType，roles 页分组/展示用 resource/action 别名
      setAllPermissions(perms.map((p: any) => ({ ...p, resource: p.resource || p.resourceType || 'other' })))
    } catch (e) {
      // 🔴 读失败 ⇒ 显式失败态：权限树会**整片空**，不说出来就与「这个企业没有可分配权限」不可区分
      setPermError('权限目录读取失败 —— 可能是网络或服务暂时不可用')
      toastRequestError(e, '权限目录读取失败，请稍后重试')
    }
  }, [])

  useEffect(() => {
    loadRoles()
    loadPermissions()
    loadWorkerCatalog()
  }, [loadRoles, loadPermissions, loadWorkerCatalog])

  // 手机端可见面标注（issue #6759）：**真值只在服务端**（`MobileSurfaces` 派生自
  // `GET /api/admin/menus` 的 `mobileTitles`）—— 本页只把它挂到对应权限码上，不自造映射。
  //
  // 🔴 issue #6781：一个权限码在树上可以有**多个承载节点**（#5699/#5291 的有意设计面）⇒
  // 这个 `码 → 面` 表**首见优先**（先到先得，后来的同码节点不覆盖）。同一张表要喂给
  // `menuGroups` 与 `standaloneTopItems` 两个梯队，只有首见优先才能保证「每行渲染出的标注
  // 与树序首个承载节点一致」（服务端 `annotateMobileTitles` 也是这个语义；两边同一条规则）。
  useEffect(() => {
    let alive = true
    request.get('/api/admin/menus')
      .then((res: any) => {
        if (!alive) return
        const data = res?.data?.data || res?.data || []
        // 🔴 2026-10-18：改为扫**整棵树**（共享实现 `mobileTitlesByCodeFromTree`）—— 改前只扫
        // `children`，而「经营看板」（`dashboard:view`）自 issue #7087 起是**顶层独立项** ⇒
        // 手机端底栏「数据」从「默认菜单 · 手机端」里静默消失（与员工管理权限列显示英文码同一个口径）。
        setMobileTitlesByCode(mobileTitlesByCodeFromTree(Array.isArray(data) ? data : []))
      })
      // 读不到 ⇒ 权限分配照常可用，只是没有手机端标注（不弹错、不阻塞）
      .catch(() => { if (alive) setMobileTitlesByCode({}) })
    return () => { alive = false }
  }, [])

  // ── #3002 菜单化权限树：分组/名称来自真实侧边栏菜单（menuGroups 单源）──
  // 🔴 #5895：侧边栏是**四个梯队** —— `standaloneHeadItems`（最前席位，issue #7087）→
  // `standaloneTopItems`（尾席位一级项）→ `menuGroups`（分组）→ `standaloneItems`（尾部项）；
  // 权限树必须**同样全接**。#5778 把「商品列表」升为一级项
  // （`standaloneTopItems`：名 =「商品管理」、码 = `product:list`）时只跟了侧边栏与 ⌘K，
  // 本页仍在只遍历 `menuGroups` ⇒ 该项在「权限分配」里**整项消失**（勾都勾不到）。
  // 🔴 2026-10-17（issue #7087）：同一形态在本轮**又出现一次**的入口 = 新增的最前席位
  // `standaloneHeadItems`（「经营看板」，码 `dashboard:view`）—— 必须一并接进权限树，
  // 否则 `dashboard:view` 只能去「操作权限」节勾（菜单名不上树 = 名实不符的同名两处）。
  // 类级判据（新增梯队未接线即红）：tests/unit/pages/roles.test.tsx 的「菜单梯队全部已并入权限树」。

  // 最前席位一级项（`standaloneHeadItems`，如「经营看板」）：与侧边栏同序 —— 渲染在**所有分组之前**
  const headMenuItems = standaloneHeadItems
    .filter(item => item.permissionCode)
    .map(item => ({ code: item.permissionCode!, label: item.name }))

  // 尾席位一级项 → 可勾选菜单项（渲染在**所有分组之前**，与侧边栏同序；无分组头，侧边栏里它也不是分组）
  const topMenuItems = standaloneTopItems
    .filter(item => item.permissionCode)
    .map(item => ({ code: item.permissionCode!, label: item.name }))

  // 菜单组 → 可勾选菜单项（仅带 permissionCode 的菜单项可授予；工作台/通知中心全员可见无码）
  const menuSections = useMemo(
    () =>
      menuGroups
        .map(group => ({
          name: group.name,
          items: group.children
            .filter(item => item.permissionCode)
            .map(item => ({ code: item.permissionCode!, label: item.name })),
        }))
        .filter(section => section.items.length > 0),
    []
  )

  // 权限码 → 权限 ID 列表（roles 保存的是权限 ID，见 RoleService.replaceRolePermissions）
  const codeIds = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const p of allPermissions) {
      if (!p.code) continue
      if (!map[p.code]) map[p.code] = []
      map[p.code].push(p.id)
    }
    return map
  }, [allPermissions])

  // 非菜单操作权限（新增商品/订单详情/新增员工等）：单独一节，避免与菜单树混排
  const menuCodeSet = useMemo(() => {
    const set = new Set<string>()
    menuGroups.forEach(g => g.children.forEach(item => item.permissionCode && set.add(item.permissionCode)))
    // #5895：一级项也是**菜单节点**（「商品管理」= `product:list`）⇒ 同样进白名单，
    // 否则它会掉进「操作权限」节（同名两处、口径混淆）
    standaloneTopItems.forEach(item => item.permissionCode && set.add(item.permissionCode))
    // 🔴 2026-10-17（issue #7087）：最前席位（「经营看板」= `dashboard:view`）同理 ——
    // 它是菜单节点，必须由本树承载可授予性，不得掉进「操作权限」节
    standaloneHeadItems.forEach(item => item.permissionCode && set.add(item.permissionCode))
    return set
  }, [])
  const extraPermissions = useMemo(
    () => allPermissions.filter(p => p.code && p.code !== '*' && !menuCodeSet.has(p.code)),
    [allPermissions, menuCodeSet]
  )

  const isCodeGranted = useCallback(
    (code: string) => {
      const ids = codeIds[code] || []
      return ids.length > 0 && ids.every(id => formData.permissionIds.includes(id))
    },
    [codeIds, formData.permissionIds]
  )

  const toggleCode = useCallback(
    (code: string) => {
      const ids = codeIds[code] || []
      setFormData(prev => {
        const granted = ids.length > 0 && ids.every(id => prev.permissionIds.includes(id))
        return {
          ...prev,
          permissionIds: granted
            ? prev.permissionIds.filter(id => !ids.includes(id))
            : [...new Set([...prev.permissionIds, ...ids])],
        }
      })
    },
    [codeIds]
  )

  // 菜单项行（权限树里**所有**菜单节点共用同一份渲染：一级项 / 组内项）—— 勾选即授予该权限码
  //
  // 🔴 issue #6770（§31 P3「不摆内部标识」）：权限码**不上商家可见面**（原形态是把 `inbound:view`
  // 这样的内部串直接印在行尾）。它与左侧菜单名（label）表达同一件事、对商家零信息量，而同族先例
  // （issue #6669 第 6 条：403 页撤掉权限码回显）已按「看不懂也无从行动」处理过。
  // 保留**非可见面**两个入口（不降可及性）：① hover 的 `title`；② 屏幕阅读器可见的 `sr-only` 文本
  // （它同时让 label 的 accessible name 含码，故**不**另加 `aria-label` —— 那会遮蔽可见名）。
  const renderCodeItem = (code: string, label: string) => {
    const mobile = formatMobileTitles(mobileTitlesByCode[code])
    return (
      <label key={`${code}-${label}`} className="flex items-center gap-2 cursor-pointer" title={code}>
        <input
          type="checkbox"
          checked={isCodeGranted(code)}
          onChange={() => toggleCode(code)}
          className="w-4 h-4 text-primary-600 rounded border-neutral-300 focus:ring-primary-500"
        />
        <span className="text-sm text-neutral-600">
          {label}
          {mobile && (
            <span className="text-xs text-neutral-400" data-testid={`roles-mobile-${code}`}>
              {mobile}
            </span>
          )}
          <span className="sr-only" data-testid={`roles-code-${code}`}>{code}</span>
        </span>
      </label>
    )
  }

  // 菜单组全选/取消全选（组内权限码去重后一并授予/移除）
  const toggleMenuGroup = useCallback(
    (codes: string[]) => {
      setFormData(prev => {
        const allGranted = codes.every(code => {
          const ids = codeIds[code] || []
          return ids.length > 0 && ids.every(id => prev.permissionIds.includes(id))
        })
        const ids = codes.flatMap(code => codeIds[code] || [])
        return {
          ...prev,
          permissionIds: allGranted
            ? prev.permissionIds.filter(id => !ids.includes(id))
            : [...new Set([...prev.permissionIds, ...ids])],
        }
      })
    },
    [codeIds]
  )

  // 打开新增对话框
  const handleAdd = () => {
    setEditingRole(null)
    setFormData({ name: '', code: '', description: '', permissionIds: [] })
    setFormOpen(true)
  }

  // 打开编辑对话框
  const handleEdit = (role: Role) => {
    setEditingRole(role)
    setFormData({
      name: role.name,
      code: role.code,
      description: role.description || '',
      permissionIds: role.permissions?.map(p => p.id) || [],
    })
    setFormOpen(true)
  }

  // 提交表单
  const handleSubmit = async () => {
    if (!formData.name.trim()) { toast.error('请输入岗位名称'); return }
    if (!formData.code.trim()) { toast.error('请输入岗位编码'); return }

    setFormLoading(true)
    try {
      if (editingRole) {
        await roleApi.updateRole(editingRole.id, {
          name: formData.name,
          code: formData.code,
          description: formData.description || undefined,
          permissionIds: formData.permissionIds,
        })
        toast.success('编辑成功')
      } else {
        await roleApi.createRole({
          name: formData.name,
          code: formData.code,
          description: formData.description || undefined,
          permissionIds: formData.permissionIds,
        })
        toast.success('创建成功')
      }
      setFormOpen(false)
      loadRoles()
    } catch (e) {
      // Error handled by API layer
    } finally {
      setFormLoading(false)
    }
  }

  // 删除
  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await roleApi.deleteRole(deleteTarget.id)
      toast.success('删除成功')
      setDeleteTarget(null)
      loadRoles()
    } catch (e) {
      // Error handled by API layer
    } finally {
      setDeleting(false)
    }
  }

  // 权限勾选（操作权限项：按权限 ID）
  const togglePermission = (permId: string) => {
    setFormData(prev => ({
      ...prev,
      permissionIds: prev.permissionIds.includes(permId)
        ? prev.permissionIds.filter(id => id !== permId)
        : [...prev.permissionIds, permId],
    }))
  }

  return (
    <div className="p-6 space-y-4">
      {/* 页面标题 */}
      <PageHeader
        title="岗位权限"
        subtitle="管理岗位及默认权限"
        actions={
          <Button onClick={handleAdd}>
            <Plus className="w-4 h-4 mr-1.5" />
            新增岗位
          </Button>
        }
      />

      {/* 岗位列表 - 卡片 */}
      <PageCard padded={false}>
      {loadError ? (
        /* 🔴 失败态 ≠ 空态（issue #6663）：说清「不是没有岗位，是读不到」+ 给重试出口。
           范式：`src/app/(dashboard)/dashboard/page.tsx` 的 `dashboard-load-failed`。 */
        <div
          data-testid="roles-load-error"
          className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="flex-1">
            岗位加载失败 —— 可能是网络或服务暂时不可用。这不是「没有岗位」：读不到时清单不该显示成空。
          </span>
          <button
            type="button"
            onClick={() => void loadRoles()}
            className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
          >
            重新加载
          </button>
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          <span className="ml-2 text-neutral-500">加载中...</span>
        </div>
      ) : roles.length === 0 ? (
        <div className="text-center py-20 text-neutral-500">
          暂无岗位，点击上方按钮新增
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {roles.map(role => (
            <div
              key={role.id}
              className="bg-white rounded-lg border border-neutral-200 shadow-card p-5 hover:shadow-card-hover transition-shadow"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center">
                    <Shield className="w-5 h-5 text-primary-600" />
                  </div>
                  <div>
                    <h3 className="font-medium text-neutral-900">{role.name}</h3>
                    <p className="text-xs text-neutral-400">{role.code}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleEdit(role)}
                    className="p-1.5 text-neutral-400 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
                    title="编辑"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setDeleteTarget(role)}
                    className="p-1.5 text-neutral-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                    title="删除"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {role.description && (
                <div className="mb-3">
                  <p
                    data-testid={`role-description-${role.code}`}
                    className={`text-sm text-neutral-500 ${
                      expandedDescriptions.includes(role.id) ? '' : 'line-clamp-2'
                    }`}
                  >
                    {role.description}
                  </p>
                  {/* 只有会被 clamp 截断的长描述才给「展开」——短描述给按钮只是噪音 */}
                  {role.description.length > DESCRIPTION_TOGGLE_MIN_CHARS && (
                    <button
                      type="button"
                      onClick={() => toggleDescription(role.id)}
                      aria-expanded={expandedDescriptions.includes(role.id)}
                      data-testid={`role-description-toggle-${role.code}`}
                      className="mt-1 text-xs text-primary-600 hover:underline"
                    >
                      {expandedDescriptions.includes(role.id) ? '收起' : '展开'}
                    </button>
                  )}
                </div>
              )}

              {/* issue #7146：默认菜单 = **后台 + 手机端**（同一批权限码的两面投影）。默认收起（§31 P1）。 */}
              {(() => {
                const menu = menuOfRole(role)
                const expanded = expandedMenus.includes(role.id)
                return (
                  <div className="mb-3" data-testid={`role-default-menu-${role.code}`}>
                    <button
                      type="button"
                      onClick={() => toggleMenu(role.id)}
                      aria-expanded={expanded}
                      className="text-xs text-neutral-500 hover:text-primary-600"
                    >
                      <span data-testid={`role-default-menu-summary-${role.code}`}>
                        {roleDefaultMenuSummary(menu)}
                      </span>
                      <span className="ml-1 text-primary-600">{expanded ? '收起' : '展开'}</span>
                    </button>
                    {expanded && (
                      <div className="mt-1 space-y-0.5 text-xs text-neutral-500">
                        <p data-testid={`role-default-menu-backend-${role.code}`}>
                          后台：{menu.backend.join('、') || '无'}
                        </p>
                        <p data-testid={`role-default-menu-mobile-${role.code}`}>
                          手机端：{menu.mobile.join('、') || '无'}
                        </p>
                      </div>
                    )}
                  </div>
                )
              })()}

              <div className="flex items-center justify-between text-xs text-neutral-400">
                <span>
                  <Badge variant="info">{role.permissions?.length || 0} 个权限</Badge>
                </span>
                <DateTimeCell value={role.createdAt} />
              </div>
            </div>
          ))}
        </div>
      )}
      </PageCard>

      {/*
        工人端菜单（issue #7146，用户 2026-10-17 裁定「加一张只读『工人』卡」）。

        🔴 工人**不是** `roles` 行：`permissions` 恒为 `[]`、无后台菜单；工人端页面键由
        `users.worker_pages` **逐人**收窄（`WorkerPages` 一处真值，issue #6788/#6828）
        ⇒ 这里**只读展示**默认全集，配置出口在「员工管理 → 工人档案」。
        页键与人话名都取服务端 `GET /api/admin/worker-pages`（前端不维护第二份词表）。
      */}
      <PageCard>
        <div data-testid="worker-menu-card">
          <div className="flex items-start justify-between gap-3 mb-2">
            <div>
              <h3 className="font-medium text-neutral-900">工人</h3>
              <p className="text-xs text-neutral-400">工人端身份（用工号 + PIN 登录，不进管理后台）</p>
            </div>
            <Badge variant="info">只读</Badge>
          </div>

          {workerCatalogError ? (
            /* 🔴 失败态 ≠ 空态：读不到目录 ≠ 工人端没有页面（同页岗位清单失败态的口径，issue #6663） */
            <div
              data-testid="worker-menu-error"
              className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span className="flex-1">
                工人端页面目录读取失败 —— 这不是「没有页面」：读不到时清单不该显示成空。
              </span>
              <button
                type="button"
                onClick={() => void loadWorkerCatalog()}
                className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
              >
                重试
              </button>
            </div>
          ) : workerCatalog === null ? (
            <p className="text-xs text-neutral-400">加载中...</p>
          ) : (
            <>
              <p className="text-xs text-neutral-400 mb-1">
                工人端菜单（默认全部 {workerCatalog.pages.length} 页，逐人可收窄）
              </p>
              <div data-testid="worker-menu-pages" className="flex flex-wrap gap-2">
                {workerCatalog.pages.map(key => (
                  <span
                    key={key}
                    className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs text-neutral-600"
                  >
                    {workerCatalog.labels?.[key] || key}
                  </span>
                ))}
              </div>
            </>
          )}

          <a href="/employees" className="mt-2 inline-block text-xs text-primary-600 hover:underline">
            在「员工管理 → 工人档案」逐人配置
          </a>
        </div>
      </PageCard>

      {/* 新增/编辑岗位对话框 */}
      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingRole ? '编辑岗位' : '新增岗位'}
        width={640}
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)} disabled={formLoading}>
              取消
            </Button>
            <Button onClick={handleSubmit} loading={formLoading}>
              {editingRole ? '保存' : '创建'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="岗位名称"
            placeholder="例如：管理员、客服"
            value={formData.name}
            onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
          />
          <Input
            label="岗位编码"
            placeholder="例如：admin、customer_service"
            value={formData.code}
            onChange={(e) => setFormData(prev => ({ ...prev, code: e.target.value }))}
            disabled={!!editingRole}
          />
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">描述</label>
            <textarea
              className="w-full h-20 px-3 py-2 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="岗位描述（选填）"
              value={formData.description}
              onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
            />
          </div>

          {/* 权限树 */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-2">权限分配</label>
            {permError ? (
              /* 🔴 失败态 ≠ 空态（issue #6663）：目录读不到时权限树整片空，若不说明就与
                 「这个企业没有可分配的权限」不可区分 —— 而这是**两个完全不同**的处境。 */
              <div
                data-testid="roles-permissions-error"
                className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span className="flex-1">权限目录读取失败 —— 可能是网络或服务暂时不可用</span>
                <button
                  type="button"
                  onClick={() => void loadPermissions()}
                  className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
                >
                  重新加载
                </button>
              </div>
            ) : allPermissions.length === 0 ? (
              <p className="text-sm text-neutral-400">暂无权限数据</p>
            ) : (
              <div className="border border-neutral-200 rounded-lg max-h-[300px] overflow-y-auto" data-testid="perm-menu-sections">
                {/* 最前席位一级项（`standaloneHeadItems`，如「经营看板」，issue #7087）：与侧边栏同序 ——
                    渲染在**所有分组之前**、无分组头（侧边栏里它也不是分组） */}
                {headMenuItems.length > 0 && (
                  <div className="border-b border-neutral-100 px-4 py-2 flex flex-wrap gap-x-6 gap-y-2" data-testid="perm-standalone-head">
                    {headMenuItems.map(item => renderCodeItem(item.code, item.label))}
                  </div>
                )}
                {/* #5895 一级项（`standaloneTopItems`，如「商品管理」）：与侧边栏同序 ——
                    渲染在**所有分组之前**、无分组头（侧边栏里它也不是分组） */}
                {topMenuItems.length > 0 && (
                  <div className="border-b border-neutral-100 px-4 py-2 flex flex-wrap gap-x-6 gap-y-2" data-testid="perm-standalone-top">
                    {topMenuItems.map(item => renderCodeItem(item.code, item.label))}
                  </div>
                )}
                {/* #3002 菜单化权限树：分组/名称与真实侧边栏菜单一致（menuGroups 单源） */}
                {menuSections.map(section => {
                  const codes = [...new Set(section.items.map(i => i.code))]
                  const allSelected = codes.every(c => isCodeGranted(c))
                  const someSelected = codes.some(c => isCodeGranted(c))
                  return (
                    <div key={section.name} className="border-b border-neutral-100 last:border-b-0">
                      {/* 菜单组标题（= 侧边栏菜单组名） */}
                      <div
                        className="flex items-center gap-2 px-4 py-2.5 bg-neutral-50 cursor-pointer hover:bg-neutral-100 transition-colors"
                        onClick={() => toggleMenuGroup(codes)}
                      >
                        <input
                          type="checkbox"
                          checked={allSelected}
                          ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected }}
                          onChange={() => toggleMenuGroup(codes)}
                          onClick={(e) => e.stopPropagation()}
                          className="w-4 h-4 text-primary-600 rounded border-neutral-300 focus:ring-primary-500"
                        />
                        <span className="text-sm font-medium text-neutral-700">{section.name}</span>
                        <span className="text-xs text-neutral-400">({codes.length}项)</span>
                      </div>
                      {/* 菜单项（= 侧边栏菜单项名，勾选即授予对应权限码） */}
                      <div className="px-4 py-2 flex flex-wrap gap-x-6 gap-y-2">
                        {section.items.map(item => renderCodeItem(item.code, item.label))}
                      </div>
                    </div>
                  )
                })}
                {/* 非菜单操作权限（新增商品/订单详情/新增员工等，不直接对应菜单入口） */}
                {extraPermissions.length > 0 && (
                  <div className="border-b border-neutral-100 last:border-b-0" data-testid="perm-extra-section">
                    <div className="flex items-center gap-2 px-4 py-2.5 bg-neutral-50">
                      <span className="text-sm font-medium text-neutral-700">操作权限</span>
                      <span className="text-xs text-neutral-400">（不直接对应菜单入口）({extraPermissions.length})</span>
                    </div>
                    <div className="px-4 py-2 flex flex-wrap gap-x-6 gap-y-2">
                      {extraPermissions.map(perm => (
                        <label key={perm.id} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={formData.permissionIds.includes(perm.id)}
                            onChange={() => togglePermission(perm.id)}
                            className="w-4 h-4 text-primary-600 rounded border-neutral-300 focus:ring-primary-500"
                          />
                          <span className="text-sm text-neutral-600">{perm.name}</span>
                          {perm.description && (
                            <span className="text-xs text-neutral-400" title={perm.description}>({perm.action})</span>
                          )}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
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
          确定要删除岗位 <span className="font-medium text-neutral-900">{deleteTarget?.name}</span> 吗？删除后已分配该岗位的员工将失去对应权限。
        </p>
      </Modal>
    </div>
  )
}
