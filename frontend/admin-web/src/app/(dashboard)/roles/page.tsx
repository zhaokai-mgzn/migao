'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Pencil, Trash2, Shield } from 'lucide-react'
import { toast } from 'sonner'
import { roleApi, permissionApi } from '@/lib/api'
import { Button, Input, Modal, Badge } from '@/components/ui'
import type { Role, Permission } from '@/types'
import dayjs from 'dayjs'

// 按资源分组权限
function groupPermissionsByResource(permissions: Permission[]): Record<string, Permission[]> {
  const map: Record<string, Permission[]> = {}
  for (const perm of permissions) {
    if (!map[perm.resource]) map[perm.resource] = []
    map[perm.resource].push(perm)
  }
  return map
}

export default function RolesPage() {
  // 角色列表
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
    permissionIds: [] as number[],
  })

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null)
  const [deleting, setDeleting] = useState(false)

  // 加载角色列表
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
    } catch {
      toast.error('加载角色列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 加载权限列表
  const loadPermissions = useCallback(async () => {
    try {
      const res = await permissionApi.getPermissions()
      setAllPermissions(res.data.data || [])
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    loadRoles()
    loadPermissions()
  }, [loadRoles, loadPermissions])

  // 权限分组
  const groupedPermissions = useMemo(
    () => groupPermissionsByResource(allPermissions),
    [allPermissions]
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
    if (!formData.name.trim()) { toast.error('请输入角色名称'); return }
    if (!formData.code.trim()) { toast.error('请输入角色编码'); return }

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
    } catch {
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
    } catch {
      // Error handled by API layer
    } finally {
      setDeleting(false)
    }
  }

  // 权限勾选
  const togglePermission = (permId: number) => {
    setFormData(prev => ({
      ...prev,
      permissionIds: prev.permissionIds.includes(permId)
        ? prev.permissionIds.filter(id => id !== permId)
        : [...prev.permissionIds, permId],
    }))
  }

  // 资源组全选/取消全选
  const toggleResourceGroup = (permissions: Permission[]) => {
    const ids = permissions.map(p => p.id)
    const allSelected = ids.every(id => formData.permissionIds.includes(id))
    if (allSelected) {
      setFormData(prev => ({
        ...prev,
        permissionIds: prev.permissionIds.filter(id => !ids.includes(id)),
      }))
    } else {
      setFormData(prev => ({
        ...prev,
        permissionIds: [...new Set([...prev.permissionIds, ...ids])],
      }))
    }
  }

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">角色权限</h1>
          <p className="text-sm text-gray-500 mt-1">管理系统角色和权限分配</p>
        </div>
        <Button onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1.5" />
          新增角色
        </Button>
      </div>

      {/* 角色列表 - 卡片 */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          <span className="ml-2 text-gray-500">加载中...</span>
        </div>
      ) : roles.length === 0 ? (
        <div className="text-center py-20 text-gray-500">
          暂无角色，点击上方按钮新增
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {roles.map(role => (
            <div
              key={role.id}
              className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center">
                    <Shield className="w-5 h-5 text-primary-600" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900">{role.name}</h3>
                    <p className="text-xs text-gray-400">{role.code}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleEdit(role)}
                    className="p-1.5 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
                    title="编辑"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setDeleteTarget(role)}
                    className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                    title="删除"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {role.description && (
                <p className="text-sm text-gray-500 mb-3 line-clamp-2">{role.description}</p>
              )}

              <div className="flex items-center justify-between text-xs text-gray-400">
                <span>
                  <Badge variant="info">{role.permissions?.length || 0} 个权限</Badge>
                </span>
                <span>{role.createdAt ? dayjs(role.createdAt).format('YYYY-MM-DD') : '-'}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 新增/编辑角色对话框 */}
      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingRole ? '编辑角色' : '新增角色'}
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
            label="角色名称"
            placeholder="例如：管理员、客服"
            value={formData.name}
            onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
          />
          <Input
            label="角色编码"
            placeholder="例如：admin、customer_service"
            value={formData.code}
            onChange={(e) => setFormData(prev => ({ ...prev, code: e.target.value }))}
            disabled={!!editingRole}
          />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">描述</label>
            <textarea
              className="w-full h-20 px-3 py-2 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="角色描述（选填）"
              value={formData.description}
              onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
            />
          </div>

          {/* 权限树 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">权限分配</label>
            {allPermissions.length === 0 ? (
              <p className="text-sm text-gray-400">暂无权限数据</p>
            ) : (
              <div className="border border-gray-200 rounded-lg max-h-[300px] overflow-y-auto">
                {Object.entries(groupedPermissions).map(([resource, perms]) => {
                  const allSelected = perms.every(p => formData.permissionIds.includes(p.id))
                  const someSelected = perms.some(p => formData.permissionIds.includes(p.id))
                  return (
                    <div key={resource} className="border-b border-gray-100 last:border-b-0">
                      {/* 资源组标题 */}
                      <div
                        className="flex items-center gap-2 px-4 py-2.5 bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors"
                        onClick={() => toggleResourceGroup(perms)}
                      >
                        <input
                          type="checkbox"
                          checked={allSelected}
                          ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected }}
                          onChange={() => toggleResourceGroup(perms)}
                          className="w-4 h-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                        />
                        <span className="text-sm font-medium text-gray-700">{resource}</span>
                        <span className="text-xs text-gray-400">({perms.length})</span>
                      </div>
                      {/* 权限项 */}
                      <div className="px-4 py-2 flex flex-wrap gap-x-6 gap-y-2">
                        {perms.map(perm => (
                          <label
                            key={perm.id}
                            className="flex items-center gap-2 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={formData.permissionIds.includes(perm.id)}
                              onChange={() => togglePermission(perm.id)}
                              className="w-4 h-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500"
                            />
                            <span className="text-sm text-gray-600">{perm.name}</span>
                            {perm.description && (
                              <span className="text-xs text-gray-400" title={perm.description}>({perm.action})</span>
                            )}
                          </label>
                        ))}
                      </div>
                    </div>
                  )
                })}
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
        <p className="text-gray-600">
          确定要删除角色 <span className="font-medium text-gray-900">{deleteTarget?.name}</span> 吗？删除后已分配该角色的员工将失去对应权限。
        </p>
      </Modal>
    </div>
  )
}
