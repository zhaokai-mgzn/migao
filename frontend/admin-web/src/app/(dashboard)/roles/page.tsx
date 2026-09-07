'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Pencil, Trash2, Shield } from 'lucide-react'
import { toast } from 'sonner'
import { roleApi, permissionApi } from '@/lib/api'
import { Button, Input, Modal, Badge } from '@/components/ui'
import type { Role, Permission } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
// #3002 权限分配与真实菜单一致：复用侧边栏菜单配置做单一来源，
// 弹窗分组/名称 = 侧边栏菜单分组/菜单项，避免展示旧口径权限目录
import { menuGroups } from '@/config/menu'

export default function RolesPage() {
  // 岗位列表
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(false)

  // 所有权限
  const [allPermissions, setAllPermissions] = useState<Permission[]>([])

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

  // 加载岗位列表
  const loadRoles = useCallback(async () => {
    setLoading(true)
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
      toast.error('加载岗位列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 加载权限列表
  const loadPermissions = useCallback(async () => {
    try {
      const res = await permissionApi.getPermissions()
      const perms = (res.data.data || []) as any[]
      // RBAC 修复：后端字段为 resourceType，roles 页分组/展示用 resource/action 别名
      setAllPermissions(perms.map((p: any) => ({ ...p, resource: p.resource || p.resourceType || 'other' })))
    } catch (e) {
      // ignore
    }
  }, [])

  useEffect(() => {
    loadRoles()
    loadPermissions()
  }, [loadRoles, loadPermissions])

  // ── #3002 菜单化权限树：分组/名称来自真实侧边栏菜单（menuGroups 单源）──

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
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">岗位权限</h1>
          <p className="text-sm text-neutral-500 mt-1">管理岗位及默认权限</p>
        </div>
        <Button onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1.5" />
          新增岗位
        </Button>
      </div>

      {/* 岗位列表 - 卡片 */}
      {loading ? (
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
              className="bg-white rounded-lg border border-neutral-200 p-5 hover:shadow-md transition-shadow"
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
                <p className="text-sm text-neutral-500 mb-3 line-clamp-2">{role.description}</p>
              )}

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
            {allPermissions.length === 0 ? (
              <p className="text-sm text-neutral-400">暂无权限数据</p>
            ) : (
              <div className="border border-neutral-200 rounded-lg max-h-[300px] overflow-y-auto" data-testid="perm-menu-sections">
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
                        {section.items.map(item => (
                          <label
                            key={`${section.name}-${item.label}`}
                            className="flex items-center gap-2 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={isCodeGranted(item.code)}
                              onChange={() => toggleCode(item.code)}
                              className="w-4 h-4 text-primary-600 rounded border-neutral-300 focus:ring-primary-500"
                            />
                            <span className="text-sm text-neutral-600">{item.label}</span>
                            <span className="text-xs text-neutral-400" title={item.code}>{item.code}</span>
                          </label>
                        ))}
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
